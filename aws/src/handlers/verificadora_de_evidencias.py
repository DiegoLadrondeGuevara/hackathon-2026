"""VerificadoraDeEvidencias: ramas del Parallel de `VerificarIncidente`. Ver contracts/flows.md.

Entrada directa `{"incident_id", "mode"}` con `mode` = users | antennas. Solo lectura, así que
repetir la ejecución no cambia nada.
"""
import logging

from boto3.dynamodb.conditions import Key

from common import ddb, domain

log = logging.getLogger()
log.setLevel(logging.INFO)


def _meta(incident_id: str) -> dict:
    key = {"pk": f"INCIDENT#{incident_id}", "sk": "META"}
    meta = ddb.table("Incidents").get_item(Key=key, ConsistentRead=True).get("Item")
    if not meta:
        raise ValueError(f"el incidente {incident_id} no existe")
    return meta


def _links(incident_id: str, kind: str) -> list:
    return ddb.query_all(
        "Incidents",
        KeyConditionExpression=Key("pk").eq(f"INCIDENT#{incident_id}") & Key("sk").begins_with(f"LINK#{kind}#"),
        ConsistentRead=True,
    )


def _earliest(*values) -> str | None:
    present = [v for v in values if v]
    return min(present) if present else None


def _users(incident_id: str, meta: dict) -> dict:
    users, reports = _links(incident_id, "USER"), _links(incident_id, "REPORT")
    first = None
    if reports:
        # Los report_id son ULID: el menor es el reporte más antiguo.
        oldest = min(r["report_id"] for r in reports)
        item = ddb.table("Reports").get_item(Key={"pk": f"REPORT#{oldest}", "sk": "META"}).get("Item") or {}
        first = item.get("created_at")
    return {
        "evidence_users": bool(users),
        "affected_users": len(users),
        "report_count": len(reports),
        "first_report_at": _earliest(meta.get("first_report_at"), first),
    }


def _antennas(incident_id: str, meta: dict) -> dict:
    links = _links(incident_id, "ANTENNA")
    worst = None
    for link in links:
        state = link.get("state")
        if state in domain.ANTENNA_SEVERITY:
            worst = domain.worse(worst, state) if worst else state
    return {
        "evidence_tech": bool(links),
        "antenna_ids": sorted({link["antenna_id"] for link in links}),
        "worst_antenna_state": worst,
        "first_anomaly_at": meta.get("first_anomaly_at") or _earliest(*[link.get("linked_at") for link in links]),
        "tech_recovered": bool(links) and all(link.get("recovered_at") for link in links),
    }


def handler(event, context):
    incident_id, mode = event.get("incident_id"), event.get("mode")
    if not isinstance(incident_id, str) or not incident_id:
        raise ValueError("falta incident_id")
    if mode not in ("users", "antennas"):
        raise ValueError(f"mode no válido: {mode}")
    meta = _meta(incident_id)
    result = _users(incident_id, meta) if mode == "users" else _antennas(incident_id, meta)
    log.info("evidencias %s de %s verificadas", mode, incident_id)
    return result
