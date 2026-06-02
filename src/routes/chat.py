"""Chat API routes."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent.foundry_agent import FoundryAgent
from agent.guardrails import (
    ContentPolicyViolationError,
    Guardrails,
    PromptInjectionError,
)
from auth.rbac import AGENT_USER_ROLE_NAME, require_role

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Incoming chat message from the client."""

    message: str = Field(..., min_length=1, description="User prompt for the agent")
    thread_id: str | None = Field(
        default=None,
        description="Existing Foundry thread id, or null to start a new thread.",
    )


class ChatResponse(BaseModel):
    """Chat response returned to the client."""

    response: str
    thread_id: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


def get_foundry_agent(request: Request) -> FoundryAgent:
    """Resolve the Foundry agent instance for request handling."""
    agent = getattr(request.app.state, "foundry_agent", None)
    if agent is None:
        settings = getattr(request.app.state, "settings", None)
        guardrails = (
            Guardrails(
                content_safety_endpoint=settings.azure_content_safety_endpoint,
                content_safety_key=settings.azure_content_safety_key,
            )
            if settings is not None
            else None
        )
        agent = FoundryAgent(guardrails=guardrails)
        request.app.state.foundry_agent = agent
    return agent


def _extract_user_token(request: Request) -> str:
    user = getattr(request.state, "user", None)
    if not isinstance(user, dict):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authenticated user.",
        )

    for key in ("access_token", "token", "bearer_token", "obo_token"):
        token = user.get(key)
        if isinstance(token, str) and token:
            return token

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing delegated user token.",
    )


@router.post("/chat", response_model=ChatResponse)
async def post_chat(
    request: Request,
    body: ChatRequest,
    _: None = Depends(require_role(AGENT_USER_ROLE_NAME)),
    agent: FoundryAgent = Depends(get_foundry_agent),
) -> ChatResponse:
    """Accept a chat message from an authenticated AgentUser."""
    user = getattr(request.state, "user", {})
    user_id = user.get("oid") or user.get("sub") if isinstance(user, dict) else None
    logger.info(
        "chat.request",
        extra={
            "custom_dimensions": {
                "thread_id": body.thread_id,
                "message_length": len(body.message),
                "user_id": user_id,
            }
        },
    )

    try:
        result = await agent.chat(
            body.message,
            _extract_user_token(request),
            body.thread_id,
        )
    except PromptInjectionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ContentPolicyViolationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Content policy violation: {exc}",
        ) from exc

    tool_calls = getattr(result, "tool_calls", []) or []
    logger.info(
        "chat.response",
        extra={
            "custom_dimensions": {
                "thread_id": result.thread_id,
                "response_length": len(result.text),
                "tool_call_count": len(tool_calls),
                "user_id": user_id,
            }
        },
    )
    return ChatResponse(
        response=result.text,
        thread_id=result.thread_id,
        tool_calls=tool_calls,
    )
