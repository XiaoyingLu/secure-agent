"""Runtime initialization orchestration for the application."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import FastAPI

from secure_agent.config import Settings
from secure_agent.agent.foundry_agent import FoundryAgent
from secure_agent.agent.guardrails import Guardrails
from secure_agent.auth.msal_client import MSALClient
from secure_agent.auth.token_validator import EntraJWTValidator
from secure_agent.graph.graph_client import GraphClient

logger = logging.getLogger(__name__)
DEFAULT_ENTRA_REDIRECT_URI = "http://127.0.0.1:8000/auth/callback"


async def initialize_runtime(app: FastAPI) -> None:
    """Load configuration and initialise the app's shared runtime dependencies."""
    settings = Settings.load()
    app.state.settings = settings

    if settings.demo_mode:
        from secure_agent.audit.audit_logger import AuditLogger

        app.state.audit_logger = AuditLogger()
        logger.info("Demo mode enabled — AuditLogger initialised")

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
        redirect_uri = (
            settings.entra_redirect_uris[0]
            if settings.entra_redirect_uris
            else DEFAULT_ENTRA_REDIRECT_URI
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

    app.state.bootstrap_complete = True


async def shutdown_runtime(app: FastAPI) -> None:
    """Close resources created during runtime initialisation."""
    jwt_validator = getattr(app.state, "jwt_validator", None)
    if jwt_validator is not None:
        await jwt_validator.aclose()

    graph_client = getattr(app.state, "graph_client", None)
    if graph_client is not None:
        await graph_client.aclose()

    logger.info("Application shutdown complete")
