"""HTTP API consumed by AWS publisher and the public Azure page."""

import json
import logging
import time

import azure.functions as func

from observability import record_request
from status_store import get_table_client, list_zones, save_newer

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


def response(payload: object, status: int = 200) -> func.HttpResponse:
    return func.HttpResponse(
        json.dumps(payload, ensure_ascii=False),
        status_code=status,
        mimetype="application/json",
        charset="utf-8",
    )


def observed(route: str, started: float, result: func.HttpResponse, zones: list[dict] | None = None) -> func.HttpResponse:
    record_request(route, result.status_code, (time.monotonic() - started) * 1000, zones)
    return result


@app.route(route="estado/{zone_id}", methods=["PUT"], auth_level=func.AuthLevel.FUNCTION)
def actualizar_estado(req: func.HttpRequest) -> func.HttpResponse:
    started = time.monotonic()
    route = "PUT /api/estado/{zone_id}"
    try:
        body = req.get_json()
        applied, entity = save_newer(get_table_client(), req.route_params["zone_id"], body)
        result = response({"applied": applied, "zone_id": entity["RowKey"], "updated_at": entity["updated_at"]})
    except (ValueError, TypeError) as exc:
        result = response({"error": str(exc)}, 400)
    except Exception:
        logging.exception("No se pudo actualizar el estado de zona")
        result = response({"error": "Error interno"}, 500)
    return observed(route, started, result)


@app.route(route="estado", methods=["GET"], auth_level=func.AuthLevel.ANONYMOUS)
def consultar_estados(req: func.HttpRequest) -> func.HttpResponse:
    started = time.monotonic()
    route = "GET /api/estado"
    zones = None
    try:
        zones = list_zones(get_table_client())
        result = response({"zones": zones})
    except Exception:
        logging.exception("No se pudo consultar el estado de zonas")
        result = response({"error": "Error interno"}, 500)
    return observed(route, started, result, zones)
