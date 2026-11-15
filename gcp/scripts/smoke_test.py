"""Opt-in real HTTP/BigQuery acceptance test; inserts synthetic events, never deletes history."""

import argparse
import concurrent.futures
import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime
from pathlib import Path

from google.cloud import bigquery


def run(url, key_file, project, dataset, require_ai):
    key = Path(key_file).read_text().strip()
    event_id = "SMOKE_" + uuid.uuid4().hex
    stamp = datetime.now(UTC).isoformat()
    event = {
        "event_id": event_id,
        "type": "report.created",
        "occurred_at": stamp,
        "data": {
            "report_id": "R_" + uuid.uuid4().hex,
            "zone_id": "Z01",
            "service": "INTERNET",
            "problem_type": "SIN_INTERNET",
            "synthetic": True,
        },
    }

    def post(path, body):
        req = urllib.request.Request(
            url.rstrip("/") + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json", "X-Api-Key": key},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            return json.load(response)

    def deliver(_):
        for attempt in range(5):
            try:
                return post("/ingest", {"events": [event, event]})
            except (TimeoutError, urllib.error.URLError):
                if attempt == 4:
                    raise
                time.sleep(2**attempt)

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(deliver, range(4)))
    assert all(r["inserted"] in (0, 1) for r in results), results
    assert post("/ingest", {"events": [event]}) == {"inserted": 0}
    # Deliberately change the partition timestamp while keeping the event_id.
    event["occurred_at"] = "2026-01-01T00:00:00Z"
    assert post("/ingest", {"events": [event]}) == {"inserted": 0}
    config = bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("id", "STRING", event_id)])
    rows = list(
        bigquery.Client(project=project)
        .query(f"SELECT COUNT(*) AS n FROM `{project}.{dataset}.incident_events` WHERE event_id=@id", job_config=config)
        .result(timeout=30)
    )
    assert rows[0]["n"] == 1, "Duplicate persisted event_id"
    start = time.monotonic()
    suggestion = post("/suggest", {"incident_id": "SMOKE_INCIDENT", "zone_id": "Z01", "days": 30})
    elapsed = time.monotonic() - start
    assert elapsed < 4, f"Suggestion took {elapsed:.2f}s"
    if require_ai:
        assert suggestion.get("available") is True, "Gemini demonstration not available"
    if suggestion.get("available"):
        assert 1 <= len(suggestion["hypotheses"]) <= 3
    else:
        assert suggestion == {"available": False}
    print(f"PASS: concurrent deduplication, changed-date retry, physical row count=1, suggest={elapsed:.2f}s")
    print("Gemini hypotheses available:", suggestion.get("available"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("key_file")
    parser.add_argument("project")
    parser.add_argument("--dataset", default="redtelecorp")
    parser.add_argument("--require-ai", action="store_true")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    if not args.live or not args.url.startswith("https://"):
        parser.error("--live and HTTPS are required; this writes synthetic cloud data")
    if not args.dataset.replace("_", "").isalnum():
        parser.error("Invalid dataset")
    run(args.url, args.key_file, args.project, args.dataset, args.require_ai)
