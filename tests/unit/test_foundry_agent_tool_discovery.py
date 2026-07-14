from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from agent.foundry_agent import _parse_enabled_tools_from_env, discover_base_tools
from tools.base_tool import BaseTool


class _EnabledTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(name="enabled_tool", description="enabled")

    async def execute(self, token: str, **kwargs):
        return {"ok": True}


class _OtherTool(BaseTool):
    def __init__(self) -> None:
        super().__init__(name="other_tool", description="other")

    async def execute(self, token: str, **kwargs):
        return {"ok": True}


class _RequiresArgsTool(BaseTool):
    def __init__(self, required_arg: str) -> None:
        super().__init__(name="requires_args", description="requires args")
        self.required_arg = required_arg

    async def execute(self, token: str, **kwargs):
        return {"ok": True}


def _fake_module_info(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name)


def test_discover_base_tools_filters_by_enabled_tool_names() -> None:
    with (
        patch("agent.foundry_agent.pkgutil.iter_modules", return_value=[_fake_module_info("email_tool")]),
        patch("agent.foundry_agent.importlib.import_module"),
        patch.object(
            BaseTool,
            "__subclasses__",
            return_value=[_EnabledTool, _OtherTool, _RequiresArgsTool],
        ),
    ):
        tools = discover_base_tools(enabled_tool_names={"enabled_tool"})

    assert [tool.name for tool in tools] == ["enabled_tool"]


def test_discover_base_tools_returns_all_when_allowlist_is_unset() -> None:
    with (
        patch("agent.foundry_agent.pkgutil.iter_modules", return_value=[_fake_module_info("email_tool")]),
        patch("agent.foundry_agent.importlib.import_module"),
        patch.object(
            BaseTool,
            "__subclasses__",
            return_value=[_EnabledTool, _OtherTool, _RequiresArgsTool],
        ),
    ):
        tools = discover_base_tools()

    assert sorted(tool.name for tool in tools) == ["enabled_tool", "other_tool"]


def test_parse_enabled_tools_from_env_handles_csv_values() -> None:
    with patch.dict(
        "os.environ",
        {"ENABLED_TOOLS": " enabled_tool,other_tool ,, "},
        clear=False,
    ):
        parsed = _parse_enabled_tools_from_env()

    assert parsed == {"enabled_tool", "other_tool"}
