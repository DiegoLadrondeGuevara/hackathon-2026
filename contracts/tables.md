# Contrato de tablas (DynamoDB)

Fuente de verdad del modelo de datos. Infra crea las tablas; el código las usa.
Si algo cambia, se cambia aquí y en `aws/tests/schema.py` en el mismo commit.

## Reglas generales
- Nombre físico: `red-telecorp-dev-<Tabla>` (ej. `red-telecorp-dev-Reports`).
- Facturación PAY_PER_REQUEST. PITR activado si AWS Academy lo permite.
- Claves genéricas en minúscula, todas String: `pk`, `sk`; índices `gsi1pk/gsi1sk`, `gsi2pk/gsi2sk`. Proyección ALL.
- Varias entidades por tabla, distinguidas por el atributo `type`.
- IDs: ULID (26 caracteres, ordenable por tiempo). Fechas: ISO-8601 UTC con milisegundos y `Z`: `2026-11-14T20:01:02.123Z`.
- Números: `int` o `Decimal`. Nunca `float`. GB/min se guarda como `Decimal`.
- Atributos en snake_case. Los ítems META llevan `version` (int). Todo cambio de estado usa `ConditionExpression version = :v` y suma 1.
- TTL: atributo `ttl` (epoch en segundos) solo donde se indica. El borrado por TTL puede tardar horas: el código filtra por fecha y no confía en el TTL.
- Streams: solo `Outbox` (NEW_IMAGE).
- Cambio de estado = una transacción (`TransactWriteItems`) que actualiza META, agrega HIST y agrega el evento a Outbox.
- MVP: una antena cubre una sola zona.

Enumeraciones:
- `service`: MOVIL | INTERNET (los incidentes de origen telemétrico usan además ANY)
- `problem_type`: SIN_SENAL | SIN_INTERNET | LLAMADAS | SMS | LENTITUD | OTRO
- `zone_type`: RESIDENCIAL | INDUSTRIAL | EDUCATIVA | MEDICA | CRITICA
- Estado de antena: NORMAL | CAIDA | SATURADA | INHABILITADA

---

## Reports
| type | pk | sk |
|---|---|---|
| REPORT_META | `REPORT#<report_id>` | `META` |
| REPORT_HIST | `REPORT#<report_id>` | `HIST#<at>` |
| IDEMPOTENCY | `IDEM#<customer_id>#<key>` | `META` (ttl = creación + 24 h) |

**REPORT_META**: report_id, customer_id, service_number, zone_id, service, problem_type, description (1 a 1000), location_text (opcional, hasta 200), occurred_at, created_at, updated_at, status, incident_id (opcional, se fija al vincular), version.
Índices: `gsi1pk=CUSTOMER#<customer_id>`, `gsi1sk=<created_at>#<report_id>`; `gsi2pk=ZONE#<zone_id>`, `gsi2sk=<created_at>#<report_id>`.
**REPORT_HIST**: from_status (null en el primero), to_status, actor (`CUSTOMER#<id>` | `OPERATOR#<id>` | `SYSTEM#<nombre>`), reason (opcional), at.
**IDEMPOTENCY**: report_id, ttl.

Estados del reporte y transiciones (solo OPERATOR, salvo el primero que es del sistema):
`REGISTRADA → EN_REVISION → EN_ATENCION → SOLUCIONADA → CERRADA`, más `SOLUCIONADA → EN_ATENCION` (reabrir).

| GSI | Uso |
|---|---|
| `GSI1-customer` | ListarMisReportes (orden descendente) |
| `GSI2-zone` | Reportes por zona (operador, tendencias) |

---

## Incidents
| type | pk | sk |
|---|---|---|
| INCIDENT_META | `INCIDENT#<incident_id>` | `META` |
| INCIDENT_HIST | `INCIDENT#<incident_id>` | `HIST#<at>` |
| LINK_REPORT | `INCIDENT#<incident_id>` | `LINK#REPORT#<report_id>` |
| LINK_USER | `INCIDENT#<incident_id>` | `LINK#USER#<customer_id>` |
| LINK_ANTENNA | `INCIDENT#<incident_id>` | `LINK#ANTENNA#<antenna_id>#<episode_id>` |
| NOTIFY | `INCIDENT#<incident_id>` | `NOTIFY#<milestone>#<customer_id>` |

**INCIDENT_META**: incident_id, origin (REPORTES | TELEMETRIA), zone_id, service, status, priority (P1|P2|P3), priority_score (int), affected_users (int, = cantidad de LINK_USER), report_count (int), evidence_users (bool), evidence_tech (bool), antenna_ids (string set), worst_antenna_state (opcional), tech_recovered (bool), structural_suspect (bool), review_required (bool), recommended_action (opcional), detected_by (USUARIOS | ANTENA), first_report_at (opcional), first_anomaly_at (opcional), detection_lag_seconds (opcional, = first_report_at − first_anomaly_at; positivo = la antena avisó antes que los usuarios), opened_at, confirmed_at, restored_at, closed_at (opcionales), duration_seconds (al cerrar = closed_at − opened_at), updated_at, version.
Índices: `gsi1pk=ZONE#<zone_id>`, `gsi1sk=<opened_at>#<incident_id>`; `gsi2pk=STATUS#<status>`, `gsi2sk=<priority>#<opened_at>#<incident_id>` (hay que reescribirlos cuando cambia el estado o la prioridad).
**INCIDENT_HIST**: from_status, to_status, actor, reason, change (CREATED | EVIDENCE | THRESHOLD | RECOVERY | PRIORITY | STATUS), at.
**LINK_REPORT**: report_id, customer_id, linked_at. **LINK_USER**: customer_id, first_report_id, linked_at. **LINK_ANTENNA**: antenna_id, episode_id, state, linked_at, recovered_at (opcional).
**NOTIFY**: milestone, customer_id, status (PENDING | SENT | FAILED | SKIPPED), channel (EMAIL | SMS | SIMULATED | NONE), attempts (int), created_at, last_attempt_at, sent_at, error, message_id. Se crea con `attribute_not_exists(pk)`: es la intención única por cliente e hito.

Estados del incidente y transiciones:
`EVALUACION → CONFIRMADO → RESTABLECIDO → CERRADO`, más `EVALUACION → CERRADO` (falso positivo) y `RESTABLECIDO → CONFIRMADO` (reabrir).
Hitos de notificación: EVALUACION, CONFIRMADO, RESTABLECIDO (CERRADO no notifica).
Quién cambia el estado: CONFIRMADO lo pone el sistema si hay evidencia técnica, o el operador; RESTABLECIDO y CERRADO solo el operador.

---

## Telemetry
| type | pk | sk |
|---|---|---|
| ANTENNA_LAST | `ANTENNA#<antenna_id>` | `LAST` |
| EPISODE | `ANTENNA#<antenna_id>` | `EPISODE#<opened_at>#<episode_id>` |

**ANTENNA_LAST**: antenna_id, zone_id, last_ts, gb_per_min, state, consecutive_normals (int), open_episode_id (opcional), open_episode_sk (opcional), updated_at.
**EPISODE**: episode_id, antenna_id, zone_id, state (el peor alcanzado: INHABILITADA > CAIDA > SATURADA), status (OPEN | CLOSED), opened_at, closed_at (opcional), readings (int), min_gb, max_gb, duration_seconds (al cerrar).
Índices: `gsi1pk=ZONE#<zone_id>`, `gsi1sk=<opened_at>#<antenna_id>` (todos los episodios); `gsi2pk=OPEN#<zone_id>`, `gsi2sk=<opened_at>#<antenna_id>` (solo mientras el episodio está OPEN: se elimina al cerrar).
Recurrencia: `Query pk=ANTENNA#<id>` con `sk BETWEEN EPISODE#<ahora−7d> AND EPISODE#~`.

---

## CorrelationMembers
| type | pk | sk |
|---|---|---|
| MEMBER | `GROUP#<zone_id>#<service>` | `MEMBER#<customer_id>` |
| ACTIVE_INCIDENT | `GROUP#<zone_id>#<service>` | `ACTIVE_INCIDENT` |

**MEMBER**: customer_id, window_started_at, last_reported_at, report_ids (string set, máximo 20), ttl (last_reported_at + 48 h).
Conteo del umbral: `Query pk, sk begins_with MEMBER#` y contar los que tienen `last_reported_at >= ahora − 24 h`. Si `last_reported_at` es anterior a 24 h, al reportar de nuevo se reinicia `window_started_at`.
**ACTIVE_INCIDENT**: incident_id, opened_at. Puntero al incidente activo del grupo. Se crea con `attribute_not_exists(pk)` en la misma transacción que el incidente (evita duplicados) y se borra en la transacción que lo cierra. `service` puede ser MOVIL, INTERNET o ANY.

---

## NetworkCatalog
| type | pk | sk |
|---|---|---|
| ZONE | `ZONE#<zone_id>` | `META` |
| ANTENNA | `ANTENNA#<antenna_id>` | `META` |
| SCENARIO | `SCENARIO#ACTIVE` | `META` |

**ZONE**: zone_id, name, zone_type, criticality (1 a 5), est_users (int). Índice: `gsi1pk=TYPE#ZONE`, `gsi1sk=<zone_id>`.
**ANTENNA**: antenna_id, zone_id, name, nominal_gb (int). Índices: `gsi1pk=TYPE#ANTENNA`, `gsi1sk=<antenna_id>`; `gsi2pk=ZONE#<zone_id>`, `gsi2sk=ANTENNA#<antenna_id>`.
**SCENARIO**: overrides (mapa antenna_id → Decimal GB/min), expires_at. Lo escribe `scripts/scenario.py` para forzar fallas en la demo. El generador lo ignora si ya expiró.
Criticidad por tipo: RESIDENCIAL 1, INDUSTRIAL 2, EDUCATIVA 3, MEDICA 4, CRITICA 5.

---

## CustomerProfiles
| type | pk | sk |
|---|---|---|
| CUSTOMER | `CUSTOMER#<customer_id>` | `PROFILE` |
| OPERATOR | `OPERATOR#<operator_id>` | `PROFILE` |

**CUSTOMER**: customer_id (documento), role=`CUSTOMER`, full_name, email, phone (E.164, `+51...`), password_hash, channel_pref (EMAIL | SMS), consent_email (bool), consent_sms (bool), consent_at, created_at.
**OPERATOR**: operator_id, role=`OPERATOR`, full_name, email, password_hash.
`password_hash` con scrypt: `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`. El login busca `CUSTOMER#<identifier>` y luego `OPERATOR#<identifier>`.
Esta tabla tiene datos personales: nada de ella sale de AWS.

---

## Outbox
| type | pk | sk |
|---|---|---|
| OUTBOX | `EVENT#<event_id>` | `EVT` |

Atributos: event_id, detail_type, source (`red-telecorp`), detail (string JSON del sobre completo, ver `events.md`), created_at, ttl (creación + 7 días).
Streams NEW_IMAGE. `EnrutadoraDeOutbox` procesa solo los INSERT y publica en el bus.
