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

El template no despliega código: primero crea recursos, luego se publica `azure/api` con Azure Functions Core Tools y `azure/web/dist` con Static Web Apps CLI. Ver [guía Azure](../README.md).
