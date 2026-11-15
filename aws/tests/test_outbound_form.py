"""common.outbound.post_form: formulario HTTPS con las mismas protecciones que el JSON."""
import json
from urllib.parse import parse_qs

import pytest

from common import outbound


class Response:
    def __init__(self, status=201, value=None):
        self.status, self.value = status, value if value is not None else {"sid": "SM1"}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def read(self, *_):
        return json.dumps(self.value).encode()


def test_envia_formulario_codificado_con_las_cabeceras(monkeypatch):
    vistos = []

    def transport(req, timeout):
        vistos.append((req, timeout))
        return Response()

    monkeypatch.setattr(outbound, "urlopen", transport)
    out = outbound.post_form("https://api.example.com/x", {"To": "+51956839954", "Body": "Hola ñandú & más"},
                             {"Authorization": "Basic abc"}, timeout=7)
    assert out == {"sid": "SM1"}
    (req, timeout) = vistos[0]
    assert req.get_method() == "POST" and timeout == 7
    assert req.get_header("Content-type") == "application/x-www-form-urlencoded"
    assert req.get_header("Authorization") == "Basic abc"
    assert parse_qs(req.data.decode()) == {"To": ["+51956839954"], "Body": ["Hola ñandú & más"]}


def test_exige_https_y_rechaza_credenciales_en_la_url():
    for url in ("http://api.example.com", "https://u:p@api.example.com", "https://api.example.com/#x"):
        with pytest.raises(outbound.OutboundError):
            outbound.post_form(url, {"a": "b"})


def test_respuesta_no_exitosa_o_error_no_filtra_detalles(monkeypatch):
    monkeypatch.setattr(outbound, "urlopen", lambda req, timeout: Response(status=500))
    with pytest.raises(outbound.OutboundError) as exc:
        outbound.post_form("https://api.example.com", {"Body": "secreto-xyz"})
    assert "secreto-xyz" not in str(exc.value)


def test_el_json_sigue_igual(monkeypatch):
    vistos = []
    monkeypatch.setattr(outbound, "urlopen", lambda req, timeout: vistos.append(req) or Response(200, {}))
    outbound.post_json("https://api.example.com", {"a": 1})
    assert vistos[0].get_header("Content-type") == "application/json" and vistos[0].data == b'{"a":1}'
