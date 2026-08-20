"""Chat orchestration service for the FastAPI routes."""

from __future__ import annotations

import asyncio
from typing import Any

from secure_agent.agent.foundry_agent import AgentResponse, FoundryAgent
from secure_agent.agent.guardrails import ContentPolicyViolationError, PromptInjectionError
from secure_agent.auth.obo_client import OBOError
from secure_agent.graph.graph_client import (
    GraphAuthError,
    GraphClientError,
    GraphPermissionError,
    GraphRateLimitError,
)


class ChatService:
    """Coordinate chat requests and delegated tool execution."""

    async def process_chat_async(
        self,
        *,
        agent: FoundryAgent,
        message: str,
        user_token: str,
        conversation_id: str | None,
        user: dict[str, Any] | None = None,
    ) -> AgentResponse:
        """Invoke the agent with a delegated token and return the result."""
        try:
            async with asyncio.timeout(120):
                result = await agent.chat(message, user_token, conversation_id)
        except PromptInjectionError:
            raise
        except ContentPolicyViolationError:
            raise
        except OBOError:
            raise
        except GraphAuthError:
            raise
        except GraphPermissionError:
            raise
        except GraphRateLimitError:
            raise
        except GraphClientError:
            raise
        except TimeoutError as exc:
            raise TimeoutError("Request timed out. The agent took too long to respond. Please try again.") from exc

        if not isinstance(result, AgentResponse):
            raise TypeError("Agent returned an unexpected result type.")
        return result

    def process_chat(
        self,
        *,
        agent: FoundryAgent,
        message: str,
        user_token: str,
        conversation_id: str | None,
        user: dict[str, Any] | None = None,
    ) -> AgentResponse:
        """Synchronous wrapper for tests and simple orchestration usage."""
        return asyncio.run(
            self.process_chat_async(
                agent=agent,
                message=message,
                user_token=user_token,
                conversation_id=conversation_id,
                user=user,
            )
        )
