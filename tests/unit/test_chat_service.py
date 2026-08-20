from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

from secure_agent.agent.foundry_agent import AgentResponse
from secure_agent.auth.obo_client import OBOError
from secure_agent.services.chat_service import ChatService


@dataclass
class MockFoundryAgent:
    chat: AsyncMock = field(default_factory=AsyncMock)


def test_chat_service_handles_successful_chat() -> None:
    agent = MockFoundryAgent()
    agent.chat.return_value = AgentResponse(
        text="Here is your answer.",
        conversation_id="thread-123",
        tool_calls=[{"name": "get_my_emails"}],
    )

    service = ChatService()
    result = service.process_chat(
        agent=agent,
        message="What mail did I get?",
        user_token="delegated-user-token",
        conversation_id="thread-abc",
        user={"sub": "user-1", "roles": ["AgentUser"], "access_token": "delegated-user-token"},
    )

    assert result.text == "Here is your answer."
    assert result.conversation_id == "thread-123"
    assert result.tool_calls == [{"name": "get_my_emails"}]
    agent.chat.assert_awaited_once_with(
        "What mail did I get?",
        "delegated-user-token",
        "thread-abc",
    )


def test_chat_service_raises_obo_error_for_failed_exchange() -> None:
    agent = MockFoundryAgent()
    agent.chat.side_effect = OBOError("invalid_grant")

    service = ChatService()

    try:
        service.process_chat(
            agent=agent,
            message="Show my latest emails",
            user_token="delegated-user-token",
            conversation_id=None,
            user={"sub": "user-1", "roles": ["AgentUser"]},
        )
        raise AssertionError("OBOError should have been raised")
    except OBOError:
        pass
