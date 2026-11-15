# Portal de clientes · Red TeleCorp

Primera versión React + TypeScript + Vite del portal autenticado de clientes. Usa la API HTTP de AWS; no guarda datos de prueba ni simula respuestas exitosas. La página pública de Azure se abre mediante un enlace separado.

## Ejecutar en local

Requiere Node.js 20.19+ o 22.12+ y npm.

```bash
cd frontend/cliente
cp .env.example .env
npm ci
npm run dev
```

En PowerShell, usa `Copy-Item .env.example .env`. El valor de `VITE_API_BASE_URL` es una URL pública, no una clave. Si no creas `.env`, se usa la URL de `dev` indicada en [`.env.example`](.env.example). Para comprobar la compilación: `npm run build`; el resultado queda en `dist/`.

## Funciones y rutas utilizadas

| Vista | Método y ruta AWS | Uso |
| --- | --- | --- |
| Acceso | `POST /auth/login` | Inicia una sesión `CUSTOMER` con JWT de 15 minutos. El token vive solo en memoria. |
| Nuevo reporte | `GET /zonas`, `POST /reportes` | Consulta zonas, valida campos y envía `Idempotency-Key` para evitar duplicados en reintentos. |
| Mis reportes | `GET /reportes?limit=12&cursor=…` | Lista únicamente los reportes del cliente; carga más páginas bajo demanda. |
| Detalle | `GET /reportes/{report_id}` | Muestra información e historial real de estados. |
| Estado de zona | `GET /incidentes?zone_id=…&limit=20&cursor=…` | Muestra la vista pública de incidentes y permite seguir el cursor aunque una página esté vacía. |

Los errores de red, CORS, respuesta inválida, permisos y fallo del servidor se muestran en la vista correspondiente con una opción para reintentar cuando aplica. No se interpreta un HTTP 404 de un reporte como prueba de que el endpoint completo falta.

## Publicar en Amplify Hosting

Conecta la rama del repositorio en Amplify Hosting y configura la raíz de la aplicación como `frontend/cliente`. Usa `npm ci` para instalar, `npm run build` para compilar y `dist` como directorio de artefactos. Agrega la variable de compilación `VITE_API_BASE_URL=https://ynyvt8x51k.execute-api.us-east-1.amazonaws.com` y una regla de reescritura SPA `/<*>` → `/index.html` con código `200`. La variable `VITE_` queda expuesta en el navegador; nunca pongas JWT ni secretos allí. Antes de publicar, prueba el CORS de API Gateway desde el dominio de Amplify.

## Verificación

- El build local pasó. Se revisó visualmente la pantalla de acceso en escritorio y móvil, y el inicio, detalle e ingreso al formulario en una sesión autenticada de escritorio.
- Con la cuenta ficticia `CUSTOMER` de la semilla, el login, `GET /zonas`, `GET /reportes`, `GET /reportes/{id}` y `GET /incidentes?zone_id=Z01` respondieron HTTP 200 el 15/11/2026. La respuesta incluyó 12 zonas y el detalle de un reporte con historial. La contraseña de demo se distribuye fuera de este repositorio.
- Las solicitudes `OPTIONS` de `/auth/login` y `/reportes` desde `http://localhost:5173` respondieron 204 y autorizaron `authorization,content-type,idempotency-key`. Debe repetirse desde el dominio definitivo de Amplify.
- El historial de un reporte se mostró en el navegador autenticado. Falta probar la creación de reportes, la paginación y el vencimiento de sesión desde el navegador. No se creó un reporte de prueba en la API durante esta verificación.
- No existe todavía una aplicación Amplify para este portal. El portal de operadores es una fase posterior y no está incluido aquí.
- El backend actual acepta `location_text` vacío, aunque el caso pide localización aproximada; este formulario la exige. AWS debe alinear la validación del servidor. El backend tampoco comprueba aún que `service_number` pertenezca al usuario autenticado.

Para el contexto general y despliegue del backend, consulta el [`README.md` principal](../../README.md).
