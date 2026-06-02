import json

import pytest
from mcp.shared.exceptions import McpError

from tools.base_tool import BaseTool
from tools.mcp_server import MCPToolServer, OBO_TOKEN_ARGUMENT


class MockTool(BaseTool):
    """Minimal concrete tool for MCP server tests."""

    def __init__(self) -> None:
        super().__init__(
            name="mock_tool",
            description="A mock tool for unit tests",
        )

    async def execute(self, token: str, **kwargs) -> dict:
        return {
            "token_prefix": token[:8],
            "kwargs": kwargs,
        }


@pytest.fixture
def mock_tool():
    return MockTool()


@pytest.fixture
def mcp_tool_server(mock_tool):
    return MCPToolServer("secure-agent-tools", [mock_tool])


def test_to_mcp_schema(mock_tool):
    schema = mock_tool.to_mcp_schema()

    assert schema["name"] == "mock_tool"
    assert schema["description"] == "A mock tool for unit tests"
    assert schema["inputSchema"]["type"] == "object"
    assert OBO_TOKEN_ARGUMENT not in schema["inputSchema"].get("properties", {})


@pytest.mark.asyncio
async def test_mock_tool_appears_in_tools_list(mcp_tool_server):
    tools = mcp_tool_server.build_tool_list()

    assert len(tools) == 1
    assert tools[0].name == "mock_tool"
    assert tools[0].description == "A mock tool for unit tests"
    assert tools[0].inputSchema["type"] == "object"


@pytest.mark.asyncio
async def test_dispatch_passes_obo_token_to_execute(mcp_tool_server, mock_tool):
    content = await mcp_tool_server.dispatch_tool_call(
        "mock_tool",
        {OBO_TOKEN_ARGUMENT: "obo-delegated-token", "query": "inbox"},
    )

    assert len(content) == 1
    payload = json.loads(content[0].text)
    assert payload["token_prefix"] == "obo-dele"
    assert payload["kwargs"] == {"query": "inbox"}


@pytest.mark.asyncio
async def test_dispatch_unknown_tool_raises(mcp_tool_server):
    with pytest.raises(McpError, match="Unknown tool"):
        await mcp_tool_server.dispatch_tool_call("missing", {OBO_TOKEN_ARGUMENT: "t"})


@pytest.mark.asyncio
async def test_dispatch_requires_obo_token(mcp_tool_server):
    with pytest.raises(McpError, match=OBO_TOKEN_ARGUMENT):
        await mcp_tool_server.dispatch_tool_call("mock_tool", {"query": "inbox"})
