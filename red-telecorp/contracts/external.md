# Contrato hacia otras nubes

Nada de datos personales sale de AWS. `PublicadoraHaciaGCP` y `PublicadoraHaciaAzure` quitan `customer_id` y ponen `customer_hash = sha256(pii_salt + customer_id)` (primeros 16 caracteres hex). `description` y `location_text` nunca viajan.
Comunicación por HTTPS con clave en cabecera; las claves salen de SSM. Si la nube externa falla, el mensaje vuelve a la cola y termina en la DLQ: la operación en AWS no se ve afectada.

## GCP: Cloud Run function `red-telecorp-analisis`
- `POST /ingest`, cabecera `X-Api-Key`. Cuerpo `{"events":[{"event_id","type","occurred_at","data"}]}` (hasta 10). Inserta en BigQuery `incident_events` usando `event_id` como clave de deduplicación. → 200 `{"inserted": n}`.
- Tabla `incident_events`: event_id STRING, type STRING, occurred_at TIMESTAMP, incident_id STRING, zone_id STRING, service STRING, status STRING, priority STRING, antenna_id STRING, customer_hash STRING, payload STRING (JSON).
- `POST /suggest`, cuerpo `{"incident_id","zone_id","days":30}`. Resume el historial de la zona desde BigQuery (datos agregados) y pide hipótesis a Gemini con salida JSON fija. Responde en menos de 4 s: `{"available":true,"hypotheses":[{"title","rationale"}],"model","generated_at"}`. Las hipótesis se presentan como sugerencias revisables, nunca como hechos.
- Nota: la inserción por streaming de BigQuery requiere un proyecto con facturación; en sandbox usar carga por lotes (load job).

## Azure: Functions `red-telecorp-estado-api` + Table Storage `EstadoZonas` + Static Web App `red-telecorp-estado-publico`
- `PUT /api/estado/{zone_id}`, cabecera `x-functions-key`. Cuerpo `{"zone_id","status","priority","updated_at","public_message"}` con `status` en SIN_INCIDENTE | EVALUACION | CONFIRMADO | RESTABLECIDO. `PartitionKey = "ZONA"`, `RowKey = zone_id`.
- `GET /api/estado` → lista de zonas con su estado público. Lo consume la Static Web App.
- `PublicadoraHaciaAzure` traduce `incident.updated`: estado del incidente mientras esté activo, y SIN_INCIDENTE cuando pasa a CERRADO.
