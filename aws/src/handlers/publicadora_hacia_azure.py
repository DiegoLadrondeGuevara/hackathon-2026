"""PublicadoraHaciaAzure: ColaAzure → `PUT /api/estado/{zone_id}` de la Function de estado público.

Traduce `incident.updated` al estado público de la zona: el estado del incidente mientras esté activo
(EVALUACION, CONFIRMADO, RESTABLECIDO) y SIN_INCIDENTE cuando pasa a CERRADO. El cuerpo lleva solo zona,
estado, prioridad, fecha y un mensaje público: nunca datos personales ni identificadores de incidente.
Hay un estado por zona: gana el último evento (si una zona tiene varios incidentes, el más reciente).
Dentro de un lote se envía un solo PUT por zona, con el evento más nuevo. Los fallos devuelven los mensajes
a la cola (`batchItemFailures`) y el PUT es idempotente. Clave en SSM `azure/api_key`, URL en `azure/base_url`.
"""
import json
import logging
import re
from urllib.parse import quote

from common import config, outbound

log = logging.getLogger(__name__)

PUBLIC_STATUS = {
    "EVALUACION": "EVALUACION",
    "CONFIRMADO": "CONFIRMADO",
    "RESTABLECIDO": "RESTABLECIDO",
    "CERRADO": "SIN_INCIDENTE",
}
PUBLIC_MESSAGE = {
    "EVALUACION": "Evaluando",
    "CONFIRMADO": "Incidencia confirmada, nuestro equipo está trabajando para resolverla",
    "RESTABLECIDO": "Servicio restablecido",
    "SIN_INCIDENTE": "Sin incidentes",
}
_ZONE = re.compile(r"^[A-Za-z0-9_-]{1,20}$")
_CALL_TIMEOUT = 10      # segundos por llamada
_RESERVE = 3            # segundos que se dejan libres antes del timeout de la Lambda
_MIN_CALL = 2           # si queda menos que esto, el resto vuelve a la cola


def _state(record: dict) -> dict:
    """Estado público de un registro `incident.updated`; ValueError/KeyError/TypeError si no aplica."""
    detail = json.loads(record["body"])["detail"]
    if isinstance(detail, str):
        detail = json.loads(detail)
    if detail["type"] != "incident.updated":
        raise ValueError("tipo no publicable")
    data = detail["data"]
    status = PUBLIC_STATUS[data["status"]]
    zone_id, updated_at = data["zone_id"], data["updated_at"]
    if not isinstance(zone_id, str) or not _ZONE.match(zone_id):
        raise ValueError("zona inválida")
    if not isinstance(updated_at, str) or not updated_at:
        raise ValueError("fecha inválida")
    priority = data.get("priority") if status != "SIN_INCIDENTE" else None
    return {
        "zone_id": zone_id,
        "status": status,
        "priority": priority if isinstance(priority, str) and priority else None,
        "updated_at": updated_at,
        "public_message": PUBLIC_MESSAGE[status],
    }


def _remaining(context) -> float | None:
    getter = getattr(context, "get_remaining_time_in_millis", None)
    return getter() / 1000 if getter else None


def handler(event, context):
    records = event.get("Records", [])
    if not records:
        return {"batchItemFailures": []}
    try:
        base, key = (config.get_secret(k) for k in ("azure/base_url", "azure/api_key"))
        if any(not v or v == "PENDIENTE" for v in (base, key)):
            raise ValueError("Integración no configurada")
    except Exception:
        log.warning("Azure sin configurar: los mensajes vuelven a la cola")
        return {"batchItemFailures": [{"itemIdentifier": r["messageId"]} for r in records]}

    by_zone = {}   # zone_id -> (estado más nuevo, ids de los mensajes de esa zona)
    for record in records:
        try:
            state = _state(record)
        except (ValueError, KeyError, TypeError):
            log.warning("Evento Azure inválido descartado")  # nunca registrar el contenido
            continue
        current, ids_ = by_zone.get(state["zone_id"], (None, []))
        ids_.append(record["messageId"])
        if current is None or state["updated_at"] >= current["updated_at"]:
            current = state
        by_zone[state["zone_id"]] = (current, ids_)

    failed = []
    for zone_id, (state, message_ids) in by_zone.items():
        timeout = _CALL_TIMEOUT
        left = _remaining(context)
        if left is not None:
            timeout = min(_CALL_TIMEOUT, left - _RESERVE)
        try:
            if timeout < _MIN_CALL:
                raise TimeoutError("sin tiempo para llamar a Azure")
            outbound.put_json(
                f"{base.rstrip('/')}/api/estado/{quote(zone_id, safe='')}", state,
                {"x-functions-key": key}, timeout=timeout,
            )
        except Exception:
            log.warning("Envío a Azure pendiente de reintento: zona=%s", zone_id)
            failed.extend({"itemIdentifier": mid} for mid in message_ids)
    return {"batchItemFailures": failed}
