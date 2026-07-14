import base64
import hashlib
import time

import pytest

from auth.msal_client import (
    MSALAuthenticationError,
    MSALClient,
    generate_pkce_pair,
)


@pytest.fixture
def mock_cca(mocker):
    cca = mocker.MagicMock()
    cca._decorate_scope.side_effect = lambda scopes: scopes + ["openid", "profile"]
    cca.client.build_auth_request_uri.return_value = (
        "https://login.microsoftonline.com/tenant/oauth2/v2.0/authorize?mock=1"
    )
    return cca


@pytest.fixture
def client(mock_cca):
    return MSALClient(
        tenant_id="test-tenant",
        client_id="test-client-id",
        client_secret="test-secret",
        redirect_uri="https://app.example/callback",
        scopes=["User.Read"],
        app=mock_cca,
    )


class TestGeneratePkce:
    def test_verifier_length_and_charset(self):
        pair = generate_pkce_pair(length=64)
        assert len(pair.code_verifier) == 64
        assert all(c in pair.code_verifier for c in pair.code_verifier)

    def test_challenge_is_s256_of_verifier(self):
        pair = generate_pkce_pair()
        expected = (
            base64.urlsafe_b64encode(
                hashlib.sha256(pair.code_verifier.encode("ascii")).digest()
            )
            .rstrip(b"=")
            .decode("ascii")
        )
        assert pair.code_challenge == expected
        assert pair.code_challenge_method == "S256"

    def test_rejects_invalid_length(self):
        with pytest.raises(ValueError, match="43 and 128"):
            generate_pkce_pair(length=42)


class TestMSALClientAuthorization:
    def test_requires_client_secret(self):
        with pytest.raises(ValueError, match="ENTRA_CLIENT_SECRET"):
            MSALClient(
                tenant_id="test-tenant",
                client_id="test-client-id",
                client_secret="",
                redirect_uri="https://app.example/callback",
                scopes=["User.Read"],
            )

    def test_generate_pkce_stores_pair_on_client(self, client):
        pair = client.generate_pkce()
        assert client.pkce is pair
        assert pair.code_challenge_method == "S256"

    def test_build_authorization_url_without_pkce_for_confidential_client(
        self, client, mock_cca
    ):
        url = client.build_authorization_url(state="csrf-state")

        assert url.startswith("https://login.microsoftonline.com")
        call_kwargs = mock_cca.client.build_auth_request_uri.call_args.kwargs
        assert "code_challenge" not in call_kwargs
        assert "code_challenge_method" not in call_kwargs

    def test_build_authorization_url_includes_pkce_and_state(self, client, mock_cca):
        pkce = client.generate_pkce()
        url = client.build_authorization_url(state="csrf-state")

        assert url.startswith("https://login.microsoftonline.com")
        assert client.auth_state == "csrf-state"
        mock_cca._decorate_scope.assert_called_once_with(["User.Read"])
        mock_cca.client.build_auth_request_uri.assert_called_once_with(
            "code",
            redirect_uri="https://app.example/callback",
            scope=["User.Read", "openid", "profile"],
            state="csrf-state",
            login_hint=None,
            code_challenge=pkce.code_challenge,
            code_challenge_method="S256",
        )

    def test_build_authorization_url_generates_state_when_omitted(
        self, client, mock_cca
    ):
        client.generate_pkce()
        client.build_authorization_url()

        assert client.auth_state is not None
        call_kwargs = mock_cca.client.build_auth_request_uri.call_args.kwargs
        assert call_kwargs["state"] == client.auth_state


class TestMSALClientTokenExchange:
    def test_state_bound_pkce_uses_matching_verifier(self, client, mock_cca):
        mock_cca.acquire_token_by_authorization_code.return_value = {
            "access_token": "access-123",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_cca.get_accounts.return_value = [{"username": "user@contoso.com"}]

        client.generate_pkce()
        client.build_authorization_url(state="state-1")
        client.generate_pkce()
        client.build_authorization_url(state="state-2")

        client.exchange_authorization_code("code-1", state="state-1")
        client.exchange_authorization_code("code-2", state="state-2")

        first_call = mock_cca.acquire_token_by_authorization_code.call_args_list[0].kwargs
        second_call = mock_cca.acquire_token_by_authorization_code.call_args_list[1].kwargs
        assert first_call["code_verifier"]
        assert second_call["code_verifier"]
        assert first_call["code_verifier"] != second_call["code_verifier"]

    def test_exchange_authorization_code_success(self, client, mock_cca):
        client.generate_pkce()
        token_response = {
            "access_token": "access-123",
            "refresh_token": "refresh-456",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_cca.acquire_token_by_authorization_code.return_value = token_response
        mock_cca.get_accounts.return_value = [{"username": "user@contoso.com"}]

        result = client.exchange_authorization_code("auth-code-xyz")

        assert result == token_response
        mock_cca.acquire_token_by_authorization_code.assert_called_once_with(
            "auth-code-xyz",
            scopes=["User.Read"],
            redirect_uri="https://app.example/callback",
            code_verifier=client.pkce.code_verifier,
        )

    def test_exchange_authorization_code_raises_on_msal_error(
        self, client, mock_cca
    ):
        client.generate_pkce()
        mock_cca.acquire_token_by_authorization_code.return_value = {
            "error": "invalid_grant",
            "error_description": "Code expired",
        }

        with pytest.raises(MSALAuthenticationError, match="Code expired"):
            client.exchange_authorization_code("bad-code")

    def test_exchange_without_pkce_for_confidential_client(self, client, mock_cca):
        token_response = {
            "access_token": "access-123",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_cca.acquire_token_by_authorization_code.return_value = token_response
        mock_cca.get_accounts.return_value = [{"username": "user@contoso.com"}]

        result = client.exchange_authorization_code("code")

        assert result == token_response
        mock_cca.acquire_token_by_authorization_code.assert_called_once_with(
            "code",
            scopes=["User.Read"],
            redirect_uri="https://app.example/callback",
        )


class TestMSALClientSilentRefresh:
    def test_returns_cached_token_when_not_expired(self, client, mock_cca, mocker):
        client.generate_pkce()
        mock_cca.acquire_token_by_authorization_code.return_value = {
            "access_token": "cached-token",
            "expires_on": int(time.time()) + 3600,
        }
        mock_cca.get_accounts.return_value = [{"username": "user@contoso.com"}]
        client.exchange_authorization_code("code")

        result = client.get_valid_access_token()

        assert result["access_token"] == "cached-token"
        mock_cca.acquire_token_silent.assert_not_called()

    def test_silent_refresh_when_token_expired(self, client, mock_cca):
        client.generate_pkce()
        mock_cca.acquire_token_by_authorization_code.return_value = {
            "access_token": "old-token",
            "expires_on": int(time.time()) - 10,
        }
        mock_cca.get_accounts.return_value = [{"username": "user@contoso.com"}]
        client.exchange_authorization_code("code")

        refreshed = {
            "access_token": "new-token",
            "expires_on": int(time.time()) + 3600,
        }
        mock_cca.acquire_token_silent.return_value = refreshed

        result = client.get_valid_access_token()

        assert result["access_token"] == "new-token"
        mock_cca.acquire_token_silent.assert_called_once_with(
            ["User.Read"],
            account={"username": "user@contoso.com"},
            force_refresh=False,
        )

    def test_force_refresh_skips_cache(self, client, mock_cca):
        client.generate_pkce()
        mock_cca.acquire_token_by_authorization_code.return_value = {
            "access_token": "cached-token",
            "expires_on": int(time.time()) + 3600,
        }
        mock_cca.get_accounts.return_value = [{"username": "user@contoso.com"}]
        client.exchange_authorization_code("code")

        mock_cca.acquire_token_silent.return_value = {
            "access_token": "forced-token",
            "expires_on": int(time.time()) + 3600,
        }

        result = client.get_valid_access_token(force_refresh=True)

        assert result["access_token"] == "forced-token"
        mock_cca.acquire_token_silent.assert_called_once_with(
            ["User.Read"],
            account={"username": "user@contoso.com"},
            force_refresh=True,
        )

    def test_silent_refresh_failure_raises(self, client, mock_cca):
        client.generate_pkce()
        mock_cca.acquire_token_by_authorization_code.return_value = {
            "access_token": "old-token",
            "expires_on": int(time.time()) - 10,
        }
        mock_cca.get_accounts.return_value = [{"username": "user@contoso.com"}]
        client.exchange_authorization_code("code")
        mock_cca.acquire_token_silent.return_value = None

        with pytest.raises(RuntimeError, match="Silent token refresh failed"):
            client.get_valid_access_token()

    def test_get_valid_access_token_requires_authentication(self, client):
        with pytest.raises(RuntimeError, match="No authenticated session"):
            client.get_valid_access_token()
