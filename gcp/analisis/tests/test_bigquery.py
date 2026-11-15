import time

import bigquery_repo as repo
import pytest
from contract import sanitize_event, to_row
from google.api_core.exceptions import BadRequest


class Job:
    def __init__(self, value=None, failure=None):
        self.value = value
        self.failure = failure

    def result(self, **kwargs):
        assert kwargs["retry"] is None and kwargs["job_retry"] is None
        if self.failure:
            raise self.failure
        return self.value


class BigQuery:
    def __init__(self, jobs):
        self.jobs = iter(jobs)
        self.calls = []

    def query(self, sql, **kwargs):
        self.calls.append((sql, kwargs))
        return next(self.jobs)


def test_guard_transaction_global_dedup_and_count(event):
    bq = BigQuery([Job([{"inserted": 1}]), Job([{"inserted": 0}])])
    rows = [to_row(sanitize_event(event))]
    assert repo.merge_rows(rows, time.monotonic() + 1, bq) == 1
    assert repo.merge_rows(rows, time.monotonic() + 1, bq) == 0
    sql, args = bq.calls[0]
    assert sql.index("BEGIN TRANSACTION") < sql.index("UPDATE") < sql.index("MERGE") < sql.index("COMMIT")
    assert "ASSERT @@row_count = 1" in sql
    assert "ON T.event_id = S.event_id\n" in sql  # No date predicate can bypass uniqueness.
    assert "E1" not in sql
    assert args["job_config"].maximum_bytes_billed == 1000000000
    assert len(args["job_config"].query_parameters) == 11
    assert args["job_id"] != bq.calls[1][1]["job_id"]


def test_conflicting_transaction_retried_after_abort(event):
    bq = BigQuery([Job(failure=BadRequest("Transaction is aborted due to concurrent update")), Job([{"inserted": 0}])])
    assert repo.merge_rows([to_row(sanitize_event(event))], time.monotonic() + 2, bq) == 0
    assert len(bq.calls) == 2


@pytest.mark.parametrize("failure", [TimeoutError(), BadRequest("Invalid SQL")])
def test_ambiguous_timeout_and_sql_errors_not_retried_internally(event, failure):
    bq = BigQuery([Job(failure=failure)])
    with pytest.raises(type(failure)):
        repo.merge_rows([to_row(sanitize_event(event))], time.monotonic() + 1, bq)
    assert len(bq.calls) == 1


def test_history_aggregation_has_no_sample_limit():
    bq = BigQuery(
        [
            Job(
                [
                    {
                        "event_count": 50,
                        "events_by_type": [{"type": "report.created", "count": 50}],
                        "incidents_by_priority": [],
                        "anomaly_antennas": [],
                    }
                ]
            )
        ]
    )
    facts = repo.zone_summary("Z01", 30, time.monotonic() + 1, bq)
    sql, args = bq.calls[0]
    assert facts["event_count"] == 50 and facts["detection_lag_seconds"] is None
    assert "LIMIT 35" not in sql and "PARTITION BY incident_id" in sql
    assert [p.value for p in args["job_config"].query_parameters] == ["Z01", 30]
    assert "customer_hash" not in str(facts) and "payload" not in str(facts)
