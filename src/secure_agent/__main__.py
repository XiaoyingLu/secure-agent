"""CLI entrypoint for the Secure Agent package."""

from __future__ import annotations

import uvicorn


def run_server() -> None:
    """Run the API server using the canonical FastAPI app entrypoint."""
    uvicorn.run("secure_agent.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run_server()
