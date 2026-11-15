"""T07: correlacionadora_de_reportes (incidente colectivo)."""
import json

from boto3.dynamodb.conditions import Key

from common import ddb, ids
from handlers import correlacionadora_de_reportes as corr

ZONA = "Z05"
GRUPO = f"GROUP#{ZONA}#INTERNET"
BASE = "2026-11-14T10:00:00.000Z"


def _zona(zone_id=ZONA, zone_type="EDUCATIVA", criticality=3):
    ddb.table("NetworkCatalog").put_item(Item={
        "pk": f"ZONE#{zone_id}", "sk": "META", "type": "ZONE", "zone_id": zone_id, "name": "La Molina",
        "zone_type": zone_type, "criticality": criticality, "est_users": 1000,
        "gsi1pk": "TYPE#ZONE", "gsi1sk": zone_id,
    })


def _reporte(n: int, customer: str | None = None, zone=ZONA, service="INTERNET", at: str | None = None) -> dict:
    """Crea el REPORT_META y devuelve el `data` de su `report.created`."""
    rid = f"R{n:025d}"
    customer = customer or f"7000{n:04d}"
    at = at or ids.shift_iso(BASE, minutes=n)
    ddb.table("Reports").put_item(Item={
        "pk": f"REPORT#{rid}", "sk": "META", "type": "REPORT_META", "report_id": rid, "customer_id": customer,
        "zone_id": zone, "service": service, "problem_type": "SIN_INTERNET", "status": "REGISTRADA",
        "created_at": at, "updated_at": at, "version": 1,
    })
    return {"report_id": rid, "customer_id": customer, "zone_id": zone, "service": service,
            "problem_type": "SIN_INTERNET", "created_at": at}


def _record(data: dict, event_type="report.created", message_id=None) -> dict:
    envelope = {"event_id": ids.new_id(), "type": event_type, "version": 1, "occurred_at": BASE, "data": data}
    body = {"source": "red-telecorp", "detail-type": event_type, "detail": envelope}
    return {"messageId": message_id or f"m-{data.get('report_id')}", "body": json.dumps(body)}


def _run(*datas) -> dict:
    return corr.handler({"Records": [_record(d) for d in datas]}, None)


def _outbox(event_type=None) -> list:
    items = [json.loads(i["detail"]) for i in ddb.table("Outbox").scan()["Items"]]
    return [e for e in items if event_type in (None, e["type"])]


def _incidentes() -> list:
    return [i for i in ddb.table("Incidents").scan()["Items"] if i["type"] == "INCIDENT_META"]


def _items(incident_id: str, prefix: str) -> list:
    return ddb.query_all(
        "Incidents", KeyConditionExpression=Key("pk").eq(f"INCIDENT#{incident_id}") & Key("sk").begins_with(prefix)
    )


def _puntero(group=GRUPO):
    return ddb.table("CorrelationMembers").get_item(Key={"pk": group, "sk": "ACTIVE_INCIDENT"}).get("Item")


def _report_meta(rid: str) -> dict:
    return ddb.table("Reports").get_item(Key={"pk": f"REPORT#{rid}", "sk": "META"})["Item"]


def _incidente_existente(incident_id="I0000000000000000000000001", group=GRUPO, service="INTERNET",
                         origin="REPORTES", evidence_users=True, affected_users=0, opened_at=BASE) -> str:
    ddb.table("Incidents").put_item(Item={
        "pk": f"INCIDENT#{incident_id}", "sk": "META", "type": "INCIDENT_META", "incident_id": incident_id,
        "origin": origin, "zone_id": ZONA, "service": service, "status": "EVALUACION", "priority": "P3",
        "priority_score": 3, "affected_users": affected_users, "report_count": affected_users,
        "evidence_users": evidence_users, "evidence_tech": origin == "TELEMETRIA", "opened_at": opened_at,
        "updated_at": opened_at, "version": 1,
    })
    ddb.table("CorrelationMembers").put_item(Item={
        "pk": group, "sk": "ACTIVE_INCIDENT", "type": "ACTIVE_INCIDENT", "incident_id": incident_id,
        "opened_at": opened_at,
    })
    return incident_id


def test_nueve_clientes_no_crean_incidente(aws):
    _zona()
    assert _run(*[_reporte(n) for n in range(1, 10)]) == {"batchItemFailures": []}
    assert _incidentes() == [] and _puntero() is None and _outbox() == []
    miembro = ddb.table("CorrelationMembers").get_item(Key={"pk": GRUPO, "sk": "MEMBER#70000001"})["Item"]
    at = ids.shift_iso(BASE, minutes=1)
    assert miembro["window_started_at"] == at and miembro["last_reported_at"] == at
    assert miembro["report_ids"] == {f"R{1:025d}"} and miembro["ttl"] == ids.epoch(at) + 48 * 3600


def test_el_decimo_cliente_crea_el_incidente_y_vincula_la_ventana(aws):
    _zona()
    datos = [_reporte(n) for n in range(1, 11)]
    assert _run(*datos) == {"batchItemFailures": []}

    (meta,) = _incidentes()
    iid = meta["incident_id"]
    assert meta["origin"] == "REPORTES" and meta["status"] == "EVALUACION" and meta["service"] == "INTERNET"
    assert meta["zone_id"] == ZONA and meta["detected_by"] == "USUARIOS" and meta["evidence_users"] is True
    assert meta["affected_users"] == 10 and meta["report_count"] == 10 and meta["version"] == 1
    assert meta["first_report_at"] == ids.shift_iso(BASE, minutes=1)
    assert (meta["priority_score"], meta["priority"]) == (5, "P3")  # 2*1 usuarios + criticidad 3
    assert meta["gsi1pk"] == f"ZONE#{ZONA}" and meta["gsi1sk"] == f"{meta['opened_at']}#{iid}"
    assert meta["gsi2pk"] == "STATUS#EVALUACION" and meta["gsi2sk"] == f"P3#{meta['opened_at']}#{iid}"
    assert _puntero()["incident_id"] == iid

    assert len(_items(iid, "LINK#REPORT#")) == 10 and len(_items(iid, "LINK#USER#")) == 10
    (hist,) = _items(iid, "HIST#")
    assert hist["change"] == "CREATED" and hist["to_status"] == "EVALUACION" and hist["from_status"] is None
    assert all(_report_meta(d["report_id"])["incident_id"] == iid for d in datos)

    (creado,) = _outbox("incident.updated")
    assert creado["data"] == {
        "incident_id": iid, "zone_id": ZONA, "service": "INTERNET", "status": "EVALUACION", "priority": "P3",
        "milestone": "EVALUACION", "change": "CREATED", "affected_users": 0, "updated_at": meta["opened_at"],
    }
    vinculados = _outbox("report.linked")
    assert len(vinculados) == 10
    assert {e["data"]["report_id"] for e in vinculados} == {d["report_id"] for d in datos}
    assert all(e["data"]["incident_status"] == "EVALUACION" and e["data"]["incident_id"] == iid for e in vinculados)


def test_el_mismo_cliente_diez_veces_no_cuenta(aws):
    _zona()
    _run(*[_reporte(n, customer="70000001") for n in range(1, 11)])
    assert _incidentes() == []
    miembro = ddb.table("CorrelationMembers").get_item(Key={"pk": GRUPO, "sk": "MEMBER#70000001"})["Item"]
    assert len(miembro["report_ids"]) == 10 and miembro["window_started_at"] == ids.shift_iso(BASE, minutes=1)


def test_otro_servicio_u_otra_zona_no_suman(aws):
    _zona()
    _zona("Z06", "INDUSTRIAL", 2)
    datos = [_reporte(n) for n in range(1, 9)]
    datos += [_reporte(9, service="MOVIL"), _reporte(10, zone="Z06")]
    _run(*datos)
    assert _incidentes() == []


def test_duplicado_no_repite_nada(aws):
    _zona()
    datos = [_reporte(n) for n in range(1, 11)]
    _run(*datos)
    eventos = len(_outbox())
    assert _run(*datos) == {"batchItemFailures": []}  # SQS entrega otra vez todo el lote
    (meta,) = _incidentes()
    assert meta["affected_users"] == 10 and meta["report_count"] == 10
    assert len(_outbox()) == eventos and len(_items(meta["incident_id"], "LINK#")) == 20


def test_reportes_posteriores_se_vinculan_sin_evento_de_incidente(aws):
    _zona()
    _run(*[_reporte(n) for n in range(1, 11)])
    _run(_reporte(11), _reporte(12, customer="70000001"))  # cliente nuevo y cliente ya vinculado
    (meta,) = _incidentes()
    assert meta["affected_users"] == 11 and meta["report_count"] == 12
    assert len(_outbox("incident.updated")) == 1 and len(_outbox("report.linked")) == 12
    assert len(_items(meta["incident_id"], "LINK#USER#")) == 11


def test_carrera_con_puntero_existente_vincula(aws, monkeypatch):
    """Otro proceso crea el incidente entre el conteo y la transacción: se vincula al suyo."""
    _zona()
    _run(*[_reporte(n) for n in range(1, 10)])
    real, calls = ddb.transact, []

    def carrera(ops):
        calls.append(1)
        if len(calls) == 1:
            _incidente_existente("IGANADOR000000000000000001", opened_at=ids.now_iso())
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    assert _run(_reporte(10)) == {"batchItemFailures": []}

    (meta,) = _incidentes()
    assert meta["incident_id"] == "IGANADOR000000000000000001" == _puntero()["incident_id"]
    assert meta["affected_users"] == 10 and meta["report_count"] == 10
    assert len(_outbox("report.linked")) == 10 and _outbox("incident.updated") == []


def test_reintento_tras_fallo_a_medias_completa_la_ventana(aws, monkeypatch):
    _zona()
    datos = [_reporte(n) for n in range(1, 11)]
    _run(*datos[:9])
    real, calls = ddb.transact, []

    def falla_al_cuarto(ops):
        calls.append(1)
        if len(calls) == 4:  # creación + 2 vínculos correctos
            raise RuntimeError("corte simulado")
        return real(ops)

    monkeypatch.setattr(ddb, "transact", falla_al_cuarto)
    assert _run(datos[9]) == {"batchItemFailures": [{"itemIdentifier": f"m-{datos[9]['report_id']}"}]}
    assert _incidentes()[0]["report_count"] == 2

    monkeypatch.setattr(ddb, "transact", real)
    assert _run(datos[9]) == {"batchItemFailures": []}
    (meta,) = _incidentes()
    assert meta["affected_users"] == 10 and meta["report_count"] == 10
    assert len(_outbox("incident.updated")) == 1 and len(_outbox("report.linked")) == 10


def test_puntero_any_recibe_el_reporte_y_emite_evidencia(aws):
    _zona()
    iid = _incidente_existente(group=f"GROUP#{ZONA}#ANY", service="ANY", origin="TELEMETRIA", evidence_users=False)
    _run(_reporte(1), _reporte(2))
    meta = _incidentes()[0]
    assert meta["evidence_users"] is True and meta["affected_users"] == 2 and meta["report_count"] == 2
    (evento,) = _outbox("incident.updated")  # solo el primer usuario emite EVIDENCE
    assert evento["data"]["change"] == "EVIDENCE" and evento["data"]["milestone"] is None
    assert evento["data"]["affected_users"] == 1 and evento["data"]["service"] == "ANY"
    assert [h["change"] for h in _items(iid, "HIST#")] == ["EVIDENCE"]
    assert _puntero() is None  # no se crea puntero de INTERNET


def test_cruce_de_umbral_emite_threshold(aws):
    _zona()
    _incidente_existente(affected_users=99)
    _run(_reporte(1), _reporte(2))
    assert _incidentes()[0]["affected_users"] == 101
    (evento,) = _outbox("incident.updated")
    assert evento["data"]["change"] == "THRESHOLD" and evento["data"]["affected_users"] == 100


def test_umbral_alcanzado_por_otro_proceso_se_relee(aws, monkeypatch):
    """Se leyó 98, pero al escribir ya hay 99: la condición falla y el reintento emite THRESHOLD."""
    _zona()
    iid = _incidente_existente(affected_users=98)
    real, calls = ddb.transact, []

    def carrera(ops):
        calls.append(1)
        if len(calls) == 1:
            ddb.table("Incidents").update_item(
                Key={"pk": f"INCIDENT#{iid}", "sk": "META"}, UpdateExpression="ADD affected_users :one",
                ExpressionAttributeValues={":one": 1},
            )
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    _run(_reporte(1))
    assert _incidentes()[0]["affected_users"] == 100 and len(calls) == 2
    assert [e["data"]["change"] for e in _outbox("incident.updated")] == ["THRESHOLD"]


def test_miembro_fuera_de_ventana_no_cuenta_y_reinicia(aws):
    _zona()
    viejo = ids.shift_iso(BASE, hours=-25)
    _run(_reporte(1, at=viejo), *[_reporte(n) for n in range(2, 10)])
    _run(_reporte(10, customer="70000002"))  # sigue habiendo solo 8 clientes dentro de 24 h
    assert _incidentes() == []

    _run(_reporte(11, customer="70000001"))  # el cliente antiguo vuelve: ventana nueva, 9 en total
    miembro = ddb.table("CorrelationMembers").get_item(Key={"pk": GRUPO, "sk": "MEMBER#70000001"})["Item"]
    assert miembro["window_started_at"] == ids.shift_iso(BASE, minutes=11)
    assert miembro["report_ids"] == {f"R{11:025d}"}
    assert _incidentes() == []

    _run(_reporte(12))
    (meta,) = _incidentes()
    assert meta["affected_users"] == 10 and meta["first_report_at"] == ids.shift_iso(BASE, minutes=2)
    assert "incident_id" not in _report_meta(f"R{1:025d}")  # el reporte de la ventana vieja no se vincula


def test_report_ids_se_limita_a_veinte(aws):
    _zona()
    _run(*[_reporte(n, customer="70000001") for n in range(1, 24)])
    miembro = ddb.table("CorrelationMembers").get_item(Key={"pk": GRUPO, "sk": "MEMBER#70000001"})["Item"]
    assert miembro["report_ids"] == {f"R{n:025d}" for n in range(4, 24)}


def test_mensajes_invalidos_se_descartan(aws):
    _zona()
    bueno = _reporte(1)
    records = [
        {"messageId": "a", "body": "no es json"},
        {"messageId": "b", "body": json.dumps({"detail": {"type": "report.created", "data": {"report_id": "x"}}})},
        _record({**bueno, "service": "ANY"}, message_id="c"),
        _record({**bueno, "created_at": "ayer"}, message_id="d"),
        _record(bueno, event_type="report.linked", message_id="e"),
        _record(bueno, message_id="f"),
    ]
    assert corr.handler({"Records": records}, None) == {"batchItemFailures": []}
    miembros = ddb.query_all("CorrelationMembers", KeyConditionExpression=Key("pk").eq(GRUPO))
    assert len(miembros) == 1


def test_reporte_inexistente_se_descarta(aws):
    _zona()
    _incidente_existente()
    fantasma = {"report_id": "RNOEXISTE", "customer_id": "70000001", "zone_id": ZONA, "service": "INTERNET",
                "created_at": ids.shift_iso(BASE, minutes=1)}
    assert _run(fantasma) == {"batchItemFailures": []}
    assert _incidentes()[0]["report_count"] == 0 and _outbox() == []
    assert "Item" not in ddb.table("Reports").get_item(Key={"pk": "REPORT#RNOEXISTE", "sk": "META"})


def test_fallo_parcial_del_lote_solo_reporta_el_registro_fallido(aws, monkeypatch):
    _zona()
    _incidente_existente()
    uno, dos = _reporte(1), _reporte(2)
    real = corr._link

    def falla(incident_id, report_id, customer_id):
        if report_id == dos["report_id"]:
            raise RuntimeError("corte simulado")
        return real(incident_id, report_id, customer_id)

    monkeypatch.setattr(corr, "_link", falla)
    assert _run(uno, dos) == {"batchItemFailures": [{"itemIdentifier": f"m-{dos['report_id']}"}]}
    assert _incidentes()[0]["report_count"] == 1
