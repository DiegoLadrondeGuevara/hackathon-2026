import hashlib
import json
import threading
import time
from urllib.error import HTTPError

import boto3
import pytest

from common import outbound, pii
from handlers import publicadora_hacia_gcp as publisher


class Response:
    status = 200

    def __init__(self, value):
        self.value = value

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, *_):
        return json.dumps(self.value).encode()


@pytest.fixture
def configured(aws):
    ssm = boto3.client("ssm")
    for key, value in {"gcp/base_url": "https://gcp.example", "gcp/api_key": "test-key", "pii_salt": "salt"}.items():
        ssm.put_parameter(Name=f"/red-telecorp/test/{key}", Value=value, Type="SecureString")


def record(n=0):
    return {"messageId": str(n), "body": json.dumps({"detail": {
        "event_id": f"E{n}", "type": "report.created", "version": 1, "occurred_at": "2026-11-14T00:00:00Z",
        "data": {"report_id": "R1", "customer_id": "12345678", "zone_id": "Z01", "service": "INTERNET",
                 "problem_type": "SIN_INTERNET", "description": "private text", "location_text": "private place",
                 "actor": "OPERATOR#private", "unexpected": {"phone": "private"}},
    }})}


def test_sanitized_delivery_and_duplicate_ack(configured, monkeypatch, caplog):
    sent = []

    def transport(req, timeout):
        sent.append(json.loads(req.data))
        assert req.get_header("X-api-key") == "test-key"
        assert timeout == 20  # más que los 15 s que espera GCP en /ingest
        return Response({"inserted": 0})

    monkeypatch.setattr(outbound, "urlopen", transport)
    assert publisher.handler({"Records": [record()]}, None) == {"batchItemFailures": []}
    data = sent[0]["events"][0]["data"]
    assert data["customer_hash"] == hashlib.sha256(b"salt12345678").hexdigest()[:16]
    assert sent[0]["events"][0]["event_id"] == "E0"
    for forbidden in ("customer_id", "description", "location_text", "actor", "private", "12345678"):
        assert forbidden not in json.dumps(sent) + caplog.text


def test_only_failed_batch_retried(configured, monkeypatch):
    sizes = []

    def send(req, timeout):
        size = len(json.loads(req.data)["events"])
        sizes.append(size)
        if len(sizes) == 2:
            raise TimeoutError("secret must not be logged")
        return Response({"inserted": size})

    monkeypatch.setattr(outbound, "urlopen", send)
    result = publisher.handler({"Records": [record(i) for i in range(12)]}, None)
    assert sizes == [10, 2]
    assert result == {"batchItemFailures": [{"itemIdentifier": "10"}, {"itemIdentifier": "11"}]}


@pytest.mark.parametrize("failure", [TimeoutError(), HTTPError("https://gcp.example", 503, "error", {}, None)])
def test_network_failures_retry(configured, monkeypatch, failure):
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(outbound, "urlopen", fail)
    assert publisher.handler({"Records": [record()]}, None)["batchItemFailures"] == [{"itemIdentifier": "0"}]


def test_pending_config_and_invalid_message(configured, monkeypatch):
    monkeypatch.setattr(publisher.config, "get_secret", lambda _: "PENDIENTE")
    assert publisher.handler({"Records": [record()]}, None)["batchItemFailures"] == [{"itemIdentifier": "0"}]
    monkeypatch.setattr(publisher.config, "get_secret", lambda _: "configured")
    assert publisher.handler({"Records": [{"messageId": "bad", "body": "bad json"}]}, None) == {
        "batchItemFailures": [],
    }
    monkeypatch.undo()


def test_recursive_sanitization_does_not_mutate():
    source = {"nested": [{"customer_id": "id", "safe": 1}], "actor": "id"}
    assert pii.strip_pii(source) == {"nested": [{"safe": 1}]}
    assert source["actor"] == "id"


def test_total_timeout_even_when_transport_ignores_timeout(monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(outbound, "urlopen", lambda *a, **k: (release.wait(1), Response({}))[1])
    start = time.monotonic()
    try:
        with pytest.raises(outbound.OutboundError):
            outbound.post_json("https://gcp.example", {}, timeout=0.02)
        assert time.monotonic() - start < 0.2
    finally:
        release.set()


def test_https_and_redirect_policy():
    with pytest.raises(outbound.OutboundError):
        outbound.post_json("http://gcp.example", {})
    assert outbound._NoRedirect().redirect_request(None, None, 302, "", {}, "https://other.example") is None


def test_put_json_for_azure(monkeypatch):
    def transport(req, timeout):
        assert req.method == "PUT"
        return Response({})
    monkeypatch.setattr(outbound, "urlopen", transport)
    assert outbound.put_json("https://azure.example", {}) == {}
