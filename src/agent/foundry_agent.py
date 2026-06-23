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

from dotenv import load_dotenv
from tools.base_tool import BaseTool
from agent.guardrails import Guardrails
from auth.obo_client import OBOClient

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
    conversation_id: str
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

        self._agent_name = agent_name
        self._obo_client = OBOClient(
            tenant_id=os.getenv("ENTRA_TENANT_ID", ""),
            client_id=os.getenv("ENTRA_CLIENT_ID", ""),
            client_secret=os.getenv("ENTRA_CLIENT_SECRET", ""),
        )
        self.GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]

        from azure.ai.projects.models import FunctionTool, PromptAgentDefinition, Tool
        from azure.ai.projects import AIProjectClient

        self._client = AIProjectClient(
            endpoint=self.project_endpoint,
            credential=credential or DefaultAzureCredential(),
        )
        self._agents = self._client.agents
        self._openai = self._client.get_openai_client()

        tools: list[Tool] = [
            FunctionTool(
                name=tool.name,
                description=tool.description,
                parameters=tool.input_schema(),
                strict=False,
            )
            for tool in self.tools
        ]
        definition = PromptAgentDefinition(
            model=self.model_deployment_name,
            instructions=self.system_prompt,
            tools=tools,
        )
        self._agent = self._agents.create_version(agent_name=agent_name, definition=definition)
        logger.info("Created Foundry agent %s", self._agent.id)

    @property
    def agent_id(self) -> str:
        """Azure AI Foundry agent id."""
        return self._agent.id

    # --- chat() replaces the entire thread/run/poll loop ---
    async def chat(
        self,
        user_message: str,
        user_token: str,
        conversation_id: str | None,
    ) -> AgentResponse:
        """Send a message, execute requested tools with the OBO token, return text."""
        if not user_message.strip():
            raise ValueError("user_message must not be blank")
        if not user_token:
            raise ValueError("user_token must not be blank")

        sanitised_message = self.guardrails.sanitise_input(user_message)
        
        conversation_id = await self._get_or_create_conversation(conversation_id)

        # OBO exchange is deferred — only performed when tools are actually called.
        # This avoids failures from app-only / client-credentials tokens when no
        # tools are needed (the token is not a user assertion and cannot be
        # exchanged via the OBO flow).
        obo_token: str | None = None

        from openai.types.responses.response_input_param import FunctionCallOutput, ResponseInputParam
        input_payload: ResponseInputParam = sanitised_message
        tool_calls_made = []

        while True:
            response = await asyncio.to_thread(
                self._openai.responses.create,
                input=input_payload,
                conversation=conversation_id,
                extra_body={"agent_reference": {
                    "name": self._agent_name,
                    "type": "agent_reference",
                }},
            )

            # Collect any function calls the model wants to make
            function_outputs: list[FunctionCallOutput] = []
            for item in response.output:
                if item.type == "function_call":
                    tool = self._tool_map.get(item.name)
                    if tool:
                        # Exchange the user assertion for a downstream token only
                        # when a tool actually needs it.
                        if obo_token is None:
                            obo_token = await self._obo_client.exchange(
                                user_token,
                                scopes=self.GRAPH_SCOPES,
                            )
                        kwargs = json.loads(item.arguments)
                        result = await tool.execute(token=obo_token, **kwargs)
                        # await self._audit_logger.log(...)   # T14 audit hook
                        function_outputs.append(FunctionCallOutput(
                            type="function_call_output",
                            call_id=item.call_id,
                            output=json.dumps(result),
                        ))
                        tool_calls_made.append(item.name)

            if not function_outputs:
                # No more tool calls — model has produced its final answer
                break

            # Feed results back and loop
            input_payload = function_outputs

        # Run the model's final answer through content safety filtering before
        # returning it to the caller.
        filtered_text = await self.guardrails.filter_output(response.output_text)

        return AgentResponse(
            text=filtered_text,
            conversation_id=conversation_id,
            tool_calls=tool_calls_made,
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
        await asyncio.to_thread(self._agents.delete_version, agent_name=self._agent.name, agent_version=self._agent.version)

    # --- conversation replaces thread ---
    async def _get_or_create_conversation(self, conversation_id: str | None) -> str:
        if conversation_id:
            return conversation_id  # conversations are just IDs, no fetch needed
        conv = await asyncio.to_thread(self._openai.conversations.create)
        return conv.id

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
