"""Safe first live check: one synthetic event, one replay, then BigQuery row count.

Requires Google Cloud Shell bq CLI and the private API key file. Writes one
synthetic event only with --live; never prints the key or personal data.
"""

import argparse
import csv
import io
import json
import pathlib
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

from ensure_guard import run_query


def post_ingest(url, key, events):
    req = urllib.request.Request(
        url.rstrip("/") + "/ingest",
        method="POST",
        headers={"Content-Type": "application/json", "X-Api-Key": key},
        data=json.dumps({"events": events}).encode("utf-8"),
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as exc:
        # Intentionally don't print request headers or credential contents.
        raise RuntimeError(f"Cloud Run /ingest returned HTTP {exc.code}") from None


def smoke(url, key_path, project, dataset="redtelecorp", location="us-central1"):
    # Ensure the table is initialized before issuing any concurrent requests.
    from ensure_guard import ensure_guard
    ensure_guard(project, dataset, location, apply=False)
    key = pathlib.Path(key_path).read_text().strip()
    if not key:
        raise RuntimeError("API key file is empty")
    eid = "SMOKE_" + uuid.uuid4().hex
    event = {
        "event_id": eid,
        "type": "report.created",
        "occurred_at": datetime.now(UTC).isoformat(),
        "data": {
            "report_id": "R_" + uuid.uuid4().hex,
            "zone_id": "Z01",
            "service": "INTERNET",
            "problem_type": "SIN_INTERNET",
            "synthetic": True,
        },
    }
    first = post_ingest(url, key, [event])
    second = post_ingest(url, key, [event])
    sql = f"SELECT COUNT(*) AS matches FROM `{project}.{dataset}.incident_events` WHERE event_id = '{eid}'"
    reader = csv.DictReader(io.StringIO(run_query(project, location, sql)))
    rows = list(reader)
    actual = int(rows[0]["matches"]) if len(rows) == 1 else -1
    if first != {"inserted": 1} or second != {"inserted": 0} or actual != 1:
        raise RuntimeError(f"Smoke test failed: first={first}, duplicate={second}, BigQuery rows={actual}")
    print(f"PASS live: /ingest accepted event, replay deduplicated, BigQuery has exactly 1 row ({eid})")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("key_file")
    parser.add_argument("project")
    parser.add_argument("--dataset", default="redtelecorp")
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--live", action="store_true", help="Authorize two Cloud Run calls and one event insert")
    args = parser.parse_args()
    if not args.live or not args.url.startswith("https://"):
        parser.error("Explicit --live and HTTPS are required")
    smoke(args.url, args.key_file, args.project, args.dataset, args.location)
