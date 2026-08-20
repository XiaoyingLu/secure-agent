# Secure Agent

This project is a FastAPI-based secure AI agent with Microsoft Entra ID authentication, delegated Graph access, and Foundry tool orchestration.

## Local setup

### 1. Create a virtual environment

```powershell
cd C:\Users\amber.lu\Projects\secure-agent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

### 2. Install dependencies

```powershell
python -m pip install --upgrade pip
python -m pip install -e .
```

### 3. Configure local environment variables

Copy the sample file and fill in the values for your tenant and Azure resources:

```powershell
Copy-Item .env.example .env.local
notepad .env.local
```

Required local values typically include:

```env
ENTRA_TENANT_ID=<your-tenant-id>
ENTRA_CLIENT_ID=<your-api-app-registration-client-id>
ENTRA_CLIENT_SECRET=<your-api-client-secret>
ENTRA_REDIRECT_URIS=http://127.0.0.1:8000/auth/callback

AZURE_AI_PROJECT_ENDPOINT=https://<your-project>.services.ai.azure.com/api/projects/<project-name>
AZURE_AI_MODEL_DEPLOYMENT_NAME=<your-model-deployment-name>

AZURE_OPENAI_ENDPOINT=https://<your-openai-resource>.openai.azure.com/openai/v1
AZURE_CONTENT_SAFETY_ENDPOINT=https://<your-content-safety>.cognitiveservices.azure.com/
AZURE_CONTENT_SAFETY_KEY=<your-content-safety-key>
REDIS_CONNECTION_STRING=
APPLICATIONINSIGHTS_CONNECTION_STRING=

DEMO_MODE=true
ENABLED_TOOLS=lookup_employee,lookup_it_tickets,search_policies,lookup_budget
```

Notes:
- `ENTRA_REDIRECT_URIS` is a comma-separated list; a single callback is enough for local development.
- `DEMO_MODE=true` enables the demo tools. Leave it false for production-style tool discovery.
- `ENABLED_TOOLS` is optional; leave it unset to allow all discovered tools when the env is blank.

### 4. Start the backend

From the repo root:

```powershell
python -m secure_agent
```

This starts the server on `http://127.0.0.1:8000` with reload enabled.

You can also use:

```powershell
uvicorn secure_agent.app:app --reload --port 8000
```

### 5. Verify the app is running

Open these in a browser:

- `http://127.0.0.1:8000/health`
- `http://127.0.0.1:8000/docs`

### 6. Run the frontend (optional)

A Vite-based React client is included in `web/`.

```powershell
cd web
npm install
npm run dev
```

Then open `http://localhost:5173` and sign in with Microsoft.

### 7. Local container build

```powershell
docker build -t secure-agent .
docker run -p 8000:8000 --env-file .env.local secure-agent
```

## Build And Push Container To Azure Container Registry

### Local One-Command Publish (PowerShell)

Use [scripts/publish-acr.ps1](scripts/publish-acr.ps1) from the repo root.

```powershell
./scripts/publish-acr.ps1 `
	-SubscriptionId "<subscription-id>" `
	-ResourceGroup "<resource-group>" `
	-AcrName "<acr-name>" `
	-ImageRepository "secure-agent" `
	-ImageTag "20260629.1"
```

If you run from Git Bash/WSL, invoke with PowerShell explicitly:

```bash
pwsh -File ./scripts/publish-acr.ps1 \
	-SubscriptionId "<subscription-id>" \
	-ResourceGroup "<resource-group>" \
	-AcrName "<acr-name>" \
	-ImageRepository "secure-agent" \
	-ImageTag "20260629.1"
```

If the registry does not exist yet, add `-CreateAcr`.

If Docker Desktop is not running or unavailable locally, build and push remotely via ACR Tasks:

```powershell
./scripts/publish-acr.ps1 `
	-SubscriptionId "<subscription-id>" `
	-ResourceGroup "<resource-group>" `
	-AcrName "<acr-name>" `
	-ImageRepository "secure-agent" `
	-ImageTag "20260629.1" `
	-CreateAcr `
	-UseAcrBuild
```

The script will:
- set the active subscription
- create ACR when requested
- build the Docker image
- log in to ACR
- tag and push `latest` and your version tag

### CI Publish (GitHub Actions + OIDC)

Workflow file: [.github/workflows/publish-acr.yml](.github/workflows/publish-acr.yml)

Required repository variables:
- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `ACR_NAME`

Trigger options:
- automatic on push to `main`
- manual via `workflow_dispatch` with optional `image_tag`

## React Chat Front-End (MSAL)

A standard React + Vite chat client is available in `web/`.

### 1. Configure Entra ID for SPA

Create `web/.env.local` from `web/.env.example` and set:

- `VITE_ENTRA_TENANT_ID`: your tenant id
- `VITE_ENTRA_CLIENT_ID`: SPA app registration client id
- `VITE_API_SCOPE`: API delegated scope (required), for example `api://<api-app-client-id>/access_as_user`.

Notes:
- In Entra app registration for the SPA client, add a redirect URI for `http://localhost:5173` (Single-page application).
- Ensure the scope in `VITE_API_SCOPE` exists on the API app registration and the SPA app has permission to it.
- If you see `AADSTS9002326`, your client app is configured as Web instead of SPA for browser token redemption. In Entra, add the SPA platform and keep `http://localhost:5173` as a SPA redirect URI.

### 2. Install and run the front-end

```powershell
cd web
npm install
npm run dev
```

The app runs on `http://localhost:5173` and proxies `/chat`, `/health`, and `/auth` to `http://127.0.0.1:8000` by default.

### 3. Run backend with the front-end

From the repo root (in a separate terminal):

```powershell
python -m secure_agent
```

Then open `http://localhost:5173`, sign in with Microsoft, and send chat messages.

### 4. Production API base URL

Set `VITE_API_BASE_URL` (for example, your APIM endpoint) to call a deployed backend directly instead of the Vite proxy.
