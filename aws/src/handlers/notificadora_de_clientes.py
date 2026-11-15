"""NotificadoraDeClientes: consume ColaNotificaciones (T12).

`incident.updated` con hito: avisa a todos los clientes vinculados al incidente (`LINK#USER#*`).
`report.linked`: avisa al cliente del evento si el incidente está en un hito.
Cada (incidente, hito, cliente) tiene una sola intención `NOTIFY#<hito>#<cliente>`, creada con
`attribute_not_exists(pk)`; así un reintento o un evento repetido no manda dos mensajes.
Los fallos de envío se reintentan hasta 3 veces (`batchItemFailures`). Sin datos personales en los logs.
"""
import json
import logging
import os

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from common import config, ddb, domain, ids

log = logging.getLogger()
log.setLevel(logging.INFO)

MAX_ATTEMPTS = 3
SUBJECT = "Red TeleCorp: novedades de tu reporte"
TEMPLATES = {
    "EVALUACION": "Estamos evaluando el inconveniente que reportaste en tu zona. "
                  "Te avisaremos cuando haya novedades.",
    "CONFIRMADO": "Identificamos una incidencia en tu zona. Nuestro equipo está trabajando para resolverla.",
    "RESTABLECIDO": "El servicio fue restablecido en tu zona. Si el problema continúa, vuelve a reportarlo.",
}
_CHANNELS = ("EMAIL", "SMS")
_CONDITION_FAILED = "ConditionalCheckFailedException"


class InvalidMessage(Exception):
    """Dato inválido: se registra y se descarta, no se reintenta."""


class SendError(Exception):
    """Falló el envío por el canal; `code` es un texto corto sin datos personales."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _text(value, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise InvalidMessage(f"{name} vacío o no textual")
    return value


def _parse(record: dict) -> tuple[str, str, list | None]:
    """Devuelve (incident_id, milestone, clientes). `clientes` None = todos los vinculados al incidente.
    Devuelve milestone vacío cuando el evento no corresponde a un hito (se ignora)."""
    try:
        body = json.loads(record["body"])
        detail = body["detail"]
        if isinstance(detail, str):
            detail = json.loads(detail)
        kind, data = detail["type"], detail["data"]
        incident_id = _text(data["incident_id"], "incident_id")
        if kind == "incident.updated":
            milestone, customers = data.get("milestone"), None
        elif kind == "report.linked":
            milestone, customers = data.get("incident_status"), [_text(data["customer_id"], "customer_id")]
        else:
            raise InvalidMessage(f"tipo inesperado: {kind}")
    except InvalidMessage:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise InvalidMessage("mensaje mal formado") from exc
    return incident_id, milestone if milestone in domain.MILESTONES else "", customers


def _recipients(incident_id: str) -> list:
    links = ddb.query_all(
        "Incidents",
        KeyConditionExpression=Key("pk").eq(f"INCIDENT#{incident_id}") & Key("sk").begins_with("LINK#USER#"),
        ConsistentRead=True,
    )
    return [link["customer_id"] for link in links]


# --- Intención NOTIFY ---

def _intent(incident_id: str, milestone: str, customer_id: str) -> dict | None:
    """Crea la intención PENDING o devuelve la existente. None si ya no hay nada que hacer."""
    key = {"pk": f"INCIDENT#{incident_id}", "sk": f"NOTIFY#{milestone}#{customer_id}"}
    table = ddb.table("Incidents")
    item = {**key, "type": "NOTIFY", "milestone": milestone, "customer_id": customer_id,
            "status": "PENDING", "attempts": 0, "created_at": ids.now_iso()}
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        return item
    except ClientError as exc:
        if exc.response["Error"]["Code"] != _CONDITION_FAILED:
            raise
    existing = table.get_item(Key=key, ConsistentRead=True).get("Item")
    if not existing or existing["status"] in ("SENT", "SKIPPED") or int(existing["attempts"]) >= MAX_ATTEMPTS:
        return None
    return existing


def _record_result(intent: dict, status: str, channel: str, attempts: int, error: str | None = None,
                   message_id: str | None = None) -> None:
    """Guarda el resultado. Si otro proceso ya avanzó los intentos, no pisa su resultado."""
    now = ids.now_iso()
    sets = ["#status = :status", "channel = :channel", "attempts = :attempts", "last_attempt_at = :now"]
    values = {":status": status, ":channel": channel, ":attempts": attempts, ":now": now,
              ":prev": int(intent["attempts"]), ":sent": "SENT", ":skipped": "SKIPPED"}
    if status == "SENT":
        sets.append("sent_at = :now")
    if message_id:
        sets.append("message_id = :mid")
        values[":mid"] = message_id
    if error:
        sets.append("#error = :error")
        values[":error"] = error
    try:
        ddb.table("Incidents").update_item(
            Key={"pk": intent["pk"], "sk": intent["sk"]},
            UpdateExpression="SET " + ", ".join(sets),
            ConditionExpression="attempts = :prev AND NOT (#status IN (:sent, :skipped))",
            ExpressionAttributeNames={"#status": "status", **({"#error": "error"} if error else {})},
            ExpressionAttributeValues=values,
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] != _CONDITION_FAILED:
            raise
        log.info("la notificación %s ya fue resuelta por otro proceso", intent["milestone"])


# --- Canal y envío ---

def _channel(profile: dict) -> str | None:
    """`channel_pref` si hay consentimiento (y dato de contacto); si no, el otro canal; si ninguno, None."""
    pref = profile.get("channel_pref")
    order = [pref] if pref in _CHANNELS else []
    order += [c for c in _CHANNELS if c not in order]
    consent = {"EMAIL": profile.get("consent_email") is True and bool(profile.get("email")),
               "SMS": profile.get("consent_sms") is True and bool(profile.get("phone"))}
    return next((c for c in order if consent[c]), None)


def _send_email(profile: dict, text: str) -> str:
    ses = boto3.client("ses")
    try:
        resp = ses.send_email(
            Source=config.get_secret("ses/from_address"),
            Destination={"ToAddresses": [profile["email"]]},
            Message={"Subject": {"Data": SUBJECT, "Charset": "UTF-8"},
                     "Body": {"Text": {"Data": text, "Charset": "UTF-8"}}},
        )
    except ClientError as exc:
        raise SendError(exc.response["Error"]["Code"]) from None
    return resp["MessageId"]


def _send_sms(profile: dict, text: str) -> str:
    sns = boto3.client("sns")
    try:
        resp = sns.publish(
            PhoneNumber=profile["phone"], Message=text,
            MessageAttributes={"AWS.SNS.SMS.SMSType": {"DataType": "String", "StringValue": "Transactional"}},
        )
    except ClientError as exc:
        raise SendError(exc.response["Error"]["Code"]) from None
    return resp["MessageId"]


def _deliver(channel: str, profile: dict, text: str, modes: dict) -> tuple[str, str | None]:
    """Devuelve (canal registrado, message_id). Con SIMULATED solo se registra."""
    if modes[channel] in ("SES", "SNS"):
        send = _send_email if channel == "EMAIL" else _send_sms
        return channel, send(profile, text)
    return "SIMULATED", None


def _modes() -> dict:
    return {"EMAIL": os.environ.get("EMAIL_MODE", "SIMULATED").upper(),
            "SMS": os.environ.get("SMS_MODE", "SIMULATED").upper()}


def _notify(incident_id: str, milestone: str, customer_id: str, modes: dict) -> bool:
    """Procesa un destinatario. True si hay que reintentar (fallo de envío con intentos disponibles)."""
    intent = _intent(incident_id, milestone, customer_id)
    if intent is None:
        return False
    attempts = int(intent["attempts"]) + 1
    profile = ddb.table("CustomerProfiles").get_item(
        Key={"pk": f"CUSTOMER#{customer_id}", "sk": "PROFILE"}
    ).get("Item")
    channel = _channel(profile) if profile else None
    if channel is None:
        _record_result(intent, "SKIPPED", "NONE", attempts, error=None if profile else "PROFILE_NOT_FOUND")
        log.info("notificación omitida: incidente=%s hito=%s sin canal con consentimiento", incident_id, milestone)
        return False
    try:
        used, message_id = _deliver(channel, profile, TEMPLATES[milestone], modes)
    except SendError as exc:
        _record_result(intent, "FAILED", channel, attempts, error=exc.code)
        retry = attempts < MAX_ATTEMPTS
        log.warning("fallo de envío: incidente=%s hito=%s canal=%s intento=%d error=%s",
                    incident_id, milestone, channel, attempts, exc.code)
        return retry
    _record_result(intent, "SENT", used, attempts, message_id=message_id)
    log.info("notificación enviada: incidente=%s hito=%s canal=%s", incident_id, milestone, used)
    return False


def _process(record: dict, modes: dict) -> bool:
    incident_id, milestone, customers = _parse(record)
    if not milestone:
        return False
    if customers is None:
        customers = _recipients(incident_id)
    retry = False
    for customer_id in sorted(set(customers)):
        retry = _notify(incident_id, milestone, customer_id, modes) or retry
    return retry


def handler(event, context):
    modes = _modes()
    failures = []
    for record in event.get("Records", []):
        message_id = record.get("messageId")
        try:
            if _process(record, modes):
                failures.append({"itemIdentifier": message_id})
        except InvalidMessage as exc:
            log.warning("mensaje %s descartado: %s", message_id, exc)
        except Exception:  # noqa: BLE001 - el registro vuelve a la cola
            log.exception("fallo al procesar el mensaje %s", message_id)
            failures.append({"itemIdentifier": message_id})
    return {"batchItemFailures": failures}
