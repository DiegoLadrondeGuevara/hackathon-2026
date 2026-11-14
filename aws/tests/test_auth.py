import base64
import hashlib
import hmac
import json

import boto3
import pytest

from common import auth

KEY = "clave-de-prueba"
NOW = 1_800_000_000


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _seg(obj: dict) -> str:
    return _b64url(json.dumps(obj).encode("utf-8"))


def _forge(header: dict, payload: dict, key: str = KEY) -> str:
    """Token firmado correctamente con HS256 sobre la cabecera y carga dadas."""
    signing_input = f"{_seg(header)}.{_seg(payload)}"
    sig = hmac.new(key.encode(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64url(sig)}"


def _payload(**over) -> dict:
    base = {"sub": "12345678", "role": "CUSTOMER", "iss": "red-telecorp", "iat": NOW, "exp": NOW + 900}
    base.update(over)
    return {k: v for k, v in base.items() if v is not None}


HS256 = {"alg": "HS256", "typ": "JWT"}


# --- Contraseñas ---

def test_hash_formato_y_verificacion():
    stored = auth.hash_password("Secreta#1")
    parts = stored.split("$")
    assert parts[:4] == ["scrypt", "16384", "8", "1"] and len(parts) == 6
    assert len(base64.b64decode(parts[4])) == 16 and len(base64.b64decode(parts[5])) == 32
    assert auth.verify_password("Secreta#1", stored)
    assert not auth.verify_password("secreta#1", stored)
    assert not auth.verify_password("", stored)


def test_hash_usa_salt_distinto():
    a, b = auth.hash_password("misma"), auth.hash_password("misma")
    assert a != b
    assert auth.verify_password("misma", a) and auth.verify_password("misma", b)


def test_hash_acepta_unicode():
    stored = auth.hash_password("contraseña-ñandú")
    assert auth.verify_password("contraseña-ñandú", stored)


def test_hash_respeta_parametros_guardados():
    salt = b"0123456789abcdef"
    digest = hashlib.scrypt(b"clave", salt=salt, n=1024, r=8, p=1, dklen=32)
    stored = f"scrypt$1024$8$1${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"
    assert auth.verify_password("clave", stored)
    assert not auth.verify_password("otra", stored)


@pytest.mark.parametrize(
    "stored",
    [
        "",
        "texto-plano",
        "bcrypt$16384$8$1$c2FsdA==$aGFzaA==",
        "scrypt$16384$8$1$c2FsdA==",
        "scrypt$x$8$1$c2FsdA==$aGFzaA==",
        "scrypt$16384$8$1$no-base64!$aGFzaA==",
        "scrypt$16384$8$1$$",
        "scrypt$1000$8$1$c2FsdA==$aGFzaA==",  # n no es potencia de 2
        "scrypt$1073741824$8$1$c2FsdA==$aGFzaA==",  # n fuera de rango
        "scrypt$16384$1024$1$c2FsdA==$aGFzaA==",  # r fuera de rango
        "scrypt$16384$8$0$c2FsdA==$aGFzaA==",
        None,
    ],
)
def test_hash_mal_formado_es_false(stored):
    assert auth.verify_password("clave", stored) is False


# --- JWT ---

def test_token_valido():
    token = auth.issue_token("12345678", "CUSTOMER", key=KEY, now=NOW)
    assert token.count(".") == 2 and "=" not in token
    header = json.loads(base64.urlsafe_b64decode(token.split(".")[0] + "=="))
    assert header == HS256
    claims = auth.verify_token(token, key=KEY, now=NOW + 60)
    assert claims == {"sub": "12345678", "role": "CUSTOMER", "iss": "red-telecorp", "iat": NOW, "exp": NOW + 900}
    assert all(not isinstance(v, float) for v in claims.values())


def test_token_vencido():
    token = auth.issue_token("12345678", "CUSTOMER", key=KEY, now=NOW)
    assert auth.verify_token(token, key=KEY, now=NOW + 899)["sub"] == "12345678"
    for later in (NOW + 900, NOW + 5000):
        with pytest.raises(auth.AuthError):
            auth.verify_token(token, key=KEY, now=later)


def test_token_vencido_con_reloj_real():
    token = auth.issue_token("12345678", "CUSTOMER", key=KEY, now=NOW - 10_000_000_000)
    with pytest.raises(auth.AuthError):
        auth.verify_token(token, key=KEY)
    assert auth.verify_token(auth.issue_token("1", "OPERATOR", key=KEY), key=KEY)["role"] == "OPERATOR"


def test_firma_alterada():
    token = auth.issue_token("12345678", "CUSTOMER", key=KEY, now=NOW)
    head, payload, sig = token.split(".")
    otra = ("A" if sig[0] != "A" else "B") + sig[1:]
    for bad in (f"{head}.{payload}.{otra}", f"{head}.{payload}.", f"{head}.{payload}.{sig}x", f"{head}.{payload}.ñ"):
        with pytest.raises(auth.AuthError):
            auth.verify_token(bad, key=KEY, now=NOW)


def test_payload_alterado():
    token = auth.issue_token("12345678", "CUSTOMER", key=KEY, now=NOW)
    head, _, sig = token.split(".")
    with pytest.raises(auth.AuthError):
        auth.verify_token(f"{head}.{_seg(_payload(role='OPERATOR'))}.{sig}", key=KEY, now=NOW)


def test_clave_distinta():
    token = auth.issue_token("12345678", "CUSTOMER", key="otra-clave", now=NOW)
    with pytest.raises(auth.AuthError):
        auth.verify_token(token, key=KEY, now=NOW)


@pytest.mark.parametrize("alg", ["none", "None", "NONE", "hs256", "HS512", "RS256", "", None])
def test_alg_distinto_de_hs256_se_rechaza(alg):
    header = {"typ": "JWT"} if alg is None else {"alg": alg, "typ": "JWT"}
    sin_firma = f"{_seg(header)}.{_seg(_payload())}."
    # Ni sin firma ni con una firma HS256 válida sobre esa cabecera.
    for token in (sin_firma, _forge(header, _payload())):
        with pytest.raises(auth.AuthError):
            auth.verify_token(token, key=KEY, now=NOW)


@pytest.mark.parametrize(
    "token",
    ["", "abc", "a.b", "a.b.c.d", "!!.!!.!!", f"{_b64url(b'[1]')}.{_b64url(b'{}')}.x", None, 123],
)
def test_token_mal_formado(token):
    with pytest.raises(auth.AuthError):
        auth.verify_token(token, key=KEY, now=NOW)


@pytest.mark.parametrize(
    "payload",
    [
        _payload(iss="otro"),
        _payload(iss=None),
        _payload(sub=None),
        _payload(sub=""),
        _payload(role=None),
        _payload(role=7),
        _payload(exp=None),
        _payload(exp=str(NOW + 900)),
        _payload(exp=True),
    ],
)
def test_claims_invalidos_con_firma_correcta(payload):
    with pytest.raises(auth.AuthError):
        auth.verify_token(_forge(HS256, payload), key=KEY, now=NOW)


def test_payload_que_no_es_objeto():
    signing_input = f"{_seg(HS256)}.{_b64url(b'[1,2]')}"
    sig = hmac.new(KEY.encode(), signing_input.encode(), hashlib.sha256).digest()
    with pytest.raises(auth.AuthError):
        auth.verify_token(f"{signing_input}.{_b64url(sig)}", key=KEY, now=NOW)


def test_clave_desde_ssm(aws):
    boto3.client("ssm").put_parameter(
        Name="/red-telecorp/test/jwt/signing_key", Value="clave-ssm", Type="SecureString"
    )
    token = auth.issue_token("OP001", "OPERATOR")
    assert auth.verify_token(token)["sub"] == "OP001"
    assert auth.verify_token(token, key="clave-ssm")["role"] == "OPERATOR"
    with pytest.raises(auth.AuthError):
        auth.verify_token(token, key="otra")


def test_clave_vacia_no_firma():
    with pytest.raises(ValueError):
        auth.issue_token("1", "CUSTOMER", key="")
