from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.foundry_agent import FoundryAgent
from tools.base_tool import BaseTool


@dataclass
class _Model:
    id: str
    status: str | None = None


@dataclass
class MockResponseItem:
    type: str
    name: str = ""
    arguments: str = "{}"
    call_id: str = ""


@dataclass
class MockResponse:
    output: list[MockResponseItem] = field(default_factory=list)
    output_text: str = ""
    id: str = "resp-1"


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


def _make_conversation_mock(conversation_id: str = "conv-1") -> MagicMock:
    """Return a ``create`` callable that returns an object with ``id``."""
    mock = MagicMock()
    mock.return_value = _Model(id=conversation_id)
    return mock


def _make_responses_mock(*responses: MockResponse) -> MagicMock:
    """Return a ``create`` callable that returns responses in sequence."""
    mock = MagicMock()
    mock.side_effect = list(responses)
    return mock


def _make_agent(
    *,
    guardrails: _Guardrails | None = None,
    tool_map: dict[str, BaseTool] | None = None,
    conversation_id: str = "conv-1",
    responses: list[MockResponse] | None = None,
) -> FoundryAgent:
    agent = FoundryAgent.__new__(FoundryAgent)
    agent.guardrails = guardrails or _Guardrails()
    agent._agent = _Model(id="agent-1")
    agent._agent_name = "secure-agent-integration-test"
    agent._tool_map = tool_map or {}
    agent._obo_client = AsyncMock()
    agent.GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]
    agent.poll_interval_seconds = 0

    # Mock the OpenAI client
    openai_mock = MagicMock()
    openai_mock.conversations.create = _make_conversation_mock(conversation_id)
    openai_mock.responses.create = _make_responses_mock(
        *(responses or [MockResponse(output=[], output_text="done")])
    )
    agent._openai = openai_mock

    return agent


@pytest.mark.asyncio
async def test_chat_sanitises_user_message_before_sending_to_foundry() -> None:
    """Guardrails.sanitise_input is called before the message reaches Foundry."""
    guardrails = _Guardrails()
    agent = _make_agent(guardrails=guardrails)

    await agent.chat("hello", "token", None)

    # The input sent to Foundry should be sanitised
    call_kwargs = agent._openai.responses.create.call_args
    assert call_kwargs is not None
    input_payload = call_kwargs[1].get("input")
    assert input_payload == "sanitised: hello"


@pytest.mark.asyncio
async def test_chat_returns_content_safety_filtered_response() -> None:
    """Guardrails.filter_output is applied to the model's text response."""
    guardrails = _Guardrails()
    agent = _make_agent(
        guardrails=guardrails,
        responses=[MockResponse(output=[], output_text="final answer")],
    )

    response = await agent.chat("hello", "token", None)

    # The returned text should go through guardrails.filter_output
    assert response.text == "filtered: final answer"
    assert guardrails.filtered_text == "final answer"


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
