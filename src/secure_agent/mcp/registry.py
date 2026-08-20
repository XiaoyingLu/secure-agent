"""MCP tool registry helpers."""

from __future__ import annotations

from collections.abc import Iterable

from secure_agent.tools.base_tool import BaseTool


def build_tools(tool_iterable: Iterable[BaseTool]) -> dict[str, BaseTool]:
    """Return a unique-name mapping for registered tools."""
    tools = list(tool_iterable)
    mapping = {tool.name: tool for tool in tools}
    if len(mapping) != len(tools):
        raise ValueError("Tool names must be unique")
    return mapping
