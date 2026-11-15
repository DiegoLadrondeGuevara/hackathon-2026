"""AlertadoraDeOperaciones: pasos `AlertarOperaciones` y `AlertarFalla` de `VerificarIncidente`.

Entrada `{"mode":"incident","incident_id","calc"}` o `{"mode":"failure","incident_id","error"}`.
Publica en el tema SNS `alertas-operaciones` (`OPS_TOPIC_ARN`) un resumen JSON sin datos personales.
"""
import logging
import os

import boto3

from common import ddb, ids, jsonutil

log = logging.getLogger()
log.setLevel(logging.INFO)

_SUMMARY_FIELDS = (
    "incident_id", "origin", "zone_id", "service", "status", "priority", "priority_score", "affected_users",
    "report_count", "evidence_users", "evidence_tech", "antenna_ids", "worst_antenna_state", "tech_recovered",
    "structural_suspect", "review_required", "recommended_action", "detected_by", "detection_lag_seconds",
    "opened_at", "confirmed_at", "updated_at",
)
_MAX_CAUSE = 500
_client = None


def _sns():
    global _client
    if _client is None:
        _client = boto3.client("sns")
    return _client


def _incident_message(event: dict) -> tuple[str, dict]:
    incident_id = event.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("falta incident_id")
    key = {"pk": f"INCIDENT#{incident_id}", "sk": "META"}
    meta = ddb.table("Incidents").get_item(Key=key, ConsistentRead=True).get("Item")
    if not meta:
        raise ValueError(f"el incidente {incident_id} no existe")
    calc = event.get("calc") or {}
    body = {
        "kind": "INCIDENT_ALERT",
        "incident": {name: meta[name] for name in _SUMMARY_FIELDS if name in meta},
        "calc": {name: calc.get(name) for name in ("priority", "priority_changed", "status_changed", "alert")},
        "sent_at": ids.now_iso(),
    }
    subject = f"[{meta.get('priority', 'P?')}] Incidente {meta['zone_id']} {meta['service']}: {meta['status']}"
    return subject, body


def _failure_message(event: dict) -> tuple[str, dict]:
    error = event.get("error") if isinstance(event.get("error"), dict) else {}
    body = {
        "kind": "VERIFICATION_FAILURE",
        "incident_id": event.get("incident_id"),
        "error": str(error.get("Error", "Desconocido"))[:100],
        "cause": str(error.get("Cause", ""))[:_MAX_CAUSE],
        "sent_at": ids.now_iso(),
    }
    return "Fallo al verificar un incidente", body


def handler(event, context):
    mode = event.get("mode")
    if mode == "incident":
        subject, body = _incident_message(event)
    elif mode == "failure":
        subject, body = _failure_message(event)
    else:
        raise ValueError(f"mode no válido: {mode}")
    resp = _sns().publish(TopicArn=os.environ["OPS_TOPIC_ARN"], Subject=subject[:100], Message=jsonutil.dumps(body))
    log.info("alerta de operaciones publicada: modo=%s incidente=%s", mode, event.get("incident_id"))
    return {"published": True, "message_id": resp["MessageId"]}
