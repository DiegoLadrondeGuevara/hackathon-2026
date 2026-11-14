# Red TeleCorp

Gestión de incidencias y monitoreo de antenas. AWS (núcleo serverless), GCP (analítica e IA), Azure (estado público).

- `contracts/`: modelo de datos, eventos, flujos, API, requisitos de infraestructura y contrato con otras nubes.
- `aws/src/`: Lambdas en Python (`handlers/`) y módulos compartidos (`common/`).
- `aws/serverless.yml` y `aws/infra/`: infraestructura (Serverless Framework v3).
- `gcp/`, `azure/`: funciones de cada nube.
- `scripts/`: carga de datos, escenarios y prueba de carga.

Pruebas: `cd aws && python -m pip install -r requirements-dev.txt && python -m pytest`. Despliegue: `cd aws && npm install && npm run deploy`.
