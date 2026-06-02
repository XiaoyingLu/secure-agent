@description('Name of the Key Vault (3–24 alphanumeric characters).')
param keyVaultName string

@description('Azure region for the Key Vault.')
param location string = resourceGroup().location

@description('Principal ID of the Container App system-assigned managed identity.')
param containerAppPrincipalId string

@description('Optional resource tags.')
param tags object = {}

@description('Built-in role: Key Vault Secrets User')
var keyVaultSecretsUserRoleDefinitionId = '4633458b-17bd-4259-b356-88601d906910'

resource keyVault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: keyVaultName
  location: location
  tags: tags
  properties: {
    tenantId: subscription().tenantId
    sku: {
      family: 'A'
      name: 'standard'
    }
    enableRbacAuthorization: true
    enabledForTemplateDeployment: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 7
  }
}

resource containerAppSecretsUserAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(keyVault.id, containerAppPrincipalId, keyVaultSecretsUserRoleDefinitionId)
  scope: keyVault
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      keyVaultSecretsUserRoleDefinitionId
    )
    principalId: containerAppPrincipalId
    principalType: 'ServicePrincipal'
  }
}

output keyVaultId string = keyVault.id
output keyVaultName string = keyVault.name
output keyVaultUri string = keyVault.properties.vaultUri
