# Arquitectura v3 propuesta — señales unificadas y estado independiente

**Estado:** propuesta para revisar con el equipo. Conserva todos los nombres de recursos AWS v2; añade `ColaAnomalias` y `CorrelacionadoraDeAnomalias` como nombres nuevos **aún no declarados en `serverless.yml`**. Cloudflare, Grafana Cloud y Azure Static Web Apps también están propuestos, sin despliegue. El [checklist](PENDIENTES.md#revisión-de-arquitectura-v3--observaciones-del-equipo) separa lo pendiente. Fuente: [enunciado](hackathonCloudEnunciado.txt) y [definiciones existentes](puntos-dolor-cliente.md).

**Ver:** [HTML interactivo](arquitectura-solucion-v3.html), [panorama Mermaid](arquitectura-solucion-v3.mmd), [SVG](arquitectura-solucion-v3.svg), [PNG](arquitectura-solucion-v3.png) y [flujo de correlación](flujo-correlacion-v3.mmd).

## Evaluación crítica de las observaciones

| Observación | Evaluación | Cambio propuesto y límite |
| --- | --- | --- |
| 1. Una anomalía de antena no inicia la gestión de incidentes. | **Válida.** El v2 sí clasifica y publica una anomalía, pero no tiene consumidor que abra un caso o invoque `VerificarIncidente`. El enunciado pide reducir la detección tardía; no exige que toda lectura anómala confirme una caída. | Nuevo camino `OperacionesBus → ColaAnomalias → CorrelacionadoraDeAnomalias → Incidents → VerificarIncidente`. Un **episodio** genera una sospecha técnica y una verificación, sin esperar 10 usuarios. No se confirma afectación de clientes solo por GB/min. |
| 2. Falta unir anomalías y reportes. | **Válida, con parte ya definida.** `NetworkCatalog`, el puntero activo en `Incidents` y S05 describían cobertura y enlazado, pero faltaba un criterio común ejecutable y el caso de señal técnica primero. | Ambos caminos comparten el mismo `incident_id` cuando coinciden zona, cobertura y tiempo. La tabla `Incidents` mantiene un puntero activo por grupo con escritura condicional. Si hay más de un candidato, se exige revisión humana. |
| 3. Azure aporta poco valor. | **Parcialmente válida.** Una proyección pública en otro proveedor ya aporta un dominio de fallo separado; aun así, la v2 no dibujaba una **página** que pudiera usarse sin Amplify. | Se propone `red-telecorp-estado-publico` **(Azure Static Web Apps)** que lee `red-telecorp-estado-api` **(Azure Functions)** y `EstadoZonas` **(Azure Table Storage)**. Publica la última información recibida con `last_synced_at` y aviso de atraso. No es recuperación completa de AWS ni conoce cambios que AWS no haya enviado. |

## Camino técnico y unión determinista

1. `GeneradoraDeMetricasYLotes` **(AWS Lambda)** escribe un lote en el bucket S3 existente. `ColaMetricas` **(SQS)** activa `ClasificadoraDeMetricas` **(AWS Lambda)**.
2. La clasificadora conserva lectura/episodio en `Telemetry` **(tabla DynamoDB)** y crea un evento en `Outbox` **(tabla DynamoDB)**, idealmente en una misma transacción. `Outbox` usa **DynamoDB Streams `NEW_IMAGE`**; `EnrutadoraDeOutbox` **(AWS Lambda)** publica `telemetry.anomaly` en `OperacionesBus` **(EventBridge)**. Una lectura repetida del mismo minuto no abre otro episodio.
3. Una regla nueva dirige `telemetry.anomaly` a `ColaAnomalias` **(SQS + DLQ, propuesta)**. `CorrelacionadoraDeAnomalias` **(AWS Lambda, propuesta)** consulta `NetworkCatalog` **(tabla DynamoDB)** para conocer las zonas cubiertas. Como GB/min por sí solo no identifica voz o Internet, busca primero incidentes activos compatibles de la zona: si hay **uno**, añade la evidencia técnica a ese `incident_id`; si no hay ninguno, crea una **sospecha técnica de conectividad general por zona** en `Incidents` **(tabla DynamoDB)** e inicia `VerificarIncidente` **(Step Functions Standard)** sin esperar usuarios. Si hay varios candidatos, conserva el episodio y pide revisión humana sin duplicar un caso automáticamente. Un puntero `GROUP#<zone_id>#GENERAL / ACTIVE` y el `event_id` impiden reabrir el mismo episodio. La sospecha no equivale a afectación confirmada.
4. Un usuario crea un reporte con `CrearReporte` **(AWS Lambda)**. `Reports`, `CorrelationMembers` y `Outbox` **(tablas DynamoDB)** se escriben en una transacción. El evento `report.created` pasa por `OperacionesBus → ColaReportes → CorrelacionadoraDeReportes`.
5. `CorrelacionadoraDeReportes` busca primero el puntero activo de **zona + servicio**. Si no existe, comprueba un único candidato técnico `GENERAL` con cobertura válida y tiempo compatible. **Propuesta de ventana de enlace:** `occurred_at` del reporte entre cinco minutos antes del inicio del episodio y 30 minutos después de su fin; un episodio abierto sigue siendo candidato. Si coincide, enlaza el reporte al mismo `incident_id` y reclama condicionalmente el puntero del servicio. Si hay varios candidatos o no hay cobertura clara, el enlace queda pendiente de decisión del operador. Para que la búsqueda de incidentes activos por zona sea consistente, `Incidents` puede guardar ítems de puntero adicionales `PK=ZONE#<zone_id>#ACTIVE`, `SK=SERVICE#<service>` y consultarlos con `Query` fuertemente consistente sobre la tabla base; el GSI eventual solo sirve para paneles.
6. El umbral del reto permanece intacto: **10 clientes distintos**, mismo `zone_id` y servicio, en **menos de 24 h** activan verificación aunque las métricas sean normales. Si el grupo ya apunta al incidente técnico, se añade la evidencia y se reevalúa **el mismo caso**; si no hay candidato, se crea uno nuevo con origen `reportes`. La revisión usa `incident_id + revision` como clave de idempotencia para no repetir pasos o avisos.

La ventana de enlace, la identidad por zona y el manejo de candidatos ambiguos son **decisiones del prototipo**, no números impuestos por el enunciado. La prioridad sigue el [S08 existente](puntos-dolor-cliente.md#s08-prioridad-por-impacto-y-criticidad): una antena inhabilitada no equivale automáticamente a miles de afectados. El operador confirma o descarta con evidencia.

## Nombres y tipos que se deben ver en el dibujo

| Nombre | Tipo y proveedor | Estado |
| --- | --- | --- |
| `red-telecorp-portal` | Aplicación estática **Amplify Hosting, AWS** | Nombre propuesto v2; configuración externa al YAML. |
| `red-telecorp-dev-api-http` | **API Gateway HTTP API, AWS** | Declarado v2. |
| `red-telecorp-dev-AutenticarUsuario` / `red-telecorp-dev-AutorizarJWT` | Dos **AWS Lambda**; el segundo es Lambda Authorizer | Declaradas v2. |
| `red-telecorp-dev-Reports`, `-CorrelationMembers`, `-Telemetry`, `-Incidents`, `-NetworkCatalog`, `-CustomerProfiles`, `-Outbox` | Siete **tablas DynamoDB, AWS** | Declaradas v2. `Outbox` tiene Streams. |
| `red-telecorp-dev-operaciones` | Bus **EventBridge, AWS** (`OperacionesBus`) | Declarado v2. |
| `red-telecorp-dev-reportes`, `-metricas`, `-gcp`, `-azure`, `-notificaciones` | **Colas SQS, AWS**, cada una con DLQ | Declaradas v2. |
| `red-telecorp-dev-anomalias` | Nueva **cola SQS + DLQ, AWS** (`ColaAnomalias`) | Propuesta v3. |
| `red-telecorp-dev-CorrelacionadoraDeAnomalias` | Nueva **AWS Lambda** | Propuesta v3. |
| `red-telecorp-dev-VerificarIncidente` | **Step Functions Standard, AWS** | Declarada v2. |
| `red-telecorp-analisis` / `red_telecorp_analitica.incident_events` | **Cloud Run function / tabla BigQuery, GCP** | Nombres propuestos; conservan el rol v2. |
| Gemini Developer API | **API de IA de Google**, invocada desde Cloud Run | Propuesta v2; llamada real pendiente. |
| `red-telecorp-estado-api` / `EstadoZonas` | **Azure Functions / Azure Table Storage** | Nombres propuestos para los recursos v2. |
| `red-telecorp-estado-publico` | **Azure Static Web Apps** | Propuesta v3, sujeta a la suscripción del equipo. |
| `portal.<dominio>` | Registro DNS/proxy **Cloudflare** hacia Amplify | Propuesta condicional: requiere dominio propio. |
| `red-telecorp-observabilidad` | Stack **Grafana Cloud** gestionado | Propuesta condicional: comprobar plan y cuota. |

## Qué suma cada plataforma

| Plataforma | Aporte visible | Dependencia/límite |
| --- | --- | --- |
| **AWS Academy** | Portal autenticado, fuente de verdad, ingestión de antenas, reportes, correlación, verificación Step Functions y alertas. | `LabRole`, servicios habilitados, secretos y canales reales pendientes de prueba. |
| **GCP** | BigQuery reúne historial y tendencias; Cloud Run invoca Gemini para hipótesis y verificaciones con hechos depurados. | IA auxiliar, sin datos personales ni decisiones automáticas de estado. |
| **Azure** | Estado público en un portal alojado fuera de AWS, respaldado por Functions/Table; explica cuán reciente es la copia. | Consistencia eventual: si AWS deja de enviar, muestra último estado y marca atraso. [Static Web Apps Free admite alojamiento y dominios, sujeto a sus cuotas](https://learn.microsoft.com/en-us/azure/static-web-apps/plans). |
| **Cloudflare** | DNS y, si se valida, proxy HTTPS delante de Amplify para el **portal estático**. | Amplify ya usa CDN. Requiere dominio; no protege automáticamente API Gateway ni sustituye AWS. [AWS exige DNS only para validar y luego permite proxy Full (Strict)](https://docs.aws.amazon.com/amplify/latest/userguide/to-add-a-custom-domain-managed-by-cloudflare.html). |
| **Grafana Cloud** | Panel de salud transversal con métricas de aplicación y pruebas HTTPS públicas. | SaaS de observabilidad, no fuente de verdad ni nube funcional adicional para la rúbrica. La conexión directa a CloudWatch [requiere IAM](https://grafana.com/docs/grafana-cloud/observe-and-act/monitor-infrastructure/monitor-cloud-provider/aws/cloudwatch-metrics/config-cw-metric-scrape/); con `LabRole` sin creación de roles, se propone **OTLP saliente** desde las funciones, con token secreto y sin PII. [Grafana documenta el envío directo](https://grafana.com/docs/grafana-cloud/send-data/otlp/send-data-otlp/). |

**Rúbrica:** AWS + GCP ya satisfacen el requisito arquitectónico de dos proveedores, sujeto a desplegar flujos reales. Azure añade continuidad informativa. Cloudflare y Grafana sirven como borde y observabilidad; no se deben presentar como sustitutos de una carga funcional en otra nube. El proyecto sigue sin implementación demostrada.
