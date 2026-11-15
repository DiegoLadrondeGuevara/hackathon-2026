"""PublicadoraHaciaGrafana: cada 5 minutos envía a Grafana Cloud (OTLP/HTTP JSON) el estado del sistema.

Métricas (gauges, solo conteos: nada de datos personales):
- redtelecorp.aws.queue.messages{queue,state}   mensajes visibles y en vuelo de cada cola
- redtelecorp.aws.dlq.messages{queue}           mensajes en cada cola de mensajes fallidos
- redtelecorp.aws.incidents{status,priority}    incidentes por estado y prioridad
- redtelecorp.aws.antenna.open_episodes{zone}   episodios de antena abiertos por zona
Configuración en SSM: grafana/otlp_endpoint, grafana/instance_id y grafana/token (autenticación Basic).
Es "mejor esfuerzo": un fallo se registra y no se reintenta; nunca afecta al flujo principal.
"""
import base64
import logging
import os
import time

import boto3
from boto3.dynamodb.conditions import Key

from common import config, ddb, domain, outbound

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

SEND_TIMEOUT = 10
PRIORITIES = ("P1", "P2", "P3")
_SQS_ATTRS = ["ApproximateNumberOfMessages", "ApproximateNumberOfMessagesNotVisible"]


def _count(logical: str, **query) -> int:
    """Cuenta ítems de un índice sin leerlos (Select=COUNT), con paginación."""
    table, total = ddb.table(logical), 0
    while True:
        resp = table.query(Select="COUNT", **query)
        total += resp["Count"]
        if not resp.get("LastEvaluatedKey"):
            return total
        query["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


def _queues(stage: str) -> list:
    """[(nombre corto, visibles, en vuelo)] de las colas del stage."""
    sqs, prefix, out = boto3.client("sqs"), f"red-telecorp-{stage}-", []
    for url in sqs.list_queues(QueueNamePrefix=prefix).get("QueueUrls", []):
        attrs = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=_SQS_ATTRS)["Attributes"]
        out.append((url.rsplit("/", 1)[-1][len(prefix):], int(attrs["ApproximateNumberOfMessages"]),
                    int(attrs["ApproximateNumberOfMessagesNotVisible"])))
    return sorted(out)


def _incidents() -> list:
    return [
        (status, priority, _count(
            "Incidents", IndexName="GSI2-queue",
            KeyConditionExpression=Key("gsi2pk").eq(f"STATUS#{status}") & Key("gsi2sk").begins_with(f"{priority}#"),
        ))
        for status in sorted(domain.INCIDENT_TRANSITIONS) for priority in PRIORITIES
    ]


def _open_episodes() -> list:
    zones = ddb.query_all("NetworkCatalog", IndexName="GSI1-type", KeyConditionExpression=Key("gsi1pk").eq("TYPE#ZONE"))
    return [
        (z["zone_id"], _count("Telemetry", IndexName="GSI2-open",
                              KeyConditionExpression=Key("gsi2pk").eq(f"OPEN#{z['zone_id']}")))
        for z in sorted(zones, key=lambda z: z["zone_id"])
    ]


def _attrs(**values) -> list:
    return [{"key": k, "value": {"stringValue": str(v)}} for k, v in values.items()]


def build_payload(queues: list, incidents: list, episodes: list, stage: str, now_ns: int | None = None) -> dict:
    now = str(now_ns if now_ns is not None else time.time_ns())

    def point(value, **attributes):
        return {"timeUnixNano": now, "asInt": str(int(value)), "attributes": _attrs(**attributes)}

    def gauge(name, points):
        return {"name": name, "unit": "1", "gauge": {"dataPoints": points}}

    main = [(n, v, f) for n, v, f in queues if not n.endswith("-dlq")]
    dlqs = [(n, v + f) for n, v, f in queues if n.endswith("-dlq")]
    metrics = [
        gauge("redtelecorp.aws.queue.messages",
              [point(v, queue=n, state="visible") for n, v, _ in main]
              + [point(f, queue=n, state="in_flight") for n, _, f in main]),
        gauge("redtelecorp.aws.dlq.messages", [point(total, queue=n) for n, total in dlqs]),
        gauge("redtelecorp.aws.incidents", [point(c, status=s, priority=p) for s, p, c in incidents]),
        gauge("redtelecorp.aws.antenna.open_episodes", [point(c, zone=z) for z, c in episodes]),
    ]
    metrics = [m for m in metrics if m["gauge"]["dataPoints"]]  # algunos receptores rechazan colecciones vacías
    return {"resourceMetrics": [{
        "resource": {"attributes": _attrs(**{"service.name": "red-telecorp-aws", "deployment.environment": stage})},
        "scopeMetrics": [{"scope": {"name": "redtelecorp.aws"}, "metrics": metrics}],
    }]}


def collect(stage: str) -> dict:
    return build_payload(_queues(stage), _incidents(), _open_episodes(), stage)


def _settings():
    names = ("grafana/otlp_endpoint", "grafana/instance_id", "grafana/token")
    endpoint, instance, token = (config.get_secret(k) for k in names)
    if any(not v or v == "PENDIENTE" for v in (endpoint, instance, token)):
        raise ValueError("Grafana no configurado")
    endpoint = endpoint.rstrip("/")
    if not endpoint.endswith("/v1/metrics"):
        endpoint += "/v1/metrics"
    auth = base64.b64encode(f"{instance}:{token}".encode()).decode()
    return endpoint, {"Authorization": "Basic " + auth}


def handler(event, context):
    try:
        endpoint, headers = _settings()
    except Exception:
        log.warning("Grafana sin configurar: no se envían métricas")
        return {"published": False, "reason": "not_configured"}
    try:
        payload = collect(os.environ.get("STAGE", "dev"))
        outbound.post_json(endpoint, payload, headers, timeout=SEND_TIMEOUT)
    except Exception:
        log.warning("No se pudieron enviar las métricas a Grafana")  # sin detalles: la respuesta puede traer datos
        return {"published": False, "reason": "error"}
    points = sum(len(m["gauge"]["dataPoints"]) for m in payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"])
    log.info("métricas enviadas a Grafana: %d puntos", points)
    return {"published": True, "points": points}
