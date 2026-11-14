# Pendientes de implementación — Red TeleCorp

Actualizado: 14 de noviembre de 2026. **Estado:** todo lo siguiente requiere despliegue/prueba; los diagramas y documentos están en la raíz. Marcar `[x]` únicamente después de guardar evidencia (archivo, enlace, captura o resultado de prueba) en esta lista o en [rubrica-hackathon.md](rubrica-hackathon.md). Arquitectura: [v1](arquitectura-solucion-v1.md). IA: [decisión v1](decision-ia.md).

## AWS Academy — núcleo operativo

### Acceso y seguridad

- [ ] Comprobar en el laboratorio región, saldo/cuotas y `LabRole`: confianza `lambda.amazonaws.com`, `states.amazonaws.com`, `iam:PassRole` y permisos para API Gateway, DynamoDB, S3, SQS, EventBridge, Step Functions, SSM/KMS, SNS/SES y Amplify. **Hecho cuando:** pruebas mínimas de creación/invocación funcionan o se registran bloqueos exactos.
- [ ] Definir el mecanismo de despliegue en [`aws/infra/`](aws/infra/README.md) sin crear roles IAM; codificar recursos y parámetros. **Hecho cuando:** otro integrante puede reproducir la infraestructura usando `LabRole` y las instrucciones del repo.
- [ ] Crear parámetros `SecureString` separados para firma JWT y firmas entre nubes; probar lectura desde las Lambdas. **Hecho cuando:** las claves no aparecen en Git, frontend ni logs y una invocación autorizada las recupera.
- [ ] Implementar `POST /auth/login` con Lambda Auth, cuentas ficticias y contraseñas con hash/sal. Emitir JWT breve con `sub`, rol, `iss`, `aud`, `exp`, `jti`, sin PII. **Hecho cuando:** login válido emite token y credenciales erróneas no lo hacen.
- [ ] Configurar Lambda Authorizer para rutas protegidas de API Gateway; desactivar caché en v1. **Hecho cuando:** token vencido, alterado o de otro rol es rechazado; el usuario no puede consultar reportes ajenos. [Diseño](arquitectura-solucion-v1.md#vista-por-capas-tres-nubes).
- [ ] Desplegar SPA estática en Amplify, CORS y límites de API/login. **Hecho cuando:** portal de usuario y operador funcionan por HTTPS sin secretos en el navegador.

### Datos, API e ingesta

- [ ] Crear tablas DynamoDB on-demand e índices descritos en [diseño de datos](arquitectura-solucion-v1.md#diseño-de-datos-consultas-primero-claves-después): `CustomerProfiles`, `NetworkCatalog`, `Reports`, `CorrelationMembers`, `Incidents`, `Telemetry`, `Outbox`. **Hecho cuando:** las consultas principales usan PK/SK o GSI, no `Scan`, y los TTL previstos están configurados.
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
