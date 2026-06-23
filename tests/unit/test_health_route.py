from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from auth.rbac import AGENT_ADMIN_ROLE_NAME
from graph.graph_client import (
    GraphAuthError,
    GraphClientError,
    GraphPermissionError,
    GraphRateLimitError,
)
from routes.health import APP_VERSION, ENV_GRAPH_HEALTH_CHECK_TOKEN, router


@pytest.fixture
def mock_graph_client() -> AsyncMock:
    """Fixture providing a mocked GraphClient."""
    return AsyncMock()


def _client(
    graph_client: Any | None = None,
    user: dict[str, Any] | None = None,
) -> TestClient:
    """Helper to create a TestClient with pre-configured app state and user context."""
    app = FastAPI()

    @app.middleware("http")
    async def set_user(request: Request, call_next):
        # Default to an admin user for these tests unless overridden
        request.state.user = user if user is not None else {
            "sub": "admin-123",
            "roles": [AGENT_ADMIN_ROLE_NAME],
        }
        return await call_next(request)

    if graph_client:
        app.state.graph_client = graph_client

    app.include_router(router)
    return TestClient(app)


def test_health_liveness_returns_200() -> None:
    """Verify the basic health probe returns version info."""
    client = _client()
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": APP_VERSION}


def test_health_auth_success(mock_graph_client: AsyncMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify connectivity check succeeds when Graph returns a profile."""
    monkeypatch.setenv(ENV_GRAPH_HEALTH_CHECK_TOKEN, "valid-test-token")
    mock_graph_client.get_me.return_value = {
        "id": "admin-id",
        "displayName": "Test Administrator",
        "userPrincipalName": "admin@contoso.com",
    }

    client = _client(graph_client=mock_graph_client)
    response = client.get("/health/auth")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["graph"]["id"] == "admin-id"
    mock_graph_client.get_me.assert_awaited_once_with("valid-test-token")


def test_health_auth_fails_if_token_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify 503 if the required environment variable is missing."""
    monkeypatch.delenv(ENV_GRAPH_HEALTH_CHECK_TOKEN, raising=False)
    client = _client()
    response = client.get("/health/auth")
    assert response.status_code == 503
    assert "TOKEN is not configured" in response.json()["detail"]


def test_health_auth_fails_if_graph_client_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify 503 if the graph client was not initialized in app state."""
    monkeypatch.setenv(ENV_GRAPH_HEALTH_CHECK_TOKEN, "token")
    client = _client(graph_client=None)
    response = client.get("/health/auth")
    assert response.status_code == 503
    assert "Graph client is not initialized" in response.json()["detail"]


def test_health_auth_requires_admin_role(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify 403 if the user lacks the AgentAdmin role."""
    monkeypatch.setenv(ENV_GRAPH_HEALTH_CHECK_TOKEN, "token")
    client = _client(user={"roles": ["AgentUser"]})
    response = client.get("/health/auth")
    assert response.status_code == 403


@pytest.mark.parametrize("error_class, expected_detail", [
    (GraphAuthError("Auth Failed", status_code=401), "Graph authentication failed"),
    (GraphPermissionError("No Perms", status_code=403), "Graph permission denied"),
    (GraphRateLimitError("Throttled", status_code=429, retry_after=30), "Graph rate limited (retry_after=30)"),
    (GraphClientError("Generic", status_code=400), "Graph request failed"),
])
def test_health_auth_propagates_graph_errors(
    mock_graph_client: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
    error_class: Exception,
    expected_detail: str
) -> None:
    """Verify specific Graph error types are mapped to 502 Bad Gateway."""
    monkeypatch.setenv(ENV_GRAPH_HEALTH_CHECK_TOKEN, "token")
    mock_graph_client.get_me.side_effect = error_class
    client = _client(graph_client=mock_graph_client)
    response = client.get("/health/auth")
    assert response.status_code == 502
    assert expected_detail in response.json()["detail"]
