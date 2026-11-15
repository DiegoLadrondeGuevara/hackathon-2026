"""Public zone state projection in Azure Table Storage; no customer data."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceModifiedError, ResourceNotFoundError
from azure.data.tables import TableServiceClient, UpdateMode

STATUSES = {
    "SIN_INCIDENTE": "Sin incidencias",
    "EVALUACION": "Evaluando",
    "CONFIRMADO": "Incidencia identificada",
    "RESTABLECIDO": "Servicio restablecido",
}
PRIORITIES = {"P1", "P2", "P3"}
ZONE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
PARTITION_KEY = "ZONA"


def parse_utc(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("updated_at debe ser una fecha ISO 8601 con zona horaria")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("updated_at debe ser una fecha ISO 8601 con zona horaria") from exc
    if parsed.tzinfo is None:
        raise ValueError("updated_at debe incluir zona horaria")
    return parsed.astimezone(timezone.utc)


def validate_update(zone_id: str, body: Any) -> dict[str, str]:
    if not isinstance(body, dict):
        raise ValueError("El cuerpo debe ser un objeto JSON")
    if not ZONE_RE.fullmatch(zone_id) or body.get("zone_id") != zone_id:
        raise ValueError("zone_id inválido o distinto de la ruta")
    status = body.get("status")
    if status not in STATUSES:
        raise ValueError("status inválido")
    priority = body.get("priority")
    if priority is not None and priority not in PRIORITIES:
        raise ValueError("priority inválida")
    # Only approved public text is accepted; prevents accidental PII in the public store.
    if body.get("public_message") != STATUSES[status]:
        raise ValueError("public_message debe ser el texto público aprobado para el estado")
    updated_at = parse_utc(body.get("updated_at"))
    return {
        "PartitionKey": PARTITION_KEY,
        "RowKey": zone_id,
        "status": status,
        "priority": (priority or "") if status != "SIN_INCIDENTE" else "",
        "updated_at": updated_at.isoformat().replace("+00:00", "Z"),
        "public_message": STATUSES[status],
    }


def get_table_client():
    connection = os.environ["AZURE_STORAGE_CONNECTION_STRING"]
    table_name = os.getenv("TABLE_NAME", "EstadoZonas")
    return TableServiceClient.from_connection_string(connection).get_table_client(table_name)


def save_newer(table: Any, zone_id: str, body: Any) -> tuple[bool, dict[str, str]]:
    desired = validate_update(zone_id, body)
    for _ in range(5):
        try:
            current = table.get_entity(partition_key=PARTITION_KEY, row_key=zone_id)
        except ResourceNotFoundError:
            entity = {**desired, "last_synced_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
            try:
                table.create_entity(entity=entity)
                return True, entity
            except ResourceExistsError:
                continue
        else:
            if parse_utc(current["updated_at"]) >= parse_utc(desired["updated_at"]):
                return False, dict(current)
            entity = {**desired, "last_synced_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")}
            try:
                table.update_entity(
                    entity=entity,
                    mode=UpdateMode.REPLACE,
                    etag=current.metadata["etag"],
                    match_condition=MatchConditions.IfNotModified,
                )
                return True, entity
            except (ResourceModifiedError, ResourceNotFoundError):
                continue
    raise RuntimeError("No se pudo guardar el estado por cambios concurrentes")


def list_zones(table: Any) -> list[dict[str, str | None]]:
    rows = table.query_entities(query_filter="PartitionKey eq 'ZONA'")
    return sorted(
        (
            {
                "zone_id": row["RowKey"],
                "status": row["status"],
                "priority": row.get("priority") or None,
                "updated_at": row["updated_at"],
                "last_synced_at": row["last_synced_at"],
                "public_message": row["public_message"],
            }
            for row in rows
        ),
        key=lambda row: row["zone_id"],
    )
