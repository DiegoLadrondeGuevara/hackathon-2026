"""Red TeleCorp AWS -> GCP v1 external contract. No personal data may cross."""

import json
import math
import re
from datetime import UTC, datetime

EVENT_FIELDS = {"event_id", "type", "version", "occurred_at", "data"}
ALLOWED_TYPES = {
    "report.created": {"report_id", "customer_hash", "zone_id", "service", "problem_type", "created_at", "synthetic"},
    "report.status_changed": {
        "report_id",
        "customer_hash",
        "zone_id",
        "from_status",
        "to_status",
        "at",
        "actor",
        "synthetic",
    },
    "report.linked": {
        "incident_id",
        "report_id",
        "customer_hash",
        "zone_id",
        "incident_status",
        "linked_at",
        "synthetic",
    },
    "telemetry.anomaly": {
        "antenna_id",
        "zone_id",
        "episode_id",
        "state",
        "gb_per_min",
        "reason",
        "opened_at",
        "episodes_7d",
        "synthetic",
    },
    "telemetry.recovered": {"antenna_id", "zone_id", "episode_id", "closed_at", "duration_seconds", "synthetic"},
    "telemetry.recurrent": {"antenna_id", "zone_id", "episodes_7d", "window_start", "synthetic"},
    "incident.updated": {
        "incident_id",
        "zone_id",
        "service",
        "status",
        "priority",
        "milestone",
        "change",
        "affected_users",
        "updated_at",
        "synthetic",
    },
}
ID_RE = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
HASH_RE = re.compile(r"[0-9a-f]{16}\Z")
STATE = {"INHABILITADA", "CAIDA", "NORMAL", "SATURADA"}
SERVICE = {"INTERNET", "MOVIL", "ANY"}
PRIORITY = {"P1", "P2", "P3"}
STATES_INCIDENT = {"EVALUACION", "CONFIRMADO", "RESTABLECIDO", "CERRADO"}
STATES_REPORT = {"REGISTRADA", "EN_REVISION", "EN_ATENCION", "SOLUCIONADA", "CERRADA"}
CHANGES = {"CREATED", "EVIDENCE", "THRESHOLD", "RECOVERY", "PRIORITY", "STATUS"}
TYPES = {"SIN_SENAL", "SIN_INTERNET", "LLAMADAS", "SMS", "LENTITUD", "OTRO"}
TIMES = {"created_at", "at", "linked_at", "opened_at", "closed_at", "window_start", "updated_at"}
NUMERIC = {"gb_per_min", "duration_seconds", "affected_users", "episodes_7d"}
# actor is part of the AWS event, but operator/customer IDs must NOT cross the boundary.
DROP_FIELDS = {"actor"}


class ContractError(ValueError):
    pass


def parse_time(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ContractError("timestamp ISO-8601 UTC requerido")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ContractError("timestamp ISO-8601 inválido") from exc
    if dt.tzinfo is None or dt.utcoffset() is None or dt.utcoffset().total_seconds() != 0:
        raise ContractError("timestamp debe indicar UTC")
    return dt.astimezone(UTC)


def check_id(value, name):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise ContractError(f"{name} inválido")
    return value


def sanitize_event(obj):
    if not isinstance(obj, dict) or (set(obj) - EVENT_FIELDS):
        raise ContractError("sobre de evento desconocido")
    event_id = check_id(obj.get("event_id"), "event_id")
    event_type = obj.get("type")
    if not isinstance(event_type, str) or event_type not in ALLOWED_TYPES:
        raise ContractError("type desconocido")
    if type(obj.get("version", 1)) is not int or obj.get("version", 1) != 1:
        raise ContractError("version debe ser 1")
    occurred_at = parse_time(obj.get("occurred_at"))
    data = obj.get("data")
    if not isinstance(data, dict):
        raise ContractError("data debe ser objeto")
    if set(data) - ALLOWED_TYPES[event_type]:
        raise ContractError("campo no permitido o potencial dato personal en data")
    if not isinstance(data.get("zone_id"), str) or not ID_RE.fullmatch(data["zone_id"]):
        raise ContractError("zone_id requerido")
    clean = {}
    for key, val in data.items():
        if key in DROP_FIELDS:
            raise ContractError("actor debe eliminarse antes de salir de AWS")
        if val is None and key == "milestone":
            clean[key] = val
            continue
        if key == "synthetic":
            if type(val) is not bool:
                raise ContractError("synthetic debe ser booleano")
        elif key == "customer_hash":
            if not isinstance(val, str) or not HASH_RE.fullmatch(val):
                raise ContractError("customer_hash debe ser sha256 truncado de 16 hex")
        elif key in TIMES:
            parse_time(val)
        elif key in NUMERIC:
            if type(val) not in (int, float) or not 0 <= val <= 1_000_000_000 or not math.isfinite(val):
                raise ContractError(f"{key} numérico inválido")
            if key != "gb_per_min" and type(val) is not int:
                raise ContractError(f"{key} debe ser entero")
        elif key in (
            "state",
            "status",
            "from_status",
            "to_status",
            "incident_status",
            "service",
            "priority",
            "milestone",
            "change",
            "problem_type",
            "reason",
        ):
            allowed = {
                "state": STATE,
                "status": STATES_INCIDENT,
                "from_status": STATES_REPORT,
                "to_status": STATES_REPORT,
                "incident_status": STATES_INCIDENT,
                "service": SERVICE,
                "priority": PRIORITY,
                "milestone": {"EVALUACION", "CONFIRMADO", "RESTABLECIDO"},
                "change": CHANGES,
                "problem_type": TYPES,
                "reason": {"OPENED", "ESCALATED"},
            }[key]
            if not isinstance(val, str) or val not in allowed:
                raise ContractError(f"{key} inválido")
        elif isinstance(val, str):
            check_id(val, key)
        else:
            raise ContractError(f"{key} inválido")
        clean[key] = val
    # Each type carries the minimum information needed for analytics and correlation evidence.
    required = {
        "report.created": {"zone_id", "report_id", "service", "problem_type"},
        "report.status_changed": {"zone_id", "report_id", "to_status"},
        "report.linked": {"zone_id", "report_id", "incident_id"},
        "telemetry.anomaly": {"zone_id", "antenna_id", "episode_id", "state", "gb_per_min"},
        "telemetry.recovered": {"zone_id", "antenna_id", "episode_id", "duration_seconds"},
        "telemetry.recurrent": {"zone_id", "antenna_id", "episodes_7d"},
        "incident.updated": {"zone_id", "incident_id", "status", "change"},
    }[event_type]
    if not required.issubset(clean):
        raise ContractError("faltan campos obligatorios en data")
    # AWS owns classification and incident decisions; GCP validates the wire schema only.
    return {"event_id": event_id, "type": event_type, "occurred_at": occurred_at.isoformat(), "data": clean}


def to_row(event):
    data = event["data"]
    return {
        "event_id": event["event_id"],
        "type": event["type"],
        "occurred_at": event["occurred_at"],
        "incident_id": data.get("incident_id"),
        "zone_id": data.get("zone_id"),
        "service": data.get("service"),
        "status": data.get("status"),
        "priority": data.get("priority"),
        "antenna_id": data.get("antenna_id"),
        "customer_hash": data.get("customer_hash"),
        "payload": json.dumps(data, separators=(",", ":"), ensure_ascii=False, sort_keys=True),
    }
