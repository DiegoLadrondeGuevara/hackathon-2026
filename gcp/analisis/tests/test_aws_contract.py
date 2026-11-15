"""Compatibility across the actual publisher and the GCP HTTP boundary, with no cloud calls."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "aws/src"))
import main  # noqa: E402
from handlers import publicadora_hacia_gcp as publisher  # noqa: E402

CASES = {
    "report.created": {
        "report_id": "R1",
        "service": "INTERNET",
        "problem_type": "SIN_INTERNET",
        "customer_id": "private",
    },
    "report.status_changed": {
        "report_id": "R1",
        "from_status": "REGISTRADA",
        "to_status": "EN_REVISION",
        "actor": "OPERATOR#private",
        "customer_id": "private",
    },
    "report.linked": {
        "report_id": "R1",
        "incident_id": "I1",
        "incident_status": "EVALUACION",
        "customer_id": "private",
    },
    "telemetry.anomaly": {
        "antenna_id": "A001",
        "episode_id": "EP1",
        "state": "INHABILITADA",
        "gb_per_min": 0,
        "reason": "OPENED",
        "episodes_7d": 3,
    },
    "telemetry.recovered": {"antenna_id": "A001", "episode_id": "EP1", "duration_seconds": 300},
    "telemetry.recurrent": {"antenna_id": "A001", "episodes_7d": 3},
    "incident.updated": {
        "incident_id": "I1",
        "service": "ANY",
        "status": "EVALUACION",
        "priority": "P3",
        "milestone": "EVALUACION",
        "change": "CREATED",
        "affected_users": 0,
    },
}


@pytest.mark.parametrize("kind,data", CASES.items())
def test_publisher_payload_is_accepted_by_gcp(client, monkeypatch, kind, data):
    event = {
        "event_id": "E1",
        "type": kind,
        "version": 1,
        "occurred_at": "2026-11-14T12:00:00Z",
        "data": {"zone_id": "Z01", **data},
    }
    safe = publisher._envelope({"body": json.dumps({"detail": event})}, "test-salt")
    assert "private" not in json.dumps(safe)
    monkeypatch.setattr(main.repository, "merge_rows", lambda rows, end: len(rows))
    response = client.post("/ingest", json={"events": [safe]}, headers={"X-Api-Key": "test-key"})
    assert response.status_code == 200 and response.json == {"inserted": 1}
