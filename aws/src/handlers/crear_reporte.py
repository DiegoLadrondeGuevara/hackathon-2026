"""CrearReporte: POST /reportes (rol CUSTOMER). Ver contracts/flows.md.

Una transacción: REPORT_META + REPORT_HIST + Outbox `report.created` (+ IDEMPOTENCY si viene
la cabecera `Idempotency-Key`). Si la clave ya existía se devuelve 200 con el reporte original.
"""
import logging
from datetime import datetime

from botocore.exceptions import ClientError

from common import ddb, events, http, ids

log = logging.getLogger()

# Enumeraciones de contracts/tables.md
SERVICES = ("MOVIL", "INTERNET")
PROBLEM_TYPES = ("SIN_SENAL", "SIN_INTERNET", "LLAMADAS", "SMS", "LENTITUD", "OTRO")

_IDEMPOTENCY_HOURS = 24
_MAX_KEY = 128
_MAX_FUTURE_MINUTES = 5
_MAX_PAST_DAYS = 30


def _invalid(message: str) -> http.ApiError:
    return http.ApiError("VALIDATION", message)


def _text(body: dict, name: str, max_len: int, required: bool = True) -> str | None:
    value = body.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise _invalid(f"El campo {name} debe ser texto")
    value = value.strip()
    if not value and not required:
        return None
    if not 1 <= len(value) <= max_len:
        raise _invalid(f"El campo {name} debe tener entre 1 y {max_len} caracteres")
    return value


def _choice(body: dict, name: str, options: tuple) -> str:
    value = body.get(name)
    if not isinstance(value, str) or value not in options:
        raise _invalid(f"El campo {name} debe ser uno de: {', '.join(options)}")
    return value


def _occurred_at(body: dict, now: str) -> str:
    raw = body.get("occurred_at")
    if raw is None:
        return now
    if not isinstance(raw, str):
        raise _invalid("El campo occurred_at debe ser una fecha ISO-8601")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("sin zona horaria")
        value = ids.to_iso(parsed)
    except (ValueError, OverflowError) as exc:
        raise _invalid("El campo occurred_at debe ser una fecha ISO-8601 con zona horaria") from exc
    if value > ids.shift_iso(now, minutes=_MAX_FUTURE_MINUTES):
        raise _invalid("El campo occurred_at no puede estar en el futuro")
    if value < ids.shift_iso(now, days=-_MAX_PAST_DAYS):
        raise _invalid(f"El campo occurred_at no puede ser anterior a {_MAX_PAST_DAYS} días")
    return value


def _zone_id(body: dict) -> str:
    zone_id = _text(body, "zone_id", 20)
    item = ddb.table("NetworkCatalog").get_item(Key={"pk": f"ZONE#{zone_id}", "sk": "META"}).get("Item")
    if not item or item.get("type") != "ZONE":
        raise _invalid("La zona indicada no existe")
    return zone_id


def _idempotency_key(event) -> str | None:
    raw = http.header(event, "Idempotency-Key")
    if raw is None:
        return None
    key = raw.strip()
    if not 1 <= len(key) <= _MAX_KEY:
        raise _invalid(f"La cabecera Idempotency-Key debe tener entre 1 y {_MAX_KEY} caracteres")
    return key


def _original(idem_key: dict, now: str) -> dict | None:
    """Reporte creado antes con la misma clave de idempotencia (si sigue vigente)."""
    idem = ddb.table("Reports").get_item(Key=idem_key, ConsistentRead=True).get("Item")
    if not idem or idem["ttl"] < ids.epoch(now):
        return None
    key = {"pk": f"REPORT#{idem['report_id']}", "sk": "META"}
    return ddb.table("Reports").get_item(Key=key, ConsistentRead=True).get("Item")


def _summary(meta: dict) -> dict:
    return {"report_id": meta["report_id"], "status": meta["status"], "created_at": meta["created_at"]}


@http.api
def handler(event, context):
    customer_id = http.require_role(event, "CUSTOMER")["sub"]
    idem = _idempotency_key(event)
    body = http.json_body(event)
    now = ids.now_iso()

    fields = {
        "service_number": _text(body, "service_number", 20),
        "service": _choice(body, "service", SERVICES),
        "problem_type": _choice(body, "problem_type", PROBLEM_TYPES),
        "description": _text(body, "description", 1000),
        "occurred_at": _occurred_at(body, now),
    }
    location_text = _text(body, "location_text", 200, required=False)
    if location_text:
        fields["location_text"] = location_text
    fields["zone_id"] = _zone_id(body)

    report_id = ids.new_id()
    pk = f"REPORT#{report_id}"
    meta = {
        "pk": pk,
        "sk": "META",
        "type": "REPORT_META",
        "report_id": report_id,
        "customer_id": customer_id,
        **fields,
        "created_at": now,
        "updated_at": now,
        "status": "REGISTRADA",
        "version": 1,
        "gsi1pk": f"CUSTOMER#{customer_id}",
        "gsi1sk": f"{now}#{report_id}",
        "gsi2pk": f"ZONE#{fields['zone_id']}",
        "gsi2sk": f"{now}#{report_id}",
    }
    hist = {
        "pk": pk,
        "sk": f"HIST#{now}",
        "type": "REPORT_HIST",
        "from_status": None,
        "to_status": "REGISTRADA",
        "actor": f"CUSTOMER#{customer_id}",
        "at": now,
    }
    ops = [
        ddb.put_op("Reports", meta, condition="attribute_not_exists(pk)"),
        ddb.put_op("Reports", hist),
        events.outbox_put_op(
            "report.created",
            {
                "report_id": report_id,
                "customer_id": customer_id,
                "zone_id": fields["zone_id"],
                "service": fields["service"],
                "problem_type": fields["problem_type"],
                "created_at": now,
            },
        ),
    ]
    idem_key = None
    if idem:
        idem_key = {"pk": f"IDEM#{customer_id}#{idem}", "sk": "META"}
        idem_item = {
            **idem_key,
            "type": "IDEMPOTENCY",
            "report_id": report_id,
            "ttl": ids.epoch(now) + _IDEMPOTENCY_HOURS * 3600,
        }
        # El borrado por TTL puede tardar: una clave vencida cuenta como inexistente.
        ops.append(
            ddb.put_op(
                "Reports",
                idem_item,
                condition="attribute_not_exists(pk) OR #ttl < :now",
                names={"#ttl": "ttl"},
                values={":now": ids.epoch(now)},
            )
        )

    try:
        ddb.transact(ops)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException" or not idem_key:
            raise
        original = _original(idem_key, now)
        if not original:
            raise
        log.info("reporte repetido por idempotencia: %s", original["report_id"])
        return http.response(200, _summary(original))

    log.info("reporte creado: %s zona=%s", report_id, fields["zone_id"])
    return http.response(201, _summary(meta))
