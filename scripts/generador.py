"""Pausa o reanuda el simulador de antenas sin volver a desplegar (regla de EventBridge de cada minuto).

Uso (con las credenciales de AWS Academy ya configuradas):
    python scripts/generador.py estado
    python scripts/generador.py pausar      # antes de una prueba de carga o de grabar la demo
    python scripts/generador.py reanudar

Opciones comunes: --stage (por defecto dev) y --region (por defecto us-east-1).
Pausar baja el consumo de Lambda (y de créditos) mientras no se usa el simulador. El valor `generator` de
`aws/infra/flags.yml` sigue mandando: el próximo despliegue vuelve a dejar la regla como diga ese archivo.
Con el simulador pausado no hay lecturas nuevas: los episodios abiertos no se cierran hasta reanudar.
"""
import argparse

import boto3

PREFIX = "GeneradoraDeMetricasYLotes"


def find_rule(events, stage: str) -> dict:
    prefix = f"red-telecorp-{stage}-{PREFIX}"
    rules = [r for page in events.get_paginator("list_rules").paginate(NamePrefix=prefix) for r in page["Rules"]]
    if not rules:
        raise SystemExit(f"No se encontró la regla del simulador del stage {stage}: ¿está desplegado?")
    return rules[0]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description="Pausa o reanuda el simulador de antenas")
    parser.add_argument("accion", choices=["estado", "pausar", "reanudar"])
    parser.add_argument("--stage", default="dev")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)
    events = boto3.client("events", region_name=args.region)
    rule = find_rule(events, args.stage)
    if args.accion == "pausar":
        events.disable_rule(Name=rule["Name"])
    elif args.accion == "reanudar":
        events.enable_rule(Name=rule["Name"])
    state = events.describe_rule(Name=rule["Name"])["State"]
    estado = "ACTIVO" if state == "ENABLED" else "PAUSADO"
    print(f"Simulador de antenas: {estado} ({rule.get('ScheduleExpression', '')})")


if __name__ == "__main__":
    main()
