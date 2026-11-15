"""Carga los datos de demo: 12 zonas, 30 antenas, 1 operador y 20 clientes ficticios.

Uso (con las credenciales de AWS Academy ya configuradas):
    PowerShell:  $env:SEED_DEMO_PASSWORD = "<clave de demo>"
    bash:        export SEED_DEMO_PASSWORD='<clave de demo>'
    python scripts/seed.py --stage dev

Escribe en `red-telecorp-<stage>-NetworkCatalog` y `red-telecorp-<stage>-CustomerProfiles`.
Es idempotente: el catálogo se reescribe igual y los perfiles que ya existen no se tocan
(ni el hash ni `created_at`). Con --force los perfiles se reescriben, por ejemplo para cambiar la clave.
La contraseña sale solo de la variable de entorno SEED_DEMO_PASSWORD y nunca se imprime.
Con --telefono-demo +51999888777 el cliente 70000003 (o --cliente-demo) queda con ese teléfono, preferencia SMS
y consentimiento de SMS, para probar el SMS real; los demás clientes siguen sin consentimiento de SMS.
"""
import argparse
import os
import re
import sys
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aws" / "src"))

from common import auth, domain, ids  # noqa: E402

PASSWORD_ENV = "SEED_DEMO_PASSWORD"
NOMINAL_GB = 95
OPERATOR_ID = "OP001"

# (zone_id, nombre, tipo, usuarios estimados, antenas)
ZONES = [
    ("Z01", "Miraflores", "RESIDENCIAL", 45000, 3),
    ("Z02", "San Isidro", "CRITICA", 30000, 3),
    ("Z03", "Santiago de Surco", "RESIDENCIAL", 60000, 3),
    ("Z04", "San Borja", "RESIDENCIAL", 28000, 3),
    ("Z05", "La Molina", "EDUCATIVA", 32000, 3),
    ("Z06", "Callao", "INDUSTRIAL", 50000, 3),
    ("Z07", "Ate", "INDUSTRIAL", 40000, 2),
    ("Z08", "San Miguel", "EDUCATIVA", 26000, 2),
    ("Z09", "Jesús María", "MEDICA", 18000, 2),
    ("Z10", "San Juan de Lurigancho", "RESIDENCIAL", 55000, 2),
    ("Z11", "Villa El Salvador", "INDUSTRIAL", 35000, 2),
    ("Z12", "Barranco", "EDUCATIVA", 8000, 2),
]

# Nombres inventados. Documento, correo y teléfono se derivan del orden.
CUSTOMER_NAMES = [
    "Ana Torres Demo", "Luis Paredes Demo", "María Quispe Demo", "Jorge Salazar Demo",
    "Rosa Huamán Demo", "Carlos Mendoza Demo", "Lucía Vargas Demo", "Pedro Castillo Demo",
    "Elena Rojas Demo", "Miguel Flores Demo", "Carmen Díaz Demo", "José Ramos Demo",
    "Patricia Chávez Demo", "Raúl Espinoza Demo", "Sofía Guerrero Demo", "Diego Navarro Demo",
    "Valeria Campos Demo", "Andrés Cárdenas Demo", "Gabriela León Demo", "Fernando Vega Demo",
]
# Clientes sin ningún consentimiento (caso SKIPPED de las notificaciones).
NO_CONSENT = {19, 20}


def zone_items() -> list:
    return [
        {
            "pk": f"ZONE#{zone_id}",
            "sk": "META",
            "type": "ZONE",
            "zone_id": zone_id,
            "name": name,
            "zone_type": zone_type,
            "criticality": domain.ZONE_CRITICALITY[zone_type],
            "est_users": est_users,
            "gsi1pk": "TYPE#ZONE",
            "gsi1sk": zone_id,
        }
        for zone_id, name, zone_type, est_users, _ in ZONES
    ]


def antenna_items() -> list:
    items = []
    for zone_id, zone_name, _, _, count in ZONES:
        for _ in range(count):
            antenna_id = f"A{len(items) + 1:03d}"
            items.append(
                {
                    "pk": f"ANTENNA#{antenna_id}",
                    "sk": "META",
                    "type": "ANTENNA",
                    "antenna_id": antenna_id,
                    "zone_id": zone_id,
                    "name": f"Antena {antenna_id} {zone_name}",
                    "nominal_gb": NOMINAL_GB,
                    "gsi1pk": "TYPE#ANTENNA",
                    "gsi1sk": antenna_id,
                    "gsi2pk": f"ZONE#{zone_id}",
                    "gsi2sk": f"ANTENNA#{antenna_id}",
                }
            )
    return items


def operator_item(password: str) -> dict:
    return {
        "pk": f"OPERATOR#{OPERATOR_ID}",
        "sk": "PROFILE",
        "type": "OPERATOR",
        "operator_id": OPERATOR_ID,
        "role": "OPERATOR",
        "full_name": "Operador Demo",
        "email": "operador@example.com",
        "password_hash": auth.hash_password(password),
    }


def customer_item(number: int, password: str, now: str) -> dict:
    customer_id = f"{70000000 + number}"
    return {
        "pk": f"CUSTOMER#{customer_id}",
        "sk": "PROFILE",
        "type": "CUSTOMER",
        "customer_id": customer_id,
        "role": "CUSTOMER",
        "full_name": CUSTOMER_NAMES[number - 1],
        "email": f"cliente{number:02d}@example.com",
        "phone": f"+519000000{number:02d}",
        "password_hash": auth.hash_password(password),
        "channel_pref": "EMAIL",
        "consent_email": number not in NO_CONSENT,
        # Teléfonos inventados: sin consentimiento de SMS para no escribirle a un número real.
        "consent_sms": False,
        "consent_at": now,
        "created_at": now,
    }


def put_profile(table, item: dict, force: bool) -> bool:
    """True si escribió; False si el perfil ya existía y no se pidió --force."""
    if force:
        table.put_item(Item=item)
        return True
    try:
        table.put_item(Item=item, ConditionExpression="attribute_not_exists(pk)")
        return True
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise


def enable_demo_sms(table, customer_id: str, phone: str) -> None:
    """Deja a un cliente de demo con un teléfono real, preferencia SMS y consentimiento de SMS."""
    if not re.fullmatch(r"\+[1-9]\d{7,14}", phone):
        raise SystemExit("--telefono-demo debe estar en formato internacional, por ejemplo +51999888777")
    try:
        table.update_item(
            Key={"pk": f"CUSTOMER#{customer_id}", "sk": "PROFILE"},
            UpdateExpression="SET phone = :p, channel_pref = :c, consent_sms = :t, consent_at = :now",
            ConditionExpression="attribute_exists(pk)",
            ExpressionAttributeValues={":p": phone, ":c": "SMS", ":t": True, ":now": ids.now_iso()},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise SystemExit(f"El cliente {customer_id} no existe") from None
        raise


def main(argv=None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="dev")
    ap.add_argument("--region", default="us-east-1")
    ap.add_argument("--force", action="store_true", help="Reescribir los perfiles que ya existen")
    ap.add_argument("--telefono-demo", help="Teléfono real (+51...) del cliente de demo de SMS; no se guarda")
    ap.add_argument("--cliente-demo", default="70000003", help="Cliente de demo de SMS (por defecto 70000003)")
    args = ap.parse_args(argv)

    password = os.environ.get(PASSWORD_ENV, "")
    if not password:
        raise SystemExit(f"Falta la variable de entorno {PASSWORD_ENV} con la contraseña de demo")

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    catalog = dynamodb.Table(f"red-telecorp-{args.stage}-NetworkCatalog")
    profiles = dynamodb.Table(f"red-telecorp-{args.stage}-CustomerProfiles")

    zones, antennas = zone_items(), antenna_items()
    with catalog.batch_writer() as batch:
        for item in zones + antennas:
            batch.put_item(Item=item)
    print(f"{catalog.name}: {len(zones)} zonas y {len(antennas)} antenas")

    now = ids.now_iso()
    items = [operator_item(password)]
    items += [customer_item(n, password, now) for n in range(1, len(CUSTOMER_NAMES) + 1)]
    written = sum(put_profile(profiles, item, args.force) for item in items)
    print(f"{profiles.name}: {written} perfiles escritos, {len(items) - written} ya existían")
    if args.telefono_demo:
        enable_demo_sms(profiles, args.cliente_demo, args.telefono_demo)
        print(f"Cliente {args.cliente_demo}: preferencia SMS con consentimiento (teléfono de demo configurado)")


if __name__ == "__main__":
    main()
