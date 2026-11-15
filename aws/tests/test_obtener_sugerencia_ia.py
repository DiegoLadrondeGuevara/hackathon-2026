import json
import threading
import time
from urllib.error import HTTPError

import boto3
import pytest

from common import ddb, outbound
from handlers import obtener_sugerencia_ia as suggestions

SUCCESS = {
    "available": True,
    "hypotheses": [{"title": "Revisar cobertura", "rationale": "Reportes en la zona"}],
    "model": "gemini-3.5-flash-lite",
    "generated_at": "2026-11-14T10:00:00Z",
}


@pytest.fixture
def incident(aws):
    ddb.table("Incidents").put_item(Item={"pk": "INCIDENT#I1", "sk": "META", "zone_id": "Z01"})
    for name, value in {"gcp/base_url": "https://gcp.example", "gcp/api_key": "test-key"}.items():
        boto3.client("ssm").put_parameter(Name=f"/red-telecorp/test/{name}", Value=value, Type="SecureString")


def invoke(role="OPERATOR", incident_id="I1", context=None):
    event = {
        "pathParameters": {"incident_id": incident_id},
        "requestContext": {"authorizer": {"lambda": {"sub": "test-user", "role": role}}},
    }
    response = suggestions.handler(event, context)
    return response["statusCode"], json.loads(response["body"])


def test_operator_success_uses_incident_zone(incident, monkeypatch):
    def send(url, body, headers, timeout):
        assert url == "https://gcp.example/suggest"
        assert body == {"incident_id": "I1", "zone_id": "Z01", "days": 30}
        assert headers == {"X-Api-Key": "test-key"}
        assert 0 < timeout <= 4
        return SUCCESS

    monkeypatch.setattr(outbound, "post_json", send)
    assert invoke() == (200, SUCCESS)


def test_access_and_missing_incident(incident, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("External call must not happen")

    monkeypatch.setattr(outbound, "post_json", forbidden)
    assert invoke("CUSTOMER")[0] == 403
    assert invoke("")[0] == 401
    assert invoke(incident_id="MISSING")[0] == 404
    assert invoke(incident_id="invalid/id")[0] == 400


@pytest.mark.parametrize(
    "error",
    [TimeoutError(), outbound.OutboundError(), HTTPError("https://gcp.example", 503, "provider error", {}, None)],
)
def test_provider_failure_returns_200(incident, monkeypatch, error):
    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(outbound, "post_json", fail)
    assert invoke() == (200, {"available": False})


@pytest.mark.parametrize(
    "body",
    [
        None,
        {},
        {"available": False, "reason": "provider text"},
        {"available": True, "hypotheses": []},
        {**SUCCESS, "generated_at": "bad"},
    ],
)
def test_invalid_response_is_fallback(incident, monkeypatch, body):
    monkeypatch.setattr(outbound, "post_json", lambda *a, **k: body)
    assert invoke() == (200, {"available": False})


def test_pending_configuration(incident, monkeypatch):
    with monkeypatch.context() as patch:
        patch.setattr(suggestions.config, "get_secret", lambda _: "PENDIENTE")
        assert invoke() == (200, {"available": False})


def test_slow_ssm_has_total_deadline(incident, monkeypatch):
    release = threading.Event()
    with monkeypatch.context() as patch:
        patch.setattr(suggestions, "_PROVIDER_SECONDS", 0.02)
        patch.setattr(suggestions.config, "get_secret", lambda _: (release.wait(1), "PENDIENTE")[1])
        start = time.monotonic()
        try:
            assert invoke() == (200, {"available": False})
            assert time.monotonic() - start < 0.3
        finally:
            release.set()


def test_lambda_deadline_reserves_response_time(incident):
    class Context:
        def get_remaining_time_in_millis(self):
            return 100

    assert invoke(context=Context()) == (200, {"available": False})
