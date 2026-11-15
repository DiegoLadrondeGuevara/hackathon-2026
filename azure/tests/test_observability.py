"""The exporter sends only aggregate metrics and never interrupts the API."""

import base64
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import observability  # noqa: E402


class FakeResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        observability._REQUESTS.clear()
        observability._ERRORS.clear()

    def test_unconfigured_exporter_does_nothing(self):
        with patch.dict("os.environ", {"GRAFANA_OTLP_ENDPOINT": "", "GRAFANA_INSTANCE_ID": "", "GRAFANA_TOKEN": ""}):
            with patch.object(observability, "urlopen") as send:
                observability.record_request("GET /api/estado", 200, 12.0)
        send.assert_not_called()

    def test_export_uses_otlp_json_and_no_zone_or_customer_identifiers(self):
        env = {
            "GRAFANA_OTLP_ENDPOINT": "https://otlp.example.test/otlp",
            "GRAFANA_INSTANCE_ID": "12345",
            "GRAFANA_TOKEN": "dummy-test-token",
            "AZURE_ENVIRONMENT": "test",
        }
        zones = [{"zone_id": "Z01", "last_synced_at": "2020-01-01T00:00:00Z", "customer_id": "private"}]
        with patch.dict("os.environ", env):
            with patch.object(observability, "urlopen", return_value=FakeResponse()) as send:
                observability.record_request("GET /api/estado", 200, 12.5, zones)

        request = send.call_args.args[0]
        self.assertEqual(request.full_url, "https://otlp.example.test/otlp/v1/metrics")
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.get_header("Content-type"), "application/json")
        credentials = request.get_header("Authorization").removeprefix("Basic ")
        self.assertEqual(base64.b64decode(credentials).decode(), "12345:dummy-test-token")
        self.assertEqual(send.call_args.kwargs["timeout"], 1.0)

        payload = json.loads(request.data)
        encoded = json.dumps(payload)
        self.assertNotIn("customer_id", encoded)
        self.assertNotIn("private", encoded)
        self.assertNotIn("zone_id", encoded)
        self.assertNotIn("Z01", encoded)
        self.assertNotIn("dummy-test-token", encoded)
        metrics = payload["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        self.assertEqual(
            {metric["name"] for metric in metrics},
            {"redtelecorp.azure.requests", "redtelecorp.azure.latency_ms", "redtelecorp.azure.zones_stale", "redtelecorp.azure.sync_age_max_seconds"},
        )
        self.assertEqual(metrics[0]["sum"]["aggregationTemporality"], 2)
        self.assertEqual(metrics[2]["gauge"]["dataPoints"][0]["asDouble"], 1)

    def test_failed_export_is_best_effort_and_count_remains_cumulative(self):
        env = {
            "GRAFANA_OTLP_ENDPOINT": "https://otlp.example.test/otlp/v1/metrics",
            "GRAFANA_INSTANCE_ID": "12345",
            "GRAFANA_TOKEN": "dummy-test-token",
        }
        with patch.dict("os.environ", env):
            with patch.object(observability, "urlopen", side_effect=OSError("network down")):
                observability.record_request("PUT /api/estado/{zone_id}", 500, 4.0)
            with patch.object(observability, "urlopen", return_value=FakeResponse()) as send:
                observability.record_request("PUT /api/estado/{zone_id}", 500, 5.0)

        request = send.call_args.args[0]
        self.assertEqual(request.full_url, env["GRAFANA_OTLP_ENDPOINT"])
        metrics = json.loads(request.data)["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
        counts = {metric["name"]: metric["sum"]["dataPoints"][0]["asInt"] for metric in metrics if "sum" in metric}
        self.assertEqual(counts["redtelecorp.azure.requests"], "2")
        self.assertEqual(counts["redtelecorp.azure.errors"], "2")


if __name__ == "__main__":
    unittest.main()
