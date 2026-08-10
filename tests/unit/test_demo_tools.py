from __future__ import annotations

import os

import pytest

os.environ.setdefault("DEMO_MODE", "true")

from tools.demo.hr_tool import HRTool
from tools.demo.it_tool import ITTool
from tools.demo.policy_tool import PolicyTool
from tools.demo.budget_tool import BudgetTool


@pytest.mark.asyncio
async def test_hr_tool_found():
    tool = HRTool()
    result = await tool.execute(token="fake", name="Alice Chen")
    assert result["found"] is True
    assert result["employee"]["onboarding_complete"] is True


@pytest.mark.asyncio
async def test_hr_tool_not_found():
    tool = HRTool()
    result = await tool.execute(token="fake", name="Nobody Here")
    assert result["found"] is False


@pytest.mark.asyncio
async def test_hr_tool_demo_mode_off(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("DEMO_MODE", "false")
    tool = HRTool()
    with pytest.raises(RuntimeError, match="DEMO_MODE"):
        await tool.execute(token="fake", name="Alice Chen")


@pytest.mark.asyncio
async def test_policy_tool_match():
    tool = PolicyTool()
    result = await tool.execute(token="fake", query="remote work")
    assert len(result["policies"]) >= 1
    assert any("remote" in p["title"].lower() for p in result["policies"])


@pytest.mark.asyncio
async def test_policy_tool_no_match():
    tool = PolicyTool()
    result = await tool.execute(token="fake", query="zzznomatch")
    assert result["policies"] == []


@pytest.mark.asyncio
async def test_it_tool_by_assignee():
    tool = ITTool()
    result = await tool.execute(token="fake", assignee="Frank Nguyen")
    assert len(result["tickets"]) > 0
    assert all(t["assignee"] == "Frank Nguyen" for t in result["tickets"])


@pytest.mark.asyncio
async def test_it_tool_by_status():
    tool = ITTool()
    result = await tool.execute(token="fake", status="open")
    assert len(result["tickets"]) > 0
    assert all(t["status"] == "open" for t in result["tickets"])


@pytest.mark.asyncio
async def test_budget_tool_found():
    tool = BudgetTool()
    result = await tool.execute(token="fake", team="Engineering")
    assert result["found"] is True
    assert result["budget"]["quarter"] == "Q3 2026"


@pytest.mark.asyncio
async def test_budget_tool_not_found():
    tool = BudgetTool()
    result = await tool.execute(token="fake", team="NoSuchTeam")
    assert result["found"] is False
