"""Sanitización antes de cruzar el límite de AWS; no modifica el objeto original."""
import hashlib

FORBIDDEN = frozenset({
    "customer_id", "description", "location_text", "actor", "service_number",
    "email", "phone", "full_name", "password", "password_hash", "operator_id",
})


def customer_hash(salt: str, customer_id: str) -> str:
    if not isinstance(salt, str) or not salt or salt == "PENDIENTE":
        raise ValueError("Sal no configurada")
    if not isinstance(customer_id, str) or not customer_id:
        raise ValueError("Identificador inválido")
    return hashlib.sha256((salt + customer_id).encode("utf-8")).hexdigest()[:16]


def strip_pii(data):
    if isinstance(data, dict):
        return {k: strip_pii(v) for k, v in data.items() if k.lower() not in FORBIDDEN}
    if isinstance(data, list):
        return [strip_pii(v) for v in data]
    return data
