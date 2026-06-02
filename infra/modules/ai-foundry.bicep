/*
  infra/modules/ai-foundry.bicep
  ─────────────────────────────
  Provisions:
    • Azure AI Hub  (Microsoft.MachineLearningServices/workspaces, kind=Hub)
    • Azure AI Project (kind=Project, linked to the Hub)
    • gpt-4o model deployment via the AI Services / Cognitive Services connection
    • System-assigned Managed Identity on both Hub and Project
    • Role assignments so the Project MI can call the Hub and the AI Services account

  Upstream dependencies (must exist before this module runs):
    • A Storage Account  → hubStorageId
    • An Application Insights instance → hubAppInsightsId
    • An Azure Container Registry (optional) → hubContainerRegistryId
    • An Azure AI Services (Cognitive Services) account → aiServicesId
      (the account that hosts the gpt-4o model deployment)

  Outputs consumed by other modules:
    • projectEndpoint  – used by FoundryAgent to initialise AIProjectClient
    • projectName      – used by CI/CD to look up the project
    • hubName          – used by Defender / Monitor alert rules
*/

// ── Parameters ───────────────────────────────────────────────────────────────

@description('Azure region for all resources in this module.')
param location string = resourceGroup().location

@description('Short environment tag used in resource names: dev | test | prod.')
@allowed(['dev', 'test', 'prod'])
param environment string = 'dev'

@description('Workload prefix, e.g. "agent". Combined with environment for unique names.')
@maxLength(12)
param workloadPrefix string = 'agent'

@description('Resource ID of the Storage Account used by the AI Hub.')
param hubStorageId string

@description('Resource ID of the Application Insights instance used by the AI Hub.')
param hubAppInsightsId string

@description('Resource ID of the Azure Container Registry. Pass empty string to skip.')
param hubContainerRegistryId string = ''

@description('Resource ID of the Azure AI Services (Cognitive Services) account that hosts model deployments.')
param aiServicesId string

@description('The API endpoint of the AI Services account (e.g. https://<name>.openai.azure.com/).')
param aiServicesEndpoint string

@description('Name of the gpt-4o model deployment to create.')
param gpt4oDeploymentName string = 'gpt-4o'

@description('Azure OpenAI model version to deploy.')
param gpt4oModelVersion string = '2024-11-20'

@description('''
  Tokens-per-minute quota (thousands) for the gpt-4o deployment.
  Default 30 = 30,000 TPM. Adjust to match your subscription quota.
''')
@minValue(1)
@maxValue(2000)
param gpt4oCapacityK int = 30

@description('Object ID of a user or group to assign the Azure AI Developer role on the Project (optional).')
param developerPrincipalId string = ''

// ── Variables ─────────────────────────────────────────────────────────────────

var suffix     = '${workloadPrefix}-${environment}'
var hubName    = 'aih-${suffix}'
var projectName = 'aip-${suffix}'

// Built-in role definition IDs (stable across all tenants)
var roleAzureAIDeveloper    = '64702f94-c441-49e6-a78b-ef80e0188fee'
var roleStorageBlobContrib  = 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'

// ── AI Hub ────────────────────────────────────────────────────────────────────

resource hub 'Microsoft.MachineLearningServices/workspaces@2024-04-01' = {
  name: hubName
  location: location
  kind: 'Hub'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    friendlyName: 'AI Hub — ${suffix}'
    description: 'Enterprise AI Agent hub (${environment})'

    storageAccount: hubStorageId
    applicationInsights: hubAppInsightsId
    containerRegistry: empty(hubContainerRegistryId) ? null : hubContainerRegistryId

    publicNetworkAccess: 'Disabled'   // All traffic via Private Endpoint (infra/modules/vnet.bicep)

    // Require customer-managed keys or leave as platform-managed (default)
    encryption: {
      status: 'Disabled'             // Switch to 'Enabled' + keyVaultProperties for CMK
    }
  }

  tags: {
    environment: environment
    workload: workloadPrefix
    managedBy: 'bicep'
  }
}

// ── AI Services connection on the Hub ────────────────────────────────────────
// This connection lets the Hub (and all its Projects) call the AI Services
// account for model inference without re-supplying credentials.

resource aiServicesConnection 'Microsoft.MachineLearningServices/workspaces/connections@2024-04-01' = {
  parent: hub
  name: 'ai-services-connection'
  properties: {
    category: 'AzureOpenAI'
    target: aiServicesEndpoint
    authType: 'AAD'                  // Managed Identity — no stored API key
    isSharedToAll: true              // All Projects in this Hub inherit the connection
    metadata: {
      ApiVersion: '2024-05-01-preview'
      ApiType: 'azure'
      ResourceId: aiServicesId
    }
  }
}

// ── AI Project ────────────────────────────────────────────────────────────────

resource project 'Microsoft.MachineLearningServices/workspaces@2024-04-01' = {
  name: projectName
  location: location
  kind: 'Project'
  identity: {
    type: 'SystemAssigned'
  }
  properties: {
    friendlyName: 'Enterprise AI Agent — ${suffix}'
    description: 'Agent project: email / calendar / SharePoint MCP tools (${environment})'
    hubResourceId: hub.id
    publicNetworkAccess: 'Disabled'
  }
  tags: {
    environment: environment
    workload: workloadPrefix
    managedBy: 'bicep'
  }
  dependsOn: [aiServicesConnection]
}

// ── gpt-4o Deployment ─────────────────────────────────────────────────────────
// Deployed on the AI Services account (not the Hub directly).
// The Hub's AI Services connection makes it available to the Project.

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-04-01-preview' existing = {
  name: last(split(aiServicesId, '/'))
  scope: resourceGroup()
}

resource gpt4oDeployment 'Microsoft.CognitiveServices/accounts/deployments@2024-04-01-preview' = {
  parent: aiServices
  name: gpt4oDeploymentName
  sku: {
    name: 'GlobalStandard'           // Use Standard for single-region quota
    capacity: gpt4oCapacityK
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o'
      version: gpt4oModelVersion
    }
    raiPolicyName: 'Microsoft.DefaultV2'   // Responsible AI policy — do not remove
    versionUpgradeOption: 'OnceNewDefaultVersionAvailable'
  }
}

// ── Role assignments ──────────────────────────────────────────────────────────

// Project MI → Azure AI Developer on the Hub
// Required for the Project to submit inference requests via the Hub connection.
resource projectMiHubRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(hub.id, project.identity.principalId, roleAzureAIDeveloper)
  scope: hub
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAzureAIDeveloper)
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

// Project MI → Storage Blob Data Contributor on the Hub's storage account
// Required for the Project to read/write experiment artifacts and logs.
resource projectMiStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(hubStorageId, project.identity.principalId, roleStorageBlobContrib)
  scope: resourceGroup()            // Scoped to RG; tighten to the storage resource if preferred
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleStorageBlobContrib)
    principalId: project.identity.principalId
    principalType: 'ServicePrincipal'
    condition: '((!(ActionMatches{\'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read\'})) OR (@Resource[Microsoft.Storage/storageAccounts:id] StringEquals \'${hubStorageId}\'))'
    conditionVersion: '2.0'
  }
}

// Optional: grant a human developer the Azure AI Developer role on the Project
// so they can run experiments and inspect traces without Contributor rights.
resource developerRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(developerPrincipalId)) {
  name: guid(project.id, developerPrincipalId, roleAzureAIDeveloper)
  scope: project
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAzureAIDeveloper)
    principalId: developerPrincipalId
    principalType: 'User'
  }
}

// ── Outputs ───────────────────────────────────────────────────────────────────

@description('HTTPS endpoint for the AI Project. Set as AZURE_AI_PROJECT_ENDPOINT in Key Vault.')
output projectEndpoint string = project.properties.discoveryUrl

@description('Resource name of the AI Project (used by azd and CLI tooling).')
output projectName string = project.name

@description('Resource name of the AI Hub.')
output hubName string = hub.name

@description('Principal ID of the Project system-assigned Managed Identity.')
output projectPrincipalId string = project.identity.principalId

@description('Name of the gpt-4o deployment (pass to FoundryAgent as model name).')
output gpt4oDeploymentName string = gpt4oDeployment.name
