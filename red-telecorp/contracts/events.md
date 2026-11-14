# Contrato de eventos

Todo evento de dominio se escribe primero en `Outbox` (misma transacción que el cambio de datos) y `EnrutadoraDeOutbox` lo publica en el bus `red-telecorp-dev-operaciones`.
Nadie llama a `PutEvents` directamente salvo `EnrutadoraDeOutbox`.

## Sobre
EventBridge: `Source = red-telecorp`, `DetailType = <type>`, `Detail = sobre JSON`:
```json
{"event_id":"01J...","type":"report.created","version":1,"occurred_at":"2026-11-14T20:01:02.123Z","data":{}}
```
Helper: `common.events.outbox_put_op(type, data)`.
Cuando un evento llega por SQS, el cuerpo es el evento de EventBridge completo; el sobre está en `body["detail"]`.
Los consumidores tienen que ser idempotentes (SQS entrega al menos una vez).

## Catálogo
| type | Productor | `data` | Consumidores |
|---|---|---|---|
| report.created | CrearReporte | report_id, customer_id, zone_id, service, problem_type, created_at | ColaReportes, ColaGCP |
| report.status_changed | CambiarEstadoReporte | report_id, customer_id, zone_id, from_status, to_status, actor, at | ColaGCP |
| report.linked | CorrelacionadoraDeReportes | incident_id, report_id, customer_id, zone_id, incident_status, linked_at | ColaNotificaciones, ColaGCP |
| telemetry.anomaly | ClasificadoraDeMetricas | antenna_id, zone_id, episode_id, state, gb_per_min, reason (OPENED \| ESCALATED), opened_at, episodes_7d | ColaAnomalias, ColaGCP |
| telemetry.recovered | ClasificadoraDeMetricas | antenna_id, zone_id, episode_id, closed_at, duration_seconds | ColaAnomalias, ColaGCP |
| telemetry.recurrent | ClasificadoraDeMetricas | antenna_id, zone_id, episodes_7d, window_start | ColaAnomalias, ColaGCP |
| incident.updated | Correlacionadoras, CalculadoraDePrioridad, CambiarEstadoIncidente | incident_id, zone_id, service, status, priority, milestone (o null), change, affected_users, updated_at | Ver reglas |

`incident.updated.change`: CREATED | EVIDENCE | THRESHOLD | RECOVERY | PRIORITY | STATUS.
`milestone`: el nuevo estado si cambió a EVALUACION, CONFIRMADO o RESTABLECIDO; en cualquier otro caso `null`.

## Reglas de enrutamiento (EventBridge)
| Regla | Patrón | Destino |
|---|---|---|
| reportes-creados | `detail-type = report.created` | ColaReportes |
| anomalias | `detail-type` en `telemetry.anomaly`, `telemetry.recovered`, `telemetry.recurrent` | ColaAnomalias |
| verificar-incidente | `incident.updated` con `detail.data.change` en CREATED, EVIDENCE, THRESHOLD, RECOVERY | Step Functions `VerificarIncidente` |
| notificar | `incident.updated` con `detail.data.milestone` en EVALUACION, CONFIRMADO o RESTABLECIDO, o `report.linked` | ColaNotificaciones |
| hacia-gcp | `report.created`, `report.status_changed`, `report.linked`, `telemetry.*`, `incident.updated` | ColaGCP |
| hacia-azure | `incident.updated` | ColaAzure |

La regla `verificar-incidente` no incluye PRIORITY ni STATUS a propósito: `CalculadoraDePrioridad` emite esos cambios y, si los incluyera, se dispararía en bucle.
EventBridge asigna el nombre de la ejecución, así que `VerificarIncidente` y sus Lambdas tienen que ser idempotentes.

## Datos personales
Los eventos llevan `customer_id` y circulan solo dentro de AWS. `PublicadoraHaciaGCP` y `PublicadoraHaciaAzure` lo sustituyen por `customer_hash` (ver `external.md`).
