# Project Overview

This is an enterprise-grade AI agent that enables users to securely query their Microsoft 365 data (email, calendar, SharePoint) through natural language, using Microsoft-recommended authentication patterns (Entra ID, OAuth 2.0 delegation, On-Behalf-Of flow) and MCP-compliant tool servers orchestrated by Azure AI Foundry.

## Goal

Deliver a production-hardened AI agent that enforces zero-trust, least-privilege access — every data request is scoped to the authenticated user's own permissions via delegated tokens, never service-principal credentials — while maintaining <2s end-to-end response latency and full audit traceability.

---

# Technology Stack

- **Agent Runtime:** Azure AI Foundry (gpt-4o), Foundry Agent SDK (Python)
- **Auth & Identity:** Microsoft Entra ID, MSAL Python (`msal`), OAuth 2.0 Auth-code + PKCE, On-Behalf-Of (OBO) flow
- **MCP Tool Servers:** Python (`mcp` SDK), Pydantic v2 for input validation
- **API Gateway:** Azure API Management (APIM) with `validate-jwt` policy
- **Backend / API:** FastAPI (Python 3.12), Uvicorn
- **Infrastructure:** Azure Container Apps, Azure Virtual Network, Private Endpoints
- **Secrets:** Azure Key Vault, `DefaultAzureCredential` (Managed Identity in prod)
- **Storage:** Azure Table Storage (audit log), Azure Blob Storage, Azure Cache for Redis (semantic cache)
- **Observability:** Azure Monitor, Application Insights (`azure-monitor-opentelemetry`)
- **Security:** Azure AI Content Safety, Microsoft Defender for Containers
- **IaC:** Bicep, GitHub Actions with Workload Identity Federation (WIF)
- **Testing:** Pytest, pytest-asyncio, pytest-mock, Playwright (E2E)
- **Linting / Formatting:** Ruff, Black, Pyright (strict)

---

# Project Architecture

```
secure-agent/
├── .github/
│   └── workflows/
│       ├── ci.yml              # lint + tests + security checks
│       └── deploy.yml          # Bicep/Azure deployment flow
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
│   ├── main.py                 # bootstrap entry
│   ├── config.py               # settings loader / env config
│   ├── mcp_server.py           # compatibility export for MCP server
│   ├── secure_agent/
│   │   ├── __init__.py         # app factory and lazy package export
│   │   ├── __main__.py         #python -m secure_agent entry
│   │   ├── app.py              # FastAPI app factory + middleware wiring
│   │   ├── bootstrap.py        # lifecycle startup/shutdown hooks
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── deps.py
│   │   │   └── routes/
│   │   │       ├── auth.py
│   │   │       ├── audit.py
│   │   │       ├── chat.py
│   │   │       └── health.py
│   │   ├── auth/
│   │   │   ├── __init__.py
│   │   │   ├── entra_config.py
│   │   │   ├── msal_client.py
│   │   │   ├── obo_client.py
│   │   │   ├── rbac.py
│   │   │   └── token_validator.py
│   │   ├── agent/
│   │   │   ├── __init__.py
│   │   │   ├── foundry_agent.py
│   │   │   ├── guardrails.py
│   │   │   └── system_prompt.txt
│   │   ├── graph/
│   │   │   ├── __init__.py
│   │   │   └── graph_client.py
│   │   ├── tools/
│   │   │   ├── __init__.py
│   │   │   ├── base_tool.py
│   │   │   ├── calendar_tool.py
│   │   │   ├── email_tool.py
│   │   │   ├── sharepoint_tool.py
│   │   │   └── demo/
│   │   │       ├── __init__.py
│   │   │       ├── budget_tool.py
│   │   │       ├── hr_tool.py
│   │   │       ├── it_tool.py
│   │   │       └── policy_tool.py
│   │   ├── audit/
│   │   │   ├── __init__.py
│   │   │   └── audit_logger.py
│   │   ├── cache/
│   │   │   └── semantic_cache.py
│   │   ├── security/
│   │   │   ├── __init__.py
│   │   │   └── token_guard.py
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── chat_service.py
│   │   │   └── runtime_service.py
│   │   ├── mcp/
│   │   │   ├── __init__.py
│   │   │   ├── registry.py
│   │   │   └── server.py
│   │   └── utils/
│   │       └── logging.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── e2e/
├── web/
│   ├── src/
│   ├── package.json
│   ├── vite.config.ts
│   └── index.html
├── .env.example
├── .gitignore
├── CLAUDE.md
├── Dockerfile
├── README.md
├── pyproject.toml
└── pytest.ini
```

- **Main App Entry:** `src/secure_agent/__main__.py` and `src/secure_agent/app.py`
- **Auth Middleware:** `src/secure_agent/auth/token_validator.py`
- **Agent Entrypoint:** `src/secure_agent/agent/foundry_agent.py`
- **Graph Client:** `src/secure_agent/graph/graph_client.py`
- **MCP Tools:** `src/secure_agent/tools/`
- **API Routes:** `src/secure_agent/api/routes/`
- **Runtime Lifecycle:** `src/secure_agent/bootstrap.py` and `src/secure_agent/services/runtime_service.py`
- **IaC:** `infra/`

---

# Key Commands

Run these exact commands in the terminal when interacting with the project:

- **Install:** `pip install -e ".[dev]"`
- **Run Locally:** `python -m secure_agent`
- **Run Locally (Uvicorn direct):** `uvicorn secure_agent.app:app --reload --port 8000`
- **Run Tests:** `pytest tests/ -v`
- **Run Unit Tests Only:** `pytest tests/unit/ -v`
- **Run with Coverage:** `pytest tests/ --cov=src --cov-report=term-missing`
- **Lint:** `ruff check . && pyright`
- **Format:** `black . && ruff check --fix .`
- **Build Container:** `docker build -t enterprise-ai-agent .`
- **Deploy Infra (dry run):** `az deployment sub what-if -f infra/main.bicep -l canadacentral`
- **Deploy Infra:** `az deployment sub create -f infra/main.bicep -l canadacentral`

---

# Environment Variables

All secrets are fetched from **Azure Key Vault at startup** via `DefaultAzureCredential`. Never set secrets as plain environment variables in production.

| Variable | Source | Description |
|---|---|---|
| `AZURE_KEY_VAULT_URL` | Env var (non-secret) | Key Vault URI |
| `AZURE_CLIENT_ID` | Managed Identity | Set automatically in Azure |
| `ENTRA_TENANT_ID` | Key Vault secret | Entra ID tenant |
| `ENTRA_CLIENT_ID` | Key Vault secret | App registration client ID |
| `ENTRA_CLIENT_SECRET` | Key Vault secret | App registration secret (dev only) |
| `AZURE_OPENAI_ENDPOINT` | Key Vault secret | Foundry / AOAI endpoint |
| `AZURE_CONTENT_SAFETY_ENDPOINT` | Key Vault secret | Azure AI Content Safety endpoint |
| `AZURE_CONTENT_SAFETY_KEY` | Key Vault secret | Azure AI Content Safety key |
| `REDIS_CONNECTION_STRING` | Key Vault secret | Azure Cache for Redis |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Key Vault secret | App Insights |

For local development, copy `.env.example` to `.env.local` and populate with dev tenant values. **Never commit `.env.local`.**

---

# Coding Standards & Preferences

- **Architecture:** Keep components strictly modular — one responsibility per file. MCP tools must extend `BaseTool` in `src/secure_agent/tools/base_tool.py`. Never call Graph API directly from routes; always go through `src/secure_agent/graph/graph_client.py`.
- **Naming:** `snake_case` for all Python files, functions, and variables. `PascalCase` for classes. Bicep files use `camelCase` parameter names.
- **Auth invariant:** MCP tools **must always** receive and forward the user's delegated OBO token. Never use a service principal or app-only token for Graph calls. This is the core security contract of the project.
- **Formatting:** Black (line length 88) + Ruff. All code must pass `ruff check .` and `pyright` before commit.
- **Type hints:** All functions must have full type annotations. Pyright strict mode is enforced.
- **Validation:** All MCP tool inputs must be validated with Pydantic v2 models. Never accept raw `dict` inputs from the agent.
- **Documentation:** Add docstrings (Google style) to all public functions and classes. Include `Args:`, `Returns:`, and `Raises:` sections.
- **Error handling:** Never let raw exceptions bubble to the API surface. Catch at the route level, log via App Insights, return structured `{"error": ..., "code": ...}` JSON.
- **Logging:** Use `logging` (stdlib) with structured JSON formatter. Never use `print()` in any source file.

### Prohibitions — Never Do These

- ❌ Do not hard-code secrets, tokens, client secrets, or connection strings anywhere in source or IaC files.
- ❌ Do not use `requests` for Graph API calls — use `httpx` (async) via `src/secure_agent/graph/graph_client.py`.
- ❌ Do not call Graph API with app-only (client credentials) tokens. Delegated OBO only.
- ❌ Do not bypass the guardrails layer (`src/secure_agent/secure_agent/agent/guardrails.py`) when returning LLM output to the user.
- ❌ Do not store user data or conversation history in the application database — the audit log records tool-call metadata only, not content.
- ❌ Do not use `console.log` / `print()` in production code paths.
- ❌ Do not deploy any resource with a public endpoint — all Azure services must use Private Endpoints inside the VNet.
- ❌ Do not merge a PR that has failing `ruff`, `pyright`, or `pytest` checks.

---

# Security Requirements

These are non-negotiable and must be validated in every PR:

1. **Token forwarding:** Every Graph API call must carry the user's OBO-exchanged delegated access token. Audit this in code review.
2. **Secret hygiene:** Run `credscan` (Microsoft Security DevOps Action) on every PR. Any detected secret auto-blocks merge.
3. **Input sanitisation:** All user inputs must pass through `src/secure_agent/agent/guardrails.py` before reaching the LLM.
4. **Audit logging:** Every MCP tool invocation must write a record to Azure Table Storage via `src/secure_agent/audit/audit_logger.py` before returning its result.
5. **Content Safety:** All LLM outputs must pass Azure AI Content Safety filtering before being returned to the user.

---

# Workflow & Guidelines

1. **Explore first:** Before making any change, read `pyproject.toml`, the relevant module's existing tests, and any related Bicep module. Understand before you edit.
2. **Plan before implementing:** For any change beyond a single-line fix, propose your approach and wait for explicit approval before writing code. State which files you'll touch and why.
3. **Test-driven:** Write or update tests before (or alongside) implementation. New tool servers require unit tests with mocked Graph responses and an integration test with a real dev-tenant token.
4. **Security review:** For any change touching `src/auth/`, `src/tools/`, or `infra/`, explicitly call out the security implications in your plan.
5. **Commit-ready standard:** Code is only commit-ready when `ruff check .`, `pyright`, and `pytest tests/ --cov=src` all pass locally. State this explicitly before suggesting a commit.
6. **Infra changes:** All Azure resource changes go through Bicep — never use `az` CLI one-liners to modify production resources. Run `what-if` before `create`.
7. **No scope creep:** Implement exactly what was agreed in the plan. If you discover something adjacent that should change, flag it as a separate suggestion rather than bundling it in.
