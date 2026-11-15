"""Sugerencias para operadores; los fallos de IA nunca generan 5xx."""

import queue
import re
import threading
import time
from datetime import datetime

from common import config, ddb, http, outbound

_slots = threading.BoundedSemaphore(4)
_PROVIDER_SECONDS = 3.8


def _validated(body):
    if not isinstance(body, dict) or body.get("available") is not True:
        return {"available": False}
    items = body.get("hypotheses")
    if not isinstance(items, list) or not 1 <= len(items) <= 3:
        raise ValueError("Hipótesis inválidas")
    clean = []
    for item in items:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(k), str) and item[k].strip() for k in ("title", "rationale")
        ):
            raise ValueError("Hipótesis inválida")
        clean.append({"title": item["title"][:120], "rationale": item["rationale"][:500]})
    model, generated = body.get("model"), body.get("generated_at")
    if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,70}", model):
        raise ValueError("Modelo inválido")
    if not isinstance(generated, str) or len(generated) > 40:
        raise ValueError("Fecha inválida")
    timestamp = datetime.fromisoformat(generated.replace("Z", "+00:00"))
    if timestamp.utcoffset() is None or timestamp.utcoffset().total_seconds() != 0:
        raise ValueError("Fecha no UTC")
    return {"available": True, "hypotheses": clean, "model": model, "generated_at": generated}


def _suggest(incident_id, zone_id, seconds):
    # Covers SSM as well as HTTPS. No context manager waits for a stalled worker on timeout.
    end = time.monotonic() + seconds
    if seconds <= 0 or not _slots.acquire(blocking=False):
        return {"available": False}
    result = queue.Queue(maxsize=1)

    def work():
        try:
            base, key = (config.get_secret(k) for k in ("gcp/base_url", "gcp/api_key"))
            if any(not v or v == "PENDIENTE" for v in (base, key)):
                raise ValueError("GCP no configurado")
            response = outbound.post_json(
                base.rstrip("/") + "/suggest",
                {"incident_id": incident_id, "zone_id": zone_id, "days": 30},
                {"X-Api-Key": key},
                timeout=max(0, end - time.monotonic()),
            )
            result.put(_validated(response))
        except Exception:
            result.put({"available": False})
        finally:
            _slots.release()

    threading.Thread(target=work, daemon=True).start()
    try:
        return result.get(timeout=max(0, end - time.monotonic()))
    except queue.Empty:
        return {"available": False}


@http.api
def handler(event, context):
    http.require_role(event, "OPERATOR")
    incident_id = (event.get("pathParameters") or {}).get("incident_id")
    if not isinstance(incident_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", incident_id):
        raise http.ApiError("VALIDATION", "incident_id inválido")
    item = (
        ddb.table("Incidents")
        .get_item(
            Key={"pk": f"INCIDENT#{incident_id}", "sk": "META"},
            ConsistentRead=True,
        )
        .get("Item")
    )
    if not item:
        raise http.ApiError("NOT_FOUND", "Incidente no encontrado")
    zone = item.get("zone_id")
    if not isinstance(zone, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", zone):
        return http.response(200, {"available": False})
    seconds = _PROVIDER_SECONDS
    if context is not None and hasattr(context, "get_remaining_time_in_millis"):
        seconds = min(seconds, context.get_remaining_time_in_millis() / 1000 - 0.2)
    return http.response(200, _suggest(incident_id, zone, seconds))
