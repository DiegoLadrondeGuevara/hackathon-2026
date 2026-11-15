"""T14: obtener_tendencias."""
import json
from itertools import count

import pytest

from common import ddb, ids
from handlers import obtener_tendencias

_n = count(1)


def _auth(role="OPERATOR"):
    return {"requestContext": {"authorizer": {"lambda": {"sub": "OP001", "role": role}}}}


def _hace(**delta) -> str:
    return ids.shift_iso(ids.now_iso(), **{k: -v for k, v in delta.items()})


def _zonas():
    for zid, name in (("Z01", "Miraflores"), ("Z02", "San Isidro"), ("Z03", "Surco")):
        ddb.table("NetworkCatalog").put_item(Item={
            "pk": f"ZONE#{zid}", "sk": "META", "type": "ZONE", "zone_id": zid, "name": name,
            "zone_type": "RESIDENCIAL", "criticality": 1, "est_users": 100,
            "gsi1pk": "TYPE#ZONE", "gsi1sk": zid,
        })


def _reporte(zone, problem="SIN_INTERNET", at=None):
    rid = f"R{next(_n):025d}"
    at = at or _hace(days=1)
    ddb.table("Reports").put_item(Item={
        "pk": f"REPORT#{rid}", "sk": "META", "type": "REPORT_META", "report_id": rid, "customer_id": "70000001",
        "zone_id": zone, "service": "INTERNET", "problem_type": problem, "status": "REGISTRADA",
        "created_at": at, "updated_at": at, "version": 1,
        "gsi1pk": "CUSTOMER#70000001", "gsi1sk": f"{at}#{rid}", "gsi2pk": f"ZONE#{zone}", "gsi2sk": f"{at}#{rid}",
    })


def _incidente(zone, at=None, detected_by="USUARIOS", lag=None):
    iid = f"I{next(_n):025d}"
    at = at or _hace(days=1)
    item = {
        "pk": f"INCIDENT#{iid}", "sk": "META", "type": "INCIDENT_META", "incident_id": iid, "zone_id": zone,
        "service": "INTERNET", "status": "EVALUACION", "priority": "P3", "detected_by": detected_by,
        "opened_at": at, "updated_at": at, "version": 1,
        "gsi1pk": f"ZONE#{zone}", "gsi1sk": f"{at}#{iid}",
        "gsi2pk": "STATUS#EVALUACION", "gsi2sk": f"P3#{at}#{iid}",
    }
    if lag is not None:
        item["detection_lag_seconds"] = lag
    ddb.table("Incidents").put_item(Item=item)
    # Un vínculo en la misma partición no debe contarse como incidente.
    ddb.table("Incidents").put_item(Item={
        "pk": f"INCIDENT#{iid}", "sk": "LINK#USER#70000001", "type": "LINK_USER", "customer_id": "70000001",
    })


def _episodio(antenna, zone, at=None):
    at = at or _hace(days=1)
    eid = f"E{next(_n):025d}"
    ddb.table("Telemetry").put_item(Item={
        "pk": f"ANTENNA#{antenna}", "sk": f"EPISODE#{at}#{eid}", "type": "EPISODE", "episode_id": eid,
        "antenna_id": antenna, "zone_id": zone, "state": "CAIDA", "status": "CLOSED", "opened_at": at,
        "gsi1pk": f"ZONE#{zone}", "gsi1sk": f"{at}#{antenna}",
    })


def _get(role="OPERATOR", **params):
    event = {**_auth(role), "queryStringParameters": params or None}
    resp = obtener_tendencias.handler(event, None)
    return resp["statusCode"], json.loads(resp["body"])


def test_sin_datos_devuelve_listas_vacias(aws):
    _zonas()
    status, body = _get()
    assert status == 200
    assert body == {"days": 30, "top_zonas": [], "top_antenas": [], "top_tipos": [], "recurrentes": [],
                    "deteccion": {"avg_lag_seconds": 0, "detected_by_users": 0, "detected_by_antenna": 0}}


def test_top_zonas_cuenta_reportes_e_incidentes_y_ordena(aws):
    _zonas()
    for _ in range(3):
        _reporte("Z02")
    _reporte("Z01")
    _incidente("Z02")
    _incidente("Z02")
    _, body = _get()
    assert body["top_zonas"] == [
        {"zone_id": "Z02", "name": "San Isidro", "reports": 3, "incidents": 2},
        {"zone_id": "Z01", "name": "Miraflores", "reports": 1, "incidents": 0},
    ]


def test_top_tipos(aws):
    _zonas()
    for problem, n in (("SIN_INTERNET", 3), ("LENTITUD", 1), ("LLAMADAS", 2)):
        for _ in range(n):
            _reporte("Z01", problem)
    _reporte("Z03", "LENTITUD")
    _, body = _get()
    assert body["top_tipos"] == [
        {"problem_type": "SIN_INTERNET", "count": 3}, {"problem_type": "LENTITUD", "count": 2},
        {"problem_type": "LLAMADAS", "count": 2},
    ]


def test_el_filtro_days_excluye_lo_antiguo(aws):
    _zonas()
    _reporte("Z01", at=_hace(days=2))
    _reporte("Z01", at=_hace(days=10))
    _incidente("Z01", at=_hace(days=10))
    _episodio("A001", "Z01", at=_hace(days=10))
    _, semana = _get(days="5")
    assert semana["days"] == 5
    assert semana["top_zonas"][0]["reports"] == 1 and semana["top_zonas"][0]["incidents"] == 0
    assert semana["top_antenas"] == []
    _, mes = _get(days="30")
    assert mes["top_zonas"][0]["reports"] == 2 and mes["top_zonas"][0]["incidents"] == 1
    assert mes["top_antenas"] == [{"antenna_id": "A001", "zone_id": "Z01", "episodes": 1}]


def test_top_antenas_y_recurrentes(aws):
    _zonas()
    for d in (1, 2, 3):
        _episodio("A004", "Z02", at=_hace(days=d))
    for d in (1, 2):
        _episodio("A005", "Z02", at=_hace(days=d))
    for d in (20, 21, 22):  # tres episodios, pero fuera de la ventana de 7 días
        _episodio("A009", "Z03", at=_hace(days=d))
    _, body = _get()
    assert [a["antenna_id"] for a in body["top_antenas"]] == ["A004", "A009", "A005"]
    assert body["top_antenas"][0] == {"antenna_id": "A004", "zone_id": "Z02", "episodes": 3}
    assert body["recurrentes"] == [{"antenna_id": "A004", "zone_id": "Z02", "episodes_7d": 3}]


def test_recurrencia_usa_siete_dias_aunque_days_sea_menor(aws):
    _zonas()
    for horas in (24, 60, 72):  # el corte de days=2 es a las 48 h: ninguno cae justo en el borde
        _episodio("A004", "Z02", at=_hace(hours=horas))
    _, body = _get(days="2")
    assert body["top_antenas"] == [{"antenna_id": "A004", "zone_id": "Z02", "episodes": 1}]
    assert body["recurrentes"] == [{"antenna_id": "A004", "zone_id": "Z02", "episodes_7d": 3}]


def test_deteccion(aws):
    _zonas()
    _incidente("Z01", detected_by="USUARIOS", lag=-300)
    _incidente("Z01", detected_by="ANTENA", lag=900)
    _incidente("Z02", detected_by="ANTENA", lag=600)
    _incidente("Z02", detected_by="USUARIOS")  # sin lag: no entra en el promedio
    _, body = _get()
    assert body["deteccion"] == {"avg_lag_seconds": 400, "detected_by_users": 2, "detected_by_antenna": 2}


def test_solo_el_top_cinco(aws):
    _zonas()
    for n in range(7):
        _episodio(f"A{n:03d}", "Z01")
    _, body = _get()
    assert len(body["top_antenas"]) == 5


@pytest.mark.parametrize("days", ["0", "-1", "366", "abc", "1.5"])
def test_days_invalido(aws, days):
    status, body = _get(days=days)
    assert status == 400 and body["error"]["code"] == "VALIDATION"


def test_cliente_no_puede_ver_tendencias(aws):
    status, body = _get(role="CUSTOMER")
    assert status == 403 and body["error"]["code"] == "FORBIDDEN"


def test_sin_sesion_es_401(aws):
    resp = obtener_tendencias.handler({}, None)
    assert resp["statusCode"] == 401
