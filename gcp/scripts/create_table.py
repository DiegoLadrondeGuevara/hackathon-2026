"""Explicit bootstrap/repair alternative; prefer Terraform. Never runs on import."""

import argparse
import json
from pathlib import Path

from google.cloud import bigquery


def create(project, dataset_id, location):
    if not dataset_id.replace("_", "").isalnum():
        raise ValueError("Invalid dataset")
    client = bigquery.Client(project=project)
    dataset = bigquery.Dataset(f"{project}.{dataset_id}")
    dataset.location = location
    client.create_dataset(dataset, exists_ok=True)
    schema = [
        bigquery.SchemaField.from_api_repr(v)
        for v in json.loads((Path(__file__).resolve().parents[1] / "infra/schema.json").read_text())
    ]
    table = bigquery.Table(f"{project}.{dataset_id}.incident_events", schema=schema)
    table.time_partitioning = bigquery.TimePartitioning(field="occurred_at")
    table.clustering_fields = ["event_id", "zone_id"]
    client.create_table(table, exists_ok=True)
    guard = bigquery.Table(
        f"{project}.{dataset_id}.ingest_guard",
        schema=[
            bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
            bigquery.SchemaField("generation", "INTEGER", mode="REQUIRED"),
        ],
    )
    client.create_table(guard, exists_ok=True)
    client.query(
        f"""MERGE `{project}.{dataset_id}.ingest_guard` T
        USING (SELECT 'singleton' AS id) S ON T.id = S.id
        WHEN NOT MATCHED THEN INSERT (id, generation) VALUES (S.id, 0)""",
        location=location,
    ).result(timeout=30)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("--dataset", default="redtelecorp")
    parser.add_argument("--location", default="us-central1")
    parser.add_argument("--apply", action="store_true", help="Explicitly authorize cloud writes")
    args = parser.parse_args()
    if not args.apply:
        parser.error("Cloud writes require --apply; do not run concurrently with ingestion")
    create(args.project, args.dataset, args.location)
