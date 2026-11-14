"""Configuración: nombres de tablas (variables de entorno) y secretos (SSM)."""
import os
from functools import cache

import boto3

# Nombre lógico -> variable de entorno con el nombre físico (ver contracts/infra.md)
TABLES = {
    "Reports": "TABLE_REPORTS",
    "Incidents": "TABLE_INCIDENTS",
    "Telemetry": "TABLE_TELEMETRY",
    "CorrelationMembers": "TABLE_CORRELATION_MEMBERS",
    "NetworkCatalog": "TABLE_NETWORK_CATALOG",
    "CustomerProfiles": "TABLE_CUSTOMER_PROFILES",
    "Outbox": "TABLE_OUTBOX",
}


def table_name(logical: str) -> str:
    return os.environ[TABLES[logical]]


def ssm_prefix() -> str:
    return os.environ.get("SSM_PREFIX", "/red-telecorp/dev")


@cache
def get_secret(name: str) -> str:
    """Lee `<SSM_PREFIX>/<name>` (con descifrado). Se cachea por contenedor de Lambda."""
    client = boto3.client("ssm")
    resp = client.get_parameter(Name=f"{ssm_prefix()}/{name}", WithDecryption=True)
    return resp["Parameter"]["Value"]
