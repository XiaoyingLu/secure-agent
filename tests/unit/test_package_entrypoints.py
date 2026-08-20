"""Tests for the canonical package entrypoints."""

from __future__ import annotations

from unittest.mock import patch

import secure_agent
from secure_agent.__main__ import run_server


def test_package_exports_create_app() -> None:
    """The package should expose the app factory from the canonical package."""
    assert callable(secure_agent.create_app)


@patch("secure_agent.__main__.uvicorn.run")
def test_run_server_uses_package_entrypoint(mock_run) -> None:
    """The installed script should resolve to the canonical FastAPI app."""
    run_server()

    mock_run.assert_called_once_with(
        "secure_agent.app:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
