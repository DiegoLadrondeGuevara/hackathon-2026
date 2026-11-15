"""Standard-library transaction regression harness for environments without google-cloud-bigquery.
Run: python3 gcp/scripts/tests/offline_transaction_harness.py
It mocks the Google SDK; it does not prove BigQuery succeeds in Google Cloud.
"""

import concurrent.futures
import importlib.util
import pathlib
import sys
import threading
import time
import types

root = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(root / "analisis"))


def module(name):
    obj = types.ModuleType(name)
    obj.__path__ = []
    sys.modules[name] = obj
    return obj


google = module("google")
api = module("google.api_core")
exceptions = module("google.api_core.exceptions")
cloud = module("google.cloud")
bigquery = module("google.cloud.bigquery")
google.api_core, google.cloud = api, cloud
api.exceptions = exceptions
cloud.bigquery = bigquery


class BadRequest(Exception):
    pass


class Conflict(Exception):
    pass


class ScalarQueryParameter:
    def __init__(self, name, type_, value):
        self.name, self.type_, self.value = name, type_, value


class QueryJobConfig:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


exceptions.BadRequest = BadRequest
exceptions.Conflict = Conflict
bigquery.QueryJobConfig = QueryJobConfig
bigquery.ScalarQueryParameter = ScalarQueryParameter

spec = importlib.util.spec_from_file_location("bigquery_repo", root / "analisis/bigquery_repo.py")
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)

import os
os.environ["GOOGLE_CLOUD_PROJECT"] = "test-project-123"

record = {k: "demo" for k in repo.COLUMNS}
record["event_id"] = "E-DEMO-1"
record["occurred_at"] = "2026-11-15T00:00:00Z"
seen = set()
lock = threading.Lock()
active = 0
max_active = 0


class Job:
    def __init__(self, event):
        self.event = event

    def result(self, **kwargs):
        global active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.04)
            with lock:
                if self.event in seen:
                    return [{"inserted": 0}]
                seen.add(self.event)
                return [{"inserted": 1}]
        finally:
            with lock:
                active -= 1


class Client:
    def query(self, sql, **kwargs):
        assert "ASSERT @@row_count = 1" in sql
        assert "BEGIN TRANSACTION" in sql
        assert "ON T.event_id = S.event_id" in sql
        return Job(next(p.value for p in kwargs["job_config"].query_parameters if p.name == "event_id_0"))


with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(lambda _: repo.merge_rows([record], time.monotonic() + 2, Client()), range(4)))
assert sorted(results) == [0, 0, 0, 1], results
assert max_active == 1, max_active
print("PASS offline: four simultaneous calls serialized, exactly one insertion, three deduplications")


class FailingClient:
    def __init__(self):
        self.calls = 0

    def query(self, sql, **kwargs):
        self.calls += 1
        if self.calls == 1:
            raise BadRequest("Transaction is aborted due to concurrent update")
        return Job("E-DEMO-1")


client = FailingClient()
assert repo.merge_rows([record], time.monotonic() + 2, client) == 0
assert client.calls == 2
print("PASS offline: retryable BigQuery conflict retried without duplicate insertion")

repo._local_ingest_lock.acquire()
try:
    try:
        repo.merge_rows([record], time.monotonic() + 0.02, Client())
        assert False, "Should have timed out waiting for local lock"
    except TimeoutError:
        print("PASS offline: local lock acquisition respects request deadline")
finally:
    repo._local_ingest_lock.release()
