# Cleaned-Up Folder Structure

```text
secure-agent/
├── .github/
│   └── workflows/
│       ├── ci.yml
│       └── deploy.yml
├── docs/
│   ├── architecture/
│   ├── deployment/
│   └── security/
├── infra/
│   ├── main.bicep
│   ├── modules/
│   │   ├── ai-foundry.bicep
│   │   ├── app-registration.md
│   │   └── keyvault.bicep
├── scripts/
│   ├── publish-acr.ps1
│   └── bootstrap-dev.ps1
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── main.py
│   ├── mcp_server.py
│   └── secure_agent/
│       ├── __init__.py
│       ├── __main__.py
│       ├── app.py
│       ├── bootstrap.py
│       ├── agent/
│       │   ├── __init__.py
│       │   ├── foundry_agent.py
│       │   ├── guardrails.py
│       │   └── system_prompt.txt
│       ├── api/
│       │   ├── __init__.py
│       │   └── routes/
│       │       ├── __init__.py
│       │       ├── auth.py
│       │       ├── audit.py
│       │       ├── chat.py
│       │       └── health.py
│       ├── auth/
│       │   ├── __init__.py
│       │   ├── entra_config.py
│       │   ├── msal_client.py
│       │   ├── obo_client.py
│       │   ├── rbac.py
│       │   └── token_validator.py
│       ├── audit/
│       │   ├── __init__.py
│       │   └── audit_logger.py
│       ├── graph/
│       │   ├── __init__.py
│       │   └── graph_client.py
│       ├── mcp/
│       │   ├── __init__.py
│       │   ├── registry.py
│       │   └── server.py
│       ├── security/
│       │   ├── __init__.py
│       │   └── token_guard.py
│       ├── services/
│       │   ├── __init__.py
│       │   ├── chat_service.py
│       │   └── runtime_service.py
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── base_tool.py
│       │   ├── calendar_tool.py
│       │   ├── email_tool.py
│       │   ├── sharepoint_tool.py
│       │   └── demo/
│       │       ├── __init__.py
│       │       ├── budget_tool.py
│       │       ├── hr_tool.py
│       │       ├── it_tool.py
│       │       └── policy_tool.py
│       └── utils/
│           └── logging.py
├── tests/
│   ├── __init__.py
│   ├── integration/
│   │   ├── integration_token_check.py
│   │   └── test_foundry_agent.py
│   ├── unit/
│   │   ├── test_audit_logger.py
│   │   ├── test_audit_route.py
│   │   ├── test_auth_route.py
│   │   ├── test_calendar_tool.py
│   │   ├── test_chat_route.py
│   │   ├── test_config.py
│   │   ├── test_demo_tools.py
│   │   ├── test_email_tool.py
│   │   ├── test_entra_config.py
│   │   ├── test_foundry_agent_guardrails.py
│   │   ├── test_foundry_agent_tool_discovery.py
│   │   ├── test_graph_client.py
│   │   ├── test_guardrails.py
│   │   ├── test_health_route.py
│   │   ├── test_mcp_tools_server.py
│   │   ├── test_msal_client.py
│   │   ├── test_obo_client.py
│   │   ├── test_rbac.py
│   │   ├── test_sharepoint_tool.py
│   │   └── test_token_validator.py
│   └── test_api.py
├── web/
│   ├── index.html
│   ├── package.json
│   ├── tsconfig.json
│   ├── tsconfig.node.json
│   ├── vite.config.ts
│   └── src/
│       ├── api.ts
│       ├── App.tsx
│       ├── main.tsx
│       ├── msalConfig.ts
│       ├── styles.css
│       └── vite-env.d.ts
├── .env.example
├── .gitignore
├── CLAUDE.md
├── Dockerfile
├── README.md
├── pyproject.toml
├── pytest.ini
├── sitecustomize.py
└── app.py
```

This is the canonical package structure used by the app runtime and tests. Legacy compatibility modules may remain temporarily during migration, but the source of truth is the package under `src/secure_agent`.
