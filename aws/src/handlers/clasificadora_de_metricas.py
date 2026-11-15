"""ClasificadoraDeMetricas: consume los lotes de ColaMetricas. Ver contracts/flows.md.

Mensaje `{"bucket","key"}`; cada línea del archivo es `{"antenna_id","ts","gb_per_min"}`. Por antena y
en orden de `ts` clasifica la lectura, abre, escala o cierra el episodio y actualiza LAST. Cada lectura
va en una transacción (LAST + EPISODE + Outbox) condicionada al `last_ts` leído: un mensaje repetido
o dos ejecuciones a la vez no duplican episodios ni eventos.
"""
import json
import logging
import os
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import ddb, domain, events, ids

log = logging.getLogger()
log.setLevel(logging.INFO)

_ATTEMPTS = 3
_NAMES = {"#state": "state", "#status": "status"}


class InvalidMessage(Exception):
    """Dato inválido: se registra y se descarta, no se reintenta."""


def _parse(record: dict) -> tuple[str, str]:
    try:
        body = json.loads(record["body"])
        bucket, key = body["bucket"], body["key"]
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidMessage("mensaje mal formado") from exc
    if not (isinstance(bucket, str) and bucket and isinstance(key, str) and key.startswith("metrics/")):
        raise InvalidMessage("bucket o key no válidos")
    expected = os.environ.get("METRICS_BUCKET")
    if expected and bucket != expected:
        raise InvalidMessage("el bucket no es el de métricas")
    return bucket, key


def _readings(bucket: str, key: str) -> dict:
    """Lecturas válidas del archivo, agrupadas por antena: {antenna_id: [(ts, gb), ...]}."""
    try:
        raw = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8")
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("NoSuchKey", "NoSuchBucket"):
            raise InvalidMessage(f"el archivo {key} no existe") from exc
        raise
    except UnicodeDecodeError as exc:
        raise InvalidMessage(f"el archivo {key} no es texto UTF-8") from exc

    by_antenna, discarded = {}, 0
    for line in raw.splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line, parse_float=Decimal)
            antenna_id, gb = row["antenna_id"], row["gb_per_min"]
            if not isinstance(antenna_id, str) or not antenna_id:
                raise ValueError("antenna_id")
            if isinstance(gb, bool) or not isinstance(gb, (int, Decimal)):
                raise ValueError("gb_per_min")
            gb = Decimal(gb)
            if not gb.is_finite() or gb < 0:
                raise ValueError("gb_per_min")
            ts = ids.to_iso(ids.parse_iso(row["ts"]))
        except (KeyError, TypeError, ValueError, AttributeError, ArithmeticError):
            discarded += 1
            continue
        by_antenna.setdefault(antenna_id, []).append((ts, gb))
    if discarded:
        log.warning("%s: %d líneas inválidas descartadas", key, discarded)
    return by_antenna


def _zone_of(antenna_id: str) -> str | None:
    key = {"pk": f"ANTENNA#{antenna_id}", "sk": "META"}
    return (ddb.table("NetworkCatalog").get_item(Key=key).get("Item") or {}).get("zone_id")


def _get(pk: str, sk: str) -> dict | None:
    return ddb.table("Telemetry").get_item(Key={"pk": pk, "sk": sk}, ConsistentRead=True).get("Item")


def _episodes_7d(pk: str, ts: str) -> int:
    """Episodios de la antena abiertos en los últimos 7 días (ver contracts/tables.md)."""
    since = ids.shift_iso(ts, days=-domain.RECURRENCE_DAYS)
    return len(ddb.query_all(
        "Telemetry",
        KeyConditionExpression=Key("pk").eq(pk) & Key("sk").between(f"EPISODE#{since}", "EPISODE#~"),
        ConsistentRead=True,
    ))


def _open_episode(pk: str, last: dict) -> dict:
    episode = _get(pk, last["open_episode_sk"])
    if not episode:
        raise RuntimeError(f"LAST apunta a un episodio inexistente: {last.get('open_episode_id')}")
    return episode


def _step_ops(last: dict | None, antenna_id: str, zone_id: str, ts: str, gb: Decimal) -> list:
    """Operaciones de la transacción para una lectura posterior a `last`."""
    pk = f"ANTENNA#{antenna_id}"
    state = domain.classify_gb(gb)
    has_open = bool(last and last.get("open_episode_sk"))
    new_last = {
        "pk": pk, "sk": "LAST", "type": "ANTENNA_LAST", "antenna_id": antenna_id, "zone_id": zone_id,
        "last_ts": ts, "gb_per_min": gb, "state": state, "consecutive_normals": 0, "updated_at": ids.now_iso(),
    }
    keep_open = {"open_episode_id": (last or {}).get("open_episode_id"),
                 "open_episode_sk": (last or {}).get("open_episode_sk")}
    ops = []

    if state != "NORMAL" and not has_open:
        episode_id = ids.new_id()
        sk = f"EPISODE#{ts}#{episode_id}"
        episodes = _episodes_7d(pk, ts) + 1  # incluye el que se abre ahora
        ops.append(ddb.put_op("Telemetry", {
            "pk": pk, "sk": sk, "type": "EPISODE", "episode_id": episode_id, "antenna_id": antenna_id,
            "zone_id": zone_id, "state": state, "status": "OPEN", "opened_at": ts, "readings": 1,
            "min_gb": gb, "max_gb": gb,
            "gsi1pk": f"ZONE#{zone_id}", "gsi1sk": f"{ts}#{antenna_id}",
            "gsi2pk": f"OPEN#{zone_id}", "gsi2sk": f"{ts}#{antenna_id}",
        }, condition="attribute_not_exists(pk)"))
        new_last.update({"open_episode_id": episode_id, "open_episode_sk": sk})
        ops.append(events.outbox_put_op("telemetry.anomaly", {
            "antenna_id": antenna_id, "zone_id": zone_id, "episode_id": episode_id, "state": state,
            "gb_per_min": gb, "reason": "OPENED", "opened_at": ts, "episodes_7d": episodes,
        }))
        if episodes >= domain.RECURRENCE_EPISODES:
            ops.append(events.outbox_put_op("telemetry.recurrent", {
                "antenna_id": antenna_id, "zone_id": zone_id, "episodes_7d": episodes,
                "window_start": ids.shift_iso(ts, days=-domain.RECURRENCE_DAYS),
            }))

    elif state != "NORMAL":
        episode = _open_episode(pk, last)
        new_last.update(keep_open)
        escalated = domain.ANTENNA_SEVERITY[state] > domain.ANTENNA_SEVERITY[episode["state"]]
        update = "SET readings = readings + :one, min_gb = :min, max_gb = :max"
        values = {":one": 1, ":min": min(episode["min_gb"], gb), ":max": max(episode["max_gb"], gb),
                  ":open": "OPEN"}
        if escalated:
            update += ", #state = :state"
            values[":state"] = state
        names = _NAMES if escalated else {"#status": "status"}
        ops.append(ddb.update_op(
            "Telemetry", {"pk": pk, "sk": episode["sk"]}, update,
            condition="#status = :open", names=names, values=values,
        ))
        if escalated:
            ops.append(events.outbox_put_op("telemetry.anomaly", {
                "antenna_id": antenna_id, "zone_id": zone_id, "episode_id": episode["episode_id"], "state": state,
                "gb_per_min": gb, "reason": "ESCALATED", "opened_at": episode["opened_at"],
                "episodes_7d": _episodes_7d(pk, ts),
            }))

    elif has_open:
        normals = int(last.get("consecutive_normals", 0)) + 1
        if normals >= domain.NORMALS_TO_CLOSE:
            episode = _open_episode(pk, last)
            duration = ids.epoch(ts) - ids.epoch(episode["opened_at"])
            ops.append(ddb.update_op(
                "Telemetry", {"pk": pk, "sk": episode["sk"]},
                "SET #status = :closed, closed_at = :ts, duration_seconds = :d REMOVE gsi2pk, gsi2sk",
                condition="#status = :open", names={"#status": "status"},
                values={":closed": "CLOSED", ":open": "OPEN", ":ts": ts, ":d": duration},
            ))
            ops.append(events.outbox_put_op("telemetry.recovered", {
                "antenna_id": antenna_id, "zone_id": zone_id, "episode_id": episode["episode_id"],
                "closed_at": ts, "duration_seconds": duration,
            }))
        else:
            new_last.update(keep_open)
            new_last["consecutive_normals"] = normals

    if last:
        ops.append(ddb.put_op("Telemetry", new_last, condition="last_ts = :prev", values={":prev": last["last_ts"]}))
    else:
        ops.append(ddb.put_op("Telemetry", new_last, condition="attribute_not_exists(pk)"))
    return ops


def _process_antenna(antenna_id: str, readings: list) -> None:
    pk = f"ANTENNA#{antenna_id}"
    zone_id = None
    for ts, gb in sorted(readings):
        for _ in range(_ATTEMPTS):
            last = _get(pk, "LAST")
            if last and ts <= last["last_ts"]:
                break  # lectura ya procesada o fuera de orden
            zone_id = (last or {}).get("zone_id") or zone_id or _zone_of(antenna_id)
            if not zone_id:
                log.warning("antena %s fuera del catálogo: lecturas descartadas", antenna_id)
                return
            try:
                ddb.transact(_step_ops(last, antenna_id, zone_id, ts, gb))
                break
            except ClientError as exc:
                # Otra ejecución escribió LAST o el episodio: se relee y se reevalúa.
                if exc.response["Error"]["Code"] != "TransactionCanceledException":
                    raise
        else:
            raise RuntimeError(f"conflicto persistente al clasificar la antena {antenna_id}")


def _process(bucket: str, key: str) -> None:
    by_antenna = _readings(bucket, key)
    for antenna_id in sorted(by_antenna):
        _process_antenna(antenna_id, by_antenna[antenna_id])
    log.info("lote %s clasificado: %d antenas", key, len(by_antenna))


def handler(event, context):
    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            _process(*_parse(record))
        except InvalidMessage as exc:
            log.warning("mensaje %s descartado: %s", message_id, exc)
        except Exception:  # noqa: BLE001 - el registro vuelve a la cola
            log.exception("fallo al procesar el mensaje %s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
