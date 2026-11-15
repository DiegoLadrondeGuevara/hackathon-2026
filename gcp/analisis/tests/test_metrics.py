import json
import queue
import threading
import time

import main
import metrics


def test_otlp_cumulative_schema_and_privacy():
    values = metrics.Aggregates()
    values.add(("/ingest", 200, 3, 20, False))
    values.add(("/suggest", 200, 0, 1000, True))
    values.add(("/suggest", 401, 0, 5, False))
    payload = values.payload()
    resource = payload["resourceMetrics"][0]
    assert resource["resource"]["attributes"][0]["value"]["stringValue"] == "red-telecorp-gcp"
    by_name = {m["name"]: m for m in resource["scopeMetrics"][0]["metrics"]}
    assert set(by_name) == {
        "redtelecorp.gcp.requests",
        "redtelecorp.gcp.errors",
        "redtelecorp.gcp.ingest.rows",
        "redtelecorp.gcp.suggest.latency_ms",
    }
    assert by_name["redtelecorp.gcp.ingest.rows"]["sum"]["dataPoints"][0]["asInt"] == "3"
    histogram = by_name["redtelecorp.gcp.suggest.latency_ms"]["histogram"]["dataPoints"][0]
    assert histogram["count"] == "2" and histogram["sum"] == 1005
    assert sum(map(int, histogram["bucketCounts"])) == 2
    assert len(histogram["bucketCounts"]) == len(histogram["explicitBounds"]) + 1
    for forbidden in ["customer_id", "customer_hash", "description", "location_text", "incident_id", "API_KEY"]:
        assert forbidden not in json.dumps(payload)


def test_full_queue_and_unknown_path_never_block(monkeypatch):
    monkeypatch.setenv("GRAFANA_OTLP_ENDPOINT", "https://grafana.example/otlp")
    monkeypatch.setenv("GRAFANA_INSTANCE_ID", "123")
    monkeypatch.setenv("GRAFANA_TOKEN", "private-token")
    q = queue.Queue(maxsize=1)
    monkeypatch.setattr(metrics, "_QUEUE", q)
    monkeypatch.setattr(metrics, "_started", True)
    start = time.monotonic()
    metrics.record("/private/person/id", 404, 0, 1)
    metrics.record("/ingest", 200, 1, 2)
    assert time.monotonic() - start < 0.1
    assert q.get_nowait()[0] == "__other__"


def test_export_failure_does_not_change_http_response(client, event, monkeypatch):
    monkeypatch.setattr(main.repository, "merge_rows", lambda rows, end: 1)

    def fail(*a, **k):
        raise RuntimeError("private exporter error")

    monkeypatch.setattr(metrics, "record", fail)
    response = client.post("/ingest", json={"events": [event]}, headers={"X-Api-Key": "test-key"})
    assert response.status_code == 200 and response.json == {"inserted": 1}


def test_slow_exporter_runs_off_request_thread(client, event, monkeypatch):
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    monkeypatch.setattr(main.repository, "merge_rows", lambda rows, end: 1)
    monkeypatch.setenv("GRAFANA_OTLP_ENDPOINT", "https://grafana.example/otlp")
    monkeypatch.setenv("GRAFANA_INSTANCE_ID", "123")
    monkeypatch.setenv("GRAFANA_TOKEN", "private-token")

    # A dedicated finite consumer tests the real asynchronous queue without leaving a worker behind.
    def consumer():
        metrics._QUEUE.get()
        entered.set()
        release.wait(1)
        finished.set()

    monkeypatch.setattr(metrics, "_worker", consumer)
    monkeypatch.setattr(metrics, "_started", False)
    monkeypatch.setattr(metrics, "_QUEUE", queue.Queue(maxsize=128))
    try:
        start = time.monotonic()
        response = client.post("/ingest", json={"events": [event]}, headers={"X-Api-Key": "test-key"})
        assert response.status_code == 200 and time.monotonic() - start < 0.2
        assert entered.wait(0.2) and not finished.is_set()
    finally:
        release.set()
        assert finished.wait(1)


def test_export_transport_auth_and_endpoint(monkeypatch):
    monkeypatch.setenv("GRAFANA_OTLP_ENDPOINT", "https://grafana.example/otlp")
    monkeypatch.setenv("GRAFANA_INSTANCE_ID", "123")
    monkeypatch.setenv("GRAFANA_TOKEN", "token")

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    class Opener:
        def open(self, req, timeout):
            assert req.full_url == "https://grafana.example/otlp/v1/metrics"
            assert req.get_header("Authorization") == "Basic MTIzOnRva2Vu"
            assert timeout == 0.5
            return Response()

    monkeypatch.setattr(metrics.urllib.request, "build_opener", lambda *a: Opener())
    metrics._send({"resourceMetrics": []})
