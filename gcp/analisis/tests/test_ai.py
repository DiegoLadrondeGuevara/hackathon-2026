import json
import time

import ai
import pytest


class Response:
    status = 200

    def __init__(self, items):
        self.items = items

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, *_):
        return json.dumps(
            {"candidates": [{"content": {"parts": [{"text": json.dumps({"hypotheses": self.items})}]}}]}
        ).encode()


def test_gemini_request_uses_aggregates_and_fixed_schema(monkeypatch):
    facts = {"zone_id": "Z01", "event_count": 42, "detection_lag_seconds": None}

    class Opener:
        def open(self, request, timeout):
            body = json.loads(request.data)
            assert 0 < timeout <= 1
            assert "AWS es la fuente de verdad" in body["contents"][0]["parts"][0]["text"]
            assert "customer_hash" not in str(body)
            assert request.get_header("X-goog-api-key") == "gemini-test-key"
            return Response([{"title": "Revisar cobertura", "rationale": "Existen reportes agregados."}])

    monkeypatch.setattr(ai.urllib.request, "build_opener", lambda *a: Opener())
    result = ai.generate_hypotheses(facts, time.monotonic() + 1)
    assert set(result) == {"available", "hypotheses", "model", "generated_at"}
    assert result["available"] and len(result["hypotheses"]) == 1


@pytest.mark.parametrize(
    "items",
    [[], None, [{"title": "missing"}], [{"title": "", "rationale": "r"}], [{"title": "t", "rationale": "r"}] * 4],
)
def test_invalid_hypotheses_rejected(monkeypatch, items):
    class Opener:
        def open(self, *a, **k):
            return Response(items)

    monkeypatch.setattr(ai.urllib.request, "build_opener", lambda *a: Opener())
    with pytest.raises(ValueError):
        ai.generate_hypotheses({}, time.monotonic() + 1)
