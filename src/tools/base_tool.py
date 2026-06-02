"""Abstract base class for MCP tools backed by delegated Graph access."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Base class for secure-agent MCP tools.

    Subclasses implement :meth:`execute` and may override :meth:`input_schema`
    to describe tool parameters exposed to the MCP client.
    """

    def __init__(self, name: str, description: str) -> None:
        self.name = name
        self.description = description

    @abstractmethod
    async def execute(self, token: str, **kwargs: Any) -> dict[str, Any]:
        """Run the tool using a delegated OBO access token.

        Args:
            token: On-Behalf-Of access token for downstream APIs (e.g. Graph).
            **kwargs: Tool-specific arguments from the MCP ``tools/call`` request.

        Returns:
            JSON-serialisable result dictionary.
        """

    def input_schema(self) -> dict[str, Any]:
        """JSON Schema for tool arguments (override in subclasses)."""
        return {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        }

    def to_mcp_schema(self) -> dict[str, Any]:
        """Return the MCP tool definition for ``tools/list``."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema(),
        }
