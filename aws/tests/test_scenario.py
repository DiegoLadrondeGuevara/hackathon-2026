"""scripts/scenario.py: activar, ver y limpiar el escenario de antenas."""
import importlib.util
from decimal import Decimal
from pathlib import Path

import pytest

from common import ddb, ids

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "scenario.py"
STAGE = ["--stage", "test"]
KEY = {"pk": "SCENARIO#ACTIVE", "sk": "META"}


@pytest.fixture
def scenario(aws):
    spec = importlib.util.spec_from_file_location("scenario", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for antenna_id, zone in (("A013", "Z05"), ("A014", "Z05"), ("A001", "Z01")):
        ddb.table("NetworkCatalog").put_item(Item={
            "pk": f"ANTENNA#{antenna_id}", "sk": "META", "type": "ANTENNA", "antenna_id": antenna_id,
            "zone_id": zone, "nominal_gb": 95, "gsi1pk": "TYPE#ANTENNA", "gsi1sk": antenna_id,
            "gsi2pk": f"ZONE#{zone}", "gsi2sk": f"ANTENNA#{antenna_id}",
        })
    return mod


def _item():
    return ddb.table("NetworkCatalog").get_item(Key=KEY).get("Item")


def test_activar_por_antena_guarda_decimales_y_expiracion(scenario, capsys):
    antes = ids.now_iso()
    scenario.main(["activar", "--antena", "a013=0", "--antena", "A014=40.5", "--minutos", "30", *STAGE])
    item = _item()
    assert item["type"] == "SCENARIO" and item["overrides"] == {"A013": Decimal("0"), "A014": Decimal("40.5")}
    assert all(isinstance(v, Decimal) for v in item["overrides"].values())
    assert ids.shift_iso(antes, minutes=30) <= item["expires_at"] <= ids.shift_iso(ids.now_iso(), minutes=30)
    salida = capsys.readouterr().out
    assert "A013: 0 GB/min (INHABILITADA)" in salida and "A014: 40.5 GB/min (CAIDA)" in salida


def test_activar_por_zona_y_reemplazo_del_escenario_anterior(scenario):
    scenario.main(["activar", "--antena", "A001=150", *STAGE])
    scenario.main(["activar", "--zona", "z05", "--gb", "0", "--antena", "A014=140", *STAGE])
    assert _item()["overrides"] == {"A013": Decimal("0"), "A014": Decimal("140")}


def test_el_generador_aplica_el_escenario_del_script(scenario, monkeypatch):
    import boto3

    from handlers import generadora_de_metricas_y_lotes as generadora

    boto3.client("s3").create_bucket(Bucket="metricas-test")
    monkeypatch.setenv("METRICS_BUCKET", "metricas-test")
    monkeypatch.setenv("QUEUE_METRICAS_URL", boto3.client("sqs").create_queue(QueueName="metricas")["QueueUrl"])
    scenario.main(["activar", "--antena", "A013=0", *STAGE])
    assert generadora.handler({}, None)["overrides"] == 1
    scenario.main(["limpiar", *STAGE])
    assert _item() is None and generadora.handler({}, None)["overrides"] == 0


def test_ver_y_limpiar(scenario, capsys):
    scenario.main(["ver", *STAGE])
    assert "sin escenario" in capsys.readouterr().out
    scenario.main(["activar", "--antena", "A013=0", *STAGE])
    capsys.readouterr()
    scenario.main(["ver", *STAGE])
    assert "escenario activo" in capsys.readouterr().out
    scenario.main(["limpiar", *STAGE])
    scenario.main(["limpiar", *STAGE])  # limpiar dos veces no falla
    assert _item() is None


@pytest.mark.parametrize("args", [
    ["activar"], ["activar", "--antena", "A013"], ["activar", "--antena", "A013=-1"],
    ["activar", "--antena", "A013=mucho"], ["activar", "--antena", "A013=NaN"], ["activar", "--antena", "A999=0"],
    ["activar", "--zona", "Z05"], ["activar", "--zona", "Z99", "--gb", "0"],
    ["activar", "--antena", "A013=0", "--minutos", "0"],
])
def test_argumentos_invalidos_no_escriben(scenario, args):
    with pytest.raises(SystemExit):
        scenario.main([*args, *STAGE])
    assert _item() is None
