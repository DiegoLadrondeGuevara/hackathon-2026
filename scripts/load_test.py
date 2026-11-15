"""Prueba de carga del API desplegado: N reportes de INTERNET (o MOVIL) en una zona, en paralelo.

Uso (después de `serverless deploy` y de `scripts/seed.py`):
    PowerShell:  $env:SEED_DEMO_PASSWORD = "<clave de demo>"
    bash:        export SEED_DEMO_PASSWORD='<clave de demo>'
    python scripts/load_test.py --base-url https://<id>.execute-api.us-east-1.amazonaws.com --zona Z05 -n 30
    python scripts/load_test.py --zona Z02 -n 100 --hilos 4 --servicio MOVIL --espera 120

Opciones: --zona (Z05), -n/--reportes (30, hasta 1000), --servicio INTERNET|MOVIL (INTERNET),
--problema (SIN_INTERNET), --hilos (1, hasta 4), --pausa (0.25: segundos entre reportes de cada hilo),
--clientes (20: cuántos clientes de demo, de 70000001 en adelante, hasta 20), --espera (60: segundos para
esperar un incidente activo; 0 lo omite).
La URL también puede venir de SMOKE_BASE_URL. La contraseña sale solo de SEED_DEMO_PASSWORD y nunca se
imprime, igual que los tokens. Solo usa stdlib.

Cada cliente inicia sesión una vez y los reportes se reparten entre los clientes por turnos. El incidente
colectivo exige 10 clientes distintos en la misma zona y servicio dentro de 24 h, así que con -n menor
que 10 (o --clientes menor que 10) no se espera incidente. Con -n mayor que --clientes, los clientes se
repiten y no suman usuarios afectados. Los reportes son reales: límpialos con el flujo normal de la demo.
Imprime reportes enviados y fallidos por código HTTP, latencia p50, p95 y máxima, y reportes por segundo.
Termina con código 0 si todos se crearon (201) y 1 si alguno falló.
"""
import argparse
import os
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import smoke  # noqa: E402

PASSWORD_ENV = "SEED_DEMO_PASSWORD"
BASE_URL_ENV = "SMOKE_BASE_URL"
FIRST_CUSTOMER = 70000001
MAX_CUSTOMERS = 20
MAX_REPORTS = 1000
MAX_THREADS = 4   # AWS Academy: máx. 10 Lambdas simultáneas en toda la cuenta
DEFAULT_PAUSE = 0.25
MAX_PAUSE = 10.0
POLL_SECONDS = 3


def percentile(sorted_values: list, p: float) -> float:
    """Percentil por rango más cercano sobre una lista ya ordenada (0 si está vacía)."""
    if not sorted_values:
        return 0.0
    rank = max(1, -(-len(sorted_values) * p // 100))  # techo de n*p/100
    return sorted_values[int(rank) - 1]


def login_all(base_url: str, password: str, count: int) -> list:
    tokens = []
    for number in range(count):
        identifier = str(FIRST_CUSTOMER + number)
        status, body = smoke.call(base_url, "POST", "/auth/login",
                                  body={"identifier": identifier, "password": password})
        if status != 200 or not body.get("token"):
            raise SystemExit(f"login del cliente {number + 1} de {count} falló (HTTP {status})")
        tokens.append(body["token"])
    return tokens


def send_report(base_url: str, token: str, number: int, zone: str, service: str, problem: str) -> tuple:
    """Crea un reporte. Devuelve (status HTTP, segundos); un fallo de red cuenta como status 0."""
    report = {
        "service_number": f"{900000000 + number}",
        "zone_id": zone,
        "service": service,
        "problem_type": problem,
        "description": "Prueba de carga generada por scripts/load_test.py",
    }
    started = time.perf_counter()
    try:
        status, _ = smoke.call(base_url, "POST", "/reportes", token, report, {"Idempotency-Key": str(uuid.uuid4())})
    except smoke.StepError:
        status = 0
    return status, time.perf_counter() - started


def paced_report(pause: float, *args) -> tuple:
    """Un reporte y una pausa: reparte la carga en el tiempo para no pasar el límite de Lambdas del laboratorio."""
    result = send_report(*args)
    time.sleep(pause)
    return result


def run_load(base_url: str, tokens: list, zone: str, count: int, service: str, problem: str, threads: int,
             pause: float = 0.0) -> dict:
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=threads) as pool:
        futures = [
            pool.submit(paced_report, pause, base_url, tokens[n % len(tokens)], n + 1, zone, service, problem)
            for n in range(count)
        ]
        results = [f.result() for f in futures]
    elapsed = time.perf_counter() - started
    failures = {}
    for status, _ in results:
        if status != 201:
            failures[status] = failures.get(status, 0) + 1
    latencies = sorted(seconds * 1000 for _, seconds in results)
    return {
        "sent": count,
        "created": count - sum(failures.values()),
        "failures": failures,
        "p50_ms": percentile(latencies, 50),
        "p95_ms": percentile(latencies, 95),
        "max_ms": latencies[-1] if latencies else 0.0,
        "seconds": elapsed,
        "per_second": count / elapsed if elapsed > 0 else 0.0,
    }


def active_incident(base_url: str, token: str, zone: str, service: str):
    """Primer incidente no cerrado de la zona y el servicio, o None."""
    status, body = smoke.call(base_url, "GET", f"/incidentes?zone_id={zone}&limit=100", token)
    if status != 200 or not isinstance(body.get("items"), list):
        raise smoke.StepError(f"listar incidentes falló (HTTP {status})")
    for item in body["items"]:
        if item.get("service") in (service, "ANY") and item.get("status") != "CERRADO":
            return item
    return None


def wait_incident(base_url: str, token: str, zone: str, service: str, seconds: int):
    deadline = time.monotonic() + seconds
    while True:
        incident = active_incident(base_url, token, zone, service)
        if incident or time.monotonic() >= deadline:
            return incident
        time.sleep(POLL_SECONDS)


def print_summary(summary: dict) -> None:
    print(f"enviados {summary['sent']}, creados {summary['created']}, "
          f"fallidos {summary['sent'] - summary['created']}")
    for status, n in sorted(summary["failures"].items()):
        print(f"  HTTP {status or 'sin respuesta'}: {n}")
    print(f"latencia p50 {summary['p50_ms']:.0f} ms, p95 {summary['p95_ms']:.0f} ms, "
          f"máxima {summary['max_ms']:.0f} ms")
    print(f"{summary['per_second']:.1f} reportes/s en {summary['seconds']:.1f} s")


def bounded(name: str, value: int, low: int, high: int) -> int:
    if not low <= value <= high:
        raise SystemExit(f"{name} debe estar entre {low} y {high}")
    return value


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Prueba de carga: N reportes de una zona")
    parser.add_argument("--base-url", default=os.environ.get(BASE_URL_ENV, ""))
    parser.add_argument("--zona", default="Z05")
    parser.add_argument("-n", "--reportes", type=int, default=30)
    parser.add_argument("--servicio", choices=["INTERNET", "MOVIL"], default="INTERNET")
    parser.add_argument("--problema", default="SIN_INTERNET")
    parser.add_argument("--hilos", type=int, default=1)
    parser.add_argument("--clientes", type=int, default=MAX_CUSTOMERS)
    parser.add_argument("--espera", type=int, default=60)
    parser.add_argument("--pausa", type=float, default=DEFAULT_PAUSE)
    args = parser.parse_args(argv)

    base_url = args.base_url.rstrip("/")
    if not base_url:
        raise SystemExit(f"Falta --base-url o la variable {BASE_URL_ENV}")
    password = os.environ.get(PASSWORD_ENV, "")
    if not password:
        raise SystemExit(f"Falta la variable de entorno {PASSWORD_ENV} con la contraseña de demo")
    zone = args.zona.strip().upper()
    if not zone:
        raise SystemExit("--zona no puede estar vacía")
    count = bounded("-n/--reportes", args.reportes, 1, MAX_REPORTS)
    threads = bounded("--hilos", args.hilos, 1, MAX_THREADS)
    customers = bounded("--clientes", args.clientes, 1, MAX_CUSTOMERS)
    wait = bounded("--espera", args.espera, 0, 600)
    if not 0 <= args.pausa <= MAX_PAUSE:
        raise SystemExit(f"--pausa debe estar entre 0 y {MAX_PAUSE:g} segundos")

    try:
        tokens = login_all(base_url, password, customers)
        print(f"{customers} cliente(s) con sesión; enviando {count} reporte(s) a {zone} ({args.servicio})")
        summary = run_load(base_url, tokens, zone, count, args.servicio, args.problema, threads, args.pausa)
        print_summary(summary)
        if wait and summary["created"] and min(count, customers) >= 10:
            incident = wait_incident(base_url, tokens[0], zone, args.servicio, wait)
            if incident:
                print(f"incidente activo {incident['incident_id']} en {zone}: estado {incident.get('status')}")
            else:
                print(f"no apareció un incidente en {zone} tras {wait} s "
                      "(revisar CorrelacionadoraDeReportes, EnrutadoraDeOutbox y la DLQ de ColaReportes)")
                return 1
        elif wait:
            print("sin espera de incidente: hacen falta 10 clientes distintos y reportes creados")
    except smoke.StepError as exc:
        print(f"falló: {exc}")
        return 1
    return 0 if not summary["failures"] else 1


if __name__ == "__main__":
    sys.exit(main())
