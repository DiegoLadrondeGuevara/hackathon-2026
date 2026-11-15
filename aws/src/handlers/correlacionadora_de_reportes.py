"""CorrelacionadoraDeReportes: consume `report.created` de ColaReportes.

Por cada reporte: actualiza el MEMBER del grupo (zona, servicio); si el grupo tiene incidente activo
vincula el reporte; si no, y hay 10 clientes distintos en 24 h, crea el incidente (con el puntero
ACTIVE_INCIDENT en la misma transacción) y vincula los reportes de la ventana.
Idempotente: el vínculo `LINK#REPORT` y el puntero se crean con `attribute_not_exists`.
"""
import json
import logging
import re

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import ddb, domain, events, ids

log = logging.getLogger()
log.setLevel(logging.INFO)

ACTOR = "SYSTEM#CorrelacionadoraDeReportes"
SERVICES = ("MOVIL", "INTERNET")
MAX_REPORT_IDS = 20
MEMBER_TTL_HOURS = 48
_LINK_ATTEMPTS = 6
_CONDITION_FAILED = "ConditionalCheckFailed"

# Posición de cada operación en la transacción de vínculo (para leer los motivos de cancelación).
_OP_LINK_REPORT, _OP_REPORT, _OP_INCIDENT, _OP_LINKED_EVENT, _OP_LINK_USER = range(5)


class InvalidMessage(Exception):
    """Dato inválido: se registra y se descarta, no se reintenta."""


def _parse(record: dict) -> dict:
    try:
        body = json.loads(record["body"])
        detail = body["detail"]
        if isinstance(detail, str):
            detail = json.loads(detail)
        if detail["type"] != "report.created":
            raise InvalidMessage(f"tipo inesperado: {detail['type']}")
        data = detail["data"]
        out = {name: data[name] for name in ("report_id", "customer_id", "zone_id", "service", "created_at")}
    except InvalidMessage:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidMessage("mensaje mal formado") from exc
    if not all(isinstance(v, str) and v for v in out.values()):
        raise InvalidMessage("campos vacíos o no textuales")
    if out["service"] not in SERVICES:
        raise InvalidMessage("servicio no válido")
    try:
        out["created_at"] = ids.to_iso(ids.parse_iso(out["created_at"]))
    except ValueError as exc:
        raise InvalidMessage("created_at no es una fecha ISO") from exc
    return out


def _cancel_codes(exc: ClientError) -> list | None:
    """Motivo por operación de una transacción cancelada, o None si el error es otro."""
    if exc.response["Error"]["Code"] != "TransactionCanceledException":
        return None
    reasons = exc.response.get("CancellationReasons")
    if reasons:
        return [r.get("Code") for r in reasons]
    found = re.search(r"\[([^\]]*)\]", exc.response["Error"].get("Message", ""))
    return [c.strip() for c in found.group(1).split(",")] if found else []


def _failed(codes: list, index: int) -> bool:
    return index < len(codes) and codes[index] == _CONDITION_FAILED


def _window_start(at: str) -> str:
    return ids.shift_iso(at, hours=-domain.COLLECTIVE_WINDOW_HOURS)


# --- Miembro ---

def _touch_member(group: str, report: dict) -> None:
    at = report["created_at"]
    key = {"pk": group, "sk": f"MEMBER#{report['customer_id']}"}
    table = ddb.table("CorrelationMembers")
    current = table.get_item(Key=key, ConsistentRead=True).get("Item")
    restart = not current or current["last_reported_at"] < _window_start(at)
    last = at if restart else max(current["last_reported_at"], at)
    values = {
        ":type": "MEMBER",
        ":customer": report["customer_id"],
        ":last": last,
        ":ttl": ids.epoch(last) + MEMBER_TTL_HOURS * 3600,
        ":started": at if restart else min(current["window_started_at"], at),
        ":rid": {report["report_id"]},
    }
    sets = (
        "SET #type = :type, customer_id = :customer, last_reported_at = :last, #ttl = :ttl, "
        "window_started_at = :started"
    )
    # Ventana nueva: los reportes de la ventana anterior ya no cuentan.
    update = f"{sets}, report_ids = :rid" if restart else f"{sets} ADD report_ids :rid"
    item = table.update_item(
        Key=key,
        UpdateExpression=update,
        ExpressionAttributeNames={"#type": "type", "#ttl": "ttl"},
        ExpressionAttributeValues=values,
        ReturnValues="ALL_NEW",
    )["Attributes"]
    extra = sorted(item["report_ids"])[:-MAX_REPORT_IDS]  # los ULID ordenan por tiempo: se quitan los más viejos
    if extra:
        table.update_item(
            Key=key, UpdateExpression="DELETE report_ids :old", ExpressionAttributeValues={":old": set(extra)}
        )


def _members_in_window(group: str, at: str) -> list:
    members = ddb.query_all(
        "CorrelationMembers",
        KeyConditionExpression=Key("pk").eq(group) & Key("sk").begins_with("MEMBER#"),
        ConsistentRead=True,
    )
    since = _window_start(at)
    return [m for m in members if m["last_reported_at"] >= since]


# --- Puntero e incidente ---

def _pointer(zone_id: str, service: str) -> dict | None:
    table = ddb.table("CorrelationMembers")
    for svc in (service, "ANY"):
        key = {"pk": f"GROUP#{zone_id}#{svc}", "sk": "ACTIVE_INCIDENT"}
        item = table.get_item(Key=key, ConsistentRead=True).get("Item")
        if item:
            return item
    return None


def _incident(incident_id: str) -> dict:
    key = {"pk": f"INCIDENT#{incident_id}", "sk": "META"}
    meta = ddb.table("Incidents").get_item(Key=key, ConsistentRead=True).get("Item")
    if not meta:
        raise RuntimeError(f"el puntero apunta a un incidente inexistente: {incident_id}")
    return meta


def _criticality(zone_id: str) -> int:
    zone = ddb.table("NetworkCatalog").get_item(Key={"pk": f"ZONE#{zone_id}", "sk": "META"}).get("Item") or {}
    return int(zone.get("criticality") or domain.ZONE_CRITICALITY.get(zone.get("zone_type"), 1))


def _create_incident(group: str, zone_id: str, service: str, members: list) -> str:
    """Crea incidente + puntero. Si otro proceso ganó la carrera, devuelve el incidente del puntero."""
    now = ids.now_iso()
    incident_id = ids.new_id()
    pk = f"INCIDENT#{incident_id}"
    score, level = domain.priority(len(members), _criticality(zone_id))
    meta = {
        "pk": pk, "sk": "META", "type": "INCIDENT_META", "incident_id": incident_id,
        "origin": "REPORTES", "zone_id": zone_id, "service": service, "status": "EVALUACION",
        "priority": level, "priority_score": score,
        # Los contadores suben al vincular: affected_users = cantidad de LINK_USER.
        "affected_users": 0, "report_count": 0,
        "evidence_users": True, "evidence_tech": False, "tech_recovered": False,
        "structural_suspect": False, "review_required": False,
        "detected_by": "USUARIOS",
        "first_report_at": min(m["window_started_at"] for m in members),
        "opened_at": now, "updated_at": now, "version": 1,
        "gsi1pk": f"ZONE#{zone_id}", "gsi1sk": f"{now}#{incident_id}",
        "gsi2pk": "STATUS#EVALUACION", "gsi2sk": f"{level}#{now}#{incident_id}",
    }
    pointer = {"pk": group, "sk": "ACTIVE_INCIDENT", "type": "ACTIVE_INCIDENT",
               "incident_id": incident_id, "opened_at": now}
    hist = {
        "pk": pk, "sk": f"HIST#{now}", "type": "INCIDENT_HIST", "from_status": None, "to_status": "EVALUACION",
        "actor": ACTOR, "change": "CREATED", "at": now,
        "reason": f"{domain.COLLECTIVE_USERS} o más clientes distintos en {domain.COLLECTIVE_WINDOW_HOURS} h",
    }
    event = events.outbox_put_op("incident.updated", {
        "incident_id": incident_id, "zone_id": zone_id, "service": service, "status": "EVALUACION",
        "priority": level, "milestone": "EVALUACION", "change": "CREATED", "affected_users": 0, "updated_at": now,
    })
    try:
        ddb.transact([
            ddb.put_op("CorrelationMembers", pointer, condition="attribute_not_exists(pk)"),
            ddb.put_op("Incidents", meta, condition="attribute_not_exists(pk)"),
            ddb.put_op("Incidents", hist),
            event,
        ])
    except ClientError as exc:
        if _cancel_codes(exc) is None:
            raise
        existing = ddb.table("CorrelationMembers").get_item(
            Key={"pk": group, "sk": "ACTIVE_INCIDENT"}, ConsistentRead=True
        ).get("Item")
        if not existing:
            raise
        log.info("carrera al crear incidente en %s: se usa %s", group, existing["incident_id"])
        return existing["incident_id"]
    log.info("incidente creado: %s grupo=%s miembros=%d", incident_id, group, len(members))
    return incident_id


# --- Vínculo ---

def _link_ops(meta: dict, report_id: str, customer_id: str, with_user: bool) -> list:
    now = ids.now_iso()
    incident_id, pk = meta["incident_id"], meta["pk"]
    ops = [
        ddb.put_op(
            "Incidents",
            {"pk": pk, "sk": f"LINK#REPORT#{report_id}", "type": "LINK_REPORT", "report_id": report_id,
             "customer_id": customer_id, "linked_at": now},
            condition="attribute_not_exists(pk)",
        ),
        ddb.update_op(
            "Reports", {"pk": f"REPORT#{report_id}", "sk": "META"}, "SET incident_id = :i",
            condition="attribute_exists(pk)", values={":i": incident_id},
        ),
    ]
    linked = events.outbox_put_op("report.linked", {
        "incident_id": incident_id, "report_id": report_id, "customer_id": customer_id,
        "zone_id": meta["zone_id"], "incident_status": meta["status"], "linked_at": now,
    })
    key = {"pk": pk, "sk": "META"}
    if not with_user:
        ops.append(ddb.update_op(
            "Incidents", key, "SET updated_at = :now ADD report_count :one",
            condition="attribute_exists(pk)", values={":now": now, ":one": 1},
        ))
        return ops + [linked]

    users = int(meta.get("affected_users", 0))
    change = None
    values = {":now": now, ":one": 1, ":true": True}
    if not meta.get("evidence_users"):
        change = "EVIDENCE"
        condition = "attribute_exists(pk) AND (attribute_not_exists(evidence_users) OR evidence_users = :false)"
        values[":false"] = False
    elif users + 1 in domain.THRESHOLDS_USERS:
        change = "THRESHOLD"
        condition = "affected_users = :users"
        values[":users"] = users
    else:
        # Sin evento: la condición garantiza que este usuario no es el primero ni cruza un umbral.
        # Si no se cumple, se relee el incidente y se toma una de las ramas de arriba.
        edges = {f":edge{i}": t - 1 for i, t in enumerate(domain.THRESHOLDS_USERS)}
        condition = f"evidence_users = :true AND NOT (affected_users IN ({', '.join(edges)}))"
        values.update(edges)
    ops.append(ddb.update_op(
        "Incidents", key,
        "SET updated_at = :now, evidence_users = :true ADD report_count :one, affected_users :one",
        condition=condition, values=values,
    ))
    ops.append(linked)
    ops.append(ddb.put_op(
        "Incidents",
        {"pk": pk, "sk": f"LINK#USER#{customer_id}", "type": "LINK_USER", "customer_id": customer_id,
         "first_report_id": report_id, "linked_at": now},
        condition="attribute_not_exists(pk)",
    ))
    if change:
        ops.append(ddb.put_op("Incidents", {
            "pk": pk, "sk": f"HIST#{now}", "type": "INCIDENT_HIST", "from_status": meta["status"],
            "to_status": meta["status"], "actor": ACTOR, "change": change, "at": now,
        }))
        ops.append(events.outbox_put_op("incident.updated", {
            "incident_id": incident_id, "zone_id": meta["zone_id"], "service": meta["service"],
            "status": meta["status"], "priority": meta.get("priority"), "milestone": None, "change": change,
            "affected_users": users + 1, "updated_at": now,
        }))
    return ops


def _link(incident_id: str, report_id: str, customer_id: str) -> dict:
    """Vincula el reporte al incidente (idempotente). Devuelve el META del incidente leído."""
    with_user = True
    for _ in range(_LINK_ATTEMPTS):
        meta = _incident(incident_id)
        try:
            ddb.transact(_link_ops(meta, report_id, customer_id, with_user))
            log.info("reporte %s vinculado a %s", report_id, incident_id)
            return meta
        except ClientError as exc:
            codes = _cancel_codes(exc)
            if codes is None:
                raise
        if _failed(codes, _OP_LINK_REPORT):
            return meta  # ya estaba procesado
        if _failed(codes, _OP_REPORT):
            raise InvalidMessage(f"el reporte {report_id} no existe")
        if with_user and _failed(codes, _OP_LINK_USER):
            with_user = False  # el cliente ya estaba vinculado: no se suma affected_users
        # En otro caso cambió el incidente (contador, evidencia) o hubo conflicto: se relee y se repite.
    raise RuntimeError(f"no se pudo vincular el reporte {report_id} a {incident_id}")


def _link_window(incident_id: str, members: list, skip: str | None = None) -> None:
    for member in members:
        for report_id in sorted(member.get("report_ids") or ()):
            if report_id == skip:
                continue
            try:
                _link(incident_id, report_id, member["customer_id"])
            except InvalidMessage as exc:
                log.warning("vínculo descartado: %s", exc)


def _process(report: dict) -> None:
    zone_id, service, at = report["zone_id"], report["service"], report["created_at"]
    group = f"GROUP#{zone_id}#{service}"
    _touch_member(group, report)

    pointer = _pointer(zone_id, service)
    if pointer:
        meta = _link(pointer["incident_id"], report["report_id"], report["customer_id"])
        # Reporte anterior a la apertura: es el que la disparó (reintento tras un fallo a medias) o
        # corrió en paralelo. Se completa el vínculo de la ventana; lo ya vinculado se ignora.
        if meta.get("origin") == "REPORTES" and meta["opened_at"] > at:
            _link_window(pointer["incident_id"], _members_in_window(group, at), skip=report["report_id"])
        return

    members = _members_in_window(group, at)
    if len(members) < domain.COLLECTIVE_USERS:
        return
    incident_id = _create_incident(group, zone_id, service, members)
    _link_window(incident_id, members)


def handler(event, context):
    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            _process(_parse(record))
        except InvalidMessage as exc:
            log.warning("mensaje %s descartado: %s", message_id, exc)
        except Exception:  # noqa: BLE001 - el registro vuelve a la cola
            log.exception("fallo al procesar el mensaje %s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
