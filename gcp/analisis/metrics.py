"""Best-effort OTLP/HTTP JSON. Bounded queue, one daemon, cumulative process counters."""

import base64
import json
import os
import queue
import threading
import time
import urllib.request
import uuid
from collections import Counter
from urllib.parse import urlsplit

_QUEUE = queue.Queue(maxsize=128)
_START_LOCK = threading.Lock()
_started = False
_START_NS = str(time.time_ns())
_INSTANCE = uuid.uuid4().hex
_BOUNDS = [50, 100, 250, 500, 1000, 2000, 3200, 4000]


def _configuration():
    endpoint = os.environ.get("GRAFANA_OTLP_ENDPOINT", "").rstrip("/")
    instance = os.environ.get("GRAFANA_INSTANCE_ID", "")
    token = os.environ.get("GRAFANA_TOKEN", "")
    parsed = urlsplit(endpoint)
    if (
        not instance
        or not token
        or parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        return None
    if not endpoint.endswith("/v1/metrics"):
        endpoint += "/v1/metrics"
    return endpoint, instance, token


def record(route, status, inserted, elapsed_ms, failed=False):
    """Never performs network I/O or waits for queue space on a request thread."""
    global _started
    if not _configuration():
        return
    route = route if route in ("/ingest", "/suggest", "/healthz") else "__other__"
    # Start at most one exporter; contention drops a sample rather than blocking the API.
    if not _started:
        if not _START_LOCK.acquire(blocking=False):
            return
        try:
            if not _started:
                threading.Thread(target=_worker, daemon=True, name="otlp-exporter").start()
                _started = True
        finally:
            _START_LOCK.release()
    try:
        _QUEUE.put_nowait((route, int(status), max(0, int(inserted)), max(0, elapsed_ms), bool(failed)))
    except queue.Full:
        pass


class Aggregates:
    def __init__(self):
        self.requests = Counter()
        self.errors = Counter()
        self.rows = 0
        self.latency_sum = 0
        self.latency_count = 0
        self.buckets = [0] * (len(_BOUNDS) + 1)

    def add(self, sample):
        route, status, inserted, elapsed, failed = sample
        self.requests[(route, status)] += 1
        if status >= 400 or failed:
            self.errors[(route, status)] += 1
        self.rows += inserted
        if route == "/suggest":
            self.latency_sum += elapsed
            self.latency_count += 1
            index = next((i for i, limit in enumerate(_BOUNDS) if elapsed <= limit), len(_BOUNDS))
            self.buckets[index] += 1

    def payload(self):
        now = str(time.time_ns())

        def point(value, route=None, status=None):
            result = {"startTimeUnixNano": _START_NS, "timeUnixNano": now, "asInt": str(value)}
            if route is not None:
                result["attributes"] = [
                    {"key": "http.route", "value": {"stringValue": route}},
                    {"key": "http.response.status_code", "value": {"intValue": str(status)}},
                ]
            return result

        def counter(name, points):
            return {
                "name": name,
                "unit": "1",
                "sum": {"aggregationTemporality": 2, "isMonotonic": True, "dataPoints": points},
            }

        metrics = [
            counter("redtelecorp.gcp.requests", [point(v, *k) for k, v in self.requests.items()]),
            counter("redtelecorp.gcp.errors", [point(v, *k) for k, v in self.errors.items()]),
            counter("redtelecorp.gcp.ingest.rows", [point(self.rows)]),
        ]
        if self.latency_count:
            metrics.append(
                {
                    "name": "redtelecorp.gcp.suggest.latency_ms",
                    "unit": "ms",
                    "histogram": {
                        "aggregationTemporality": 2,
                        "dataPoints": [
                            {
                                "startTimeUnixNano": _START_NS,
                                "timeUnixNano": now,
                                "count": str(self.latency_count),
                                "sum": self.latency_sum,
                                "explicitBounds": _BOUNDS,
                                "bucketCounts": [str(v) for v in self.buckets],
                            }
                        ],
                    },
                }
            )
        # Some receivers reject empty data point collections.
        metrics = [m for m in metrics if m.get("sum", m.get("histogram"))["dataPoints"]]
        return {
            "resourceMetrics": [
                {
                    "resource": {
                        "attributes": [
                            {"key": "service.name", "value": {"stringValue": "red-telecorp-gcp"}},
                            {"key": "service.instance.id", "value": {"stringValue": _INSTANCE}},
                        ]
                    },
                    "scopeMetrics": [{"scope": {"name": "redtelecorp.gcp"}, "metrics": metrics}],
                }
            ]
        }


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _send(payload):
    configuration = _configuration()
    if configuration is None:
        return
    endpoint, instance, token = configuration
    auth = base64.b64encode(f"{instance}:{token}".encode()).decode()
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Basic " + auth},
    )
    with urllib.request.build_opener(_NoRedirect()).open(request, timeout=0.5) as response:
        if not 200 <= response.status < 300:
            raise RuntimeError("OTLP export failed")


def _worker():
    aggregates = Aggregates()
    while True:
        aggregates.add(_QUEUE.get())
        # Coalesce queued requests. Cumulative counters recover failed exports on the next request.
        for _ in range(127):
            try:
                aggregates.add(_QUEUE.get_nowait())
            except queue.Empty:
                break
        try:
            _send(aggregates.payload())
        except Exception:
            pass  # Never expose receiver errors, headers or application payloads.
