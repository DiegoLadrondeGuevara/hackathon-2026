"""Crea los parámetros SSM que usan las Lambdas (SecureString para los secretos).

Uso (con las credenciales de AWS Academy ya configuradas):
    python scripts/bootstrap_ssm.py --stage dev --from-address correo-verificado@dominio.com

No pisa lo que ya existe, salvo con --force. Los valores PENDIENTE se reemplazan cuando GCP, Azure,
Grafana o Twilio estén listos:
    python scripts/bootstrap_ssm.py --stage dev --only gcp/base_url --value https://... --force
Para una clave sin dejarla en el historial, usa una variable de entorno:
    PowerShell:  $env:CLAVE = "..."; python scripts/bootstrap_ssm.py --only twilio/auth_token --value-env CLAVE --force
"""
import argparse
import os
import secrets

import boto3
from botocore.exceptions import ClientError

# nombre -> (tipo, valor por defecto; None = generar aleatorio)
PARAMS = {
    "jwt/signing_key": ("SecureString", None),
    "pii_salt": ("SecureString", None),
    "ses/from_address": ("String", "no-reply@example.com"),
    "gcp/base_url": ("String", "PENDIENTE"),
    "gcp/api_key": ("SecureString", "PENDIENTE"),
    "azure/base_url": ("String", "PENDIENTE"),
    "azure/api_key": ("SecureString", "PENDIENTE"),
    "grafana/otlp_endpoint": ("String", "PENDIENTE"),
    "grafana/instance_id": ("String", "PENDIENTE"),
    "grafana/token": ("SecureString", "PENDIENTE"),
    "twilio/account_sid": ("String", "PENDIENTE"),
    "twilio/auth_token": ("SecureString", "PENDIENTE"),
    "twilio/from_number": ("String", "PENDIENTE"),
}


def exists(ssm, name: str) -> bool:
    try:
        ssm.get_parameter(Name=name)
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ParameterNotFound":
            return False
        raise


def put(ssm, prefix: str, key: str, value: str, kind: str, force: bool) -> str:
    name = f"{prefix}/{key}"
    if exists(ssm, name) and not force:
        return "ya existe"
    ssm.put_parameter(Name=name, Value=value, Type=kind, Overwrite=True)
    return "creado"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="dev")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--from-address", help="Correo verificado en SES para enviar notificaciones")
    ap.add_argument("--only", help="Solo este parámetro (ej. gcp/base_url)")
    ap.add_argument("--value", help="Valor para --only")
    ap.add_argument("--value-env", help="Nombre de una variable de entorno con el valor (no queda en el historial)")
    ap.add_argument("--force", action="store_true", help="Sobrescribir si existe")
    args = ap.parse_args()

    ssm = boto3.client("ssm", region_name=args.region)
    prefix = f"/red-telecorp/{args.stage}"

    if args.only:
        value = args.value if args.value is not None else os.environ.get(args.value_env or "")
        if args.only not in PARAMS or value is None:
            raise SystemExit(f"--only debe ser uno de {sorted(PARAMS)} y llevar --value o --value-env definida")
        kind = PARAMS[args.only][0]
        print(f"{prefix}/{args.only}: {put(ssm, prefix, args.only, value, kind, args.force)}")
        return

    for key, (kind, default) in PARAMS.items():
        value = default if default is not None else secrets.token_urlsafe(48)
        if key == "ses/from_address" and args.from_address:
            value = args.from_address
        print(f"{prefix}/{key}: {put(ssm, prefix, key, value, kind, args.force)}")


if __name__ == "__main__":
    main()
