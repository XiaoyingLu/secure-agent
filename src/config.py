"""Application configuration loaded from Key Vault or local env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from azure.core.exceptions import ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient
from dotenv import load_dotenv

# Key Vault secret names (hyphenated; see docs and infra/modules/keyvault.bicep)
KV_SECRET_ENTRA_TENANT_ID = "ENTRA-TENANT-ID"
KV_SECRET_ENTRA_CLIENT_ID = "ENTRA-CLIENT-ID"
KV_SECRET_ENTRA_CLIENT_SECRET = "ENTRA-CLIENT-SECRET"
KV_SECRET_AZURE_OPENAI_ENDPOINT = "AZURE-OPENAI-ENDPOINT"
KV_SECRET_AZURE_CONTENT_SAFETY_ENDPOINT = "AZURE-CONTENT-SAFETY-ENDPOINT"
KV_SECRET_AZURE_CONTENT_SAFETY_KEY = "AZURE-CONTENT-SAFETY-KEY"
KV_SECRET_REDIS_CONNECTION_STRING = "REDIS-CONNECTION-STRING"
KV_SECRET_APPLICATIONINSIGHTS_CONNECTION_STRING = "APPLICATIONINSIGHTS-CONNECTION-STRING"

# .env.local variable names (see CLAUDE.md)
ENV_ENTRA_TENANT_ID = "ENTRA_TENANT_ID"
ENV_ENTRA_CLIENT_ID = "ENTRA_CLIENT_ID"
ENV_ENTRA_CLIENT_SECRET = "ENTRA_CLIENT_SECRET"
ENV_AZURE_OPENAI_ENDPOINT = "AZURE_OPENAI_ENDPOINT"
ENV_AZURE_CONTENT_SAFETY_ENDPOINT = "AZURE_CONTENT_SAFETY_ENDPOINT"
ENV_AZURE_CONTENT_SAFETY_KEY = "AZURE_CONTENT_SAFETY_KEY"
ENV_REDIS_CONNECTION_STRING = "REDIS_CONNECTION_STRING"
ENV_APPLICATIONINSIGHTS_CONNECTION_STRING = "APPLICATIONINSIGHTS_CONNECTION_STRING"
ENV_AZURE_KEY_VAULT_URL = "AZURE_KEY_VAULT_URL"


class ConfigurationError(Exception):
    """Raised when required settings are missing or cannot be loaded."""


@dataclass(frozen=True)
class Settings:
    """Typed application settings sourced from Key Vault or ``.env.local``."""

    entra_tenant_id: str
    entra_client_id: str
    entra_client_secret: str | None
    azure_openai_endpoint: str
    azure_content_safety_endpoint: str
    azure_content_safety_key: str
    redis_connection_string: str
    applicationinsights_connection_string: str
    azure_key_vault_url: str | None = None

    _REQUIRED_ENV_KEYS: ClassVar[tuple[str, ...]] = (
        ENV_ENTRA_TENANT_ID,
        ENV_ENTRA_CLIENT_ID,
        ENV_AZURE_OPENAI_ENDPOINT,
        ENV_AZURE_CONTENT_SAFETY_ENDPOINT,
        ENV_AZURE_CONTENT_SAFETY_KEY,
        ENV_REDIS_CONNECTION_STRING,
        ENV_APPLICATIONINSIGHTS_CONNECTION_STRING,
    )

    @classmethod
    def load(
        cls,
        *,
        secret_client: SecretClient | None = None,
        env_file: str | Path = ".env.local",
    ) -> Settings:
        """Load settings at startup from Key Vault or local env.

        Uses ``AZURE_KEY_VAULT_URL`` when set (production / Azure). Otherwise
        loads ``.env.local`` for local development.

        Args:
            secret_client: Optional ``SecretClient`` (for unit tests).
            env_file: Path to the local env file when Key Vault is not configured.

        Returns:
            Frozen :class:`Settings` instance.

        Raises:
            ConfigurationError: If required values are missing.
        """
        vault_url = os.getenv(ENV_AZURE_KEY_VAULT_URL)
        if vault_url:
            return cls._from_key_vault(vault_url, secret_client=secret_client)
        return cls._from_env_file(env_file)

    @classmethod
    def _from_key_vault(
        cls,
        vault_url: str,
        *,
        secret_client: SecretClient | None = None,
    ) -> Settings:
        client = secret_client or SecretClient(
            vault_url=vault_url,
            credential=DefaultAzureCredential(),
        )

        def _get_required(name: str) -> str:
            value = client.get_secret(name).value
            if not value:
                raise ConfigurationError(f"Key Vault secret '{name}' is empty.")
            return value

        def _get_optional(name: str) -> str | None:
            try:
                return client.get_secret(name).value
            except ResourceNotFoundError:
                return None

        return cls(
            azure_key_vault_url=vault_url,
            entra_tenant_id=_get_required(KV_SECRET_ENTRA_TENANT_ID),
            entra_client_id=_get_required(KV_SECRET_ENTRA_CLIENT_ID),
            entra_client_secret=_get_optional(KV_SECRET_ENTRA_CLIENT_SECRET),
            azure_openai_endpoint=_get_required(KV_SECRET_AZURE_OPENAI_ENDPOINT),
            azure_content_safety_endpoint=_get_required(
                KV_SECRET_AZURE_CONTENT_SAFETY_ENDPOINT
            ),
            azure_content_safety_key=_get_required(KV_SECRET_AZURE_CONTENT_SAFETY_KEY),
            redis_connection_string=_get_required(KV_SECRET_REDIS_CONNECTION_STRING),
            applicationinsights_connection_string=_get_required(
                KV_SECRET_APPLICATIONINSIGHTS_CONNECTION_STRING
            ),
        )

    @classmethod
    def _from_env_file(cls, env_file: str | Path) -> Settings:
        path = Path(env_file)
        if path.is_file():
            load_dotenv(path)
        elif not cls._has_required_env():
            raise ConfigurationError(
                f"Missing {path.resolve()}. Copy .env.example to .env.local for local dev."
            )

        missing = [key for key in cls._REQUIRED_ENV_KEYS if not os.getenv(key)]
        if missing:
            raise ConfigurationError(
                f"Missing required environment variables: {', '.join(missing)}"
            )

        return cls(
            azure_key_vault_url=None,
            entra_tenant_id=os.environ[ENV_ENTRA_TENANT_ID],
            entra_client_id=os.environ[ENV_ENTRA_CLIENT_ID],
            entra_client_secret=os.getenv(ENV_ENTRA_CLIENT_SECRET),
            azure_openai_endpoint=os.environ[ENV_AZURE_OPENAI_ENDPOINT],
            azure_content_safety_endpoint=os.environ[
                ENV_AZURE_CONTENT_SAFETY_ENDPOINT
            ],
            azure_content_safety_key=os.environ[ENV_AZURE_CONTENT_SAFETY_KEY],
            redis_connection_string=os.environ[ENV_REDIS_CONNECTION_STRING],
            applicationinsights_connection_string=os.environ[
                ENV_APPLICATIONINSIGHTS_CONNECTION_STRING
            ],
        )

    @classmethod
    def _has_required_env(cls) -> bool:
        return all(os.getenv(key) for key in cls._REQUIRED_ENV_KEYS)
