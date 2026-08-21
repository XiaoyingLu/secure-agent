targetScope = 'resourceGroup'

@description('Azure region for all resources in this deployment.')
param location string = resourceGroup().location

@description('Short environment tag used in resource names: dev | test | prod.')
@allowed([
  'dev'
  'test'
  'prod'
])
param environment string = 'dev'

@description('Workload prefix used when composing resource names.')
@maxLength(12)
param workloadPrefix string = 'agent'

@description('Name of an existing Azure Container Registry that already contains the secure-agent image.')
param acrName string

@description('Repository name inside the existing Azure Container Registry.')
param imageRepository string = 'secure-agent'

@description('Image tag to deploy from the existing Azure Container Registry.')
param imageTag string = 'latest'

@description('Name of the Key Vault to create for runtime secrets.')
param keyVaultName string

@description('HTTPS endpoint for the existing Azure AI Foundry project used by the app.')
param projectEndpoint string

@description('Resource ID of the Azure AI Services account that hosts model deployments.')
param aiServicesId string

@description('Entra tenant ID used by the API application registration.')
param entraTenantId string

@description('Entra client ID used by the API application registration.')
param entraClientId string

@secure()
@description('Entra client secret used for confidential-client login flows.')
param entraClientSecret string

@description('Comma-separated redirect URIs for the deployed API, including /auth/callback.')
param entraRedirectUris string

@description('Azure OpenAI endpoint consumed by the application runtime.')
param azureOpenAiEndpoint string

@description('Azure Content Safety endpoint consumed by the application runtime.')
param azureContentSafetyEndpoint string

@secure()
@description('Azure Content Safety key consumed by the application runtime.')
param azureContentSafetyKey string

@secure()
@description('Redis connection string consumed by the application runtime.')
param redisConnectionString string

@secure()
@description('Application Insights connection string consumed by the application runtime.')
param applicationInsightsConnectionString string

@secure()
@description('Optional delegated token used by /health/auth for AgentAdmin checks.')
param graphHealthCheckToken string = ''

@description('Whether to enable demo mode in the deployed runtime.')
param demoMode bool = false

@description('Optional comma-separated demo tool allowlist for ENABLED_TOOLS.')
param enabledTools string = ''

@description('Azure OpenAI deployment name created inside the shared AI Services account.')
param modelDeploymentName string = 'gpt-4o-mini'

@description('Azure OpenAI model version for the deployment.')
param modelVersion string = '2024-07-18'

@description('Tokens-per-minute quota for the model deployment.')
@minValue(1)
@maxValue(200000)
param modelCapacity int = 10

@description('Minimum replica count for the Container App.')
@minValue(0)
param minReplicas int = 1

@description('Maximum replica count for the Container App.')
@minValue(1)
param maxReplicas int = 3

@description('vCPU allocation for the application container.')
param containerCpu int = 1

@description('Memory allocation for the application container.')
param containerMemory string = '2Gi'

@description('Whether the Container App ingress should be public.')
param ingressExternal bool = true

@description('Optional tags applied to created resources.')
param tags object = {}

var suffix = '${workloadPrefix}-${environment}'
var acrLoginServer = '${acrName}.azurecr.io'
var containerAppName = 'ca-${suffix}'
var containerAppEnvironmentName = 'cae-${suffix}'
var logAnalyticsWorkspaceName = 'log-${suffix}'
var keyVaultUri = 'https://${keyVaultName}.${az.environment().suffixes.keyvaultDns}'
var mergedTags = union({
  environment: environment
  workload: workloadPrefix
  managedBy: 'bicep'
}, tags)
var roleAcrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource logAnalyticsWorkspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logAnalyticsWorkspaceName
  location: location
  tags: mergedTags
  properties: {
    sku: {
      name: 'PerGB2018'
    }
    retentionInDays: 30
    publicNetworkAccessForIngestion: 'Enabled'
    publicNetworkAccessForQuery: 'Enabled'
  }
}

resource containerAppEnvironment 'Microsoft.App/managedEnvironments@2025-01-01' = {
  name: containerAppEnvironmentName
  location: location
  tags: mergedTags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logAnalyticsWorkspace.properties.customerId
        sharedKey: logAnalyticsWorkspace.listKeys().primarySharedKey
      }
    }
  }
}

module aiFoundry 'modules/ai-foundry.bicep' = {
  params: {
    environment: environment
    workloadPrefix: workloadPrefix
    projectEndpoint: projectEndpoint
    aiServicesId: aiServicesId
    gpt4DeploymentName: modelDeploymentName
    gpt4ModelVersion: modelVersion
    gpt4Capacity: modelCapacity
  }
}

resource containerApp 'Microsoft.App/containerApps@2025-01-01' = {
  name: containerAppName
  location: location
  identity: {
    type: 'SystemAssigned'
  }
  tags: mergedTags
  properties: {
    managedEnvironmentId: containerAppEnvironment.id
    configuration: {
      activeRevisionsMode: 'Single'
      ingress: {
        external: ingressExternal
        targetPort: 8000
        allowInsecure: false
        transport: 'Auto'
      }
      registries: [
        {
          server: acrLoginServer
          identity: 'system'
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'secure-agent'
          image: '${acrLoginServer}/${imageRepository}:${imageTag}'
          env: [
            {
              name: 'AZURE_KEY_VAULT_URL'
              value: keyVaultUri
            }
            {
              name: 'AZURE_AI_PROJECT_ENDPOINT'
              value: aiFoundry.outputs.projectEndpoint
            }
            {
              name: 'AZURE_AI_MODEL_DEPLOYMENT_NAME'
              value: aiFoundry.outputs.gpt4DeploymentName
            }
            {
              name: 'DEMO_MODE'
              value: demoMode ? 'true' : 'false'
            }
            {
              name: 'ENABLED_TOOLS'
              value: enabledTools
            }
          ]
          resources: {
            cpu: containerCpu
            memory: containerMemory
          }
        }
      ]
      scale: {
        minReplicas: minReplicas
        maxReplicas: maxReplicas
      }
    }
  }
}

resource acrPullRoleAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, containerApp.id, roleAcrPull)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleAcrPull)
    principalId: containerApp.identity.principalId
    principalType: 'ServicePrincipal'
  }
}

module keyVault 'modules/keyvault.bicep' = {
  params: {
    keyVaultName: keyVaultName
    location: location
    containerAppPrincipalId: containerApp.identity.principalId
    tags: mergedTags
  }
}

resource keyVaultRef 'Microsoft.KeyVault/vaults@2023-07-01' existing = {
  name: keyVaultName
}

resource entraTenantIdSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultRef
  name: 'ENTRA-TENANT-ID'
  properties: {
    value: entraTenantId
  }
  dependsOn: [
    keyVault
  ]
}

resource entraClientIdSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultRef
  name: 'ENTRA-CLIENT-ID'
  properties: {
    value: entraClientId
  }
  dependsOn: [
    keyVault
  ]
}

resource entraClientSecretSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultRef
  name: 'ENTRA-CLIENT-SECRET'
  properties: {
    value: entraClientSecret
  }
  dependsOn: [
    keyVault
  ]
}

resource entraRedirectUrisSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultRef
  name: 'ENTRA-REDIRECT-URIS'
  properties: {
    value: entraRedirectUris
  }
  dependsOn: [
    keyVault
  ]
}

resource azureOpenAiEndpointSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultRef
  name: 'AZURE-OPENAI-ENDPOINT'
  properties: {
    value: azureOpenAiEndpoint
  }
  dependsOn: [
    keyVault
  ]
}

resource azureContentSafetyEndpointSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultRef
  name: 'AZURE-CONTENT-SAFETY-ENDPOINT'
  properties: {
    value: azureContentSafetyEndpoint
  }
  dependsOn: [
    keyVault
  ]
}

resource azureContentSafetyKeySecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultRef
  name: 'AZURE-CONTENT-SAFETY-KEY'
  properties: {
    value: azureContentSafetyKey
  }
  dependsOn: [
    keyVault
  ]
}

resource redisConnectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultRef
  name: 'REDIS-CONNECTION-STRING'
  properties: {
    value: redisConnectionString
  }
  dependsOn: [
    keyVault
  ]
}

resource applicationInsightsConnectionStringSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: keyVaultRef
  name: 'APPLICATIONINSIGHTS-CONNECTION-STRING'
  properties: {
    value: applicationInsightsConnectionString
  }
  dependsOn: [
    keyVault
  ]
}

resource graphHealthCheckTokenSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = if (!empty(graphHealthCheckToken)) {
  parent: keyVaultRef
  name: 'GRAPH-HEALTH-CHECK-TOKEN'
  properties: {
    value: graphHealthCheckToken
  }
  dependsOn: [
    keyVault
  ]
}

output containerAppName string = containerApp.name
output containerAppUrl string = 'https://${containerApp.properties.configuration.ingress.fqdn}'
output keyVaultUri string = keyVaultUri
output projectEndpoint string = aiFoundry.outputs.projectEndpoint
output modelDeployment string = aiFoundry.outputs.gpt4DeploymentName
