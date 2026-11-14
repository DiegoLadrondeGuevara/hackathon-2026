"""Guardia: cada handler declarado en infra/functions.yml existe y expone `handler`."""
import importlib
import re
from pathlib import Path

FUNCTIONS = Path(__file__).resolve().parents[1] / "infra" / "functions.yml"
NAMES = re.findall(r"handler: src/handlers/(\w+)\.handler", FUNCTIONS.read_text(encoding="utf-8"))


def test_hay_handlers_declarados():
    assert len(NAMES) >= 20


def test_cada_handler_existe_y_es_invocable():
    for name in NAMES:
        module = importlib.import_module(f"handlers.{name}")
        assert callable(getattr(module, "handler", None)), name
