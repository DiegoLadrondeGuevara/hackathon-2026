"""AlertadoraDeOperaciones: pasos `AlertarOperaciones` y `AlertarFalla` de `VerificarIncidente`.

Entrada `{"mode":"incident","incident_id","calc"}` o `{"mode":"failure","incident_id","error"}`.
Publica en el tema SNS `alertas-operaciones` (`OPS_TOPIC_ARN`) un correo de texto sin datos personales
(el fallo de verificación se envía como JSON).
"""
import logging
import os

import boto3

from common import ddb, ids, jsonutil

log = logging.getLogger()
log.setLevel(logging.INFO)

_MAX_CAUSE = 500
_client = None


def _sns():
    global _client
    if _client is None:
        _client = boto3.client("sns")
    return _client


def _incident_message(event: dict) -> tuple[str, str]:
    incident_id = event.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("falta incident_id")
    key = {"pk": f"INCIDENT#{incident_id}", "sk": "META"}
    meta = ddb.table("Incidents").get_item(Key=key, ConsistentRead=True).get("Item")
    if not meta:
        raise ValueError(f"el incidente {incident_id} no existe")
    antennas = ", ".join(sorted(meta.get("antenna_ids") or ())) or "ninguna"
    subject = f"[{meta.get('priority', 'P?')}] Incidente {meta['status']} en {meta['zone_id']}"
    lines = [
        f"Incidente: {incident_id}",
        f"Zona: {meta['zone_id']}",
        f"Servicio: {meta['service']}",
        f"Prioridad: {meta.get('priority', 'P?')}",
        f"Estado: {meta['status']}",
        f"Antenas: {antennas}",
        f"Acción recomendada: {meta.get('recommended_action') or 'ninguna'}",
        f"Clientes afectados: {int(meta.get('affected_users', 0))}",
        f"Actualizado: {meta.get('updated_at', ids.now_iso())}",
    ]
    return subject, "\n".join(lines)


def _failure_message(event: dict) -> tuple[str, str]:
    error = event.get("error") if isinstance(event.get("error"), dict) else {}
    body = {
        "kind": "VERIFICATION_FAILURE",
        "incident_id": event.get("incident_id"),
        "error": str(error.get("Error", "Desconocido"))[:100],
        "cause": str(error.get("Cause", ""))[:_MAX_CAUSE],
        "sent_at": ids.now_iso(),
    }
    return "Fallo al verificar un incidente", jsonutil.dumps(body)


def handler(event, context):
    mode = event.get("mode")
    if mode == "incident":
        subject, message = _incident_message(event)
    elif mode == "failure":
        subject, message = _failure_message(event)
    else:
        raise ValueError(f"mode no válido: {mode}")
    resp = _sns().publish(TopicArn=os.environ["OPS_TOPIC_ARN"], Subject=subject[:100], Message=message)
    log.info("alerta de operaciones publicada: modo=%s incidente=%s", mode, event.get("incident_id"))
    return {"published": True, "message_id": resp["MessageId"]}
