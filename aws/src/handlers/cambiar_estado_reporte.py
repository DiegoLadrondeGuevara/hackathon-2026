"""CambiarEstadoReporte: PATCH /reportes/{report_id}/estado (rol OPERATOR). Ver contracts/flows.md.

Valida la transición con `domain` y, en una transacción con `version`, actualiza META, agrega
REPORT_HIST y el evento `report.status_changed` en Outbox. Transición inválida: 409.
Versión desfasada: se reintenta una vez; si vuelve a fallar, 409.
"""
import logging

from botocore.exceptions import ClientError

from common import ddb, domain, events, http, ids

log = logging.getLogger()

_MAX_REASON = 500
_ATTEMPTS = 2


def _to_status(body: dict) -> str:
    value = body.get("to_status")
    if not isinstance(value, str) or value not in domain.REPORT_TRANSITIONS:
        raise http.ApiError("VALIDATION", "El campo to_status no es un estado de reporte válido")
    return value


def _reason(body: dict) -> str | None:
    value = body.get("reason")
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > _MAX_REASON:
        raise http.ApiError("VALIDATION", f"El campo reason debe ser texto de hasta {_MAX_REASON} caracteres")
    return value.strip() or None


def _apply(report_id: str, to_status: str, reason: str | None, actor: str) -> dict | None:
    """Un intento. Devuelve el nuevo META, o None si otro cambio ganó la carrera de versión."""
    key = {"pk": f"REPORT#{report_id}", "sk": "META"}
    meta = ddb.table("Reports").get_item(Key=key, ConsistentRead=True).get("Item")
    if not meta:
        raise http.ApiError("NOT_FOUND", "El reporte no existe")
    from_status = meta["status"]
    if not domain.can_transition_report(from_status, to_status):
        raise http.ApiError("CONFLICT", f"Transición no permitida: {from_status} a {to_status}")

    now = ids.now_iso()
    hist = {
        "pk": key["pk"],
        "sk": f"HIST#{now}",
        "type": "REPORT_HIST",
        "from_status": from_status,
        "to_status": to_status,
        "actor": actor,
        "at": now,
    }
    if reason:
        hist["reason"] = reason
    ops = [
        ddb.update_op(
            "Reports",
            key,
            "SET #s = :to, updated_at = :now, #v = #v + :one",
            condition="#v = :v",
            names={"#s": "status", "#v": "version"},
            values={":to": to_status, ":now": now, ":one": 1, ":v": meta["version"]},
        ),
        ddb.put_op("Reports", hist, condition="attribute_not_exists(pk)"),
        events.outbox_put_op(
            "report.status_changed",
            {
                "report_id": report_id,
                "customer_id": meta["customer_id"],
                "zone_id": meta["zone_id"],
                "from_status": from_status,
                "to_status": to_status,
                "actor": actor,
                "at": now,
            },
        ),
    ]
    try:
        ddb.transact(ops)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        return None
    return {**meta, "status": to_status, "updated_at": now, "version": meta["version"] + 1}


@http.api
def handler(event, context):
    claims = http.require_role(event, "OPERATOR")
    report_id = http.path_param(event, "report_id")
    body = http.json_body(event)
    to_status, reason = _to_status(body), _reason(body)
    actor = f"OPERATOR#{claims['sub']}"

    for _ in range(_ATTEMPTS):
        meta = _apply(report_id, to_status, reason, actor)
        if meta:
            log.info("reporte %s pasa a %s", report_id, to_status)
            return http.response(200, http.public_item(meta))
    raise http.ApiError("CONFLICT", "El reporte cambió al mismo tiempo; vuelve a intentarlo")
