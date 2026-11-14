# Red TeleCorp — documentación de la solución serverless multinube

**Hackathon Cloud 2026 · Grupo 12, Escuadrón S3.** Esta es la guía de consulta del diseño v4. Existe una plantilla declarativa de AWS; los handlers, el frontend y las integraciones de GCP y Azure todavía no están desplegados. «Diseñado» no significa «probado» ni puntos obtenidos en la rúbrica.

## Índice

1. [Problema y objetivo](#1-problema-y-objetivo)
2. [Los 13 puntos de dolor y su respuesta](#2-los-13-puntos-de-dolor-y-su-respuesta)
3. [Solución y diagrama](#3-solución-y-diagrama)
4. [Actores, entidades y reglas](#4-actores-entidades-y-reglas)
5. [Servicios por plataforma](#5-servicios-por-plataforma)
6. [Viaje de una petición desde el cliente y respuesta](#6-viaje-de-una-petición-desde-el-cliente-y-respuesta)
7. [Viaje de las métricas de antenas](#7-viaje-de-las-métricas-de-antenas)
8. [Incidentes, prioridad, historial y comunicación](#8-incidentes-prioridad-historial-y-comunicación)
9. [Ida y vuelta entre AWS, GCP y Azure](#9-ida-y-vuelta-entre-aws-gcp-y-azure)
10. [Datos, eventos, seguridad, fallos y costo](#10-datos-eventos-seguridad-fallos-y-costo)
11. [Rúbrica y evidencias pendientes](#11-rúbrica-y-evidencias-pendientes)
12. [Implementación pendiente y archivos de referencia](#12-implementación-pendiente-y-archivos-de-referencia)

## 1. Problema y objetivo

Red TeleCorp presta telefonía móvil, Internet y conectividad a usuarios de distintas zonas. Una antena caída, inhabilitada o saturada puede degradar el servicio; varios reportes aparentemente aislados pueden ser un único problema de zona. La empresa recibe métricas de antenas, avisos de usuarios y registros operativos, pero necesita **relacionarlos a tiempo**, atender con prioridad, informar a los afectados y aprender del historial. El [enunciado](hackathonCloudEnunciado.txt) plantea una simulación: no suministra antenas ni sistemas reales que debamos conectar.

El objetivo del prototipo es **detectar, correlacionar, verificar, priorizar, seguir y comunicar** incidentes usando servicios sin servidores administrados por el equipo. AWS Academy conserva el dato operativo; GCP aporta historia e IA; Azure ofrece una consulta pública de estado fuera de AWS. Cloudflare y Grafana Cloud son capas opcionales.

## 2. Los 13 puntos de dolor y su respuesta

**Revisión de cobertura previa a la rúbrica.** Cada dolor de [puntos-dolor-cliente.md](puntos-dolor-cliente.md) tiene un camino de solución. La cuarta columna señala lo que aún puede impedir afirmar que está *resuelto en la práctica*.

| ID | Dolor del cliente | Respuesta prevista | Verificación pendiente |
| --- | --- | --- | --- |
| **D01** | Fallas, saturación e interrupciones de antenas pasan inadvertidas. | Lotes periódicos, `ClasificadoraDeMetricas`, `Telemetry` y evento de anomalía. | Generar y clasificar valores `0/59/60/129/130`. |
| **D02** | Métricas, reportes y evidencia operativa no se relacionan. | `Incidents` une referencias a reportes y episodios por zona/tiempo; `VerificadoraDeEvidencias` las reúne. Notas internas sintéticas pueden anexarse al historial. | Demostrar trazabilidad; integrar sistemas internos reales requeriría un conector adicional no especificado en el reto. |
| **D03** | El usuario carece de una vía estructurada para reportar. | Portal Amplify y `CrearReporte` validan identificación, número de servicio, ubicación, hora, tipo y descripción. | Implementar formulario, validación y persistencia. |
| **D04** | Se pierde el avance y la historia de un reporte. | API de consulta/administración; `Reports` guarda `META` actual y `HIST` de los cinco estados. | Reconstruir transiciones con actor, hora y motivo. |
| **D05** | Diez avisos aislados ocultan un incidente de zona. | `CorrelationMembers` cuenta diez clientes distintos en la misma zona/servicio y <24 h; abre sospecha y verifica, aun sin antena identificada. | Casos 9/10/11, duplicados y límite de 24 h. |
| **D06** | Los afectados no reciben información. | `NotificadoraDeClientes` selecciona vinculados, crea intención por cliente/hito y registra envío y resultado; portal consultable. | Probar un canal real: SNS SMS si se permite, o alternativa verificada. |
| **D07** | Casos críticos pueden quedar detrás de otros menores. | `CalculadoraDePrioridad` usa reportantes, severidad y criticidad de zona para P1–P3 explicados. | Mostrar la regla y una intervención manual motivada. |
| **D08** | No se conocen zonas, antenas ni tipos más problemáticos. | Eventos depurados a BigQuery; `ObtenerTendencias` consulta agregados a Cloud Run y los devuelve al panel. | Implementar el contrato de consulta y enviar las categorías necesarias a GCP. |
| **D09** | Una antena se recupera y vuelve a fallar repetidamente. | `Telemetry` conserva episodios; tres episodios distintos en siete días activan alerta. | Probar racha única, recuperación y recurrencia. |
| **D10** | Los usuarios pueden detectar antes que operaciones. | La anomalía técnica puede abrir una sospecha sin esperar reportes; marcas `first_signal_at`/`detected_at` miden retraso. | Comparar cronologías en un escenario simulado. |
| **D11** | Una ráfaga simultánea puede perder registros. | Persistir antes de responder, Outbox, SQS/DLQ, reintentos e idempotencia. | Prueba de 1000 reportes en diez minutos, sin pérdida de aceptados. |
| **D12** | No hay historia de duración, alcance y frecuencia. | `Reports`/`Incidents` guardan transiciones, `Telemetry` episodios y BigQuery agregados de 7/30 días. | Consultas reproducibles de duración, zona, reportantes y recurrencia. |
| **D13** | Infraestructura siempre encendida aumenta costo. | Lambda, DynamoDB bajo demanda, SQS, EventBridge, Step Functions, Cloud Run y Azure Functions; no servidores propios permanentes. | Medir cuotas, escala y costo real de las cuentas. |

**Resultado del análisis:** D01–D13 están cubiertos **en la propuesta**. D06 depende de confirmar un canal real; D08 requiere completar consulta y eventos de GCP; D11 y D13 requieren mediciones. No presentaremos una decisión arquitectónica como una funcionalidad entregada.

## 3. Solución y diagrama

**AWS Academy** es la fuente de verdad para clientes ficticios, reportes, lecturas, episodios, incidentes, prioridad y comunicación. **GCP** analiza eventos depurados y produce sugerencias de IA revisables. **Azure** publica el último estado de zona recibido. **Cloudflare** puede servir de borde al portal estático y **Grafana Cloud** permite observar la salud de las tres nubes. Un reporte individual, una anomalía técnica y un incidente colectivo son entidades distintas; pueden reunirse bajo el mismo `incident_id` sin confirmar automáticamente una falla.

**Diagrama provisional de arquitectura v4:**

![Arquitectura general de Red TeleCorp v4](arquitectura-solucion-v4.svg)

**Diagrama del equipo en Eraser:** [abrir espacio de trabajo](https://app.eraser.io/workspace/GFexrYcESXJiLHryglNx?origin=share). Sustituiremos aquí el diagrama provisional por la versión final del equipo. Este README incluye **solo el diagrama general**; los flujos detallados se explican en texto.

**Conexiones por completar en el diagrama final:** la consulta `ObtenerTendencias ↔ red-telecorp-analisis` descrita en la sección 9; la detección de tres lecturas ausentes; y el canal de clientes que realmente permita AWS Academy. El diagrama provisional no demuestra por sí solo que esos tramos estén implementados.

## 4. Actores, entidades y reglas

- **Cliente:** inicia sesión, registra un reporte y consulta su estado. **Operador:** verifica evidencia, gestiona incidentes y reportes, y consulta tendencias/IA. **Responsables:** analizan patrones. La demo usa identidades y números de servicio ficticios.
- **30 antenas simuladas:** son **30 registros lógicos** de `NetworkCatalog` (tabla DynamoDB), con ID y zonas cubiertas. El número es una escala elegida para la demo, no una cifra impuesta por el enunciado. **Una sola** `GeneradoraDeMetricasYLotes` (AWS Lambda) crea aproximadamente 30 lecturas por minuto cuando la activa EventBridge. No existen 30 Lambdas ni antenas físicas.
- **Rangos de tráfico:** `0 GB/min` = inhabilitada; `0 < x < 60` = caída; `60 ≤ x ≤ 129` = normal en la simulación; `x > 129` = saturada. Tres lecturas consecutivas ausentes significan **telemetría ausente**, no `0`.
- **Reportes relacionados:** mismo `zone_id` y servicio (`internet`, `voz`, `mensajería` o `conectividad general`), aunque varíe el síntoma. Se cuentan `customer_id` únicos con `ahora − 24 h < occurred_at ≤ ahora`; `received_at` se guarda por separado. Diez usuarios abren un caso **sospechado** aunque las métricas sean normales o falten.
- **Episodios:** la primera lectura anómala abre uno; cinco normales consecutivas lo cierran. Una racha cuenta como un episodio. Tres episodios distintos de una antena en siete días móviles justifican una alerta estructural. Estas reglas de cierre y recurrencia son decisiones de prototipo.
- **Estados:** el reporte tiene `registrada → en revisión → siendo atendida → solucionada → cerrada`, con vuelta motivada a revisión. El incidente compartido tiene `sospechado → confirmado → restablecido → cerrado`, o `descartado`. Cada transición conserva estado anterior, nuevo, hora, actor y motivo. Una antena recuperada **no cierra** reportes por sí sola.
- **Prioridad propuesta:** P1 = falla confirmada en zona médica/crítica o ≥100 reportantes distintos de zona/servicio en 24 h; P2 = 10–99, antena inhabilitada o falla confirmada no crítica; P3 = señal aislada. Prevalece la prioridad más alta y una subida manual requiere motivo. Se muestra «usuarios que reportaron», no un total de afectados inventado.

## 5. Servicios por plataforma

Los recursos AWS declarados siguen el prefijo `red-telecorp-dev-`. «Declarado en YAML» **no significa desplegado**. Los nombres cortos siguientes son los del diseño y del [`serverless.yml`](aws/infra/serverless.yml).

### AWS Academy: portal, operación y dato principal

| Recurso | Servicio nativo | Responsabilidad |
| --- | --- | --- |
| `red-telecorp-portal` | Amplify Hosting | Frontend estático; se configura fuera del YAML. |
| `red-telecorp-dev-api-http` | API Gateway HTTP API | Rutas HTTPS del portal. |
| `AutenticarUsuario`, `AutorizarJWT` | Dos AWS Lambda; la segunda Lambda Authorizer | Credenciales ficticias, JWT y autorización sin Cognito. |
| `CrearReporte`, `ListarMisReportes`, `ObtenerReporte`, `ListarIncidentesZona`, `CambiarEstadoReporte`, `CambiarEstadoIncidente`, `ObtenerTendencias`, `ObtenerSugerenciaIA` | Ocho AWS Lambda, una por ruta | API de usuarios y operaciones. |
| `generar-metricas-cada-minuto`, `GeneradoraDeMetricasYLotes` | Regla EventBridge + AWS Lambda | Invocación/minuto y generación del lote sintético. |
| Bucket `red-telecorp-dev-metricas-<accountId>`, `ColaMetricas`, `ClasificadoraDeMetricas` | S3 + SQS/DLQ + AWS Lambda | Lote crudo, desacoplamiento y clasificación. |
| `CustomerProfiles`, `NetworkCatalog`, `Reports`, `CorrelationMembers`, `Incidents`, `Telemetry`, `Outbox` | Siete tablas DynamoDB | Perfiles, cobertura, reportes, miembros únicos, casos, episodios y eventos pendientes. |
| `EnrutadoraDeOutbox`, `OperacionesBus` | AWS Lambda + DynamoDB Streams + EventBridge bus | Publicación y distribución de eventos persistidos. |
| `ColaReportes`/`CorrelacionadoraDeReportes` y `ColaAnomalias`/`CorrelacionadoraDeAnomalias` | SQS/DLQ + AWS Lambda | Correlación de usuarios y de anomalías. La pareja de anomalías aún **no está en el YAML v2**. |
| `VerificarIncidente`, `VerificadoraDeEvidencias`, `CalculadoraDePrioridad`, `AlertadoraDeOperaciones` | Step Functions Standard + tres AWS Lambda | Evidencia, prioridad y alerta interna. |
| `ColaNotificaciones`, `NotificadoraDeClientes`, `MensajeriaClientesSMS` | SQS/DLQ + AWS Lambda + Amazon SNS SMS propuesto | Destinatarios, intención, envío y resultado. SMS depende de permisos. |
| `alertas-operaciones` | SNS topic | Aviso al equipo, separado de la comunicación a clientes. |
| `ColaGCP`/`PublicadoraHaciaGCP`; `ColaAzure`/`PublicadoraHaciaAzure` | Dos SQS/DLQ + dos AWS Lambda | Entrega HTTPS firmada y depurada a las otras nubes. |
| Claves de firma | SSM Parameter Store `SecureString` | Secretos JWT y de integración, fuera de Git. |

### GCP: historia e IA

`red-telecorp-analisis` (**Cloud Run function**) recibe eventos HTTPS firmados y sin PII; valida `event_id`/revisión y registra hechos en `incident_events` (**tabla BigQuery**). Para tendencias necesita eventos de cambios de incidente, episodios de antena y categorías de reporte depuradas. La función debe ofrecer una consulta autenticada de agregados de 7/30 días para `ObtenerTendencias` (AWS Lambda).

Para un incidente nuevo o actualizado, la misma función consulta antecedentes comparables y llama a **Gemini Developer API** con hechos ficticios o depurados. Devuelve `hipotesis`, `verificaciones`, `eventos_fuente` y `limitaciones` a AWS; la sugerencia queda asociada al incidente y se muestra mediante `ObtenerSugerenciaIA`. **La IA nunca confirma, descarta ni prioriza automáticamente.**

**A implementar en [`gcp/infra/`](gcp/infra/README.md):** proyecto, región, cuotas, Cloud Run con escala a cero, BigQuery, almacén de secretos y permisos; receptor firmado/idempotente, consulta de tendencias, llamada Gemini y pruebas. Validar el nivel gratuito disponible en el proyecto; no presuponer Vertex AI gratuito.

### Azure: estado público independiente

`red-telecorp-estado-api` (**Azure Functions**) recibe `incident.updated` firmado desde AWS, valida `event_id` y revisión, y proyecta un estado sin PII por zona en `EstadoZonas` (**Azure Table Storage**) con `last_synced_at`. Ofrece `GET /zones/{zone_id}/status`. `red-telecorp-estado-publico` (**Azure Static Web Apps**) muestra la respuesta en una página fuera de AWS.

Si AWS deja de publicar, Azure sigue mostrando **el último estado conocido** con aviso de atraso; no puede conocer incidentes nuevos que nunca recibió y no es réplica completa de AWS. Un reenvío antiguo no debe revertir una revisión nueva.

**A implementar en [`azure/infra/`](azure/infra/README.md):** suscripción, región, cuotas, Function, Storage Account/Table, secreto de firma y Static Web Apps; recepción firmada, `GET` público, idempotencia, CORS, criterio de dato atrasado y prueba durante una interrupción de AWS. Azure AI Language o Azure Email son alternativas **condicionales**, no dependencias actuales.

### Cloudflare y Grafana Cloud: opcionales

**Cloudflare** puede gestionar el dominio y actuar como proxy HTTPS delante de **Amplify Hosting**. El navegador llama a API Gateway por su propio endpoint; este proxy del portal **no cubre automáticamente la API**. Requiere dominio y pruebas DNS/TLS. **Grafana Cloud** recibe métricas de aplicación sin PII de AWS, GCP y Azure para mostrar errores, latencia, colas y retraso de sincronización. No conserva la verdad de los incidentes ni cambia sus estados. Se propone envío OTLP saliente para evitar crear roles IAM adicionales en AWS Academy.

## 6. Viaje de una petición desde el cliente y respuesta

### Abrir el portal e iniciar sesión

1. El navegador llega al dominio del portal. Si Cloudflare está habilitado, pasa por su DNS/proxy; **Amplify Hosting** entrega HTML, CSS y JavaScript. El frontend se ejecuta en el navegador, no en una Lambda de Amplify.
2. La pantalla de acceso llama por HTTPS a `POST /auth/login` de **API Gateway**. `AutenticarUsuario` (AWS Lambda) consulta `CustomerProfiles` (DynamoDB), comprueba credenciales de la demo y obtiene la clave de firma desde **SSM SecureString**.
3. La respuesta HTTP de API Gateway devuelve un **JWT de 15 minutos** al navegador. Se diseñó un token corto para limitar la vida de una credencial robada. No hay renovación automática definida: al vencer, el usuario deberá volver a autenticarse o habrá que implementar explícitamente la renovación.
4. En cada ruta protegida, el navegador envía `Authorization: Bearer <JWT>` directamente al endpoint HTTPS de API Gateway. `AutorizarJWT` (Lambda Authorizer) valida firma, emisor, audiencia, vencimiento y rol. Cada Lambda de negocio también comprueba que el usuario pueda acceder **a ese reporte o incidente**, no solo que el token sea válido.

### Crear un reporte y recibir confirmación

5. El usuario ingresa identificación, número del servicio, ubicación aproximada/zona, fecha y hora del problema, tipo de problema y descripción. `POST /reports` llega a `CrearReporte` tras el authorizer. La Lambda valida pertenencia del número de servicio, zona, tiempos, campos y clave de idempotencia.
6. `CrearReporte` persiste el reporte `Reports META`, la membresía pertinente en `CorrelationMembers` y el evento `report.created` en `Outbox` mediante una operación coherente. **Solo después de persistirlo** devuelve al navegador `report_id` y estado `registrada`. No espera a Step Functions, Gemini ni a la mensajería. Un reintento con la misma clave debe recuperar el mismo reporte.
7. La parte asíncrona continúa `Outbox → DynamoDB Streams → EnrutadoraDeOutbox → OperacionesBus → ColaReportes → CorrelacionadoraDeReportes`. Si el décimo cliente distinto completa el grupo, se crea o actualiza un incidente sospechado; el reporte ya era visible antes de terminar esta correlación.

### Leer la respuesta actualizada

8. `GET /reports/mine` usa `ListarMisReportes` y el índice por usuario de `Reports`; `GET /reports/{id}` usa `ObtenerReporte`. La respuesta recorre `navegador → API Gateway → AutorizarJWT → Lambda → DynamoDB → Lambda → API Gateway → navegador`. Incluye estado e historial del reporte y, si existe vínculo, una referencia al incidente de zona.
9. El operador usa rutas protegidas `/ops/...`: `ListarIncidentesZona`, `CambiarEstadoReporte`, `CambiarEstadoIncidente`, `ObtenerTendencias` y `ObtenerSugerenciaIA`. Un `PATCH` actualiza `META` y añade `HIST`; el siguiente `GET` devuelve la nueva versión. El diseño no promete cambios visuales instantáneos: el frontend deberá volver a consultar o refrescar periódicamente.
10. Un mensaje SMS/correo es **otro canal**, no la respuesta HTTP de `POST /reports`. Se dispara más tarde cuando existe un hito comunicable del incidente. El portal siempre permite consultar el estado aunque el envío externo esté bloqueado.

## 7. Viaje de las métricas de antenas

1. `NetworkCatalog` (DynamoDB) contiene los ID y la cobertura de las 30 antenas ficticias. Una antena puede cubrir varias zonas y una zona puede depender de varias antenas.
2. `generar-metricas-cada-minuto` (regla EventBridge) ejecuta **una** `GeneradoraDeMetricasYLotes` (AWS Lambda). Esta produce un archivo comprimido `telemetry/raw/*.json.gz` con lecturas que contienen `antenna_id`, `measured_at`, `traffic_gb_per_min` y `event_id` y lo guarda en el bucket **S3** de métricas crudas. El generador debe permitir secuencias reproducibles para los escenarios de prueba.
3. El evento `s3:ObjectCreated` coloca la referencia del objeto en `ColaMetricas` (**SQS**). `ClasificadoraDeMetricas` (AWS Lambda) consume el mensaje, lee el lote y valida cada lectura. La cola absorbe diferencias de ritmo entre generación y clasificación; la **DLQ** conserva mensajes que agotan reintentos.
4. La clasificadora actualiza `Telemetry` (DynamoDB) con la lectura y el estado anterior de la antena. Mantiene un episodio abierto, contador de normales y episodios cerrados. Lecturas anómalas consecutivas son **un solo episodio**; cinco normales consecutivas emiten recuperación. Tres episodios distintos en siete días móviles emiten recurrencia.
5. Los cambios relevantes producen eventos en `Outbox`. **DynamoDB Streams** activa `EnrutadoraDeOutbox`, que publica `telemetry.anomaly`, `telemetry.recovered` o `telemetry.recurrent` en `OperacionesBus` (**EventBridge**). Estos eventos deben ir a `ColaAnomalias` (**SQS**) y `CorrelacionadoraDeAnomalias` (AWS Lambda).
6. La correlacionadora consulta `NetworkCatalog` para conocer zonas cubiertas y busca un incidente compatible. Si no hay uno, puede crear una **sospecha técnica** en `Incidents` antes del primer reporte de usuario; si hay varios candidatos, solicita revisión humana. La señal técnica inicia `VerificarIncidente` (Step Functions). Una antena que vuelve a valores normales aporta evidencia, pero **no** declara por sí sola el restablecimiento del servicio de cada cliente.
7. Tres minutos sin lecturas se deben marcar como **telemetría ausente**, un caso distinto de antena inhabilitada. El mecanismo que detecta ausencias aunque no llegue ningún archivo de esa antena todavía debe implementarse explícitamente.

## 8. Incidentes, prioridad, historial y comunicación

### Dos maneras de abrir la misma investigación

**Origen usuario:** `CorrelationMembers` permite contar `customer_id` distintos por zona/servicio y ventana móvil estricta. Al décimo, `CorrelacionadoraDeReportes` usa un puntero activo y escritura condicional para crear un solo `Incidents` en estado `sospechado`, o reforzar uno existente. El undécimo reportante se enlaza al mismo `incident_id`. **No se exige conocer la antena averiada.**

**Origen infraestructura:** `CorrelacionadoraDeAnomalias` puede haber creado primero una sospecha técnica. Las dos correlacionadoras comparan zona, cobertura y ventana temporal. Con **un** candidato compatible, anexan evidencia y reportes al mismo ID; con varios, guardan el caso para revisión humana sin unirlos arbitrariamente. Una lectura anómala no prueba por sí sola qué usuarios fueron afectados. **Ventana propuesta de asociación:** hora declarada del reporte entre cinco minutos antes del inicio del episodio y 30 minutos después de su fin; un episodio abierto sigue siendo candidato. Es una decisión revisable del prototipo, no un número exigido por la hackathon.

### Verificación y prioridad

Un caso nuevo, el umbral de 10/100 usuarios, una nueva señal técnica, una recuperación o una decisión operativa incrementan la revisión del incidente. `VerificarIncidente` (**Step Functions Standard**) ejecuta `VerificadoraDeEvidencias → CalculadoraDePrioridad → AlertadoraDeOperaciones` (tres AWS Lambda). La primera reúne lecturas, zonas cubiertas, reportes y evidencia interna sintética; la segunda consulta `NetworkCatalog`, `CorrelationMembers`, `Telemetry` e `Incidents` para aplicar P1–P3. La tercera publica al SNS topic `alertas-operaciones`.

La ejecución se identifica por `incident_id + revision` para evitar duplicar una verificación. Guardar el resultado de un intento de notificación **no** incrementa esta revisión ni vuelve a iniciar Step Functions. La máquina sugiere prioridad y evidencia; **el operador confirma, descarta o declara restablecido** con un motivo registrado.

### Historial y seguimiento individual

`Incidents` es la tabla central: `META` guarda estado, prioridad y responsable; `HIST#...` guarda transiciones; `LINK#<report_id>` identifica reportes relacionados; `NOTIFY#<customer_id>#<hito>` guarda intenciones e intentos de comunicación. `Reports` guarda `META` y `HIST#...` de cada reporte. `CambiarEstadoIncidente` y `CambiarEstadoReporte` actualizan el estado actual **y anexan historia**, sin sobrescribir transiciones anteriores. Los reportes individuales pueden seguir en revisión aunque el incidente técnico se haya recuperado.

Las marcas `first_signal_at`, `detected_at`, `confirmed_at`, `restored_at` y `closed_at` permiten medir tiempo de detección, duración y evolución. Mostrar el número de **usuarios distintos que reportaron** evita presentarlo como el total real de personas afectadas.

### Comunicación a clientes frente a alertas internas

`incident.updated` en los hitos **en evaluación**, **incidencia confirmada** y **servicio restablecido**, además de `report.linked` para un cliente que llega tarde, viaja por `OperacionesBus → ColaNotificaciones → NotificadoraDeClientes`. La Lambda lee los `LINK` de `Incidents`, los reportes y `CustomerProfiles` para escoger solo a quienes corresponden y respetar contacto/consentimiento.

Se crea una intención única `NOTIFY#customer_id#hito`; después se registra canal, hora, intento y resultado. El canal del diagrama es `MensajeriaClientesSMS` (**Amazon SNS SMS**), sujeto a una prueba de permisos y entrega en AWS Academy. Si no funciona, habría que validar correo con SES o la alternativa Azure antes de cambiarlo. Un reintento conserva la intención, aunque la entrega externa no puede prometerse exactamente una vez. Sin canal disponible, el estado continúa en el portal.

`AlertadoraDeOperaciones → alertas-operaciones` es **solo para el equipo interno**. No reemplaza `NotificadoraDeClientes`. Una recuperación técnica no genera el mensaje «servicio restablecido» hasta que el operador registre ese hito.

## 9. Ida y vuelta entre AWS, GCP y Azure

### AWS → GCP → AWS → panel del operador

1. `OperacionesBus` enruta eventos depurados a `ColaGCP` (**SQS**). `PublicadoraHaciaGCP` (AWS Lambda) firma el cuerpo con una clave protegida en SSM y hace `POST` HTTPS a `red-telecorp-analisis` (**Cloud Run function**). Deben viajar `event_id`, tipo, tiempo, zona/servicio, `incident_id` y revisión cuando correspondan; **no** nombres, teléfonos, números de servicio ni descripción libre.
2. Cloud Run valida firma y caducidad, deduplica el evento y registra hechos en `incident_events` (**BigQuery**). Para D08 necesita categorías depuradas de `report.created`, episodios de antena e `incident.updated`. **La regla `ReglaGCP` del YAML v2 todavía no incluye todos esos eventos.**
3. Ante un incidente pertinente, Cloud Run consulta pocos antecedentes comparables en BigQuery y llama a **Gemini Developer API**. La respuesta estructurada (hipótesis, verificaciones y fuentes) **regresa a AWS** por la respuesta HTTPS a `PublicadoraHaciaGCP`; esta la guarda asociada al caso en `Incidents`. El contrato y el límite de tiempo de esa vuelta aún requieren implementación. Si la IA tarda más de lo permitido, habrá que diseñar un retorno asíncrono firmado.
4. Cuando el operador llama `GET /ops/incidents/{id}/ai-suggestion`, `ObtenerSugerenciaIA` lee la sugerencia persistida en AWS y la devuelve por API Gateway al navegador. El operador puede revisarla; no cambia estados automáticamente.
5. Para tendencias, `GET /ops/trends` llega a `ObtenerTendencias` (AWS Lambda). **Ruta objetivo aún no implementada:** consulta HTTPS autenticada a Cloud Run → agregados BigQuery de 7/30 días → respuesta Cloud Run → Lambda → API Gateway → navegador. Esta vuelta concreta completa D08 y debe añadirse al código/contrato de GCP.

### AWS → Azure → navegador público

1. `incident.updated` se enruta a `ColaAzure` (**SQS**). `PublicadoraHaciaAzure` (AWS Lambda) firma un resumen **sin PII** y lo entrega por HTTPS a `red-telecorp-estado-api` (**Azure Functions**).
2. Azure valida firma, `event_id` y revisión; actualiza `EstadoZonas` (**Azure Table Storage**) con estado público por zona y `last_synced_at`. Devuelve a AWS un resultado de recepción. Un reenvío antiguo no debe revertir una versión más reciente.
3. Un visitante abre **directamente** `red-telecorp-estado-publico` (**Azure Static Web Apps**), sin pasar por Amplify. El navegador llama al `GET /zones/{zone_id}/status` de Azure Functions; esta lee Table Storage y devuelve estado y hora de sincronización al navegador.
4. Si AWS deja de enviar eventos, Azure conserva el **último dato conocido** y marca su antigüedad. No puede conocer nuevas incidencias no recibidas ni reemplaza la base operacional de AWS.

### Métricas operativas → Grafana Cloud

Las funciones de las tres nubes pueden enviar por HTTPS métricas agregadas sin PII —errores, latencia, profundidad de colas, retraso de Azure— a **Grafana Cloud** mediante OTLP. El retorno es un **panel para el equipo**; Grafana no modifica incidentes ni funciona como base de datos del producto. Su plan, cuotas y token todavía deben comprobarse.

## 10. Datos, eventos, seguridad, fallos y costo

**Modelo operativo:** `CustomerProfiles` conserva perfiles/consentimiento ficticios; `NetworkCatalog`, zonas, antenas, cobertura y criticidad; `Reports`, estados e historial individual; `CorrelationMembers`, membresía única del grupo; `Incidents`, caso compartido e historial; `Telemetry`, lecturas y episodios; `Outbox`, eventos por publicar. Son **siete tablas DynamoDB** separadas, declaradas bajo demanda. `Reports` tiene índices por usuario y por zona/estado; `Incidents`, por zona/caso abierto. Las búsquedas críticas deben usar clave o índice y escrituras condicionales, no `Scan` de toda la tabla. El diseño físico exacto de algunas consultas de ventana móvil aún debe comprobarse con carga.

**Contrato de eventos propuesto:** `event_id`, versión de esquema, `type`, `occurred_at`, origen, zona/servicio si aplican, `incident_id` y `revision`. Tipos relevantes: `report.created`, `report.linked`, `report.status.changed`, `telemetry.anomaly`, `telemetry.recovered`, `telemetry.recurrent`, `incident.suspected` e `incident.updated`. Los cruces de nube usan una versión depurada. El cambio de negocio y su Outbox deben ser atómicos o tener conciliación; cada consumidor debe manejar reintentos sin duplicar efectos. El YAML v2 aún debe incorporar `ColaAnomalias`, su correlacionadora y las reglas de eventos v4.

**Seguridad:** el laboratorio AWS Academy del equipo usa `LabRole` y no permite crear roles IAM; la plantilla utiliza ese rol existente. Las contraseñas ficticias se guardan con hash y sal; la autenticación propia es para la demo y necesitaría endurecimiento antes de uso real. SSM Parameter Store `SecureString` protege claves JWT e integración. GCP/Azure guardan sus claves equivalentes en almacenes de secretos, fuera de Git y del frontend. `AutorizarJWT` y cada Lambda de negocio aplican acceso por rol/propiedad. Se usan datos sintéticos y no se envía PII a GCP, Azure o Grafana. No se presupone WAF ni permiso efectivo para Streams, Step Functions, SNS SMS o SES: hay que probarlos en la cuenta real.

**Fallos y durabilidad:** un reporte solo se declara aceptado tras persistirse. Outbox evita perder la intención de publicar eventos, y SQS con DLQ permite reintentos y revisión de errores. Una caída de GCP, Azure o Gemini **no debe impedir** registrar reportes en AWS; la entrega entre nubes se reintenta y Azure expone la antigüedad de su copia. La base administrada y la copia pública no son un plan de respaldo completo: falta definir y probar respaldo/restauración y conciliación de Outbox según permisos y presupuesto de AWS Academy.

**Escala y costo de la demo:** 30 antenas × una lectura/minuto y una prueba de **1000 reportes en diez minutos**. Metas internas: confirmar recepción p95 en <3 s y detectar el umbral colectivo en <2 min. Retención propuesta: 30 días de detalle de métricas y un año de reportes, incidentes y agregados. Son objetivos/supuestos, **no garantías**. Deben medirse cuotas, latencia, costo y vida efectiva del laboratorio antes de afirmar capacidad para millones de usuarios.

## 11. Rúbrica y evidencias pendientes

La evaluación de D01–D13 está **antes** de esta sección para comprobar que la solución aborda el problema y no solo enumera servicios. La matriz viva es [rubrica-hackathon.md](rubrica-hackathon.md). Ningún punto se considera ganado por dibujar el flujo.

| Criterio | Máximo | Qué mostrar en la demo | Estado |
| --- | ---: | --- | --- |
| Problemas del contexto | 3 | Escenarios de los dolores D01–D13, incluidos mensaje recibido y tendencias. | Diseñado; pruebas pendientes. |
| Persistencia y alta disponibilidad | 2 | Reporte/historial durable, reintento, fallo y recuperación comprobados. | Pendiente. |
| Step Functions | 2 | Ejecución real de `VerificarIncidente`, pasos, fallos y resultado. | Declarado en YAML; despliegue pendiente. |
| Dos nubes o más | 3 | AWS + GCP conectadas y funcionales; Azure añade estado público. | Pendiente de despliegue. |
| Arquitectura | 3 | Diagrama final del equipo con flujos, fronteras, datos, seguridad y costos. | Propuesta; versión final pendiente. |
| Pitch | 2 | Video claro de **máximo cinco minutos**. | Pendiente. |
| Serverless | 2 | Ejecución sin servidores propios permanentes en las nubes usadas. | Propuesto; configuración real pendiente. |
| IA funcional | 3 | Sugerencia Gemini invocable, útil y revisable, con entrada/salida visibles. | Pendiente. |

**Condiciones de entrega:** al menos **dos nubes**; dos cuentas AWS no equivalen a dos proveedores. Video exportado `≤ 05:00`. Entregar por Canvas **video, repositorio GitHub y arquitectura**. El enunciado pide **no adjuntar un informe**; este README es documentación de trabajo del repositorio, no un archivo de informe para Canvas. Debe mostrarse un servicio AWS que proteja variables/secretos: se propone **SSM Parameter Store `SecureString`**.

## 12. Implementación pendiente y archivos de referencia

1. **AWS Academy:** validar `LabRole`, región, cuotas, Streams, Step Functions, SSM y mensajería; implementar frontend, handlers, datos sintéticos, episodios, las dos correlacionadoras, historia, prioridad, notificaciones y pruebas. Alinear [`aws/infra/serverless.yml`](aws/infra/serverless.yml) con v4. El YAML por sí solo **no implementa** los handlers.
2. **GCP:** infraestructura reproducible, Cloud Run, BigQuery, secreto, receptor firmado, categorías de eventos, consulta de tendencias y sugerencia Gemini. Ver [`gcp/infra/`](gcp/infra/README.md) y [decisión de IA](decision-ia.md).
3. **Azure:** infraestructura reproducible, Functions, Table Storage, Static Web Apps, secreto, proyección por revisión, consulta pública y aviso de dato atrasado. Ver [`azure/infra/`](azure/infra/README.md).
4. **Opcionales:** dominio/proxy Cloudflare y métricas Grafana, si hay acceso, cuota y tiempo, sin desplazar los flujos obligatorios.
5. **Demostración:** valores de borde `0/59/60/129/130`; 9 frente a 10 clientes únicos; recurrencia y recuperación; prioridad crítica; mensaje real; estados/historial; tendencias; IA; caída de integración; carga de 1000 reportes. Guardar evidencia en [PENDIENTES.md](PENDIENTES.md) y [rubrica-hackathon.md](rubrica-hackathon.md).

**Fuentes de esta guía:** [enunciado original](hackathonCloudEnunciado.txt), [puntos de dolor y reglas S01–S12](puntos-dolor-cliente.md), [arquitectura v4 propuesta](arquitectura-solucion-v4.md), [plantilla AWS](aws/infra/serverless.yml) y [checklist](PENDIENTES.md). Si una implementación cambia un contrato o una conexión, actualizar esta guía y el diagrama del equipo.
