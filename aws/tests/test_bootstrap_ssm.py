import importlib.util
import sys
from pathlib import Path

import boto3

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "bootstrap_ssm.py"


def load():
    spec = importlib.util.spec_from_file_location("bootstrap_ssm", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_bootstrap_crea_y_no_pisa(aws, monkeypatch, capsys):
    mod = load()
    monkeypatch.setattr(sys, "argv", ["x", "--stage", "test", "--from-address", "a@b.com"])
    mod.main()
    ssm = boto3.client("ssm")
    key1 = ssm.get_parameter(Name="/red-telecorp/test/jwt/signing_key", WithDecryption=True)["Parameter"]
    assert len(key1["Value"]) > 40 and key1["Type"] == "SecureString"
    assert ssm.get_parameter(Name="/red-telecorp/test/ses/from_address")["Parameter"]["Value"] == "a@b.com"
    mod.main()  # segunda corrida: no cambia nada
    key2 = ssm.get_parameter(Name="/red-telecorp/test/jwt/signing_key", WithDecryption=True)["Parameter"]
    assert key1["Value"] == key2["Value"]
    assert "ya existe" in capsys.readouterr().out


def test_bootstrap_crea_los_parametros_de_twilio_pendientes(aws, monkeypatch):
    mod = load()
    monkeypatch.setattr(sys, "argv", ["x", "--stage", "test"])
    mod.main()
    ssm = boto3.client("ssm")
    for clave, tipo in (("account_sid", "String"), ("auth_token", "SecureString"), ("from_number", "String")):
        p = ssm.get_parameter(Name=f"/red-telecorp/test/twilio/{clave}", WithDecryption=True)["Parameter"]
        assert p["Value"] == "PENDIENTE" and p["Type"] == tipo


def test_value_env_lee_la_clave_de_una_variable_de_entorno(aws, monkeypatch, capsys):
    mod = load()
    monkeypatch.setenv("CLAVE_DE_PRUEBA", "secreto-123")
    monkeypatch.setattr(sys, "argv", ["x", "--stage", "test", "--only", "twilio/auth_token",
                                      "--value-env", "CLAVE_DE_PRUEBA", "--force"])
    mod.main()
    p = boto3.client("ssm").get_parameter(Name="/red-telecorp/test/twilio/auth_token", WithDecryption=True)["Parameter"]
    assert p["Value"] == "secreto-123" and p["Type"] == "SecureString"
    assert "secreto-123" not in capsys.readouterr().out


def test_value_env_sin_la_variable_definida_falla(aws, monkeypatch):
    import pytest
    mod = load()
    monkeypatch.delenv("NO_EXISTE_XYZ", raising=False)
    argv = ["x", "--stage", "test", "--only", "twilio/auth_token", "--value-env", "NO_EXISTE_XYZ"]
    monkeypatch.setattr(sys, "argv", argv)
    with pytest.raises(SystemExit, match="--value-env"):
        mod.main()
