"""T09: listar_incidentes_zona y cambiar_estado_incidente."""
import json

import pytest
from boto3.dynamodb.conditions import Key

from common import ddb, ids
from handlers import cambiar_estado_incidente, listar_incidentes_zona

CLIENTE = "70000001"
OPERADOR = "OP001"


def _auth(sub, role):
    return {"requestContext": {"authorizer": {"lambda": {"sub": sub, "role": role}}}}


def _iid(n: int) -> str:
    return f"I{n:025d}"


def _put_incident(n: int, zone="Z05", service="INTERNET", status="EVALUACION", priority="P3",
                  pointer=True, opened_at=None) -> str:
    iid = _iid(n)
    at = opened_at or f"2026-11-14T10:{n:02d}:00.000Z"
    ddb.table("Incidents").put_item(Item={
        "pk": f"INCIDENT#{iid}", "sk": "META", "type": "INCIDENT_META", "incident_id": iid, "origin": "REPORTES",
        "zone_id": zone, "service": service, "status": status, "priority": priority, "priority_score": 5,
        "affected_users": 10, "report_count": 12, "evidence_users": True, "evidence_tech": False,
        "detected_by": "USUARIOS", "opened_at": at, "updated_at": at, "version": 1,
        "gsi1pk": f"ZONE#{zone}", "gsi1sk": f"{at}#{iid}",
        "gsi2pk": f"STATUS#{status}", "gsi2sk": f"{priority}#{at}#{iid}",
    })
    ddb.table("Incidents").put_item(Item={
        "pk": f"INCIDENT#{iid}", "sk": f"HIST#{at}", "type": "INCIDENT_HIST", "from_status": None,
        "to_status": "EVALUACION", "actor": "SYSTEM#CorrelacionadoraDeReportes", "change": "CREATED", "at": at,
    })
    # Los vínculos comparten partición pero no entran en los índices.
    ddb.table("Incidents").put_item(Item={
        "pk": f"INCIDENT#{iid}", "sk": f"LINK#USER#{CLIENTE}", "type": "LINK_USER", "customer_id": CLIENTE,
        "first_report_id": "R1", "linked_at": at,
    })
    if pointer:
        ddb.table("CorrelationMembers").put_item(Item={
            "pk": f"GROUP#{zone}#{service}", "sk": "ACTIVE_INCIDENT", "type": "ACTIVE_INCIDENT",
            "incident_id": iid, "opened_at": at,
        })
    return iid


def _list(sub=CLIENTE, role="CUSTOMER", **params):
    event = {**_auth(sub, role), "queryStringParameters": params or None}
    resp = listar_incidentes_zona.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def _get(iid, sub=OPERADOR, role="OPERATOR"):
    event = {**_auth(sub, role), "pathParameters": {"incident_id": iid}}
    resp = listar_incidentes_zona.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def _patch(iid, to_status, sub=OPERADOR, role="OPERATOR", reason=None, raw=None):
    payload = {"to_status": to_status}
    if reason is not None:
        payload["reason"] = reason
    event = {
        **_auth(sub, role),
        "pathParameters": {"incident_id": iid},
        "body": raw if raw is not None else json.dumps(payload),
    }
    resp = cambiar_estado_incidente.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def _meta(iid) -> dict:
    return ddb.table("Incidents").get_item(Key={"pk": f"INCIDENT#{iid}", "sk": "META"})["Item"]


def _puntero(zone="Z05", service="INTERNET"):
    key = {"pk": f"GROUP#{zone}#{service}", "sk": "ACTIVE_INCIDENT"}
    return ddb.table("CorrelationMembers").get_item(Key=key).get("Item")


def _outbox():
    return [json.loads(i["detail"]) for i in ddb.table("Outbox").scan()["Items"]]


# --- listar_incidentes_zona ---

def test_vista_publica_para_cliente(aws):
    i1, i2 = _put_incident(1), _put_incident(2, service="MOVIL")
    _put_incident(3, zone="Z01")
    status, body = _list(zone_id="Z05")
    assert status == 200 and body["next_cursor"] is None
    assert [i["incident_id"] for i in body["items"]] == [i2, i1]  # más reciente primero
    assert body["items"][1] == {
        "incident_id": i1, "zone_id": "Z05", "service": "INTERNET", "status": "EVALUACION",
        "opened_at": "2026-11-14T10:01:00.000Z", "updated_at": "2026-11-14T10:01:00.000Z",
    }


def test_vista_publica_excluye_cerrados_y_el_operador_los_ve(aws):
    abierto = _put_incident(1)
    cerrado = _put_incident(2, status="CERRADO", pointer=False)
    restablecido = _put_incident(3, service="MOVIL", status="RESTABLECIDO")
    status, body = _list(zone_id="Z05")
    assert status == 200 and body["next_cursor"] is None
    assert [i["incident_id"] for i in body["items"]] == [restablecido, abierto]
    _, body = _list(sub=OPERADOR, role="OPERATOR", zone_id="Z05")
    assert [i["incident_id"] for i in body["items"]] == [restablecido, cerrado, abierto]


def test_pagina_publica_corta_o_vacia_conserva_el_cursor(aws):
    abierto = _put_incident(1, pointer=False)
    _put_incident(2, status="CERRADO", pointer=False)
    _put_incident(3, status="CERRADO", pointer=False)
    _, p1 = _list(zone_id="Z05", limit="2")
    assert p1["items"] == [] and p1["next_cursor"]  # el filtro se aplica después de limit
    vistos, cursor = [], p1["next_cursor"]
    while cursor:
        _, page = _list(zone_id="Z05", limit="2", cursor=cursor)
        vistos += [i["incident_id"] for i in page["items"]]
        cursor = page["next_cursor"]
    assert vistos == [abierto]


def test_operador_ve_el_meta_completo_por_zona(aws):
    i1 = _put_incident(1)
    status, body = _list(sub=OPERADOR, role="OPERATOR", zone_id="Z05")
    assert status == 200
    (item,) = body["items"]
    assert item["incident_id"] == i1 and item["priority"] == "P3" and item["affected_users"] == 10
    assert item["version"] == 1 and not any(k in ("pk", "sk") or k.startswith("gsi") for k in item)


def test_cola_por_estado_ordenada_por_prioridad(aws):
    p3 = _put_incident(1, priority="P3")
    p1 = _put_incident(2, zone="Z01", priority="P1")
    p2 = _put_incident(3, zone="Z02", priority="P2")
    _put_incident(4, zone="Z03", status="CONFIRMADO", priority="P1")
    status, body = _list(sub=OPERADOR, role="OPERATOR", status="EVALUACION")
    assert status == 200 and [i["incident_id"] for i in body["items"]] == [p1, p2, p3]
    _, body = _list(sub=OPERADOR, role="OPERATOR", status="EVALUACION", zone_id="Z01")
    assert [i["incident_id"] for i in body["items"]] == [p1]


def test_cliente_no_puede_usar_la_cola_por_estado(aws):
    _put_incident(1)
    status, body = _list(status="EVALUACION")
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    status, body = _list(status="EVALUACION", zone_id="Z05")
    assert status == 403


def test_paginacion_y_cursor_de_otra_particion(aws):
    iids = [_put_incident(n, pointer=False) for n in range(1, 6)]
    _, p1 = _list(zone_id="Z05", limit="2")
    assert [i["incident_id"] for i in p1["items"]] == [iids[4], iids[3]] and p1["next_cursor"]
    _, p2 = _list(zone_id="Z05", limit="2", cursor=p1["next_cursor"])
    _, p3 = _list(zone_id="Z05", limit="2", cursor=p2["next_cursor"])
    assert [i["incident_id"] for i in p2["items"] + p3["items"]] == [iids[2], iids[1], iids[0]]
    status, body = _list(zone_id="Z01", cursor=p1["next_cursor"])
    assert status == 400 and body["error"]["code"] == "VALIDATION"


@pytest.mark.parametrize("role,params", [
    ("CUSTOMER", {}), ("OPERATOR", {}), ("OPERATOR", {"status": "ABIERTO"}),
    ("CUSTOMER", {"zone_id": "Z05", "limit": "0"}), ("CUSTOMER", {"zone_id": "Z05", "cursor": "%%%"}),
])
def test_listar_parametros_invalidos_dan_400(aws, role, params):
    status, body = _list(role=role, **params)
    assert status == 400 and body["error"]["code"] == "VALIDATION"


def test_listar_sin_sesion_da_401(aws):
    assert listar_incidentes_zona.handler({}, None)["statusCode"] == 401


def test_detalle_para_operador(aws):
    iid = _put_incident(1)
    ddb.table("Incidents").put_item(Item={
        "pk": f"INCIDENT#{iid}", "sk": "LINK#ANTENNA#A013#E1", "type": "LINK_ANTENNA", "antenna_id": "A013",
        "episode_id": "E1", "state": "CAIDA", "linked_at": "2026-11-14T10:05:00.000Z",
    })
    status, body = _get(iid)
    assert status == 200 and body["incident_id"] == iid and body["status"] == "EVALUACION"
    assert not any(k in ("pk", "sk") or k.startswith("gsi") for k in body)
    assert body["history"] == [{
        "from_status": None, "to_status": "EVALUACION", "actor": "SYSTEM#CorrelacionadoraDeReportes",
        "reason": None, "change": "CREATED", "at": "2026-11-14T10:01:00.000Z",
    }]
    assert body["links"] == {"reports": 12, "users": 10, "antennas": [{
        "antenna_id": "A013", "episode_id": "E1", "state": "CAIDA", "linked_at": "2026-11-14T10:05:00.000Z",
        "recovered_at": None,
    }]}
    assert CLIENTE not in json.dumps(body)  # el detalle no lista clientes


def test_detalle_prohibido_para_cliente_e_inexistente(aws):
    iid = _put_incident(1)
    status, body = _get(iid, sub=CLIENTE, role="CUSTOMER")
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"
    status, body = _get("NOEXISTE")
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


# --- cambiar_estado_incidente ---

def test_confirmar_actualiza_meta_gsi2_hist_y_outbox(aws):
    iid = _put_incident(1)
    status, body = _patch(iid, "CONFIRMADO", reason="Falla verificada en campo")
    assert status == 200 and body["status"] == "CONFIRMADO" and body["version"] == 2
    assert body["confirmed_at"] == body["updated_at"]
    assert not any(k in ("pk", "sk") or k.startswith("gsi") for k in body)

    meta = _meta(iid)
    assert meta["status"] == "CONFIRMADO" and meta["version"] == 2
    assert meta["gsi2pk"] == "STATUS#CONFIRMADO" and meta["gsi2sk"] == f"P3#{meta['opened_at']}#{iid}"
    assert meta["gsi1pk"] == "ZONE#Z05"
    assert _puntero()["incident_id"] == iid  # sigue activo

    _, detalle = _get(iid)
    assert detalle["history"][-1] == {
        "from_status": "EVALUACION", "to_status": "CONFIRMADO", "actor": f"OPERATOR#{OPERADOR}",
        "reason": "Falla verificada en campo", "change": "STATUS", "at": body["updated_at"],
    }
    (evento,) = _outbox()
    assert evento["type"] == "incident.updated" and evento["data"] == {
        "incident_id": iid, "zone_id": "Z05", "service": "INTERNET", "status": "CONFIRMADO", "priority": "P3",
        "milestone": "CONFIRMADO", "change": "STATUS", "affected_users": 10, "updated_at": body["updated_at"],
    }
    # La cola por estado refleja el cambio
    _, cola = _list(sub=OPERADOR, role="OPERATOR", status="CONFIRMADO")
    assert [i["incident_id"] for i in cola["items"]] == [iid]
    assert _list(sub=OPERADOR, role="OPERATOR", status="EVALUACION")[1]["items"] == []


def test_restablecer_fija_restored_at_y_conserva_el_puntero(aws):
    iid = _put_incident(1, status="CONFIRMADO")
    status, body = _patch(iid, "RESTABLECIDO")
    assert status == 200 and body["restored_at"] == body["updated_at"]
    assert _puntero()["incident_id"] == iid
    assert _outbox()[0]["data"]["milestone"] == "RESTABLECIDO"


def test_cerrar_borra_el_puntero_y_fija_la_duracion(aws):
    abierto = ids.shift_iso(ids.now_iso(), hours=-2)
    iid = _put_incident(1, status="RESTABLECIDO", opened_at=abierto)
    status, body = _patch(iid, "CERRADO")
    assert status == 200 and body["status"] == "CERRADO" and body["closed_at"] == body["updated_at"]
    assert 7200 <= body["duration_seconds"] <= 7260
    assert body["duration_seconds"] == ids.epoch(body["closed_at"]) - ids.epoch(abierto)

    meta = _meta(iid)
    assert meta["duration_seconds"] == body["duration_seconds"] and meta["gsi2pk"] == "STATUS#CERRADO"
    assert _puntero() is None
    (evento,) = _outbox()
    assert evento["data"]["status"] == "CERRADO" and evento["data"]["milestone"] is None


def test_falso_positivo_cierra_desde_evaluacion(aws):
    iid = _put_incident(1)
    assert _patch(iid, "CERRADO", reason="Falso positivo")[0] == 200
    assert _puntero() is None


def test_cerrar_no_borra_el_puntero_de_otro_incidente(aws):
    viejo = _put_incident(1, status="RESTABLECIDO", pointer=False)
    nuevo = _put_incident(2)  # el grupo ya apunta a otro incidente
    assert _patch(viejo, "CERRADO")[0] == 200
    assert _puntero()["incident_id"] == nuevo


def test_reabrir_desde_restablecido(aws):
    iid = _put_incident(1, status="RESTABLECIDO")
    status, body = _patch(iid, "CONFIRMADO")
    assert status == 200 and body["status"] == "CONFIRMADO"
    assert _outbox()[0]["data"]["milestone"] == "CONFIRMADO"


@pytest.mark.parametrize(
    "actual,destino",
    [("EVALUACION", "RESTABLECIDO"), ("CONFIRMADO", "CERRADO"), ("CONFIRMADO", "EVALUACION"),
     ("CERRADO", "CONFIRMADO"), ("RESTABLECIDO", "EVALUACION"), ("EVALUACION", "EVALUACION")],
)
def test_transicion_prohibida_da_409_y_no_escribe(aws, actual, destino):
    iid = _put_incident(1, status=actual)
    status, body = _patch(iid, destino)
    assert status == 409 and body["error"]["code"] == "CONFLICT"
    meta = _meta(iid)
    assert meta["status"] == actual and meta["version"] == 1
    assert _outbox() == [] and _puntero()["incident_id"] == iid


def test_reintento_duplicado_no_repite_el_cambio(aws):
    iid = _put_incident(1)
    assert _patch(iid, "CONFIRMADO")[0] == 200
    status, body = _patch(iid, "CONFIRMADO")
    assert status == 409 and body["error"]["code"] == "CONFLICT"
    assert len(_outbox()) == 1 and _meta(iid)["version"] == 2
    hist = ddb.query_all(
        "Incidents", KeyConditionExpression=Key("pk").eq(f"INCIDENT#{iid}") & Key("sk").begins_with("HIST#")
    )
    assert len(hist) == 2


def _bump_version(iid):
    ddb.table("Incidents").update_item(
        Key={"pk": f"INCIDENT#{iid}", "sk": "META"}, UpdateExpression="SET #v = #v + :one",
        ExpressionAttributeNames={"#v": "version"}, ExpressionAttributeValues={":one": 1},
    )


def test_version_desfasada_reintenta_una_vez(aws, monkeypatch):
    iid = _put_incident(1)
    real, calls = ddb.transact, []

    def carrera(ops):
        calls.append(1)
        if len(calls) == 1:
            _bump_version(iid)
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    status, body = _patch(iid, "CERRADO")
    assert status == 200 and body["version"] == 3 and len(calls) == 2
    assert len(_outbox()) == 1 and _puntero() is None


def test_version_desfasada_dos_veces_da_409(aws, monkeypatch):
    iid = _put_incident(1)
    real = ddb.transact

    def carrera(ops):
        _bump_version(iid)
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    status, body = _patch(iid, "CERRADO")
    assert status == 409 and body["error"]["code"] == "CONFLICT"
    assert _outbox() == [] and _meta(iid)["status"] == "EVALUACION" and _puntero()["incident_id"] == iid


def test_cliente_no_puede_cambiar_estado(aws):
    iid = _put_incident(1)
    status, body = _patch(iid, "CONFIRMADO", sub=CLIENTE, role="CUSTOMER")
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"


def test_incidente_inexistente_da_404(aws):
    status, body = _patch("NOEXISTE", "CONFIRMADO")
    assert status == 404 and body["error"]["code"] == "NOT_FOUND"


@pytest.mark.parametrize(
    "raw",
    ["", "no es json", json.dumps({}), json.dumps({"to_status": "RESUELTO"}), json.dumps({"to_status": 3}),
     json.dumps({"to_status": "CONFIRMADO", "reason": 7}),
     json.dumps({"to_status": "CONFIRMADO", "reason": "x" * 501})],
)
def test_cuerpo_invalido_da_400(aws, raw):
    iid = _put_incident(1)
    status, body = _patch(iid, None, raw=raw)
    assert status == 400 and body["error"]["code"] == "VALIDATION"
    assert _outbox() == []
