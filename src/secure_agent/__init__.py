"""Secure Agent application package."""

from __future__ import annotations

__all__ = ["app", "create_app"]


def create_app():
    """Create the FastAPI app lazily to avoid circular imports during module loading."""
    from .app import create_app as _create_app

    return _create_app()


def __getattr__(name: str):
    if name == "app":
        from .app import app as _app

        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
