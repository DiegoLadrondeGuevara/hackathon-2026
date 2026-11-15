# Azure: estado público de zonas

Esta carpeta implementa solamente la parte Azure del [contrato entre nubes](../contracts/external.md). AWS publica el estado agregado de cada zona mediante HTTPS; Azure conserva la última versión en Table Storage y sirve una página pública. No se reciben datos personales, descripciones de clientes ni ubicaciones detalladas.

## Qué construimos

1. `infra/main.bicep`: StorageV2 con Table Storage `EstadoZonas`, Function App `red-telecorp-estado-api-*` en Flex Consumption y Static Web App `red-telecorp-estado-publico-*` Free. Los sufijos globales son deterministas por suscripción, grupo y entorno.
2. `api/function_app.py`: `PUT /api/estado/{zone_id}` con autorización **Function** (cabecera `x-functions-key`) y `GET /api/estado` anónimo.
3. `api/status_store.py`: valida mensajes públicos, ignora eventos repetidos o más antiguos y usa ETag para impedir que una escritura concurrente antigua reemplace una nueva.
4. `web/`: portal que consulta la API cada 30 segundos y avisa si la última sincronización supera 10 minutos. El portal conserva la última vista si la API falla.

`PartitionKey` es siempre `ZONA` y `RowKey` es `zone_id`. Este diseño sirve para la demostración de 30 zonas; si el número de zonas crece mucho, habrá que repartir las particiones y paginar el listado.

## Cuenta y costos

Primero intenta [Azure for Students](https://learn.microsoft.com/azure/education-hub/about-azure-for-students) con tu correo institucional de UTEC: Microsoft ofrece USD 100 durante un año sin tarjeta para estudiantes elegibles y verifica el correo académico. **No hemos comprobado que el dominio de UTEC pase la verificación**; el formulario de Microsoft lo confirmará. La cuenta [Azure gratuita estándar](https://azure.microsoft.com/en-us/pricing/purchase-options/azure-account) ofrece USD 200 por 30 días, pero requiere tarjeta para verificar identidad.

[Bicep](https://learn.microsoft.com/en-us/azure/azure-resource-manager/bicep/overview) y Azure CLI son herramientas gratuitas; los recursos desplegados pueden consumir crédito. Static Web Apps tiene [plan Free](https://learn.microsoft.com/en-us/azure/static-web-apps/plans). La Function usa Flex Consumption sin instancias `alwaysReady`, pero Storage y ejecuciones se facturan según la suscripción. El [cupo mensual gratuito de Flex](https://learn.microsoft.com/en-us/azure/azure-functions/pricing) aplica a suscripciones de consumo pagadas; no lo presupuestes como beneficio adicional de Azure for Students. Comprueba que Flex y Static Web Apps Free estén habilitados en la región y tipo de suscripción antes de desplegar. Configura un presupuesto en Azure Cost Management.

## Preparar el entorno

- Para IaC puedes usar **Azure Cloud Shell** desde el portal o instalar **Azure CLI** y Bicep localmente. Cloud Shell evita instalar CLI, pero igualmente requiere una suscripción y sus recursos pueden tener costo.
- Para publicar Python desde Windows, instala **Python 3.11** y **Azure Functions Core Tools v4**. Para el portal, instala Node.js y usa `npx @azure/static-web-apps-cli`.
- Copia `.env.example` a `.env` para guardar los nombres, regiones y URLs no secretos del despliegue. En el checkout local del responsable de Azure ya existe `azure/.env` con los valores del despliegue `dev`; cada integrante debe crear su propia copia si la necesita. Git lo ignora. El archivo no configura automáticamente Azure: Bicep define los ajustes de la Function en Azure y `web/dist/config.js` define la URL que consulta el portal. Cloud Shell es efímero y tampoco carga `azure/.env` automáticamente.
- No guardes la clave de Function `aws-publisher`, connection strings ni deployment tokens en `.env`, Cloud Shell persistente, Git o mensajes públicos. La clave ya se creó en Azure; se puede copiar desde las **Function keys** de `actualizar_estado` en el portal para entregarla solo al responsable de AWS por un canal privado.
- Confirma en Azure CLI la suscripción y la región: `az login`, `az account list --output table`, `az account set --subscription <id>`, `az functionapp list-flexconsumption-locations --output table`.

## Validar y crear recursos

En Cloud Shell **Bash efímero**, la rama de Azure se puede obtener y revisar así. El grupo de recursos no genera cargos por sí mismo; `what-if` previsualiza cambios sin desplegar recursos. La consulta de salida muestra solo nombres y tipos de cambio, no los ajustes de la Function que incluyen una conexión de Storage.

```bash
git clone --depth 1 --branch codex/azure-grafana https://github.com/DiegoLadrondeGuevara/hackathon-2026.git hackathon-azure
cd hackathon-azure
az bicep build --file azure/infra/main.bicep
az group create --name rg-red-telecorp-estado-dev --location eastus2 --output table
az deployment group what-if --resource-group rg-red-telecorp-estado-dev --template-file azure/infra/main.bicep --parameters environmentName=dev location=eastus2 staticLocation=centralus --no-pretty-print --query "changes[].{tipo:changeType,recurso:resourceId}" --output table
```

Si el resultado y las cuotas son correctos, el comando de despliegue es:

```bash
az deployment group create --resource-group rg-red-telecorp-estado-dev --template-file azure/infra/main.bicep --parameters environmentName=dev location=eastus2 staticLocation=centralus --query "properties.outputs" --output json
```

Alternativamente, desde la raíz del repositorio en Windows, con Azure CLI autenticado:

```powershell
az bicep build --file azure/infra/main.bicep
az group create --name rg-red-telecorp-estado-dev --location eastus2
az deployment group what-if --resource-group rg-red-telecorp-estado-dev --template-file azure/infra/main.bicep --parameters environmentName=dev location=eastus2 staticLocation=centralus
az deployment group create --resource-group rg-red-telecorp-estado-dev --template-file azure/infra/main.bicep --parameters environmentName=dev location=eastus2 staticLocation=centralus
```

Usa las regiones que `az functionapp list-flexconsumption-locations` y Static Web Apps acepten en tu suscripción. La salida del despliegue entrega `functionAppName`, `functionBaseUrl`, `staticWebAppName` y `staticWebAppUrl`; no contiene secretos. El `what-if` permite revisar recursos antes de crearlos.

## Publicar API y portal

Desde Cloud Shell **Bash**, en el clon del repositorio y con la Function ya creada, se puede publicar Python sin instalar Core Tools. El ZIP debe tener `host.json` y `function_app.py` en su raíz; `--build-remote true` instala las dependencias en Linux:

```bash
cd ~/hackathon-azure/azure/api
FUNCTION_APP=$(az deployment group show --resource-group rg-red-telecorp-estado-dev --name red-telecorp-azure-dev --query 'properties.outputs.functionAppName.value' --output tsv)
zip -j /tmp/red-telecorp-estado-api.zip function_app.py status_store.py observability.py host.json requirements.txt
az functionapp deployment source config-zip --resource-group rg-red-telecorp-estado-dev --name "$FUNCTION_APP" --src /tmp/red-telecorp-estado-api.zip --build-remote true
curl -i "https://$FUNCTION_APP.azurewebsites.net/api/estado"
```

El `GET` inicial debe responder `200` y `{"zones":[]}`. Desde `azure/api` en Windows, la alternativa con Core Tools es:

```powershell
func azure functionapp publish <functionAppName>
```

El código fuente no está incluido en Bicep. Core Tools empaqueta las dependencias y publica la Function. El portal se publica por separado:

En Cloud Shell Bash, preparar el portal con la URL de la Function y publicar la Static Web App sin imprimir el token:

```bash
cd ~/hackathon-azure
FUNCTION_APP=$(az deployment group show --resource-group rg-red-telecorp-estado-dev --name red-telecorp-azure-dev --query 'properties.outputs.functionAppName.value' --output tsv)
SWA_NAME=$(az deployment group show --resource-group rg-red-telecorp-estado-dev --name red-telecorp-azure-dev --query 'properties.outputs.staticWebAppName.value' --output tsv)
mkdir -p azure/web/dist
cp azure/web/index.html azure/web/staticwebapp.config.json azure/web/dist/
printf 'window.RED_TELECORP_API_BASE_URL = "https://%s.azurewebsites.net";\n' "$FUNCTION_APP" > azure/web/dist/config.js
export SWA_CLI_DEPLOYMENT_TOKEN=$(az staticwebapp secrets list --name "$SWA_NAME" --resource-group rg-red-telecorp-estado-dev --query 'properties.apiKey' --output tsv)
npx --yes @azure/static-web-apps-cli deploy azure/web/dist --env production
unset SWA_CLI_DEPLOYMENT_TOKEN
```

En Windows PowerShell, la alternativa usa `prepare-web.ps1`:

```powershell
./azure/web/prepare-web.ps1 -ApiBaseUrl 'https://<functionAppName>.azurewebsites.net'
$env:AZURE_SWA_DEPLOYMENT_TOKEN = az staticwebapp secrets list --name <staticWebAppName> --resource-group rg-red-telecorp-estado-dev --query 'properties.apiKey' --output tsv
npx @azure/static-web-apps-cli deploy ./azure/web/dist --deployment-token $env:AZURE_SWA_DEPLOYMENT_TOKEN --env production
Remove-Item Env:AZURE_SWA_DEPLOYMENT_TOKEN
```

El token queda solo en la sesión local. No muestres ni compartas la salida de `az staticwebapp secrets list`.

## Pruebas locales

Para ejecutar los tests sin Azure, crea un entorno Python 3.11 e instala `azure/api/requirements.txt`. Luego:

```powershell
python -m unittest discover -s azure/tests -v
```

Para probar la Function localmente, ejecuta Azurite y copia `api/local.settings.example.json` a `api/local.settings.json`; crea la tabla `EstadoZonas` en Azurite. Desde `azure/api`, ejecuta `func start`. El archivo real de configuración local está ignorado por Git. El `PUT` local puede requerir una clave según la configuración de Core Tools; en Azure requiere `x-functions-key`.

Ejemplo de actualización (el texto público debe coincidir con el estado):

```http
PUT /api/estado/Z01
x-functions-key: <clave privada>
Content-Type: application/json

{"zone_id":"Z01","status":"EVALUACION","priority":"P2","updated_at":"2026-11-14T10:00:00Z","public_message":"Evaluando"}
```

La API devuelve `{"applied":true,...}` cuando guarda, y `{"applied":false,...}` si el evento es repetido o antiguo. `GET /api/estado` devuelve `{"zones":[...]}` con `zone_id`, estado, prioridad, mensaje, `updated_at` y `last_synced_at`, ordenado por zona.

## Estado del despliegue y entrega al equipo

La cuenta Free Trial está activa y el grupo `rg-red-telecorp-estado-dev` contiene la Function, Storage/Table Storage y Static Web App. La API y el portal ya se publicaron. Se verificó CORS desde el portal, un `PUT` autenticado para `Z01` respondió `applied: true` y el `GET` público devolvió esa zona. Esto comprueba Azure de forma aislada; **todavía no demuestra la publicación desde AWS**.

El equipo de AWS necesita ahora:

1. La URL base pública `https://red-telecorp-estado-api-slx33vbj.azurewebsites.net` y la ruta `PUT /api/estado/{zone_id}`. El cuerpo y los estados permitidos están en [el contrato](../contracts/external.md). El portal público es `https://mango-ground-073e60210.3.azurestaticapps.net` para enlazarlo desde Amplify si lo desean.
2. La **clave de la Function** `actualizar_estado`, llamada `aws-publisher`, por un canal privado. Es el valor de la cabecera `x-functions-key`; no es la clave de despliegue de Static Web Apps. Deben guardarla en SSM como `azure/api_key` y guardar la URL base como `azure/base_url`. Si la clave se expone, hay que rotarla y actualizar SSM.
3. Implementar y probar `PublicadoraHaciaAzure` desde `ColaAzure`: `zone_id` estable, `updated_at` en UTC con zona horaria y creciente para cada zona, `status` en `SIN_INCIDENTE | EVALUACION | CONFIRMADO | RESTABLECIDO`, `priority` en `P1 | P2 | P3` o nula, y uno de los cuatro mensajes públicos exactos: `Sin incidencias`, `Evaluando`, `Incidencia identificada`, `Servicio restablecido`. `CERRADO` de AWS se traduce a `SIN_INCIDENTE`. No se envían PII ni texto libre de clientes.
4. Acordar un **refresco periódico por zona**. El portal avisa si `last_synced_at` supera 10 minutos y Azure solo actualiza esa marca cuando recibe una versión con `updated_at` posterior. Si AWS envía exclusivamente `incident.updated`, una zona sin cambios aparecerá desactualizada. Una opción es publicar una instantánea o latido por zona cada menos de 10 minutos con `updated_at` nuevo; antes de hacerlo debemos definir si ese campo representa el momento de publicación o el del cambio operacional. Hasta acordarlo, la advertencia de antigüedad es esperable.

Del equipo AWS necesitamos también la lista definitiva de `zone_id` del catálogo y una carga de prueba sin datos personales. Cuando su Lambda esté conectada, verificaremos el flujo `ColaAzure → PublicadoraHaciaAzure → PUT → EstadoZonas → GET → portal` y los reintentos/DLQ ante un error de Azure.

Azure no requiere hoy ninguna credencial ni URL de GCP. La exportación a Grafana es una integración adicional pendiente; solo debe transmitir métricas sin PII.

## Grafana Cloud: exportador preparado, despliegue pendiente

El equipo facilitó estos datos **no secretos** para la futura exportación desde Azure:

| Ajuste | Valor |
| --- | --- |
| Endpoint OTLP base | `https://otlp-gateway-prod-us-east-6.grafana.net/otlp` |
| Endpoint de métricas OTLP/HTTP | `https://otlp-gateway-prod-us-east-6.grafana.net/otlp/v1/metrics` |
| Instance ID | `1925059` |
| Protocolo acordado | OTLP/HTTP JSON, adecuado para el volumen bajo de la demo |

Usa el token completo de Grafana que el equipo ya entregó. Pégalo únicamente como valor de `GRAFANA_TOKEN` en **Environment variables → App settings** de la Function App existente. No hace falta crear otro token ni poner este en `azure/.env`, `local.settings.json`, Bicep, Git, Cloud Shell o Amplify. La autenticación OTLP usa el Instance ID como usuario y el token como contraseña. [Grafana documenta la ruta `/v1/metrics` y la configuración OTLP](https://grafana.com/docs/grafana-cloud/send-data/otlp/send-data-otlp/); [Azure documenta los ajustes cifrados de Function App](https://learn.microsoft.com/en-us/azure/azure-functions/functions-how-to-use-azure-function-app-settings).

`api/observability.py` emite métricas OTLP/HTTP JSON desde la Function, sin dependencias nuevas. Cada respuesta `GET /api/estado` o `PUT /api/estado/{zone_id}` registra recuento acumulado, errores y latencia; el GET registra además cantidad de zonas con sincronización atrasada (>10 min) y mayor antigüedad. Solo se transmiten ruta fija, estado HTTP y agregados, sin `zone_id`, cuerpos, usuarios, claves ni texto público. Un fallo de Grafana no modifica la respuesta del API; la exportación puede añadir hasta un segundo de latencia a cada petición mientras esté configurada. Las respuestas 401 rechazadas por el runtime antes de invocar la Function no están instrumentadas.

| Métrica | Significado |
| --- | --- |
| `redtelecorp.azure.requests` | Contador acumulado de respuestas por ruta fija y código HTTP |
| `redtelecorp.azure.errors` | Contador acumulado de respuestas HTTP 4xx/5xx por ruta y código |
| `redtelecorp.azure.latency_ms` | Duración de la operación Azure, sin el tiempo de envío a Grafana |
| `redtelecorp.azure.zones_stale` | Zonas cuya última sincronización supera 10 min o no tiene fecha válida |
| `redtelecorp.azure.sync_age_max_seconds` | Mayor antigüedad de sincronización entre zonas con fecha válida |

### Activación en Azure

1. Reutiliza el clon existente de Cloud Shell en `~/hackathon-azure`; **no hagas otro `git clone`**. Ejecuta `git status --short` y, si hay cambios propios en archivos versionados, consérvalos antes de cambiar de rama. Luego ejecuta `git fetch origin` y `git switch --track origin/codex/azure-grafana` (o `git switch codex/azure-grafana && git pull --ff-only` si la rama local ya existe).
2. Publica únicamente el ZIP actualizado de `azure/api`, incluyendo `observability.py`, con `az functionapp deployment source config-zip`; los comandos están en **Publicar API y portal** más arriba. No vuelvas a crear los recursos con Bicep ni a publicar la Static Web App.
3. En Azure Portal abre la Function App `red-telecorp-estado-api-slx33vbj` → **Settings → Environment variables → App settings**. Agrega `GRAFANA_OTLP_ENDPOINT` con el endpoint base de la tabla, `GRAFANA_INSTANCE_ID` con `1925059` y `GRAFANA_TOKEN` con el **token completo que ya tienes**. Guarda los cambios. Si falta uno de los tres, el exportador queda desactivado y la API sigue funcionando.
4. Invoca `GET https://red-telecorp-estado-api-slx33vbj.azurewebsites.net/api/estado` y busca las métricas `redtelecorp.azure.*` en Grafana Explore. Verifica la recepción y el panel. El token no debe aparecer en logs ni capturas.

`main.bicep` declara actualmente la lista de `appSettings`; si vuelves a desplegar la infraestructura, comprueba si los tres ajustes de Grafana siguen presentes y vuelve a introducirlos desde el portal si fueron reemplazados. La exportación Azure todavía **no está desplegada ni verificada contra Grafana** en esta rama: las pruebas locales usan un receptor simulado.
