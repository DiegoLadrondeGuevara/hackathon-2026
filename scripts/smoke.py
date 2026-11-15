"""Prueba de humo del API desplegado: login, crear reporte, listar mis reportes y consultar uno.

Uso (después de `serverless deploy` y de `scripts/seed.py`):
    PowerShell:  $env:SEED_DEMO_PASSWORD = "<clave de demo>"
    bash:        export SEED_DEMO_PASSWORD='<clave de demo>'
    python scripts/smoke.py --base-url https://<id>.execute-api.us-east-1.amazonaws.com

La URL también puede venir de la variable SMOKE_BASE_URL. Solo usa stdlib.
Crea un reporte real en la zona indicada (por defecto Z01) con el cliente de demo 70000001.
La contraseña sale solo de SEED_DEMO_PASSWORD; ni ella ni el token se imprimen.
Termina con código 0 si los cuatro pasos pasan y 1 si alguno falla.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
import uuid

PASSWORD_ENV = "SEED_DEMO_PASSWORD"
BASE_URL_ENV = "SMOKE_BASE_URL"
TIMEOUT_SECONDS = 15


class StepError(Exception):
    pass


def call(base_url: str, method: str, path: str, token: str | None = None, body=None, headers=None):
    """Devuelve (status, json). Los errores HTTP no lanzan: se devuelven con su cuerpo."""
    req = urllib.request.Request(f"{base_url}{path}", method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for name, value in (headers or {}).items():
        req.add_header(name, value)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=TIMEOUT_SECONDS) as resp:
            status, raw = resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read()
    except urllib.error.URLError as exc:
        raise StepError(f"sin conexión con {base_url}: {exc.reason}") from exc
    try:
        return status, json.loads(raw) if raw else {}
    except ValueError:
        return status, {"raw": raw[:200].decode("utf-8", "replace")}


def expect(condition: bool, message: str, status: int, payload: dict) -> None:
    if not condition:
        # Del cuerpo solo se muestra el error estándar, nunca datos del reporte ni el token.
        detail = payload.get("error") or payload.get("message") or ""
        raise StepError(f"{message} (HTTP {status}) {detail}".strip())


def run(base_url: str, identifier: str, password: str, zone_id: str) -> None:
    status, body = call(base_url, "POST", "/auth/login", body={"identifier": identifier, "password": password})
    expect(status == 200 and body.get("token"), "login falló", status, body)
    token = body["token"]
    print(f"1/4 login OK (rol {body.get('role')})")

    report = {
        "service_number": "900000001",
        "zone_id": zone_id,
        "service": "INTERNET",
        "problem_type": "SIN_INTERNET",
        "description": "Prueba de humo: reporte generado por scripts/smoke.py",
    }
    idem = {"Idempotency-Key": str(uuid.uuid4())}
    status, body = call(base_url, "POST", "/reportes", token, report, idem)
    expect(status == 201 and body.get("status") == "REGISTRADA", "crear reporte falló", status, body)
    report_id = body["report_id"]
    status, again = call(base_url, "POST", "/reportes", token, report, idem)
    expect(status == 200 and again.get("report_id") == report_id, "la idempotencia no devolvió el original",
           status, again)
    print(f"2/4 crear reporte OK ({report_id}; repetido con la misma clave devuelve 200)")

    status, body = call(base_url, "GET", "/reportes?limit=20", token)
    listed = [item.get("report_id") for item in body.get("items", [])]
    expect(status == 200 and report_id in listed, "el reporte no aparece en mis reportes", status, body)
    print(f"3/4 listar mis reportes OK ({len(listed)} en la primera página)")

    status, body = call(base_url, "GET", f"/reportes/{report_id}", token)
    history = body.get("history") or []
    first = history[0].get("to_status") if history else None
    expect(status == 200 and body.get("report_id") == report_id and first == "REGISTRADA",
"consultar el reporte falló", status, body)
    print(f"4/4 consultar reporte OK (estado {body.get('status')}, {len(history)} entrada(s) de historial)")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get(BASE_URL_ENV, ""), help="URL del HTTP API, sin / final")
    ap.add_argument("--identifier", default="70000001", help="Cliente de demo de scripts/seed.py")
    ap.add_argument("--zone", default="Z01")
    args = ap.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    if not base_url.startswith("https://") and not base_url.startswith("http://localhost"):
        raise SystemExit(f"Falta --base-url (o la variable {BASE_URL_ENV}) con la URL https del API")
    password = os.environ.get(PASSWORD_ENV, "")
    if not password:
        raise SystemExit(f"Falta la variable de entorno {PASSWORD_ENV} con la contraseña de demo")

    try:
        run(base_url, args.identifier, password, args.zone)
    except StepError as exc:
        print(f"FALLO: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("Prueba de humo completa")


if __name__ == "__main__":
    main()
