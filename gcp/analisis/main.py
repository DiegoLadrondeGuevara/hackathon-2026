"""Cloud Run HTTP function: AWS events and advisory hypotheses."""

import hmac
import json
import logging
import os
import time

import ai
import bigquery_repo as repository
import deadline
import functions_framework
import metrics
from contract import ContractError, check_id, sanitize_event, to_row
from flask import g, jsonify, make_response

log = logging.getLogger(__name__)
MAX_BODY = 96 * 1024
SUGGEST_SECONDS = 3.2  # Includes BigQuery + Gemini; leaves room for AWS/HTTP overhead.
INGEST_SECONDS = 15


def _body(request):
    if not request.is_json or (request.content_length or 0) > MAX_BODY:
        raise ContractError("JSON requerido; máximo 96 KiB")
    # Bounded read even when Content-Length is missing.
    raw = request.stream.read(MAX_BODY + 1)
    if len(raw) > MAX_BODY:
        raise ContractError("Cuerpo demasiado grande")
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ContractError("JSON inválido") from exc
    if not isinstance(value, dict):
        raise ContractError("Se requiere objeto JSON")
    return value


def _ingest(body):
    if set(body) != {"events"} or not isinstance(body["events"], list) or not 1 <= len(body["events"]) <= 10:
        raise ContractError("Se requieren de 1 a 10 eventos")
    unique = {}
    for raw in body["events"]:
        event = sanitize_event(raw)
        existing = unique.get(event["event_id"])
        if existing is not None and existing != event:
            raise ContractError("Un event_id tiene contenido contradictorio en el lote")
        unique[event["event_id"]] = event
    rows = [to_row(event) for event in unique.values()]
    return {"inserted": deadline.run(lambda end: repository.merge_rows(rows, end), INGEST_SECONDS)}


def _suggest(body):
    if set(body) - {"incident_id", "zone_id", "days"}:
        raise ContractError("Campos desconocidos")
    check_id(body.get("incident_id"), "incident_id")
    check_id(body.get("zone_id"), "zone_id")
    days = body.get("days", 30)
    if type(days) is not int or not 1 <= days <= 90:
        raise ContractError("days debe ser entero entre 1 y 90")

    def work(end):
        facts = repository.zone_summary(body["zone_id"], days, end)
        if not facts["event_count"]:
            return {"available": False}
        return ai.generate_hypotheses(facts, end)

    try:
        return deadline.run(work, SUGGEST_SECONDS)
    except Exception:
        g.ai_failed = True
        log.warning("Sugerencia no disponible")
        return {"available": False}


def _handle(request):
    if request.path == "/healthz" and request.method in ("GET", "HEAD"):
        return jsonify({"status": "ok"}), 200
    if request.path not in ("/ingest", "/suggest"):
        return jsonify({"error": "NOT_FOUND"}), 404
    if request.method != "POST":
        return jsonify({"error": "METHOD_NOT_ALLOWED"}), 405
    actual, expected = request.headers.get("X-Api-Key", ""), os.environ.get("API_KEY", "")
    if not expected or not hmac.compare_digest(actual.encode(), expected.encode()):
        return jsonify({"error": "UNAUTHORIZED"}), 401
    try:
        body = _body(request)
        result = _ingest(body) if request.path == "/ingest" else _suggest(body)
        return jsonify(result), 200, {"Cache-Control": "no-store"}
    except ContractError as exc:
        return jsonify({"error": "VALIDATION", "message": str(exc)}), 400
    except Exception:
        log.warning("Persistencia no disponible")
        return jsonify({"error": "DEPENDENCY_UNAVAILABLE"}), 503


@functions_framework.http
def api(request):
    start = time.monotonic()
    response = make_response(_handle(request))
    try:
        body = response.get_json(silent=True) or {}
        metrics.record(
            request.path,
            response.status_code,
            body.get("inserted", 0),
            (time.monotonic() - start) * 1000,
            failed=getattr(g, "ai_failed", False),
        )
    except Exception:
        pass  # Telemetry must never change the API response.
    return response
