"""T08: verificadora_de_evidencias, calculadora_de_prioridad y alertadora_de_operaciones."""
import json

import boto3
import pytest
from boto3.dynamodb.conditions import Key

from common import ddb
from handlers import alertadora_de_operaciones as alertadora
from handlers import calculadora_de_prioridad as calculadora
from handlers import verificadora_de_evidencias as verificadora

IID = "I0000000000000000000000001"
PK = f"INCIDENT#{IID}"
ABIERTO = "2026-11-14T10:00:00.000Z"


def _zona(zone_id="Z05", criticality=3):
    ddb.table("NetworkCatalog").put_item(Item={
        "pk": f"ZONE#{zone_id}", "sk": "META", "type": "ZONE", "zone_id": zone_id, "criticality": criticality,
    })


def _incidente(zone_id="Z05", status="EVALUACION", priority="P3", score=5, **extra) -> dict:
    item = {
        "pk": PK, "sk": "META", "type": "INCIDENT_META", "incident_id": IID, "origin": "REPORTES",
        "zone_id": zone_id, "service": "INTERNET", "status": status, "priority": priority, "priority_score": score,
        "affected_users": 0, "report_count": 0, "evidence_users": True, "evidence_tech": False,
        "tech_recovered": False, "structural_suspect": False, "review_required": False, "detected_by": "USUARIOS",
        "opened_at": ABIERTO, "updated_at": ABIERTO, "version": 1,
        "gsi1pk": f"ZONE#{zone_id}", "gsi1sk": f"{ABIERTO}#{IID}",
        "gsi2pk": f"STATUS#{status}", "gsi2sk": f"{priority}#{ABIERTO}#{IID}",
        **extra,
    }
    ddb.table("Incidents").put_item(Item=item)
    return item


def _usuarios(n: int, first_at="2026-11-14T09:30:00.000Z"):
    for i in range(1, n + 1):
        rid, customer = f"R{i:025d}", f"7000{i:04d}"
        ddb.table("Incidents").put_item(Item={"pk": PK, "sk": f"LINK#REPORT#{rid}", "type": "LINK_REPORT",
                                              "report_id": rid, "customer_id": customer, "linked_at": ABIERTO})
        ddb.table("Incidents").put_item(Item={"pk": PK, "sk": f"LINK#USER#{customer}", "type": "LINK_USER",
                                              "customer_id": customer, "first_report_id": rid, "linked_at": ABIERTO})
    ddb.table("Incidents").update_item(
        Key={"pk": PK, "sk": "META"}, UpdateExpression="SET affected_users = :n, report_count = :n",
        ExpressionAttributeValues={":n": n},
    )
    ddb.table("Reports").put_item(Item={"pk": f"REPORT#R{1:025d}", "sk": "META", "created_at": first_at})


def _antena(antenna_id, state, episode="E1", linked_at="2026-11-14T10:05:00.000Z", recovered_at=None):
    item = {"pk": PK, "sk": f"LINK#ANTENNA#{antenna_id}#{episode}", "type": "LINK_ANTENNA",
            "antenna_id": antenna_id, "episode_id": episode, "state": state, "linked_at": linked_at}
    if recovered_at:
        item["recovered_at"] = recovered_at
    ddb.table("Incidents").put_item(Item=item)


def _meta() -> dict:
    return ddb.table("Incidents").get_item(Key={"pk": PK, "sk": "META"})["Item"]


def _hist() -> list:
    return ddb.query_all("Incidents", KeyConditionExpression=Key("pk").eq(PK) & Key("sk").begins_with("HIST#"))


def _outbox() -> list:
    return [json.loads(i["detail"]) for i in ddb.table("Outbox").scan()["Items"]]


def _verificar() -> list:
    """Las dos ramas del Parallel, con la forma que recibe CalcularPrioridad."""
    return [verificadora.handler({"incident_id": IID, "mode": mode}, None) for mode in ("users", "antennas")]


def _calcular(evidence=None) -> dict:
    return calculadora.handler({"incident_id": IID, "evidence": _verificar() if evidence is None else evidence}, None)


# --- verificadora_de_evidencias ---

def test_evidencias_de_usuarios(aws):
    _incidente(first_report_at="2026-11-14T09:40:00.000Z")
    _usuarios(12)
    assert verificadora.handler({"incident_id": IID, "mode": "users"}, None) == {
        "evidence_users": True, "affected_users": 12, "report_count": 12,
        "first_report_at": "2026-11-14T09:30:00.000Z",  # el reporte más antiguo gana al valor del META
    }


def test_evidencias_de_antenas(aws):
    _incidente(first_anomaly_at="2026-11-14T09:50:00.000Z")
    _antena("A013", "SATURADA", recovered_at="2026-11-14T10:20:00.000Z")
    _antena("A014", "INHABILITADA")
    assert verificadora.handler({"incident_id": IID, "mode": "antennas"}, None) == {
        "evidence_tech": True, "antenna_ids": ["A013", "A014"], "worst_antenna_state": "INHABILITADA",
        "first_anomaly_at": "2026-11-14T09:50:00.000Z", "tech_recovered": False,
    }
    _antena("A014", "INHABILITADA", recovered_at="2026-11-14T10:30:00.000Z")
    assert verificadora.handler({"incident_id": IID, "mode": "antennas"}, None)["tech_recovered"] is True


def test_sin_evidencias_y_resultado_serializable(aws):
    _incidente()
    users, antennas = _verificar()
    assert users == {"evidence_users": False, "affected_users": 0, "report_count": 0, "first_report_at": None}
    assert antennas == {"evidence_tech": False, "antenna_ids": [], "worst_antenna_state": None,
                        "first_anomaly_at": None, "tech_recovered": False}
    json.dumps([users, antennas])  # Lambda serializa la respuesta con json estándar


def test_verificadora_es_de_solo_lectura(aws):
    antes = _incidente()
    _usuarios(3)
    antes = _meta()
    _verificar()
    assert _meta() == antes and _outbox() == []


@pytest.mark.parametrize("event", [{"mode": "users"}, {"incident_id": IID, "mode": "todo"}, {"incident_id": IID}])
def test_verificadora_entrada_invalida(aws, event):
    _incidente()
    with pytest.raises(ValueError):
        verificadora.handler(event, None)


def test_verificadora_incidente_inexistente(aws):
    with pytest.raises(ValueError):
        verificadora.handler({"incident_id": "NOEXISTE", "mode": "users"}, None)


# --- calculadora_de_prioridad ---

def test_solo_usuarios_sigue_en_evaluacion_sin_eventos(aws):
    _zona()
    _incidente()
    _usuarios(10)
    assert _calcular() == {"priority": "P3", "priority_changed": False, "status_changed": False, "alert": False}
    meta = _meta()
    assert meta["status"] == "EVALUACION" and meta["priority_score"] == 5 and meta["version"] == 2
    assert meta["recommended_action"] == "Verificar infraestructura de la zona"
    assert meta["first_report_at"] == "2026-11-14T09:30:00.000Z" and meta["detected_by"] == "USUARIOS"
    assert _outbox() == [] and _hist() == []


def test_evidencia_tecnica_confirma_solo(aws):
    _zona()
    _incidente()
    _usuarios(10)
    _antena("A013", "CAIDA", linked_at="2026-11-14T09:20:00.000Z")
    # 2*1 (usuarios) + 2*2 (CAIDA) + 3 (criticidad) = 9 -> P2
    assert _calcular() == {"priority": "P2", "priority_changed": True, "status_changed": True, "alert": True}

    meta = _meta()
    assert meta["status"] == "CONFIRMADO" and meta["priority"] == "P2" and meta["priority_score"] == 9
    assert meta["evidence_tech"] is True and meta["worst_antenna_state"] == "CAIDA" and meta["version"] == 2
    assert meta["confirmed_at"] == meta["updated_at"]
    assert meta["gsi2pk"] == "STATUS#CONFIRMADO" and meta["gsi2sk"] == f"P2#{ABIERTO}#{IID}"
    assert meta["detected_by"] == "ANTENA" and meta["detection_lag_seconds"] == 600
    assert "recommended_action" not in meta
    assert meta["affected_users"] == 10  # los contadores son de quien vincula

    (hist,) = _hist()
    assert (hist["from_status"], hist["to_status"], hist["change"]) == ("EVALUACION", "CONFIRMADO", "STATUS")
    assert hist["actor"] == "SYSTEM#CalculadoraDePrioridad"
    (evento,) = _outbox()
    assert evento["type"] == "incident.updated" and evento["data"] == {
        "incident_id": IID, "zone_id": "Z05", "service": "INTERNET", "status": "CONFIRMADO", "priority": "P2",
        "milestone": "CONFIRMADO", "change": "STATUS", "affected_users": 10, "updated_at": meta["updated_at"],
    }


def test_repetir_la_ejecucion_no_cambia_nada(aws):
    _zona()
    _incidente()
    _usuarios(10)
    _antena("A013", "CAIDA")
    _calcular()
    meta = _meta()
    assert _calcular() == {"priority": "P2", "priority_changed": False, "status_changed": False, "alert": False}
    assert _meta() == meta and len(_outbox()) == 1 and len(_hist()) == 1


def test_solo_cambia_la_prioridad_emite_priority(aws):
    _zona()
    _incidente(status="CONFIRMADO", evidence_tech=True, worst_antenna_state="SATURADA", priority="P3", score=5)
    _usuarios(10)
    _antena("A013", "INHABILITADA")
    # 2*1 + 2*3 + 3 = 11 -> P1
    assert _calcular() == {"priority": "P1", "priority_changed": True, "status_changed": False, "alert": True}
    meta = _meta()
    assert meta["status"] == "CONFIRMADO" and meta["gsi2sk"] == f"P1#{ABIERTO}#{IID}"
    (evento,) = _outbox()
    assert evento["data"]["change"] == "PRIORITY" and evento["data"]["milestone"] is None
    assert evento["data"]["priority"] == "P1"
    (hist,) = _hist()
    assert hist["change"] == "PRIORITY" and hist["from_status"] == hist["to_status"] == "CONFIRMADO"
    # P1 sigue alertando aunque ya no cambie nada
    assert _calcular() == {"priority": "P1", "priority_changed": False, "status_changed": False, "alert": True}


def test_review_required_alerta(aws):
    _zona()
    _incidente(review_required=True)
    assert _calcular()["alert"] is True


def test_recuperacion_tecnica_recomienda_pero_no_restablece(aws):
    _zona()
    _incidente(status="CONFIRMADO", evidence_tech=True, worst_antenna_state="CAIDA", priority="P2", score=9)
    _usuarios(10)
    _antena("A013", "CAIDA", recovered_at="2026-11-14T10:40:00.000Z")
    resultado = _calcular()
    assert resultado["status_changed"] is False and resultado["priority"] == "P2"
    meta = _meta()
    assert meta["status"] == "CONFIRMADO" and meta["tech_recovered"] is True
    assert meta["recommended_action"] == "Evaluar restablecimiento" and "restored_at" not in meta
    assert _outbox() == []


def test_sospecha_estructural(aws):
    _zona()
    _incidente(structural_suspect=True)
    _calcular()
    assert _meta()["recommended_action"] == "Revisión estructural de la antena"


def test_incidente_cerrado_no_se_recalcula(aws):
    _zona()
    antes = _incidente(status="CERRADO")
    _antena("A013", "INHABILITADA")
    assert _calcular() == {"priority": "P3", "priority_changed": False, "status_changed": False, "alert": False}
    assert _meta() == antes and _outbox() == []


def _bump_version():
    ddb.table("Incidents").update_item(
        Key={"pk": PK, "sk": "META"}, UpdateExpression="SET #v = #v + :one",
        ExpressionAttributeNames={"#v": "version"}, ExpressionAttributeValues={":one": 1},
    )


def test_conflicto_de_version_reintenta(aws, monkeypatch):
    _zona()
    _incidente()
    _antena("A013", "CAIDA")
    evidencia = _verificar()
    real, calls = ddb.transact, []

    def carrera(ops):
        calls.append(1)
        if len(calls) == 1:
            _bump_version()
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    assert _calcular(evidencia)["status_changed"] is True
    assert len(calls) == 2 and _meta()["version"] == 3 and len(_outbox()) == 1


def test_conflicto_persistente_falla_sin_escribir(aws, monkeypatch):
    _zona()
    _incidente()
    _antena("A013", "CAIDA")
    evidencia = _verificar()
    real = ddb.transact

    def carrera(ops):
        _bump_version()
        return real(ops)

    monkeypatch.setattr(ddb, "transact", carrera)
    with pytest.raises(RuntimeError):
        _calcular(evidencia)
    assert _meta()["status"] == "EVALUACION" and _outbox() == []


def test_calculadora_entrada_invalida(aws):
    with pytest.raises(ValueError):
        calculadora.handler({"evidence": []}, None)
    with pytest.raises(ValueError):
        calculadora.handler({"incident_id": "NOEXISTE", "evidence": []}, None)


# --- alertadora_de_operaciones ---

@pytest.fixture
def alertas(aws, monkeypatch):
    """Tema SNS con una cola suscrita para leer lo publicado."""
    monkeypatch.setattr(alertadora, "_client", None)
    sns, sqs = boto3.client("sns"), boto3.client("sqs")
    topic = sns.create_topic(Name="alertas-operaciones")["TopicArn"]
    monkeypatch.setenv("OPS_TOPIC_ARN", topic)
    url = sqs.create_queue(QueueName="alertas")["QueueUrl"]
    arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=arn)

    def received() -> list:
        msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
        return [json.loads(m["Body"]) for m in msgs]

    return received


def test_alerta_de_incidente(alertas):
    _incidente(status="CONFIRMADO", priority="P1", score=11, antenna_ids={"A014", "A013"}, review_required=True,
               recommended_action="Revisión estructural de la antena")
    _usuarios(2)
    calc = {"priority": "P1", "priority_changed": True, "status_changed": True, "alert": True}
    resp = alertadora.handler({"mode": "incident", "incident_id": IID, "calc": calc}, None)
    assert resp["published"] is True and resp["message_id"]

    (msg,) = alertas()
    assert msg["Subject"] == "[P1] Incidente CONFIRMADO en Z05"
    lines = msg["Message"].splitlines()
    assert f"Incidente: {IID}" in lines and "Zona: Z05" in lines and "Servicio: INTERNET" in lines
    assert "Prioridad: P1" in lines and "Estado: CONFIRMADO" in lines
    assert "Antenas: A013, A014" in lines
    assert "Acción recomendada: Revisión estructural de la antena" in lines
    assert "Clientes afectados: 2" in lines
    assert "7000" not in msg["Message"] and "gsi1pk" not in msg["Message"]  # sin clientes ni claves internas


def test_alerta_de_incidente_sin_antenas_ni_accion(alertas):
    _incidente(status="EVALUACION", priority="P3", score=1)
    alertadora.handler({"mode": "incident", "incident_id": IID}, None)
    (msg,) = alertas()
    assert msg["Subject"] == "[P3] Incidente EVALUACION en Z05"
    assert "Antenas: ninguna" in msg["Message"] and "Acción recomendada: ninguna" in msg["Message"]


def test_alerta_de_falla(alertas):
    error = {"Error": "States.TaskFailed", "Cause": "x" * 2000}
    alertadora.handler({"mode": "failure", "incident_id": IID, "error": error}, None)
    (msg,) = alertas()
    body = json.loads(msg["Message"])
    assert msg["Subject"] == "Fallo al verificar un incidente"
    assert body["kind"] == "VERIFICATION_FAILURE" and body["incident_id"] == IID
    assert body["error"] == "States.TaskFailed" and len(body["cause"]) == 500


def test_alertadora_entrada_invalida(alertas):
    with pytest.raises(ValueError):
        alertadora.handler({"mode": "otro"}, None)
    with pytest.raises(ValueError):
        alertadora.handler({"mode": "incident", "incident_id": "NOEXISTE"}, None)
    assert alertas() == []
