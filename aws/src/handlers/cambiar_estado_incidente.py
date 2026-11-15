"""CambiarEstadoIncidente: PATCH /incidentes/{incident_id}/estado (rol OPERATOR). Ver contracts/flows.md.

Valida la transición con `domain` y, en una transacción con `version`, actualiza META (y gsi2), agrega
INCIDENT_HIST y el evento `incident.updated` (`change=STATUS`). RESTABLECIDO fija `restored_at`; CERRADO
fija `closed_at` y `duration_seconds` y borra el puntero ACTIVE_INCIDENT en la misma transacción.
Transición inválida: 409. Versión desfasada: se reintenta una vez; si vuelve a fallar, 409.
"""
import logging

from botocore.exceptions import ClientError

from common import ddb, domain, events, http, ids

log = logging.getLogger()

_MAX_REASON = 500
_ATTEMPTS = 2
_TIMESTAMP = {"CONFIRMADO": "confirmed_at", "RESTABLECIDO": "restored_at", "CERRADO": "closed_at"}


def _to_status(body: dict) -> str:
    value = body.get("to_status")
    if not isinstance(value, str) or value not in domain.INCIDENT_TRANSITIONS:
        raise http.ApiError("VALIDATION", "El campo to_status no es un estado de incidente válido")
    return value


def _reason(body: dict) -> str | None:
    value = body.get("reason")
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > _MAX_REASON:
        raise http.ApiError("VALIDATION", f"El campo reason debe ser texto de hasta {_MAX_REASON} caracteres")
    return value.strip() or None


def _pointer_delete_op(meta: dict) -> dict | None:
    """Borrado del puntero del grupo, solo si sigue apuntando a este incidente."""
    key = {"pk": f"GROUP#{meta['zone_id']}#{meta['service']}", "sk": "ACTIVE_INCIDENT"}
    pointer = ddb.table("CorrelationMembers").get_item(Key=key, ConsistentRead=True).get("Item")
    if not pointer or pointer.get("incident_id") != meta["incident_id"]:
        return None
    return ddb.delete_op(
        "CorrelationMembers", key, condition="incident_id = :i", values={":i": meta["incident_id"]}
    )


def _apply(incident_id: str, to_status: str, reason: str | None, actor: str) -> dict | None:
    """Un intento. Devuelve el nuevo META, o None si otro cambio ganó la carrera de versión."""
    key = {"pk": f"INCIDENT#{incident_id}", "sk": "META"}
    meta = ddb.table("Incidents").get_item(Key=key, ConsistentRead=True).get("Item")
    if not meta or meta.get("type") != "INCIDENT_META":
        raise http.ApiError("NOT_FOUND", "El incidente no existe")
    from_status = meta["status"]
    if not domain.can_transition_incident(from_status, to_status):
        raise http.ApiError("CONFLICT", f"Transición no permitida: {from_status} a {to_status}")

    now = ids.now_iso()
    changes = {
        "status": to_status,
        "updated_at": now,
        "version": meta["version"] + 1,
        "gsi2pk": f"STATUS#{to_status}",
        "gsi2sk": f"{meta['priority']}#{meta['opened_at']}#{incident_id}",
        _TIMESTAMP[to_status]: now,
    }
    if to_status == "CERRADO":
        changes["duration_seconds"] = ids.epoch(now) - ids.epoch(meta["opened_at"])

    names = {f"#a{i}": name for i, name in enumerate(changes)}
    values = {f":a{i}": value for i, value in enumerate(changes.values())}
    update = "SET " + ", ".join(f"#a{i} = :a{i}" for i in range(len(changes)))
    hist = {
        "pk": key["pk"], "sk": f"HIST#{now}", "type": "INCIDENT_HIST", "from_status": from_status,
        "to_status": to_status, "actor": actor, "change": "STATUS", "at": now,
    }
    if reason:
        hist["reason"] = reason
    ops = [
        ddb.update_op(
            "Incidents", key, update, condition="#v = :v",
            names={**names, "#v": "version"}, values={**values, ":v": meta["version"]},
        ),
        ddb.put_op("Incidents", hist, condition="attribute_not_exists(pk)"),
        events.outbox_put_op("incident.updated", {
            "incident_id": incident_id, "zone_id": meta["zone_id"], "service": meta["service"],
            "status": to_status, "priority": meta["priority"],
            "milestone": to_status if to_status in domain.MILESTONES else None, "change": "STATUS",
            "affected_users": int(meta.get("affected_users") or 0), "updated_at": now,
        }),
    ]
    if to_status == "CERRADO":
        delete = _pointer_delete_op(meta)
        if delete:
            ops.append(delete)
    try:
        ddb.transact(ops)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        return None
    return {**meta, **changes}


@http.api
def handler(event, context):
    claims = http.require_role(event, "OPERATOR")
    incident_id = http.path_param(event, "incident_id")
    body = http.json_body(event)
    to_status, reason = _to_status(body), _reason(body)
    actor = f"OPERATOR#{claims['sub']}"

    for _ in range(_ATTEMPTS):
        meta = _apply(incident_id, to_status, reason, actor)
        if meta:
            log.info("incidente %s pasa a %s", incident_id, to_status)
            return http.response(200, http.public_item(meta))
    raise http.ApiError("CONFLICT", "El incidente cambió al mismo tiempo; vuelve a intentarlo")
