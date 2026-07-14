"""Chat API routes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from agent.foundry_agent import FoundryAgent
from agent.guardrails import (
    ContentPolicyViolationError,
    PromptInjectionError,
)
from auth.obo_client import OBOError
from auth.rbac import AGENT_USER_ROLE_NAME, require_role
from graph.graph_client import (
    GraphAuthError,
    GraphClientError,
    GraphPermissionError,
    GraphRateLimitError,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


class ChatRequest(BaseModel):
    """Incoming chat message from the client."""

    message: str = Field(..., min_length=1, description="User prompt for the agent")
    conversation_id: str | None = Field(
        default=None,
        description="Existing Foundry conversation id, or null to start a new conversation.",
    )


class ChatResponse(BaseModel):
    """Chat response returned to the client."""

    response: str
    conversation_id: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)


def get_foundry_agent(request: Request) -> FoundryAgent:
    """Resolve the Foundry agent instance from application state."""
    agent = getattr(request.app.state, "foundry_agent", None)
    if agent is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Agent not available. Check server configuration.",
        )
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
        logger.debug("Checking for delegated token in user state key '%s'", key)
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
                "conversation_id": body.conversation_id,
                "message_length": len(body.message),
                "user_id": user_id,
            }
        },
    )

    user_token = _extract_user_token(request)
    try:
        try:
            async with asyncio.timeout(120):
                result = await agent.chat(
                    body.message,
                    user_token,
                    body.conversation_id,
                )
        except TimeoutError:
            logger.error("Chat operation timed out after 120 seconds")
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Request timed out. The agent took too long to respond. Please try again.",
            ) from None
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
    except OBOError as exc:
        logger.warning("chat.obo_exchange_failed", extra={"custom_dimensions": {"user_id": user_id}})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Delegated token exchange failed for downstream Microsoft Graph access. "
                "Sign out and sign in again, then retry."
            ),
        ) from exc
    except GraphAuthError as exc:
        logger.warning(
            "chat.graph_auth_failed",
            extra={"custom_dimensions": {"user_id": user_id}},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=(
                "Microsoft Graph rejected the delegated token. "
                "This usually means you haven't granted permission for the required Graph scopes. "
                "Please complete the permission consent flow at /auth/graph-consent, then retry."
            ),
        ) from exc
    except GraphPermissionError as exc:
        logger.warning(
            "chat.graph_permission_denied",
            extra={"custom_dimensions": {"user_id": user_id}},
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Missing Microsoft Graph delegated permissions for this operation. "
                "Confirm Mail.Read, Calendars.Read, and Sites.Read.All are consented."
            ),
        ) from exc
    except GraphRateLimitError as exc:
        logger.warning(
            "chat.graph_rate_limited",
            extra={"custom_dimensions": {"user_id": user_id}},
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Microsoft Graph rate limit reached. Please retry shortly.",
            headers={"Retry-After": str(exc.retry_after)} if exc.retry_after is not None else None,
        ) from exc
    except GraphClientError as exc:
        logger.warning(
            "chat.graph_error",
            extra={"custom_dimensions": {"user_id": user_id}},
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Downstream Microsoft Graph request failed.",
        ) from exc
    except Exception as exc:
        logger.exception("chat.unhandled_error", extra={"custom_dimensions": {"user_id": user_id}})
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Agent execution failed while processing the request.",
        ) from exc

    tool_calls = getattr(result, "tool_calls", []) or []
    conversation_id = result.conversation_id if hasattr(result, "conversation_id") else ""
    logger.info(
        "chat.response",
        extra={
            "custom_dimensions": {
                "conversation_id": conversation_id,
                "response_length": len(result.text),
                "tool_call_count": len(tool_calls),
                "user_id": user_id,
            }
        },
    )
    return ChatResponse(
        response=result.text,
        conversation_id=conversation_id,
        tool_calls=tool_calls,
    )
