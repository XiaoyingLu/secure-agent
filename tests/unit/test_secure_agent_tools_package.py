from __future__ import annotations

from secure_agent.tools.base_tool import BaseTool


def test_secure_agent_tool_base_class_is_importable() -> None:
    class ExampleTool(BaseTool):
        async def execute(self, token: str, **kwargs):
            return {"ok": True, "token": token, **kwargs}

    tool = ExampleTool("example", "example tool")

    assert tool.name == "example"
    assert tool.description == "example tool"
    assert tool.to_mcp_schema()["name"] == "example"
