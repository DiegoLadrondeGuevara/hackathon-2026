# Red TeleCorp: guía para el agente

Hackatón de Cloud Computing (UTEC), equipo de 3, 72 horas. Núcleo en AWS Academy, serverless y de costo mínimo.
Otras nubes: GCP (BigQuery, Cloud Run, Gemini) y Azure (Functions, Table Storage, Static Web Apps).

## Antes de escribir código
Lee `contracts/` completo: `tables.md`, `events.md`, `flows.md`, `api.md`, `infra.md`, `external.md`. Son la fuente de verdad.
Si el contrato no alcanza o hay que cambiarlo, para y avisa. El cambio se hace primero en `contracts/` y en `aws/tests/schema.py`, en un commit aparte.

## Reglas que no se rompen
- Solo serverless y pago por uso. Nada de EC2, RDS/Aurora, OpenSearch, Kinesis, ECS ni NAT Gateway.
- Python 3.11 (runtime de Lambda; en local sirve 3.11 o superior). En AWS solo stdlib y boto3 (lo trae el runtime). Sin dependencias de terceros en las Lambdas.
- Código común en `aws/src/common/`: usarlo, no duplicarlo (`config`, `ids`, `ddb`, `events`, `http`, `domain`, `jsonutil`).
  Reglas de negocio (umbrales, transiciones, prioridad) solo en `domain.py`.
- Un handler por archivo en `aws/src/handlers/<nombre_snake>.py` con `handler(event, context)`. Nombres según `contracts/infra.md`.
- Todo evento sale por Outbox con `events.outbox_put_op` dentro de la misma transacción que el cambio de datos. Nadie llama a `PutEvents` salvo `EnrutadoraDeOutbox`.
- Handlers idempotentes (SQS entrega al menos una vez). Handlers SQS devuelven `batchItemFailures`.
- Números: `int` o `Decimal`, nunca `float`. Fechas: `ids.now_iso()`.
- Secretos solo en SSM SecureString (`config.get_secret`). Nunca en código, `.env` versionado ni logs.
- Sin datos personales en logs ni hacia GCP o Azure.
- La IA es apoyo: si falla, el flujo principal sigue. `ObtenerSugerenciaIA` nunca devuelve 5xx por la IA.
- No crear informes ni documentos narrativos. El README es técnico y corto.
- No tocar `aws/serverless.yml`, `aws/infra/` ni `scripts/bootstrap_ssm.py` (infra ya está hecha; la cambia quien lleva infraestructura). Rol IAM siempre `LabRole`.
- Los handlers ya existen como esqueleto (lanzan `NotImplementedError`): reemplazar el archivo completo, sin renombrarlo.

## Forma de trabajo
1. Una tarea de `docs/AGENT_TASKS.md` por rama `feat/<tarea>`.
2. Plan de 5 líneas, esperar aprobación, luego implementar.
3. Código completo por archivo, con pruebas en `aws/tests/` usando moto (fixture `aws` de `conftest.py`).
4. Dentro de `aws/`, `python -m pytest` y `ruff check src tests` en verde antes de dar algo por terminado (`make test` y `make lint` hacen lo mismo, pero en Windows `make` puede no existir).
5. Commits pequeños. Pedir confirmación antes de comandos destructivos o de cambiar claves de tablas.

## Reglas de negocio (resumen; el detalle está en `contracts/flows.md` y `domain.py`)
- Antena: 0 GB/min inhabilitada; < 60 caída; > 129 saturada; 60 a 129 normal.
- Episodio: la primera anomalía lo abre; cinco lecturas normales seguidas lo cierran; 3 episodios en 7 días = recurrencia.
- Colectivo: 10 clientes distintos, misma zona y servicio, en menos de 24 h. No exige antena.
- Reporte: REGISTRADA, EN_REVISION, EN_ATENCION, SOLUCIONADA, CERRADA. Incidente: EVALUACION, CONFIRMADO, RESTABLECIDO, CERRADO.
- La recuperación técnica es evidencia: no cierra reportes ni incidentes por sí sola.
