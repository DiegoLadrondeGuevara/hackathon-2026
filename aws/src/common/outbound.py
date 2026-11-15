"""HTTPS JSON con límite total, sin redirecciones ni secretos en excepciones."""
import json
import queue
import threading
import time
import urllib.request
from decimal import Decimal
from urllib.parse import urlsplit

from . import jsonutil

_slots = threading.BoundedSemaphore(4)
MAX_RESPONSE = 64 * 1024


class OutboundError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Sustituible en pruebas; las redirecciones no pueden filtrar la clave.
urlopen = urllib.request.build_opener(_NoRedirect()).open


def _send(method, url, body, headers, timeout):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise OutboundError("URL HTTPS inválida")
    if timeout <= 0 or not _slots.acquire(blocking=False):
        raise OutboundError("Servicio externo no disponible")
    deadline = time.monotonic() + timeout
    result = queue.Queue(maxsize=1)

    def work():
        try:
            request = urllib.request.Request(
                url, data=jsonutil.dumps(body).encode(), method=method,
                headers={**(headers or {}), "Content-Type": "application/json"},
            )
            with urlopen(request, timeout=timeout) as response:
                if not 200 <= response.status < 300:
                    raise OutboundError("Respuesta externa no exitosa")
                raw = response.read(MAX_RESPONSE + 1)
                if len(raw) > MAX_RESPONSE:
                    raise OutboundError("Respuesta externa demasiado grande")
                value = json.loads(raw, parse_float=Decimal) if raw else {}
            result.put((True, value))
        except Exception:
            result.put((False, None))
        finally:
            _slots.release()

    threading.Thread(target=work, daemon=True).start()
    try:
        ok, value = result.get(timeout=max(0, deadline - time.monotonic()))
    except queue.Empty:
        raise OutboundError("Tiempo de espera externo agotado") from None
    if not ok:
        raise OutboundError("Fallo del servicio externo")
    return value


def post_json(url, body, headers=None, timeout=10):
    return _send("POST", url, body, headers, timeout)


def put_json(url, body, headers=None, timeout=10):
    return _send("PUT", url, body, headers, timeout)
