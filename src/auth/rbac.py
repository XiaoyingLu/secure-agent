"""Role-based access control dependencies for FastAPI."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
import os
from typing import Any

from fastapi import HTTPException, Request, status

# Entra app role display names (JWT `roles` claim values)
AGENT_USER_ROLE_NAME = "AgentUser"
AGENT_ADMIN_ROLE_NAME = "AgentAdmin"

# Entra app manifest role IDs (see docs/app-roles.md)
ENV_AGENT_USER_ROLE_ID = "AGENT_USER_ROLE_ID"
ENV_AGENT_ADMIN_ROLE_ID = "AGENT_ADMIN_ROLE_ID"
AGENT_USER_ROLE_ID = os.getenv(ENV_AGENT_USER_ROLE_ID, "").strip()
AGENT_ADMIN_ROLE_ID = os.getenv(ENV_AGENT_ADMIN_ROLE_ID, "").strip()

FORBIDDEN_DETAIL = "Insufficient role for this operation"


def require_role(role: str) -> Callable[[Request], Coroutine[Any, Any, None]]:
    """FastAPI dependency factory that enforces an Entra app role.

    Reads assigned roles from ``request.state.user['roles']``, which must be
    populated by :class:`~auth.token_validator.EntraJWTMiddleware` (or equivalent).

    Args:
        role: Required role name (e.g. ``AgentUser``).

    Returns:
        An async dependency that returns ``None`` when authorized.

    Raises:
        HTTPException: 403 if the user is missing or lacks the required role.
    """

    async def _require_role(request: Request) -> None:
        print(f"Checking for required role: {role}")  # Debugging line
        user = getattr(request.state, "user", None)
        if not isinstance(user, dict):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=FORBIDDEN_DETAIL,
            )

        roles = user.get("roles")
        if not isinstance(roles, list) or role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=FORBIDDEN_DETAIL,
            )

    return _require_role
