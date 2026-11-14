# Contrato con infraestructura

Lo que el equipo de infra tiene que proveer para que las Lambdas funcionen sin cambios de código.
Código: `aws/src/handlers/<archivo>.py`, función `handler(event, context)`. Despliegue: `aws/serverless.yml` + `aws/infra/` (ya hechos). Runtime Python 3.11, sin dependencias externas (solo stdlib y boto3 del runtime): no hacen falta capas ni empaquetado especial.
Rol IAM: `LabRole` en todas (proveedor y máquina de estados). Memoria 256 MB. Timeout 10 s (API), 30 s (pipeline), 5 s (autorizador).

## Variables de entorno (todas las Lambdas)
`STAGE=dev`, `SSM_PREFIX=/red-telecorp/dev`, `TABLE_REPORTS`, `TABLE_INCIDENTS`, `TABLE_TELEMETRY`, `TABLE_CORRELATION_MEMBERS`, `TABLE_NETWORK_CATALOG`, `TABLE_CUSTOMER_PROFILES`, `TABLE_OUTBOX` (nombre físico de cada tabla).
Extra: `EVENT_BUS_NAME` (EnrutadoraDeOutbox), `METRICS_BUCKET` y `QUEUE_METRICAS_URL` (GeneradoraDeMetricasYLotes), `OPS_TOPIC_ARN` (AlertadoraDeOperaciones), `EMAIL_MODE` (SES|SIMULATED), `SMS_MODE` (SNS|SIMULATED) (NotificadoraDeClientes).

## Parámetros SSM (SecureString salvo indicación)
`/red-telecorp/dev/jwt/signing_key`, `/red-telecorp/dev/pii_salt`, `/red-telecorp/dev/ses/from_address` (String), `/red-telecorp/dev/gcp/base_url` (String), `/red-telecorp/dev/gcp/api_key`, `/red-telecorp/dev/azure/base_url` (String), `/red-telecorp/dev/azure/api_key`.

## Lambdas
Tablas: R Reports, I Incidents, T Telemetry, M CorrelationMembers, N NetworkCatalog, C CustomerProfiles, O Outbox.
| Lambda | Archivo | Disparador | Tablas | Extra |
|---|---|---|---|---|
| AutenticarUsuario | autenticar_usuario | POST /auth/login | C lee | SSM jwt |
| AutorizarJWT | autorizar_jwt | Autorizador Lambda (HTTP API, fuente `$request.header.Authorization`, respuesta simple, caché 300 s) | — | SSM jwt |
| ListarZonas | listar_zonas | GET /zonas | N lee | |
| CrearReporte | crear_reporte | POST /reportes | R, O escribe; N lee | |
| ListarMisReportes | listar_mis_reportes | GET /reportes | R lee | |
| ObtenerReporte | obtener_reporte | GET /reportes/{id} | R lee | |
| CambiarEstadoReporte | cambiar_estado_reporte | PATCH /reportes/{id}/estado | R, O | |
| ListarIncidentesZona | listar_incidentes_zona | GET /incidentes, GET /incidentes/{id} | I lee | |
| CambiarEstadoIncidente | cambiar_estado_incidente | PATCH /incidentes/{id}/estado | I, M, O | |
| ObtenerTendencias | obtener_tendencias | GET /tendencias | R, I, T, N leen | |
| ObtenerSugerenciaIA | obtener_sugerencia_ia | GET /incidentes/{id}/sugerencia | I lee | SSM gcp; timeout 5 s |
| GeneradoraDeMetricasYLotes | generadora_de_metricas_y_lotes | EventBridge `rate(1 minute)` | N lee | S3 put, SQS send |
| ClasificadoraDeMetricas | clasificadora_de_metricas | ColaMetricas | T, O; N lee | S3 get |
| CorrelacionadoraDeReportes | correlacionadora_de_reportes | ColaReportes | M, I, R, O; N lee | |
| CorrelacionadoraDeAnomalias | correlacionadora_de_anomalias | ColaAnomalias | I, M, T, O | |
| VerificadoraDeEvidencias | verificadora_de_evidencias | Step Functions | I, R, T leen | |
| CalculadoraDePrioridad | calculadora_de_prioridad | Step Functions | I, O; N lee | |
| AlertadoraDeOperaciones | alertadora_de_operaciones | Step Functions | I lee | SNS publish |
| EnrutadoraDeOutbox | enrutadora_de_outbox | Stream de Outbox | O lee | EventBridge PutEvents |
| NotificadoraDeClientes | notificadora_de_clientes | ColaNotificaciones | I, C | SES, SNS |
| PublicadoraHaciaGCP | publicadora_hacia_gcp | ColaGCP | — | SSM gcp, HTTPS |
| PublicadoraHaciaAzure | publicadora_hacia_azure | ColaAzure | — | SSM azure, HTTPS |

## Colas
Cada cola con DLQ (`maxReceiveCount` 5). Visibility timeout 180 s (6 × el timeout de 30 s de los consumidores). Mapeo de eventos con `ReportBatchItemFailures` activado. Tamaño de lote 10.
Colas: ColaReportes, ColaAnomalias, ColaMetricas, ColaNotificaciones, ColaGCP, ColaAzure.

## Stream de Outbox
Vista NEW_IMAGE, lote 10, `BisectBatchOnFunctionError`, reintentos 5, destino de fallos: cola DLQ. Filtro: solo `eventName = INSERT`.

## Máquina de estados `VerificarIncidente`
Standard. Estados: `VerificarEvidencias` (Parallel con dos ramas de VerificadoraDeEvidencias, `mode` = users | antennas), `CalcularPrioridad`, `RequiereAlerta` (Choice sobre `$.calc.alert`), `AlertarOperaciones`, `AlertarFalla`, `Fail`, `Succeed`. Detalle de entradas y salidas en `flows.md`.
Entrada: `{"incident_id","trigger_event_id","change"}` (la arma la regla con un InputTransformer).

## Alertas
SNS `alertas-operaciones`: suscripción por correo del equipo.
