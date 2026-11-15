"""ListarMisReportes: GET /reportes.

CUSTOMER: sus propios reportes (`GSI1-customer`). OPERATOR: los de una zona, con `?zone_id=`
obligatorio (`GSI2-zone`). Orden descendente por fecha de creación, paginado con `limit` y `cursor`.
"""
from boto3.dynamodb.conditions import Key

from common import ddb, http


@http.api
def handler(event, context):
    claims = http.require_role(event, "CUSTOMER", "OPERATOR")
    if claims["role"] == "CUSTOMER":
        index, pk_name, pk_value = "GSI1-customer", "gsi1pk", f"CUSTOMER#{claims['sub']}"
    else:
        zone_id = http.query_param(event, "zone_id")
        if not zone_id:
            raise http.ApiError("VALIDATION", "El parámetro zone_id es obligatorio")
        index, pk_name, pk_value = "GSI2-zone", "gsi2pk", f"ZONE#{zone_id}"

    kwargs = {
        "IndexName": index,
        "KeyConditionExpression": Key(pk_name).eq(pk_value),
        "ScanIndexForward": False,
        "Limit": http.page_limit(event),
    }
    start = http.decode_cursor(event)
    if start:
        # El cursor es opaco pero viene del cliente: no puede apuntar a otra partición.
        if start.get(pk_name) != pk_value:
            raise http.ApiError("VALIDATION", "El cursor no es válido")
        kwargs["ExclusiveStartKey"] = start

    resp = ddb.table("Reports").query(**kwargs)
    return http.response(
        200,
        {
            "items": [http.public_item(item) for item in resp.get("Items", [])],
            "next_cursor": http.encode_cursor(resp.get("LastEvaluatedKey")),
        },
    )
