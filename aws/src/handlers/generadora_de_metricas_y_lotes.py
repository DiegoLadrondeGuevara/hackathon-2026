"""GeneradoraDeMetricasYLotes: simulador de antenas, cada minuto.

Lee las antenas del catálogo, genera `gb_per_min` entre 85% y 115% de `nominal_gb`, aplica
`SCENARIO#ACTIVE` si no expiró, escribe `metrics/<fecha>/<HH-MM>.jsonl` en S3 y avisa por ColaMetricas.
Idempotente: el minuto sale del evento programado y los valores se derivan de (minuto, antena), así
que un reintento reescribe el mismo archivo; la clasificadora ignora lecturas ya vistas.
"""
import logging
import os
import random
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key

from common import ddb, ids, jsonutil

log = logging.getLogger()
log.setLevel(logging.INFO)

MIN_PCT, MAX_PCT = 85, 115


def _minute(event):
    """Minuto de la ejecución (el del evento programado si viene; si no, ahora)."""
    moment = None
    raw = event.get("time") if isinstance(event, dict) else None
    if isinstance(raw, str):
        try:
            moment = ids.parse_iso(raw)
        except ValueError:
            moment = None
    moment = moment or ids.parse_iso(ids.now_iso())
    return moment.replace(second=0, microsecond=0)


def _antennas() -> list:
    return ddb.query_all(
        "NetworkCatalog", IndexName="GSI1-type", KeyConditionExpression=Key("gsi1pk").eq("TYPE#ANTENNA")
    )


def _overrides() -> dict:
    """Mapa antena -> GB/min del escenario activo; vacío si no hay o ya expiró."""
    key = {"pk": "SCENARIO#ACTIVE", "sk": "META"}
    item = ddb.table("NetworkCatalog").get_item(Key=key).get("Item")
    if not item:
        return {}
    try:
        expired = ids.parse_iso(item["expires_at"]) <= ids.parse_iso(ids.now_iso())
    except (KeyError, TypeError, ValueError, AttributeError):
        expired = True
    if expired:
        return {}
    overrides = item.get("overrides") or {}
    return {a: v for a, v in overrides.items() if isinstance(v, Decimal) and v >= 0}


def _simulated(antenna: dict, ts: str) -> Decimal:
    nominal = int(antenna["nominal_gb"])
    rng = random.Random(f"{ts}#{antenna['antenna_id']}")
    return Decimal(rng.randint(nominal * MIN_PCT, nominal * MAX_PCT)) / 100


def handler(event, context):
    minute = _minute(event)
    ts = ids.to_iso(minute)
    antennas = _antennas()
    if not antennas:
        log.warning("no hay antenas en el catálogo: no se genera el lote")
        return {"key": None, "antennas": 0, "overrides": 0}

    overrides = _overrides()
    lines, applied = [], 0
    for antenna in sorted(antennas, key=lambda a: a["antenna_id"]):
        antenna_id = antenna["antenna_id"]
        if antenna_id in overrides:
            gb, applied = overrides[antenna_id], applied + 1
        else:
            gb = _simulated(antenna, ts)
        lines.append(jsonutil.dumps({"antenna_id": antenna_id, "ts": ts, "gb_per_min": gb}))

    bucket = os.environ["METRICS_BUCKET"]
    key = f"metrics/{minute:%Y-%m-%d}/{minute:%H-%M}.jsonl"
    boto3.client("s3").put_object(
        Bucket=bucket, Key=key, Body=("\n".join(lines) + "\n").encode("utf-8"), ContentType="application/x-ndjson"
    )
    boto3.client("sqs").send_message(
        QueueUrl=os.environ["QUEUE_METRICAS_URL"], MessageBody=jsonutil.dumps({"bucket": bucket, "key": key})
    )
    log.info("lote %s: %d antenas, %d con escenario", key, len(lines), applied)
    return {"key": key, "antennas": len(lines), "overrides": applied}
