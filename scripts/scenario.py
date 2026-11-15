"""Activa o limpia el escenario de antenas de la demo (`SCENARIO#ACTIVE` en NetworkCatalog).

Uso (con las credenciales de AWS Academy ya configuradas):
    python scripts/scenario.py activar --antena A013=0                    # apaga A013 por 15 minutos
    python scripts/scenario.py activar --antena A013=40 --antena A014=150 --minutos 30
    python scripts/scenario.py activar --zona Z05 --gb 0                  # todas las antenas de la zona
    python scripts/scenario.py ver
    python scripts/scenario.py limpiar

Opciones comunes: --stage (por defecto dev) y --region (por defecto us-east-1).
GB/min: 0 inhabilitada, menos de 60 caída, más de 129 saturada, 60 a 129 normal.
`activar` reemplaza el escenario anterior. GeneradoraDeMetricasYLotes lo aplica en su siguiente minuto
y lo ignora cuando pasa `expires_at`. Al limpiar o expirar, cada antena necesita 5 lecturas normales
seguidas (5 minutos) para que su episodio se cierre.
"""
import argparse
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

import boto3
from boto3.dynamodb.conditions import Key

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "aws" / "src"))

from common import domain, ids  # noqa: E402

KEY = {"pk": "SCENARIO#ACTIVE", "sk": "META"}
MAX_MINUTES = 24 * 60


def parse_gb(text: str) -> Decimal:
    try:
        value = Decimal(text)
    except InvalidOperation:
        raise SystemExit(f"GB/min no válido: {text}") from None
    if not value.is_finite() or value < 0:
        raise SystemExit(f"GB/min no válido: {text}")
    return value


def parse_overrides(pairs: list) -> dict:
    overrides = {}
    for pair in pairs:
        antenna_id, sep, gb = pair.partition("=")
        if not sep or not antenna_id.strip():
            raise SystemExit(f"Formato esperado ANTENA=GB (ej. A013=0): {pair}")
        overrides[antenna_id.strip().upper()] = parse_gb(gb.strip())
    return overrides


def zone_antennas(catalog, zone_id: str) -> list:
    resp = catalog.query(
        IndexName="GSI2-zone",
        KeyConditionExpression=Key("gsi2pk").eq(f"ZONE#{zone_id}") & Key("gsi2sk").begins_with("ANTENNA#"),
    )
    return [item["antenna_id"] for item in resp.get("Items", [])]


def activate(catalog, args) -> None:
    overrides = {}
    if args.zona:
        if args.gb is None:
            raise SystemExit("--zona necesita --gb")
        antennas = zone_antennas(catalog, args.zona.upper())
        if not antennas:
            raise SystemExit(f"La zona {args.zona} no tiene antenas en el catálogo")
        overrides.update({antenna_id: parse_gb(args.gb) for antenna_id in antennas})
    overrides.update(parse_overrides(args.antena))
    if not overrides:
        raise SystemExit("Indica al menos una --antena ANTENA=GB o una --zona con --gb")
    if not 1 <= args.minutos <= MAX_MINUTES:
        raise SystemExit(f"--minutos debe estar entre 1 y {MAX_MINUTES}")
    for antenna_id in overrides:
        if "Item" not in catalog.get_item(Key={"pk": f"ANTENNA#{antenna_id}", "sk": "META"}):
            raise SystemExit(f"La antena {antenna_id} no existe en el catálogo")

    expires_at = ids.shift_iso(ids.now_iso(), minutes=args.minutos)
    catalog.put_item(Item={**KEY, "type": "SCENARIO", "overrides": overrides, "expires_at": expires_at})
    print(f"{catalog.name}: escenario activo hasta {expires_at}")
    show_overrides(overrides)


def show_overrides(overrides: dict) -> None:
    for antenna_id in sorted(overrides):
        print(f"  {antenna_id}: {overrides[antenna_id]} GB/min ({domain.classify_gb(overrides[antenna_id])})")


def show(catalog) -> None:
    item = catalog.get_item(Key=KEY).get("Item")
    if not item:
        print(f"{catalog.name}: sin escenario")
        return
    state = "activo" if item["expires_at"] > ids.now_iso() else "expirado"
    print(f"{catalog.name}: escenario {state}, expira {item['expires_at']}")
    show_overrides(item.get("overrides") or {})


def clear(catalog) -> None:
    catalog.delete_item(Key=KEY)
    print(f"{catalog.name}: escenario eliminado")


def main(argv=None) -> None:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--stage", default="dev")
    common.add_argument("--region", default="us-east-1")
    ap = argparse.ArgumentParser(description="Escenario de antenas para la demo")
    sub = ap.add_subparsers(dest="command", required=True)
    act = sub.add_parser("activar", parents=[common], help="Fuerza el GB/min de una o más antenas")
    act.add_argument("--antena", action="append", default=[], metavar="ANTENA=GB")
    act.add_argument("--zona", help="Aplica --gb a todas las antenas de la zona")
    act.add_argument("--gb", help="GB/min para las antenas de --zona")
    act.add_argument("--minutos", type=int, default=15, help="Duración del escenario (por defecto 15)")
    sub.add_parser("ver", parents=[common], help="Muestra el escenario guardado")
    sub.add_parser("limpiar", parents=[common], help="Elimina el escenario")
    args = ap.parse_args(argv)

    dynamodb = boto3.resource("dynamodb", region_name=args.region)
    catalog = dynamodb.Table(f"red-telecorp-{args.stage}-NetworkCatalog")
    if args.command == "activar":
        activate(catalog, args)
    elif args.command == "ver":
        show(catalog)
    else:
        clear(catalog)


if __name__ == "__main__":
    main()
