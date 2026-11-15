"""Verify/repair the single BigQuery transaction guard; no third-party Python packages.

Cloud writes require --apply. This is intentionally independent from Terraform's
one-shot google_bigquery_job: a job resource existing does not prove its SQL ran.
"""

import argparse
import csv
import io
import re
import subprocess

PROJECT_ID = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
BQ_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
LOCATION = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


def run_query(project: str, location: str, sql: str) -> str:
    command = [
        "bq", "--quiet", f"--project_id={project}", f"--location={location}",
        "--format=csv", "query", "--use_legacy_sql=false", sql,
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=True, timeout=90)
    return result.stdout


def ensure_guard(project: str, dataset: str = "redtelecorp", location: str = "us-central1", apply: bool = False):
    if not PROJECT_ID.fullmatch(project) or not BQ_ID.fullmatch(dataset) or not LOCATION.fullmatch(location):
        raise ValueError("Invalid project, dataset or location")
    table = f"`{project}.{dataset}.ingest_guard`"
    if apply:
        # Idempotent, does not modify an existing row or delete anything.
        run_query(project, location, f"""
MERGE {table} T
USING (SELECT 'singleton' AS id) S
ON T.id = S.id
WHEN NOT MATCHED THEN INSERT (id, generation) VALUES (S.id, 0)
""")
    # Verify the actual data, not only a Terraform job's existence/status.
    output = run_query(project, location, f"SELECT COUNTIF(id = 'singleton') AS matches FROM {table}")
    rows = list(csv.DictReader(io.StringIO(output)))
    if len(rows) != 1 or int(rows[0]["matches"]) != 1:
        raise RuntimeError("BigQuery ingest_guard must contain exactly one singleton row")
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--dataset", default="redtelecorp")
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--apply", action="store_true", help="Authorize idempotent BigQuery MERGE")
    args = parser.parse_args()
    try:
        ensure_guard(args.project, args.dataset, args.location, args.apply)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError, subprocess.TimeoutExpired, RuntimeError) as exc:
        parser.exit(1, f"ERROR: ingest guard verification failed: {exc}\n")
    print("OK: BigQuery ingest_guard has exactly one singleton row")


if __name__ == "__main__":
    main()
