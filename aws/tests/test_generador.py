"""scripts/generador.py: pausar y reanudar el simulador de antenas sin volver a desplegar."""
import importlib.util
from pathlib import Path

import boto3
import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "generador.py"
STAGE = ["--stage", "test"]
NOMBRE = "red-telecorp-test-GeneradoraDeMetricasYLotesEventsRu-AbC123"


@pytest.fixture
def generador(aws):
    spec = importlib.util.spec_from_file_location("generador", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    events = boto3.client("events")
    events.put_rule(Name=NOMBRE, ScheduleExpression="rate(1 minute)", State="ENABLED")
    events.put_rule(Name="red-telecorp-test-OtraRegla", ScheduleExpression="rate(5 minutes)", State="ENABLED")
    return mod, events


def _estado(events, nombre=NOMBRE):
    return events.describe_rule(Name=nombre)["State"]


def test_estado_no_cambia_nada(generador, capsys):
    mod, events = generador
    mod.main(["estado", *STAGE])
    assert "ACTIVO" in capsys.readouterr().out and _estado(events) == "ENABLED"


def test_pausar_y_reanudar_solo_tocan_la_regla_del_simulador(generador, capsys):
    mod, events = generador
    mod.main(["pausar", *STAGE])
    assert "PAUSADO" in capsys.readouterr().out
    assert _estado(events) == "DISABLED" and _estado(events, "red-telecorp-test-OtraRegla") == "ENABLED"
    mod.main(["reanudar", *STAGE])
    assert "ACTIVO" in capsys.readouterr().out and _estado(events) == "ENABLED"


def test_pausar_es_idempotente(generador):
    mod, events = generador
    mod.main(["pausar", *STAGE])
    mod.main(["pausar", *STAGE])
    assert _estado(events) == "DISABLED"


def test_sin_regla_desplegada_avisa(aws):
    spec = importlib.util.spec_from_file_location("generador", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(SystemExit, match="desplegado"):
        mod.main(["estado", *STAGE])
