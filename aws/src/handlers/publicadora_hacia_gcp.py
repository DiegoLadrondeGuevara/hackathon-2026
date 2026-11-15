"""ColaGCP → HTTPS: eventos depurados y fallos parciales SQS."""
import json
import logging
from decimal import Decimal

from common import config, outbound, pii

log = logging.getLogger(__name__)
FIELDS = {
    "report.created": "report_id zone_id service problem_type created_at",
    "report.status_changed": "report_id zone_id from_status to_status at",
    "report.linked": "incident_id report_id zone_id incident_status linked_at",
    "telemetry.anomaly": "antenna_id zone_id episode_id state gb_per_min reason opened_at episodes_7d",
    "telemetry.recovered": "antenna_id zone_id episode_id closed_at duration_seconds",
    "telemetry.recurrent": "antenna_id zone_id episodes_7d window_start",
    "incident.updated": "incident_id zone_id service status priority milestone change affected_users updated_at",
}


def _envelope(record, salt):
    detail = json.loads(record["body"], parse_float=Decimal)["detail"]
    if isinstance(detail, str):
        detail = json.loads(detail, parse_float=Decimal)
    kind = detail["type"]
    allowed = FIELDS[kind].split()
    if detail.get("version", 1) != 1 or isinstance(detail.get("version"), bool):
        raise ValueError("Versión inválida")
    if not all(isinstance(detail.get(k), str) and detail[k] for k in ("event_id", "occurred_at")):
        raise ValueError("Sobre inválido")
    original = detail["data"]
    if not isinstance(original, dict):
        raise ValueError("Datos inválidos")
    safe = pii.strip_pii(original)
    data = {k: safe[k] for k in allowed if k in safe}
    if any(isinstance(v, (list, dict)) for v in data.values()):
        raise ValueError("Campo no escalar")
    if "customer_id" in original:
        data["customer_hash"] = pii.customer_hash(salt, original["customer_id"])
    return {"event_id": detail["event_id"], "type": kind, "occurred_at": detail["occurred_at"], "data": data}


def handler(event, context):
    records = event.get("Records", [])
    if not records:
        return {"batchItemFailures": []}
    failed = []
    try:
        base, key, salt = (config.get_secret(k) for k in ("gcp/base_url", "gcp/api_key", "pii_salt"))
        if any(not v or v == "PENDIENTE" for v in (base, key, salt)):
            raise ValueError("Integración no configurada")
    except Exception:
        return {"batchItemFailures": [{"itemIdentifier": r["messageId"]} for r in records]}
    valid = []
    for record in records:
        try:
            valid.append((record["messageId"], _envelope(record, salt)))
        except (ValueError, KeyError, TypeError):
            # flows.md: inválidos se descartan; nunca registrar el contenido.
            log.warning("Evento GCP inválido descartado")
    for offset in range(0, len(valid), 10):
        batch = valid[offset:offset + 10]
        try:
            response = outbound.post_json(
                base.rstrip("/") + "/ingest", {"events": [e for _, e in batch]}, {"X-Api-Key": key},
            )
            if (not isinstance(response, dict) or type(response.get("inserted")) is not int
                    or not 0 <= response["inserted"] <= len(batch)):
                raise ValueError("Confirmación inválida")
        except Exception:
            log.warning("Envío GCP pendiente de reintento")
            failed.extend({"itemIdentifier": mid} for mid, _ in batch)
    return {"batchItemFailures": failed}
