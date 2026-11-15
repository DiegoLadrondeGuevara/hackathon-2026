# Red TeleCorp — GCP

Cloud Run HTTP function: `POST /ingest` and `POST /suggest`, both with `X-Api-Key`.
AWS owns incident decisions. Dependencies stay inside `gcp/`; no personal data may leave AWS.

## Local checks

Python 3.11+, Terraform 1.9+, Google provider 6.50.0 (lockfile committed).

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r gcp/requirements-dev.txt
bash gcp/scripts/check.sh
functions-framework --source=gcp/analisis/main.py --target=api --port=8080
```

Set `API_KEY` locally through a private environment; never commit it.
Tests use simulated dependencies and forbid real network calls. `smoke_test.py` is separate and opt-in.

## Runtime variables

`GOOGLE_CLOUD_PROJECT`, `BQ_DATASET=redtelecorp`, `BQ_TABLE=incident_events`, `BQ_LOCATION=us-central1`,
`BQ_MAX_BYTES_BILLED=1000000000`, `API_KEY` and `GEMINI_API_KEY` (Secret Manager references),
`GEMINI_MODEL=gemini-3.5-flash-lite`.
The model is configurable; [Google lists Flash-Lite as stable](https://aistudio.google.com/docs/models/gemini-3.5-flash-lite)
(checked 2026-11-14). Availability and quota must be checked with the deployment project's key.

## Persistence and deadlines

Each ingestion transaction updates the initialized singleton in `ingest_guard` before its global `event_id` MERGE.
Concurrent transactions conflict and roll back; bounded retries and SQS redelivery handle them.
This follows [BigQuery transaction conflict semantics](https://docs.cloud.google.com/bigquery/docs/transactions).
No process-local lock, insertId, unique constraint, instance count or date predicate is used as a uniqueness guarantee.
All writers must use this transaction path. Existing duplicate data must be audited before migration; it is not deleted.
Identical duplicates in one batch are collapsed; contradictory copies in one batch return 400.
Across requests the first committed event wins, even if a later copy changes its timestamp.
`inserted` counts rows committed by that request; a retry after a lost response may return zero.

Ingest stops waiting after 8 s; ambiguous jobs may finish later, but retries still pass the transactional guard.
Suggest stops waiting after 3.2 s for BigQuery plus Gemini, returning exactly `{"available":false}` on failure.
Daemon dependency workers are bounded (8 per process), including calls that ignore SDK timeouts.
Cold starts/network overhead are outside the application budget; AWS independently bounds the outbound call.

Statistics cover the whole requested zone/window (1–90 days), including event counts, latest incident priorities,
and anomalous antenna episodes. `detection_lag_seconds` is unavailable because the current event contract omits
it; the prompt receives null, never a fabricated measurement. No raw payloads or customer hashes enter Gemini.

## Approved deployment only

Requires a billed GCP project, Cloud Shell/ADC, Terraform and permission to enable APIs, create resources,
submit builds, upload to the dedicated staging bucket, and act as the builder/runtime service accounts.
Organization policy must allow `allUsers` invocation; API routes still require the application key.

```bash
# Review project, region and plans before approving cloud changes.
bash gcp/scripts/deploy.sh gen-lang-client-0984590124 --apply us-central1
# Optionally provide GEMINI_KEY_FILE pointing outside the repository before deployment.
# Cloud acceptance (writes synthetic events; requires BigQuery read/job permissions):
python gcp/scripts/smoke_test.py https://SERVICE.run.app /private/gcp_api_key PROJECT_ID --live --require-ai
```

Terraform creates secret containers only; values are loaded outside Terraform. The generated integration key
is stored with mode 600 outside Git. Share it with the AWS owner through a private channel for SSM
`/red-telecorp/<stage>/gcp/api_key`; base URL goes to `gcp/base_url` without a route suffix.
The AWS owner enables `external` only after both external integrations are ready. No AWS infrastructure is changed here.

Deployment has an initial bootstrap without Cloud Run, then image build and final apply. Subsequent runs skip
that bootstrap. Non-secret desired settings persist in ignored `infra/deployment.auto.tfvars.json`.
Keep that file and Terraform state private and backed up together. Never overwrite an existing deployment's state
or import the V2.3 resources blindly: names/protection/IAM changed and need a reviewed migration plan.
`create_table.py --apply` is an explicit bootstrap/repair alternative, not a second concurrent provisioning system;
prefer Terraform and import preexisting resources before managing them there.

Cloud Run scales 0–3; queries have a 1 GB billed-bytes cap per job. The transactional global scan is intended for
hackathon volume; measure cost/latency before larger workloads. Build source objects expire after 7 days.
Table and service deletion protection are enabled. Dataset deletion never silently deletes unknown tables.

```bash
bash gcp/scripts/cleanup.sh PROJECT_ID            # inspect local state only
bash gcp/scripts/cleanup.sh PROJECT_ID --destroy  # separate approval, deletes data and secrets
```

Cleanup verifies the project, requires explicit confirmation, disables protection through a reviewed apply,
then destroys managed resources, including the dedicated build source bucket and its objects. APIs remain enabled.
Do not run deployment, live tests, repair or cleanup without the project owner's approval.

## OTLP / Grafana (T19a)

Enable with `enable_metrics=true`, `grafana_otlp_endpoint` and `grafana_instance_id` in a private tfvars file.
Add the Grafana token to Secret Manager `rtc-gcp-grafana-token` outside Terraform, then set `grafana_token_version`.
Endpoint may be the Grafana OTLP base URL or full `/v1/metrics` URL. Runtime uses HTTPS Basic instance:token.
No identifiers, hashes, event payloads, URLs supplied by callers or error messages become metric attributes.

| Metric | OTLP type / meaning |
|---|---|
| `redtelecorp.gcp.requests` | Cumulative monotonic sum, by normalized route and HTTP status |
| `redtelecorp.gcp.errors` | Cumulative sum of HTTP 4xx/5xx and failed AI dependencies (including 200 fallback) |
| `redtelecorp.gcp.ingest.rows` | Cumulative sum of newly committed rows acknowledged by this process |
| `redtelecorp.gcp.suggest.latency_ms` | Cumulative histogram in milliseconds |

Resource `service.name=red-telecorp-gcp`; random `service.instance.id` separates process counters.
Queue is bounded at 128 samples. Export failure never affects API responses; cumulative values are retried on
subsequent traffic. Queue saturation or instance termination can lose observations; these are operational metrics,
not the durable event ledger. Empty-history fallback is not an error.
With metrics enabled Terraform allocates CPU outside requests so the daemon can export after the response;
this changes Cloud Run billing to instance-based while an instance exists (minimum remains zero). Keep metrics
disabled until Grafana is configured. There is no official `contracts/observability.md` in the reviewed main;
these four names/service name come from the supplied team task document, with types documented above.

Deployment target agreed with the owner: `gen-lang-client-0984590124`; Cloud Run, Artifact Registry, staging
bucket and BigQuery all use `us-central1`. An existing dataset in `US` cannot be moved in place: inspect the
actual deployment before applying; do not replace a populated dataset to change its location.

This target is a new deployment (confirmed by the owner). Run the initial bootstrap only after approval.
Before the final Cloud Run apply, the integration API secret must have an enabled version; Gemini and Grafana
remain optional until their private secret versions and configuration are supplied. A fallback-only smoke test
is not proof of working AI: the final demonstration must pass `--require-ai`.
