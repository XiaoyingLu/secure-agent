"""Compatibility bootstrap wrapper for application runtime startup."""

from __future__ import annotations

from fastapi import FastAPI

from secure_agent.services.runtime_service import initialize_runtime, shutdown_runtime


async def initialize_app_state(app: FastAPI) -> None:
    """Load configuration and initialise global dependencies for the app."""
    await initialize_runtime(app)


async def shutdown_app_state(app: FastAPI) -> None:
    """Close clients created during bootstrap."""
    await shutdown_runtime(app)
