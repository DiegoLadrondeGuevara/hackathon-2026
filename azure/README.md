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
- Copia `.env.example` a `.env` solo como recordatorio local. `.env` está ignorado por Git. No guardes claves de Function ni deployment tokens en archivos versionados.
- Confirma en Azure CLI la suscripción y la región: `az login`, `az account list --output table`, `az account set --subscription <id>`, `az functionapp list-flexconsumption-locations --output table`.

## Validar y crear recursos

En Cloud Shell **Bash efímero**, la rama de Azure se puede obtener y revisar así. El grupo de recursos no genera cargos por sí mismo; `what-if` previsualiza cambios sin desplegar recursos. La consulta de salida muestra solo nombres y tipos de cambio, no los ajustes de la Function que incluyen una conexión de Storage.

```bash
git clone --depth 1 --branch codex/azure-t16b https://github.com/DiegoLadrondeGuevara/hackathon-2026.git hackathon-azure
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
zip -j /tmp/red-telecorp-estado-api.zip function_app.py status_store.py host.json requirements.txt
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

## Integración pendiente con AWS

El equipo de AWS necesita, por canal privado, `functionBaseUrl` y una clave específica de la Function para `PublicadoraHaciaAzure`. Deben configurar sus parámetros SSM `azure/base_url` y `azure/api_key` y enviar los cuatro textos acordados: `Evaluando`, `Incidencia identificada`, `Servicio restablecido`, `Sin incidencias`. `CERRADO` en AWS se traduce a `SIN_INCIDENTE` en Azure. No se necesita un correo ni cuenta AWS dentro de Azure; el límite entre nubes es HTTPS.

Antes de la prueba de punta a punta falta una cuenta Azure activa, confirmar las regiones y cuotas, desplegar la infraestructura, publicar API y portal, probar el `PUT` con la clave, probar `GET` y conectar la Lambda de AWS. No se ha desplegado nada en Azure desde este repositorio todavía.
