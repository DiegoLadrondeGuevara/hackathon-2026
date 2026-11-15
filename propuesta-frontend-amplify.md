# Propuesta de frontend: portal Red TeleCorp

**Estado:** propuesta para revisión; el frontend aún no está implementado ni publicado. **Alcance:** portal autenticado de clientes y operadores en AWS Amplify Hosting. La página pública de estado alojada en Azure sigue siendo una aplicación distinta. Esta propuesta usa el [contrato de API](contracts/api.md), los [puntos de dolor](puntos-dolor-cliente.md) y el código AWS presente el 15/11/2026.

## 1. Propósito

El cliente debe poder informar un problema, recuperar su reporte y comprender qué se está haciendo. Operaciones debe encontrar primero los incidentes urgentes, revisar la evidencia, tomar decisiones y dejar historial. El portal presenta el resultado del procesamiento de AWS, GCP y Azure; no reemplaza las reglas de correlación, prioridad o comunicación del backend.

Nombre visible propuesto: **Red TeleCorp · Centro de servicio**. Una sola aplicación con navegación y permisos por rol:

```text
Cliente:   Acceso → Inicio → Nuevo reporte → Mis reportes → Detalle e historial
                                └──────────→ Estado de mi zona → Página pública Azure
Operador:  Acceso → Bandeja de incidentes → Detalle, evidencia y decisión
                    ├──────────→ Reportes por zona → Detalle y cambio de estado
                    └──────────→ Tendencias (cuando el endpoint esté integrado)
```

## 2. Experiencia visual

- Interfaz de centro de operaciones: fondo claro, azul petróleo para navegación y acentos ámbar/rojo solo para advertencias y prioridad. Cada estado lleva **texto e icono**, no depende únicamente del color.
- El encabezado indica rol, nombre de la sesión y tiempo restante aproximado del JWT. La navegación móvil pasa a menú compacto.
- Cliente: lenguaje cotidiano («Estamos evaluando tu reporte»). Operador: códigos exactos, fechas, prioridad y evidencia. Siempre se distingue **reporte individual** de **incidente de zona**.
- Fechas en hora local con opción de ver UTC; en las peticiones se envían fechas ISO-8601 UTC. Estados vacíos explican qué hacer; errores conservan el formulario y ofrecen reintentar.
- Ningún panel presenta datos sintéticos como producción. Las cifras solo proceden de respuestas reales del API; una lista paginada no se muestra como total global.

**Composición inicial:** el cliente ve una acción principal «Crear reporte», sus casos recientes y un bloque de estado de la zona elegida. En móvil, esas secciones se apilan. El operador ve filtros de estado/zona arriba, una bandeja ordenada de casos a la izquierda y el detalle del caso seleccionado a la derecha; en móvil, el detalle se abre como pantalla independiente. El historial y la sugerencia IA son secciones del detalle, no ventanas que oculten la decisión operativa.

## 3. Recorrido del cliente

1. **Acceso.** Identificador y contraseña → `POST /auth/login`. Con `role=CUSTOMER`, entra al espacio de cliente. El JWT dura 15 minutos y solo se mantiene en memoria durante la sesión de la pestaña; al vencer, se solicita iniciar sesión otra vez. El frontend oculta vistas de otro rol, pero API Gateway y las Lambdas hacen la autorización real.
2. **Inicio.** Resumen de sus últimos reportes y acceso destacado a «Reportar una falla». El estado de zona se consulta por `GET /incidentes?zone_id=...` para una zona elegida; solo muestra la vista pública. Un enlace abre la página independiente de Azure e indica que su dato puede estar atrasado.
3. **Nuevo reporte.** Formulario por pasos cortos: número asociado al servicio, zona del catálogo, servicio `MOVIL` o `INTERNET`, tipo de problema permitido, fecha/hora del inconveniente, ubicación aproximada y descripción. `GET /zonas` alimenta el selector. El formulario exige ubicación aproximada conforme al enunciado, aunque el handler hoy la acepta vacía; AWS debe alinear esa validación. `POST /reportes` usa `Idempotency-Key` generada para evitar duplicados por doble clic o reintento.
4. **Confirmación.** Muestra `report_id`, estado `REGISTRADA`, hora de creación y enlace al detalle. La confirmación significa **reporte recibido**, no incidencia colectiva confirmada.
5. **Mis reportes.** `GET /reportes?limit=&cursor=` permite cargar más. Cada tarjeta muestra estado, servicio, zona y fecha. `GET /reportes/{report_id}` muestra los cinco estados posibles y la cronología real de transiciones. Si el backend agrega `incident_id` al reporte, se puede cruzar con la vista pública de la zona para mostrar el estado de la afectación; el cliente no llama al detalle privado del incidente.

## 4. Recorrido del operador

1. **Bandeja de incidentes.** Pestañas por estado real del backend: `EVALUACION`, `CONFIRMADO`, `RESTABLECIDO`, `CERRADO`. `GET /incidentes?status=...` devuelve la cola paginada; se puede filtrar por `zone_id`. Las tarjetas destacan prioridad `P1/P2/P3`, zona, servicio, usuarios que **reportaron**, hora de apertura y origen técnico o de reportes si el campo existe. «En evaluación» no se presenta como falla verificada.
2. **Detalle operativo.** `GET /incidentes/{incident_id}` muestra historial, número de reportes, número de usuarios distintos, antenas vinculadas y evidencia disponible. Una sección separada consulta `GET /incidentes/{incident_id}/sugerencia`; muestra hipótesis y fundamento como **sugerencias de IA revisables**. Si responde `available:false`, se indica «Sugerencia no disponible» sin bloquear la gestión.
3. **Decisión.** Botones solo para transiciones permitidas por el estado actual: `EVALUACION → CONFIRMADO/CERRADO`, `CONFIRMADO → RESTABLECIDO`, `RESTABLECIDO → CERRADO/CONFIRMADO`. `PATCH /incidentes/{incident_id}/estado` envía `to_status` y `reason`. Tras un `409`, el portal vuelve a consultar el incidente antes de permitir otra decisión. La recuperación técnica por sí sola no pulsa el botón de restablecimiento.
4. **Reportes por zona.** `GET /reportes?zone_id=...` y `GET /reportes/{id}` muestran casos individuales e historial. `PATCH /reportes/{id}/estado` permite avanzar por `REGISTRADA → EN_REVISION → EN_ATENCION → SOLUCIONADA → CERRADA`, con el retorno `SOLUCIONADA → EN_ATENCION` que admite el backend. Cada cambio solicita motivo cuando corresponda y muestra el resultado guardado.
5. **Tendencias.** Espacio para zonas, antenas, tipos frecuentes, recurrencia y retraso de detección según `GET /tendencias?days=7|30`. El handler ya está integrado en `main` con pruebas; falta comprobar su respuesta real en el stack desplegado. No se fabrican gráficas con números ficticios para simular esta capacidad.

## 5. Conexiones y límites de los datos

| Vista | API o destino | Estado del código revisado |
| --- | --- | --- |
| Acceso | `POST /auth/login` | Handler implementado; falta prueba real con cuentas sembradas. |
| Selector de zonas | `GET /zonas` | Handler implementado; requiere JWT y datos de la semilla. |
| Crear y consultar reportes | `POST /reportes`, `GET /reportes`, `GET /reportes/{id}` | Handlers implementados; falta prueba integral desde navegador. |
| Cambiar estado de reporte | `PATCH /reportes/{id}/estado` | Handler implementado; acceso `OPERATOR`. |
| Estado de zona e incidentes | `GET /incidentes`, `GET /incidentes/{id}`, `PATCH /incidentes/{id}/estado` | Handlers implementados; detalle y cambio solo `OPERATOR`. |
| Sugerencia IA | `GET /incidentes/{id}/sugerencia` | Handler implementado; depende de la conexión real a GCP. |
| Tendencias | `GET /tendencias` | Handler integrado en `main` con pruebas; falta desplegar/probar la versión actual del stack. |
| Estado público independiente | Página Azure `https://mango-ground-073e60210.3.azurestaticapps.net` | Desplegada; falta publicar cambios de zona desde AWS. |
| Notificaciones | Sin ruta de lectura en el contrato actual | `NotificadoraDeClientes` está implementada en `main`; el portal no puede mostrar entrega ni editar consentimiento sin otro endpoint. |

La base AWS conocida es `https://ynyvt8x51k.execute-api.us-east-1.amazonaws.com`. Salvo `/auth/login`, se envía `Authorization: Bearer <jwt>`. Listas con `next_cursor` se continúan hasta que sea `null`; una página vacía puede tener otro cursor. Se distinguen `401` (sesión vencida), `403` (sin permiso), `409` (otro cambio o transición no permitida) y `5xx` (reintento). El navegador no recibe claves de GCP, Azure, Grafana, SSM ni `LabRole`.

## 6. Relación con los puntos de dolor

| Dolor | Aporte del portal y del backend |
| --- | --- |
| D03 y D04 · reportar y seguir un caso | Formulario completo, identificador, lista personal y cronología; AWS persiste y audita. Para cerrar D03, debe validar en servidor la ubicación requerida y que el número de servicio pertenece al cliente. |
| D05 y D02 · reconocer afectación colectiva y unir señales | Operador ve el incidente, sus reportantes y antenas vinculadas; la correlación y verificación ocurren en AWS, aunque el portal las haga visibles. |
| D06 · informar a afectados | Cliente consulta estados; la comunicación directa depende de `NotificadoraDeClientes` y un canal real. El portal no afirma que un correo/SMS fue enviado si no existe lectura de ese resultado. |
| D07 · atender lo más crítico | Bandeja por estado y prioridad, contexto de zona y cantidad de usuarios que reportaron; la puntuación la calcula AWS. |
| D08, D09 y D12 · focos, recurrencia e historial | Detalle e historial desde los endpoints existentes; las gráficas dependen de la integración de `ObtenerTendencias`. |
| D10 · detectar antes que usuarios | El detalle puede distinguir origen `ANTENA` o `REPORTES` cuando llega en la respuesta; el cálculo del retraso depende del backend analítico. |
| D01, D11 y D13 · telemetría, picos y costo | El portal expone resultados, pero su solución y prueba están en la ingesta, colas y servicios serverless; no se atribuyen al frontend. |

## 7. Implementación propuesta cuando se apruebe el diseño

- Carpeta `frontend/` para una SPA **React + Vite + TypeScript**, componentes simples y CSS propio. Amplify Hosting compila y sirve `dist/`; la configuración de monorepo apuntará a `frontend/` y una regla SPA enviará rutas de navegación a `index.html`. [Amplify documenta monorepos](https://docs.aws.amazon.com/amplify/latest/userguide/monorepo-configuration.html) y [reescrituras de SPA](https://docs.aws.amazon.com/amplify/latest/userguide/redirect-rewrite-examples.html).
- `VITE_API_BASE_URL` guarda solo la URL pública de API Gateway. Las variables `VITE_` quedan dentro del JavaScript entregado al navegador: **ningún secreto** va allí. [Referencia de Vite](https://vite.dev/guide/env-and-mode).
- Cliente HTTP común con tiempo límite, errores normalizados, `Authorization`, paginación y reintento seguro; rutas y tipos derivados de `contracts/api.md`. La clave de idempotencia se conserva durante un intento de creación y se cambia al iniciar un reporte nuevo.
- Protección de navegación por rol, caducidad del JWT, estados de carga/vacío/error, formularios accesibles y diseño adaptable a móvil. La autorización final siempre sigue en el backend.
- Primero se implementan acceso, formulario y seguimiento; después bandeja y decisiones; finalmente sugerencia IA y tendencias cuando las integraciones respondan en la nube. La prueba de aceptación recorre ambos roles con datos sintéticos y una pantalla pequeña.

## 8. Información que necesitamos del equipo para probarlo de punta a punta

1. Confirmar si `scripts/seed.py` ya se ejecutó en el stack `dev` y quién entregará **por canal privado** un cliente y un operador de demo con sus contraseñas. Los identificadores por sí solos no validan el login.
2. Confirmar que la URL de API Gateway anterior sigue siendo la activa y probar `POST /auth/login`, `GET /zonas` y un ciclo de reporte con cuentas de prueba. La salida de `serverless deploy` prueba rutas declaradas, no el recorrido.
3. Confirmar con AWS cómo quedará CORS al publicar Amplify. El `aws/serverless.yml` vigente permite `*`; se debe probar el origen real de Amplify y decidir si se restringe. No se usan cookies ni claves secretas en el navegador.
4. Confirmar cuándo se despliega la versión de `ObtenerTendencias` que ya entró en `main` y cuándo se prueba la conexión real de `ObtenerSugerenciaIA` a GCP; indicar si la prioridad incluye una explicación en el objeto de incidente.
5. Si desean mostrar en el portal **entrega de notificaciones**, **preferencias de contacto** o **lista exacta de reportes vinculados a un incidente**, AWS debe definir una ruta autorizada para esos datos. Hoy el contrato ofrece estados y conteos, no esas consultas.
6. Acordar con AWS la carga ficticia de **números de servicio por cliente** y la validación de pertenencia en `CrearReporte`. Hoy `scripts/seed.py` no los asigna y el handler solo verifica que `service_number` sea texto. Alinear también `location_text`: el reto lo solicita, pero el handler lo trata como opcional.
