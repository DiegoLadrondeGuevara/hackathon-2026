# Google Cloud — infraestructura

Aquí irán los archivos reproducibles de infraestructura **GCP**. Ver [PENDIENTES.md](../../PENDIENTES.md), [arquitectura-solucion-v1.md](../../arquitectura-solucion-v1.md) y [decision-ia.md](../../decision-ia.md).

Recursos previstos: Cloud Run function con mínimo de instancias en cero, BigQuery para eventos/agregados, almacén de secretos y permisos mínimos. La función usará Gemini Developer API Free para sugerencias de investigación con datos sintéticos o depurados; su clave no debe estar en el frontend ni en Git. **Vertex AI no se presupone gratuito**.

Antes de codificar la plantilla, confirmar proyecto, región, facturación/cuotas y llamada de prueba a Gemini API. Los eventos de AWS llegan firmados por HTTPS y no contienen datos personales.
