# Pendientes de implementación — Red TeleCorp

Actualizado: 14 de noviembre de 2026. **Estado:** hay una [plantilla declarativa AWS v2](aws/infra/serverless.yml), pero los cambios de la [arquitectura v4 propuesta](arquitectura-solucion-v4.md) y todo el despliegue requieren implementación y pruebas. Marcar `[x]` únicamente después de guardar evidencia. IA: [decisión v1](decision-ia.md).

## Revisión de arquitectura v4 — seis observaciones funcionales

Estas casillas describen implementación y prueba, **no elementos ya resueltos por el dibujo**. La [nota v4](arquitectura-solucion-v4.md) distingue reglas previas de omisiones visuales.

- [ ] **OBS-05 · Comunicación a afectados:** implementar `incident.updated` por hito y `report.linked` para usuarios que llegan tarde → `ColaNotificaciones` → `NotificadoraDeClientes`; leer `Incidents LINK`, `Reports` y `CustomerProfiles`, crear intención única `NOTIFY#cliente#hito`, respetar consentimiento y guardar canal, hora, intento y resultado. **Hecho cuando:** solo los usuarios relacionados reciben el hito correcto y un reintento no crea otra intención; una prueba muestra recepción real por un canal permitido.
- [ ] **OBS-06 · Estado de episodios:** persistir en `Telemetry` estado anterior, episodio abierto, contador de normales y episodios cerrados; publicar `telemetry.anomaly`, `telemetry.recovered` y `telemetry.recurrent` por Outbox. **Hecho cuando:** lecturas anómalas consecutivas forman un episodio, cinco normales lo cierran, datos ausentes no lo cierran y tres episodios en siete días activan revisión.
- [ ] **OBS-07 · Prioridad dinámica:** completar `VerificarIncidente → VerificadoraDeEvidencias → CalculadoraDePrioridad → AlertadoraDeOperaciones`; leer criticidad de `NetworkCatalog`, usuarios únicos de `CorrelationMembers`, severidad de `Telemetry` y estado de `Incidents`. Recalcular en nuevas evidencias, umbrales 10/100, recuperación y cambio del operador; usar `incident_id + revision` para idempotencia. **Hecho cuando:** casos de P1/P2/P3 muestran regla aplicada y una revisión no duplica alertas.
- [ ] **OBS-08 · Historial de estados:** `CambiarEstadoReporte` y `CambiarEstadoIncidente` actualizan `META` y anexan `HIST` con estado anterior/nuevo, actor, hora y motivo. **Hecho cuando:** se reconstruyen los cinco estados de cada reporte y el ciclo independiente del incidente, incluida una devolución a revisión.
- [ ] **OBS-09 · Colectivo sin antena:** contar diez clientes distintos de zona/servicio en menos de 24 h y crear sospecha aun con telemetría normal o ausente; buscar antena/caso técnico después. **Hecho cuando:** el décimo crea un solo incidente sin anomalía y el undécimo comparte `incident_id`; una antena compatible posterior se enlaza sin duplicación.
- [ ] **OBS-10 · Recuperación técnica:** cinco lecturas normales publican `telemetry.recovered`; la evidencia actualiza el caso y recalcula prioridad. El operador decide restablecimiento; los reportes siguen su propio ciclo. **Hecho cuando:** recuperación sola no marca `Incidents` como restablecido ni cierra `Reports`, y el hito de restablecimiento notifica solo tras decisión operativa.

## Observaciones del equipo incorporadas a la arquitectura v4

Estas casillas son **trabajo propuesto**, no funcionalidad desplegada. La [propuesta v4](arquitectura-solucion-v4.md) conserva las decisiones y los nombres de recursos.

- [ ] **OBS-01 · Detección técnica antes de 10 reportes:** conectar `telemetry.anomaly` → `OperacionesBus` → nueva `ColaAnomalias` + DLQ → nueva `CorrelacionadoraDeAnomalias` → `Incidents` → `VerificarIncidente`. Un episodio nuevo genera una sola sospecha técnica; `0` se atiende inmediatamente y las otras clasificaciones se verifican antes de confirmar afectación. **Hecho cuando:** una antena anómala inicia una ejecución de Step Functions sin reportes de usuarios y queda registrada como sospecha, no como falla confirmada.
- [ ] **OBS-02 · Unificación de señales:** usar `NetworkCatalog` para cobertura antena-zona; consultar con lectura consistente los punteros activos en `Incidents` por zona/servicio y ventana temporal, enlazar reportes y evidencia técnica al mismo `incident_id` con actualización condicional. Los casos ambiguos quedan para revisión humana. **Hecho cuando:** anomalía → reportes y reportes → anomalía producen un solo incidente; el reporte 10 lo refuerza; un reporte ajeno no se vincula; reintentos no duplican incidente ni notificación.
- [ ] **OBS-03 · Valor propio de Azure:** añadir una página pública independiente en Azure Static Web Apps sobre las Azure Functions y Table Storage ya propuestos, con `last_synced_at` y aviso de dato atrasado. **Hecho cuando:** la página de Azure muestra el último estado conocido aunque el portal AWS no responda; no se presenta como dato en tiempo real durante una caída del emisor.
- [ ] **EDGE-01 · Cloudflare delante de Amplify:** si hay dominio, configurar DNS de verificación en modo DNS only, verificar TLS en Amplify y luego probar proxy Full (Strict) solo para el portal; dejar la validación ACM sin proxy. **Hecho cuando:** `portal.<dominio>` sirve el portal por HTTPS sin bucles ni caché de respuestas privadas. Cloudflare no sustituye API Gateway ni demuestra otra nube funcional.
- [ ] **OBS-04 · Grafana Cloud transversal:** evaluar plan/cuotas, guardar token OTLP fuera de Git y enviar métricas de aplicación sin PII desde AWS, GCP y Azure; probar comprobaciones HTTPS públicas si la cuota lo permite. **Hecho cuando:** un panel distingue salud y retraso de cada nube. No usar el conector directo CloudWatch si exige crear un rol IAM prohibido por AWS Academy.
- [ ] Alinear [serverless.yml](aws/infra/serverless.yml) con `ColaAnomalias` y `CorrelacionadoraDeAnomalias` y ejecutar `serverless package` sin roles IAM nuevos. **Hecho cuando:** plantilla y arquitectura v4 coinciden, sin dependencias circulares.

## AWS Academy — núcleo operativo

### Acceso y seguridad

- [ ] Comprobar en el laboratorio región, saldo/cuotas y `LabRole`: confianza `lambda.amazonaws.com`, `states.amazonaws.com`, `iam:PassRole` y permisos para API Gateway, DynamoDB, S3, SQS, EventBridge, Step Functions, SSM/KMS, SNS/SES y Amplify. **Hecho cuando:** pruebas mínimas de creación/invocación funcionan o se registran bloqueos exactos.
- [ ] Probar el [Serverless Framework v3](aws/infra/serverless.yml) con `LabRole` sin crear roles IAM; completar marcadores y handlers. **Hecho cuando:** otro integrante puede reproducir la infraestructura y se verifica que la plantilla no crea roles.
- [ ] Crear parámetros `SecureString` separados para firma JWT y firmas entre nubes; probar lectura desde las Lambdas. **Hecho cuando:** las claves no aparecen en Git, frontend ni logs y una invocación autorizada las recupera.
- [ ] Implementar `POST /auth/login` con `AutenticarUsuario`, cuentas ficticias y contraseñas con hash/sal. Emitir JWT breve con `sub`, rol, `iss`, `aud`, `exp`, `jti`, sin PII. **Hecho cuando:** login válido emite token y credenciales erróneas no lo hacen.
- [ ] Implementar `AutorizarJWT` como Lambda Authorizer para rutas protegidas de API Gateway; caché desactivada en la plantilla actual. **Hecho cuando:** token vencido, alterado o de otro rol es rechazado; el usuario no puede consultar reportes ajenos. [Diseño vigente](arquitectura-solucion-v4.md).
- [ ] Desplegar SPA estática en Amplify, CORS y límites de API/login. **Hecho cuando:** portal de usuario y operador funcionan por HTTPS sin secretos en el navegador.

### Datos, API e ingesta

- [ ] Crear tablas DynamoDB on-demand e índices declarados en [serverless.yml](aws/infra/serverless.yml): `CustomerProfiles`, `NetworkCatalog`, `Reports`, `CorrelationMembers`, `Incidents`, `Telemetry`, `Outbox`. **Hecho cuando:** las consultas principales usan PK/SK o GSI, no `Scan`, los TTL previstos están configurados y los punteros activos v3 se consultan consistentemente.
- [ ] Sembrar clientes ficticios, zonas de cinco tipos y mapa antena-zona. **Hecho cuando:** un reporte valida número/cliente y la verificación encuentra todas las antenas de su zona.
- [ ] Implementar API de reportes y estados con transacciones, historial e idempotencia. **Hecho cuando:** un reporte aceptado persiste; un reintento con la misma clave no duplica el caso; los cinco estados quedan auditados.
- [ ] Crear regla programada EventBridge, Lambda simuladora, bucket S3 de lotes, notificación S3→SQS y Lambda clasificadora. **Hecho cuando:** 30 antenas producen una lectura/minuto y `0`, `59`, `60`, `129`, `130` se clasifican correctamente; telemetría ausente queda separada de `0`.
- [ ] Implementar episodios y recurrencia (tres episodios en siete días). **Hecho cuando:** una racha continua cuenta como uno y tres rachas distintas generan alerta.

### Eventos, incidentes y comunicación

- [ ] Implementar Outbox→DynamoDB Streams→Lambda router→EventBridge; añadir conciliación de pendientes y destino de fallo. **Hecho cuando:** los eventos se publican tras la transacción y se recuperan de un fallo simulado.
- [ ] Crear colas SQS separadas para reportes, métricas, GCP, Azure y notificaciones, cada una con DLQ y alarmas. **Hecho cuando:** un consumidor fallido no detiene otro y el mensaje acaba en su DLQ tras agotar reintentos.
- [ ] Implementar correlación con dos particiones diarias, lectura consistente, paginación y usuarios únicos. **Hecho cuando:** 9 no activan, 10 sí, duplicados no cuentan y un reporte exactamente a 24 h queda fuera.
- [ ] Desplegar Step Functions Standard para verificar antenas, registrar evidencias, calcular prioridad y alertar al operador. **Hecho cuando:** una ejecución real aparece en historial y el incidente sigue sospechado hasta decisión humana. **Bloqueo posible:** confianza/`PassRole` de `LabRole`.
- [ ] Implementar cambios de estado de incidente, notificaciones por hito y alerta SNS a operaciones. **Hecho cuando:** historial, prioridad y enlaces a reportes son visibles, con una intención de envío por usuario/hito.
- [ ] Probar un canal **real** de correo o SMS permitido (SNS/SES o alternativa Azure). **Hecho cuando:** llega un mensaje a un destino de prueba y se registra su resultado; el estado en portal por sí solo no cierra este punto.
- [ ] Configurar respaldo/recuperación que permita el laboratorio, alarmas y prueba de ráfaga de 1000 reportes/10 min. **Hecho cuando:** no se pierde ningún reporte aceptado, hay medición de latencia/costo y se puede reproducir la recuperación.

## Google Cloud / GCP — analítica e IA

- [ ] Confirmar proyecto, facturación, cuotas, región y acceso a Cloud Run, BigQuery y Gemini Developer API Free. **Hecho cuando:** el equipo ejecuta llamadas pequeñas y registra los límites reales. El nivel gratuito de Gemini API es distinto de Vertex AI.
- [ ] Crear la infraestructura en [`gcp/infra/`](gcp/infra/README.md): Cloud Run function con escala a cero, dataset/tabla BigQuery particionada y almacén de secretos. **Hecho cuando:** otro integrante puede reproducir recursos y permisos.
- [ ] Implementar receptor HTTPS firmado para eventos depurados desde AWS. **Hecho cuando:** acepta firma válida, rechaza firma/caducidad inválidas y procesa `event_id` de forma idempotente.
- [ ] Guardar revisiones de incidentes y agregados sin PII en BigQuery; exponer consultas de tendencias por zona, antena y tipo. **Hecho cuando:** el panel responde correctamente preguntas de 7/30 días y reenvíos no duplican conteos.
- [ ] Implementar la llamada a Gemini Developer API con hechos actuales y casos comparables de BigQuery. **Hecho cuando:** entrega hipótesis, verificaciones y eventos fuente; no confirma incidentes automáticamente.
- [ ] Probar tres escenarios sintéticos, consumo de cuota, latencia y salida visible al operador. **Hecho cuando:** la IA reconoce incertidumbre cuando las métricas no corroboran los reportes. No enviar datos reales al nivel gratuito.

## Azure — estado público y alternativa de IA

- [ ] Confirmar suscripción, región, cuota y acceso a Azure Functions Flex Consumption, Table Storage y secret store. **Hecho cuando:** POST/GET de prueba funcionan en la suscripción del equipo.
- [ ] Codificar infraestructura en [`azure/infra/`](azure/infra/README.md): Function con `always ready = 0`, Storage Account/Table y secreto de firma. **Hecho cuando:** otro integrante puede reproducir los recursos.
- [ ] Implementar recepción HTTPS firmada de `incident.updated` desde AWS, idempotencia por `event_id`/revisión y proyección sin PII. **Hecho cuando:** la tabla refleja el último estado y un reenvío viejo no lo revierte.
- [ ] Publicar `GET /zones/{zone_id}/status` con `last_synced_at` y CORS apropiado. **Hecho cuando:** se puede consultar desde navegador incluso si el API principal AWS no responde, y se ve si el dato está atrasado.
- [ ] **Opcional:** probar Azure AI Language F0 para resumen/frases clave si Gemini Free no está disponible. **Hecho cuando:** una salida útil se ve en operaciones, sin exceder el cupo compartido de 5000 records/mes.
- [ ] **Opcional si AWS mensajería está bloqueada:** evaluar Azure Communication Services Email y dominio habilitado. **Hecho cuando:** llega un correo real de prueba; registrar costo/permisos.

## Integración, calidad y entrega

- [ ] Definir contrato versionado de eventos (`event_id`, `type`, `occurred_at`, `zone_id`, `service`, `revision`) y la firma HTTPS; documentar qué campos nunca cruzan de AWS. **Hecho cuando:** GCP y Azure validan el mismo ejemplo y rechazan el alterado.
- [ ] Ejecutar prueba completa: reporte → décimo usuario → incidente sospechado → Step Functions → operador confirma → comunicación → IA/tendencias → estado Azure. **Hecho cuando:** existen capturas/logs de cada tramo y la [rúbrica](rubrica-hackathon.md) enlaza la evidencia.
- [ ] Actualizar diagramas tras los despliegues reales y medir latencia/costo/fallos. **Hecho cuando:** no quedan flechas del diagrama que representen servicios no implementados sin una marca de «propuesto».
- [ ] Preparar pitch y video de **menos de cinco minutos**, verificar duración exportada. **Hecho cuando:** el archivo final se reproduce completo y dura `<= 05:00`.
- [ ] Publicar repo, video y **diagrama** vía Canvas; no adjuntar informe. **Hecho cuando:** los tres elementos son accesibles para el jurado y se comprueba la entrega.
