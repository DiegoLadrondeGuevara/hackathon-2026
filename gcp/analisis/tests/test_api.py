import copy
import threading
import time

import main
import pytest

HEADERS = {"X-Api-Key": "test-key"}


@pytest.mark.parametrize("key", ["", "wrong"])
def test_authentication(client, event, key):
    assert client.post("/ingest", json={"events": [event]}, headers={"X-Api-Key": key}).status_code == 401
    assert client.post("/suggest", json={}, headers={"X-Api-Key": key}).status_code == 401


def test_duplicate_batch_and_column_mapping(client, event, monkeypatch):
    captured = []

    def persist(rows, end):
        captured.extend(rows)
        return len(rows)

    monkeypatch.setattr(main.repository, "merge_rows", persist)
    response = client.post("/ingest", json={"events": [event, event]}, headers=HEADERS)
    assert response.status_code == 200 and response.json == {"inserted": 1}
    assert len(captured) == 1 and captured[0]["customer_hash"] == event["data"]["customer_hash"]
    assert captured[0]["zone_id"] == "Z01"


def test_contradictory_duplicate_rejected(client, event):
    other = copy.deepcopy(event)
    other["data"]["zone_id"] = "Z02"
    assert client.post("/ingest", json={"events": [event, other]}, headers=HEADERS).status_code == 400


@pytest.mark.parametrize("field", ["customer_id", "actor", "description", "location_text", "email", "phone"])
def test_privacy_rejected_before_persistence(client, event, field):
    event["data"][field] = "personal"
    assert client.post("/ingest", json={"events": [event]}, headers=HEADERS).status_code == 400


@pytest.mark.parametrize("bad_type", [[], {}, None, 3, True])
def test_invalid_event_type_returns_400(client, event, bad_type):
    event["type"] = bad_type
    assert client.post("/ingest", json={"events": [event]}, headers=HEADERS).status_code == 400


@pytest.mark.parametrize("count", [0, 11])
def test_batch_limits(client, event, count):
    assert client.post("/ingest", json={"events": [event] * count}, headers=HEADERS).status_code == 400


def test_bad_json_and_large_body(client):
    for raw in [b"{", b"x" * (main.MAX_BODY + 1), b"[]"]:
        assert client.post("/ingest", data=raw, content_type="application/json", headers=HEADERS).status_code == 400


def test_retryable_ingest_failure(client, event, monkeypatch):
    def fail(*args):
        raise RuntimeError("sensitive provider message")

    monkeypatch.setattr(main.repository, "merge_rows", fail)
    response = client.post("/ingest", json={"events": [event]}, headers=HEADERS)
    assert response.status_code == 503 and "sensitive" not in response.text


def test_suggest_success_and_empty_history(client, monkeypatch):
    expected = {
        "available": True,
        "hypotheses": [{"title": "Revisar", "rationale": "Evidencia agregada"}],
        "model": "test-model",
        "generated_at": "2026-11-14T10:00:00Z",
    }
    monkeypatch.setattr(main.repository, "zone_summary", lambda *a: {"event_count": 1})
    monkeypatch.setattr(main.ai, "generate_hypotheses", lambda *a: expected)
    body = {"incident_id": "I1", "zone_id": "Z01", "days": 30}
    assert client.post("/suggest", json=body, headers=HEADERS).json == expected
    monkeypatch.setattr(main.repository, "zone_summary", lambda *a: {"event_count": 0})
    assert client.post("/suggest", json=body, headers=HEADERS).json == {"available": False}


@pytest.mark.parametrize("dependency", ["zone_summary", "generate_hypotheses"])
def test_suggest_failure_is_exact_fallback(client, monkeypatch, dependency):
    monkeypatch.setattr(main.repository, "zone_summary", lambda *a: {"event_count": 1})

    def fail(*args):
        raise RuntimeError("provider details")

    target = main.repository if dependency == "zone_summary" else main.ai
    monkeypatch.setattr(target, dependency, fail)
    response = client.post("/suggest", json={"incident_id": "I1", "zone_id": "Z01"}, headers=HEADERS)
    assert response.status_code == 200 and response.json == {"available": False}


def test_stalled_dependency_does_not_block_response(client, monkeypatch):
    release = threading.Event()
    monkeypatch.setattr(main, "SUGGEST_SECONDS", 0.02)
    monkeypatch.setattr(main.repository, "zone_summary", lambda *a: (release.wait(1), {"event_count": 0})[1])
    start = time.monotonic()
    try:
        response = client.post("/suggest", json={"incident_id": "I1", "zone_id": "Z01"}, headers=HEADERS)
        assert response.json == {"available": False}
        assert time.monotonic() - start < 0.2
    finally:
        release.set()
