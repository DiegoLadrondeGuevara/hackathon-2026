"""ObtenerTendencias: GET /tendencias?days=30 (solo OPERATOR).

Consulta por zona (12 zonas) los índices por zona de Reports, Incidents y Telemetry desde `now - days`.
Sin Scan. Los episodios se leen desde `now - max(days, 7)` para calcular la recurrencia de 7 días.
"""
from collections import Counter

from boto3.dynamodb.conditions import Key

from common import ddb, domain, http, ids

DEFAULT_DAYS = 30
MAX_DAYS = 365
TOP = 5


def _days(event) -> int:
    raw = http.query_param(event, "days")
    if raw is None or raw == "":
        return DEFAULT_DAYS
    try:
        value = int(raw)
    except ValueError as exc:
        raise http.ApiError("VALIDATION", "El parámetro days debe ser un entero") from exc
    if not 1 <= value <= MAX_DAYS:
        raise http.ApiError("VALIDATION", f"El parámetro days debe estar entre 1 y {MAX_DAYS}")
    return value


def _zones() -> dict:
    items = ddb.query_all("NetworkCatalog", IndexName="GSI1-type", KeyConditionExpression=Key("gsi1pk").eq("TYPE#ZONE"))
    return {z["zone_id"]: z.get("name", z["zone_id"]) for z in items}


def _since(index: str, pk_name: str, sk_name: str, logical: str, zone_id: str, since: str) -> list:
    return ddb.query_all(
        logical, IndexName=index,
        KeyConditionExpression=Key(pk_name).eq(f"ZONE#{zone_id}") & Key(sk_name).gte(since),
    )


def _top(counter: Counter, n: int = TOP) -> list:
    """Mayor conteo primero; en empate, por clave (orden estable)."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], str(kv[0])))[:n]


def _detection(incidents: list) -> dict:
    lags = [int(i["detection_lag_seconds"]) for i in incidents if i.get("detection_lag_seconds") is not None]
    return {
        "avg_lag_seconds": round(sum(lags) / len(lags)) if lags else 0,
        "detected_by_users": sum(1 for i in incidents if i.get("detected_by") == "USUARIOS"),
        "detected_by_antenna": sum(1 for i in incidents if i.get("detected_by") == "ANTENA"),
    }


def _trends(days: int) -> dict:
    now = ids.now_iso()
    since = ids.shift_iso(now, days=-days)
    rec_since = ids.shift_iso(now, days=-domain.RECURRENCE_DAYS)
    episodes_since = min(since, rec_since)

    zones = _zones()
    reports_by_zone, incidents_by_zone = Counter(), Counter()
    types, episodes_by_antenna, antenna_zone = Counter(), Counter(), {}
    recent_by_antenna = Counter()
    incidents = []
    for zone_id in sorted(zones):
        reports = _since("GSI2-zone", "gsi2pk", "gsi2sk", "Reports", zone_id, since)
        reports = [r for r in reports if r.get("type") == "REPORT_META"]
        reports_by_zone[zone_id] = len(reports)
        types.update(r["problem_type"] for r in reports if r.get("problem_type"))

        zone_incidents = _since("GSI1-zone", "gsi1pk", "gsi1sk", "Incidents", zone_id, since)
        zone_incidents = [i for i in zone_incidents if i.get("type") == "INCIDENT_META"]
        incidents_by_zone[zone_id] = len(zone_incidents)
        incidents.extend(zone_incidents)

        for ep in _since("GSI1-zone", "gsi1pk", "gsi1sk", "Telemetry", zone_id, episodes_since):
            if ep.get("type") != "EPISODE":
                continue
            antenna_zone[ep["antenna_id"]] = ep.get("zone_id", zone_id)
            if ep["opened_at"] >= since:
                episodes_by_antenna[ep["antenna_id"]] += 1
            if ep["opened_at"] >= rec_since:
                recent_by_antenna[ep["antenna_id"]] += 1

    activity = Counter({z: reports_by_zone[z] * 1_000_000 + incidents_by_zone[z]
                        for z in zones if reports_by_zone[z] or incidents_by_zone[z]})
    recurrent = Counter({a: n for a, n in recent_by_antenna.items() if n >= domain.RECURRENCE_EPISODES})
    return {
        "days": days,
        "top_zonas": [
            {"zone_id": z, "name": zones[z], "reports": reports_by_zone[z], "incidents": incidents_by_zone[z]}
            for z, _ in _top(activity)
        ],
        "top_antenas": [
            {"antenna_id": a, "zone_id": antenna_zone[a], "episodes": n} for a, n in _top(episodes_by_antenna)
        ],
        "top_tipos": [{"problem_type": t, "count": n} for t, n in _top(types)],
        "recurrentes": [
            {"antenna_id": a, "zone_id": antenna_zone[a], "episodes_7d": n} for a, n in _top(recurrent)
        ],
        "deteccion": _detection(incidents),
    }


@http.api
def handler(event, context):
    http.require_role(event, "OPERATOR")
    return http.response(200, _trends(_days(event)))
