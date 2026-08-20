"""API router registry."""

import os

from fastapi import APIRouter

from secure_agent.api.routes.auth import router as auth_router
from secure_agent.api.routes.audit import router as audit_router
from secure_agent.api.routes.chat import router as chat_router
from secure_agent.api.routes.health import router as health_router

# Create a prefixed auth router
auth_router_prefixed = APIRouter()
auth_router_prefixed.include_router(auth_router, prefix="/auth")

ROUTERS: list[APIRouter] = [health_router, auth_router_prefixed, chat_router]

if os.getenv("DEMO_MODE", "false").lower() == "true":
    ROUTERS.append(audit_router)
