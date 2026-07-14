"""HTTP route modules."""

from fastapi import APIRouter

from routes.auth import router as auth_router
from routes.chat import router as chat_router
from routes.health import router as health_router

# Create a prefixed auth router
auth_router_prefixed = APIRouter()
auth_router_prefixed.include_router(auth_router, prefix="/auth")

ROUTERS: list[APIRouter] = [health_router, auth_router_prefixed, chat_router]
