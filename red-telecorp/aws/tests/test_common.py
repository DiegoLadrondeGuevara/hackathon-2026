import json
import time
from decimal import Decimal

import boto3
import pytest
from boto3.dynamodb.conditions import Key

from common import config, ddb, domain, events, http, ids


def test_ids_ordenables_y_formato():
    a = ids.new_id()
    time.sleep(0.003)
    b = ids.new_id()
    assert len(a) == 26 and a < b


def test_fechas_iso():
    t = ids.now_iso()
    assert t.endswith("Z") and len(t) == 24
    assert ids.shift_iso("2026-11-14T20:00:00.000Z", hours=-24) == "2026-11-13T20:00:00.000Z"
    assert ids.epoch("1970-01-01T00:00:10.000Z") == 10


@pytest.mark.parametrize(
    "gb,state",
    [(0, "INHABILITADA"), (0.0, "INHABILITADA"), (1, "CAIDA"), (59.9, "CAIDA"), (60, "NORMAL"),
     (129, "NORMAL"), (129.1, "SATURADA"), (200, "SATURADA")],
)
def test_classify_gb(gb, state):
    assert domain.classify_gb(gb) == state


def test_classify_gb_negativo():
    with pytest.raises(ValueError):
        domain.classify_gb(-1)


def test_transiciones():
    assert domain.can_transition_report("REGISTRADA", "EN_REVISION")
    assert not domain.can_transition_report("REGISTRADA", "CERRADA")
    assert domain.can_transition_report("SOLUCIONADA", "EN_ATENCION")
    assert domain.can_transition_incident("EVALUACION", "CERRADO")
    assert not domain.can_transition_incident("CONFIRMADO", "CERRADO")
    assert not domain.can_transition_incident("CERRADO", "CONFIRMADO")


def test_prioridad():
    assert domain.priority(10, 1) == (2 + 1, "P3")
    assert domain.priority(10, 5) == (7, "P2")
    assert domain.priority(100, 4, "CAIDA") == (12, "P1")
    assert domain.priority(0, 5, "INHABILITADA") == (11, "P1")
    assert domain.priority(0, 1, "CAIDA") == (5, "P3")


def test_worse():
    assert domain.worse("SATURADA", "CAIDA") == "CAIDA"
    assert domain.worse("INHABILITADA", "CAIDA") == "INHABILITADA"


def test_secreto_ssm(aws):
    boto3.client("ssm").put_parameter(
        Name="/red-telecorp/test/jwt/signing_key", Value="s3cr3t", Type="SecureString"
    )
    assert config.get_secret("jwt/signing_key") == "s3cr3t"


def test_transaccion_con_outbox(aws):
    """Patrón del contrato: cambio de datos + evento en Outbox en una sola transacción."""
    rid = ids.new_id()
    now = ids.now_iso()
    ddb.transact(
        [
            ddb.put_op(
                "Reports",
                {"pk": f"REPORT#{rid}", "sk": "META", "type": "REPORT_META", "status": "REGISTRADA",
                 "version": 1, "created_at": now, "gsi2pk": "ZONE#Z01", "gsi2sk": f"{now}#{rid}"},
                condition="attribute_not_exists(pk)",
            ),
            events.outbox_put_op("report.created", {"report_id": rid, "zone_id": "Z01"}),
        ]
    )
    meta = ddb.table("Reports").get_item(Key={"pk": f"REPORT#{rid}", "sk": "META"})["Item"]
    assert meta["status"] == "REGISTRADA"
    out = ddb.table("Outbox").scan()["Items"]
    assert len(out) == 1 and out[0]["detail_type"] == "report.created"
    detail = json.loads(out[0]["detail"])
    assert detail["type"] == "report.created" and detail["data"]["report_id"] == rid
    assert out[0]["ttl"] > ids.epoch(now)
    # el índice por zona responde
    rows = ddb.query_all("Reports", IndexName="GSI2-zone", KeyConditionExpression=Key("gsi2pk").eq("ZONE#Z01"))
    assert len(rows) == 1


def test_transaccion_condicion_falla(aws):
    item = {"pk": "REPORT#X", "sk": "META"}
    ddb.transact([ddb.put_op("Reports", item, condition="attribute_not_exists(pk)")])
    with pytest.raises(Exception) as exc:
        ddb.transact([ddb.put_op("Reports", item, condition="attribute_not_exists(pk)")])
    assert "TransactionCanceled" in str(exc.value)


def test_decimal_en_transaccion(aws):
    ddb.transact([ddb.put_op("Telemetry", {"pk": "ANTENNA#A001", "sk": "LAST", "gb_per_min": Decimal("95.5")})])
    got = ddb.table("Telemetry").get_item(Key={"pk": "ANTENNA#A001", "sk": "LAST"})["Item"]
    assert got["gb_per_min"] == Decimal("95.5")


def test_decorador_api():
    @http.api
    def ok(event, context):
        return http.response(200, {"a": Decimal("1")})

    @http.api
    def malo(event, context):
        raise http.ApiError("CONFLICT", "ya existe")

    @http.api
    def roto(event, context):
        raise RuntimeError("boom")

    assert ok({}, None)["statusCode"] == 200
    r = malo({}, None)
    assert r["statusCode"] == 409 and json.loads(r["body"])["error"]["code"] == "CONFLICT"
    r = roto({}, None)
    assert r["statusCode"] == 500 and "boom" not in r["body"]


def test_claims_y_roles():
    ev = {"requestContext": {"authorizer": {"lambda": {"sub": "123", "role": "CUSTOMER"}}}}
    assert http.claims(ev) == {"sub": "123", "role": "CUSTOMER"}
    assert http.require_role(ev, "CUSTOMER", "OPERATOR")["sub"] == "123"
    with pytest.raises(http.ApiError) as exc:
        http.require_role(ev, "OPERATOR")
    assert exc.value.code == "FORBIDDEN"
    with pytest.raises(http.ApiError):
        http.claims({})


def test_json_body():
    assert http.json_body({"body": '{"a":1}'}) == {"a": 1}
    with pytest.raises(http.ApiError):
        http.json_body({"body": "no-json"})
    with pytest.raises(http.ApiError):
        http.json_body({})
