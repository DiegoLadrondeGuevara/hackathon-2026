"""ListarIncidentesZona: GET /incidentes y GET /incidentes/{incident_id}. Ver contracts/api.md.

Lista: `?zone_id=` para cualquiera (CUSTOMER recibe la vista pública; OPERATOR el META completo), más
reciente primero. `?status=` solo OPERATOR: cola por prioridad (`GSI2-queue`); admite `zone_id` como filtro.
Detalle (solo OPERATOR): META + `history` + `links` (conteos y antenas vinculadas).
"""
from boto3.dynamodb.conditions import Attr, Key

from common import ddb, domain, http

PUBLIC_FIELDS = ("incident_id", "zone_id", "service", "status", "opened_at", "updated_at")
_ANTENNA_FIELDS = ("antenna_id", "episode_id", "state", "linked_at", "recovered_at")
_HIST_FIELDS = ("from_status", "to_status", "actor", "reason", "change", "at")


def _detail(incident_id: str) -> dict:
    pk = f"INCIDENT#{incident_id}"
    meta = ddb.table("Incidents").get_item(Key={"pk": pk, "sk": "META"}).get("Item")
    if not meta or meta.get("type") != "INCIDENT_META":
        raise http.ApiError("NOT_FOUND", "El incidente no existe")
    history = ddb.query_all("Incidents", KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("HIST#"))
    antennas = ddb.query_all(
        "Incidents", KeyConditionExpression=Key("pk").eq(pk) & Key("sk").begins_with("LINK#ANTENNA#")
    )
    body = http.public_item(meta)
    body["history"] = [{name: h.get(name) for name in _HIST_FIELDS} for h in history]
    body["links"] = {
        "reports": meta.get("report_count", 0),
        "users": meta.get("affected_users", 0),
        "antennas": [{name: a.get(name) for name in _ANTENNA_FIELDS} for a in antennas],
    }
    return body


def _list(event, role: str) -> dict:
    zone_id, status = http.query_param(event, "zone_id"), http.query_param(event, "status")
    if status:
        if role != "OPERATOR":
            raise http.ApiError("FORBIDDEN", "No tienes permiso para esta acción")
        if status not in domain.INCIDENT_TRANSITIONS:
            raise http.ApiError("VALIDATION", "El parámetro status no es un estado de incidente válido")
        index, pk_name, pk_value, forward = "GSI2-queue", "gsi2pk", f"STATUS#{status}", True
    elif zone_id:
        index, pk_name, pk_value, forward = "GSI1-zone", "gsi1pk", f"ZONE#{zone_id}", False
    else:
        raise http.ApiError("VALIDATION", "Se requiere el parámetro zone_id o status")

    kwargs = {
        "IndexName": index,
        "KeyConditionExpression": Key(pk_name).eq(pk_value),
        "ScanIndexForward": forward,
        "Limit": http.page_limit(event),
    }
    if status and zone_id:
        kwargs["FilterExpression"] = Attr("zone_id").eq(zone_id)
    start = http.decode_cursor(event)
    if start:
        # El cursor es opaco pero viene del cliente: no puede apuntar a otra partición.
        if start.get(pk_name) != pk_value:
            raise http.ApiError("VALIDATION", "El cursor no es válido")
        kwargs["ExclusiveStartKey"] = start

    resp = ddb.table("Incidents").query(**kwargs)
    items = resp.get("Items", [])
    if role == "OPERATOR":
        out = [http.public_item(item) for item in items]
    else:
        out = [{name: item.get(name) for name in PUBLIC_FIELDS} for item in items]
    return {"items": out, "next_cursor": http.encode_cursor(resp.get("LastEvaluatedKey"))}


@http.api
def handler(event, context):
    claims = http.require_role(event, "CUSTOMER", "OPERATOR")
    incident_id = (event.get("pathParameters") or {}).get("incident_id")
    if incident_id:
        if claims["role"] != "OPERATOR":
            raise http.ApiError("FORBIDDEN", "No tienes permiso para esta acción")
        return http.response(200, _detail(incident_id))
    return http.response(200, _list(event, claims["role"]))
