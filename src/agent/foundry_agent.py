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


# Graph resource identifiers that are valid OBO token audiences.
_GRAPH_AUDIENCES = frozenset({
    "00000003-0000-0000-c000-000000000000",  # Graph GUID (v2 tokens)
    "https://graph.microsoft.com",            # Graph URI (v1 tokens)
    "https://graph.microsoft.com/",
})


def _decode_jwt_payload(token: str) -> dict[str, object]:
    """Decode a JWT payload without signature verification (diagnostics only)."""
    import base64
    import json as _json

    parts = token.split(".")
    if len(parts) < 2:
        return {}
    padded = parts[1] + "=" * (-len(parts[1]) % 4)
    return _json.loads(base64.urlsafe_b64decode(padded))  # type: ignore[return-value]


def _log_token_claims(token: str) -> None:
    """Decode the JWT payload and log aud/scp at DEBUG level."""
    try:
        payload = _decode_jwt_payload(token)
        logger.debug(
            "OBO token claims: aud=%s scp=%s roles=%s exp=%s",
            payload.get("aud"),
            payload.get("scp"),
            payload.get("roles"),
            payload.get("exp"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("OBO token: failed to decode claims: %s", exc)


def _assert_graph_audience(token: str) -> None:
    """Raise OBOError if the token is not addressed to Microsoft Graph.

    This catches the case where MSAL returns a cached token for the wrong
    resource (e.g. the app's own ``api://`` audience) before it reaches Graph,
    turning a cryptic empty-body 401 into an actionable configuration error.

    The most common cause is that the app registration in Entra does not have
    the required Graph delegated permissions (Calendars.Read, Mail.Read,
    Sites.Read.All) added **and** admin-consented.
    """
    from auth.obo_client import OBOError

    try:
        payload = _decode_jwt_payload(token)
    except Exception:
        print("[FOUNDRY] _assert_graph_audience: could not decode token")  # DEBUG
        return  # can't decode — let Graph reject it with its own error

    aud = payload.get("aud")
    if aud is None:
        print("[FOUNDRY] _assert_graph_audience: no aud claim, skipping")  # DEBUG
        return  # token is not a decodable JWT or has no aud claim — skip

    # aud may be a string or a list of strings in some token formats.
    aud_values: set[str] = {aud} if isinstance(aud, str) else set(aud)  # type: ignore[arg-type]

    print(f"[FOUNDRY] _assert_graph_audience: aud={aud} aud_values={aud_values} expected={_GRAPH_AUDIENCES}")  # DEBUG
    if not aud_values.intersection(_GRAPH_AUDIENCES):
        logger.error(
            "OBO token audience mismatch: aud=%s is not a Graph resource. "
            "Ensure the app registration has Calendars.Read, Mail.Read, and "
            "Sites.Read.All delegated permissions with admin consent in Entra.",
            aud,
        )
        print(f"[FOUNDRY] _assert_graph_audience: raising OBOError for wrong audience")  # DEBUG
        raise OBOError(
            f"OBO token audience '{aud}' is not Microsoft Graph. "
            "Add Graph delegated permissions (Calendars.Read, Mail.Read, "
            "Sites.Read.All) to the app registration and grant admin consent."
        )
    
    # Check if token has required scopes
    scp = payload.get("scp", "").split()  # scopes are space-separated in v2 tokens
    required_scopes = {"Calendars.Read", "Mail.Read", "Sites.Read.All"}
    granted_scopes = set(scp)
    missing_scopes = required_scopes - granted_scopes
    
    if missing_scopes:
        logger.warning(
            "OBO token has limited scopes. Granted: %s Missing: %s "
            "This may cause 401 errors. Ensure admin has granted consent in Entra.",
            granted_scopes,
            missing_scopes,
        )
        print(f"[FOUNDRY] WARNING: Token missing scopes: {missing_scopes}")  # DEBUG
        print(f"[FOUNDRY] Token has scopes: {granted_scopes}")  # DEBUG
    
    print(f"[FOUNDRY] _assert_graph_audience: audience is valid, scopes OK")  # DEBUG


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
        logger.info(
            "Foundry tools loaded: %s",
            ", ".join(sorted(self._tool_map.keys())) or "<none>",
        )

        self._agent_name = agent_name
        self._obo_client = OBOClient(
            tenant_id=os.getenv("ENTRA_TENANT_ID", ""),
            client_id=os.getenv("ENTRA_CLIENT_ID", ""),
            client_secret=os.getenv("ENTRA_CLIENT_SECRET", ""),
        )
        # Explicit scopes ensure MSAL targets the Graph resource unambiguously.
        # Using .default here can produce a token with the wrong audience or
        # only OIDC-level scopes, causing Graph to return an empty 401.
        # If any scope is not admin-consented, MSAL surfaces a clear OBOError
        # (error_description contains AADSTS65001) rather than silently issuing
        # an unusable token.
        # For OBO (On-Behalf-Of), scopes should be the downstream resource's
        # .default scope, not individual permissions.
        self.GRAPH_SCOPES = ["https://graph.microsoft.com/.default"]

        from azure.ai.projects.models import FunctionTool, PromptAgentDefinition, Tool
        from azure.ai.projects import AIProjectClient

        self._client = AIProjectClient(
            endpoint=self.project_endpoint,
            credential=credential or DefaultAzureCredential(),
            allow_preview=True,
        )
        self._agents = self._client.agents
        # Use the agent-specific endpoint so that responses.create and
        # conversations.create are routed through the Foundry Agent protocol
        # rather than the generic /openai/v1 endpoint.
        self._openai = self._client.get_openai_client(agent_name=agent_name)

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
        if not user_token or not user_token.strip():
            raise ValueError("user_token must not be blank or empty")

        sanitised_message = self.guardrails.sanitise_input(user_message)
        
        conversation_id = await self._get_or_create_conversation(conversation_id)

        # OBO exchange is deferred — only performed when tools are actually called.
        # This avoids failures from app-only / client-credentials tokens when no
        # tools are needed (the token is not a user assertion and cannot be
        # exchanged via the OBO flow).
        obo_token: str | None = None

        from openai.types.responses.response_input_param import FunctionCallOutput, ResponseInputParam
        input_payload: ResponseInputParam = sanitised_message
        tool_calls_made: list[dict[str, Any]] = []
        max_iterations = 10
        iteration_count = 0

        while True:
            iteration_count += 1
            if iteration_count > max_iterations:
                logger.warning(
                    "Agent loop exceeded max iterations (%d). Returning partial result.",
                    max_iterations,
                )
                break

            agent_reference: dict[str, Any] = {
                "name": self._agent_name,
                "type": "agent_reference",
            }
            agent_version = getattr(self._agent, "version", None)
            if isinstance(agent_version, str) and agent_version:
                agent_reference["version"] = agent_version

            try:
                async with asyncio.timeout(60):
                    response = await asyncio.to_thread(
                        self._openai.responses.create,
                        input=input_payload,
                        conversation=conversation_id,
                        extra_body={"agent_reference": agent_reference},
                    )
            except TimeoutError:
                logger.error("Foundry SDK call timed out after 60 seconds")
                raise TimeoutError("Agent response timed out. Please try again.")

            # Collect any function calls the model wants to make
            function_outputs: list[FunctionCallOutput] = []
            for item in response.output:
                if item.type == "function_call":
                    tool = self._tool_map.get(item.name)
                    if tool:
                        # Exchange the user assertion for a downstream token only
                        # when a tool actually needs it.
                        if obo_token is None:
                            logger.info(
                                "Exchanging user token for Graph-scoped OBO token. Scopes=%s user_token_len=%d",
                                self.GRAPH_SCOPES,
                                len(user_token),
                            )
                            try:
                                try:
                                    async with asyncio.timeout(10):
                                        print(f"[FOUNDRY] Starting OBO exchange with scopes={self.GRAPH_SCOPES}")  # DEBUG
                                        obo_token = await self._obo_client.exchange(
                                            user_token,
                                            scopes=self.GRAPH_SCOPES,
                                        )
                                        print(f"[FOUNDRY] OBO exchange succeeded: token_len={len(obo_token) if obo_token else 'None'}")  # DEBUG
                                        if obo_token:
                                            print(f"[FOUNDRY] OBO token starts: {repr(obo_token[:50])}")  # DEBUG - check for whitespace
                                            print(f"[FOUNDRY] OBO token ends: {repr(obo_token[-50:])}")  # DEBUG - check for corruption
                                            parts = obo_token.split(".")
                                            print(f"[FOUNDRY] OBO token parts: {len(parts)} (expected 3)")  # DEBUG - JWT must have 3 parts

                                except TimeoutError:
                                    logger.error("OBO token exchange timed out after 10 seconds")
                                    raise TimeoutError("Token exchange timed out. Please try again.")
                                logger.debug("OBO token acquired successfully")
                                _log_token_claims(obo_token)
                                # Full token decode for diagnostics
                                try:
                                    payload = _decode_jwt_payload(obo_token)
                                    import time as _time
                                    now = _time.time()
                                    exp = payload.get('exp')
                                    nbf = payload.get('nbf')
                                    iss = payload.get('iss')
                                    oid = payload.get('oid')
                                    tid = payload.get('tid')
                                    scp = payload.get('scp', '')
                                    print(f"[FOUNDRY] Token exp={exp} nbf={nbf} now={now}")  # DEBUG
                                    print(f"[FOUNDRY] Token expired={exp and now > exp} not_yet_valid={nbf and now < nbf}")  # DEBUG
                                    print(f"[FOUNDRY] Token iss={iss}")  # DEBUG
                                    print(f"[FOUNDRY] Token oid={oid} tid={tid}")  # DEBUG
                                    print(f"[FOUNDRY] Token scp={scp}")  # DEBUG - CRITICAL: check for Calendars.Read
                                except Exception as e:
                                    print(f"[FOUNDRY] Error decoding token: {e}")  # DEBUG
                                _assert_graph_audience(obo_token)
                            except Exception as obo_err:
                                logger.error("OBO exchange failed: %s", obo_err)
                                raise
                        kwargs = json.loads(item.arguments)
                        argument_keys = sorted(list(kwargs.keys()))
                        logger.info(
                            "Agent invoking tool: name=%s call_id=%s args=%s",
                            item.name,
                            item.call_id,
                            argument_keys,
                        )
                        if not obo_token or not obo_token.strip():
                            logger.error("BUG: OBO token is empty at tool execution time")
                            raise ValueError("OBO token is empty. Cannot execute tool.")
                        # Decode and print token claims for debugging
                        try:
                            payload = _decode_jwt_payload(obo_token)
                            print(f"[FOUNDRY] Token claims: aud={payload.get('aud')} scp={payload.get('scp')}")  # DEBUG
                        except Exception:
                            print(f"[FOUNDRY] Could not decode token claims")  # DEBUG
                        print(f"[FOUNDRY] About to invoke {item.name} with token_len={len(obo_token)}")  # DEBUG
                        try:
                            result = await tool.execute(token=obo_token, **kwargs)
                        except Exception as tool_err:
                            logger.error("Tool execution failed: %s %s", item.name, tool_err, exc_info=True)
                            print(f"[FOUNDRY] Tool {item.name} raised exception: {type(tool_err).__name__}: {tool_err}")  # DEBUG
                            # Return error result to the model so it can retry or explain
                            error_msg = f"Tool error in {item.name}: {str(tool_err)}"
                            try:
                                # Extract meaningful error messages based on exception type
                                err_type = type(tool_err).__name__
                                if err_type == "GraphPermissionError":
                                    error_msg = f"Permission denied for {item.name}. Your account may lack required scopes (Calendars.Read, Mail.Read, Sites.Read.All). Please complete the consent flow at /auth/graph-consent and retry."
                                elif err_type == "GraphAuthError":
                                    error_msg = f"Authentication failed for {item.name}. Token may be expired. Please sign out and sign in again."
                                elif err_type == "GraphRateLimitError":
                                    error_msg = f"Microsoft Graph rate limit reached. Please retry shortly."
                                elif err_type == "GraphServerError":
                                    error_msg = f"Microsoft Graph service error. Please retry shortly."
                                elif hasattr(tool_err, 'errors') and callable(tool_err.errors):
                                    # Pydantic validation error
                                    errors = tool_err.errors()
                                    if errors and isinstance(errors, list):
                                        error_msg = f"Invalid {item.name} parameters: {errors[0].get('msg', str(tool_err))}"
                            except Exception:
                                pass  # Fall back to generic error message
                            result = {"error": error_msg}
                        print(f"[FOUNDRY] Tool {item.name} completed")  # DEBUG
                        # await self._audit_logger.log(...)   # T14 audit hook
                        function_outputs.append(FunctionCallOutput(
                            type="function_call_output",
                            call_id=item.call_id,
                            output=json.dumps(result),
                        ))
                        tool_calls_made.append(
                            {
                                "name": item.name,
                                "call_id": item.call_id,
                                "argument_keys": argument_keys,
                            }
                        )
                    else:
                        logger.warning(
                            "Model requested unknown tool: name=%s call_id=%s",
                            item.name,
                            item.call_id,
                        )

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
        try:
            async with asyncio.timeout(30):
                conv = await asyncio.to_thread(self._openai.conversations.create)
        except TimeoutError:
            logger.error("conversations.create timed out after 30 seconds")
            raise TimeoutError("Failed to create conversation: Foundry service did not respond.")
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


if __name__ == "__main__":
    load_dotenv()
    logging.basicConfig(level=logging.DEBUG)
    agent = FoundryAgent()
    print("Foundry agent created:", agent.agent_id)