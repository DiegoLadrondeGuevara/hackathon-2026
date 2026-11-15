"""Grafana failure must not change the public Azure API result."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import azure.functions as func

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
import function_app  # noqa: E402
import observability  # noqa: E402


class FunctionObservabilityTests(unittest.TestCase):
    def test_get_still_returns_zone_when_otlp_is_unavailable(self):
        zone = {"zone_id": "Z01", "status": "EVALUACION", "last_synced_at": "2026-11-15T01:11:31Z"}
        req = func.HttpRequest(method="GET", url="https://example.test/api/estado", body=b"")
        env = {
            "GRAFANA_OTLP_ENDPOINT": "https://otlp.example.test/otlp",
            "GRAFANA_INSTANCE_ID": "12345",
            "GRAFANA_TOKEN": "dummy-test-token",
        }
        with patch.dict("os.environ", env):
            with patch.object(function_app, "get_table_client", return_value=object()):
                with patch.object(function_app, "list_zones", return_value=[zone]):
                    with patch.object(observability, "urlopen", side_effect=OSError("network down")):
                        response = function_app.consultar_estados(req)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.get_body()), {"zones": [zone]})


if __name__ == "__main__":
    unittest.main()
