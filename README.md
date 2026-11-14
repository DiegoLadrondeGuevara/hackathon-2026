# Red TeleCorp — Hackathon Cloud 2026

Proyecto del grupo 12, Escuadrón S3. Buscamos detectar y gestionar incidentes de telecomunicaciones relacionando reportes de usuarios con lecturas de antenas. La solución propuesta es **serverless y multinube**: AWS Academy lleva la operación principal, Google Cloud aporta analítica/IA y Azure publica un estado mínimo por zona.

## Estado actual

**Análisis y arquitectura v1 documentados. Infraestructura y aplicación todavía no desplegadas.** Las decisiones del prototipo no equivalen a puntos otorgados por el jurado. [PENDIENTES.md](PENDIENTES.md) es el tablero de trabajo; una casilla se completa solo con implementación y evidencia.

## Archivos de referencia (raíz)

| Archivo | Uso |
| --- | --- |
| [hackathonCloudEnunciado.txt](hackathonCloudEnunciado.txt) | Texto original del reto y rúbrica. |
| [puntos-dolor-cliente.md](puntos-dolor-cliente.md) | Contexto, 13 dolores y definiciones S01–S12. |
| [rubrica-hackathon.md](rubrica-hackathon.md) | Criterios, condiciones de entrega y evidencia pendiente. |
| [arquitectura-solucion-v1.md](arquitectura-solucion-v1.md) | Diagrama, capas, flujo, tablas y claves de consulta. |
| [arquitectura-v1-panorama.svg](arquitectura-v1-panorama.svg) / [PNG](arquitectura-v1-panorama.png) | Vista clara de las tres nubes para compartir. |
| [arquitectura-v1-aws.svg](arquitectura-v1-aws.svg) / [PNG](arquitectura-v1-aws.png) | Detalle del núcleo AWS. |
| [decision-ia.md](decision-ia.md) | Comparación de opciones gratuitas y recomendación de IA. |
| [PENDIENTES.md](PENDIENTES.md) | Trabajo por proveedor e integración. |

Los `.mmd` de la raíz son los diagramas editables en Mermaid. Los PNG/SVG son vistas exportadas. Un ZIP anterior del diagrama quedó en `/chatgpt/` porque ya no contenía la versión vigente.

## Organización del desarrollo

- [`aws/infra/`](aws/infra/README.md): infraestructura y despliegue de AWS Academy. Las Lambdas usarán el `LabRole` existente; no se crearán roles IAM.
- [`gcp/infra/`](gcp/infra/README.md): Cloud Run, BigQuery y secretos de integración.
- [`azure/infra/`](azure/infra/README.md): Functions y Table Storage.
- `/chatgpt/`: borradores y archivos temporales locales, **ignorados por Git**. Los documentos importantes quedan en la raíz.

## Reglas que no debemos perder

- `0 GB/min`: antena inhabilitada; `0 < x < 60`: caída; `60 <= x <= 129`: normal en la simulación; `x > 129`: saturada.
- Diez **usuarios diferentes** de la misma zona/servicio en menos de 24 horas crean un incidente colectivo *sospechado* y activan verificación.
- Se necesitan al menos dos nubes; elegimos **tres**. Vercel no cuenta según el enunciado.
- Step Functions, IA funcional, operación serverless, persistencia y disponibilidad forman parte de la rúbrica. El video debe durar **como máximo cinco minutos**. Canvas requiere video, repo de GitHub y arquitectura; el enunciado prohíbe adjuntar un informe.

## Próxima acción técnica

Comprobar permisos reales de `LabRole` para Lambda y Step Functions, crear una ruta pequeña API Gateway → Lambda → DynamoDB, y probar los accesos de GCP y Azure. El [checklist](PENDIENTES.md) establece qué se considera terminado en cada proveedor.
