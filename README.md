# Red TeleCorp

Gestión de incidencias y monitoreo de antenas. AWS (núcleo serverless), GCP (analítica e IA), Azure (estado público).

- `contracts/`: modelo de datos, eventos, flujos, API, requisitos de infraestructura y contrato con otras nubes.
- `aws/src/`: Lambdas en Python (`handlers/`) y módulos compartidos (`common/`).
- `aws/serverless.yml` y `aws/infra/`: infraestructura (Serverless Framework v3).
- `gcp/`, `azure/`: funciones de cada nube.
- `scripts/`: carga de datos, escenarios y prueba de carga.

Pruebas: `cd aws && python -m pip install -r requirements-dev.txt && python -m pytest`. Despliegue: `cd aws && npm install && npm run deploy`.

## Estado de integración · 15 de noviembre de 2026

- El equipo informó que el stack AWS `red-telecorp-dev` se desplegó en `us-east-1`; su HTTP API tiene base `https://ynyvt8x51k.execute-api.us-east-1.amazonaws.com`. La existencia de rutas no demuestra todavía que todos los handlers funcionen: `NotificadoraDeClientes` y `ObtenerTendencias` ya tienen código y pruebas en `main`, mientras `PublicadoraHaciaAzure` sigue como esqueleto en el código revisado.
- Azure Functions, Table Storage y la página pública ya están desplegadas; un `PUT` autenticado y el `GET` de Z01 respondieron correctamente. Falta la prueba real de publicación desde AWS.
- El portal de clientes y operadores en Amplify aún no existe; su [propuesta de diseño y alcance](propuesta-frontend-amplify.md) está lista para revisión. La API base AWS ya está disponible; faltan cuentas ficticias probadas, CORS desde Amplify y pruebas por rol.
- Grafana facilitó endpoint OTLP, Instance ID y token. El ZIP del exportador Azure se envió a la Function existente; el detector indicó actualización de código completada y el API respondió HTTP 200. Esperamos confirmación del responsable de Grafana sobre recepción de métricas. GCP tiene código de exportación configurable sin evidencia de recepción en el panel. Ningún token está en el repositorio.

**Trabajo actual:** esperar la comprobación Azure → Grafana por su responsable y avanzar el portal Amplify. El frontend aún no tiene código.

El estado detallado y los criterios de terminado están en [PENDIENTES.md](PENDIENTES.md); las condiciones de entrega están en [rubrica-hackathon.md](rubrica-hackathon.md).
