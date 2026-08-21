targetScope = 'resourceGroup'

@description('Short environment tag used in resource names: dev | test | prod.')
@allowed([
  'dev'
  'test'
  'prod'
])
param environment string = 'dev'

@description('Workload prefix, e.g. "agent". Combined with environment for unique names.')
@maxLength(12)
param workloadPrefix string = 'agent'

@description('HTTPS endpoint for the existing Azure AI Foundry project used by the app.')
param projectEndpoint string

@description('Resource ID of the Azure AI Services account that hosts the model deployment.')
param aiServicesId string

@description('Name of the model deployment to create inside the AI Services account.')
param gpt4DeploymentName string = 'gpt-4o-mini'

@description('Model version for the deployment.')
param gpt4ModelVersion string = '2024-07-18'

@description('Tokens-per-minute quota for the model deployment.')
@minValue(1)
@maxValue(200000)
param gpt4Capacity int = 10

var suffix = '${workloadPrefix}-${environment}'
var projectName = 'aip-${suffix}'

resource aiServices 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: last(split(aiServicesId, '/'))
}

resource gpt4Deployment 'Microsoft.CognitiveServices/accounts/deployments@2024-10-01' = {
  parent: aiServices
  name: gpt4DeploymentName
  sku: {
    name: 'Standard'
    capacity: gpt4Capacity
  }
  properties: {
    model: {
      format: 'OpenAI'
      name: 'gpt-4o-mini'
      version: gpt4ModelVersion
    }
    raiPolicyName: 'Microsoft.Default'
  }
}

@description('HTTPS endpoint for the AI project. Set as AZURE_AI_PROJECT_ENDPOINT in the app configuration.')
output projectEndpoint string = projectEndpoint

@description('Resource name of the Azure AI project for compatibility with earlier callers.')
output projectName string = projectName

@description('Name of the model deployment created inside the AI Services account.')
output gpt4DeploymentName string = gpt4Deployment.name

@description('Principal ID for compatibility with older callers; no Hub role assignment is required in this deployment model.')
output projectPrincipalId string = ''
