targetScope = 'resourceGroup'

@description('Nombre corto del entorno, por ejemplo dev o demo.')
@minLength(2)
@maxLength(12)
param environmentName string = 'dev'

@description('Region de Functions y Storage. Confirmar disponibilidad de Flex Consumption.')
param location string = resourceGroup().location

@description('Region compatible con Static Web Apps Free.')
param staticLocation string = 'centralus'

// Los nombres globales llevan un sufijo estable para evitar colisiones entre suscripciones.
var suffix = toLower(uniqueString(subscription().subscriptionId, resourceGroup().name, environmentName))
var storageName = 'sttelecorp${take(suffix, 10)}'
var functionName = 'red-telecorp-estado-api-${take(suffix, 8)}'
var staticName = 'red-telecorp-estado-publico-${take(suffix, 8)}'
var storageConnection = 'DefaultEndpointsProtocol=https;AccountName=${storageName};AccountKey=${storage.listKeys().keys[0].value};EndpointSuffix=${environment().suffixes.storage}'

resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  sku: {
    name: 'Standard_LRS'
  }
  kind: 'StorageV2'
  properties: {
    allowBlobPublicAccess: false
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource deploymentContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'app-package'
  properties: {
    publicAccess: 'None'
  }
}

resource tableService 'Microsoft.Storage/storageAccounts/tableServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource estadoZonas 'Microsoft.Storage/storageAccounts/tableServices/tables@2023-05-01' = {
  parent: tableService
  name: 'EstadoZonas'
}

resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: 'red-telecorp-estado-flex-${take(suffix, 8)}'
  location: location
  kind: 'functionapp'
  sku: {
    name: 'FC1'
    tier: 'FlexConsumption'
  }
  properties: {
    reserved: true
  }
}

resource staticSite 'Microsoft.Web/staticSites@2023-12-01' = {
  name: staticName
  location: staticLocation
  sku: {
    name: 'Free'
    tier: 'Free'
  }
  properties: {}
}

resource functionApp 'Microsoft.Web/sites@2024-04-01' = {
  name: functionName
  location: location
  kind: 'functionapp,linux'
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    functionAppConfig: {
      deployment: {
        storage: {
          type: 'blobContainer'
          value: '${storage.properties.primaryEndpoints.blob}app-package'
          authentication: {
            type: 'StorageAccountConnectionString'
            storageAccountConnectionStringName: 'AzureWebJobsStorage'
          }
        }
      }
      scaleAndConcurrency: {
        maximumInstanceCount: 40
        instanceMemoryMB: 512
        // Sin alwaysReady: escala a cero cuando no recibe solicitudes.
      }
      runtime: {
        name: 'python'
        version: '3.11'
      }
    }
    siteConfig: {
      minTlsVersion: '1.2'
      cors: {
        allowedOrigins: [
          'https://${staticSite.properties.defaultHostname}'
        ]
        supportCredentials: false
      }
      appSettings: [
        { name: 'AzureWebJobsStorage', value: storageConnection }
        { name: 'AZURE_STORAGE_CONNECTION_STRING', value: storageConnection }
        { name: 'TABLE_NAME', value: estadoZonas.name }
      ]
    }
  }
  dependsOn: [deploymentContainer]
}

output functionAppName string = functionApp.name
output functionBaseUrl string = 'https://${functionApp.properties.defaultHostName}'
output staticWebAppName string = staticSite.name
output staticWebAppUrl string = 'https://${staticSite.properties.defaultHostname}'
output storageAccountName string = storage.name
output tableName string = estadoZonas.name
