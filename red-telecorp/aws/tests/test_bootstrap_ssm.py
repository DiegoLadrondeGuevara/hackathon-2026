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
