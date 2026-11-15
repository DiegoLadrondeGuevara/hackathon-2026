"""AutenticarUsuario: POST /auth/login (público).

Busca el perfil como CUSTOMER y luego como OPERATOR, verifica la clave
con scrypt y emite un JWT HS256. Usuario inexistente y clave incorrecta responden igual.
"""
from common import auth, ddb, http

_MAX_IDENTIFIER = 64
_MAX_PASSWORD = 256
_PREFIXES = ("CUSTOMER", "OPERATOR")
_INVALID = "Credenciales inválidas"

# Hash de relleno: si el usuario no existe se verifica contra este, para que el tiempo de
# respuesta no revele qué identificadores están registrados. Se calcula una vez por contenedor.
_DUMMY_HASH = auth.hash_password("relleno-sin-uso")


def _text(body: dict, name: str, max_len: int) -> str:
    value = body.get(name)
    if not isinstance(value, str) or not value or len(value) > max_len:
        raise http.ApiError("VALIDATION", f"El campo {name} es obligatorio")
    return value


def _find_profile(identifier: str) -> dict | None:
    table = ddb.table("CustomerProfiles")
    for prefix in _PREFIXES:
        item = table.get_item(Key={"pk": f"{prefix}#{identifier}", "sk": "PROFILE"}).get("Item")
        if item:
            return item
    return None


@http.api
def handler(event, context):
    body = http.json_body(event)
    identifier = _text(body, "identifier", _MAX_IDENTIFIER).strip()
    password = _text(body, "password", _MAX_PASSWORD)

    profile = _find_profile(identifier) if identifier else None
    stored = profile.get("password_hash") if profile else None
    valid = auth.verify_password(password, stored if isinstance(stored, str) else _DUMMY_HASH)
    role = profile.get("role") if profile else None
    if not valid or not isinstance(stored, str) or role not in _PREFIXES:
        raise http.ApiError("UNAUTHORIZED", _INVALID)

    return http.response(
        200,
        {
            "token": auth.issue_token(identifier, role),
            "expires_in": auth.TOKEN_TTL_SECONDS,
            "role": role,
            "name": profile.get("full_name", ""),
        },
    )
