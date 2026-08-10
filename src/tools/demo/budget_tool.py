"""Demo tool: team budget lookup — the live-add extensibility demo beat."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from tools.base_tool import BaseTool

_FIXTURE = Path(__file__).parent / "fixtures" / "budgets.json"


class BudgetToolInput(BaseModel):
    team: str = Field(description="Team name to look up budget for (e.g. Engineering, Product)")


class BudgetTool(BaseTool):
    """Demo tool: look up a team's Q3 budget — add 'lookup_budget' to ENABLED_TOOLS to activate."""

    def __init__(self) -> None:
        super().__init__(
            name="lookup_budget",
            description="Look up the current quarter's allocated and spent budget for a team.",
        )
        with _FIXTURE.open() as f:
            self._budgets: list[dict[str, Any]] = json.load(f)

    def input_schema(self) -> dict[str, Any]:
        return BudgetToolInput.model_json_schema()

    async def execute(self, token: str, **kwargs: Any) -> dict[str, Any]:
        if os.getenv("DEMO_MODE", "false").lower() != "true":
            raise RuntimeError("BudgetTool is only available when DEMO_MODE=true")
        inp = BudgetToolInput(**kwargs)
        match = next(
            (b for b in self._budgets if inp.team.lower() in b["team"].lower()), None
        )
        if match is None:
            return {"found": False, "team": inp.team}
        return {"found": True, "budget": match}
