# Red TeleCorp — Hackathon Cloud 2026

Proyecto del grupo 12, Escuadrón S3. Buscamos detectar y gestionar incidentes de telecomunicaciones relacionando reportes de usuarios con lecturas de antenas. La solución propuesta es **serverless y multinube**: AWS Academy lleva la operación principal, Google Cloud aporta analítica/IA y Azure publica un estado mínimo por zona.

## Estado actual

**Arquitectura v3 propuesta sobre la plantilla declarativa AWS v2. Aplicación todavía no desplegada.** Las decisiones del prototipo no equivalen a puntos otorgados por el jurado. [PENDIENTES.md](PENDIENTES.md) es el tablero de trabajo; una casilla se completa solo con implementación y evidencia.

## Archivos de referencia (raíz)

| Archivo | Uso |
| --- | --- |
| [hackathonCloudEnunciado.txt](hackathonCloudEnunciado.txt) | Texto original del reto y rúbrica. |
| [puntos-dolor-cliente.md](puntos-dolor-cliente.md) | Contexto, 13 dolores y definiciones S01–S12. |
| [rubrica-hackathon.md](rubrica-hackathon.md) | Criterios, condiciones de entrega y evidencia pendiente. |
| [arquitectura-solucion-v2.md](arquitectura-solucion-v2.md) | Nombres v2 de AWS, diagrama actualizado, JWT propio y flujo de IA. |
| [arquitectura-solucion-v3.html](arquitectura-solucion-v3.html) | Vista interactiva y legible de la propuesta v3; funciona sin conexión. |
| [arquitectura-solucion-v3.md](arquitectura-solucion-v3.md) | Análisis crítico de las observaciones, correlación de señales y rol de cada plataforma. |
| [arquitectura-solucion-v3.mmd](arquitectura-solucion-v3.mmd) / [SVG](arquitectura-solucion-v3.svg) | Diagrama multinube editable y exportado de la propuesta v3. |
| [flujo-correlacion-v3.mmd](flujo-correlacion-v3.mmd) / [SVG](flujo-correlacion-v3.svg) | Detalle de cómo una anomalía y los reportes llegan al mismo incidente. |
| [arquitectura-v2-panorama.svg](arquitectura-v2-panorama.svg) / [PNG](arquitectura-v2-panorama.png) | Vista v2 legible de AWS, GCP y Azure. |
| [arquitectura-solucion-v2.svg](arquitectura-solucion-v2.svg) / [PNG](arquitectura-solucion-v2.png) | Vista técnica v2 con nombres de Lambdas y recursos. |
| [decision-ia.md](decision-ia.md) | Comparación de opciones gratuitas y recomendación de IA. |
| [PENDIENTES.md](PENDIENTES.md) | Trabajo por proveedor e integración. |

Los `.mmd` de la raíz son los diagramas editables en Mermaid. Los PNG/SVG son vistas exportadas. Un ZIP anterior del diagrama quedó en `/chatgpt/` porque ya no contenía la versión vigente.

## Organización del desarrollo

- [`aws/infra/serverless.yml`](aws/infra/serverless.yml): definiciones de AWS Academy con Serverless Framework v3. Las Lambdas usarán el `LabRole` existente; no se crearán roles IAM. Los handlers todavía no existen.
- [`gcp/infra/`](gcp/infra/README.md): Cloud Run, BigQuery y secretos de integración.
- [`azure/infra/`](azure/infra/README.md): Functions y Table Storage.
- `/chatgpt/`: borradores y archivos temporales locales, **ignorados por Git**. Los documentos importantes quedan en la raíz.

## Reglas que no debemos perder

- `0 GB/min`: antena inhabilitada; `0 < x < 60`: caída; `60 <= x <= 129`: normal en la simulación; `x > 129`: saturada.
- Diez **usuarios diferentes** de la misma zona/servicio en menos de 24 horas crean un incidente colectivo *sospechado* y activan verificación.
- Se necesitan al menos dos nubes; elegimos **tres**. Vercel no cuenta según el enunciado.
- Step Functions, IA funcional, operación serverless, persistencia y disponibilidad forman parte de la rúbrica. El video debe durar **como máximo cinco minutos**. Canvas requiere video, repo de GitHub y arquitectura; el enunciado prohíbe adjuntar un informe.

## Próxima acción técnica

Revisar la [arquitectura v3](arquitectura-solucion-v3.html) con el equipo y, si se adopta, alinear el `serverless.yml` con `ColaAnomalias` y `CorrelacionadoraDeAnomalias`. Después comprobar `LabRole`, Step Functions y Streams en AWS Academy, y los accesos de GCP y Azure. La IA propuesta usa Gemini Developer API en GCP para sugerencias revisables; Bedrock queda condicionado a una prueba de acceso y costo. El [checklist](PENDIENTES.md) establece qué se considera terminado en cada proveedor.
