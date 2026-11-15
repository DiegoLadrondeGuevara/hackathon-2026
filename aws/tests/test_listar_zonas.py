import json

from common import ddb
from handlers import listar_zonas


def _event(role="CUSTOMER"):
    return {"requestContext": {"authorizer": {"lambda": {"sub": "70000001", "role": role}}}}


def _zone(zone_id, name, zone_type, criticality):
    ddb.table("NetworkCatalog").put_item(
        Item={
            "pk": f"ZONE#{zone_id}", "sk": "META", "type": "ZONE", "zone_id": zone_id, "name": name,
            "zone_type": zone_type, "criticality": criticality, "est_users": 1000,
            "gsi1pk": "TYPE#ZONE", "gsi1sk": zone_id,
        }
    )


def test_lista_zonas_ordenadas_con_campos_publicos(aws):
    _zone("Z02", "San Isidro", "CRITICA", 5)
    _zone("Z01", "Miraflores", "RESIDENCIAL", 1)
    ddb.table("NetworkCatalog").put_item(
        Item={"pk": "ANTENNA#A001", "sk": "META", "type": "ANTENNA", "antenna_id": "A001", "zone_id": "Z01",
              "gsi1pk": "TYPE#ANTENNA", "gsi1sk": "A001", "gsi2pk": "ZONE#Z01", "gsi2sk": "ANTENNA#A001"}
    )
    resp = listar_zonas.handler(_event(), None)
    assert resp["statusCode"] == 200
    assert json.loads(resp["body"]) == {
        "items": [
            {"zone_id": "Z01", "name": "Miraflores", "zone_type": "RESIDENCIAL"},
            {"zone_id": "Z02", "name": "San Isidro", "zone_type": "CRITICA"},
        ]
    }


def test_operador_tambien_puede(aws):
    _zone("Z01", "Miraflores", "RESIDENCIAL", 1)
    resp = listar_zonas.handler(_event("OPERATOR"), None)
    assert resp["statusCode"] == 200 and len(json.loads(resp["body"])["items"]) == 1


def test_sin_zonas_devuelve_lista_vacia(aws):
    assert json.loads(listar_zonas.handler(_event(), None)["body"]) == {"items": []}


def test_sin_sesion_da_401(aws):
    resp = listar_zonas.handler({}, None)
    assert resp["statusCode"] == 401
