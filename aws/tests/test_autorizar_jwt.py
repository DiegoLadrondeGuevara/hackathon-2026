import base64
import hashlib
import hmac
import json
import time

import boto3
import pytest

from common import auth
from handlers import autorizar_jwt

KEY = "clave-de-firma-de-prueba"
DENY = {"isAuthorized": False, "context": {}}


@pytest.fixture
def clave(aws):
    boto3.client("ssm").put_parameter(
        Name="/red-telecorp/test/jwt/signing_key", Value=KEY, Type="SecureString"
    )


def _autorizar(value, header="authorization"):
    return autorizar_jwt.handler({"headers": {header: value}}, None)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _token_con_alg(alg: str, digest) -> str:
    """Token bien firmado con la clave real, pero con otro algoritmo en la cabecera."""
    now = int(time.time())
    header = _b64url(json.dumps({"alg": alg, "typ": "JWT"}).encode())
    payload = _b64url(
        json.dumps({"sub": "70000001", "role": "CUSTOMER", "iss": auth.ISSUER, "iat": now, "exp": now + 900}).encode()
    )
    signing_input = f"{header}.{payload}"
    signature = _b64url(hmac.new(KEY.encode(), signing_input.encode(), digest).digest()) if digest else ""
    return f"{signing_input}.{signature}"


def test_token_valido_devuelve_sub_y_role(clave):
    token = auth.issue_token("op001", "OPERATOR")
    assert _autorizar(f"Bearer {token}") == {
        "isAuthorized": True,
        "context": {"sub": "op001", "role": "OPERATOR"},
    }


def test_cabecera_sin_distinguir_mayusculas(clave):
    token = auth.issue_token("70000001", "CUSTOMER")
    assert _autorizar(f"bearer {token}", header="Authorization")["isAuthorized"] is True


def test_token_vencido(clave):
    token = auth.issue_token("70000001", "CUSTOMER", now=int(time.time()) - 901)
    assert _autorizar(f"Bearer {token}") == DENY


def test_firma_alterada(clave):
    token = auth.issue_token("70000001", "CUSTOMER")
    last = "A" if token[-1] != "A" else "B"
    assert _autorizar(f"Bearer {token[:-1]}{last}") == DENY


def test_firmado_con_otra_clave(clave):
    token = auth.issue_token("70000001", "CUSTOMER", key="otra-clave")
    assert _autorizar(f"Bearer {token}") == DENY


@pytest.mark.parametrize(("alg", "digest"), [("HS512", hashlib.sha512), ("none", None)])
def test_alg_distinto_de_hs256(clave, alg, digest):
    assert _autorizar(f"Bearer {_token_con_alg(alg, digest)}") == DENY


def test_rol_desconocido(clave):
    token = auth.issue_token("70000001", "ADMIN")
    assert _autorizar(f"Bearer {token}") == DENY


@pytest.mark.parametrize(
    "value", ["", "Bearer", "Bearer ", "Basic abc", "abc.def.ghi", "Bearer a b", "Bearer no-es-jwt"]
)
def test_cabecera_mal_formada(clave, value):
    assert _autorizar(value) == DENY


@pytest.mark.parametrize("event", [{}, {"headers": None}, {"headers": {}}])
def test_sin_cabecera(clave, event):
    assert autorizar_jwt.handler(event, None) == DENY
