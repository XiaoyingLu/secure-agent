"""Demo tool: employee directory lookup from static fixture."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from secure_agent.tools.base_tool import BaseTool

_FIXTURE = Path(__file__).parent / "fixtures" / "employees.json"


class HRToolInput(BaseModel):
    name: str = Field(description="Full or partial employee name to look up")


class HRTool(BaseTool):
    """Demo tool: look up an employee from a static fixture."""

    def __init__(self) -> None:
        super().__init__(
            name="lookup_employee",
            description="Look up an employee's role, department, manager, and onboarding status.",
        )
        with _FIXTURE.open() as f:
            self._employees: list[dict[str, Any]] = json.load(f)

    def input_schema(self) -> dict[str, Any]:
        return HRToolInput.model_json_schema()

    async def execute(self, token: str, **kwargs: Any) -> dict[str, Any]:
        if os.getenv("DEMO_MODE", "false").lower() != "true":
            raise RuntimeError("HRTool is only available when DEMO_MODE=true")
        inp = HRToolInput(**kwargs)
        query = inp.name.lower()
        match = next(
            (e for e in self._employees if query in e["name"].lower()), None
        )
        if match is None:
            return {"found": False, "query": inp.name}
        return {"found": True, "employee": match}
