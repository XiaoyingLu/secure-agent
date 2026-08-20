"""FastAPI application factory and runtime wiring."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from secure_agent.api.routes import ROUTERS
from secure_agent.api.routes.health import APP_VERSION
from secure_agent.auth.token_validator import EntraJWTMiddleware
from secure_agent.bootstrap import initialize_app_state, shutdown_app_state


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start up the API application and close resources on shutdown."""
    await initialize_app_state(app)
    try:
        yield
    finally:
        await shutdown_app_state(app)


def create_app() -> FastAPI:
    """Build the FastAPI application with middleware and routes."""
    app = FastAPI(title="secure-agent", version=APP_VERSION, lifespan=lifespan)
    app.add_middleware(EntraJWTMiddleware)
    for router in ROUTERS:
        app.include_router(router)
    return app


app = create_app()
