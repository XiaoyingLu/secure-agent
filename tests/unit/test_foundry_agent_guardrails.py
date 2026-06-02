from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from agent.foundry_agent import FoundryAgent
from tools.base_tool import BaseTool


@dataclass
class _Model:
    id: str
    status: str | None = None


class _Messages:
    def __init__(self) -> None:
        self.created: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> None:
        self.created = kwargs


class _Runs:
    def create(self, **kwargs: Any) -> _Model:
        return _Model(id="run-1", status="completed")


class _Agents:
    def __init__(self) -> None:
        self.messages = _Messages()
        self.runs = _Runs()


class _Guardrails:
    def __init__(self) -> None:
        self.filtered_text: str | None = None

    def sanitise_input(self, text: str) -> str:
        return f"sanitised: {text}"

    def strip_pii_from_tool_output(self, data: dict[str, Any]) -> dict[str, Any]:
        return {"redacted": data["value"].replace("ava@example.com", "[email]")}

    async def filter_output(self, text: str) -> str:
        self.filtered_text = text
        return f"filtered: {text}"


class _Tool(BaseTool):
    def __init__(self) -> None:
        super().__init__("lookup", "Lookup data")

    async def execute(self, token: str, **kwargs: Any) -> dict[str, Any]:
        return {"value": "Email ava@example.com"}


@pytest.mark.asyncio
async def test_chat_sanitises_user_message_before_sending_to_foundry() -> None:
    agent = FoundryAgent.__new__(FoundryAgent)
    agent.guardrails = _Guardrails()
    agent._agents = _Agents()
    agent._agent = _Model(id="agent-1")
    agent.poll_interval_seconds = 0

    async def get_thread(thread_id: str | None) -> _Model:
        return _Model(id=thread_id or "thread-1")

    async def latest_text(thread_id: str) -> str:
        return "done"

    agent._get_or_create_thread = get_thread
    agent._latest_assistant_text = latest_text

    await agent.chat("hello", "token", None)

    assert agent._agents.messages.created == {
        "thread_id": "thread-1",
        "role": "user",
        "content": "sanitised: hello",
    }
    assert agent.guardrails.filtered_text == "done"


@pytest.mark.asyncio
async def test_chat_returns_content_safety_filtered_response() -> None:
    agent = FoundryAgent.__new__(FoundryAgent)
    agent.guardrails = _Guardrails()
    agent._agents = _Agents()
    agent._agent = _Model(id="agent-1")
    agent.poll_interval_seconds = 0

    async def get_thread(thread_id: str | None) -> _Model:
        return _Model(id=thread_id or "thread-1")

    async def latest_text(thread_id: str) -> str:
        return "final answer"

    agent._get_or_create_thread = get_thread
    agent._latest_assistant_text = latest_text

    response = await agent.chat("hello", "token", None)

    assert response.text == "filtered: final answer"


@pytest.mark.asyncio
async def test_execute_tool_call_redacts_tool_result_before_json_output() -> None:
    agent = FoundryAgent.__new__(FoundryAgent)
    agent.guardrails = _Guardrails()
    agent._tool_map = {"lookup": _Tool()}
    tool_call = {
        "function": {
            "name": "lookup",
            "arguments": json.dumps({"query": "person"}),
        }
    }

    output = await agent._execute_tool_call(tool_call, "token")

    assert json.loads(output) == {"redacted": "Email [email]"}
