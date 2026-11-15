"""scripts/load_test.py: N reportes de una zona (con el API simulado)."""
import importlib.util
import threading
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "load_test.py"
CLAVE = "clave-secreta-de-demo"
URL = "https://api.example.com"


@pytest.fixture
def lt(monkeypatch):
    spec = importlib.util.spec_from_file_location("load_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setenv("SEED_DEMO_PASSWORD", CLAVE)
    monkeypatch.delenv("SMOKE_BASE_URL", raising=False)
    monkeypatch.setattr(mod, "POLL_SECONDS", 0)
    pausas = []
    monkeypatch.setattr(mod.time, "sleep", pausas.append)  # sin esperas reales en las pruebas
    mod.pausas = pausas
    return mod


class FakeApi:
    def __init__(self, lt, monkeypatch, report_status=201, incident=True, login_status=200):
        self.lock = threading.Lock()
        self.reports, self.logins, self.keys = [], [], []
        self.report_status, self.incident, self.login_status = report_status, incident, login_status
        self.incident_polls = 0
        monkeypatch.setattr(lt.smoke, "call", self.call)

    def call(self, base_url, method, path, token=None, body=None, headers=None):
        with self.lock:
            if path == "/auth/login":
                self.logins.append(body["identifier"])
                if self.login_status != 200:
                    return self.login_status, {"error": {"code": "UNAUTHORIZED"}}
                return 200, {"token": f"tok-{body['identifier']}"}
            if path == "/reportes":
                self.reports.append((token, body))
                self.keys.append(headers["Idempotency-Key"])
                status = self.report_status(len(self.reports)) if callable(self.report_status) else self.report_status
                return status, {"report_id": "R"} if status == 201 else {"error": {"code": "INTERNAL"}}
            if path.startswith("/incidentes"):
                self.incident_polls += 1
                items = [{"incident_id": "I1", "service": "INTERNET", "status": "EVALUACION"}] if self.incident else []
                return 200, {"items": items}
        raise AssertionError(path)


def _main(lt, *args):
    return lt.main(["--base-url", URL, *args])


def test_envia_n_reportes_repartidos_entre_clientes(lt, monkeypatch, capsys):
    api = FakeApi(lt, monkeypatch)
    assert _main(lt, "--zona", "z05", "-n", "25", "--clientes", "10") == 0
    assert len(api.reports) == 25 and len(set(api.keys)) == 25
    assert api.logins == [str(70000001 + n) for n in range(10)]
    assert {body["zone_id"] for _, body in api.reports} == {"Z05"}
    assert {body["service"] for _, body in api.reports} == {"INTERNET"}
    assert len({token for token, _ in api.reports}) == 10
    assert len({body["service_number"] for _, body in api.reports}) == 25
    salida = capsys.readouterr().out
    assert "enviados 25, creados 25, fallidos 0" in salida and "p95" in salida
    assert "incidente activo I1 en Z05" in salida


def test_no_imprime_clave_ni_tokens(lt, monkeypatch, capsys):
    FakeApi(lt, monkeypatch)
    _main(lt, "-n", "12")
    salida = capsys.readouterr().out
    assert CLAVE not in salida and "tok-" not in salida


def test_fallos_se_cuentan_por_codigo_y_dan_codigo_1(lt, monkeypatch, capsys):
    FakeApi(lt, monkeypatch, report_status=lambda n: 500 if n % 5 == 0 else 201)
    assert _main(lt, "-n", "20", "--espera", "0") == 1
    salida = capsys.readouterr().out
    assert "enviados 20, creados 16, fallidos 4" in salida and "HTTP 500: 4" in salida


def test_sin_incidente_tras_la_espera_da_codigo_1(lt, monkeypatch, capsys):
    api = FakeApi(lt, monkeypatch, incident=False)
    assert _main(lt, "-n", "10", "--espera", "1") == 1
    assert api.incident_polls >= 1
    assert "no apareció un incidente" in capsys.readouterr().out


def test_con_menos_de_diez_clientes_no_espera_incidente(lt, monkeypatch, capsys):
    api = FakeApi(lt, monkeypatch)
    assert _main(lt, "-n", "5") == 0
    assert api.incident_polls == 0
    assert "sin espera de incidente" in capsys.readouterr().out


def test_espera_cero_omite_el_incidente(lt, monkeypatch):
    api = FakeApi(lt, monkeypatch)
    assert _main(lt, "-n", "10", "--espera", "0") == 0
    assert api.incident_polls == 0


def test_servicio_movil(lt, monkeypatch):
    api = FakeApi(lt, monkeypatch)
    _main(lt, "-n", "3", "--servicio", "MOVIL", "--espera", "0")
    assert {body["service"] for _, body in api.reports} == {"MOVIL"}


def test_login_fallido_aborta_sin_enviar(lt, monkeypatch):
    api = FakeApi(lt, monkeypatch, login_status=401)
    with pytest.raises(SystemExit) as exc:
        _main(lt, "-n", "5")
    assert "login" in str(exc.value) and CLAVE not in str(exc.value)
    assert api.reports == []


def test_falta_clave_o_url(lt, monkeypatch):
    monkeypatch.delenv("SEED_DEMO_PASSWORD")
    with pytest.raises(SystemExit, match="SEED_DEMO_PASSWORD"):
        _main(lt)
    monkeypatch.setenv("SEED_DEMO_PASSWORD", CLAVE)
    with pytest.raises(SystemExit, match="base-url"):
        lt.main([])


@pytest.mark.parametrize("args", [["-n", "0"], ["-n", "1001"], ["--hilos", "0"], ["--hilos", "5"],
                                  ["--clientes", "21"], ["--espera", "-1"], ["--zona", " "],
                                  ["--pausa", "-1"], ["--pausa", "11"]])
def test_argumentos_fuera_de_rango(lt, monkeypatch, args):
    api = FakeApi(lt, monkeypatch)
    with pytest.raises(SystemExit):
        _main(lt, *args)
    assert api.logins == []


def test_percentil(lt):
    valores = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10]
    assert lt.percentile(valores, 50) == 5 and lt.percentile(valores, 95) == 10
    assert lt.percentile([], 50) == 0.0 and lt.percentile([7], 95) == 7


def test_pausa_por_defecto_entre_reportes(lt, monkeypatch):
    FakeApi(lt, monkeypatch)
    assert _main(lt, "-n", "4", "--espera", "0") == 0
    assert lt.pausas.count(lt.DEFAULT_PAUSE) == 4


def test_pausa_configurable_y_cero(lt, monkeypatch):
    FakeApi(lt, monkeypatch)
    _main(lt, "-n", "3", "--espera", "0", "--pausa", "1.5")
    assert lt.pausas.count(1.5) == 3
    lt.pausas.clear()
    _main(lt, "-n", "3", "--espera", "0", "--pausa", "0")
    assert lt.pausas.count(0.0) == 3
