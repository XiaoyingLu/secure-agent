# Deploy To Azure

This repository now supports a repeatable Azure deployment flow built around three pieces:

1. Publish the backend image to an existing or newly created Azure Container Registry with [scripts/publish-acr.ps1](c:/Users/amber.lu/Projects/secure-agent/scripts/publish-acr.ps1).
2. Deploy the runtime infrastructure with [infra/main.bicep](c:/Users/amber.lu/Projects/secure-agent/infra/main.bicep).
3. Use [docs/deployment-demo-guide.md](c:/Users/amber.lu/Projects/secure-agent/docs/deployment-demo-guide.md) when you want the shortest demo-oriented path.

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

## Post-Deployment Notes

- The Container App runs with a system-assigned managed identity and reads secrets from Key Vault at startup.
- The API image must already exist in ACR before deployment.
- The app expects the Entra redirect URI to end with `/auth/callback`.
- This template leaves ingress public by default. Put APIM, private networking, and stricter network controls in front of it before calling the result production-hardened.