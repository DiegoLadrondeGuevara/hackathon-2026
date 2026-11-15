"""Dependency-free tests; no GCP credentials or network calls."""

import importlib.util
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

MODULE = Path(__file__).resolve().parents[1] / "ensure_guard.py"
spec = importlib.util.spec_from_file_location("ensure_guard", MODULE)
ensure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ensure)


def test_repair_is_idempotent_and_checks_real_rows():
    commands = []

    def fake_run(command, **kwargs):
        commands.append((command, kwargs))
        if "MERGE" in command[-1]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, 0, "matches\n1\n", "")

    with patch.object(ensure.subprocess, "run", side_effect=fake_run):
        assert ensure.ensure_guard("project-12345", apply=True)
        assert ensure.ensure_guard("project-12345", apply=True)
    assert len(commands) == 4
    assert "WHEN NOT MATCHED THEN INSERT" in commands[0][0][-1]
    assert "DELETE" not in commands[0][0][-1]
    assert "--location=us-central1" in commands[0][0]
    assert "COUNTIF" in commands[1][0][-1]
    assert all(kwargs.get("timeout") == 90 for _, kwargs in commands)


def test_verify_only_does_not_modify_database():
    with patch.object(ensure.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, "matches\n1\n", "")) as runner:
        assert ensure.ensure_guard("project-12345", apply=False)
    assert runner.call_count == 1
    assert "SELECT" in runner.call_args.args[0][-1]


@pytest.mark.parametrize("output", ["matches\n0\n", "matches\n2\n", "matches\n"])
def test_missing_or_duplicate_guard_fails_closed(output):
    with patch.object(ensure.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output, "")):
        with pytest.raises(RuntimeError):
            ensure.ensure_guard("project-12345")


@pytest.mark.parametrize("project,dataset,location", [
    ("bad; rm -rf /", "redtelecorp", "us-central1"),
    ("project-12345", "bad`table", "us-central1"),
    ("project-12345", "redtelecorp", "invalid location"),
])
def test_untrusted_identifiers_rejected_before_subprocess(project, dataset, location):
    with patch.object(ensure.subprocess, "run") as runner:
        with pytest.raises(ValueError):
            ensure.ensure_guard(project, dataset, location, apply=True)
        runner.assert_not_called()


def test_cli_failures_are_not_silently_ignored():
    failure = subprocess.CalledProcessError(1, ["bq"])
    with patch.object(ensure.subprocess, "run", side_effect=failure):
        with pytest.raises(subprocess.CalledProcessError):
            ensure.ensure_guard("project-12345", apply=True)


def test_deploy_verifies_guard_before_building_image():
    text = (MODULE.parent / "deploy.sh").read_text()
    assert text.index('"$HERE/scripts/ensure_guard.py"') < text.index("gcloud builds submit")
    assert "--apply" in text
