# Tareas para el agente

## Cómo se usa
Cada persona abre Claude Code en la raíz del repo y pega el prompt de arranque con el ID de la tarea. Una tarea por rama (`feat/T07`).
Plan de 5 líneas, aprobación, implementación con pruebas, `python -m pytest` y `ruff check src tests` en verde (dentro de `aws/`), commit.

Prompt de arranque:
> Lee `CLAUDE.md` y todo `contracts/`. Tarea **T07** de `docs/AGENT_TASKS.md`. Primero propón un plan de 5 líneas y espera mi OK. Luego implementa con pruebas en moto y deja `python -m pytest` y `ruff check src tests` en verde (dentro de `aws/`).

## Definición de terminado
- Cumple el contrato (`flows.md`, `api.md`, `events.md`) y usa `common/`.
- Pruebas con moto: caso feliz, entrada inválida, reintento duplicado (idempotencia) y, en cada transición, la transición prohibida.
- Sin datos personales en logs. Sin `float`. Sin dependencias nuevas.

## Pasos y tareas
| ID | Paso | Entregable | Prueba mínima |
|---|---|---|---|
| T01 | S0 | `scripts/seed.py` (idempotente): 12 zonas, 30 antenas, 1 operador y 20 clientes ficticios | Corre dos veces sin duplicar; las zonas salen por `GSI1-type` |
| T02 | S1 | `common/auth.py`: hash scrypt, verificación, JWT HS256 con `hmac` | Token vencido, firma alterada y `alg=none` se rechazan |
| T03 | S1 | `autenticar_usuario`, `autorizar_jwt` | Login correcto e incorrecto; autorizador devuelve `sub` y `role` |
| T04 | S1 | `listar_zonas`, `crear_reporte` | Transacción META + HIST + Outbox; `Idempotency-Key` repetido devuelve 200 |
| T05 | S1 | `listar_mis_reportes`, `obtener_reporte`, `cambiar_estado_reporte` | Dueño vs. ajeno; transición inválida da 409 |
| T06 | S1 | `enrutadora_de_outbox` | Solo INSERT; entradas fallidas de `PutEvents` lanzan error |
| T07 | S2 | `correlacionadora_de_reportes` | 9 usuarios no crean incidente; el 10.º sí; duplicado no repite; carrera con puntero existente vincula |
| T08 | S2 | `verificadora_de_evidencias`, `calculadora_de_prioridad`, `alertadora_de_operaciones` | Auto-CONFIRMADO con evidencia técnica; `alert` correcto; conflicto de versión reintenta |
| T09 | S2 | `listar_incidentes_zona`, `cambiar_estado_incidente` | Vista pública vs. operador; CERRADO borra el puntero y fija duración |
| T10 | S3 | `generadora_de_metricas_y_lotes`, `clasificadora_de_metricas` | Escenario apaga una antena: abre episodio; 5 normales lo cierran; 3 episodios en 7 días emiten recurrencia |
| T11 | S3 | `correlacionadora_de_anomalias` | Casos: sin incidente, uno de reportes, dos o más (revisión), existe ANY |
| T12 | S4 | `notificadora_de_clientes` | Intención única por cliente e hito; sin consentimiento da SKIPPED; fallo reintenta hasta 3 |
| T13 | S5/S6 | `publicadora_hacia_gcp`, `publicadora_hacia_azure` | Sin `customer_id` en la carga; hash estable |
| T14 | S5 | `obtener_sugerencia_ia`, `obtener_tendencias` | Falla de GCP devuelve `{"available":false}`; tendencias cuentan bien con datos de prueba |
| T15 | S7 | `scripts/scenario.py` (activar y limpiar escenario de antenas) y `scripts/load_test.py` (N reportes de una zona) | Documentar el uso en el encabezado del script |
| T16 | S5/S6 | `gcp/` (Cloud Run: `/ingest`, `/suggest`) y `azure/` (Functions: `/api/estado`) con su propio `requirements.txt` | Pruebas unitarias sin llamar a la nube |

Infraestructura (`aws/serverless.yml`, `aws/infra/`) y `scripts/bootstrap_ssm.py` ya están hechos. Cada handler existe como esqueleto: se reemplaza el archivo.
T01 necesita el hash de contraseñas de T02: hacer T02 antes.

Orden sugerido: T02, T01, T03 a T06 (S0 y S1), T07 a T09 (S2), T10 y T11 (S3), T12 (S4), T13, T14 y T16 (S5/S6), T15 (S7).

## Semilla de T01
Zonas (criticidad según tipo): Z01 Miraflores RESIDENCIAL, Z02 San Isidro CRITICA, Z03 Santiago de Surco RESIDENCIAL, Z04 San Borja RESIDENCIAL, Z05 La Molina EDUCATIVA, Z06 Callao INDUSTRIAL, Z07 Ate INDUSTRIAL, Z08 San Miguel EDUCATIVA, Z09 Jesús María MEDICA, Z10 San Juan de Lurigancho RESIDENCIAL, Z11 Villa El Salvador INDUSTRIAL, Z12 Barranco EDUCATIVA.
Antenas `A001` a `A030`: tres en cada una de Z01 a Z06 y dos en cada una de Z07 a Z12. `nominal_gb` 95.
Contraseñas de demo: se leen de una variable de entorno, no del código.

## Lo que no se delega
Decisiones de arquitectura, cambios al contrato y la explicación del paso en el video. Cada integrante tiene que poder defender las piezas que su agente construyó.
