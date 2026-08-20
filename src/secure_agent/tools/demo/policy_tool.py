"""Demo tool: keyword search over internal policy fixture."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from secure_agent.tools.base_tool import BaseTool

_FIXTURE = Path(__file__).parent / "fixtures" / "policies.json"


class PolicyToolInput(BaseModel):
    query: str = Field(description="Keywords to search for in company policies")


class PolicyTool(BaseTool):
    """Demo tool: search company policies by keyword."""

    def __init__(self) -> None:
        super().__init__(
            name="search_policies",
            description="Search company internal policies by keyword and return matching policy summaries.",
        )
        with _FIXTURE.open() as f:
            self._policies: list[dict[str, Any]] = json.load(f)

    def input_schema(self) -> dict[str, Any]:
        return PolicyToolInput.model_json_schema()

    async def execute(self, token: str, **kwargs: Any) -> dict[str, Any]:
        if os.getenv("DEMO_MODE", "false").lower() != "true":
            raise RuntimeError("PolicyTool is only available when DEMO_MODE=true")
        inp = PolicyToolInput(**kwargs)
        terms = inp.query.lower().split()
        matches = [
            p for p in self._policies
            if any(
                term in p["title"].lower() or any(term in kw for kw in p["keywords"])
                for term in terms
            )
        ]
        return {"policies": [{"title": m["title"], "summary": m["summary"]} for m in matches]}
