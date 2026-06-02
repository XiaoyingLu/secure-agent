import pytest

from auth.entra_config import (
    ENV_ENTRA_CLIENT_ID,
    ENV_ENTRA_DELEGATED_SCOPES,
    ENV_ENTRA_REDIRECT_URIS,
    ENV_ENTRA_TENANT_ID,
    EntraConfig,
)


@pytest.fixture(autouse=True)
def clear_entra_env(monkeypatch):
    for key in (
        ENV_ENTRA_CLIENT_ID,
        ENV_ENTRA_TENANT_ID,
        ENV_ENTRA_DELEGATED_SCOPES,
        ENV_ENTRA_REDIRECT_URIS,
    ):
        monkeypatch.delenv(key, raising=False)


def test_load_from_env_file(tmp_path):
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        "\n".join(
            [
                f"{ENV_ENTRA_CLIENT_ID}=client-id",
                f"{ENV_ENTRA_TENANT_ID}=tenant-id",
                f"{ENV_ENTRA_DELEGATED_SCOPES}=User.Read, Mail.Read, Calendars.Read",
                f"{ENV_ENTRA_REDIRECT_URIS}=http://127.0.0.1:8000/callback, "
                "https://agent.example.com/callback",
            ]
        )
    )

    config = EntraConfig.load(env_file)

    assert config.client_id == "client-id"
    assert config.tenant_id == "tenant-id"
    assert config.delegated_scopes == ["User.Read", "Mail.Read", "Calendars.Read"]
    assert config.redirect_uris == [
        "http://127.0.0.1:8000/callback",
        "https://agent.example.com/callback",
    ]


def test_load_from_process_environment(monkeypatch):
    monkeypatch.setenv(ENV_ENTRA_CLIENT_ID, "client-id")
    monkeypatch.setenv(ENV_ENTRA_TENANT_ID, "tenant-id")
    monkeypatch.setenv(ENV_ENTRA_DELEGATED_SCOPES, "User.Read\nMail.Read")
    monkeypatch.setenv(ENV_ENTRA_REDIRECT_URIS, "http://127.0.0.1:8000/callback")

    config = EntraConfig.load(env_file=None)

    assert config.delegated_scopes == ["User.Read", "Mail.Read"]


def test_validate_raises_for_missing_required_fields():
    config = EntraConfig(
        client_id="",
        tenant_id="tenant-id",
        delegated_scopes=[],
        redirect_uris=[],
    )

    with pytest.raises(ValueError, match=ENV_ENTRA_CLIENT_ID):
        config.validate()


def test_load_raises_for_missing_env(monkeypatch):
    monkeypatch.setenv(ENV_ENTRA_CLIENT_ID, "client-id")

    with pytest.raises(ValueError, match=ENV_ENTRA_TENANT_ID):
        EntraConfig.load(env_file=None)
