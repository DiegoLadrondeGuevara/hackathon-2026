# Red TeleCorp: contexto y puntos de dolor

Fuente principal: [hackathonCloudEnunciado.txt](hackathonCloudEnunciado.txt), líneas 5–37. Fecha de análisis: 14 de noviembre de 2026.

## Qué problema de negocio se está resolviendo

Red TeleCorp presta telefonía móvil, Internet y conectividad a millones de usuarios en distintas zonas. La calidad del servicio depende de una red distribuida de antenas y otros elementos. La empresa recibe métricas de antenas, reportes de usuarios y registros internos, pero necesita relacionarlos a tiempo para descubrir, atender y explicar las incidencias. Un reporte aislado puede ser la primera señal de una falla masiva; una antena puede aparentar recuperarse mientras acumula fallas recurrentes.

El resultado buscado es una operación capaz de **detectar antes, distinguir alcance y gravedad, dar seguimiento verificable, comunicar el estado y aprender del historial**, incluso cuando llegan muchos eventos juntos y sin mantener servidores encendidos permanentemente. El enunciado plantea una simulación: no aporta datos reales de la red ni una infraestructura existente que haya que integrar.

Actores: usuario que reporta y consulta; equipo de operaciones que revisa, prioriza y resuelve; responsables que analizan tendencias. Un evento de antena, un reporte individual y un incidente colectivo son entidades distintas y conviene no confundirlas.

## Reglas explícitas del reto

- **Lectura de antena (GB/min):** `0` = inhabilitada; `0 < valor < 60` = caída según la convención del enunciado; `60 <= valor <= 129` = dentro del rango de la simulación; `valor > 129` = saturada. El caso `0` tiene prioridad sobre la regla general de «menos de 60». Estos límites son reglas del concurso, no umbrales universales de telecomunicaciones. Fuente: línea 11.
- **Posible incidente colectivo:** al menos **10 usuarios diferentes** reportan un problema relacionado con el servicio en **la misma zona** durante un intervalo **menor a 24 horas**; se debe verificar la infraestructura correspondiente. Diez reportes de una misma persona no satisfacen la condición. El texto no fija cómo se delimitan zonas ni qué tipos de problemas se consideran equivalentes. Fuente: líneas 19–21.
- **Datos del reporte:** identificación, número asociado al servicio, ubicación aproximada, fecha y hora del inconveniente, tipo de problema y descripción. Fuente: línea 15.
- **Estados de una incidencia:** registrada, en revisión, siendo atendida, solucionada, cerrada; conservar el historial de su evolución. Fuente: línea 17.

## Inventario de dolores y resultados comprobables

La columna de evidencia es una **propuesta de demostración**, no un requisito adicional textual. Sirve para decidir después qué construir y cómo probar que resuelve el problema.

| ID | Dolor y efecto para el cliente | Resultado que debería demostrar la solución | Fuente |
| --- | --- | --- | --- |
| D01 | Una falla de antena, saturación o interrupción localizada afecta servicios y puede pasar inadvertida. | Ingerir lecturas periódicas por antena, conservarlas y clasificar correctamente `0`, `<60`, `60–129` y `>129`. | 7, 11 |
| D02 | Las señales llegan de fuentes separadas: métricas, usuarios y registros internos. La operación pierde contexto. | Relacionar reportes con zona, tiempo y comportamiento de infraestructura; explicar de dónde salió una alerta. Los registros internos son una fuente mencionada, pero el texto no impone una integración concreta. | 9, 31 |
| D03 | El usuario necesita una vía estructurada para avisar un problema. | Portal que acepte y valide los seis datos pedidos, confirme el registro y permita recuperar la incidencia. | 13–15 |
| D04 | Una vez reportado, el caso puede perderse o no tener trazabilidad. | Consultar y administrar reportes; cambiar entre los cinco estados y mostrar quién/cuándo/qué cambió en su historial. | 17 |
| D05 | Reportes aparentemente aislados pueden esconder una afectación de zona. | Detectar 10 usuarios distintos con problemas relacionados en la misma zona en menos de 24 h; crear un **posible** incidente colectivo y disparar verificación de infraestructura. | 19–21 |
| D06 | Usuarios afectados quedan sin información durante la atención. | Comunicar a quienes reportaron la evaluación, la identificación de una incidencia de zona y el restablecimiento, según el estado; usar correo y/o celular disponibles. | 23 |
| D07 | La atención por orden de llegada puede dejar atrás casos de mayor impacto o servicios críticos. | Priorizar con criterios visibles de cantidad de afectados y tipo de zona (residencial, industrial, educativa, médica o crítica); justificar el orden. | 25 |
| D08 | No se ven con claridad los focos de problemas. | Consultar zonas con más incidentes, antenas con más problemas y tipos de reporte más frecuentes. | 27 |
| D09 | Una antena que falla repetidamente puede parecer sana entre eventos. | Detectar recurrencia entre días, conservar episodios y señalar posible problema estructural. | 29 |
| D10 | Los usuarios pueden detectar antes que la supervisión interna. | Comparar cronología de lecturas y reportes; identificar el inicio y reducir el retraso de detección. | 31 |
| D11 | Un corte de energía o evento climático puede producir una ráfaga de eventos y perder reportes. | Aceptar incidentes simultáneos y un pico de entradas; mostrar que los registros persisten y se procesan sin pérdida ni deterioro considerable. | 33 |
| D12 | Sin historial, la empresa no aprende de duración, alcance ni recurrencia. | Analizar evolución, duración, zonas, usuarios afectados y frecuencia de problemas por elemento. | 35 |
| D13 | La infraestructura siempre encendida eleva costo y limita elasticidad. | Escalar con usuarios/eventos y justificar el costo operativo de una solución sin servidores permanentes. | 37 |

## Relaciones que importan para el diseño posterior

1. **Detectar no es confirmar.** Diez usuarios activan la hipótesis de incidente colectivo y una verificación; el enunciado no autoriza llamar «confirmada» a toda agrupación automáticamente.
2. **Estado del reporte y estado de la afectación de zona pueden diferir.** Varios reportes podrían pertenecer a un incidente colectivo. La solución deberá mostrar la relación para no duplicar comunicaciones o perder trazabilidad.
3. **La prioridad necesita datos de impacto.** El número de reportes no equivale necesariamente al número total de afectados; para hablar de miles de usuarios se requeriría una estimación o dato adicional.
4. **Las métricas de antena y el testimonio del usuario se complementan.** Un valor normal no descarta por sí solo una falla de servicio, y una lectura anómala no demuestra por sí sola qué usuarios fueron afectados.
5. **El historial sirve tanto a la atención como al análisis.** Guardar únicamente el estado actual impediría reconstruir tiempos de detección, atención y restablecimiento.

## Definiciones propuestas para la solución v1

**Estas reglas las elegimos para el prototipo; no figuran como números o procedimientos obligatorios en el enunciado.** Son una base operativa revisable si el equipo obtiene datos reales o una aclaración de los organizadores. La [rúbrica](rubrica-hackathon.md) contiene el checklist para verificar que las decisiones estén reflejadas en la implementación.

### S01. Zona y cobertura de antenas

- «Misma zona» significa el mismo `zone_id` de un catálogo único. Para la demo se preparan zonas ficticias de tipo residencial, industrial, educativo, médico y crítico. Cada zona tiene nombre y límites conocidos por la simulación.
- En el portal, el usuario elige su zona y puede añadir una referencia de ubicación aproximada. Si se usan coordenadas, se transforman al `zone_id` solo cuando caen inequívocamente dentro de una zona; si no, el reporte queda pendiente de ubicación y no entra aún al conteo colectivo.
- Una antena puede cubrir varias zonas y una zona puede depender de varias antenas. Se mantiene una tabla de cobertura explícita. La verificación revisa **todas las antenas asociadas a la zona**, sin suponer que la más cercana es la responsable.
- **Comprobación:** dos reportes con el mismo `zone_id` se agrupan; una zona vecina no se agrupa; una antena compartida aparece al verificar ambas zonas.

### S02. Qué reportes son «relacionados»

- Catálogo de servicio: `internet`, `voz`, `mensajería` y `conectividad general`. Catálogo de síntoma: `sin servicio`, `degradado` e `intermitente`. La descripción libre se conserva aparte.
- Para el umbral automático, los reportes son relacionados si tienen **el mismo `zone_id` y el mismo servicio**; el síntoma puede variar. `Conectividad general` forma su propio grupo. Operaciones podrá vincular grupos de servicios distintos cuando una verificación revele una falla común.
- La IA, si se usa para sugerir categoría, no cambia silenciosamente el servicio que el usuario confirmó ni confirma una incidencia por sí sola.
- **Comprobación:** 10 reportes de Internet en una zona pueden activar la regla aunque describan síntomas distintos; reportes de voz de esa zona quedan en otro grupo hasta que se vinculen justificadamente.

### S03. Tiempo y ventana de 24 horas

- Guardar `occurred_at` (hora declarada del inconveniente) y `received_at` (hora en que el sistema aceptó el reporte) en UTC. Mostrar hora local en la interfaz. Los eventos y cambios de estado tienen identificador y marca de tiempo; la convención de identificador, origen y hora se inspira en [CloudEvents](https://github.com/cloudevents/spec/blob/main/cloudevents/spec.md), sin obligarnos a adoptar todo ese formato.
- El conteo colectivo usa una **ventana móvil estricta**: `ahora - 24 h < occurred_at <= ahora`. Una ocurrencia exactamente 24 horas anterior queda fuera. Los reportes recibidos tarde se guardan, pero solo contribuyen si su `occurred_at` aún cae dentro de esa ventana. Reportes más antiguos aportan al historial y se pueden revisar manualmente.
- Rechazar una hora futura que supere la hora actual en más de 5 minutos; mostrar al usuario el error para corregirla. Conservar la hora declarada y la hora de recepción sin sobrescribir una con otra.
- **Comprobación:** 9 usuarios no activan la regla; 10 sí; 10 reportes del mismo usuario cuentan como uno; un reporte exactamente al límite de 24 horas no cuenta.

### S04. Métricas de antena y datos ausentes

- En la simulación, **una lectura por antena por minuto**. Campos mínimos: `antenna_id`, `measured_at`, `traffic_gb_per_min` y `event_id`. El tráfico debe ser un número finito no negativo; usar GB/min como unidad única. La pareja `antenna_id` + minuto identifica la lectura de ese intervalo.
- Clasificar cada lectura con los umbrales explícitos del reto. Una lectura anómala crea señal para investigar; lecturas repetidas del mismo intervalo no crean episodios nuevos.
- Si faltan **tres lecturas consecutivas**, marcar `telemetría ausente` y pedir verificación. **Ausencia de dato no significa 0 GB/min ni antena inhabilitada.** La documentación de [CloudWatch sobre datos faltantes](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/alarms-and-missing-data.html) respalda tratar este caso de forma explícita.
- **Comprobación:** `0`, `59`, `60`, `129` y `130` se clasifican como indica el reto; tres minutos sin datos producen un estado distinto de `0`.

### S05. Incidente colectivo y verificación

- Contar `customer_id` distintos por `zone_id` + servicio dentro de S03. Al llegar a 10, crear **un incidente colectivo sospechado** para ese grupo si no hay uno activo; enlazarle los reportes, incluidos los posteriores. Recalcular el total sin contar dos veces a un usuario.
- La verificación reúne las métricas de antenas de S01 en el periodo relevante y los registros internos que existan en la simulación. Si encuentra evidencia, un operador marca `confirmado`; si no, mantiene `en evaluación` o descarta la hipótesis con motivo registrado. Ningún resultado automático equivale a diagnóstico definitivo.
- **Comprobación:** el décimo usuario abre un solo incidente colectivo; el undécimo se vincula al mismo; el panel muestra qué antenas se revisaron y la decisión del operador.

### S06. Estados, responsables e historial

- Los **reportes individuales** usan los cinco estados del reto: `registrada → en revisión → siendo atendida → solucionada → cerrada`. Un operador puede devolver un caso a revisión si el problema reaparece, dejando el motivo en el historial.
- El **incidente colectivo** tiene ciclo propio: `sospechado → confirmado → restablecido → cerrado`, con opción de `descartado` tras la verificación. Así se separan una hipótesis de zona y el avance de cada reporte.
- Toda transición guarda estado anterior, nuevo, hora, actor y motivo; el historial es de solo anexado. El usuario ve el estado de su reporte y, si corresponde, el del incidente de zona. Hay un responsable de operaciones por incidente colectivo. La separación entre eventos, incidentes y problemas y la asignación de responsables sigue el enfoque de [AWS Well-Architected para respuesta operativa](https://docs.aws.amazon.com/wellarchitected/latest/framework/ops_event_response_event_incident_problem_process.html).
- **Comprobación:** se puede reconstruir cronológicamente qué ocurrió y quién decidió confirmar, restablecer o cerrar.

### S07. Recurrencia de antena

- Un **episodio** comienza con una lectura anómala y termina tras **cinco lecturas normales consecutivas**. La telemetría ausente no cierra el episodio. Cada episodio conserva inicio, fin, peor clasificación y antena.
- Si una antena acumula **tres episodios distintos en siete días móviles**, crear alerta de posible problema estructural para revisión especializada. Este umbral de recurrencia es elección del prototipo, no del enunciado.
- **Comprobación:** muchas lecturas anómalas continuas cuentan como un episodio; tres episodios separados disparan la alerta.

### S08. Prioridad por impacto y criticidad

- Usar tres niveles dinámicos con explicación visible: **P1** = falla confirmada que afecta zona médica/crítica, o al menos 100 usuarios distintos reportando en una zona/servicio durante 24 h; **P2** = incidente colectivo sospechado (10–99 usuarios), antena inhabilitada, o falla confirmada fuera de zona crítica; **P3** = reporte aislado u otra anomalía de antena sin evidencia de afectación amplia.
- La prioridad más alta aplicable prevalece. Un operador puede subirla manualmente con motivo; nunca se infiere que el total de reportantes sea el total real de afectados. La cifra visible se llama `usuarios que reportaron`. La decisión de ordenar por impacto y urgencia se apoya en la [guía de AWS Well-Architected](https://docs.aws.amazon.com/wellarchitected/latest/framework/ops_event_response_prioritize_events.html); **los umbrales P1/P2/P3 son nuestros**.
- **Comprobación:** un caso crítico confirmado supera a reportes aislados; el panel muestra la regla que produjo la prioridad y cualquier intervención manual.

### S09. Identidad, duplicados y protección de datos

- Para la hackathon, usar **usuarios y números de servicio ficticios** en un catálogo de prueba. `customer_id` identifica al usuario; el número de servicio se valida contra su registro. El usuario solo consulta sus reportes; el personal de operaciones puede gestionar los de su ámbito. Estos permisos de la **aplicación** son distintos de los roles IAM de AWS Academy.
- Cada envío lleva una clave de idempotencia: reintentar el mismo envío devuelve el mismo reporte, mientras que un problema nuevo del mismo usuario puede crear otro. Esto sigue la práctica de [Amazon Builders' Library para reintentos seguros](https://aws.amazon.com/builders-library/making-retries-safe-with-idempotent-APIs/).
- Identificación, teléfono, correo, ubicación y descripción se tratan como datos sensibles: acceso limitado, cifrado del servicio elegido, sin valores reales en demo ni datos personales en logs. La [guía de clasificación de datos de AWS](https://docs.aws.amazon.com/wellarchitected/latest/framework/sec_data_classification_identify_data.html) respalda identificar qué información requiere protección. La autenticación de clientes reales necesitaría un diseño adicional; las cuentas ficticias no se presentan como listas para producción.
- **Comprobación:** dos envíos con la misma clave crean un solo reporte; otro usuario no puede abrirlo; la demo no expone datos reales.

### S10. Comunicación a usuarios

- El perfil ficticio guarda correo y/o celular y la preferencia de canal. El usuario acepta recibir comunicaciones de estado en la simulación. Si no hay canal disponible, el estado sigue visible en el portal.
- Crear **una intención de comunicación por usuario, incidente colectivo e hito**: `en evaluación`, `incidencia confirmada en la zona`, `servicio restablecido`. Registrar canal, momento e intento/resultado de entrega. Los reintentos deben usar el mismo identificador para evitar duplicados cuando el proveedor lo permita; un proveedor sin idempotencia no garantiza entrega exactamente una vez. No prometer tiempo de restablecimiento sin información verificada.
- **Comprobación:** los usuarios vinculados generan una intención del hito que corresponda; el resto no; un reintento no crea otra intención. La comunicación periódica durante incidentes está respaldada por la [guía de Google SRE](https://sre.google/resources/practices-and-processes/incident-management-guide/).

### S11. Picos, tiempos y conservación: objetivos de la demo

- Carga de prueba inicial: **30 antenas** a una lectura/minuto y una ráfaga de **1000 reportes en 10 minutos**. Meta interna: confirmar la recepción de un reporte en **menos de 3 segundos para el percentil 95** y detectar el umbral colectivo en **menos de 2 minutos** después de aceptar el décimo reporte. Son objetivos de prueba, no promesas para millones de usuarios.
- Un reporte solo se declara «recibido» después de persistirlo; si falla el procesamiento posterior, queda pendiente de reintento y visible para operaciones. Conservar el identificador del evento para procesar reintentos sin duplicarlo.
- Retención propuesta: **30 días** de lecturas detalladas; **un año** de reportes, estados e incidentes; **un año** de agregados por zona/antena/tipo. Al vencer cada plazo, borrar o agregar según corresponda. Para la demo, el laboratorio puede tener una vida menor y se validará su comportamiento real.
- **Comprobación:** la prueba de ráfaga contabiliza 1000 entradas únicas aceptadas, sin pérdidas; los percentiles y tiempos se miden, no se asumen.

### S12. Historia e indicadores

- Registrar para cada incidente `first_signal_at`, `detected_at`, `confirmed_at`, `restored_at` y `closed_at` cuando aplique. Medir **tiempo hasta detección**, **duración activa**, **usuarios distintos que reportaron**, episodios por antena y conteos por zona/tipo en periodos de 7 y 30 días.
- Las métricas de red, los reportes y los registros internos sintéticos se relacionan por zona y tiempo, mostrando su procedencia. No llamar «usuarios afectados» a una estimación inexistente: mostrar reportantes conocidos y, si se incorpora una estimación, identificar su método y fuente.
- **Comprobación:** el panel responde qué zona tuvo más incidentes, qué antena falló más y qué tipo se reportó más; una cronología explica cuándo se detectó un caso frente a su primera señal.

## Decisiones que sí dependen de la siguiente etapa

1. **Servicios concretos y diagrama multinube:** el [diagrama propuesto por el equipo](arquitectura-solucion-propuesta-equipo.png) usa AWS Academy, Google Cloud (GCP) y Azure; el [análisis beta v4](arquitectura-solucion-v4.md) documenta decisiones técnicas. Sus servicios, permisos y costos todavía deben comprobarse en las tres cuentas.
2. **Presupuesto y cuotas reales:** el enunciado no da cifras. Verificar las de AWS Academy, GCP y Azure antes de fijar límites de despliegue o afirmar un costo.
3. **Mensajería e IA disponibles:** validar si se puede enviar correo/SMS y ejecutar una función de IA real con los permisos presentes. Si no, ajustar el canal o la función sin alterar los estados y reglas ya definidos.
4. **Objetivos de producción y regulación aplicable:** la simulación no proporciona acuerdos de servicio, población por zona ni políticas de conservación para una empresa real. Los objetivos S11 y la retención son supuestos de prototipo, sujetos a revisión antes de uso real.

## Restricción de implementación informada por el equipo

La solución futura se diseñará con **AWS Academy, Google Cloud y Azure**: el equipo indica que en AWS Academy dispone de `LabRole`, no puede crear roles IAM y no puede usar WAF; otros servicios podrían estar limitados. Esto es una restricción de su laboratorio concreto, no una afirmación universal sobre todas las cuentas de AWS Academy. Antes de elegir cada servicio habrá que comprobar permisos, región, cuotas y presupuesto reales del laboratorio. La rúbrica exige al menos **dos nubes** y el equipo decidió usar tres.
