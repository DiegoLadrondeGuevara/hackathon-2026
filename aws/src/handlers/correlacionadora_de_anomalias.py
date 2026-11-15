"""CorrelacionadoraDeAnomalias: consume `telemetry.*` de ColaAnomalias. Ver contracts/flows.md.

- `telemetry.anomaly`: vincula la antena al incidente activo de la zona (el ANY, o el único de reportes)
  o crea uno `origin=TELEMETRIA`, `service=ANY` (con `review_required` si había dos o más de reportes).
- `telemetry.recovered`: marca `recovered_at` en el vínculo y recalcula `tech_recovered`. No cierra nada.
- `telemetry.recurrent`: marca `structural_suspect` en el incidente de la antena.
Idempotente: el vínculo y el puntero se crean con `attribute_not_exists` y lo ya aplicado se ignora.
Como quien vincula no sube `version`, las escrituras del META se condicionan al `updated_at` leído y se
reintentan si otro proceso escribió en medio.
"""
import json
import logging

from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import ddb, domain, events, ids

log = logging.getLogger()
log.setLevel(logging.INFO)

ACTOR = "SYSTEM#CorrelacionadoraDeAnomalias"
SERVICES = ("ANY", "MOVIL", "INTERNET")
_ATTEMPTS = 6
# Dentro de un lote: primero las anomalías (crean el vínculo que los otros dos eventos buscan).
_ORDER = {"telemetry.anomaly": 0, "telemetry.recurrent": 1, "telemetry.recovered": 2}
_REQUIRED = {
    "telemetry.anomaly": ("antenna_id", "zone_id", "episode_id", "state", "opened_at"),
    "telemetry.recovered": ("antenna_id", "zone_id", "episode_id", "closed_at"),
    "telemetry.recurrent": ("antenna_id", "zone_id"),
}
_DATES = ("opened_at", "closed_at")


class InvalidMessage(Exception):
    """Dato inválido: se registra y se descarta, no se reintenta."""


def _parse(record: dict) -> tuple[str, dict]:
    try:
        body = json.loads(record["body"])
        detail = body["detail"]
        if isinstance(detail, str):
            detail = json.loads(detail)
        event_type = detail["type"]
        if event_type not in _REQUIRED:
            raise InvalidMessage(f"tipo inesperado: {event_type}")
        out = {name: detail["data"][name] for name in _REQUIRED[event_type]}
    except InvalidMessage:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidMessage("mensaje mal formado") from exc
    if not all(isinstance(v, str) and v and "#" not in v for v in out.values()):
        raise InvalidMessage("campos vacíos o no textuales")
    if event_type == "telemetry.anomaly" and domain.ANTENNA_SEVERITY.get(out["state"], 0) == 0:
        raise InvalidMessage("estado de antena no válido")
    for name in _DATES:
        if name in out:
            try:
                out[name] = ids.to_iso(ids.parse_iso(out[name]))
            except ValueError as exc:
                raise InvalidMessage(f"{name} no es una fecha ISO") from exc
    return event_type, out


# --- Lecturas ---

def _active(zone_id: str) -> dict:
    """Incidentes activos de la zona según los punteros: {service: META}."""
    members, incidents = ddb.table("CorrelationMembers"), ddb.table("Incidents")
    out = {}
    for service in SERVICES:
        key = {"pk": f"GROUP#{zone_id}#{service}", "sk": "ACTIVE_INCIDENT"}
        pointer = members.get_item(Key=key, ConsistentRead=True).get("Item")
        if not pointer:
            continue
        meta = incidents.get_item(
            Key={"pk": f"INCIDENT#{pointer['incident_id']}", "sk": "META"}, ConsistentRead=True
        ).get("Item")
        if not meta:
            raise RuntimeError(f"el puntero apunta a un incidente inexistente: {pointer['incident_id']}")
        out[service] = meta
    return out


def _link_sk(data: dict) -> str:
    return f"LINK#ANTENNA#{data['antenna_id']}#{data['episode_id']}"


def _find_link(active: dict, sk: str) -> tuple[dict, dict] | None:
    """(META, vínculo) del incidente activo que ya tiene esa antena y episodio."""
    for meta in active.values():
        link = ddb.table("Incidents").get_item(Key={"pk": meta["pk"], "sk": sk}, ConsistentRead=True).get("Item")
        if link:
            return meta, link
    return None


# --- Operaciones ---

def _evidence_ops(meta: dict, now: str, change: str, reason: str, sets: dict, antenna_id: str | None = None) -> list:
    """Update del META (condicionado al `updated_at` leído) + HIST + `incident.updated`."""
    names = {"#status": "status"}
    values = {":prev": meta["updated_at"], ":closed": "CERRADO", ":now": now}
    parts = ["updated_at = :now"]
    for i, (name, value) in enumerate(sorted(sets.items())):
        names[f"#a{i}"] = name
        values[f":a{i}"] = value
        parts.append(f"#a{i} = :a{i}")
    update = "SET " + ", ".join(parts)
    if antenna_id:
        update += " ADD antenna_ids :antenna"
        values[":antenna"] = {antenna_id}
    return [
        ddb.update_op(
            "Incidents", {"pk": meta["pk"], "sk": "META"}, update,
            condition="updated_at = :prev AND #status <> :closed", names=names, values=values,
        ),
        ddb.put_op("Incidents", {
            "pk": meta["pk"], "sk": f"HIST#{now}", "type": "INCIDENT_HIST", "from_status": meta["status"],
            "to_status": meta["status"], "actor": ACTOR, "change": change, "reason": reason, "at": now,
        }, condition="attribute_not_exists(pk)"),  # mismo milisegundo que otro HIST: se reintenta
        events.outbox_put_op("incident.updated", {
            "incident_id": meta["incident_id"], "zone_id": meta["zone_id"], "service": meta["service"],
            "status": meta["status"], "priority": meta.get("priority"), "milestone": None, "change": change,
            "affected_users": int(meta.get("affected_users") or 0), "updated_at": now,
        }),
    ]


def _link_item(pk: str, data: dict, now: str) -> dict:
    return {
        "pk": pk, "sk": _link_sk(data), "type": "LINK_ANTENNA", "antenna_id": data["antenna_id"],
        "episode_id": data["episode_id"], "state": data["state"], "linked_at": now,
    }


def _worst(meta: dict, state: str) -> str:
    current = meta.get("worst_antenna_state")
    return domain.worse(current, state) if current in domain.ANTENNA_SEVERITY else state


def _link_ops(meta: dict, data: dict) -> list:
    now = ids.now_iso()
    sets = {
        "evidence_tech": True, "tech_recovered": False, "worst_antenna_state": _worst(meta, data["state"]),
        "first_anomaly_at": min(meta.get("first_anomaly_at") or data["opened_at"], data["opened_at"]),
    }
    reason = f"Antena {data['antenna_id']} en estado {data['state']}"
    return [
        ddb.put_op("Incidents", _link_item(meta["pk"], data, now), condition="attribute_not_exists(pk)"),
        *_evidence_ops(meta, now, "EVIDENCE", reason, sets, antenna_id=data["antenna_id"]),
    ]


def _escalate_ops(meta: dict, link: dict, data: dict) -> list:
    now = ids.now_iso()
    reason = f"Antena {data['antenna_id']} empeoró a {data['state']}"
    return [
        ddb.update_op(
            "Incidents", {"pk": link["pk"], "sk": link["sk"]}, "SET #state = :state",
            condition="#state = :old", names={"#state": "state"},
            values={":state": data["state"], ":old": link["state"]},
        ),
        *_evidence_ops(meta, now, "EVIDENCE", reason, {"worst_antenna_state": _worst(meta, data["state"])}),
    ]


def _create_ops(data: dict, review_required: bool) -> list:
    """Incidente de telemetría + puntero ANY + vínculo de la antena, todo en una transacción."""
    now = ids.now_iso()
    incident_id = ids.new_id()
    pk, zone_id, state = f"INCIDENT#{incident_id}", data["zone_id"], data["state"]
    # Prioridad provisional (criticidad mínima): CalculadoraDePrioridad la fija con la zona real al verificar.
    score, level = domain.priority(0, min(domain.ZONE_CRITICALITY.values()), state)
    meta = {
        "pk": pk, "sk": "META", "type": "INCIDENT_META", "incident_id": incident_id,
        "origin": "TELEMETRIA", "zone_id": zone_id, "service": "ANY", "status": "EVALUACION",
        "priority": level, "priority_score": score, "affected_users": 0, "report_count": 0,
        "evidence_users": False, "evidence_tech": True, "tech_recovered": False,
        "structural_suspect": False, "review_required": review_required,
        "antenna_ids": {data["antenna_id"]}, "worst_antenna_state": state,
        "detected_by": "ANTENA", "first_anomaly_at": data["opened_at"],
        "opened_at": now, "updated_at": now, "version": 1,
        "gsi1pk": f"ZONE#{zone_id}", "gsi1sk": f"{now}#{incident_id}",
        "gsi2pk": "STATUS#EVALUACION", "gsi2sk": f"{level}#{now}#{incident_id}",
    }
    pointer = {"pk": f"GROUP#{zone_id}#ANY", "sk": "ACTIVE_INCIDENT", "type": "ACTIVE_INCIDENT",
               "incident_id": incident_id, "opened_at": now}
    reason = f"Anomalía de la antena {data['antenna_id']} ({state})"
    if review_required:
        reason += "; hay varios incidentes de reportes en la zona"
    hist = {
        "pk": pk, "sk": f"HIST#{now}", "type": "INCIDENT_HIST", "from_status": None, "to_status": "EVALUACION",
        "actor": ACTOR, "change": "CREATED", "reason": reason, "at": now,
    }
    return [
        ddb.put_op("CorrelationMembers", pointer, condition="attribute_not_exists(pk)"),
        ddb.put_op("Incidents", meta, condition="attribute_not_exists(pk)"),
        ddb.put_op("Incidents", hist),
        ddb.put_op("Incidents", _link_item(pk, data, now)),
        events.outbox_put_op("incident.updated", {
            "incident_id": incident_id, "zone_id": zone_id, "service": "ANY", "status": "EVALUACION",
            "priority": level, "milestone": "EVALUACION", "change": "CREATED", "affected_users": 0,
            "updated_at": now,
        }),
    ]


def _transact(ops: list) -> bool:
    """False si la transacción se canceló por una condición: hay que releer y reevaluar."""
    try:
        ddb.transact(ops)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        return False


# --- Eventos ---

def _anomaly_ops(data: dict) -> list | None:
    active = _active(data["zone_id"])
    found = _find_link(active, _link_sk(data))
    if found:
        meta, link = found
        if domain.ANTENNA_SEVERITY[data["state"]] <= domain.ANTENNA_SEVERITY.get(link.get("state"), 0):
            return None  # duplicado, o el vínculo ya tiene un estado igual o peor
        return _escalate_ops(meta, link, data)
    reports = [active[s] for s in ("MOVIL", "INTERNET") if s in active]
    target = active.get("ANY") or (reports[0] if len(reports) == 1 else None)
    if target:
        return _link_ops(target, data)
    return _create_ops(data, review_required=len(reports) >= 2)


def _recovered_ops(data: dict) -> list | None:
    found = _find_link(_active(data["zone_id"]), _link_sk(data))
    if not found:
        log.info("recuperación sin incidente activo: antena %s", data["antenna_id"])
        return None
    meta, link = found
    if link.get("recovered_at"):
        return None
    links = ddb.query_all(
        "Incidents", KeyConditionExpression=Key("pk").eq(meta["pk"]) & Key("sk").begins_with("LINK#ANTENNA#"),
        ConsistentRead=True,
    )
    all_recovered = all(item.get("recovered_at") or item["sk"] == link["sk"] for item in links)
    now = ids.now_iso()
    reason = f"Antena {data['antenna_id']} recuperada"
    return [
        ddb.update_op(
            "Incidents", {"pk": link["pk"], "sk": link["sk"]}, "SET recovered_at = :at",
            condition="attribute_not_exists(recovered_at)", values={":at": data["closed_at"]},
        ),
        *_evidence_ops(meta, now, "RECOVERY", reason, {"tech_recovered": all_recovered}),
    ]


def _recurrent_ops(data: dict) -> list | None:
    antenna_id = data["antenna_id"]
    active = _active(data["zone_id"])
    target = next((m for m in active.values() if antenna_id in (m.get("antenna_ids") or ())), None)
    if not target:
        key = {"pk": f"ANTENNA#{antenna_id}", "sk": "LAST"}
        last = ddb.table("Telemetry").get_item(Key=key, ConsistentRead=True).get("Item") or {}
        if last.get("open_episode_id"):
            # El episodio sigue abierto: su anomalía aún no se vinculó. Se reintenta.
            raise RuntimeError(f"recurrencia de {antenna_id} sin incidente todavía")
        log.info("recurrencia sin incidente activo: antena %s", antenna_id)
        return None
    if target.get("structural_suspect"):
        return None
    reason = f"Antena {antenna_id} recurrente: sospecha estructural"
    return _evidence_ops(target, ids.now_iso(), "EVIDENCE", reason, {"structural_suspect": True})


_BUILDERS = {
    "telemetry.anomaly": _anomaly_ops,
    "telemetry.recovered": _recovered_ops,
    "telemetry.recurrent": _recurrent_ops,
}


def _process(event_type: str, data: dict) -> None:
    build = _BUILDERS[event_type]
    for _ in range(_ATTEMPTS):
        ops = build(data)
        if ops is None or _transact(ops):
            if ops:
                log.info("%s aplicado: antena %s zona %s", event_type, data["antenna_id"], data["zone_id"])
            return
    raise RuntimeError(f"conflicto persistente al aplicar {event_type} de {data['antenna_id']}")


def handler(event, context):
    failures, parsed = [], []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            parsed.append((message_id, *_parse(record)))
        except InvalidMessage as exc:
            log.warning("mensaje %s descartado: %s", message_id, exc)
    for message_id, event_type, data in sorted(parsed, key=lambda p: _ORDER[p[1]]):
        try:
            _process(event_type, data)
        except Exception:  # noqa: BLE001 - el registro vuelve a la cola
            log.exception("fallo al procesar el mensaje %s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
