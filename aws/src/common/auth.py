"""Autenticación: hash de contraseñas con scrypt y JWT HS256, solo con stdlib.

Formato del hash (contracts/tables.md): `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`.
Claims del token (contracts/flows.md): sub, role, iss, iat, exp (15 min).
"""
import base64
import hashlib
import hmac
import json
import os
import time

from . import config

ISSUER = "red-telecorp"
TOKEN_TTL_SECONDS = 900
SIGNING_KEY_PARAM = "jwt/signing_key"

SCRYPT_N = 16384
SCRYPT_R = 8
SCRYPT_P = 1
_SALT_BYTES = 16
_HASH_BYTES = 32
# Topes al verificar: un hash guardado con parámetros absurdos no debe agotar la Lambda.
_MAX_N = 32768
_MAX_R = 16
_MAX_P = 4

_ALG = "HS256"
_HEADER = {"alg": _ALG, "typ": "JWT"}


class AuthError(Exception):
    """Token inválido. El mensaje no lleva datos del token."""


# --- Contraseñas ---

def _scrypt(password: str, salt: bytes, n: int, r: int, p: int, dklen: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=dklen)


def hash_password(password: str) -> str:
    salt = os.urandom(_SALT_BYTES)
    digest = _scrypt(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P, _HASH_BYTES)
    return "$".join(
        [
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    """True si la contraseña corresponde al hash. Nunca lanza: hash mal formado es False."""
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    parts = stored.split("$")
    if len(parts) != 6 or parts[0] != "scrypt":
        return False
    try:
        n, r, p = int(parts[1]), int(parts[2]), int(parts[3])
        salt = base64.b64decode(parts[4], validate=True)
        expected = base64.b64decode(parts[5], validate=True)
        if not (2 <= n <= _MAX_N and n & (n - 1) == 0 and 1 <= r <= _MAX_R and 1 <= p <= _MAX_P):
            return False
        if not salt or not expected:
            return False
        actual = _scrypt(password, salt, n, r, p, len(expected))
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


# --- JWT HS256 ---

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4))


def _key_bytes(key: str | None) -> bytes:
    value = key if key is not None else config.get_secret(SIGNING_KEY_PARAM)
    if not value:
        raise ValueError("La clave de firma está vacía")
    return value.encode("utf-8")


def _sign(signing_input: str, key: bytes) -> str:
    return _b64url(hmac.new(key, signing_input.encode("ascii"), hashlib.sha256).digest())


def _dumps(obj: dict) -> bytes:
    return json.dumps(obj, separators=(",", ":")).encode("utf-8")


def issue_token(sub: str, role: str, *, key: str | None = None, now: int | None = None) -> str:
    """Emite un JWT HS256. `key` y `now` (epoch en segundos) solo se pasan en pruebas."""
    iat = int(time.time()) if now is None else now
    payload = {"sub": sub, "role": role, "iss": ISSUER, "iat": iat, "exp": iat + TOKEN_TTL_SECONDS}
    signing_input = f"{_b64url(_dumps(_HEADER))}.{_b64url(_dumps(payload))}"
    return f"{signing_input}.{_sign(signing_input, _key_bytes(key))}"


def _decode_json(segment: str) -> dict:
    try:
        data = json.loads(_b64url_decode(segment))
    except ValueError as exc:  # incluye binascii.Error y UnicodeDecodeError
        raise AuthError("Token mal formado") from exc
    if not isinstance(data, dict):
        raise AuthError("Token mal formado")
    return data


def _is_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def verify_token(token: str, *, key: str | None = None, now: int | None = None) -> dict:
    """Devuelve los claims si el token es válido; si no, lanza AuthError."""
    if not isinstance(token, str):
        raise AuthError("Token mal formado")
    parts = token.split(".")
    if len(parts) != 3:
        raise AuthError("Token mal formado")
    header_b64, payload_b64, signature = parts

    # El algoritmo se fija aquí: nunca se elige según la cabecera del token.
    if _decode_json(header_b64).get("alg") != _ALG:
        raise AuthError("Algoritmo no permitido")

    try:
        expected = _sign(f"{header_b64}.{payload_b64}", _key_bytes(key))
    except UnicodeEncodeError as exc:
        raise AuthError("Token mal formado") from exc
    if not hmac.compare_digest(expected.encode("ascii"), signature.encode("utf-8")):
        raise AuthError("Firma inválida")

    claims = _decode_json(payload_b64)
    current = int(time.time()) if now is None else now
    if not _is_int(claims.get("exp")) or current >= claims["exp"]:
        raise AuthError("Token vencido")
    if claims.get("iss") != ISSUER:
        raise AuthError("Emisor inválido")
    for name in ("sub", "role"):
        if not isinstance(claims.get(name), str) or not claims[name]:
            raise AuthError("Faltan claims")
    return claims
