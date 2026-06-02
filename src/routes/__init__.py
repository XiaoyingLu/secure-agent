"""HTTP route modules."""

from fastapi import APIRouter

from routes.chat import router as chat_router
from routes.health import router as health_router

ROUTERS: list[APIRouter] = [health_router, chat_router]
