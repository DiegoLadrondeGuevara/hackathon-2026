"""Utilidades para Lambdas detrás de API Gateway HTTP API (payload v2)."""
import base64
import functools
import json
import logging

from . import jsonutil

log = logging.getLogger()
log.setLevel(logging.INFO)

STATUS = {
    "VALIDATION": 400,
    "UNAUTHORIZED": 401,
    "FORBIDDEN": 403,
    "NOT_FOUND": 404,
    "CONFLICT": 409,
    "INTERNAL": 500,
}


class ApiError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def response(status: int, body) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": jsonutil.dumps(body),
    }


def error_response(code: str, message: str) -> dict:
    return response(STATUS[code], {"error": {"code": code, "message": message}})


def api(fn):
    """Decorador: convierte ApiError en la respuesta de error estándar y los fallos inesperados en 500."""

    @functools.wraps(fn)
    def wrapper(event, context=None):
        try:
            return fn(event, context)
        except ApiError as exc:
            return error_response(exc.code, exc.message)
        except Exception:  # noqa: BLE001 - no se filtran detalles internos
            log.exception("error no controlado")
            return error_response("INTERNAL", "Error interno")

    return wrapper


def json_body(event) -> dict:
    raw = event.get("body")
    if raw is None or raw == "":
        raise ApiError("VALIDATION", "Falta el cuerpo de la solicitud")
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        data = json.loads(raw)
    except ValueError as exc:
        raise ApiError("VALIDATION", "El cuerpo no es JSON válido") from exc
    if not isinstance(data, dict):
        raise ApiError("VALIDATION", "El cuerpo debe ser un objeto JSON")
    return data


def claims(event) -> dict:
    ctx = (event.get("requestContext") or {}).get("authorizer", {}).get("lambda") or {}
    if not ctx.get("sub") or not ctx.get("role"):
        raise ApiError("UNAUTHORIZED", "Sesión no válida")
    return {"sub": ctx["sub"], "role": ctx["role"]}


def require_role(event, *roles) -> dict:
    c = claims(event)
    if c["role"] not in roles:
        raise ApiError("FORBIDDEN", "No tienes permiso para esta acción")
    return c


def header(event, name: str):
    headers = event.get("headers") or {}
    for key, value in headers.items():
        if key.lower() == name.lower():
            return value
    return None
