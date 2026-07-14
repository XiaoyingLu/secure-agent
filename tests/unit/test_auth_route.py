from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import Mock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.auth import router


@dataclass
class MockMsalClient:
	client_id: str = "test-client-id"
	tenant_id: str = "test-tenant-id"
	redirect_uri: str = "http://127.0.0.1:8000/callback"
	scopes: list[str] = field(default_factory=lambda: ["api://test-client-id/access_as_user"])
	auth_state: str | None = "known-state"
	is_known_auth_state: Mock = field(default_factory=lambda: Mock(return_value=True))
	exchange_authorization_code: Mock = field(
		default_factory=lambda: Mock(
			return_value={
				"access_token": "delegated-user-token",
				"token_type": "Bearer",
				"expires_in": 3600,
			}
		)
	)
	build_authorization_url: Mock = field(
		default_factory=lambda: Mock(
			return_value="https://login.microsoftonline.com/test-tenant-id/oauth2/v2.0/authorize?mock=1"
		)
	)


def _client(msal_client: MockMsalClient | None) -> TestClient:
	app = FastAPI()
	app.state.msal_client = msal_client
	app.include_router(router, prefix="/auth")
	return TestClient(app)


def test_login_redirects_when_confidential_client_is_configured() -> None:
	msal_client = MockMsalClient()

	response = _client(msal_client).get("/auth/login", follow_redirects=False)

	assert response.status_code == 302
	assert response.headers["location"].startswith("https://login.microsoftonline.com/")
	msal_client.build_authorization_url.assert_called_once_with()


def test_login_returns_503_when_confidential_client_is_not_configured() -> None:
	response = _client(None).get("/auth/login", follow_redirects=False)

	assert response.status_code == 503
	assert "ENTRA_CLIENT_SECRET" in response.text


def test_callback_sets_http_only_access_token_cookie() -> None:
	msal_client = MockMsalClient()

	response = _client(msal_client).get(
		"/auth/callback",
		params={"code": "auth-code", "state": "known-state"},
	)

	assert response.status_code == 200
	assert response.json()["access_token"] == "delegated-user-token"
	set_cookie = response.headers.get("set-cookie", "")
	assert "secure_agent_access_token=delegated-user-token" in set_cookie
	assert "HttpOnly" in set_cookie
	assert "SameSite=lax" in set_cookie
	msal_client.is_known_auth_state.assert_called_once_with("known-state")
	msal_client.exchange_authorization_code.assert_called_once_with(
		"auth-code",
		state="known-state",
	)
