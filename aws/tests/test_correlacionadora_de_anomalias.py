"""T11: correlacionadora_de_anomalias (antenas e incidentes)."""
import json

import pytest
from boto3.dynamodb.conditions import Key

from common import ddb, ids
from handlers import correlacionadora_de_anomalias as corr
from handlers import verificadora_de_evidencias

ZONA = "Z05"
ANTENA, EPISODIO = "A013", "E0000000000000000000000001"
BASE = "2026-11-14T10:00:00.000Z"


def _record(event_type: str, data: dict, message_id=None) -> dict:
    envelope = {"event_id": ids.new_id(), "type": event_type, "version": 1, "occurred_at": BASE, "data": data}
    body = {"source": "red-telecorp", "detail-type": event_type, "detail": envelope}
    return {"messageId": message_id or f"m-{envelope['event_id']}", "body": json.dumps(body)}


def _anomalia(antenna=ANTENA, episode=EPISODIO, state="CAIDA", reason="OPENED", zone=ZONA, opened_at=BASE) -> dict:
    return _record("telemetry.anomaly", {
        "antenna_id": antenna, "zone_id": zone, "episode_id": episode, "state": state, "gb_per_min": 40,
        "reason": reason, "opened_at": opened_at, "episodes_7d": 1,
    })


def _recuperada(antenna=ANTENA, episode=EPISODIO, zone=ZONA, closed_at="2026-11-14T10:30:00.000Z") -> dict:
    return _record("telemetry.recovered", {
        "antenna_id": antenna, "zone_id": zone, "episode_id": episode, "closed_at": closed_at,
        "duration_seconds": 1800,
    })


def _recurrente(antenna=ANTENA, zone=ZONA) -> dict:
    return _record("telemetry.recurrent", {
        "antenna_id": antenna, "zone_id": zone, "episodes_7d": 3, "window_start": "2026-11-07T10:00:00.000Z",
    })


def _run(*records) -> dict:
    return corr.handler({"Records": list(records)}, None)


def _ok(*records) -> None:
    assert _run(*records) == {"batchItemFailures": []}


def _incidente(n: int, service="INTERNET", origin="REPORTES", zone=ZONA, **extra) -> str:
    """Incidente activo con su puntero, como lo deja la correlacionadora de reportes."""
    iid = f"I{n:025d}"
    at = "2026-11-14T09:00:00.000Z"
    ddb.table("Incidents").put_item(Item={
        "pk": f"INCIDENT#{iid}", "sk": "META", "type": "INCIDENT_META", "incident_id": iid, "origin": origin,
        "zone_id": zone, "service": service, "status": "EVALUACION", "priority": "P3", "priority_score": 5,
        "affected_users": 10, "report_count": 12, "evidence_users": origin == "REPORTES",
        "evidence_tech": False, "opened_at": at, "updated_at": at, "version": 1, **extra,
    })
    ddb.table("CorrelationMembers").put_item(Item={
        "pk": f"GROUP#{zone}#{service}", "sk": "ACTIVE_INCIDENT", "type": "ACTIVE_INCIDENT",
        "incident_id": iid, "opened_at": at,
    })
    return iid


def _metas() -> list:
    return [i for i in ddb.table("Incidents").scan()["Items"] if i["type"] == "INCIDENT_META"]


def _meta(iid: str) -> dict:
    return ddb.table("Incidents").get_item(Key={"pk": f"INCIDENT#{iid}", "sk": "META"})["Item"]


def _items(iid: str, prefix: str) -> list:
    return ddb.query_all(
        "Incidents", KeyConditionExpression=Key("pk").eq(f"INCIDENT#{iid}") & Key("sk").begins_with(prefix)
    )


def _puntero(service="ANY", zone=ZONA):
    key = {"pk": f"GROUP#{zone}#{service}", "sk": "ACTIVE_INCIDENT"}
    return ddb.table("CorrelationMembers").get_item(Key=key).get("Item")


def _outbox() -> list:
    items = sorted(ddb.table("Outbox").scan()["Items"], key=lambda i: i["event_id"])
    return [json.loads(i["detail"]) for i in items]


# --- telemetry.anomaly ---

def test_sin_incidente_crea_uno_de_telemetria_con_puntero_any(aws):
    _ok(_anomalia(state="INHABILITADA"))
    (meta,) = _metas()
    iid = meta["incident_id"]
    assert meta["origin"] == "TELEMETRIA" and meta["service"] == "ANY" and meta["status"] == "EVALUACION"
    assert meta["evidence_tech"] is True and meta["evidence_users"] is False and meta["review_required"] is False
    assert meta["antenna_ids"] == {ANTENA} and meta["worst_antenna_state"] == "INHABILITADA"
    assert meta["first_anomaly_at"] == BASE and meta["detected_by"] == "ANTENA" and meta["version"] == 1
    assert meta["affected_users"] == 0 and meta["report_count"] == 0
    assert meta["gsi1pk"] == f"ZONE#{ZONA}" and meta["gsi1sk"] == f"{meta['opened_at']}#{iid}"
    assert meta["gsi2pk"] == "STATUS#EVALUACION" and meta["gsi2sk"] == f"{meta['priority']}#{meta['opened_at']}#{iid}"
    assert _puntero()["incident_id"] == iid

    (link,) = _items(iid, "LINK#ANTENNA#")
    assert link["sk"] == f"LINK#ANTENNA#{ANTENA}#{EPISODIO}" and link["state"] == "INHABILITADA"
    assert link["antenna_id"] == ANTENA and link["episode_id"] == EPISODIO and "recovered_at" not in link
    (hist,) = _items(iid, "HIST#")
    assert hist["change"] == "CREATED" and hist["from_status"] is None and hist["to_status"] == "EVALUACION"
    assert hist["actor"] == "SYSTEM#CorrelacionadoraDeAnomalias"

    (evento,) = _outbox()  # solo CREATED: no se emite además EVIDENCE
    assert evento["type"] == "incident.updated" and evento["data"] == {
        "incident_id": iid, "zone_id": ZONA, "service": "ANY", "status": "EVALUACION",
        "priority": meta["priority"], "milestone": "EVALUACION", "change": "CREATED", "affected_users": 0,
        "updated_at": meta["updated_at"],
    }
    # La verificadora ve la evidencia técnica que dejó el vínculo.
    evidencia = verificadora_de_evidencias.handler({"incident_id": iid, "mode": "antennas"}, None)
    assert evidencia["evidence_tech"] is True and evidencia["antenna_ids"] == [ANTENA]
    assert evidencia["worst_antenna_state"] == "INHABILITADA" and evidencia["first_anomaly_at"] == BASE


def test_un_incidente_de_reportes_recibe_la_antena(aws):
    iid = _incidente(1, service="MOVIL")
    _ok(_anomalia())
    assert len(_metas()) == 1 and _puntero() is None  # no se crea otro
    meta = _meta(iid)
    assert meta["evidence_tech"] is True and meta["antenna_ids"] == {ANTENA} and meta["tech_recovered"] is False
    assert meta["worst_antenna_state"] == "CAIDA" and meta["first_anomaly_at"] == BASE
    assert meta["version"] == 1 and meta["status"] == "EVALUACION" and meta["origin"] == "REPORTES"
    assert meta["affected_users"] == 10 and meta["updated_at"] > "2026-11-14T09:00:00.000Z"
    assert [x["sk"] for x in _items(iid, "LINK#ANTENNA#")] == [f"LINK#ANTENNA#{ANTENA}#{EPISODIO}"]
    (hist,) = _items(iid, "HIST#")
    assert hist["change"] == "EVIDENCE" and hist["from_status"] == hist["to_status"] == "EVALUACION"
    (evento,) = _outbox()
    assert evento["data"] == {
        "incident_id": iid, "zone_id": ZONA, "service": "MOVIL", "status": "EVALUACION", "priority": "P3",
        "milestone": None, "change": "EVIDENCE", "affected_users": 10, "updated_at": meta["updated_at"],
    }


def test_dos_incidentes_de_reportes_crean_el_any_con_revision(aws):
    movil, internet = _incidente(1, service="MOVIL"), _incidente(2, service="INTERNET")
    _ok(_anomalia())
    nuevo = _puntero()["incident_id"]
    assert nuevo not in (movil, internet) and len(_metas()) == 3
    meta = _meta(nuevo)
    assert meta["origin"] == "TELEMETRIA" and meta["service"] == "ANY" and meta["review_required"] is True
    assert _items(movil, "LINK#ANTENNA#") == [] and _items(internet, "LINK#ANTENNA#") == []
    assert _meta(movil)["evidence_tech"] is False
    assert [e["data"]["change"] for e in _outbox()] == ["CREATED"]


def test_si_existe_el_any_se_vincula_a_ese(aws):
    reportes = _incidente(1, service="INTERNET")
    existente = _incidente(2, service="ANY", origin="TELEMETRIA", evidence_tech=True, antenna_ids={"A014"},
                           worst_antenna_state="SATURADA", first_anomaly_at="2026-11-14T09:30:00.000Z")
    _ok(_anomalia(opened_at="2026-11-14T09:10:00.000Z"))
    assert len(_metas()) == 2 and _items(reportes, "LINK#ANTENNA#") == []
    meta = _meta(existente)
    assert meta["antenna_ids"] == {"A014", ANTENA} and meta["worst_antenna_state"] == "CAIDA"
    assert meta["first_anomaly_at"] == "2026-11-14T09:10:00.000Z"  # el mínimo
    assert [e["data"]["change"] for e in _outbox()] == ["EVIDENCE"]
    # Una antena más leve y posterior no baja el peor estado ni adelanta la primera anomalía.
    _ok(_anomalia(antenna="A015", episode="E2", state="SATURADA", opened_at="2026-11-14T11:00:00.000Z"))
    meta = _meta(existente)
    assert meta["worst_antenna_state"] == "CAIDA" and meta["first_anomaly_at"] == "2026-11-14T09:10:00.000Z"
    assert meta["antenna_ids"] == {"A014", ANTENA, "A015"}


def test_anomalia_repetida_no_duplica(aws):
    registro = _anomalia()
    _ok(registro)
    _ok(registro, _anomalia())  # reentrega y otro evento idéntico
    (meta,) = _metas()
    assert len(_items(meta["incident_id"], "LINK#ANTENNA#")) == 1 and len(_outbox()) == 1
    assert len(_items(meta["incident_id"], "HIST#")) == 1


def test_escalada_sube_el_estado_del_vinculo_y_avisa(aws):
    iid = _incidente(1)
    _ok(_anomalia(state="SATURADA"))
    escalada = _anomalia(state="INHABILITADA", reason="ESCALATED")
    _ok(escalada)
    (link,) = _items(iid, "LINK#ANTENNA#")
    assert link["state"] == "INHABILITADA" and _meta(iid)["worst_antenna_state"] == "INHABILITADA"
    assert [e["data"]["change"] for e in _outbox()] == ["EVIDENCE", "EVIDENCE"]
    _ok(escalada, _anomalia(state="CAIDA", reason="ESCALATED"))  # repetida y más leve: nada
    assert len(_outbox()) == 2 and _items(iid, "LINK#ANTENNA#")[0]["state"] == "INHABILITADA"


def test_la_antena_ya_vinculada_no_crea_otro_incidente_si_aparece_un_segundo_de_reportes(aws):
    primero = _incidente(1, service="MOVIL")
    _ok(_anomalia(state="SATURADA"))
    _incidente(2, service="INTERNET")
    _ok(_anomalia(state="CAIDA", reason="ESCALATED"))
    assert _puntero() is None and len(_metas()) == 2
    assert _items(primero, "LINK#ANTENNA#")[0]["state"] == "CAIDA"


def test_carrera_al_crear_vincula_al_incidente_ganador(aws, monkeypatch):
    real, calls = ddb.transact, []

    def carrera(ops):
        calls.append(1)
        if len(calls) == 1:  # otro proceso crea el ANY de la zona justo antes
            _incidente(9, service="ANY", origin="TELEMETRIA")
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    _ok(_anomalia())
    assert len(calls) == 2 and len(_metas()) == 1
    ganador = _puntero()["incident_id"]
    assert ganador == f"I{9:025d}" and _meta(ganador)["antenna_ids"] == {ANTENA}
    assert [e["data"]["change"] for e in _outbox()] == ["EVIDENCE"]


def test_escritura_concurrente_en_el_meta_reintenta_sin_perder_datos(aws, monkeypatch):
    iid = _incidente(1)
    real, calls = ddb.transact, []

    def carrera(ops):
        calls.append(1)
        if len(calls) == 1:  # un reporte se vincula entre la lectura y la escritura
            ddb.table("Incidents").update_item(
                Key={"pk": f"INCIDENT#{iid}", "sk": "META"},
                UpdateExpression="SET updated_at = :u ADD affected_users :one",
                ExpressionAttributeValues={":u": "2026-11-14T09:59:00.000Z", ":one": 1},
            )
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    _ok(_anomalia())
    assert len(calls) == 2
    meta = _meta(iid)
    assert meta["affected_users"] == 11 and meta["evidence_tech"] is True
    (evento,) = _outbox()
    assert evento["data"]["affected_users"] == 11


# --- telemetry.recovered ---

def test_recuperacion_marca_el_vinculo_y_no_cierra_el_incidente(aws):
    iid = _incidente(1)
    _ok(_anomalia(), _anomalia(antenna="A014", episode="E2"))
    _ok(_recuperada())
    links = {x["antenna_id"]: x for x in _items(iid, "LINK#ANTENNA#")}
    assert links[ANTENA]["recovered_at"] == "2026-11-14T10:30:00.000Z" and "recovered_at" not in links["A014"]
    meta = _meta(iid)
    assert meta["tech_recovered"] is False and meta["status"] == "EVALUACION"
    assert _puntero("INTERNET")["incident_id"] == iid

    _ok(_recuperada(antenna="A014", episode="E2"))
    meta = _meta(iid)
    assert meta["tech_recovered"] is True and meta["status"] == "EVALUACION" and meta["version"] == 1
    assert _puntero("INTERNET")["incident_id"] == iid  # la recuperación es evidencia: no cierra
    cambios = [e["data"]["change"] for e in _outbox()]
    assert cambios == ["EVIDENCE", "EVIDENCE", "RECOVERY", "RECOVERY"]
    assert all(e["data"]["milestone"] is None for e in _outbox())
    assert [h["change"] for h in _items(iid, "HIST#")] == cambios
    evidencia = verificadora_de_evidencias.handler({"incident_id": iid, "mode": "antennas"}, None)
    assert evidencia["tech_recovered"] is True


def test_recuperacion_repetida_o_sin_vinculo_no_hace_nada(aws):
    iid = _incidente(1)
    _ok(_anomalia())
    recuperada = _recuperada()
    _ok(recuperada)
    _ok(recuperada, _recuperada(antenna="A020", episode="E9"), _recuperada(zone="Z01"))
    assert len(_outbox()) == 2 and len(_items(iid, "HIST#")) == 2


def test_una_anomalia_nueva_apaga_tech_recovered(aws):
    iid = _incidente(1)
    _ok(_anomalia())
    _ok(_recuperada())
    assert _meta(iid)["tech_recovered"] is True
    _ok(_anomalia(episode="E2"))  # la misma antena vuelve a fallar
    assert _meta(iid)["tech_recovered"] is False and len(_items(iid, "LINK#ANTENNA#")) == 2


# --- telemetry.recurrent ---

def test_recurrencia_marca_sospecha_estructural(aws):
    iid = _incidente(1)
    recurrente = _recurrente()
    _ok(recurrente, _anomalia())  # en el lote se aplica primero la anomalía
    meta = _meta(iid)
    assert meta["structural_suspect"] is True and meta["version"] == 1
    assert [e["data"]["change"] for e in _outbox()] == ["EVIDENCE", "EVIDENCE"]
    _ok(recurrente)  # reentrega
    assert len(_outbox()) == 2


def test_recurrencia_sin_incidente_y_sin_episodio_abierto_se_descarta(aws):
    _incidente(1)  # activo, pero sin esa antena
    _ok(_recurrente())
    assert _outbox() == []


def test_recurrencia_con_episodio_abierto_y_sin_incidente_se_reintenta(aws):
    ddb.table("Telemetry").put_item(Item={
        "pk": f"ANTENNA#{ANTENA}", "sk": "LAST", "type": "ANTENNA_LAST", "antenna_id": ANTENA, "zone_id": ZONA,
        "last_ts": BASE, "open_episode_id": EPISODIO, "open_episode_sk": f"EPISODE#{BASE}#{EPISODIO}",
    })
    registro = _recurrente()
    assert _run(registro) == {"batchItemFailures": [{"itemIdentifier": registro["messageId"]}]}
    assert _outbox() == []


# --- mensajes ---

@pytest.mark.parametrize("data", [
    {}, {"antenna_id": ANTENA, "zone_id": ZONA, "episode_id": EPISODIO, "state": "NORMAL", "opened_at": BASE},
    {"antenna_id": ANTENA, "zone_id": ZONA, "episode_id": EPISODIO, "state": "ROTA", "opened_at": BASE},
    {"antenna_id": ANTENA, "zone_id": ZONA, "episode_id": EPISODIO, "state": "CAIDA", "opened_at": "ayer"},
    {"antenna_id": 13, "zone_id": ZONA, "episode_id": EPISODIO, "state": "CAIDA", "opened_at": BASE},
    {"antenna_id": "A#13", "zone_id": ZONA, "episode_id": EPISODIO, "state": "CAIDA", "opened_at": BASE},
])
def test_anomalia_invalida_se_descarta(aws, data):
    _ok(_record("telemetry.anomaly", data))
    assert _metas() == [] and _outbox() == []


def test_mensajes_mal_formados_o_de_otro_tipo_se_descartan(aws):
    _ok({"messageId": "m1", "body": "no es json"}, {"messageId": "m2", "body": json.dumps({"detail": 5})},
        {"messageId": "m3"}, _record("report.created", {"report_id": "R1"}))
    assert _metas() == [] and _outbox() == []


def test_un_fallo_devuelve_solo_ese_registro(aws, monkeypatch):
    buena, mala = _anomalia(), _anomalia(antenna="A099", episode="E9", zone="Z01")
    real = ddb.transact

    def falla(ops):
        if any("Z01" in json.dumps(op, default=str) for op in ops):
            raise RuntimeError("DynamoDB no disponible")
        return real(ops)

    monkeypatch.setattr(ddb, "transact", falla)
    assert _run(mala, buena) == {"batchItemFailures": [{"itemIdentifier": mala["messageId"]}]}
    assert [m["zone_id"] for m in _metas()] == [ZONA]
