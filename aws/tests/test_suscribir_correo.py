"""scripts/suscribir_correo.py: suscripciones de correo al tema de avisos a clientes."""
import importlib.util
import json
from pathlib import Path

import boto3
import pytest

from common import pii

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "suscribir_correo.py"
STAGE = ["--stage", "test"]
SAL = "sal-de-prueba"
CORREO = "demo@example.com"


@pytest.fixture
def correo(aws):
    spec = importlib.util.spec_from_file_location("suscribir_correo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    sns = boto3.client("sns")
    topic = sns.create_topic(Name="red-telecorp-test-notificaciones-clientes")["TopicArn"]
    boto3.client("ssm").put_parameter(Name="/red-telecorp/test/pii_salt", Value=SAL, Type="SecureString")
    return mod, sns, topic


def _subs(sns, topic):
    return sns.list_subscriptions_by_topic(TopicArn=topic)["Subscriptions"]


def _filtro(sns, sub):
    attrs = sns.get_subscription_attributes(SubscriptionArn=sub["SubscriptionArn"])["Attributes"]
    return json.loads(attrs["FilterPolicy"]) if attrs.get("FilterPolicy") else None, attrs.get("FilterPolicyScope")


def test_suscribe_con_filtro_por_cliente_usando_el_seudonimo(correo, capsys):
    mod, sns, topic = correo
    mod.main(["suscribir", "--correo", CORREO, "--cliente", "70000002", "--cliente", "70000001", *STAGE])
    (sub,) = _subs(sns, topic)
    assert sub["Protocol"] == "email" and sub["Endpoint"] == CORREO
    politica, alcance = _filtro(sns, sub)
    esperado = sorted({pii.customer_hash(SAL, "70000001"), pii.customer_hash(SAL, "70000002")})
    assert politica == {"customer_hash": esperado} and alcance == "MessageAttributes"
    salida = capsys.readouterr().out
    assert "2 cliente(s)" in salida and "confirmación" in salida
    assert "70000001" not in json.dumps(politica) and SAL not in salida


def test_todos_suscribe_sin_filtro(correo):
    mod, sns, topic = correo
    mod.main(["suscribir", "--correo", CORREO, "--todos", *STAGE])
    (sub,) = _subs(sns, topic)
    assert _filtro(sns, sub)[0] is None


def test_sin_cliente_ni_todos_pide_indicarlo(correo):
    mod, sns, topic = correo
    with pytest.raises(SystemExit, match="--cliente"):
        mod.main(["suscribir", "--correo", CORREO, *STAGE])
    assert _subs(sns, topic) == []


def test_sin_tema_desplegado_avisa(aws):
    spec = importlib.util.spec_from_file_location("suscribir_correo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    with pytest.raises(SystemExit, match="despliega"):
        mod.main(["listar", *STAGE])


def test_suscripcion_pendiente_no_se_duplica(correo, monkeypatch):
    mod, sns, topic = correo
    pendiente = [{"Endpoint": CORREO, "Protocol": "email", "SubscriptionArn": "PendingConfirmation"}]
    monkeypatch.setattr(mod, "subscriptions", lambda _sns, _arn: pendiente)  # así responde el SNS real
    with pytest.raises(SystemExit, match="pendiente"):
        mod.main(["suscribir", "--correo", CORREO, "--cliente", "70000002", *STAGE])
    assert _subs(sns, topic) == []  # no se creó otra suscripción


def test_correo_ya_confirmado_solo_actualiza_su_filtro(correo, capsys):
    mod, sns, topic = correo
    mod.main(["suscribir", "--correo", CORREO, "--cliente", "70000001", *STAGE])
    (sub,) = _subs(sns, topic)
    if sub["SubscriptionArn"] == "PendingConfirmation":
        pytest.skip("el SNS real deja la suscripción pendiente hasta confirmar")
    mod.main(["suscribir", "--correo", CORREO, "--cliente", "70000002", *STAGE])
    assert len(_subs(sns, topic)) == 1 and "filtro actualizado" in capsys.readouterr().out
    assert _filtro(sns, _subs(sns, topic)[0])[0] == {"customer_hash": [pii.customer_hash(SAL, "70000002")]}


def test_listar_muestra_correo_y_estado(correo, capsys):
    mod, _, _ = correo
    mod.main(["listar", *STAGE])
    assert "Sin suscripciones" in capsys.readouterr().out
    mod.main(["suscribir", "--correo", CORREO, "--todos", *STAGE])
    capsys.readouterr()
    mod.main(["listar", *STAGE])
    salida = capsys.readouterr().out
    assert CORREO in salida and ("pendiente de confirmar" in salida or "confirmada" in salida)
