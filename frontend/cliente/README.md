# Portal de servicio · Red TeleCorp

Aplicación React + TypeScript + Vite para **clientes y operadores**. Comparte un inicio de sesión; el rol `CUSTOMER` muestra el portal de clientes y `OPERATOR` abre el centro de operaciones. Ambos consultan directamente la API HTTP de AWS. Azure ofrece una página pública independiente. No hay datos simulados en las vistas ni JWT persistidos en el navegador.

## Desarrollo local

Requiere Node.js 22.12+ y npm.

```bash
cd frontend/cliente
cp .env.example .env
npm ci
npm run dev
npm run build
```

En PowerShell, usa `Copy-Item .env.example .env`. El archivo `.env` es opcional: el código ya tiene las URLs públicas de `dev` como respaldo. La compilación sale en `dist/`.

## Flujos de clientes

| Vista | Ruta AWS | Función |
| --- | --- | --- |
| Acceso | `POST /auth/login` | JWT de 15 minutos en memoria. |
| Nuevo reporte | `GET /zonas`, `POST /reportes` | Envía la solicitud con `Idempotency-Key`; el formulario exige zona, referencia y fecha válida. |
| Mis reportes | `GET /reportes?limit=12&cursor=…` | Lista solo los propios, con paginación. |
| Detalle | `GET /reportes/{id}` | Muestra estado e historial. |
| Estado de zona | `GET /incidentes?zone_id=…&limit=20&cursor=…` | Vista pública del incidente, sin exponer el detalle operacional. |

## Flujos de operadores

| Vista | Ruta AWS | Función |
| --- | --- | --- |
| Bandeja | `GET /incidentes?status=…&zone_id=…&limit=20&cursor=…` | Filtra por estado y zona; muestra la prioridad y el impacto que devuelve AWS. Los contadores indican solo las páginas cargadas. |
| Incidente | `GET /incidentes/{id}` | Evidencia colectiva y técnica, antenas relacionadas, recuperación e historial. Un incidente puede nacer de reportes aun sin antena vinculada. |
| Decisión sobre incidente | `PATCH /incidentes/{id}/estado` | Solo transiciones permitidas. Exige un motivo y una revisión antes de confirmar; 409 actualiza el detalle para resolver un cambio concurrente. |
| Reportes por zona | `GET /reportes?zone_id=…&limit=20&cursor=…` | Muestra reportes de la zona, sin afirmar que todos pertenezcan al mismo incidente. También permite abrir un ID completo. |
| Reporte individual | `GET /reportes/{id}`, `PATCH /reportes/{id}/estado` | Consulta historial y cambia estado con motivo y confirmación. Solo muestra la terminación del número de servicio. |
| Tendencias | `GET /tendencias?days=7\|30` | Zonas, antenas, tipos de problemas, recurrencia y tiempo de detección. Se consulta al abrir la vista o al cambiar de periodo. |
| Apoyo de IA | `GET /incidentes/{id}/sugerencia` | Se solicita expresamente desde el detalle. Si GCP no responde, `available:false` se presenta sin bloquear el trabajo. La IA no decide el estado. |

Los errores de red, CORS, permisos, respuesta inválida y fallos de backend aparecen en su vista con opción de reintentar. Un HTTP 404 del recurso se distingue de una función todavía no disponible. Si el JWT expira, se vuelve al acceso.

## Publicación en Amplify Hosting

El [`amplify.yml`](../../amplify.yml) de la raíz construye `frontend/cliente` como aplicación de monorepo con Node.js 22, `npm ci`, `npm run build` y `dist/` como artefacto. **Clientes y operadores se publican en la misma aplicación Amplify.** El frontend no despliega recursos de backend ni crea roles IAM.

1. Conecta Amplify Hosting al repositorio `DiegoLadrondeGuevara/hackathon-2026` y selecciona la rama que contiene este módulo. Al integrarse en `main`, selecciona `main`.
2. Marca **My app is a monorepo**, fija `frontend/cliente` como ruta y comprueba `AMPLIFY_MONOREPO_APP_ROOT=frontend/cliente`.
3. En **Environment variables**, configura:

   | Variable | Valor |
   | --- | --- |
   | `VITE_API_BASE_URL` | `https://ynyvt8x51k.execute-api.us-east-1.amazonaws.com` |
   | `VITE_AZURE_STATUS_URL` | `https://mango-ground-073e60210.3.azurestaticapps.net` |

4. Despliega y comprueba acceso de ambos roles, CORS desde el dominio final, detalles, paginación y vencimiento de sesión.
5. Si se usarán rutas SPA profundas, configura una reescritura 200 a `/index.html` para rutas sin extensión. La versión actual navega sin cambiar la URL, así que no depende de esa regla.

Los valores `VITE_` son públicos en el JavaScript generado. **No coloques** contraseña de demo, JWT, claves de AWS, Azure o Grafana en las variables del frontend. El login utiliza directamente el backend.

**Cloudflare sigue pendiente.** Se integrará cuando haya un dominio propio y una URL de Amplify activa. El proxy podrá observar el tráfico del portal, mientras que las llamadas directas del navegador a `execute-api` no atravesarán ese proxy. Las respuestas privadas no deben quedar en caché.

## Verificación y límites

- `npm run build` pasó el 15/11/2026.
- Con el operador de demo se verificaron en navegador el login, la bandeja por estado, un incidente con historial, la lista y detalle de reportes por zona y las tendencias de 7 días. El API respondió con datos reales, incluidas antenas recurrentes.
- Se revisaron las vistas móvil y de escritorio. La pantalla de acceso móvil se ajustó para separar marca y formulario.
- No se ejecutaron `PATCH` ni se solicitó una sugerencia de IA durante esta revisión para no modificar los casos de la demo ni generar consumo externo. Esas rutas están integradas y deben probarse de extremo a extremo con un caso desechable del equipo.
- El backend no ofrece por ahora una lista de IDs de reportes vinculados a un incidente; el portal solo muestra el conteo confirmado por AWS y la lista zonal por separado. Tampoco ofrece un total global de la bandeja, por eso los indicadores describen las páginas cargadas.
- La aplicación Amplify y Cloudflare todavía requieren publicación y validación desde sus dominios finales.

Para el contexto general y los estados de negocio, consulta el [README principal](../../README.md).
