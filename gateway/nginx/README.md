# Gateway HTTP para ERP y servicios existentes

`gateway.conf` agrega las superficies reales del ERP sin retirar MS2/MS3.
La autenticación y autorización permanecen en el backend: Nginx no valida JWT
ni permite usar `X-Dev-User` para entrar al ERP.

## Verificación rápida (aislada)

Requiere Python 3 (biblioteca estándar), Docker disponible y la imagen **ya local**
`nginx:1.28-alpine`. No instala herramientas, no descarga imágenes y no recarga
Nginx compartido:

```powershell
python scripts/test_gateway.py --help
python scripts/test_gateway.py
# Alternativa PowerShell; conserva el código de salida del runner:
.\scripts\test-gateway.ps1
```

Un código `0` demuestra transporte HTTP contra upstreams simulados y sintaxis
real mediante `nginx -t`; cualquier fallo termina con código `1`. El caso negativo
comprueba un `502` con upstream caído: **no es éxito de integración**. No se
inventan endpoints health en los servicios existentes.

## Rutas públicas → upstream

| Ruta pública | Servicio / URI interna | Comportamiento |
|---|---|---|
| `/api/erp/graphql` | ERP:8081 `/graphql` | POST GraphQL; query intacta |
| `/mcp` | ERP:8081 `/mcp` | Streamable HTTP: POST/GET/DELETE, no WebSocket |
| `/api/v1/webhooks/pagofacil` | ERP:8081 misma URI | POST; mock local, no proveedor productivo certificado |
| `/api/v1/reports/export/{reporteId}/{format}` | ERP:8081 misma URI | GET PDF/XLSX; preserva URLs relativas emitidas por ERP |
| `/api/seguridad/…` | ERP:8081 misma URI completa | Alias histórico conservado; no inventa API REST ERP |
| `/api/expediente/…` | MS2:3001 misma URI completa | Sin quitar prefijo |
| `/api/agendamiento/…` | MS3:8001 misma URI completa | Sin quitar prefijo |
| `/api/erp/health`, `/actuator`, `/actuator/*` | Ninguno | 404: health público deshabilitado |
| Otras rutas | Ninguno | 404 |

El health operativo real es `/actuator/health`, accesible desde la red operativa
privada directamente al ERP. No publicar Actuator completo ni usar
`/api/seguridad/health` como prueba de salud ERP. No se habilita un alias público
health opcional: requiere una política de acceso explícita antes de agregarlo.

## Ejecutar según la topología

La fuente de verdad es el backend publicado `main`
`c6abae67109719113a2767e547ff0fce5553c740`, `application.yml` y
`application-local.yml`:

| Modo | Configuración |
|---|---|
| Nginx y ERP en el mismo host | `erp_backend` apunta a `127.0.0.1:8081`; establecer **`ERP_PORT=8081`**, también con perfil `local` |
| ERP sin perfil local | El puerto predeterminado ya es 8081 |
| Perfil `local` sin override | El backend usa **8080**: no coincide con este gateway hasta establecer `ERP_PORT=8081` o ajustar upstream |
| Nginx y servicios en contenedores | Cambiar los tres destinos a nombres DNS reales de servicios en la misma red Docker y sus puertos internos; `127.0.0.1` es el propio contenedor Nginx |
| Nginx contenedor, ERP en host | Usar `host.docker.internal:8081`; en Linux puede requerir el mapeo `host-gateway` |

El runner usa servidores HTTP falsos en puertos efímeros del host y reemplaza
los destinos solamente en una copia temporal `.gateway-test-*` dentro del repositorio
(excluida de Git y eliminada al terminar). Publica Nginx en un puerto aleatorio
**de loopback**, usa `--pull=never` y elimina sus contenedores y temporales incluso
si falla. Los falsos upstreams escuchan en interfaces del host para permitir
acceso desde Docker; ejecutarlo solamente en una estación de pruebas confiable.

### Incluir la configuración

`gateway.conf` contiene `upstream`, `map` y `server`: incluirlo **dentro de
`http {}`**, nunca dentro de otro `server`. Deshabilitar el servidor de ejemplo
que compita por el mismo puerto. Ejemplo Windows (ajustar ruta real):

```nginx
http {
    include mime.types;
    default_type application/octet-stream;
    include C:/proyectos/platform-infrastructure/gateway/nginx/gateway.conf;
}
```

Validar en la instancia operativa con `nginx -t` antes de cualquier cambio.
Iniciar/recargar servicios compartidos requiere autorización separada; el runner
no lo hace. Nginx no interpola automáticamente variables de entorno en este
archivo: ajustar upstreams y allowlist en la configuración de cada entorno.

## Frontera CORS y autenticación

- Allowlist inicial explícita: `http://localhost:4201`. Cambiar el `map` para
  orígenes reales aprobados (esquema, host y puerto exactos); no usar `*`.
- OPTIONS válido se responde localmente con 204. Origen, método o cabeceras no
  permitidos producen 403 sin autorización CORS; no alcanzan el backend.
- Métodos permitidos: GET, POST, DELETE, OPTIONS. Cabeceras permitidas:
  `Authorization`, `Content-Type`, `Accept`, `Idempotency-Key`, `Mcp-Session-Id`,
  `MCP-Protocol-Version`, `Last-Event-ID` (reanudación SSE) y `X-Correlation-ID`
  (solo transporte). Se exponen `Mcp-Session-Id`, `Content-Disposition` e
  `Idempotency-Replayed`; esto no demuestra replay ni reanudación en el backend.
- El gateway suprime los `Access-Control-*` habituales del upstream para evitar
  duplicados y agrega `Vary: Origin`. No habilita credenciales CORS.
  `ERP_CORS_ALLOWED_ORIGINS` es la variable real del backend; para tráfico directo
  requiere su propia política explícita. Nginx es la autoridad CORS en su frontera.
- CORS no autentica ni bloquea clientes no navegador. Un origen no permitido no
  recibe cabeceras CORS; las solicitudes normales siguen llegando al ERP, que
  debe validar JWT y roles. Respuestas 401/403/500 no se convierten en éxito.
- `X-Dev-User` se elimina de **todas** las rutas que alcanzan ERP, incluido
  `/api/seguridad/`. No usar `dev-mode` ni otro bypass para integrar servicios.
  Restringir también acceso directo al puerto ERP fuera de la red autorizada.
- Nginx reenvía por defecto Authorization, Idempotency-Key y cabeceras MCP;
  no necesitan una directiva por cabecera. `X-Correlation-Id` se transporta si
  el cliente lo envía: no se genera, valida, devuelve ni atribuye soporte al ERP.

## Streaming, descargas y límites de lo demostrado

`proxy_buffering off`, caché deshabilitada y HTTP/1.1 permiten eventos SSE sin
esperar al final. `proxy_read_timeout 300s` mide inactividad **entre lecturas**,
no un deadline total. Un stream puede durar más si sigue enviando datos; ajustar
el intervalo a la política operativa, sin atribuir fallos no reproducidos al
valor predeterminado de Nginx. No se configura Upgrade/WebSocket.

Las pruebas verifican método, URI, query, body y cabeceras en cada ruta; preservan
las tres rutas históricas; comprueban bytes y cabeceras PDF/XLSX, preflight,
supresión CORS, eliminación de bypass dev, errores, 404 y 502. Un primer evento
SSE debe llegar antes de que termine el upstream. La política de timeout se
explica por su semántica, no se espera 300 segundos en la prueba.

Para RED con configuración previa externa, sin leer historial Git:

```powershell
python scripts/test_gateway.py --baseline-config C:/temporal/gateway-anterior.conf
python scripts/test_gateway.py --baseline-config C:/temporal/gateway-anterior.conf --legacy-only
python scripts/test_gateway.py --legacy-only
```

El diferencial legacy verifica el mismo contrato exacto antes/después; solamente
la retirada intencional de `X-Dev-User` en MS1 difiere. No reduce las pruebas para
que una configuración antigua obtenga GREEN completo.

Pendiente de E2E autorizado: JWT firmado/issuer/roles con Keycloak, GraphQL real,
negociación y sesión MCP reales, deduplicación persistida y webhook mock ERP.
Estos tests **no certifican** esas capacidades ni PagoFácil productivo; tampoco
validan contratos de eventos o conectividad a datos reales.
