"""CalculadoraDePrioridad: paso `CalcularPrioridad` de `VerificarIncidente`.

Entrada `{"incident_id", "evidence": [resultado_users, resultado_antennas]}`. Calcula la prioridad con
`domain.priority()` y escribe en una transacción con `version` (reintenta ante conflicto). Si hay
evidencia técnica y el incidente está en EVALUACION, lo pasa a CONFIRMADO. Nunca cierra ni restablece.
Idempotente: si nada cambia, no escribe ni emite eventos.
"""
import logging

from botocore.exceptions import ClientError

from common import ddb, domain, events, ids

log = logging.getLogger()
log.setLevel(logging.INFO)

ACTOR = "SYSTEM#CalculadoraDePrioridad"
_ATTEMPTS = 3


def _criticality(zone_id: str) -> int:
    zone = ddb.table("NetworkCatalog").get_item(Key={"pk": f"ZONE#{zone_id}", "sk": "META"}).get("Item") or {}
    return int(zone.get("criticality") or domain.ZONE_CRITICALITY.get(zone.get("zone_type"), 1))


def _recommended_action(status: str, evidence_users: bool, evidence_tech: bool, tech_recovered: bool,
                        structural_suspect: bool) -> str | None:
    if tech_recovered and status == "CONFIRMADO":
        return "Evaluar restablecimiento"
    if structural_suspect:
        return "Revisión estructural de la antena"
    if evidence_users and not evidence_tech and status == "EVALUACION":
        return "Verificar infraestructura de la zona"
    return None


def _target(meta: dict, evidence: dict, now: str) -> tuple[dict, str | None]:
    """Valores que debe tener el META y el cambio a anunciar (STATUS, PRIORITY o None)."""
    # Las evidencias solo se encienden aquí: quien vincula las escribe sin subir `version`.
    evidence_users = bool(meta.get("evidence_users") or evidence.get("evidence_users"))
    evidence_tech = bool(meta.get("evidence_tech") or evidence.get("evidence_tech"))
    tech_recovered = bool(evidence.get("tech_recovered"))
    worst = evidence.get("worst_antenna_state") or meta.get("worst_antenna_state")
    first_report = evidence.get("first_report_at") or meta.get("first_report_at")
    first_anomaly = evidence.get("first_anomaly_at") or meta.get("first_anomaly_at")
    users = max(int(evidence.get("affected_users") or 0), int(meta.get("affected_users") or 0))

    score, level = domain.priority(users, _criticality(meta["zone_id"]), worst)
    status = "CONFIRMADO" if evidence_tech and meta["status"] == "EVALUACION" else meta["status"]

    target = {
        "evidence_users": evidence_users, "evidence_tech": evidence_tech, "tech_recovered": tech_recovered,
        "worst_antenna_state": worst, "first_report_at": first_report, "first_anomaly_at": first_anomaly,
        "priority": level, "priority_score": score, "status": status,
        "recommended_action": _recommended_action(
            status, evidence_users, evidence_tech, tech_recovered, bool(meta.get("structural_suspect"))
        ),
        "detected_by": meta.get("detected_by"), "detection_lag_seconds": meta.get("detection_lag_seconds"),
        "gsi2pk": f"STATUS#{status}", "gsi2sk": f"{level}#{meta['opened_at']}#{meta['incident_id']}",
    }
    if first_anomaly and first_report:
        # Positivo: la antena avisó antes que los usuarios.
        target["detection_lag_seconds"] = ids.epoch(first_report) - ids.epoch(first_anomaly)
        target["detected_by"] = "ANTENA" if first_anomaly <= first_report else "USUARIOS"
    elif first_anomaly or first_report:
        target["detected_by"] = "ANTENA" if first_anomaly else "USUARIOS"

    if status != meta["status"]:
        target["confirmed_at"] = now
        return target, "STATUS"
    return target, "PRIORITY" if level != meta.get("priority") else None


def _apply(incident_id: str, evidence: dict) -> dict | None:
    """Un intento. Devuelve el resultado, o None si otro escritor ganó la carrera de versión."""
    key = {"pk": f"INCIDENT#{incident_id}", "sk": "META"}
    meta = ddb.table("Incidents").get_item(Key=key, ConsistentRead=True).get("Item")
    if not meta:
        raise ValueError(f"el incidente {incident_id} no existe")
    if meta["status"] == "CERRADO":
        return {"priority": meta.get("priority"), "priority_changed": False, "status_changed": False,
                "alert": False}

    now = ids.now_iso()
    target, change = _target(meta, evidence, now)
    result = {
        "priority": target["priority"],
        "priority_changed": target["priority"] != meta.get("priority"),
        "status_changed": change == "STATUS",
        "alert": target["priority"] == "P1" or change == "STATUS" or bool(meta.get("review_required")),
    }
    diff = {name: value for name, value in target.items() if meta.get(name) != value}
    if not diff:
        return result

    names, values = {"#v": "version"}, {":v": meta["version"], ":one": 1, ":now": now}
    sets, removes = ["updated_at = :now", "#v = #v + :one"], []
    for i, (name, value) in enumerate(sorted(diff.items())):
        names[f"#a{i}"] = name
        if value is None:
            removes.append(f"#a{i}")
        else:
            sets.append(f"#a{i} = :a{i}")
            values[f":a{i}"] = value
    update = "SET " + ", ".join(sets) + (" REMOVE " + ", ".join(removes) if removes else "")
    ops = [ddb.update_op("Incidents", key, update, condition="#v = :v", names=names, values=values)]
    if change:
        hist = {
            "pk": key["pk"], "sk": f"HIST#{now}", "type": "INCIDENT_HIST", "from_status": meta["status"],
            "to_status": target["status"], "actor": ACTOR, "change": change, "at": now,
            "reason": "Evidencia técnica de antena" if change == "STATUS"
            else f"Prioridad {meta.get('priority')} a {target['priority']}",
        }
        ops.append(ddb.put_op("Incidents", hist))
        ops.append(events.outbox_put_op("incident.updated", {
            "incident_id": incident_id, "zone_id": meta["zone_id"], "service": meta["service"],
            "status": target["status"], "priority": target["priority"],
            "milestone": target["status"] if change == "STATUS" else None, "change": change,
            "affected_users": int(meta.get("affected_users") or 0), "updated_at": now,
        }))
    try:
        ddb.transact(ops)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        return None
    log.info("incidente %s: prioridad %s, cambio %s", incident_id, target["priority"], change)
    return result


def handler(event, context):
    incident_id = event.get("incident_id")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("falta incident_id")
    evidence = {}
    for part in event.get("evidence") or []:
        if isinstance(part, dict):
            evidence.update(part)
    for _ in range(_ATTEMPTS):
        result = _apply(incident_id, evidence)
        if result:
            return result
    raise RuntimeError(f"conflicto de versión persistente en el incidente {incident_id}")
