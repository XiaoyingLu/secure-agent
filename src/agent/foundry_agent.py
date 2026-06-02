"""Azure AI Foundry agent wrapper with delegated MCP tool execution."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import json
import logging
import os
import pkgutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from azure.identity import DefaultAzureCredential

from tools.base_tool import BaseTool
from agent.guardrails import Guardrails

logger = logging.getLogger(__name__)

ENV_PROJECT_ENDPOINT = "AZURE_AI_PROJECT_ENDPOINT"
ENV_PROJECT_ENDPOINT_LEGACY = "PROJECT_ENDPOINT"
ENV_MODEL_DEPLOYMENT = "AZURE_AI_MODEL_DEPLOYMENT_NAME"
ENV_MODEL_DEPLOYMENT_LEGACY = "MODEL_DEPLOYMENT_NAME"

_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "expired"}
_ACTIVE_RUN_STATUSES = {"queued", "in_progress", "requires_action"}


@dataclass(frozen=True)
class AgentResponse:
    """Response returned by :class:`FoundryAgent.chat`."""

    text: str
    thread_id: str
    run_id: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class FoundryAgent:
    """Thin async facade over Azure AI Foundry Agents.

    The Foundry SDK client used here is synchronous, so SDK calls are moved to
    worker threads while local tool execution remains native async.
    """

    def __init__(
        self,
        *,
        project_endpoint: str | None = None,
        model_deployment_name: str | None = None,
        tools: Iterable[BaseTool] | None = None,
        guardrails: Guardrails | None = None,
        agent_name: str = "secure-agent",
        poll_interval_seconds: float = 1.0,
        credential: Any | None = None,
    ) -> None:
        self.project_endpoint = project_endpoint or _env_first(
            ENV_PROJECT_ENDPOINT,
            ENV_PROJECT_ENDPOINT_LEGACY,
        )
        self.model_deployment_name = model_deployment_name or _env_first(
            ENV_MODEL_DEPLOYMENT,
            ENV_MODEL_DEPLOYMENT_LEGACY,
        )
        if not self.project_endpoint:
            raise ValueError(
                f"Missing Foundry project endpoint. Set {ENV_PROJECT_ENDPOINT}."
            )
        if not self.model_deployment_name:
            raise ValueError(
                f"Missing Foundry model deployment. Set {ENV_MODEL_DEPLOYMENT}."
            )

        self.poll_interval_seconds = poll_interval_seconds
        self.system_prompt = _read_system_prompt()
        self.guardrails = guardrails or Guardrails()
        self.tools = list(tools) if tools is not None else discover_base_tools()
        self._tool_map = {tool.name: tool for tool in self.tools}
        if len(self._tool_map) != len(self.tools):
            raise ValueError("Tool names must be unique")

        from azure.ai.agents.models import FunctionDefinition, FunctionToolDefinition
        from azure.ai.projects import AIProjectClient

        self._client = AIProjectClient(
            endpoint=self.project_endpoint,
            credential=credential or DefaultAzureCredential(),
        )
        self._agents = self._client.agents
        self._agent = self._agents.create_agent(
            model=self.model_deployment_name,
            name=agent_name,
            instructions=self.system_prompt,
            tools=[
                FunctionToolDefinition(
                    function=FunctionDefinition(
                        name=tool.name,
                        description=tool.description,
                        parameters=tool.input_schema(),
                    )
                )
                for tool in self.tools
            ],
        )
        logger.info("Created Foundry agent %s", self._agent.id)

    @property
    def agent_id(self) -> str:
        """Azure AI Foundry agent id."""
        return self._agent.id

    async def chat(
        self,
        user_message: str,
        user_token: str,
        thread_id: str | None,
    ) -> AgentResponse:
        """Send a message, execute requested tools with the OBO token, return text."""
        if not user_message.strip():
            raise ValueError("user_message must not be blank")
        if not user_token:
            raise ValueError("user_token must not be blank")

        sanitised_message = self.guardrails.sanitise_input(user_message)
        thread = await self._get_or_create_thread(thread_id)
        await asyncio.to_thread(
            self._agents.messages.create,
            thread_id=thread.id,
            role="user",
            content=sanitised_message,
        )
        run = await asyncio.to_thread(
            self._agents.runs.create,
            thread_id=thread.id,
            agent_id=self._agent.id,
        )

        while _model_value(run, "status") in _ACTIVE_RUN_STATUSES:
            if _model_value(run, "status") == "requires_action":
                await self._submit_required_tool_outputs(thread.id, run, user_token)
            await asyncio.sleep(self.poll_interval_seconds)
            run = await asyncio.to_thread(
                self._agents.runs.get,
                thread_id=thread.id,
                run_id=run.id,
            )

        status = _model_value(run, "status")
        if status not in _TERMINAL_RUN_STATUSES:
            raise RuntimeError(f"Foundry run ended with unexpected status: {status}")
        if status != "completed":
            raise RuntimeError(f"Foundry run did not complete successfully: {status}")

        response_text = await self._latest_assistant_text(thread.id)
        filtered_text = await self.guardrails.filter_output(response_text)

        return AgentResponse(
            text=filtered_text,
            thread_id=thread.id,
            run_id=run.id,
        )

    async def close(self) -> None:
        """Close the underlying SDK client if it supports explicit closing."""
        close = getattr(self._client, "close", None)
        if close is not None:
            result = close()
            if inspect.isawaitable(result):
                await result

    async def delete_agent(self) -> None:
        """Delete the Foundry agent created by this wrapper."""
        await asyncio.to_thread(self._agents.delete_agent, self._agent.id)

    async def _get_or_create_thread(self, thread_id: str | None) -> Any:
        if thread_id:
            return await asyncio.to_thread(self._agents.threads.get, thread_id)
        return await asyncio.to_thread(self._agents.threads.create)

    async def _submit_required_tool_outputs(
        self,
        thread_id: str,
        run: Any,
        user_token: str,
    ) -> None:
        from azure.ai.agents.models import RequiredFunctionToolCall, ToolOutput

        required_action = _model_value(run, "required_action")
        submit_outputs = _model_value(required_action, "submit_tool_outputs")
        tool_calls = _model_value(submit_outputs, "tool_calls") or []
        if not tool_calls:
            await asyncio.to_thread(
                self._agents.runs.cancel,
                thread_id=thread_id,
                run_id=run.id,
            )
            raise RuntimeError("Foundry requested tool outputs but supplied no calls")

        tool_outputs = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, RequiredFunctionToolCall):
                continue
            tool_outputs.append(
                ToolOutput(
                    tool_call_id=tool_call.id,
                    output=await self._execute_tool_call(tool_call, user_token),
                )
            )

        if tool_outputs:
            await asyncio.to_thread(
                self._agents.runs.submit_tool_outputs,
                thread_id=thread_id,
                run_id=run.id,
                tool_outputs=tool_outputs,
            )

    async def _execute_tool_call(self, tool_call: Any, user_token: str) -> str:
        details = _model_value(tool_call, "function") or _model_value(
            tool_call,
            "tool_call_details",
        )
        name = _model_value(details, "name")
        raw_arguments = _model_value(details, "arguments") or "{}"
        tool = self._tool_map.get(name)
        if tool is None:
            return json.dumps({"error": f"Unknown tool: {name}"})

        try:
            arguments = json.loads(raw_arguments)
            if not isinstance(arguments, dict):
                raise ValueError("Tool arguments must be a JSON object")
            result = await tool.execute(user_token, **arguments)
        except Exception as exc:
            logger.exception("Foundry tool %s failed", name)
            result = {"error": str(exc)}

        result = self.guardrails.strip_pii_from_tool_output(result)
        return json.dumps(result)

    async def _latest_assistant_text(self, thread_id: str) -> str:
        from azure.ai.agents.models import ListSortOrder

        messages = await asyncio.to_thread(
            lambda: list(
                self._agents.messages.list(
                    thread_id=thread_id,
                    order=ListSortOrder.DESCENDING,
                )
            )
        )
        for message in messages:
            if str(_model_value(message, "role")).lower() != "assistant":
                continue
            text = _message_text(message)
            if text:
                return text
        return ""


def discover_base_tools() -> list[BaseTool]:
    """Instantiate all no-argument ``BaseTool`` subclasses in ``tools``."""
    import tools as tools_package

    for module_info in pkgutil.iter_modules(tools_package.__path__):
        if module_info.name.startswith("_"):
            continue
        importlib.import_module(f"{tools_package.__name__}.{module_info.name}")

    discovered: list[BaseTool] = []
    for subclass in BaseTool.__subclasses__():
        if inspect.isabstract(subclass):
            continue
        try:
            discovered.append(subclass())
        except TypeError:
            logger.debug("Skipping BaseTool subclass requiring constructor args: %s", subclass)
    return discovered


def _read_system_prompt() -> str:
    return (Path(__file__).parent / "system_prompt.txt").read_text(encoding="utf-8")


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


def _model_value(model: Any, name: str) -> Any:
    if model is None:
        return None
    if isinstance(model, dict):
        return model.get(name)
    return getattr(model, name, None)


def _message_text(message: Any) -> str:
    text_messages = _model_value(message, "text_messages")
    if text_messages:
        return "\n".join(
            _model_value(_model_value(text_message, "text"), "value") or ""
            for text_message in text_messages
        ).strip()

    content_items = _model_value(message, "content") or []
    parts: list[str] = []
    for item in content_items:
        item_text = _model_value(item, "text")
        value = _model_value(item_text, "value") or _model_value(item, "text")
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts).strip()
