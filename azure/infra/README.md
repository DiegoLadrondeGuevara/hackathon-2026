# Infraestructura Azure

`main.bicep` crea, dentro de un grupo de recursos existente:

| Nombre lógico | Servicio | Función |
| --- | --- | --- |
| `red-telecorp-estado-api-*` | Azure Functions, Flex Consumption `FC1` | API Python 3.11, escala a cero |
| `red-telecorp-estado-flex-*` | App Service Plan Flex | Hospedaje de la Function |
| `sttelecorp*` | StorageV2 `Standard_LRS` | Almacenamiento de Functions y Table Storage |
| `EstadoZonas` | Azure Table Storage | Proyección pública por zona |
| `app-package` | Blob container privado | Paquetes de la Function |
| `red-telecorp-estado-publico-*` | Azure Static Web Apps Free | Portal público |

La URL de la Static Web App se configura como único origen CORS de la Function. El `PUT` sigue protegido por una clave de Function, que se administra en Azure y **no** aparece como salida de Bicep. Se usan claves de la cuenta de Storage en los ajustes de la Function para simplificar el laboratorio; no se exportan a archivos ni al repositorio. Una versión posterior podría migrar a identidades administradas con RBAC.

En Flex Consumption, Python 3.11 se declara en `functionAppConfig.runtime`. No se deben incluir los ajustes `FUNCTIONS_WORKER_RUNTIME` ni `FUNCTIONS_EXTENSION_VERSION` en la Function desplegada: Azure los rechaza o administra internamente. `FUNCTIONS_WORKER_RUNTIME` sí permanece en `api/local.settings.example.json` para ejecutar el proyecto de forma local.

El template no despliega código: primero crea recursos, luego se publica `azure/api` con Azure Functions Core Tools y `azure/web/dist` con Static Web Apps CLI. Ver [guía Azure](../README.md).
