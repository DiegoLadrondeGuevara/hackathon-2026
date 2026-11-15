"""No-network tests for the minimal live verification workflow."""

import importlib.util
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

MODULE = Path(__file__).resolve().parents[1] / "smoke_single.py"
sys.path.insert(0, str(MODULE.parent))
spec = importlib.util.spec_from_file_location("smoke_single", MODULE)
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_single_event_replay_and_physical_row_check(tmp_path):
    keyfile = tmp_path / "key"
    keyfile.write_text("test-secret")
    posts = []

    def fake_post(url, key, events):
        posts.append((url, key, events[0]["event_id"]))
        return {"inserted": 1 if len(posts) == 1 else 0}

    with patch("ensure_guard.ensure_guard", return_value=True), \
         patch.object(smoke, "post_ingest", side_effect=fake_post), \
         patch.object(smoke, "run_query", return_value="matches\n1\n") as query:
        smoke.smoke("https://test.example", str(keyfile), "project-12345")
    assert len(posts) == 2
    assert posts[0][2] == posts[1][2]
    assert posts[0][1] == "test-secret"
    assert "WHERE event_id" in query.call_args.args[-1]


def test_duplicate_or_missing_row_fails(tmp_path):
    keyfile = tmp_path / "key"
    keyfile.write_text("test-secret")
    with patch("ensure_guard.ensure_guard", return_value=True), \
         patch.object(smoke, "post_ingest", side_effect=[{"inserted": 1}, {"inserted": 0}]), \
         patch.object(smoke, "run_query", return_value="matches\n2\n"):
        with pytest.raises(RuntimeError, match="BigQuery rows=2"):
            smoke.smoke("https://test.example", str(keyfile), "project-12345")
