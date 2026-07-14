"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from agent.foundry_agent import FoundryAgent
from agent.guardrails import Guardrails
from auth.msal_client import MSALClient
from auth.token_validator import EntraJWTMiddleware, EntraJWTValidator
from config import Settings
from graph.graph_client import GraphClient
from routes import ROUTERS
from routes.health import APP_VERSION

logger = logging.getLogger(__name__)
DEFAULT_ENTRA_REDIRECT_URI = "http://127.0.0.1:8000/auth/callback"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load configuration, warm JWKS, and initialise clients on startup."""
    settings = Settings.load()
    app.state.settings = settings

    v2_issuer = f"https://login.microsoftonline.com/{settings.entra_tenant_id}/v2.0"
    v1_issuer = f"https://sts.windows.net/{settings.entra_tenant_id}/"
    jwt_validator = EntraJWTValidator(
        settings.entra_tenant_id,
        settings.entra_client_id,
        issuer=[v2_issuer, v1_issuer],
    )
    await jwt_validator.get_jwks()
    app.state.jwt_validator = jwt_validator
    logger.info("JWKS cache warmed for tenant %s", settings.entra_tenant_id)

    if settings.entra_client_secret:
        # Pick the first configured redirect URI, or fallback to a standard local default
        redirect_uri = (
            settings.entra_redirect_uris[0] if settings.entra_redirect_uris else DEFAULT_ENTRA_REDIRECT_URI
        )
        app.state.msal_client = MSALClient(
            tenant_id=settings.entra_tenant_id,
            client_id=settings.entra_client_id,
            client_secret=settings.entra_client_secret,
            redirect_uri=redirect_uri,
            scopes=[f"api://{settings.entra_client_id}/access_as_user"],
        )
        logger.info("MSAL confidential client initialised")
    else:
        app.state.msal_client = None
        logger.warning(
            "ENTRA_CLIENT_SECRET not configured; MSAL confidential-client auth flow disabled"
        )

    graph_client = GraphClient()
    app.state.graph_client = graph_client

    guardrails = Guardrails(
        content_safety_endpoint=settings.azure_content_safety_endpoint,
        content_safety_key=settings.azure_content_safety_key,
    )
    try:
        agent = await asyncio.to_thread(FoundryAgent, guardrails=guardrails)
        app.state.foundry_agent = agent
        logger.info("FoundryAgent initialised")
    except ValueError as exc:
        app.state.foundry_agent = None
        logger.warning("FoundryAgent not initialised: %s", exc)

    yield

    await jwt_validator.aclose()
    await graph_client.aclose()
    logger.info("Application shutdown complete")


def create_app() -> FastAPI:
    """Build the FastAPI application with middleware and route modules."""
    app = FastAPI(title="secure-agent", version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(EntraJWTMiddleware)
    for router in ROUTERS:
        app.include_router(router)
    return app


app = create_app()


def run_server() -> None:
    """CLI entry point: ``uv run secure-agent`` or ``uv run python -m main``."""
    import uvicorn

    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        app_dir="src",
    )


if __name__ == "__main__":
    run_server()
