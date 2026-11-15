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

El [`amplify.yml`](../../amplify.yml) de la raíz ya define `frontend/cliente` como aplicación de monorepo, Node.js 22, `npm ci`, `npm run build` y `dist/` como artefacto. No despliega infraestructura backend ni crea roles IAM.

1. En Amplify Hosting, crea una aplicación conectada a GitHub y selecciona `DiegoLadrondeGuevara/hackathon-2026`. Selecciona la rama `codex/frontend-cliente-v1` mientras el portal siga allí; si el equipo la incorpora a `main`, selecciona `main`.
2. Marca **My app is a monorepo** y escribe `frontend/cliente` como ruta de la aplicación. Amplify debe mostrar `AMPLIFY_MONOREPO_APP_ROOT=frontend/cliente`; si la aplicación ya existía, agrégala manualmente con ese valor.
3. Usa la imagen de compilación predeterminada **Amazon Linux 2023** y deja que tome el `amplify.yml` del repositorio. En **Environment variables**, agrega:

   | Variable | Valor |
   | --- | --- |
   | `VITE_API_BASE_URL` | `https://ynyvt8x51k.execute-api.us-east-1.amazonaws.com` |
   | `VITE_AZURE_STATUS_URL` | `https://mango-ground-073e60210.3.azurestaticapps.net` |

4. Guarda y despliega. El build debe terminar con `dist/index.html` y los archivos de `dist/assets/`.
5. En **Hosting → Rewrites and redirects**, añade una regla `200` a `/index.html` para rutas SPA. Para no convertir archivos estáticos ausentes en HTML, usa como *source* la expresión recomendada por AWS: `</^[^.]+$|\.(?!(css|gif|ico|jpg|js|png|txt|svg|woff|woff2|ttf|map|json|webp)$)([^.]+$)/>`.
6. Abre la URL `*.amplifyapp.com` de esa rama. Comprueba acceso con un cliente ficticio, zonas, reportes, detalle y estado de zona. Después prueba crear un reporte sintético y verifica que aparezca una sola vez. Comprueba CORS desde el dominio final y el vencimiento del JWT.

`VITE_` significa que ambos valores quedan visibles en el JavaScript del navegador; son URLs públicas. No agregues `SEED_DEMO_PASSWORD`, JWT, claves de Azure/Grafana ni credenciales AWS como variables del frontend. La contraseña de demo se comparte fuera del repositorio.

**Cloudflare: pendiente.** Primero necesitamos la URL de Amplify funcionando y un dominio propio. Luego se añade el dominio a Amplify, se conserva el CNAME de validación ACM como **DNS only**, se verifica HTTPS y recién después se evalúa el proxy de Cloudflare para el CNAME del portal con TLS **Full (strict)**. Probaremos las métricas de solicitudes y caché sin almacenar respuestas privadas. Cloudflare delante del portal observará el tráfico del sitio; las llamadas del navegador directamente a `execute-api` seguirán fuera de ese proxy.

Referencias: [monorepos en Amplify](https://docs.aws.amazon.com/amplify/latest/userguide/monorepo-configuration.html), [rewrites de SPA](https://docs.aws.amazon.com/amplify/latest/userguide/redirect-rewrite-examples.html), [dominio externo en Amplify](https://docs.aws.amazon.com/amplify/latest/userguide/to-add-a-custom-domain-managed-by-a-third-party-dns-provider.html), [proxy DNS de Cloudflare](https://developers.cloudflare.com/dns/proxy-status/).

## Verificación

- El build local pasó. Se revisó visualmente la pantalla de acceso en escritorio y móvil, y el inicio, detalle e ingreso al formulario en una sesión autenticada de escritorio.
- Con la cuenta ficticia `CUSTOMER` de la semilla, el login, `GET /zonas`, `GET /reportes`, `GET /reportes/{id}` y `GET /incidentes?zone_id=Z01` respondieron HTTP 200 el 15/11/2026. La respuesta incluyó 12 zonas y el detalle de un reporte con historial. La contraseña de demo se distribuye fuera de este repositorio.
- Las solicitudes `OPTIONS` de `/auth/login` y `/reportes` desde `http://localhost:5173` respondieron 204 y autorizaron `authorization,content-type,idempotency-key`. Debe repetirse desde el dominio definitivo de Amplify.
- El historial de un reporte se mostró en el navegador autenticado. Falta probar la creación de reportes, la paginación y el vencimiento de sesión desde el navegador. No se creó un reporte de prueba en la API durante esta verificación.
- No existe todavía una aplicación Amplify para este portal; la configuración de compilación ya está lista en el repositorio. El portal de operadores es una fase posterior y no está incluido aquí. Cloudflare también sigue pendiente.
- El backend actual acepta `location_text` vacío, aunque el caso pide localización aproximada; este formulario la exige. AWS debe alinear la validación del servidor. El backend tampoco comprueba aún que `service_number` pertenezca al usuario autenticado.

Para el contexto general y despliegue del backend, consulta el [`README.md` principal](../../README.md).
