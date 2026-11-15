"""AutorizarJWT: autorizador Lambda del HTTP API (carga 2.0, respuesta simple).

Devuelve `{"isAuthorized": bool, "context": {"sub", "role"}}`. Un token inválido nunca lanza:
se responde con isAuthorized false. El token no se escribe en logs.
"""
from common import auth, http

_ROLES = ("CUSTOMER", "OPERATOR")
_DENY = {"isAuthorized": False, "context": {}}


def _bearer_token(event) -> str | None:
    value = http.header(event, "Authorization")
    if not isinstance(value, str):
        return None
    parts = value.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1]


def handler(event, context):
    token = _bearer_token(event)
    if token is None:
        return dict(_DENY)
    try:
        claims = auth.verify_token(token)
    except auth.AuthError:
        return dict(_DENY)
    if claims["role"] not in _ROLES:
        return dict(_DENY)
    return {"isAuthorized": True, "context": {"sub": claims["sub"], "role": claims["role"]}}
