"""Integration smoke test for the Azure AI Foundry agent wrapper."""

from __future__ import annotations

import os

from azure.identity import ClientSecretCredential
import pytest
from dotenv import load_dotenv

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
    # Load local environment variables for the integration test
    load_dotenv(".env.local")
    pytest.importorskip("azure.ai.projects")
    endpoint = _env_first(ENV_PROJECT_ENDPOINT, ENV_PROJECT_ENDPOINT_LEGACY)
    model = _env_first(ENV_MODEL_DEPLOYMENT, ENV_MODEL_DEPLOYMENT_LEGACY)
    if not endpoint or not model:
        pytest.skip(
            "Set AZURE_AI_PROJECT_ENDPOINT and AZURE_AI_MODEL_DEPLOYMENT_NAME "
            "to run the Foundry integration test."
        )
    credential = ClientSecretCredential(
        tenant_id=os.getenv("ENTRA_TENANT_ID"),
        client_id=os.getenv("ENTRA_CLIENT_ID"),
        client_secret=os.getenv("ENTRA_CLIENT_SECRET")
    )
    
    agent = FoundryAgent(
        project_endpoint=endpoint,
        model_deployment_name=model,
        agent_name="secure-agent-integration-test",
        poll_interval_seconds=0.5,
        credential=credential,
    )
    try:
        response = await agent.chat(
            user_message=(
                "Reply with exactly this text and do not use tools: "
                "foundry integration ok"
            ),
            user_token=os.getenv("AZURE_FOUNDRY_TEST_USER_TOKEN", credential.get_token(
                "https://graph.microsoft.com/.default").token),
            conversation_id=None,
        )

        # conversation_id is the new name for what was thread_id; the OBO
        # exchange is now deferred so a client-credentials token works when
        # the model does not call any tools.
        assert response.conversation_id
        assert "foundry integration ok" in response.text.lower()
    finally:
        await agent.delete_agent()
        await agent.close()
