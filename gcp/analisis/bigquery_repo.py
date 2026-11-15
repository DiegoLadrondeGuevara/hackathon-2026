"""BigQuery transactions serialize writers; event_id deduplication is global."""

import os
import re
import time
import uuid
from functools import lru_cache

from deadline import remaining
from google.api_core.exceptions import BadRequest, Conflict
from google.cloud import bigquery

COLUMNS = (
    "event_id",
    "type",
    "occurred_at",
    "incident_id",
    "zone_id",
    "service",
    "status",
    "priority",
    "antenna_id",
    "customer_hash",
    "payload",
)


def table_name(name=None):
    project = os.environ["GOOGLE_CLOUD_PROJECT"]
    dataset = os.environ.get("BQ_DATASET", "redtelecorp")
    table = name or os.environ.get("BQ_TABLE", "incident_events")
    if not re.fullmatch(r"[a-z][a-z0-9-]{4,28}[a-z0-9]", project):
        raise RuntimeError("Invalid project")
    if not all(re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", v) for v in (dataset, table)):
        raise RuntimeError("Invalid BigQuery identifier")
    return f"{project}.{dataset}.{table}"


@lru_cache(maxsize=1)
def client():
    return bigquery.Client(project=os.environ["GOOGLE_CLOUD_PROJECT"])


def _query(sql, params, deadline, bq=None, *, mutation=False):
    config = bigquery.QueryJobConfig(
        query_parameters=params,
        maximum_bytes_billed=int(os.environ.get("BQ_MAX_BYTES_BILLED", "1000000000")),
        use_query_cache=not mutation,
    )
    job = (bq or client()).query(
        sql,
        job_config=config,
        job_id="rtc_" + uuid.uuid4().hex,
        location=os.environ.get("BQ_LOCATION", "us-central1"),
        timeout=remaining(deadline),
        retry=None,
        job_retry=None,
    )
    # A timeout does not prove rollback. A later delivery must still pass the guard transaction.
    return list(job.result(timeout=remaining(deadline), retry=None, job_retry=None))


def merge_rows(rows, deadline, bq=None):
    if not 1 <= len(rows) <= 10 or len({r["event_id"] for r in rows}) != len(rows):
        raise ValueError("Invalid unique batch")
    params, selects = [], []
    for index, row in enumerate(rows):
        fields = []
        for key in COLUMNS:
            param = f"{key}_{index}"
            dtype = "TIMESTAMP" if key == "occurred_at" else "STRING"
            params.append(bigquery.ScalarQueryParameter(param, dtype, row[key]))
            fields.append(f"@{param} AS {key}")
        selects.append("SELECT " + ", ".join(fields))
    sql = f"""
    DECLARE inserted INT64 DEFAULT 0;
    BEGIN TRANSACTION;
    UPDATE `{table_name("ingest_guard")}` SET generation = generation + 1 WHERE id = 'singleton';
    ASSERT @@row_count = 1 AS 'Ingest guard must be initialized';
    MERGE `{table_name()}` T USING ({" UNION ALL ".join(selects)}) S
    ON T.event_id = S.event_id
    WHEN NOT MATCHED THEN INSERT ({", ".join(COLUMNS)}) VALUES ({", ".join("S." + c for c in COLUMNS)});
    SET inserted = @@row_count;
    COMMIT TRANSACTION;
    SELECT inserted;
    """
    for attempt in range(3):
        try:
            result = _query(sql, params, deadline, bq, mutation=True)
            return int(result[0]["inserted"])
        except (BadRequest, Conflict) as exc:
            # Only known transaction conflicts are safe to retry here. Never log error text (SQL/parameters).
            conflict = "concurrent" in str(exc).lower() or "transaction is aborted" in str(exc).lower()
            if not conflict or attempt == 2:
                raise
            time.sleep(min(0.1 * (2**attempt), remaining(deadline)))
    raise RuntimeError("Transaction did not complete")


def zone_summary(zone_id, days, deadline, bq=None):
    sql = f"""
    WITH history AS (
      SELECT * FROM `{table_name()}`
      WHERE zone_id = @zone AND occurred_at >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL @days DAY)
        AND occurred_at <= CURRENT_TIMESTAMP()
    ), latest_incidents AS (
      SELECT incident_id, priority FROM history
      WHERE type = 'incident.updated' AND incident_id IS NOT NULL
      QUALIFY ROW_NUMBER() OVER(PARTITION BY incident_id ORDER BY occurred_at DESC, event_id DESC) = 1
    )
    SELECT
      (SELECT COUNT(*) FROM history) AS event_count,
      ARRAY(SELECT AS STRUCT type, COUNT(*) AS count FROM history GROUP BY type ORDER BY type) AS events_by_type,
      ARRAY(SELECT AS STRUCT priority, COUNT(*) AS count FROM latest_incidents
            GROUP BY priority ORDER BY priority) AS incidents_by_priority,
      ARRAY(SELECT AS STRUCT antenna_id, COUNT(DISTINCT JSON_VALUE(payload, '$.episode_id')) AS episodes
            FROM history WHERE type = 'telemetry.anomaly' AND antenna_id IS NOT NULL
            GROUP BY antenna_id ORDER BY episodes DESC, antenna_id LIMIT 10) AS anomaly_antennas
    """
    params = [
        bigquery.ScalarQueryParameter("zone", "STRING", zone_id),
        bigquery.ScalarQueryParameter("days", "INT64", days),
    ]
    result = _query(sql, params, deadline, bq)
    row = dict(result[0].items())
    return {
        "zone_id": zone_id,
        "days": days,
        "event_count": int(row["event_count"]),
        "events_by_type": [dict(v.items()) for v in row["events_by_type"]],
        "incidents_by_priority": [dict(v.items()) for v in row["incidents_by_priority"]],
        "anomaly_antennas": [dict(v.items()) for v in row["anomaly_antennas"]],
        "detection_lag_seconds": None,
    }  # Not transmitted by contracts/events.md; never fabricate it.
