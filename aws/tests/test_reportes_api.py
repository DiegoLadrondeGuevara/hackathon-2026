"""T05: listar_mis_reportes, obtener_reporte y cambiar_estado_reporte."""
import json

import pytest
from boto3.dynamodb.conditions import Key

from common import ddb, http
from handlers import cambiar_estado_reporte, listar_mis_reportes, obtener_reporte

DUENO = "70000001"
AJENO = "70000002"
OPERADOR = "OP001"


def _auth(sub, role):
    return {"requestContext": {"authorizer": {"lambda": {"sub": sub, "role": role}}}}


def _put_report(n: int, customer=DUENO, zone="Z01", status="REGISTRADA") -> str:
    """META + HIST inicial con la forma que escribe CrearReporte. `n` fija el orden temporal."""
    rid = f"R{n:025d}"
    at = f"2026-11-14T10:{n:02d}:00.000Z"
    table = ddb.table("Reports")
    table.put_item(
        Item={
            "pk": f"REPORT#{rid}", "sk": "META", "type": "REPORT_META", "report_id": rid,
            "customer_id": customer, "service_number": "987654321", "zone_id": zone, "service": "INTERNET",
            "problem_type": "SIN_INTERNET", "description": "Sin conexión", "occurred_at": at,
            "created_at": at, "updated_at": at, "status": status, "version": 1,
            "gsi1pk": f"CUSTOMER#{customer}", "gsi1sk": f"{at}#{rid}",
            "gsi2pk": f"ZONE#{zone}", "gsi2sk": f"{at}#{rid}",
        }
    )
    table.put_item(
        Item={"pk": f"REPORT#{rid}", "sk": f"HIST#{at}", "type": "REPORT_HIST", "from_status": None,
              "to_status": "REGISTRADA", "actor": f"CUSTOMER#{customer}", "at": at}
    )
    return rid


def _list(sub=DUENO, role="CUSTOMER", **params):
    event = {**_auth(sub, role), "queryStringParameters": params or None}
    resp = listar_mis_reportes.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def _get(rid, sub=DUENO, role="CUSTOMER"):
    event = {**_auth(sub, role), "pathParameters": {"report_id": rid}}
    resp = obtener_reporte.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def _patch(rid, to_status, sub=OPERADOR, role="OPERATOR", reason=None, raw=None):
    payload = {"to_status": to_status}
    if reason is not None:
        payload["reason"] = reason
    event = {
        **_auth(sub, role),
        "pathParameters": {"report_id": rid},
        "body": raw if raw is not None else json.dumps(payload),
    }
    resp = cambiar_estado_reporte.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def _outbox():
    return [json.loads(i["detail"]) for i in ddb.table("Outbox").scan()["Items"]]


# --- listar_mis_reportes ---

def test_cliente_ve_solo_los_suyos_en_orden_descendente(aws):
    r1, r2 = _put_report(1), _put_report(2)
    _put_report(3, customer=AJENO)
    status, body = _list()
    assert status == 200
    assert [i["report_id"] for i in body["items"]] == [r2, r1]
    assert body["next_cursor"] is None
    item = body["items"][0]
    assert item["status"] == "REGISTRADA" and item["version"] == 1
    assert not any(k in ("pk", "sk") or k.startswith("gsi") for k in item)


def test_cliente_no_puede_listar_por_zona_ajena(aws):
    """Para CUSTOMER `zone_id` se ignora: siempre salen los propios."""
    _put_report(1, customer=AJENO)
    _, body = _list(zone_id="Z01")
    assert body["items"] == []


def test_paginacion_con_cursor(aws):
    rids = [_put_report(n) for n in range(1, 6)]
    _, p1 = _list(limit="2")
    assert [i["report_id"] for i in p1["items"]] == [rids[4], rids[3]] and p1["next_cursor"]
    _, p2 = _list(limit="2", cursor=p1["next_cursor"])
    _, p3 = _list(limit="2", cursor=p2["next_cursor"])
    assert [i["report_id"] for i in p2["items"] + p3["items"]] == [rids[2], rids[1], rids[0]]


def test_cursor_de_otro_cliente_se_rechaza(aws):
    for n in range(1, 4):
        _put_report(n)
    _, p1 = _list(limit="1")
    status, body = _list(sub=AJENO, cursor=p1["next_cursor"])
    assert status == 400 and body["error"]["code"] == "VALIDATION"


@pytest.mark.parametrize("params", [{"limit": "0"}, {"limit": "x"}, {"cursor": "%%%"}, {"cursor": "W10"}])
def test_parametros_invalidos_dan_400(aws, params):
    status, body = _list(**params)
    assert status == 400 and body["error"]["code"] == "VALIDATION"


def test_limite_maximo_es_100():
    assert http.page_limit({"queryStringParameters": {"limit": "500"}}) == 100
    assert http.page_limit({}) == 20


def test_operador_lista_por_zona_y_zone_id_es_obligatorio(aws):
    r1 = _put_report(1, zone="Z01")
    r2 = _put_report(2, customer=AJENO, zone="Z01")
    _put_report(3, zone="Z02")
    status, body = _list(sub=OPERADOR, role="OPERATOR", zone_id="Z01")
    assert status == 200 and [i["report_id"] for i in body["items"]] == [r2, r1]
    status, body = _list(sub=OPERADOR, role="OPERATOR")
    assert status == 400 and body["error"]["code"] == "VALIDATION"


def test_listar_sin_sesion_da_401(aws):
    assert listar_mis_reportes.handler({}, None)["statusCode"] == 401


# --- obtener_reporte ---

def test_dueno_obtiene_meta_e_historial(aws):
    rid = _put_report(1)
    status, body = _get(rid)
    assert status == 200
    assert body["report_id"] == rid and body["customer_id"] == DUENO and body["description"] == "Sin conexión"
    assert not any(k in ("pk", "sk") or k.startswith("gsi") for k in body)
    assert body["history"] == [
        {"from_status": None, "to_status": "REGISTRADA", "actor": f"CUSTOMER#{DUENO}", "reason": None,
         "at": "2026-11-14T10:01:00.000Z"}
    ]


def test_ajeno_no_puede_ver_y_operador_si(aws):
    rid = _put_report(1)
    status, body = _get(rid, sub=AJENO)
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    assert "description" not in body
    status, body = _get(rid, sub=OPERADOR, role="OPERATOR")
    assert status == 200 and body["report_id"] == rid


def test_reporte_inexistente_da_404(aws):
    status, body = _get("NOEXISTE")
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


def test_obtener_sin_id_da_400(aws):
    resp = obtener_reporte.handler(_auth(DUENO, "CUSTOMER"), None)
    assert resp["statusCode"] == 400


# --- cambiar_estado_reporte ---

def test_transicion_valida_actualiza_meta_hist_y_outbox(aws):
    rid = _put_report(1)
    status, body = _patch(rid, "EN_REVISION", reason="Revisando la zona")
    assert status == 200
    assert body["status"] == "EN_REVISION" and body["version"] == 2
    assert body["updated_at"] > body["created_at"]
    assert not any(k in ("pk", "sk") or k.startswith("gsi") for k in body)

    meta = ddb.table("Reports").get_item(Key={"pk": f"REPORT#{rid}", "sk": "META"})["Item"]
    assert meta["status"] == "EN_REVISION" and meta["version"] == 2 and meta["updated_at"] == body["updated_at"]
    assert meta["gsi1pk"] == f"CUSTOMER#{DUENO}"  # los índices no cambian

    _, detalle = _get(rid)
    assert detalle["history"][-1] == {
        "from_status": "REGISTRADA", "to_status": "EN_REVISION", "actor": f"OPERATOR#{OPERADOR}",
        "reason": "Revisando la zona", "at": body["updated_at"],
    }
    eventos = _outbox()
    assert len(eventos) == 1 and eventos[0]["type"] == "report.status_changed"
    assert eventos[0]["data"] == {
        "report_id": rid, "customer_id": DUENO, "zone_id": "Z01", "from_status": "REGISTRADA",
        "to_status": "EN_REVISION", "actor": f"OPERATOR#{OPERADOR}", "at": body["updated_at"],
    }


def test_recorrido_completo_y_reapertura(aws):
    rid = _put_report(1)
    for to in ("EN_REVISION", "EN_ATENCION", "SOLUCIONADA", "EN_ATENCION", "SOLUCIONADA", "CERRADA"):
        status, body = _patch(rid, to)
        assert status == 200 and body["status"] == to
    assert body["version"] == 7
    assert len(_outbox()) == 6
    hist = ddb.query_all(
        "Reports", KeyConditionExpression=Key("pk").eq(f"REPORT#{rid}") & Key("sk").begins_with("HIST#")
    )
    assert len(hist) == 7


@pytest.mark.parametrize(
    "actual,destino",
    [("REGISTRADA", "EN_ATENCION"), ("REGISTRADA", "CERRADA"), ("EN_REVISION", "REGISTRADA"),
     ("CERRADA", "EN_ATENCION"), ("SOLUCIONADA", "EN_REVISION")],
)
def test_transicion_prohibida_da_409_y_no_escribe(aws, actual, destino):
    rid = _put_report(1, status=actual)
    status, body = _patch(rid, destino)
    assert status == 409 and body["error"]["code"] == "CONFLICT"
    meta = ddb.table("Reports").get_item(Key={"pk": f"REPORT#{rid}", "sk": "META"})["Item"]
    assert meta["status"] == actual and meta["version"] == 1
    assert _outbox() == []


def test_reintento_duplicado_no_repite_el_cambio(aws):
    rid = _put_report(1)
    assert _patch(rid, "EN_REVISION")[0] == 200
    status, body = _patch(rid, "EN_REVISION")
    assert status == 409 and body["error"]["code"] == "CONFLICT"
    assert len(_outbox()) == 1
    assert ddb.table("Reports").get_item(Key={"pk": f"REPORT#{rid}", "sk": "META"})["Item"]["version"] == 2


def _bump_version(rid):
    ddb.table("Reports").update_item(
        Key={"pk": f"REPORT#{rid}", "sk": "META"},
        UpdateExpression="SET #v = #v + :one",
        ExpressionAttributeNames={"#v": "version"},
        ExpressionAttributeValues={":one": 1},
    )


def test_version_desfasada_reintenta_una_vez(aws, monkeypatch):
    rid = _put_report(1)
    real, calls = ddb.transact, []

    def carrera(ops):
        calls.append(1)
        if len(calls) == 1:
            _bump_version(rid)  # otro escritor gana entre la lectura y la transacción
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    status, body = _patch(rid, "EN_REVISION")
    assert status == 200 and body["version"] == 3 and len(calls) == 2
    assert len(_outbox()) == 1


def test_version_desfasada_dos_veces_da_409(aws, monkeypatch):
    rid = _put_report(1)
    real = ddb.transact

    def carrera(ops):
        _bump_version(rid)
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    status, body = _patch(rid, "EN_REVISION")
    assert status == 409 and body["error"]["code"] == "CONFLICT"
    assert _outbox() == []
    assert ddb.table("Reports").get_item(Key={"pk": f"REPORT#{rid}", "sk": "META"})["Item"]["status"] == "REGISTRADA"


def test_cliente_no_puede_cambiar_estado(aws):
    rid = _put_report(1)
    status, body = _patch(rid, "EN_REVISION", sub=DUENO, role="CUSTOMER")
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"


def test_cambiar_estado_de_reporte_inexistente_da_404(aws):
    status, body = _patch("NOEXISTE", "EN_REVISION")
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "raw",
    ["", "no es json", json.dumps({}), json.dumps({"to_status": "RESUELTA"}), json.dumps({"to_status": 3}),
     json.dumps({"to_status": "EN_REVISION", "reason": 7}),
     json.dumps({"to_status": "EN_REVISION", "reason": "x" * 501})],
)
def test_cuerpo_invalido_da_400(aws, raw):
    rid = _put_report(1)
    status, body = _patch(rid, None, raw=raw)
    assert status == 400 and body["error"]["code"] == "VALIDATION"
    assert _outbox() == []
