"""Eventos de dominio: sobre estándar y operación de escritura en Outbox (ver contracts/events.md)."""
from . import ddb, ids, jsonutil

SOURCE = "red-telecorp"
OUTBOX_TTL_DAYS = 7


def envelope(event_type: str, data: dict) -> dict:
    return {
        "event_id": ids.new_id(),
        "type": event_type,
        "version": 1,
        "occurred_at": ids.now_iso(),
        "data": data,
    }


def outbox_put_op(event_type: str, data: dict) -> dict:
    """Operación Put para incluir en la misma transacción que el cambio de datos."""
    env = envelope(event_type, data)
    created = env["occurred_at"]
    item = {
        "pk": f"EVENT#{env['event_id']}",
        "sk": "EVT",
        "type": "OUTBOX",
        "event_id": env["event_id"],
        "detail_type": event_type,
        "source": SOURCE,
        "detail": jsonutil.dumps(env),
        "created_at": created,
        "ttl": ids.epoch(created) + OUTBOX_TTL_DAYS * 86400,
    }
    return ddb.put_op("Outbox", item)
