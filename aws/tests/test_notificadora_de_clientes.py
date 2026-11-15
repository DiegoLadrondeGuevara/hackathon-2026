"""T12: notificadora_de_clientes."""
import base64
import json

import boto3
import pytest

from common import ddb, ids, outbound, pii
from handlers import notificadora_de_clientes as notif

INCIDENTE = "I0000000000000000000000001"
BASE = "2026-11-14T10:00:00.000Z"


def _perfil(customer="70000001", pref="EMAIL", email=True, sms=True, with_email=True, with_phone=True):
    item = {
        "pk": f"CUSTOMER#{customer}", "sk": "PROFILE", "type": "CUSTOMER", "customer_id": customer,
        "role": "CUSTOMER", "channel_pref": pref, "consent_email": email, "consent_sms": sms,
        "created_at": BASE,
    }
    if with_email:
        item["email"] = f"{customer}@example.com"
    if with_phone:
        item["phone"] = "+51999000111"
    ddb.table("CustomerProfiles").put_item(Item=item)


def _vinculo(customer):
    ddb.table("Incidents").put_item(Item={
        "pk": f"INCIDENT#{INCIDENTE}", "sk": f"LINK#USER#{customer}", "type": "LINK_USER",
        "customer_id": customer, "first_report_id": "R1", "linked_at": BASE,
    })


def _record(event_type, data, message_id="m1"):
    envelope = {"event_id": ids.new_id(), "type": event_type, "version": 1, "occurred_at": BASE, "data": data}
    body = {"source": "red-telecorp", "detail-type": event_type, "detail": envelope}
    return {"messageId": message_id, "body": json.dumps(body)}


def _actualizado(milestone="CONFIRMADO", message_id="m1"):
    return _record("incident.updated", {
        "incident_id": INCIDENTE, "zone_id": "Z05", "service": "INTERNET", "status": milestone or "EVALUACION",
        "milestone": milestone, "change": "STATUS", "affected_users": 2, "updated_at": BASE,
    }, message_id)


def _vinculado(customer="70000001", status="EVALUACION", message_id="m1"):
    return _record("report.linked", {
        "incident_id": INCIDENTE, "report_id": "R1", "customer_id": customer, "zone_id": "Z05",
        "incident_status": status, "linked_at": BASE,
    }, message_id)


def _run(*records):
    return notif.handler({"Records": list(records)}, None)


def _notify_items():
    items = ddb.table("Incidents").scan()["Items"]
    return {i["sk"]: i for i in items if i["type"] == "NOTIFY"}


def _fallos(resp):
    return [f["itemIdentifier"] for f in resp["batchItemFailures"]]


@pytest.fixture
def ses_sns(aws, monkeypatch):
    """SES y SNS reales de moto, con remitente verificado y parámetro SSM del remitente."""
    monkeypatch.setenv("EMAIL_MODE", "SES")
    monkeypatch.setenv("SMS_MODE", "SNS")
    boto3.client("ses").verify_email_identity(EmailAddress="avisos@example.com")
    boto3.client("ssm").put_parameter(Name="/red-telecorp/test/ses/from_address", Value="avisos@example.com",
                                      Type="String")


def test_incidente_notifica_a_todos_los_vinculados_en_simulado(aws):
    for c in ("70000001", "70000002"):
        _perfil(c)
        _vinculo(c)
    assert _run(_actualizado("CONFIRMADO")) == {"batchItemFailures": []}
    items = _notify_items()
    assert sorted(items) == ["NOTIFY#CONFIRMADO#70000001", "NOTIFY#CONFIRMADO#70000002"]
    for item in items.values():
        assert item["status"] == "SENT" and item["channel"] == "SIMULATED" and item["attempts"] == 1
        assert item["milestone"] == "CONFIRMADO" and item["sent_at"]


def test_evento_sin_hito_se_ignora(aws):
    _perfil()
    _vinculo("70000001")
    assert _run(_actualizado(None), _vinculado(status="CONFIRMADO_X"))["batchItemFailures"] == []
    assert _notify_items() == {}


def test_report_linked_notifica_solo_al_cliente_del_evento(aws):
    for c in ("70000001", "70000002"):
        _perfil(c)
        _vinculo(c)
    _run(_vinculado("70000002", "EVALUACION"))
    assert list(_notify_items()) == ["NOTIFY#EVALUACION#70000002"]


def test_report_linked_con_estado_distinto_de_un_hito_se_ignora(aws):
    _perfil()
    _run(_vinculado(status="CERRADO"))
    assert _notify_items() == {}


def test_misma_intencion_desde_dos_eventos_envia_una_vez(ses_sns, monkeypatch):
    _perfil()
    _vinculo("70000001")
    enviados = []
    monkeypatch.setattr(notif, "_send_email", lambda profile, text: enviados.append(text) or "id-1")
    _run(_actualizado("EVALUACION", "m1"), _vinculado("70000001", "EVALUACION", "m2"), _actualizado("EVALUACION", "m3"))
    assert len(enviados) == 1
    assert enviados[0] == notif.TEMPLATES["EVALUACION"]
    assert len(_notify_items()) == 1


def test_hitos_distintos_son_intenciones_distintas(aws):
    _perfil()
    _vinculo("70000001")
    _run(_actualizado("EVALUACION"), _actualizado("CONFIRMADO"), _actualizado("RESTABLECIDO"))
    assert len(_notify_items()) == 3


def test_sin_consentimiento_queda_skipped_con_canal_none(aws):
    _perfil(email=False, sms=False)
    _vinculo("70000001")
    assert _run(_actualizado())["batchItemFailures"] == []
    item = _notify_items()["NOTIFY#CONFIRMADO#70000001"]
    assert item["status"] == "SKIPPED" and item["channel"] == "NONE"


def test_perfil_inexistente_queda_skipped(aws):
    _vinculo("70000009")
    assert _run(_actualizado())["batchItemFailures"] == []
    item = _notify_items()["NOTIFY#CONFIRMADO#70000009"]
    assert item["status"] == "SKIPPED" and item["error"] == "PROFILE_NOT_FOUND"


def test_skipped_no_se_vuelve_a_evaluar(aws):
    _perfil(email=False, sms=False)
    _vinculo("70000001")
    _run(_actualizado())
    _perfil()  # ahora sí consiente, pero la intención ya está resuelta
    _run(_actualizado())
    assert _notify_items()["NOTIFY#CONFIRMADO#70000001"]["status"] == "SKIPPED"


@pytest.mark.parametrize("perfil,esperado", [
    (dict(pref="EMAIL"), "EMAIL"),
    (dict(pref="SMS"), "SMS"),
    (dict(pref="EMAIL", email=False), "SMS"),
    (dict(pref="SMS", sms=False), "EMAIL"),
    (dict(pref="EMAIL", with_email=False), "SMS"),
    (dict(pref="SMS", with_phone=False), "EMAIL"),
])
def test_eleccion_de_canal(perfil, esperado):
    profile = {"channel_pref": perfil["pref"], "consent_email": perfil.get("email", True),
               "consent_sms": perfil.get("sms", True)}
    if perfil.get("with_email", True):
        profile["email"] = "a@example.com"
    if perfil.get("with_phone", True):
        profile["phone"] = "+51999000111"
    assert notif._channel(profile) == esperado


def test_consentimiento_debe_ser_verdadero_explicito():
    assert notif._channel({"channel_pref": "EMAIL", "consent_email": "false", "email": "a@example.com"}) is None


def test_envio_real_por_ses_y_sns_guarda_message_id(ses_sns):
    _perfil("70000001", pref="EMAIL")
    _perfil("70000002", pref="SMS")
    for c in ("70000001", "70000002"):
        _vinculo(c)
    assert _run(_actualizado())["batchItemFailures"] == []
    items = _notify_items()
    correo, sms = items["NOTIFY#CONFIRMADO#70000001"], items["NOTIFY#CONFIRMADO#70000002"]
    assert (correo["status"], correo["channel"]) == ("SENT", "EMAIL")
    assert (sms["status"], sms["channel"]) == ("SENT", "SMS")
    assert correo["message_id"] and sms["message_id"]


def test_fallo_de_envio_reintenta_hasta_tres_y_luego_se_detiene(aws, monkeypatch):
    monkeypatch.setenv("EMAIL_MODE", "SES")
    boto3.client("ssm").put_parameter(Name="/red-telecorp/test/ses/from_address", Value="sin-verificar@example.com",
                                      Type="String")
    _perfil(sms=False)
    _vinculo("70000001")
    clave = "NOTIFY#CONFIRMADO#70000001"
    assert _fallos(_run(_actualizado())) == ["m1"]
    assert (_notify_items()[clave]["status"], _notify_items()[clave]["attempts"]) == ("FAILED", 1)
    assert _fallos(_run(_actualizado())) == ["m1"]
    assert _notify_items()[clave]["attempts"] == 2
    assert _fallos(_run(_actualizado())) == []  # tercer intento: ya no se reintenta
    item = _notify_items()[clave]
    assert (item["status"], item["attempts"], item["channel"]) == ("FAILED", 3, "EMAIL")
    assert item["error"] == "MessageRejected"
    assert _fallos(_run(_actualizado())) == []  # agotado: no se vuelve a enviar
    assert _notify_items()[clave]["attempts"] == 3


def test_reintento_exitoso_despues_de_un_fallo(ses_sns, monkeypatch):
    _perfil(sms=False)
    _vinculo("70000001")
    clave = "NOTIFY#CONFIRMADO#70000001"

    def falla(profile, text):
        raise notif.SendError("Throttling")

    original = notif._send_email
    monkeypatch.setattr(notif, "_send_email", falla)
    assert _fallos(_run(_actualizado())) == ["m1"]
    monkeypatch.setattr(notif, "_send_email", original)
    assert _fallos(_run(_actualizado())) == []
    item = _notify_items()[clave]
    assert (item["status"], item["attempts"]) == ("SENT", 2)
    assert item["message_id"]


def test_fallo_de_un_destinatario_no_repite_a_los_ya_enviados(ses_sns, monkeypatch):
    for c in ("70000001", "70000002"):
        _perfil(c, sms=False)
        _vinculo(c)
    llamadas = []

    def envia(profile, text):
        llamadas.append(profile["customer_id"])
        if profile["customer_id"] == "70000002" and llamadas.count("70000002") == 1:
            raise notif.SendError("Throttling")
        return "id"

    monkeypatch.setattr(notif, "_send_email", envia)
    assert _fallos(_run(_actualizado())) == ["m1"]
    assert _fallos(_run(_actualizado())) == []
    assert llamadas == ["70000001", "70000002", "70000002"]
    assert {i["status"] for i in _notify_items().values()} == {"SENT"}


def test_pending_abandonado_se_reintenta(aws):
    _perfil()
    _vinculo("70000001")
    ddb.table("Incidents").put_item(Item={
        "pk": f"INCIDENT#{INCIDENTE}", "sk": "NOTIFY#CONFIRMADO#70000001", "type": "NOTIFY",
        "milestone": "CONFIRMADO", "customer_id": "70000001", "status": "PENDING", "attempts": 0,
        "created_at": BASE,
    })
    _run(_actualizado())
    assert _notify_items()["NOTIFY#CONFIRMADO#70000001"]["status"] == "SENT"


def test_mensajes_invalidos_se_descartan(aws):
    malos = [
        {"messageId": "a", "body": "no es json"},
        {"messageId": "b", "body": json.dumps({"detail": {"type": "report.created", "data": {}}})},
        {"messageId": "c", "body": json.dumps({"detail": {"type": "incident.updated", "data": {"milestone": "X"}}})},
        _record("report.linked", {"incident_id": INCIDENTE, "incident_status": "CONFIRMADO"}, "d"),
    ]
    assert _run(*malos) == {"batchItemFailures": []}
    assert _notify_items() == {}


def test_error_inesperado_devuelve_el_registro_a_la_cola(aws, monkeypatch):
    _perfil()
    _vinculo("70000001")

    def explota(*args):
        raise RuntimeError("tabla no disponible")

    monkeypatch.setattr(notif, "_recipients", explota)
    assert _fallos(_run(_actualizado(message_id="x1"))) == ["x1"]


def test_los_logs_no_llevan_datos_personales(aws, caplog):
    _perfil()
    _vinculo("70000001")
    with caplog.at_level("INFO"):
        _run(_actualizado())
    texto = caplog.text
    assert "70000001" not in texto and "example.com" not in texto and "+51999" not in texto


# --- Correo por tema SNS (EMAIL_MODE=SNS) ---

@pytest.fixture
def correo_sns(aws, monkeypatch):
    """Tema SNS con una cola suscrita, para leer lo publicado. Devuelve (tema, leer, suscribir_con_filtro)."""
    monkeypatch.setenv("EMAIL_MODE", "SNS")
    sns, sqs = boto3.client("sns"), boto3.client("sqs")
    topic = sns.create_topic(Name="red-telecorp-test-notificaciones-clientes")["TopicArn"]
    monkeypatch.setenv("CUSTOMERS_TOPIC_ARN", topic)
    boto3.client("ssm").put_parameter(Name="/red-telecorp/test/pii_salt", Value="sal-de-prueba", Type="SecureString")

    def suscribir(nombre, customer_id=None):
        url = sqs.create_queue(QueueName=nombre)["QueueUrl"]
        arn = sqs.get_queue_attributes(QueueUrl=url, AttributeNames=["QueueArn"])["Attributes"]["QueueArn"]
        attrs = {}
        if customer_id:
            h = pii.customer_hash("sal-de-prueba", customer_id)
            attrs = {"FilterPolicy": json.dumps({"customer_hash": [h]}), "FilterPolicyScope": "MessageAttributes"}
        sns.subscribe(TopicArn=topic, Protocol="sqs", Endpoint=arn, Attributes=attrs)
        return url

    def leer(url):
        msgs = sqs.receive_message(QueueUrl=url, MaxNumberOfMessages=10).get("Messages", [])
        return [json.loads(m["Body"]) for m in msgs]

    return topic, leer, suscribir


def test_correo_por_sns_publica_en_el_tema_con_seudonimo(correo_sns):
    topic, leer, suscribir = correo_sns
    todos = suscribir("todos")
    _perfil("70000001", sms=False)
    _vinculo("70000001")
    assert _run(_actualizado("CONFIRMADO"))["batchItemFailures"] == []
    item = _notify_items()["NOTIFY#CONFIRMADO#70000001"]
    assert (item["status"], item["channel"]) == ("SENT", "EMAIL") and item["message_id"]
    (msg,) = leer(todos)
    assert msg["Message"] == notif.TEMPLATES["CONFIRMADO"] and msg["Subject"] == notif.SUBJECT
    assert msg["MessageAttributes"]["customer_hash"]["Value"] == pii.customer_hash("sal-de-prueba", "70000001")


def test_correo_por_sns_no_lleva_documento_ni_correo(correo_sns):
    _, leer, suscribir = correo_sns
    todos = suscribir("todos")
    _perfil("70000001", sms=False)
    _vinculo("70000001")
    _run(_actualizado())
    texto = json.dumps(leer(todos))
    assert "70000001" not in texto and "example.com" not in texto and "+51999" not in texto


def test_cada_suscriptor_recibe_solo_los_clientes_que_eligio(correo_sns):
    _, leer, suscribir = correo_sns
    solo_uno, otro, todos = suscribir("uno", "70000001"), suscribir("otro", "70000002"), suscribir("todos")
    for c in ("70000001", "70000002", "70000003"):
        _perfil(c, sms=False)
        _vinculo(c)
    _run(_actualizado())
    assert len(leer(solo_uno)) == 1 and len(leer(otro)) == 1 and len(leer(todos)) == 3


def test_correo_por_sns_sin_tema_configurado_falla_y_reintenta(correo_sns, monkeypatch):
    monkeypatch.delenv("CUSTOMERS_TOPIC_ARN")
    _perfil(sms=False)
    _vinculo("70000001")
    assert _fallos(_run(_actualizado())) == ["m1"]
    item = _notify_items()["NOTIFY#CONFIRMADO#70000001"]
    assert (item["status"], item["error"], item["attempts"]) == ("FAILED", "TopicNotConfigured", 1)


def test_el_modo_sms_sigue_independiente_del_correo_por_sns(correo_sns, monkeypatch):
    monkeypatch.setenv("SMS_MODE", "SIMULATED")
    _perfil(pref="SMS", email=False, sms=True)
    _vinculo("70000001")
    _run(_actualizado())
    assert _notify_items()["NOTIFY#CONFIRMADO#70000001"]["channel"] == "SIMULATED"


# --- SMS por Twilio (SMS_MODE=TWILIO) ---

SID_TWILIO, TOKEN_TWILIO, DESDE = "ACtest0000000000000000000000000000", "token-secreto-de-prueba", "+17372508034"


@pytest.fixture
def twilio(aws, monkeypatch):
    """SMS_MODE=TWILIO con credenciales en SSM y la API de Twilio simulada. Devuelve la lista de llamadas."""
    monkeypatch.setenv("SMS_MODE", "TWILIO")
    ssm = boto3.client("ssm")
    for key, value, kind in (("account_sid", SID_TWILIO, "String"), ("auth_token", TOKEN_TWILIO, "SecureString"),
                             ("from_number", DESDE, "String")):
        ssm.put_parameter(Name=f"/red-telecorp/test/twilio/{key}", Value=value, Type=kind)
    llamadas = []

    def falso(url, fields, headers=None, timeout=10):
        llamadas.append({"url": url, "fields": fields, "headers": headers, "timeout": timeout})
        return {"sid": "SM0123456789", "status": "queued"}

    monkeypatch.setattr(outbound, "post_form", falso)
    return llamadas


def _cliente_sms(customer="70000001"):
    _perfil(customer, pref="SMS", email=False, sms=True)
    _vinculo(customer)


def test_sms_por_twilio_envia_el_formulario_con_autenticacion_basic(twilio):
    _cliente_sms()
    assert _run(_actualizado("CONFIRMADO"))["batchItemFailures"] == []
    (llamada,) = twilio
    assert llamada["url"] == f"https://api.twilio.com/2010-04-01/Accounts/{SID_TWILIO}/Messages.json"
    assert llamada["headers"] == {
        "Authorization": "Basic " + base64.b64encode(f"{SID_TWILIO}:{TOKEN_TWILIO}".encode()).decode()}
    assert llamada["fields"] == {"To": "+51999000111", "From": DESDE,
                                 "Body": notif._sms_text(notif.TEMPLATES["CONFIRMADO"])}
    item = _notify_items()["NOTIFY#CONFIRMADO#70000001"]
    assert (item["status"], item["channel"], item["message_id"]) == ("SENT", "SMS", "SM0123456789")


def test_sms_solo_lleva_telefono_remitente_y_texto(twilio):
    _cliente_sms()
    _run(_actualizado())
    campos = twilio[0]["fields"]
    assert set(campos) == {"To", "From", "Body"}
    assert "70000001" not in json.dumps(campos) and "example.com" not in json.dumps(campos)


def test_los_textos_del_sms_caben_en_160_caracteres_sin_tildes():
    for hito, texto in notif.TEMPLATES.items():
        sms = notif._sms_text(texto)
        assert all(ord(c) < 128 or c in "ñÑ" for c in sms), hito
        assert len(sms) + len("Sent from your Twilio trial account - ") <= 160, hito
    con_tildes, sin_tildes = "Está trabajando. Ñandú", "Esta trabajando. Ñandu"
    assert notif._sms_text(con_tildes) == sin_tildes


@pytest.mark.parametrize("telefono,valido", [("+51956839954", True), ("+17372508034", True), ("956839954", False),
                                             ("+0123456789", False), ("+51 956 839 954", False), ("", False),
                                             ("+519568399541234567", False)])
def test_el_telefono_debe_estar_en_formato_e164(telefono, valido):
    perfil = {"channel_pref": "SMS", "consent_sms": True, "phone": telefono}
    assert (notif._channel(perfil) == "SMS") is valido


def test_telefono_invalido_no_envia_y_cae_al_otro_canal(twilio):
    ddb.table("CustomerProfiles").put_item(Item={
        "pk": "CUSTOMER#70000001", "sk": "PROFILE", "type": "CUSTOMER", "customer_id": "70000001",
        "channel_pref": "SMS", "consent_sms": True, "phone": "956839954", "consent_email": True,
        "email": "a@example.com"})
    _vinculo("70000001")
    _run(_actualizado())
    assert twilio == [] and _notify_items()["NOTIFY#CONFIRMADO#70000001"]["channel"] == "SIMULATED"


@pytest.mark.parametrize("valor", [None, "PENDIENTE"])
def test_sin_credenciales_de_twilio_falla_y_reintenta(aws, monkeypatch, valor):
    monkeypatch.setenv("SMS_MODE", "TWILIO")
    ssm = boto3.client("ssm")
    if valor:
        for key, kind in (("account_sid", "String"), ("auth_token", "SecureString"), ("from_number", "String")):
            ssm.put_parameter(Name=f"/red-telecorp/test/twilio/{key}", Value=valor, Type=kind)
    _cliente_sms()
    assert _fallos(_run(_actualizado())) == ["m1"]
    item = _notify_items()["NOTIFY#CONFIRMADO#70000001"]
    assert (item["status"], item["error"], item["attempts"]) == ("FAILED", "TwilioNotConfigured", 1)


def test_error_de_twilio_se_reintenta_hasta_tres_veces_sin_filtrar_secretos(twilio, monkeypatch, caplog):
    def falla(*args, **kwargs):
        raise outbound.OutboundError("Fallo del servicio externo")

    monkeypatch.setattr(outbound, "post_form", falla)
    _cliente_sms()
    with caplog.at_level("INFO"):
        assert _fallos(_run(_actualizado())) == ["m1"]
        assert _fallos(_run(_actualizado())) == ["m1"]
        assert _fallos(_run(_actualizado())) == []  # tercer intento: ya no se reintenta
    item = _notify_items()["NOTIFY#CONFIRMADO#70000001"]
    assert (item["status"], item["error"], item["attempts"]) == ("FAILED", "TwilioError", 3)
    for secreto in (SID_TWILIO, TOKEN_TWILIO, "+51999000111"):
        assert secreto not in caplog.text and secreto not in json.dumps(item, default=str)
    assert "70000001" not in caplog.text  # el documento solo vive en la tabla, nunca en los logs


def test_respuesta_de_twilio_sin_sid_es_un_fallo(twilio, monkeypatch):
    monkeypatch.setattr(outbound, "post_form", lambda *a, **k: {"status": "queued"})
    _cliente_sms()
    assert _fallos(_run(_actualizado())) == ["m1"]
    assert _notify_items()["NOTIFY#CONFIRMADO#70000001"]["error"] == "TwilioInvalidResponse"


def test_un_cliente_sin_consentimiento_de_sms_no_recibe_sms(twilio):
    _perfil("70000001", pref="SMS", email=False, sms=False)
    _vinculo("70000001")
    _run(_actualizado())
    assert twilio == [] and _notify_items()["NOTIFY#CONFIRMADO#70000001"]["status"] == "SKIPPED"


def test_el_aviso_se_envia_una_sola_vez_por_cliente_e_hito(twilio):
    _cliente_sms()
    _run(_actualizado("CONFIRMADO", "m1"), _actualizado("CONFIRMADO", "m2"), _vinculado("70000001", "CONFIRMADO", "m3"))
    assert len(twilio) == 1
