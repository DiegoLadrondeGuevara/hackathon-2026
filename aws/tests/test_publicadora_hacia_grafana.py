"""PublicadoraHaciaGrafana: métricas de AWS hacia Grafana Cloud (OTLP/HTTP JSON)."""
import base64
import json

import boto3
import pytest

from common import ddb, outbound
from handlers import publicadora_hacia_grafana as grafana

ENDPOINT = "https://otlp.example.net/otlp"
INSTANCIA = "1234567"
TOKEN = "glc_token-secreto"


@pytest.fixture
def configured(aws):
    ssm = boto3.client("ssm")
    ssm.put_parameter(Name="/red-telecorp/test/grafana/otlp_endpoint", Value=ENDPOINT, Type="String")
    ssm.put_parameter(Name="/red-telecorp/test/grafana/instance_id", Value=INSTANCIA, Type="String")
    ssm.put_parameter(Name="/red-telecorp/test/grafana/token", Value=TOKEN, Type="SecureString")


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake(url, body, headers=None, timeout=10):
        calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        return {}

    monkeypatch.setattr(outbound, "post_json", fake)
    return calls


def _datos():
    sqs = boto3.client("sqs")
    for name in ("ColaGCP", "ColaGCP-dlq", "ColaReportes", "ColaReportes-dlq", "OutboxStream-dlq"):
        sqs.create_queue(QueueName=f"red-telecorp-test-{name}")
    url = sqs.get_queue_url(QueueName="red-telecorp-test-ColaGCP-dlq")["QueueUrl"]
    for _ in range(3):
        sqs.send_message(QueueUrl=url, MessageBody="x")
    reportes = sqs.get_queue_url(QueueName="red-telecorp-test-ColaReportes")["QueueUrl"]
    sqs.send_message(QueueUrl=reportes, MessageBody="y")
    sqs.create_queue(QueueName="otro-proyecto-Cola")  # otra cola de la cuenta: no debe aparecer

    inc = ddb.table("Incidents")
    for n, (status, priority) in enumerate([("EVALUACION", "P3"), ("CONFIRMADO", "P1"), ("CONFIRMADO", "P1"),
                                            ("CERRADO", "P2")]):
        iid = f"I{n}"
        inc.put_item(Item={"pk": f"INCIDENT#{iid}", "sk": "META", "type": "INCIDENT_META", "incident_id": iid,
                           "status": status, "priority": priority, "gsi1pk": "ZONE#Z01", "gsi1sk": f"t#{iid}",
                           "gsi2pk": f"STATUS#{status}", "gsi2sk": f"{priority}#t#{iid}"})
    # Un vínculo con datos personales en la misma partición: no debe contarse ni viajar.
    inc.put_item(Item={"pk": "INCIDENT#I0", "sk": "LINK#USER#70000001", "type": "LINK_USER", "customer_id": "70000001"})

    for zid in ("Z01", "Z02"):
        ddb.table("NetworkCatalog").put_item(Item={"pk": f"ZONE#{zid}", "sk": "META", "type": "ZONE", "zone_id": zid,
                                                   "name": zid, "gsi1pk": "TYPE#ZONE", "gsi1sk": zid})
    for n, zid in enumerate(("Z02", "Z02")):
        ddb.table("Telemetry").put_item(Item={
            "pk": f"ANTENNA#A00{n}", "sk": f"EPISODE#t#E{n}", "type": "EPISODE", "antenna_id": f"A00{n}",
            "zone_id": zid, "status": "OPEN", "gsi1pk": f"ZONE#{zid}", "gsi1sk": f"t#A00{n}",
            "gsi2pk": f"OPEN#{zid}", "gsi2sk": f"t#A00{n}"})


def _metric(payload, name):
    metrics = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
    (m,) = [m for m in metrics if m["name"] == name]
    return {tuple(sorted((a["key"], a["value"]["stringValue"]) for a in p["attributes"])): int(p["asInt"])
            for p in m["gauge"]["dataPoints"]}


def test_envia_las_metricas_con_autenticacion_basic(configured, sent):
    _datos()
    assert grafana.handler({}, None)["published"] is True
    (call,) = sent
    assert call["url"] == ENDPOINT + "/v1/metrics"
    assert call["headers"] == {"Authorization": "Basic " + base64.b64encode(f"{INSTANCIA}:{TOKEN}".encode()).decode()}
    assert call["timeout"] == grafana.SEND_TIMEOUT
    resource = call["body"]["resourceMetrics"][0]["resource"]["attributes"]
    assert {"key": "service.name", "value": {"stringValue": "red-telecorp-aws"}} in resource


def test_metricas_de_colas_y_dlq(configured, sent):
    _datos()
    grafana.handler({}, None)
    body = sent[0]["body"]
    colas = _metric(body, "redtelecorp.aws.queue.messages")
    assert colas[(("queue", "ColaReportes"), ("state", "visible"))] == 1
    assert colas[(("queue", "ColaGCP"), ("state", "visible"))] == 0
    assert not any("dlq" in dict(k)["queue"] for k in colas) and not any("otro" in dict(k)["queue"] for k in colas)
    dlq = _metric(body, "redtelecorp.aws.dlq.messages")
    assert dlq[(("queue", "ColaGCP-dlq"),)] == 3 and dlq[(("queue", "ColaReportes-dlq"),)] == 0
    assert (("queue", "OutboxStream-dlq"),) in dlq


def test_incidentes_por_estado_y_prioridad(configured, sent):
    _datos()
    grafana.handler({}, None)
    inc = _metric(sent[0]["body"], "redtelecorp.aws.incidents")
    assert inc[(("priority", "P1"), ("status", "CONFIRMADO"))] == 2
    assert inc[(("priority", "P3"), ("status", "EVALUACION"))] == 1
    assert inc[(("priority", "P2"), ("status", "CERRADO"))] == 1
    assert inc[(("priority", "P1"), ("status", "EVALUACION"))] == 0
    assert len(inc) == 12  # 4 estados x 3 prioridades


def test_episodios_abiertos_por_zona(configured, sent):
    _datos()
    grafana.handler({}, None)
    ep = _metric(sent[0]["body"], "redtelecorp.aws.antenna.open_episodes")
    assert ep == {(("zone", "Z01"),): 0, (("zone", "Z02"),): 2}


def test_el_payload_no_lleva_datos_personales(configured, sent):
    _datos()
    grafana.handler({}, None)
    texto = json.dumps(sent[0]["body"])
    assert "70000001" not in texto and "customer" not in texto and TOKEN not in texto and INSTANCIA not in texto


def test_endpoint_que_ya_termina_en_v1_metrics(configured, sent):
    boto3.client("ssm").put_parameter(Name="/red-telecorp/test/grafana/otlp_endpoint", Value=ENDPOINT + "/v1/metrics/",
                                      Type="String", Overwrite=True)
    grafana.handler({}, None)
    assert sent[0]["url"] == ENDPOINT + "/v1/metrics"


def test_sin_datos_envia_solo_las_metricas_con_puntos(configured, sent):
    assert grafana.handler({}, None)["published"] is True
    names = [m["name"] for m in sent[0]["body"]["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]]
    assert "redtelecorp.aws.queue.messages" not in names and "redtelecorp.aws.incidents" in names


def test_sin_configurar_no_envia_ni_falla(aws, sent):
    assert grafana.handler({}, None) == {"published": False, "reason": "not_configured"}
    assert sent == []


def test_parametros_pendiente_no_envian(aws, sent):
    ssm = boto3.client("ssm")
    for key, kind in (("otlp_endpoint", "String"), ("instance_id", "String"), ("token", "SecureString")):
        ssm.put_parameter(Name=f"/red-telecorp/test/grafana/{key}", Value="PENDIENTE", Type=kind)
    assert grafana.handler({}, None)["reason"] == "not_configured"
    assert sent == []


def test_un_fallo_de_grafana_no_lanza_ni_filtra_la_clave(configured, monkeypatch, caplog):
    _datos()

    def falla(*args, **kwargs):
        raise outbound.OutboundError("Fallo del servicio externo")

    monkeypatch.setattr(outbound, "post_json", falla)
    with caplog.at_level("INFO"):
        assert grafana.handler({}, None) == {"published": False, "reason": "error"}
    assert TOKEN not in caplog.text and INSTANCIA not in caplog.text
