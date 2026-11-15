import json

import pytest
from boto3.dynamodb.conditions import Key

from common import ddb, ids
from handlers import crear_reporte

CUSTOMER = "70000001"
BODY = {
    "service_number": "987654321",
    "zone_id": "Z01",
    "service": "INTERNET",
    "problem_type": "SIN_INTERNET",
    "description": "No tengo conexión desde las 8",
    "location_text": "Cerca del parque Kennedy",
}


@pytest.fixture
def zona(aws):
    ddb.table("NetworkCatalog").put_item(
        Item={"pk": "ZONE#Z01", "sk": "META", "type": "ZONE", "zone_id": "Z01", "name": "Miraflores",
              "zone_type": "RESIDENCIAL", "criticality": 1, "est_users": 45000,
              "gsi1pk": "TYPE#ZONE", "gsi1sk": "Z01"}
    )


def _call(body=None, *, sub=CUSTOMER, role="CUSTOMER", key=None, raw=None, **changes):
    payload = {**BODY, **(body or {}), **changes}
    event = {
        "requestContext": {"authorizer": {"lambda": {"sub": sub, "role": role}}},
        "headers": {"idempotency-key": key} if key is not None else {},
        "body": raw if raw is not None else json.dumps(payload),
    }
    resp = crear_reporte.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def _scan(logical):
    return ddb.table(logical).scan()["Items"]


def test_crea_meta_hist_y_outbox(zona):
    status, body = _call()
    assert status == 201
    assert body["status"] == "REGISTRADA" and len(body["report_id"]) == 26
    rid, now = body["report_id"], body["created_at"]

    items = ddb.query_all("Reports", KeyConditionExpression=Key("pk").eq(f"REPORT#{rid}"))
    hist, meta = sorted(items, key=lambda i: i["sk"])
    assert meta["sk"] == "META" and meta["type"] == "REPORT_META"
    assert meta["customer_id"] == CUSTOMER and meta["status"] == "REGISTRADA" and meta["version"] == 1
    assert meta["created_at"] == meta["updated_at"] == meta["occurred_at"] == now
    assert meta["description"] == BODY["description"] and meta["location_text"] == BODY["location_text"]
    assert meta["service_number"] == "987654321" and "incident_id" not in meta
    assert meta["gsi1pk"] == f"CUSTOMER#{CUSTOMER}" and meta["gsi1sk"] == f"{now}#{rid}"
    assert meta["gsi2pk"] == "ZONE#Z01" and meta["gsi2sk"] == f"{now}#{rid}"

    assert hist["sk"] == f"HIST#{now}" and hist["type"] == "REPORT_HIST"
    assert hist["from_status"] is None and hist["to_status"] == "REGISTRADA"
    assert hist["actor"] == f"CUSTOMER#{CUSTOMER}" and hist["at"] == now

    out = _scan("Outbox")
    assert len(out) == 1 and out[0]["detail_type"] == "report.created"
    assert json.loads(out[0]["detail"])["data"] == {
        "report_id": rid, "customer_id": CUSTOMER, "zone_id": "Z01", "service": "INTERNET",
        "problem_type": "SIN_INTERNET", "created_at": now,
    }


def test_customer_id_sale_del_token_no_del_cuerpo(zona):
    _, body = _call({"customer_id": "99999999"})
    meta = ddb.table("Reports").get_item(Key={"pk": f"REPORT#{body['report_id']}", "sk": "META"})["Item"]
    assert meta["customer_id"] == CUSTOMER


def test_opcionales_ausentes(zona):
    payload = {k: v for k, v in BODY.items() if k != "location_text"}
    event = {
        "requestContext": {"authorizer": {"lambda": {"sub": CUSTOMER, "role": "CUSTOMER"}}},
        "body": json.dumps(payload),
    }
    resp = crear_reporte.handler(event, None)
    assert resp["statusCode"] == 201
    rid = json.loads(resp["body"])["report_id"]
    meta = ddb.table("Reports").get_item(Key={"pk": f"REPORT#{rid}", "sk": "META"})["Item"]
    assert "location_text" not in meta


def test_occurred_at_se_normaliza_a_utc(zona):
    hace_una_hora = ids.shift_iso(ids.now_iso(), hours=-1)
    con_offset = hace_una_hora.replace("Z", "+00:00")
    _, body = _call(occurred_at=con_offset)
    meta = ddb.table("Reports").get_item(Key={"pk": f"REPORT#{body['report_id']}", "sk": "META"})["Item"]
    assert meta["occurred_at"] == hace_una_hora


def test_idempotency_key_repetida_devuelve_200_con_el_original(zona):
    s1, b1 = _call(key="abc-123")
    s2, b2 = _call(key="abc-123", description="otro texto")
    assert (s1, s2) == (201, 200)
    assert b2 == b1
    assert len([i for i in _scan("Reports") if i["type"] == "REPORT_META"]) == 1
    assert len(_scan("Outbox")) == 1
    idem = ddb.table("Reports").get_item(Key={"pk": f"IDEM#{CUSTOMER}#abc-123", "sk": "META"})["Item"]
    assert idem["type"] == "IDEMPOTENCY" and idem["report_id"] == b1["report_id"]
    assert idem["ttl"] == ids.epoch(b1["created_at"]) + 24 * 3600


def test_misma_clave_de_otro_cliente_crea_otro_reporte(zona):
    _, b1 = _call(key="abc-123")
    s2, b2 = _call(key="abc-123", sub="70000002")
    assert s2 == 201 and b2["report_id"] != b1["report_id"]


def test_clave_de_idempotencia_vencida_no_cuenta(zona):
    _, b1 = _call(key="vieja")
    ddb.table("Reports").update_item(
        Key={"pk": f"IDEM#{CUSTOMER}#vieja", "sk": "META"},
        UpdateExpression="SET #t = :t",
        ExpressionAttributeNames={"#t": "ttl"},
        ExpressionAttributeValues={":t": ids.epoch(ids.now_iso()) - 10},
    )
    s2, b2 = _call(key="vieja")
    assert s2 == 201 and b2["report_id"] != b1["report_id"]
    idem = ddb.table("Reports").get_item(Key={"pk": f"IDEM#{CUSTOMER}#vieja", "sk": "META"})["Item"]
    assert idem["report_id"] == b2["report_id"]


def test_sin_clave_dos_llamadas_crean_dos_reportes(zona):
    _, b1 = _call()
    _, b2 = _call()
    assert b1["report_id"] != b2["report_id"]
    assert len(_scan("Outbox")) == 2


@pytest.mark.parametrize(
    "changes",
    [
        {"service_number": ""},
        {"service_number": "1" * 21},
        {"service_number": 987654321},
        {"zone_id": "Z99"},
        {"zone_id": None},
        {"service": "ANY"},
        {"service": "internet"},
        {"problem_type": "OTRA_COSA"},
        {"description": "   "},
        {"description": "x" * 1001},
        {"location_text": "x" * 201},
        {"location_text": 5},
        {"occurred_at": "ayer"},
        {"occurred_at": "2026-11-14T13:05:00"},
        {"occurred_at": 1700000000},
        {"occurred_at": ids.shift_iso(ids.now_iso(), minutes=10)},
        {"occurred_at": ids.shift_iso(ids.now_iso(), days=-31)},
    ],
)
def test_entrada_invalida_da_400_y_no_escribe(zona, changes):
    status, body = _call(changes)
    assert status == 400 and body["error"]["code"] == "VALIDATION"
    assert _scan("Reports") == [] and _scan("Outbox") == []


@pytest.mark.parametrize("raw", ["", "no es json", "[]"])
def test_cuerpo_invalido_da_400(zona, raw):
    status, body = _call(raw=raw)
    assert status == 400 and body["error"]["code"] == "VALIDATION"


def test_idempotency_key_demasiado_larga_da_400(zona):
    status, _ = _call(key="k" * 129)
    assert status == 400


def test_operador_no_puede_crear(zona):
    status, body = _call(role="OPERATOR", sub="OP001")
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    assert _scan("Reports") == []


def test_sin_sesion_da_401(zona):
    resp = crear_reporte.handler({"body": json.dumps(BODY)}, None)
    assert resp["statusCode"] == 401


def test_antena_no_sirve_como_zona(zona):
    ddb.table("NetworkCatalog").put_item(Item={"pk": "ZONE#A001", "sk": "META", "type": "ANTENNA"})
    status, _ = _call(zone_id="A001")
    assert status == 400
