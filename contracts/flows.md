# Contrato de flujos

Algoritmos exactos de cada pieza. Las reglas de negocio puras (umbrales, transiciones, prioridad) están en `aws/src/common/domain.py`: se usan, no se reescriben.
Convenciones de handlers SQS: devolver `{"batchItemFailures":[{"itemIdentifier": messageId}]}` para los registros que fallen; los datos inválidos se registran en log (sin datos personales) y se descartan, no se reintentan.

## CrearReporte (POST /reportes, rol CUSTOMER)
1. `customer_id` sale del token (`sub`), nunca del cuerpo.
2. Validar: service_number (texto, 1 a 20), zone_id existe en NetworkCatalog, service y problem_type válidos, description (1 a 1000), occurred_at (opcional; por defecto ahora; no mayor a ahora + 5 min ni anterior a 30 días), location_text (opcional, hasta 200).
3. Una transacción: Put REPORT_META (`attribute_not_exists(pk)`, status `REGISTRADA`), Put REPORT_HIST (from null → REGISTRADA, actor `CUSTOMER#<id>`), Put Outbox `report.created`, y si viene `Idempotency-Key`, Put IDEMPOTENCY (`attribute_not_exists(pk)`).
4. Si la transacción falla por el ítem IDEMPOTENCY, leerlo y devolver 200 con el reporte original. Si no, 201.

## CorrelacionadoraDeReportes (ColaReportes)
Por cada `report.created` (zona Z, servicio S, cliente C, fecha T):
1. **Miembro.** Leer `MEMBER#C` del grupo `GROUP#Z#S`. Si no existe o `last_reported_at < T − 24 h`, `window_started_at = T`. Guardar `last_reported_at = T`, agregar report_id a `report_ids` (máximo 20) y `ttl = T + 48 h`.
2. **Incidente activo.** Buscar el puntero `ACTIVE_INCIDENT` en `GROUP#Z#S`; si no hay, en `GROUP#Z#ANY`.
3. **Si hay incidente:** vincular el reporte (procedimiento abajo).
   - Si es el primer usuario vinculado y `evidence_users` era false: evento `incident.updated` con `change=EVIDENCE`.
   - Si `affected_users` pasa a 100 o a 1000: evento con `change=THRESHOLD`.
   - En otro caso, sin evento (evita saturar Step Functions).
4. **Si no hay incidente:** contar los MEMBER con `last_reported_at >= T − 24 h`. Si son 10 o más:
   - Una transacción: Put `ACTIVE_INCIDENT` (`attribute_not_exists(pk)`), Put INCIDENT_META (`origin=REPORTES`, `service=S`, `status=EVALUACION`, `evidence_users=true`, `first_report_at` = mínimo de `window_started_at` de esos miembros, `opened_at=ahora`, `detected_by` según la evidencia más antigua), Put INCIDENT_HIST (`change=CREATED`) y Put Outbox `incident.updated` (`change=CREATED`, `milestone=EVALUACION`).
   - Si la transacción falla porque el puntero ya existe, leer el puntero y vincular a ese incidente.
   - Después vincular los `report_ids` de todos los miembros dentro de la ventana.
5. Menos de 10 y sin incidente: no hacer nada más.

**Vincular reporte R de cliente C al incidente I** (idempotente), una transacción:
Put `LINK#REPORT#R` (`attribute_not_exists`), Update Reports META (`incident_id = I`), Update Incidents META (`ADD report_count 1`), Put Outbox `report.linked`, y además Put `LINK#USER#C` (`attribute_not_exists`) con Update `ADD affected_users 1`.
Si falla porque ya existe `LINK#REPORT#R`: ya estaba procesado, ignorar. Si falla solo porque ya existe `LINK#USER#C`: repetir la transacción sin el Put de usuario y sin sumar `affected_users`.

## ClasificadoraDeMetricas (ColaMetricas)
Mensaje: `{"bucket": "...", "key": "metrics/2026-11-14/20-01.jsonl"}`. Cada línea del archivo: `{"antenna_id":"A001","ts":"...Z","gb_per_min":95}`.
Por antena, en orden de `ts`, ignorando lecturas con `ts <= last_ts`:
1. `state = classify_gb(gb)` (0 → INHABILITADA; < 60 → CAIDA; > 129 → SATURADA).
2. **Anomalía y sin episodio abierto:** crear EPISODE (OPEN) con gsi1 y gsi2, fijar `open_episode_*` en LAST, `consecutive_normals = 0`. Contar episodios de los últimos 7 días (incluyendo este). Emitir `telemetry.anomaly` (`reason=OPENED`, `episodes_7d`). Si `episodes_7d >= 3`, emitir también `telemetry.recurrent`.
3. **Anomalía con episodio abierto:** `consecutive_normals = 0`, actualizar `readings`, `min_gb`, `max_gb`. Si el estado es peor que el del episodio (INHABILITADA > CAIDA > SATURADA), subir `state` y emitir `telemetry.anomaly` con `reason=ESCALATED`.
4. **Normal con episodio abierto:** `consecutive_normals += 1`. Al llegar a 5, cerrar el episodio (CLOSED, `closed_at` = `ts` de esa lectura, `duration_seconds`), quitar los atributos gsi2, limpiar `open_episode_*` y emitir `telemetry.recovered`.
5. Actualizar LAST. Cada antena se procesa en una transacción (LAST + EPISODE + Outbox).

## GeneradoraDeMetricasYLotes (cada minuto)
Lee las antenas (GSI1-type), genera `gb_per_min` entre 85% y 115% de `nominal_gb`, aplica `SCENARIO#ACTIVE` si no ha expirado, escribe un archivo JSONL en S3 (`metrics/<fecha>/<HH-MM>.jsonl`, `ts` alineado al minuto) y envía el mensaje a ColaMetricas.

## CorrelacionadoraDeAnomalias (ColaAnomalias)
**telemetry.anomaly** (zona Z):
- Buscar punteros `ACTIVE_INCIDENT` en `GROUP#Z#ANY`, `GROUP#Z#MOVIL` y `GROUP#Z#INTERNET`.
- Si existe el de ANY: vincular a ese. Si no, y hay exactamente un incidente de reportes activo: vincular a ese. Si no hay ninguno: crear incidente `origin=TELEMETRIA`, `service=ANY`, `status=EVALUACION` (misma transacción con puntero que en reportes, `change=CREATED`, `milestone=EVALUACION`). Si hay dos o más de reportes y no existe ANY: crear el ANY con `review_required=true`.
- Vincular la antena: Put `LINK#ANTENNA#<antenna>#<episode>`, `evidence_tech=true`, `antenna_ids` + antena, `first_anomaly_at = min(actual, opened_at)`, `worst_antenna_state` actualizado. Emitir `incident.updated` con `change=EVIDENCE` (o solo CREATED si lo acaba de crear).
**telemetry.recovered:** en los punteros de la zona, buscar el ítem `LINK#ANTENNA#<antenna>#<episode>`; si existe, ponerle `recovered_at`. Si todas las antenas vinculadas tienen `recovered_at`, `tech_recovered=true`. Emitir `incident.updated` con `change=RECOVERY`.
**telemetry.recurrent:** marcar `structural_suspect=true` en el incidente de la antena y emitir `change=EVIDENCE`.

## VerificarIncidente (Step Functions Standard)
Entrada: `{"incident_id": "...", "trigger_event_id": "...", "change": "..."}`.
1. `VerificarEvidencias` (Parallel):
   - Entrada de la Lambda: `{"incident_id", "mode"}` (directa, sin sobre).
   - Rama A: `VerificadoraDeEvidencias` con `mode=users` → `{evidence_users, affected_users, report_count, first_report_at}` (solo lectura).
   - Rama B: `VerificadoraDeEvidencias` con `mode=antennas` → `{evidence_tech, antenna_ids, worst_antenna_state, first_anomaly_at, tech_recovered}` (solo lectura).
2. `CalcularPrioridad` (`CalculadoraDePrioridad`), entrada `{"incident_id", "evidence": [resultado_users, resultado_antennas]}`: lee la criticidad de la zona, calcula `priority_score` y `priority` con `domain.priority()`, y escribe todo en una transacción con `version` (reintento ante conflicto): evidencias, `detection_lag_seconds`, `detected_by`, `recommended_action`, y si hay evidencia técnica con estado EVALUACION, pasa a CONFIRMADO (HIST + evento `change=STATUS`, `milestone=CONFIRMADO`). Si solo cambia la prioridad, emite `change=PRIORITY`. Devuelve `{priority, priority_changed, status_changed, alert}`.
   - `recommended_action`: `tech_recovered` y CONFIRMADO → "Evaluar restablecimiento"; `structural_suspect` → "Revisión estructural de la antena"; solo usuarios y EVALUACION → "Verificar infraestructura de la zona"; si no, nulo. Nunca cierra ni restablece solo.
   - `alert = true` si la prioridad nueva es P1, si pasó a CONFIRMADO o si `review_required`.
3. `RequiereAlerta` (Choice): `alert` true → `AlertarOperaciones`; si no → `Succeed`.
4. `AlertarOperaciones` (`AlertadoraDeOperaciones`, entrada `{"mode":"incident","incident_id","calc"}`): publica en `alertas-operaciones` (SNS) un correo de texto del incidente: asunto `[<prioridad>] Incidente <estado> en <zona>` y cuerpo con zona, servicio, prioridad, estado, antenas y acción recomendada (sin datos personales).
5. Retry en cada tarea: `Lambda.ServiceException`, `Lambda.TooManyRequestsException`, 3 intentos, backoff 2. Catch general → `AlertarFalla` (la misma Lambda con `{"mode":"failure","incident_id","error"}`) → `Fail`.

## CambiarEstadoReporte / CambiarEstadoIncidente (rol OPERATOR)
Validar la transición con `domain`. Una transacción con `version`: actualizar META (y gsi2 en incidentes), HIST, Outbox (`report.status_changed` o `incident.updated` con `change=STATUS` y `milestone`). Al pasar a RESTABLECIDO fijar `restored_at`; al pasar a CERRADO fijar `closed_at` y `duration_seconds`, y borrar el puntero `ACTIVE_INCIDENT` en la misma transacción. Transición inválida: 409 `CONFLICT`. Versión desfasada: 409 con reintento interno una vez.

## NotificadoraDeClientes (ColaNotificaciones)
- `incident.updated` con hito M: destinatarios = todos los `LINK#USER#*` del incidente.
- `report.linked`: destinatario = `customer_id` del evento; el hito es `incident_status` si es EVALUACION, CONFIRMADO o RESTABLECIDO; si no, ignorar.
Por destinatario:
1. Put `NOTIFY#M#C` con `attribute_not_exists(pk)` (PENDING). Si ya existe y está SENT o SKIPPED, seguir con el siguiente. Si está FAILED o PENDING y `attempts < 3`, reintentar.
2. Cargar el perfil. Canal: `channel_pref` si hay consentimiento; si no, el otro canal con consentimiento; si ninguno, `SKIPPED` con canal NONE.
3. Enviar: EMAIL por SES si `EMAIL_MODE=SES`; SMS por SNS (`Publish` con `PhoneNumber`) si `SMS_MODE=SNS`; con `SIMULATED` solo se registra. Actualizar NOTIFY con canal, intento, resultado.
4. Si falla el envío: marcar FAILED, sumar el intento y reportar el registro en `batchItemFailures` mientras `attempts < 3`.
Plantillas:
- EVALUACION: "Estamos evaluando el inconveniente que reportaste en tu zona. Te avisaremos cuando haya novedades."
- CONFIRMADO: "Identificamos una incidencia en tu zona. Nuestro equipo está trabajando para resolverla."
- RESTABLECIDO: "El servicio fue restablecido en tu zona. Si el problema continúa, vuelve a reportarlo."
Sin datos personales en los logs.

## AutenticarUsuario / AutorizarJWT
- Login: scrypt (`hashlib.scrypt`, stdlib) y comparación con `hmac.compare_digest`. Mensaje único para "usuario inexistente" y "clave incorrecta".
- JWT HS256 con `hmac` (stdlib). Claims: `sub`, `role`, `iss=red-telecorp`, `iat`, `exp` (15 min). Clave en SSM `jwt/signing_key`.
- Autorizador HTTP API (formato de carga 2.0, respuesta simple): devuelve `{"isAuthorized": bool, "context": {"sub": "...", "role": "..."}}`. Rechazar `alg` distinto de HS256 y tokens vencidos.
