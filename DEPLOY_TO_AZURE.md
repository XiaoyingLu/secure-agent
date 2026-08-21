# Deploy To Azure

This repository now supports a repeatable Azure deployment flow built around four pieces:

1. Publish the backend image to an existing or newly created Azure Container Registry with [scripts/publish-acr.ps1](c:/Users/amber.lu/Projects/secure-agent/scripts/publish-acr.ps1).
2. Deploy the runtime infrastructure with [infra/main.bicep](c:/Users/amber.lu/Projects/secure-agent/infra/main.bicep).
3. Deploy the React frontend from [web/](c:/Users/amber.lu/Projects/secure-agent/web/) to static hosting.
4. Use [docs/deployment-demo-guide.md](c:/Users/amber.lu/Projects/secure-agent/docs/deployment-demo-guide.md) when you want the shortest demo-oriented path.

## What `infra/main.bicep` Creates

- Log Analytics workspace for Container Apps logs
- Container Apps managed environment
- Secure Agent Container App with system-assigned managed identity
- AcrPull role assignment on an existing ACR
- Key Vault plus secret access for the Container App identity
- Key Vault secrets for the runtime settings the app requires
- Azure AI model deployment in the existing AI Services account through [infra/modules/ai-foundry.bicep](c:/Users/amber.lu/Projects/secure-agent/infra/modules/ai-foundry.bicep)

## What Must Already Exist

- Azure subscription and resource group
- Entra ID app registration for the API, configured per [infra/modules/app-registration.md](c:/Users/amber.lu/Projects/secure-agent/infra/modules/app-registration.md)
- Azure Container Registry containing the `secure-agent` image
- Existing Azure AI project endpoint used by the app
- Existing Azure AI Services account hosting model deployments
- Existing Redis instance and Application Insights resource, or at least their connection strings

This is a production baseline for the app and its immediate dependencies. It is not yet a full private-endpoint landing zone and it does not provision APIM.

## Required Secret And Setting Inputs

The deployment seeds Key Vault with the exact secret names read by [src/secure_agent/config.py](c:/Users/amber.lu/Projects/secure-agent/src/secure_agent/config.py):

- `ENTRA-TENANT-ID`
- `ENTRA-CLIENT-ID`
- `ENTRA-CLIENT-SECRET`
- `ENTRA-REDIRECT-URIS`
- `AZURE-OPENAI-ENDPOINT`
- `AZURE-CONTENT-SAFETY-ENDPOINT`
- `AZURE-CONTENT-SAFETY-KEY`
- `REDIS-CONNECTION-STRING`
- `APPLICATIONINSIGHTS-CONNECTION-STRING`
- `GRAPH-HEALTH-CHECK-TOKEN` optionally

The deployment also sets these non-secret Container App environment variables because the Foundry agent reads them directly:

- `AZURE_KEY_VAULT_URL`
- `AZURE_AI_PROJECT_ENDPOINT`
- `AZURE_AI_MODEL_DEPLOYMENT_NAME`
- `DEMO_MODE`
- `ENABLED_TOOLS`

## Step 0: Preflight Checks

Before provisioning anything, confirm local tools and Azure context:

```powershell
az --version
az bicep version
docker --version
node --version
npm --version

az login
az account set --subscription '<subscription-id>'
az account show --query "{name:name,id:id,tenantId:tenantId}" -o table
```

Confirm required existing Azure assets are available:

- Entra API app registration and API scope (`access_as_user`)
- Entra SPA app registration for frontend sign-in
- Azure AI Foundry project endpoint
- Azure AI Services account (model hosting)
- Redis and Application Insights connection strings
- DNS plan for backend host and frontend host

DNS plan checklist:

1. Reserve final public hostnames, for example:
  - `app.<your-domain>` for the frontend
  - `api.<your-domain>` for the backend or APIM endpoint
2. Decide API routing path:
  - preferred: browser -> APIM -> Container App
  - alternate: browser -> Container App directly
3. Create DNS records:
  - frontend host -> CNAME to static website host
  - API host -> CNAME to APIM gateway host (or Container App FQDN)
4. Confirm TLS coverage for both hosts (managed or custom certs) and enforce HTTPS-only access.
5. Update Entra redirect URIs to match final production URLs:
  - SPA redirect URI should match the frontend origin
  - API callback URI should end with `/auth/callback`
6. Verify end-to-end:
  - DNS resolution works publicly
  - browser shows valid cert chain
  - frontend sign-in callback and API calls succeed without CORS failures

## Step 1: Create The Resource Group

```powershell
$subscriptionId = '<subscription-id>'
$location = 'canadacentral'
$resourceGroup = 'rg-secure-agent-prod'

az login
az account set --subscription $subscriptionId
az group create --name $resourceGroup --location $location
```

## Step 2: Publish The Image To ACR

If the registry does not exist yet, let the script create it.

```powershell
$acrName = 'acrsecureagentprod'
$imageTag = '20260820.1'

pwsh -File ./scripts/publish-acr.ps1 `
  -SubscriptionId $subscriptionId `
  -ResourceGroup $resourceGroup `
  -AcrName $acrName `
  -ImageRepository 'secure-agent' `
  -ImageTag $imageTag `
  -CreateAcr
```

Use `-UseAcrBuild` if you want Azure to build the image instead of local Docker.

## Step 3: Gather Existing Azure Values

You need two existing values before the Bicep deployment:

- `projectEndpoint`: the Azure AI Foundry project endpoint used by the app
- `aiServicesId`: the Azure AI Services account resource ID used for model deployments

Example values:

```powershell
$projectEndpoint = 'https://<your-project>.services.ai.azure.com/api/projects/<project-name>'
$aiServicesId = '<ai-services-resource-id>'
```

## Step 4: Deploy The Infrastructure

Run a pre-deployment diff first:

```powershell
az deployment group what-if `
  --resource-group $resourceGroup `
  --template-file ./infra/main.bicep `
  --parameters `
    location=$location `
    environment=prod `
    workloadPrefix=agent `
    acrName=$acrName `
    imageRepository=secure-agent `
    imageTag=$imageTag `
    keyVaultName=$keyVaultName `
    projectEndpoint=$projectEndpoint `
    aiServicesId=$aiServicesId `
    entraTenantId='<tenant-id>' `
    entraClientId='<api-app-client-id>' `
    entraClientSecret='<api-app-client-secret>' `
    entraRedirectUris='https://<api-host>/auth/callback' `
    azureOpenAiEndpoint='https://<openai-resource>.openai.azure.com/openai/v1' `
    azureContentSafetyEndpoint='https://<content-safety>.cognitiveservices.azure.com/' `
    azureContentSafetyKey='<content-safety-key>' `
    redisConnectionString='<redis-connection-string>' `
    applicationInsightsConnectionString='<application-insights-connection-string>'
```

If the what-if output looks correct, apply the deployment:

```powershell
$keyVaultName = 'kvsecureagentprod01'

az deployment group create `
  --resource-group $resourceGroup `
  --template-file ./infra/main.bicep `
  --parameters `
    location=$location `
    environment=prod `
    workloadPrefix=agent `
    acrName=$acrName `
    imageRepository=secure-agent `
    imageTag=$imageTag `
    keyVaultName=$keyVaultName `
    projectEndpoint=$projectEndpoint `
    aiServicesId=$aiServicesId `
    entraTenantId='<tenant-id>' `
    entraClientId='<api-app-client-id>' `
    entraClientSecret='<api-app-client-secret>' `
    entraRedirectUris='https://<api-host>/auth/callback' `
    azureOpenAiEndpoint='https://<openai-resource>.openai.azure.com/openai/v1' `
    azureContentSafetyEndpoint='https://<content-safety>.cognitiveservices.azure.com/' `
    azureContentSafetyKey='<content-safety-key>' `
    redisConnectionString='<redis-connection-string>' `
    applicationInsightsConnectionString='<application-insights-connection-string>'
```

Recommended additions for your environment:

- `modelDeploymentName='model-router'` if you want a non-default deployment name
- `demoMode=true enabledTools='lookup_employee,lookup_it_tickets,search_policies,lookup_budget'` for a demo deployment

## Step 5: Verify Outputs

The deployment returns:

- `containerAppName`
- `containerAppUrl`
- `keyVaultUri`
- `projectEndpoint`
- `modelDeployment`

Check the health endpoint:

```powershell
$appUrl = az deployment group show `
  --resource-group $resourceGroup `
  --name main `
  --query properties.outputs.containerAppUrl.value `
  -o tsv

Invoke-RestMethod -Uri "$appUrl/health"
```

If you used a custom deployment name in the `az deployment group create` command, query that deployment name instead of `main`.

## Step 6: Register The Frontend SPA In Entra ID

Create or reuse a separate Entra app registration for the frontend SPA client.

- Platform type: `Single-page application`
- Redirect URI: your final frontend URL (for example `https://<frontend-host>/`)
- API permissions: delegated permission to your API scope (for example `api://<api-app-client-id>/access_as_user`)

Collect these values for the frontend build:

- `VITE_ENTRA_TENANT_ID`
- `VITE_ENTRA_CLIENT_ID` (SPA app client ID)
- `VITE_API_SCOPE` (delegated scope exposed by the backend API app)
- `VITE_API_BASE_URL` (public API base URL used by the browser)

## Step 7: Build The Frontend

From the repository root:

```powershell
cd web
npm ci

$env:VITE_ENTRA_TENANT_ID = '<tenant-id>'
$env:VITE_ENTRA_CLIENT_ID = '<spa-client-id>'
$env:VITE_API_SCOPE = 'api://<api-app-client-id>/access_as_user'
$env:VITE_API_BASE_URL = 'https://<public-api-host>'

npm run build
```

The production assets are generated in `web/dist`.

## Step 8: Publish Frontend Assets To Azure Static Website

Example using Azure Storage static website hosting:

```powershell
cd ..
$storageAccountName = 'stsecureagentwebprod01'

az storage account create `
  --resource-group $resourceGroup `
  --name $storageAccountName `
  --location $location `
  --sku Standard_LRS `
  --kind StorageV2

az storage blob service-properties update `
  --account-name $storageAccountName `
  --static-website `
  --index-document index.html `
  --404-document index.html

az storage blob upload-batch `
  --account-name $storageAccountName `
  --auth-mode login `
  --destination '$web' `
  --source ./web/dist `
  --overwrite

$frontendUrl = az storage account show `
  --resource-group $resourceGroup `
  --name $storageAccountName `
  --query primaryEndpoints.web `
  -o tsv

Write-Host "Frontend URL: $frontendUrl"
```

## Step 9: API Wiring Notes For Browser Calls

The frontend sends authenticated browser requests to `VITE_API_BASE_URL` (for example `/chat`, `/audit`, `/health`).

- If your frontend and backend are on different origins, configure CORS on the public API endpoint.
- If you front the API with APIM, configure CORS at APIM for the frontend origin.
- If you do not configure CORS, browser calls from the deployed frontend to the API will fail even when sign-in succeeds.

Recommended check from a browser devtools network tab:

1. `OPTIONS <api-base-url>/chat` returns success with expected `Access-Control-Allow-*` headers.
2. `POST <api-base-url>/chat` returns 200/4xx (not a CORS failure).

## Step 10: Validate Frontend Sign-In And Chat

- Open the frontend URL.
- Select **Sign in with Microsoft**.
- Confirm the popup returns to your frontend origin.
- Send a test message and verify the API response is shown in chat.

## Step 11: Configure Domain And TLS (Recommended)

- Map a custom domain to the frontend host.
- Map a custom domain to the backend/API host (or APIM host).
- Ensure HTTPS-only access and valid managed certificates on both endpoints.
- Update Entra redirect URIs to the final frontend and backend callback URLs.

## Step 12: Configure API Edge And CORS (Recommended)

For production, front the backend with APIM (or equivalent) and enforce:

- JWT validation policy at the edge.
- CORS allowlist limited to your frontend origin(s).
- Rate limiting/throttling to protect backend capacity.
- Request/response logging without storing sensitive payloads.

If the backend remains directly public, ensure equivalent controls are implemented before go-live.

## Step 13: Security Hardening Checklist

Before go-live, verify:

- Key Vault contains only required secrets and no plaintext test values.
- Container App has least-privilege role assignments only.
- No app-only Graph token usage path exists for user data calls.
- Content Safety and guardrails are enabled in runtime paths.
- `ENTRA_REDIRECT_URIS` and SPA redirect URIs are exact and environment-specific.
- Secret scanning is enabled in CI and passing.

## Step 14: Observability And Alerts

Configure monitoring before first production traffic:

- Application Insights availability test for `/health`.
- Alerts for API 5xx rate, latency, and Container App replica saturation.
- Alerts for failed deployments and repeated auth failures.
- Diagnostic retention aligned with your compliance requirements.

## Step 15: Smoke Tests And Rollback Plan

Run smoke tests after each deployment:

1. `/health` responds 200.
2. Frontend sign-in succeeds.
3. `/chat` round-trip succeeds with a delegated token.
4. Audit log records tool calls.

Prepare rollback steps ahead of time:

- Keep prior backend image tag available in ACR.
- Re-run deployment with previous `imageTag` to roll back runtime quickly.
- Keep prior frontend artifact package to republish static hosting if needed.
- Record rollback execution time and owner in your runbook.

## Post-Deployment Notes

- The Container App runs with a system-assigned managed identity and reads secrets from Key Vault at startup.
- The API image must already exist in ACR before deployment.
- The app expects the Entra redirect URI to end with `/auth/callback`.
- This template leaves ingress public by default. Put APIM, private networking, and stricter network controls in front of it before calling the result production-hardened.
- Frontend `VITE_*` values are compiled at build time. Rebuild and republish `web/dist` whenever these values change.