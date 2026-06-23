"""MCP server that registers :class:`~tools.base_tool.BaseTool` instances."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any

import mcp.types as types
from mcp.server.lowlevel import Server
from mcp.shared.exceptions import McpError
from mcp.types import INVALID_PARAMS, ErrorData

from tools.base_tool import BaseTool

logger = logging.getLogger(__name__)

# Reserved ``tools/call`` argument injected by the host/orchestrator (not in tool schema).
OBO_TOKEN_ARGUMENT = "obo_token"


class MCPToolServer:
    """MCP server that lists tools and dispatches ``tools/call`` to :class:`BaseTool`."""

    def __init__(self, server_name: str, tools: Iterable[BaseTool]) -> None:
        tool_map = {tool.name: tool for tool in tools}
        if len(tool_map) != len(list(tools)):
            raise ValueError("Tool names must be unique")

        self.server_name = server_name
        self._tools = tool_map
        self._mcp = Server(server_name)
        self._register_handlers()

    @property
    def mcp_server(self) -> Server:
        """Underlying MCP ``Server`` instance (for stdio/SSE transport wiring)."""
        return self._mcp

    def _register_handlers(self) -> None:
        @self._mcp.list_tools()
        async def handle_list_tools() -> list[types.Tool]:
            return self.build_tool_list()

        @self._mcp.call_tool()
        async def handle_call_tool(
            name: str, arguments: dict[str, Any] | None
        ) -> list[types.TextContent]:
            return await self.dispatch_tool_call(name, arguments or {})

    def build_tool_list(self) -> list[types.Tool]:
        """Build MCP tool definitions for all registered tools."""
        return [
            types.Tool(
                name=schema["name"],
                description=schema.get("description"),
                inputSchema=schema["inputSchema"],
            )
            for schema in (tool.to_mcp_schema() for tool in self._tools.values())
        ]

    async def dispatch_tool_call(
        self,
        name: str,
        arguments: dict[str, Any],
    ) -> list[types.TextContent]:
        """Route a ``tools/call`` to the matching tool's :meth:`~BaseTool.execute`.

        The OBO token must be supplied in ``arguments[OBO_TOKEN_ARGUMENT]``. It is
        removed before keyword arguments are passed to ``execute``.
        """
        tool = self._tools.get(name)
        if tool is None:
            raise McpError(
                ErrorData(code=INVALID_PARAMS, message=f"Unknown tool: {name}")
            )

        call_args = dict(arguments)
        obo_token = call_args.pop(OBO_TOKEN_ARGUMENT, None)
        if not obo_token or not isinstance(obo_token, str):
            raise McpError(
                ErrorData(
                    code=INVALID_PARAMS,
                    message=(
                        f"Missing required argument '{OBO_TOKEN_ARGUMENT}' "
                        "(delegated access token)"
                    ),
                )
            )

        try:
            result = await tool.execute(obo_token, **call_args)
        except Exception as exc:
            logger.exception("Tool %s failed", name)
            return [
                types.TextContent(
                    type="text",
                    text=json.dumps({"error": str(exc)}),
                )
            ]

        return [
            types.TextContent(
                type="text",
                text=json.dumps(result),
            )
        ]

if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server
    
    # 1. Instantiate the actual tools your server should provide
    # (Replace these mock examples with your actual BaseTool subclasses)
    from tools.base_tool import BaseTool  # Ensure your tool subclasses are imported
    
    from tools.calendar_tool import CalendarTool
    from tools.email_tool import EmailTool
    from tools.secure_lookup_tool import SecureLookupTool
    from tools.sharepoint_tool import SharePointTool

    registered_tools: list[BaseTool] = [
        EmailTool(),
        CalendarTool(),
        SharePointTool(),
        SecureLookupTool(),
    ]

    # 2. Initialize your custom wrapper class
    server_wrapper = MCPToolServer(
        server_name="secure-agent-tools", 
        tools=registered_tools
    )

    async def main():
        # 3. Pull out the low-level Server instance and attach it to stdio streams
        async with stdio_server() as (read_stream, write_stream):
            # This keeps the background process alive and waiting for client requests
            await server_wrapper.mcp_server.run(
                read_stream,
                write_stream,
                server_wrapper.mcp_server.create_initialization_options()
            )

    # Run the async loop
    asyncio.run(main())