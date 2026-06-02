"""Integration smoke test for the Azure AI Foundry agent wrapper."""

from __future__ import annotations

import os

import pytest

from agent.foundry_agent import (
    ENV_MODEL_DEPLOYMENT,
    ENV_MODEL_DEPLOYMENT_LEGACY,
    ENV_PROJECT_ENDPOINT,
    ENV_PROJECT_ENDPOINT_LEGACY,
    FoundryAgent,
)


pytestmark = pytest.mark.integration


def _env_first(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


@pytest.mark.asyncio
async def test_foundry_agent_chat_against_real_endpoint() -> None:
    pytest.importorskip("azure.ai.projects")
    endpoint = _env_first(ENV_PROJECT_ENDPOINT, ENV_PROJECT_ENDPOINT_LEGACY)
    model = _env_first(ENV_MODEL_DEPLOYMENT, ENV_MODEL_DEPLOYMENT_LEGACY)
    if not endpoint or not model:
        pytest.skip(
            "Set AZURE_AI_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT_NAME "
            "to run the Foundry integration test."
        )

    agent = FoundryAgent(
        project_endpoint=endpoint,
        model_deployment_name=model,
        agent_name="secure-agent-integration-test",
        poll_interval_seconds=0.5,
    )
    try:
        response = await agent.chat(
            user_message=(
                "Reply with exactly this text and do not use tools: "
                "foundry integration ok"
            ),
            user_token=os.getenv("AZURE_FOUNDRY_TEST_USER_TOKEN", "not-used"),
            thread_id=None,
        )

        assert response.thread_id
        assert response.run_id
        assert "foundry integration ok" in response.text.lower()
    finally:
        await agent.delete_agent()
        await agent.close()
