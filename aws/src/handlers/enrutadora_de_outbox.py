"""EnrutadoraDeOutbox: stream de la tabla Outbox -> bus de EventBridge.

Es la única Lambda que llama a `PutEvents` (contracts/events.md). Solo publica registros INSERT.
Si `PutEvents` rechaza alguna entrada se lanza un error: el stream reintenta el lote (con bisección)
y al agotar los reintentos va a la DLQ. Un reintento puede repetir eventos ya publicados; los
consumidores son idempotentes por `event_id`.
"""
import logging
import os

import boto3

log = logging.getLogger()
log.setLevel(logging.INFO)

_MAX_ENTRIES = 10  # límite de PutEvents por llamada
_client = None


def _events_client():
    global _client
    if _client is None:
        _client = boto3.client("events")
    return _client


def _text(image: dict, name: str) -> str | None:
    value = (image.get(name) or {}).get("S")
    return value if isinstance(value, str) and value else None


def _entry(record: dict, bus_name: str) -> dict | None:
    """Entrada de PutEvents a partir de un registro del stream; None si no se publica."""
    if record.get("eventName") != "INSERT":
        return None
    image = (record.get("dynamodb") or {}).get("NewImage") or {}
    detail_type, source, detail = _text(image, "detail_type"), _text(image, "source"), _text(image, "detail")
    if not (detail_type and source and detail):
        # Dato inválido: reintentar no lo arregla. Se registra (sin contenido) y se descarta.
        log.error("registro de Outbox incompleto, descartado: %s", _text(image, "pk"))
        return None
    return {"EventBusName": bus_name, "Source": source, "DetailType": detail_type, "Detail": detail}


def handler(event, context):
    bus_name = os.environ["EVENT_BUS_NAME"]
    entries = [e for e in (_entry(r, bus_name) for r in event.get("Records") or []) if e]
    for start in range(0, len(entries), _MAX_ENTRIES):
        chunk = entries[start : start + _MAX_ENTRIES]
        resp = _events_client().put_events(Entries=chunk)
        failed = resp.get("FailedEntryCount", 0)
        if failed:
            codes = sorted({e.get("ErrorCode", "?") for e in resp.get("Entries", []) if e.get("ErrorCode")})
            raise RuntimeError(f"PutEvents rechazó {failed} de {len(chunk)} entradas: {codes}")
    log.info("eventos publicados: %d", len(entries))
    return {"published": len(entries)}
