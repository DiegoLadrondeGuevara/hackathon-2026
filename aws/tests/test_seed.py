import importlib.util
from collections import Counter
from pathlib import Path

import pytest
from boto3.dynamodb.conditions import Key

from common import auth, ddb

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "seed.py"
ARGS = ["--stage", "test"]
PASSWORD = "clave-de-prueba"


def load():
    spec = importlib.util.spec_from_file_location("seed", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def seed(aws, monkeypatch):
    mod = load()
    monkeypatch.setenv(mod.PASSWORD_ENV, PASSWORD)
    return mod


def scan(logical: str) -> list:
    return ddb.table(logical).scan()["Items"]


def has_float(value) -> bool:
    if isinstance(value, float):
        return True
    if isinstance(value, dict):
        return any(has_float(v) for v in value.values())
    if isinstance(value, list | set):
        return any(has_float(v) for v in value)
    return False


def test_seed_carga_conteos_del_contrato(seed):
    seed.main(ARGS)
    catalog = Counter(item["type"] for item in scan("NetworkCatalog"))
    profiles = Counter(item["type"] for item in scan("CustomerProfiles"))
    assert catalog == {"ZONE": 12, "ANTENNA": 30}
    assert profiles == {"OPERATOR": 1, "CUSTOMER": 20}


def test_seed_dos_corridas_no_duplican_ni_cambian_perfiles(seed, capsys):
    seed.main(ARGS)
    before = {item["pk"]: item for item in scan("CustomerProfiles")}
    seed.main(ARGS)
    after = {item["pk"]: item for item in scan("CustomerProfiles")}
    assert after == before  # mismo hash y mismo created_at
    assert len(scan("NetworkCatalog")) == 42
    assert "0 perfiles escritos, 21 ya existían" in capsys.readouterr().out


def test_seed_force_reescribe_el_hash(seed, monkeypatch):
    seed.main(ARGS)
    key = {"pk": "CUSTOMER#70000001", "sk": "PROFILE"}
    old = ddb.table("CustomerProfiles").get_item(Key=key)["Item"]["password_hash"]
    monkeypatch.setenv(seed.PASSWORD_ENV, "otra-clave")
    seed.main([*ARGS, "--force"])
    new = ddb.table("CustomerProfiles").get_item(Key=key)["Item"]["password_hash"]
    assert new != old
    assert auth.verify_password("otra-clave", new)
    assert len(scan("CustomerProfiles")) == 21


def test_zonas_salen_por_gsi1_type(seed):
    seed.main(ARGS)
    zones = ddb.query_all(
        "NetworkCatalog", IndexName="GSI1-type", KeyConditionExpression=Key("gsi1pk").eq("TYPE#ZONE")
    )
    assert [z["zone_id"] for z in zones] == [f"Z{n:02d}" for n in range(1, 13)]
    by_id = {z["zone_id"]: z for z in zones}
    assert by_id["Z01"]["name"] == "Miraflores" and by_id["Z01"]["criticality"] == 1
    assert by_id["Z02"]["zone_type"] == "CRITICA" and by_id["Z02"]["criticality"] == 5
    assert by_id["Z09"]["zone_type"] == "MEDICA" and by_id["Z09"]["criticality"] == 4
    assert all(z["est_users"] > 0 and z["est_users"] % 1 == 0 for z in zones)


def test_antenas_por_tipo_y_por_zona(seed):
    seed.main(ARGS)
    antennas = ddb.query_all(
        "NetworkCatalog", IndexName="GSI1-type", KeyConditionExpression=Key("gsi1pk").eq("TYPE#ANTENNA")
    )
    assert [a["antenna_id"] for a in antennas] == [f"A{n:03d}" for n in range(1, 31)]
    assert all(a["nominal_gb"] == 95 for a in antennas)
    for n in range(1, 13):
        zone_id = f"Z{n:02d}"
        in_zone = ddb.query_all(
            "NetworkCatalog", IndexName="GSI2-zone", KeyConditionExpression=Key("gsi2pk").eq(f"ZONE#{zone_id}")
        )
        assert len(in_zone) == (3 if n <= 6 else 2)
        assert all(a["zone_id"] == zone_id for a in in_zone)


def test_perfiles_cumplen_el_contrato(seed):
    seed.main(ARGS)
    table = ddb.table("CustomerProfiles")
    operator = table.get_item(Key={"pk": "OPERATOR#OP001", "sk": "PROFILE"})["Item"]
    assert operator["role"] == "OPERATOR"
    assert auth.verify_password(PASSWORD, operator["password_hash"])

    customers = [item for item in scan("CustomerProfiles") if item["type"] == "CUSTOMER"]
    assert sorted(c["customer_id"] for c in customers) == [str(70000000 + n) for n in range(1, 21)]
    assert len({c["password_hash"] for c in customers}) == 20  # sal distinta por cliente
    for c in customers:
        assert c["pk"] == f"CUSTOMER#{c['customer_id']}" and c["role"] == "CUSTOMER"
        assert c["password_hash"].startswith("scrypt$")
        assert c["email"].endswith("@example.com")
        assert c["phone"].startswith("+51") and len(c["phone"]) == 12
        assert c["channel_pref"] == "EMAIL" and c["consent_sms"] is False
        assert c["consent_at"].endswith("Z") and c["created_at"].endswith("Z")
    assert sum(1 for c in customers if not c["consent_email"]) == 2
    first = table.get_item(Key={"pk": "CUSTOMER#70000001", "sk": "PROFILE"})["Item"]
    assert auth.verify_password(PASSWORD, first["password_hash"])
    assert not auth.verify_password("incorrecta", first["password_hash"])


@pytest.mark.parametrize("value", [None, ""])
def test_sin_variable_de_entorno_aborta_sin_escribir(seed, monkeypatch, value):
    if value is None:
        monkeypatch.delenv(seed.PASSWORD_ENV)
    else:
        monkeypatch.setenv(seed.PASSWORD_ENV, value)
    with pytest.raises(SystemExit) as exc:
        seed.main(ARGS)
    assert seed.PASSWORD_ENV in str(exc.value)
    assert scan("NetworkCatalog") == [] and scan("CustomerProfiles") == []


def test_no_imprime_la_clave_ni_usa_float(seed, capsys):
    seed.main(ARGS)
    assert PASSWORD not in capsys.readouterr().out
    items = seed.zone_items() + seed.antenna_items() + [seed.customer_item(1, PASSWORD, "2026-11-14T00:00:00.000Z")]
    assert not any(has_float(item) for item in items)
