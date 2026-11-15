"""Best-effort OTLP/HTTP JSON metrics for the public Azure API.

Only fixed route names, HTTP status and aggregate zone freshness leave Azure.
No request body, zone ID, customer data or credentials are metric attributes.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

_LOG = logging.getLogger(__name__)
_START_NS = str(time.time_ns())
_INSTANCE_ID = uuid.uuid4().hex
_LOCK = threading.Lock()
_REQUESTS: dict[tuple[str, int], int] = {}
_ERRORS: dict[tuple[str, int], int] = {}
_TIMEOUT_SECONDS = 1.0
_STALE_SECONDS = 600


def _attribute(key: str, value: str) -> dict:
    return {"key": key, "value": {"stringValue": value}}


def _sum(name: str, count: int, attributes: list[dict], now_ns: str) -> dict:
    return {
        "name": name,
        "unit": "1",
        "sum": {
            "aggregationTemporality": 2,  # cumulative within this Function worker
            "isMonotonic": True,
            "dataPoints": [{
                "attributes": attributes,
                "startTimeUnixNano": _START_NS,
                "timeUnixNano": now_ns,
                "asInt": str(count),
            }],
        },
    }


def _gauge(name: str, value: float | int, unit: str, attributes: list[dict], now_ns: str) -> dict:
    return {
        "name": name,
        "unit": unit,
        "gauge": {"dataPoints": [{
            "attributes": attributes,
            "timeUnixNano": now_ns,
            "asDouble": value,
        }]},
    }


def _zone_freshness(zones: list[dict], now: datetime) -> tuple[int, float]:
    stale = 0
    maximum_age = 0.0
    for zone in zones:
        try:
            synced = datetime.fromisoformat(zone["last_synced_at"].replace("Z", "+00:00"))
            if synced.tzinfo is None:
                raise ValueError("timestamp without timezone")
            age = max(0.0, (now - synced.astimezone(timezone.utc)).total_seconds())
            maximum_age = max(maximum_age, age)
            stale += age > _STALE_SECONDS
        except (KeyError, TypeError, ValueError, AttributeError):
            stale += 1
    return stale, maximum_age


def _destination() -> tuple[str, str] | None:
    endpoint = os.getenv("GRAFANA_OTLP_ENDPOINT", "").rstrip("/")
    instance = os.getenv("GRAFANA_INSTANCE_ID", "")
    token = os.getenv("GRAFANA_TOKEN", "")
    if not all((endpoint, instance, token)):
        return None
    parsed = urlsplit(endpoint)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise ValueError("Invalid OTLP endpoint")
    url = endpoint if endpoint.endswith("/v1/metrics") else endpoint + "/v1/metrics"
    credentials = base64.b64encode(f"{instance}:{token}".encode("utf-8")).decode("ascii")
    return url, "Basic " + credentials


def record_request(route: str, status_code: int, duration_ms: float, zones: list[dict] | None = None) -> None:
    """Record an API response; Grafana failure never changes that response."""
    try:
        destination = _destination()
        if destination is None:
            return
        now_ns = str(time.time_ns())
        attributes = [_attribute("http.route", route), _attribute("http.status_code", str(status_code))]
        key = (route, status_code)
        with _LOCK:
            _REQUESTS[key] = _REQUESTS.get(key, 0) + 1
            request_count = _REQUESTS[key]
            if status_code >= 400:
                _ERRORS[key] = _ERRORS.get(key, 0) + 1
                error_count = _ERRORS[key]
            else:
                error_count = None

        metrics = [
            _sum("redtelecorp.azure.requests", request_count, attributes, now_ns),
            _gauge("redtelecorp.azure.latency_ms", round(duration_ms, 3), "ms", attributes, now_ns),
        ]
        if error_count is not None:
            metrics.append(_sum("redtelecorp.azure.errors", error_count, attributes, now_ns))
        if zones is not None:
            stale, max_age = _zone_freshness(zones, datetime.now(timezone.utc))
            metrics.extend([
                _gauge("redtelecorp.azure.zones_stale", stale, "1", [], now_ns),
                _gauge("redtelecorp.azure.sync_age_max_seconds", round(max_age, 3), "s", [], now_ns),
            ])

        payload = {"resourceMetrics": [{
            "resource": {"attributes": [
                _attribute("service.name", "red-telecorp-azure"),
                _attribute("service.instance.id", _INSTANCE_ID),
                _attribute("deployment.environment", os.getenv("AZURE_ENVIRONMENT", "dev")),
            ]},
            "scopeMetrics": [{"scope": {"name": "red-telecorp-azure-api"}, "metrics": metrics}],
        }]}
        url, authorization = destination
        request = Request(
            url,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
            headers={"Content-Type": "application/json", "Authorization": authorization},
            method="POST",
        )
        with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError("OTLP endpoint rejected metrics")
    except Exception:  # observability is deliberately outside the business transaction
        _LOG.warning("Azure metrics export failed", exc_info=False)
