# Rúbrica y seguimiento de la hackathon

Fuente: [hackathonCloudEnunciado.txt](hackathonCloudEnunciado.txt), líneas 39–66. Fecha de análisis: 14 de noviembre de 2026.

**Uso de este archivo:** actualizar `Estado`, enlazar evidencia real y registrar la puntuación otorgada cuando exista. `Pendiente` significa que todavía no hay una implementación o demostración verificada; estos documentos de análisis no cuentan como solución terminada. Los puntos son máximos de la rúbrica, no una predicción de la nota.

## Condiciones de admisión y entrega (prioridad máxima)

| ID | Condición literal o interpretación conservadora | Comprobación antes de entregar | Estado |
| --- | --- | --- | --- |
| G01 | **Al menos dos nubes**; Vercel no cuenta. Si no se cumple, no se corrige el trabajo. Dos cuentas de AWS siguen siendo AWS y no demuestran dos nubes. | Identificar dos proveedores/plataformas de nube que sí cuenten y mostrar una función real de cada una, más su interacción en el diagrama y la demo. Confirmar con organizadores si hubiera duda sobre el segundo proveedor. | Pendiente |
| G02 | **Video de máximo 5 minutos**; si lo sobrepasa, no se revisa. | Comprobar duración final del archivo exportado: `<= 05:00`. Conviene dejar margen. | Pendiente |
| G03 | Entregar **video, repositorio de GitHub y arquitectura** vía Canvas. | Abrir enlaces/archivos finales y verificar que los tres están en Canvas. | Pendiente |
| G04 | **No colocar un informe** en la entrega; el enunciado dice que anula la participación. | Entregar solo lo solicitado. Estos dos archivos son notas de trabajo: antes de publicar el repositorio de entrega, verificar que no se incluyan ni se presenten como informe si eso pudiera interpretarse como incumplimiento. | Pendiente |
| G05 | Usar **algún servicio de AWS para proteger la data de variables globales**. | Demostrar dónde se guardan los secretos/configuración sensible, quién puede leerlos y que no están en código ni en el repositorio. Elegir el servicio tras verificar disponibilidad en AWS Academy. | Pendiente |

## Criterios puntuables (total máximo: 20)

| ID | Criterio | Máx. | Qué habría que poder mostrar | Estado | Evidencia / nota obtenida |
| --- | --- | ---: | --- | --- | --- |
| R01 | Resolver la mayor cantidad de problemas del contexto | 3 | Escenarios funcionales trazados a los dolores D01–D13 de [puntos-dolor-cliente.md](puntos-dolor-cliente.md); distinguir lo implementado de lo propuesto. | Pendiente | — |
| R02 | Persistencia y alta disponibilidad de los datos | 2 | Reportes, lecturas, estados e historial sobreviven a fallos razonables; explicar durabilidad, disponibilidad, respaldos o recuperación según los servicios elegidos. | Pendiente | — |
| R03 | Uso de Step Functions para automatización | 2 | Una máquina de estados real con disparador, pasos, decisiones, fallos y resultado visible; asociarla a un proceso útil del incidente. | Pendiente de despliegue | [Diseño v4](arquitectura-solucion-v4.md); verificar confianza de `LabRole` e `iam:PassRole`. |
| R04 | Uso de 2 nubes o más | 3 | Componentes funcionales en dos nubes que participen en el flujo; diagrama, configuración y demo. Relacionado con G01. | Pendiente de despliegue | [Diseño de AWS + GCP + Azure](arquitectura-solucion-v4.md); falta prueba real en las tres. |
| R05 | Arquitectura de la solución | 3 | Diagrama legible con flujos, servicios, datos, seguridad, escalado y frontera entre nubes; justificar decisiones de costo y disponibilidad. | Propuesta v4, sin despliegue | [HTML v4](arquitectura-solucion-v4.html), [análisis v4](arquitectura-solucion-v4.md) y [plantilla AWS v2](aws/infra/serverless.yml); falta alinear la infraestructura, validar servicios y cerrar el diagrama final. |
| R06 | Pitch de 5 minutos | 2 | Video que venda el problema, la solución, el recorrido funcional y los criterios clave dentro del tiempo. Relacionado con G02. | Pendiente | — |
| R07 | Solución completamente serverless | 2 | Todos los componentes de ejecución, también los de GCP y Azure, sin servidores administrados permanentemente por el equipo; explicar cualquier servicio discutible. | Pendiente de despliegue | [Diseño v4](arquitectura-solucion-v4.md) sin cómputo propio permanente; comprobar configuración efectiva. |
| R08 | Uso de IA en la solución | 3 | Función de IA real, invocable y útil para un dolor concreto; mostrar entrada, salida, límites y cómo encaja en el flujo. Un prompt en el pitch no constituye por sí solo una función del producto. | Pendiente de despliegue | [Gemini Developer API como asistente de verificación](arquitectura-solucion-v2.md) y [opciones gratuitas](decision-ia.md); falta llamada real y evaluación de salida. |

**Control:** máximos `3+2+2+3+3+2+2+3 = 20`. Puntuación otorgada: **aún no evaluada**. La rúbrica no da subcriterios ni garantiza puntos parciales por una evidencia determinada.

## Cobertura del problema: referencia para R01

Marcar solo cuando exista una demo verificable. Los IDs y la descripción completa están en [puntos-dolor-cliente.md](puntos-dolor-cliente.md).

| ID | Escenario a demostrar | Estado | Evidencia |
| --- | --- | --- | --- |
| D01 | Lecturas de antena y clasificación en los cuatro rangos | Pendiente | — |
| D02 | Relación entre fuentes y trazabilidad de una alerta | Pendiente | — |
| D03 | Creación de reporte en portal con todos los datos requeridos | Pendiente | — |
| D04 | Consulta, administración, cinco estados e historial | Pendiente | — |
| D05 | 10 usuarios distintos, misma zona, menos de 24 h → verificación | Pendiente | — |
| D06 | Notificación pertinente a usuarios afectados | Pendiente | — |
| D07 | Priorización explicable por impacto y criticidad de zona | Pendiente | — |
| D08 | Tendencias por zonas, antenas y tipos de problema | Pendiente | — |
| D09 | Detección de recurrencia de antena | Pendiente | — |
| D10 | Cronología que relacione reportes y métricas, con tiempo de detección | Pendiente | — |
| D11 | Ráfaga de incidentes sin pérdida de registros | Pendiente | — |
| D12 | Histórico de duración, alcance y frecuencia | Pendiente | — |
| D13 | Escalado y costo sin infraestructura siempre encendida | Pendiente | — |

## Checklist de definiciones de la solución

Las decisiones S01–S12 ya están **definidas como propuesta v1** en [puntos-dolor-cliente.md](puntos-dolor-cliente.md). Esto cierra la etapa de análisis; **ninguna está implementada todavía**. Al construir, comprobar las reglas con ejemplos y actualizar la evidencia. Los valores elegidos para la demo no proceden de la rúbrica.

| ID | Decisión definida | Definición | Implementación / prueba |
| --- | --- | --- | --- |
| S01 | Zona y mapa de cobertura antena-zona | Propuesta v1 | Pendiente |
| S02 | Servicios, síntomas y criterio de «problema relacionado» | Propuesta v1 | Pendiente |
| S03 | Hora del problema, hora de recepción y ventana móvil estricta | Propuesta v1 | Pendiente |
| S04 | Lectura por minuto, validación y telemetría ausente | Propuesta v1 | Pendiente |
| S05 | Conteo de usuarios distintos, incidente sospechado y verificación | Propuesta v1 | Pendiente |
| S06 | Estados separados, responsable e historial de transiciones | Propuesta v1 | Pendiente |
| S07 | Episodios y umbral de recurrencia de antena | Propuesta v1 | Pendiente |
| S08 | Niveles P1–P3 y justificación de prioridad | Propuesta v1 | Pendiente |
| S09 | Identidad sintética, acceso, idempotencia y privacidad | Propuesta v1 | Pendiente |
| S10 | Contacto, hitos de comunicación y deduplicación | Propuesta v1 | Pendiente |
| S11 | Carga, latencia, reintentos y retención de la demo | Propuesta v1 | Pendiente |
| S12 | Indicadores históricos y procedencia de las señales | Propuesta v1 | Pendiente |

**Arquitectura v4 propuesta:** el equipo decidió usar **AWS Academy + Google Cloud/GCP + Azure**. Existen [vista v4](arquitectura-solucion-v4.html) y [plantilla AWS v2](aws/infra/serverless.yml). Siguen pendientes las pruebas de permisos y despliegue en las tres cuentas, presupuesto/cuotas, autenticación, mensajería e IA disponibles; los puntos de la rúbrica no se consideran logrados solo por dibujar el diseño.

## Restricciones de AWS Academy que deben guiar la arquitectura

Estas son condiciones **informadas por el equipo** para su laboratorio, no puntos de la rúbrica: utilizar `LabRole`, no crear roles IAM, no depender de WAF y verificar cualquier otro servicio antes de basar en él el diseño. AWS describe Learner Lab como acceso a **servicios seleccionados**, por lo que no se debe asumir que un servicio o permiso concreto estará habilitado en esta sesión: [AWS Academy Learner Lab](https://aws.amazon.com/training/awsacademy/). Verificar también región, cuotas, presupuesto, persistencia al cerrar el laboratorio y permisos necesarios para Step Functions, IA, almacenamiento, mensajería y secretos.

## Orden de verificación sugerido al construir

1. Asegurar G01–G05; G01, G02 y G04 tienen consecuencias de descalificación/no revisión.
2. Validar servicios y permisos disponibles en las tres nubes, especialmente Step Functions y secretos en AWS Academy, Cloud Run/Gemini API en GCP y Functions/Storage en Azure.
3. Implementar un recorrido completo comprobable de reporte → detección/correlación → seguimiento/notificación → historial; registrar qué dolores cubre de verdad.
4. Probar casos de borde: `0`, `59`, `60`, `129`, `130` GB/min; 9 frente a 10 usuarios distintos; dos reportes del mismo usuario; ventana menor a 24 h; ráfaga de entradas.
5. Actualizar esta matriz con enlaces a código, capturas o marcas de tiempo del video; revisar diagrama, duración y entrega en Canvas.
