"""Suscribe un correo al tema SNS de avisos a clientes (`EMAIL_MODE=SNS`) y lista las suscripciones.

Uso (con las credenciales de AWS Academy ya configuradas):
    python scripts/suscribir_correo.py suscribir --correo demo@dominio.com --cliente 70000001
    python scripts/suscribir_correo.py suscribir --correo demo@dominio.com --cliente 70000001 --cliente 70000002
    python scripts/suscribir_correo.py suscribir --correo demo@dominio.com --todos
    python scripts/suscribir_correo.py listar

Opciones comunes: --stage (por defecto dev) y --region (por defecto us-east-1).
SNS envía un correo de confirmación: hay que abrir su enlace para empezar a recibir avisos; lo publicado antes
de confirmar no se recupera. Con --cliente solo llegan los avisos de esos clientes (el tema los distingue por un
seudónimo con sal, nunca por su documento); con --todos llegan los de todos. Volver a suscribir un correo ya
confirmado reemplaza su filtro. Para darse de baja se usa el enlace que trae cada correo.
"""
import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aws" / "src"))

from common import pii  # noqa: E402

PENDING = "PendingConfirmation"


def topic_arn(sns, stage: str) -> str:
    suffix = f":red-telecorp-{stage}-notificaciones-clientes"
    for page in sns.get_paginator("list_topics").paginate():
        for topic in page["Topics"]:
            if topic["TopicArn"].endswith(suffix):
                return topic["TopicArn"]
    raise SystemExit(f"No existe el tema de notificaciones del stage {stage}: despliega primero")


def salt(ssm, stage: str) -> str:
    try:
        return ssm.get_parameter(Name=f"/red-telecorp/{stage}/pii_salt", WithDecryption=True)["Parameter"]["Value"]
    except ClientError:
        raise SystemExit("No se pudo leer pii_salt de SSM (¿credenciales vencidas o stage incorrecto?)") from None


def subscriptions(sns, arn: str) -> list:
    return [s for page in sns.get_paginator("list_subscriptions_by_topic").paginate(TopicArn=arn)
            for s in page["Subscriptions"]]


def subscribe(sns, ssm, args) -> None:
    if not args.todos and not args.cliente:
        raise SystemExit("Indica --cliente <documento> (una o más veces) o --todos")
    arn = topic_arn(sns, args.stage)
    attrs = {}
    if not args.todos:
        hashes = sorted({pii.customer_hash(salt(ssm, args.stage), c.strip()) for c in args.cliente})
        attrs = {"FilterPolicy": json.dumps({"customer_hash": hashes}), "FilterPolicyScope": "MessageAttributes"}
    existing = next((s for s in subscriptions(sns, arn)
                     if s["Endpoint"] == args.correo and s["Protocol"] == "email"), None)
    if existing and existing["SubscriptionArn"] != PENDING:
        sns.set_subscription_attributes(SubscriptionArn=existing["SubscriptionArn"], AttributeName="FilterPolicy",
                                        AttributeValue=attrs.get("FilterPolicy", ""))
        if "FilterPolicyScope" in attrs:
            sns.set_subscription_attributes(SubscriptionArn=existing["SubscriptionArn"],
                                            AttributeName="FilterPolicyScope", AttributeValue="MessageAttributes")
        print(f"{args.correo}: filtro actualizado")
        return
    if existing:
        raise SystemExit(f"{args.correo} ya tiene una suscripción pendiente: abre el correo de confirmación de AWS")
    sns.subscribe(TopicArn=arn, Protocol="email", Endpoint=args.correo, Attributes=attrs)
    who = "todos los clientes" if args.todos else f"{len(args.cliente)} cliente(s)"
    print(f"{args.correo}: suscripción creada para {who}. Abre el correo de confirmación de AWS para activarla.")


def list_subscriptions(sns, args) -> None:
    arn = topic_arn(sns, args.stage)
    rows = subscriptions(sns, arn)
    if not rows:
        print("Sin suscripciones.")
    for s in rows:
        estado = "pendiente de confirmar" if s["SubscriptionArn"] == PENDING else "confirmada"
        print(f"{s['Protocol']:6} {s['Endpoint']:40} {estado}")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Suscripciones de correo al tema de avisos a clientes")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--stage", default="dev")
    common.add_argument("--region", default="us-east-1")
    sub = parser.add_subparsers(dest="accion", required=True)
    s = sub.add_parser("suscribir", parents=[common])
    s.add_argument("--correo", required=True)
    s.add_argument("--cliente", action="append", default=[])
    s.add_argument("--todos", action="store_true")
    sub.add_parser("listar", parents=[common])
    args = parser.parse_args(argv)
    sns = boto3.client("sns", region_name=args.region)
    if args.accion == "suscribir":
        subscribe(sns, boto3.client("ssm", region_name=args.region), args)
    else:
        list_subscriptions(sns, args)


if __name__ == "__main__":
    main()
