"""Security helpers for delegated and authenticated user tokens."""

from __future__ import annotations

from typing import Any


def extract_delegated_token(user: dict[str, Any]) -> str:
    """Return the delegated user token from known auth state keys."""
    for key in ("access_token", "token", "bearer_token", "obo_token"):
        token = user.get(key)
        if isinstance(token, str) and token:
            return token
    raise ValueError("Missing delegated user token.")
