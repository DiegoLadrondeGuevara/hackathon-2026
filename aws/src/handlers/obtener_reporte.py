"""ObtenerReporte: GET /reportes/{report_id} (dueño u OPERATOR).

Devuelve el META sin atributos de índices más `history` (REPORT_HIST en orden cronológico).
"""
from boto3.dynamodb.conditions import Key

from common import ddb, http


@http.api
def handler(event, context):
    claims = http.require_role(event, "CUSTOMER", "OPERATOR")
    report_id = http.path_param(event, "report_id")

    items = ddb.query_all("Reports", KeyConditionExpression=Key("pk").eq(f"REPORT#{report_id}"))
    meta = next((i for i in items if i["sk"] == "META"), None)
    if not meta:
        raise http.ApiError("NOT_FOUND", "El reporte no existe")
    if claims["role"] == "CUSTOMER" and meta.get("customer_id") != claims["sub"]:
        raise http.ApiError("FORBIDDEN", "No tienes permiso para ver este reporte")

    history = [
        {
            "from_status": h.get("from_status"),
            "to_status": h.get("to_status"),
            "actor": h.get("actor"),
            "reason": h.get("reason"),
            "at": h.get("at"),
        }
        for h in sorted((i for i in items if i["sk"].startswith("HIST#")), key=lambda i: i["sk"])
    ]
    return http.response(200, {**http.public_item(meta), "history": history})
