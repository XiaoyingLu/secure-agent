import time
from typing import Any

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, Request
from jwt.algorithms import RSAAlgorithm
from starlette.testclient import TestClient

from auth.token_validator import (
    INVALID_TOKEN_BODY,
    EntraJWTMiddleware,
    EntraJWTValidator,
)

TEST_TENANT = "test-tenant"
TEST_CLIENT_ID = "test-client-id"
TEST_ISSUER = f"https://login.microsoftonline.com/{TEST_TENANT}/v2.0"
TEST_KID = "unit-test-key"
TEST_JWKS_URL = f"https://login.microsoftonline.com/{TEST_TENANT}/discovery/v2.0/keys"


@pytest.fixture(scope="module")
def rsa_keypair() -> tuple[Any, dict[str, Any]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    jwk = RSAAlgorithm.to_jwk(public_key, as_dict=True)
    jwk.update({"kid": TEST_KID, "use": "sig", "alg": "RS256"})
    return private_key, jwk


@pytest.fixture
def mock_http(mocker, rsa_keypair):
    _, jwk = rsa_keypair
    client = mocker.AsyncMock(spec=httpx.AsyncClient)
    response = mocker.MagicMock()
    response.raise_for_status = mocker.MagicMock()
    response.json.return_value = {"keys": [jwk]}
    client.get.return_value = response
    return client


@pytest.fixture
def validator(mock_http):
    return EntraJWTValidator(
        tenant_id=TEST_TENANT,
        client_id=TEST_CLIENT_ID,
        issuer=TEST_ISSUER,
        jwks_url=TEST_JWKS_URL,
        jwks_ttl_seconds=3600,
        http_client=mock_http,
    )


def _encode_token(
    private_key: Any,
    claims: dict[str, Any],
    *,
    kid: str = TEST_KID,
) -> str:
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return jwt.encode(
        claims,
        pem,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _valid_claims(**overrides: Any) -> dict[str, Any]:
    now = int(time.time())
    base = {
        "iss": TEST_ISSUER,
        "aud": TEST_CLIENT_ID,
        "sub": "user-123",
        "exp": now + 3600,
        "nbf": now - 60,
        "iat": now,
        "preferred_username": "user@contoso.com",
    }
    base.update(overrides)
    return base


@pytest.fixture
def protected_app(validator):
    app = FastAPI()
    app.add_middleware(
        EntraJWTMiddleware,
        tenant_id=TEST_TENANT,
        client_id=TEST_CLIENT_ID,
        validator=validator,
        exclude_paths=frozenset(),
    )

    @app.get("/protected")
    async def protected(request: Request):
        return {"sub": request.state.user["sub"]}

    return app


class TestEntraJWTValidator:
    @pytest.mark.asyncio
    async def test_validate_token_success(self, validator, rsa_keypair, mock_http):
        private_key, _ = rsa_keypair
        token = _encode_token(private_key, _valid_claims())

        claims = await validator.validate_token(token)

        assert claims["sub"] == "user-123"
        mock_http.get.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_jwks_cached_for_one_hour(self, validator, rsa_keypair, mock_http):
        private_key, _ = rsa_keypair
        await validator.validate_token(_encode_token(private_key, _valid_claims()))
        await validator.validate_token(_encode_token(private_key, _valid_claims()))

        assert mock_http.get.await_count == 1

    @pytest.mark.asyncio
    async def test_jwks_refetched_after_ttl(self, validator, rsa_keypair, mock_http):
        validator.jwks_ttl_seconds = 1
        private_key, _ = rsa_keypair

        # Initial fetch
        await validator.validate_token(_encode_token(private_key, _valid_claims()))
        assert mock_http.get.await_count == 1

        # Expire cache manually
        validator._jwks_fetched_at = time.time() - 2

        # Second fetch should trigger another HTTP GET
        await validator.validate_token(_encode_token(private_key, _valid_claims()))
        assert mock_http.get.await_count == 2

    @pytest.mark.asyncio
    async def test_expired_token_raises(self, validator, rsa_keypair):
        private_key, _ = rsa_keypair
        token = _encode_token(
            private_key,
            _valid_claims(exp=int(time.time()) - 10),
        )

        with pytest.raises(jwt.ExpiredSignatureError):
            await validator.validate_token(token)

    @pytest.mark.asyncio
    async def test_invalid_issuer_raises(self, validator, rsa_keypair):
        private_key, _ = rsa_keypair
        token = _encode_token(
            private_key,
            _valid_claims(iss="https://evil.example/wrong"),
        )

        with pytest.raises(jwt.InvalidIssuerError):
            await validator.validate_token(token)

    @pytest.mark.asyncio
    async def test_invalid_audience_raises(self, validator, rsa_keypair):
        private_key, _ = rsa_keypair
        token = _encode_token(
            private_key,
            _valid_claims(aud="wrong-audience"),
        )

        with pytest.raises(jwt.InvalidAudienceError):
            await validator.validate_token(token)

    @pytest.mark.asyncio
    async def test_nbf_in_future_raises(self, validator, rsa_keypair):
        private_key, _ = rsa_keypair
        token = _encode_token(
            private_key,
            _valid_claims(nbf=int(time.time()) + 600),
        )

        with pytest.raises(jwt.ImmatureSignatureError):
            await validator.validate_token(token)

    @pytest.mark.asyncio
    async def test_invalid_signature_raises(self, validator, rsa_keypair):
        other_private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        token = _encode_token(other_private, _valid_claims())

        with pytest.raises(jwt.InvalidSignatureError):
            await validator.validate_token(token)

    @pytest.mark.asyncio
    async def test_unknown_kid_refreshes_jwks_once(self, validator, rsa_keypair, mock_http):
        private_key, _ = rsa_keypair
        token = _encode_token(private_key, _valid_claims(), kid="unknown-kid")

        with pytest.raises(ValueError, match="Signing key not found"):
            await validator.validate_token(token)

        assert mock_http.get.await_count == 2


class TestEntraJWTMiddleware:
    def test_valid_token_sets_request_state_user(self, protected_app, rsa_keypair):
        private_key, _ = rsa_keypair
        token = _encode_token(private_key, _valid_claims())

        with TestClient(protected_app) as client:
            response = client.get(
                "/protected",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 200
        assert response.json() == {"sub": "user-123"}

    def test_cookie_token_sets_request_state_user(self, protected_app, rsa_keypair):
        private_key, _ = rsa_keypair
        token = _encode_token(private_key, _valid_claims())

        with TestClient(protected_app) as client:
            client.cookies.set("secure_agent_access_token", token)
            response = client.get("/protected")

        assert response.status_code == 200
        assert response.json() == {"sub": "user-123"}

    def test_missing_authorization_returns_401(self, protected_app):
        with TestClient(protected_app) as client:
            response = client.get("/protected")

        assert response.status_code == 401
        assert response.json() == INVALID_TOKEN_BODY

    def test_expired_token_returns_401(self, protected_app, rsa_keypair):
        private_key, _ = rsa_keypair
        token = _encode_token(
            private_key,
            _valid_claims(exp=int(time.time()) - 10),
        )

        with TestClient(protected_app) as client:
            response = client.get(
                "/protected",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 401
        assert response.json() == INVALID_TOKEN_BODY

    def test_wrong_issuer_returns_401(self, protected_app, rsa_keypair):
        private_key, _ = rsa_keypair
        token = _encode_token(
            private_key,
            _valid_claims(iss="https://wrong-issuer.example"),
        )

        with TestClient(protected_app) as client:
            response = client.get(
                "/protected",
                headers={"Authorization": f"Bearer {token}"},
            )

        assert response.status_code == 401
        assert response.json() == INVALID_TOKEN_BODY

    def test_excluded_path_skips_validation(self, validator):
        app = FastAPI()
        app.add_middleware(
            EntraJWTMiddleware,
            tenant_id=TEST_TENANT,
            client_id=TEST_CLIENT_ID,
            validator=validator,
            exclude_paths=frozenset({"/public"}),
        )

        @app.get("/public")
        async def public():
            return {"ok": True}

        with TestClient(app) as client:
            response = client.get("/public")

        assert response.status_code == 200
        assert response.json() == {"ok": True}
