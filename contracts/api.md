# Contrato de la API (API Gateway HTTP API)

Autenticación: `Authorization: Bearer <jwt>` en todas las rutas salvo `/auth/login`. CORS lo configura API Gateway, no las Lambdas.
Roles: CUSTOMER y OPERATOR (claim `role`). Las Lambdas leen el contexto en `event["requestContext"]["authorizer"]["lambda"]` (`sub`, `role`).
Respuestas JSON. Fechas ISO-8601 UTC. Listas paginadas: `?limit=` (por defecto 20, máximo 100) y `?cursor=` (opaco, base64 de `LastEvaluatedKey`); la respuesta incluye `next_cursor` (o `null`).

## Rutas
| Ruta | Lambda | Acceso |
|---|---|---|
| POST /auth/login | AutenticarUsuario | público |
| GET /zonas | ListarZonas | cualquiera |
| POST /reportes | CrearReporte | CUSTOMER |
| GET /reportes | ListarMisReportes | CUSTOMER: los propios. OPERATOR: `?zone_id=` obligatorio |
| GET /reportes/{report_id} | ObtenerReporte | dueño u OPERATOR |
| PATCH /reportes/{report_id}/estado | CambiarEstadoReporte | OPERATOR |
| GET /incidentes | ListarIncidentesZona | `?zone_id=` cualquiera (vista pública para CUSTOMER, sin incidentes CERRADO); `?status=` solo OPERATOR (cola, por prioridad) |
| GET /incidentes/{incident_id} | ListarIncidentesZona | OPERATOR |
| PATCH /incidentes/{incident_id}/estado | CambiarEstadoIncidente | OPERATOR |
| GET /incidentes/{incident_id}/sugerencia | ObtenerSugerenciaIA | OPERATOR |
| GET /tendencias | ObtenerTendencias | OPERATOR |

## Cuerpos principales
**POST /auth/login** `{"identifier":"12345678","password":"..."}` → 200 `{"token":"...","expires_in":900,"role":"CUSTOMER","name":"..."}`.
**GET /zonas** → `{"items":[{"zone_id":"Z01","name":"Miraflores","zone_type":"RESIDENCIAL"}]}`.
**POST /reportes** (header opcional `Idempotency-Key`)
```json
{"service_number":"987654321","zone_id":"Z01","service":"INTERNET","problem_type":"SIN_INTERNET",
 "description":"No tengo conexión desde las 8","location_text":"Cerca del parque Kennedy","occurred_at":"2026-11-14T13:05:00.000Z"}
```
→ 201 `{"report_id":"...","status":"REGISTRADA","created_at":"..."}` (200 con el reporte original si la clave de idempotencia ya existía).
**GET /reportes/{id}** → META sin atributos gsi + `history:[{from_status,to_status,actor,reason,at}]`.
**PATCH …/estado** `{"to_status":"EN_REVISION","reason":"opcional"}` → 200 con el nuevo META.
**GET /incidentes?zone_id=** → CUSTOMER: `{"items":[{"incident_id","zone_id","service","status","opened_at","updated_at"}]}`. OPERATOR: META completo sin atributos gsi.
La vista pública (CUSTOMER) excluye los incidentes CERRADO; OPERATOR los sigue viendo. El filtro se aplica después de `limit`: una página pública puede traer menos elementos que `limit`, o ninguno, y aun así devolver `next_cursor`. El cliente debe seguir el cursor hasta que sea `null`.
**GET /incidentes/{id}** → META + `history` + `links:{reports, users, antennas}` (conteos y listas de antenas).
**GET /tendencias?days=30** →
```json
{"days":30,"top_zonas":[{"zone_id":"Z02","name":"San Isidro","reports":0,"incidents":0}],
 "top_antenas":[{"antenna_id":"A004","zone_id":"Z02","episodes":0}],
 "top_tipos":[{"problem_type":"SIN_INTERNET","count":0}],
 "recurrentes":[{"antenna_id":"A004","zone_id":"Z02","episodes_7d":3}],
 "deteccion":{"avg_lag_seconds":0,"detected_by_users":0,"detected_by_antenna":0}}
```
**GET /incidentes/{id}/sugerencia** → 200 `{"available":true,"hypotheses":[{"title":"...","rationale":"..."}],"model":"...","generated_at":"..."}`; si GCP falla o tarda más de 4 s: 200 `{"available":false}`. Nunca devuelve 5xx por la IA.

## Errores
Formato único: `{"error":{"code":"VALIDATION","message":"..."}}`.
| code | HTTP |
|---|---|
| VALIDATION | 400 |
| UNAUTHORIZED | 401 |
| FORBIDDEN | 403 |
| NOT_FOUND | 404 |
| CONFLICT | 409 |
| INTERNAL | 500 (sin detalles internos) |
