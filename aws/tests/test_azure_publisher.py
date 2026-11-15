"""T13: publicadora_hacia_azure (ColaAzure → PUT /api/estado/{zone_id})."""
import json

import boto3
import pytest

from common import outbound
from handlers import publicadora_hacia_azure as publisher

BASE = "https://estado.example.net"
CLAVE = "clave-de-azure"


@pytest.fixture
def configured(aws):
    ssm = boto3.client("ssm")
    ssm.put_parameter(Name="/red-telecorp/test/azure/base_url", Value=BASE + "/", Type="String")
    ssm.put_parameter(Name="/red-telecorp/test/azure/api_key", Value=CLAVE, Type="SecureString")


class Calls(list):
    """Llamadas PUT registradas; `fail` lista fragmentos de URL que deben fallar."""

    def __init__(self):
        super().__init__()
        self.fail = []


@pytest.fixture
def puts(monkeypatch):
    calls = Calls()

    def fake(url, body, headers=None, timeout=10):
        calls.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        if any(part in url for part in calls.fail):
            raise outbound.OutboundError("Fallo del servicio externo")
        return {}

    monkeypatch.setattr(outbound, "put_json", fake)
    return calls


def record(n, zone="Z01", status="EVALUACION", priority="P2", at="2026-11-15T10:00:00.000Z", kind="incident.updated",
           **extra):
    data = {"incident_id": f"I{n}", "zone_id": zone, "service": "INTERNET", "status": status, "priority": priority,
            "milestone": None, "change": "STATUS", "affected_users": 12, "updated_at": at, **extra}
    detail = {"event_id": f"E{n}", "type": kind, "version": 1, "occurred_at": at, "data": data}
    return {"messageId": f"m{n}", "body": json.dumps({"detail-type": kind, "detail": detail})}


def run(*records, context=None):
    return publisher.handler({"Records": list(records)}, context)


def test_publica_el_estado_de_la_zona(configured, puts):
    assert run(record(1, zone="Z02", status="CONFIRMADO", priority="P1")) == {"batchItemFailures": []}
    (call,) = puts
    assert call["url"] == f"{BASE}/api/estado/Z02"
    assert call["headers"] == {"x-functions-key": CLAVE}
    assert call["body"] == {
        "zone_id": "Z02", "status": "CONFIRMADO", "priority": "P1", "updated_at": "2026-11-15T10:00:00.000Z",
        "public_message": publisher.PUBLIC_MESSAGE["CONFIRMADO"],
    }


@pytest.mark.parametrize("estado", ["EVALUACION", "CONFIRMADO", "RESTABLECIDO"])
def test_estados_activos_pasan_igual(configured, puts, estado):
    run(record(1, status=estado))
    assert puts[0]["body"]["status"] == estado
    assert puts[0]["body"]["public_message"] == publisher.PUBLIC_MESSAGE[estado]


def test_cerrado_se_publica_como_sin_incidente(configured, puts):
    run(record(1, status="CERRADO", priority="P1"))
    assert puts[0]["body"]["status"] == "SIN_INCIDENTE"
    assert puts[0]["body"]["priority"] is None
    assert puts[0]["body"]["public_message"] == publisher.PUBLIC_MESSAGE["SIN_INCIDENTE"]


def test_el_cuerpo_solo_lleva_los_cinco_campos_publicos(configured, puts):
    run(record(1, customer_id="12345678", description="privado", location_text="Calle 1"))
    body = puts[0]["body"]
    assert set(body) == {"zone_id", "status", "priority", "updated_at", "public_message"}
    assert "12345678" not in json.dumps(body) and "I1" not in json.dumps(body)


def test_un_put_por_zona_con_el_evento_mas_nuevo(configured, puts):
    resp = run(
        record(1, zone="Z01", status="EVALUACION", at="2026-11-15T10:00:00.000Z"),
        record(2, zone="Z01", status="CONFIRMADO", at="2026-11-15T10:05:00.000Z"),
        record(3, zone="Z01", status="EVALUACION", at="2026-11-15T09:00:00.000Z"),  # llegó tarde: no pisa
        record(4, zone="Z02", status="RESTABLECIDO"),
    )
    assert resp == {"batchItemFailures": []}
    assert len(puts) == 2
    by_zone = {c["body"]["zone_id"]: c["body"] for c in puts}
    assert by_zone["Z01"]["status"] == "CONFIRMADO" and by_zone["Z02"]["status"] == "RESTABLECIDO"


def test_eventos_que_no_aplican_se_descartan_sin_error(configured, puts):
    malos = [
        record(1, kind="report.created"),
        record(2, status="DESCONOCIDO"),
        record(3, zone="../Z01"),
        record(4, zone="Z0 1"),
        {"messageId": "m5", "body": "no es json"},
        {"messageId": "m6", "body": json.dumps({"detail": {"type": "incident.updated", "data": {}}})},
        record(7, at=""),
    ]
    assert run(*malos) == {"batchItemFailures": []}
    assert puts == []


def test_fallo_de_una_zona_devuelve_solo_sus_mensajes(configured, puts):
    puts.fail.append("/Z02")
    resp = run(record(1, zone="Z01"), record(2, zone="Z02"), record(3, zone="Z02", at="2026-11-15T11:00:00.000Z"))
    assert sorted(f["itemIdentifier"] for f in resp["batchItemFailures"]) == ["m2", "m3"]


def test_sin_configurar_devuelve_todo_a_la_cola(aws, puts):
    resp = run(record(1), record(2, zone="Z02"))
    assert [f["itemIdentifier"] for f in resp["batchItemFailures"]] == ["m1", "m2"]
    assert puts == []


def test_parametros_pendiente_devuelven_todo_a_la_cola(aws, puts):
    ssm = boto3.client("ssm")
    ssm.put_parameter(Name="/red-telecorp/test/azure/base_url", Value="PENDIENTE", Type="String")
    ssm.put_parameter(Name="/red-telecorp/test/azure/api_key", Value="PENDIENTE", Type="SecureString")
    assert [f["itemIdentifier"] for f in run(record(1))["batchItemFailures"]] == ["m1"]
    assert puts == []


def test_sin_tiempo_el_resto_vuelve_a_la_cola(configured, puts):
    class Contexto:
        def __init__(self):
            self.ms = 16000  # alcanza para una llamada (16 s - 3 s de reserva = 13 s) y luego no

        def get_remaining_time_in_millis(self):
            ms, self.ms = self.ms, self.ms - 12000
            return ms

    resp = run(record(1, zone="Z01"), record(2, zone="Z02"), record(3, zone="Z03"), context=Contexto())
    assert len(puts) == 1 and puts[0]["body"]["zone_id"] == "Z01" and puts[0]["timeout"] == 10
    assert sorted(f["itemIdentifier"] for f in resp["batchItemFailures"]) == ["m2", "m3"]


def test_sin_registros(configured, puts):
    assert publisher.handler({"Records": []}, None) == {"batchItemFailures": []}
    assert puts == []


def test_los_logs_no_llevan_clave_ni_datos_personales(configured, puts, caplog):
    puts.fail.append("/Z01")
    with caplog.at_level("INFO"):
        run(record(1, customer_id="12345678"))
    assert CLAVE not in caplog.text and "12345678" not in caplog.text
