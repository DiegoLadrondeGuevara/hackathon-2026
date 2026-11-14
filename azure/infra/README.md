# Azure — infraestructura

Aquí irán los archivos reproducibles de infraestructura **Azure**. Ver [PENDIENTES.md](../../PENDIENTES.md), [arquitectura-solucion-v3.md](../../arquitectura-solucion-v3.md) y [decision-ia.md](../../decision-ia.md).

Recursos previstos: Azure Functions en **Flex Consumption** con `always ready = 0`, Storage Account/Table Storage y un almacén de secretos para verificar los eventos HTTPS de AWS. La tabla publica solo estado por zona y hora de última sincronización, sin datos personales.

La propuesta v3 añade `red-telecorp-estado-publico` (**Azure Static Web Apps**) como página independiente que consulta la Function `red-telecorp-estado-api` y la tabla `EstadoZonas`. Si AWS deja de enviar eventos, la página conserva el último estado y señala que `last_synced_at` está atrasado. Se debe probar el plan Free en la suscripción del equipo y el CORS de la Function antes de considerarlo viable.

Azure AI Language F0 es una alternativa opcional de IA. Azure Communication Services Email solo se evalúa si AWS no permite el canal de correo/SMS y se puede habilitar un dominio. Primero confirmar que la suscripción y la región del equipo permiten crear Functions y Storage.
