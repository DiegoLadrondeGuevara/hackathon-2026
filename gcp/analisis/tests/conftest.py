import socket

import main
import pytest
from flask import Flask, request


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv("API_KEY", "test-key")
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "telecorp-test123")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test-key")

    def forbidden(*args, **kwargs):
        raise AssertionError("Real network is forbidden in unit tests")

    monkeypatch.setattr(socket, "create_connection", forbidden)


@pytest.fixture
def client():
    app = Flask(__name__)
    app.add_url_rule("/<path:path>", view_func=lambda path: main.api(request), methods=["GET", "POST"])
    return app.test_client()


@pytest.fixture
def event():
    return {
        "event_id": "E1",
        "type": "report.created",
        "version": 1,
        "occurred_at": "2026-11-14T10:00:00Z",
        "data": {
            "report_id": "R1",
            "zone_id": "Z01",
            "service": "INTERNET",
            "problem_type": "SIN_INTERNET",
            "customer_hash": "abcdef0123456789",
        },
    }
