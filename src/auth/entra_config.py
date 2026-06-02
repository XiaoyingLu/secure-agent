"""Typed Entra ID app registration configuration loaded from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ENV_ENTRA_CLIENT_ID = "ENTRA_CLIENT_ID"
ENV_ENTRA_TENANT_ID = "ENTRA_TENANT_ID"
ENV_ENTRA_DELEGATED_SCOPES = "ENTRA_DELEGATED_SCOPES"
ENV_ENTRA_REDIRECT_URIS = "ENTRA_REDIRECT_URIS"


def _split_env_list(value: str | None) -> list[str]:
    if not value:
        return []

    parts: list[str] = []
    for line in value.splitlines():
        parts.extend(item.strip() for item in line.split(","))
    return [item for item in parts if item]


@dataclass(frozen=True)
class EntraConfig:
    """Entra ID app registration metadata.

    Attributes:
        client_id: Application (client) ID for the Entra app registration.
        tenant_id: Directory (tenant) ID that owns the app registration.
        delegated_scopes: Delegated scopes required by the agent.
        redirect_uris: Registered redirect URIs for auth-code flows.
    """

    client_id: str
    tenant_id: str
    delegated_scopes: list[str] = field(default_factory=list)
    redirect_uris: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, env_file: str | Path | None = ".env.local") -> EntraConfig:
        """Load Entra ID configuration from environment variables.

        Args:
            env_file: Optional dotenv file to load before reading process
                environment variables. Pass ``None`` to skip dotenv loading.

        Returns:
            Loaded EntraConfig instance.

        Raises:
            ValueError: If a required field is missing.
        """
        if env_file is not None:
            load_dotenv(env_file)

        config = cls(
            client_id=os.getenv(ENV_ENTRA_CLIENT_ID, "").strip(),
            tenant_id=os.getenv(ENV_ENTRA_TENANT_ID, "").strip(),
            delegated_scopes=_split_env_list(os.getenv(ENV_ENTRA_DELEGATED_SCOPES)),
            redirect_uris=_split_env_list(os.getenv(ENV_ENTRA_REDIRECT_URIS)),
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Validate that all required Entra ID registration fields are present.

        Raises:
            ValueError: If one or more required fields are blank or empty.
        """
        missing: list[str] = []
        if not self.client_id:
            missing.append(ENV_ENTRA_CLIENT_ID)
        if not self.tenant_id:
            missing.append(ENV_ENTRA_TENANT_ID)
        if not self.delegated_scopes:
            missing.append(ENV_ENTRA_DELEGATED_SCOPES)
        if not self.redirect_uris:
            missing.append(ENV_ENTRA_REDIRECT_URIS)

        if missing:
            raise ValueError(
                "Missing required Entra ID configuration fields: "
                + ", ".join(missing)
            )
