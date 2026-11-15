"""ListarZonas: GET /zonas (cualquier usuario autenticado).

Lee las zonas del catálogo por `GSI1-type` y devuelve solo los campos públicos del contrato.
"""
from boto3.dynamodb.conditions import Key

from common import ddb, http


@http.api
def handler(event, context):
    http.claims(event)
    zones = ddb.query_all(
        "NetworkCatalog", IndexName="GSI1-type", KeyConditionExpression=Key("gsi1pk").eq("TYPE#ZONE")
    )
    items = [{"zone_id": z["zone_id"], "name": z["name"], "zone_type": z["zone_type"]} for z in zones]
    return http.response(200, {"items": items})
