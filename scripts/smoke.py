"""Prueba de humo del API desplegado: login, crear reporte, listar mis reportes, consultar uno
e incidente colectivo (10 clientes distintos reportan en una zona y aparece un incidente).

Uso (después de `serverless deploy` y de `scripts/seed.py`):
    PowerShell:  $env:SEED_DEMO_PASSWORD = "<clave de demo>"
    bash:        export SEED_DEMO_PASSWORD='<clave de demo>'
    python scripts/smoke.py --base-url https://<id>.execute-api.us-east-1.amazonaws.com

La URL también puede venir de la variable SMOKE_BASE_URL. Solo usa stdlib.
Crea un reporte real en la zona indicada (por defecto Z01) con el cliente de demo 70000001.
La contraseña sale solo de SEED_DEMO_PASSWORD; ni ella ni el token se imprimen.
El paso 5 crea 10 reportes reales de INTERNET en --collective-zone (por defecto Z05) con los clientes
de demo 70000011 a 70000020 y espera a que GET /incidentes muestre un incidente activo en esa zona.
Si la zona ya tenía un incidente activo, los reportes se vinculan a ese y el paso lo indica.
Con --collective-zone "" se omite.
Termina con código 0 si todos los pasos pasan y 1 si alguno falla.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
import uuid

PASSWORD_ENV = "SEED_DEMO_PASSWORD"
BASE_URL_ENV = "SMOKE_BASE_URL"
TIMEOUT_SECONDS = 15
COLLECTIVE_CUSTOMERS = [f"{70000000 + n}" for n in range(11, 21)]  # 10 clientes de scripts/seed.py
COLLECTIVE_SERVICE = "INTERNET"
COLLECTIVE_WAIT_SECONDS = 90
COLLECTIVE_POLL_SECONDS = 3


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


def active_incidents(base_url: str, token: str, zone_id: str) -> dict:
    """Incidentes no cerrados de INTERNET en la zona: {incident_id: status}."""
    status, body = call(base_url, "GET", f"/incidentes?zone_id={zone_id}&limit=100", token)
    expect(status == 200 and isinstance(body.get("items"), list), "listar incidentes falló", status, body)
    return {
        item["incident_id"]: item.get("status")
        for item in body["items"]
        if item.get("service") == COLLECTIVE_SERVICE and item.get("status") != "CERRADO"
    }


def run_collective(base_url: str, password: str, zone_id: str, step: str) -> None:
    token, before = None, {}
    for number, identifier in enumerate(COLLECTIVE_CUSTOMERS, start=1):
        status, body = call(base_url, "POST", "/auth/login", body={"identifier": identifier, "password": password})
        expect(status == 200 and body.get("token"), f"login del cliente {number} de 10 falló", status, body)
        token = body["token"]
        if number == 1:
            before = active_incidents(base_url, token, zone_id)
        report = {
            "service_number": f"9000001{number:02d}",
            "zone_id": zone_id,
            "service": COLLECTIVE_SERVICE,
            "problem_type": "SIN_INTERNET",
            "description": "Prueba de humo: incidente colectivo generado por scripts/smoke.py",
        }
        status, body = call(base_url, "POST", "/reportes", token, report, {"Idempotency-Key": str(uuid.uuid4())})
        expect(status == 201, f"crear el reporte {number} de 10 falló", status, body)

    deadline = time.monotonic() + COLLECTIVE_WAIT_SECONDS
    while True:
        current = active_incidents(base_url, token, zone_id)
        new = sorted(set(current) - set(before))
        if new:
            print(f"{step} incidente colectivo OK (nuevo {new[0]} en {zone_id}, estado {current[new[0]]})")
            return
        if before and current:
            incident_id = sorted(current)[0]
            print(f"{step} incidente colectivo OK ({zone_id} ya tenía activo {incident_id}, "
                  f"estado {current[incident_id]}; los 10 reportes se vinculan a ese)")
            return
        if time.monotonic() >= deadline:
            raise StepError(f"no apareció un incidente en {zone_id} tras {COLLECTIVE_WAIT_SECONDS} s "
                            "(revisar CorrelacionadoraDeReportes, EnrutadoraDeOutbox y la DLQ de ColaReportes)")
        time.sleep(COLLECTIVE_POLL_SECONDS)


def run(base_url: str, identifier: str, password: str, zone_id: str, collective_zone: str = "") -> None:
    total = 5 if collective_zone else 4
    status, body = call(base_url, "POST", "/auth/login", body={"identifier": identifier, "password": password})
    expect(status == 200 and body.get("token"), "login falló", status, body)
    token = body["token"]
    print(f"1/{total} login OK (rol {body.get('role')})")

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
    print(f"2/{total} crear reporte OK ({report_id}; repetido con la misma clave devuelve 200)")

    status, body = call(base_url, "GET", "/reportes?limit=20", token)
    listed = [item.get("report_id") for item in body.get("items", [])]
    expect(status == 200 and report_id in listed, "el reporte no aparece en mis reportes", status, body)
    print(f"3/{total} listar mis reportes OK ({len(listed)} en la primera página)")

    status, body = call(base_url, "GET", f"/reportes/{report_id}", token)
    history = body.get("history") or []
    first = history[0].get("to_status") if history else None
    expect(status == 200 and body.get("report_id") == report_id and first == "REGISTRADA",
"consultar el reporte falló", status, body)
    print(f"4/{total} consultar reporte OK (estado {body.get('status')}, {len(history)} entrada(s) de historial)")

    if collective_zone:
        run_collective(base_url, password, collective_zone, f"5/{total}")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default=os.environ.get(BASE_URL_ENV, ""), help="URL del HTTP API, sin / final")
    ap.add_argument("--identifier", default="70000001", help="Cliente de demo de scripts/seed.py")
    ap.add_argument("--zone", default="Z01")
    ap.add_argument("--collective-zone", default="Z05",
                    help="Zona del paso de incidente colectivo (10 reportes); vacío para omitirlo")
    args = ap.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    if not base_url.startswith("https://") and not base_url.startswith("http://localhost"):
        raise SystemExit(f"Falta --base-url (o la variable {BASE_URL_ENV}) con la URL https del API")
    password = os.environ.get(PASSWORD_ENV, "")
    if not password:
        raise SystemExit(f"Falta la variable de entorno {PASSWORD_ENV} con la contraseña de demo")

    try:
        run(base_url, args.identifier, password, args.zone, args.collective_zone.strip())
    except StepError as exc:
        print(f"FALLO: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("Prueba de humo completa")


if __name__ == "__main__":
    main()
