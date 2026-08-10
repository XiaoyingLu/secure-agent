import os

# Import demo tool classes so BaseTool.__subclasses__() picks them up during discovery.
if os.getenv("DEMO_MODE", "false").lower() == "true":
    from tools.demo.hr_tool import HRTool as _HRTool  # noqa: F401
    from tools.demo.it_tool import ITTool as _ITTool  # noqa: F401
    from tools.demo.policy_tool import PolicyTool as _PolicyTool  # noqa: F401

    _enabled = {t.strip() for t in os.getenv("ENABLED_TOOLS", "").split(",") if t.strip()}
    if "lookup_budget" in _enabled:
        from tools.demo.budget_tool import BudgetTool as _BudgetTool  # noqa: F401
