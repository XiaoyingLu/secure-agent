"""Health and connectivity probe routes."""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, status

from auth.rbac import AGENT_ADMIN_ROLE_NAME, require_role
from graph.graph_client import (
    GraphAuthError,
    GraphClient,
    GraphClientError,
    GraphPermissionError,
    GraphRateLimitError,
)

router = APIRouter(tags=["health"])

APP_VERSION = "0.1.0"
ENV_GRAPH_HEALTH_CHECK_TOKEN = "GRAPH_HEALTH_CHECK_TOKEN"


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe; no authentication required."""
    return {"status": "ok", "version": APP_VERSION}


@router.get("/health/auth")
async def health_auth(
    request: Request,
    _: None = Depends(require_role(AGENT_ADMIN_ROLE_NAME)),
) -> dict[str, object]:
    """Verify Microsoft Graph connectivity using a configured test token."""
    settings = getattr(request.app.state, "settings", None)
    token = settings.graph_health_check_token if settings else os.getenv(ENV_GRAPH_HEALTH_CHECK_TOKEN)

    if not token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GRAPH_HEALTH_CHECK_TOKEN is not configured",
        )

    graph: GraphClient | None = getattr(request.app.state, "graph_client", None)
    if graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Graph client is not initialized",
        )

    try:
        profile = await graph.get_me(token)
    except GraphAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Graph authentication failed: {exc}",
        ) from exc
    except GraphPermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Graph permission denied: {exc}",
        ) from exc
    except GraphRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Graph rate limited (retry_after={exc.retry_after})",
        ) from exc
    except GraphClientError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Graph request failed: {exc}",
        ) from exc

    return {
        "status": "ok",
        "graph": {
            "id": profile.get("id"),
            "displayName": profile.get("displayName"),
            "userPrincipalName": profile.get("userPrincipalName"),
        },
    }
