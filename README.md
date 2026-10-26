# Platform Infrastructure — AI-Dentist

Configuración del gateway, identidad y contratos de integración. La adaptación
ERP conserva las rutas, el realm y la topología históricos de MS2/MS3. Los
artefactos preparados y las pruebas con upstreams simulados **no acreditan una
integración extremo a extremo con servicios desplegados**.

## Referencias verificadas

| Repositorio | `main` publicado consultado |
|---|---|
| platform-infrastructure (base de esta adaptación) | `3357d56fe890d789efcd7382caf7ca3b8b614990` |
| ms-erp (solo consulta) | `c6abae67109719113a2767e547ff0fce5553c740` |

El ERP publicado es la fuente de verdad: no se le agregan endpoints REST para
satisfacer propuestas antiguas. Para actualizar contratos, volver a comprobar el
`main` publicado y sincronizar SDL/introspección juntos.

## Mapa de ejecución

| Componente | Puerto local | Contrato / modo |
|---|---|---|
| Nginx | `80` | [Configuración y tabla completa de rutas](gateway/nginx/README.md) |
| MS1 ERP | `8081` | `ERP_PORT=8081`; sin override, perfil `local` usa `8080` |
| MS2 Expediente | `3001` | `/api/expediente/`, URI completa preservada |
| MS3 Agendamiento | `8001` | `/api/agendamiento/`, URI completa preservada |
| Keycloak ERP | `8180` | Realm `dental-platform`, roles sin prefijo `ROLE_` |
| Keycloak legacy | `8080` previsto | Realm `odontoclinic-realm` conservado, no migrado |
| RabbitMQ | `5672` / `15672` | Topologías declarativas separadas; no aprovisionado aquí |
| MCP clínico propuesto MS2 | `3100` previsto | Distinto del MCP ERP `/mcp` |

### Rutas ERP

| Pública | Backend ERP |
|---|---|
| `POST /api/erp/graphql` | `POST /graphql` |
| `/mcp` (POST/GET/DELETE) | `/mcp` — Streamable HTTP autenticado |
| `POST /api/v1/webhooks/pagofacil` | Misma URI — **mock local**, secreto propio |
| `GET /api/v1/reports/export/{reporteId}/{format}` | Misma URI — PDF/XLSX, autorización ERP |
| `/api/seguridad/…` | Misma URI — alias legacy, no implementa login ni health ERP |

Las otras rutas devuelven 404, incluidos `/graphql` directo y Actuator. El health
operativo real es `/actuator/health`, solo por la red privada al ERP. No se expone
Actuator completo. En contenedores, sustituir loopback por DNS real del servicio;
`127.0.0.1` no representa a otro contenedor.

## Configuración necesaria

1. Incluir `gateway/nginx/gateway.conf` dentro de `http {}` y ajustar upstreams y
   allowlist de orígenes del entorno. No hay interpolación automática de variables
   del shell en ese archivo. Origen local preparado: `http://localhost:4201`.
2. Fijar `ERP_PORT=8081`. La cadena JWT normal usa
   `KEYCLOAK_ISSUER_URI`; la cadena Bearer del perfil local usa
   `ERP_LOCAL_JWT_ISSUER_URI`. Issuer local ERP:
   `http://localhost:8180/realms/dental-platform`. Claim `iss`, discovery y
   configuración deben coincidir y ser alcanzables desde sus consumidores.
3. Preparar identidad según [identity/keycloak/README.md](identity/keycloak/README.md).
   No se renombra ni elimina el realm legacy. El ejemplo ERP no incluye usuarios
   ni secretos. No usar perfiles de bypass ni `X-Dev-User` como solución.
4. Configurar `ERP_DB_URL`, `ERP_DB_USER`, `ERP_DB_PASSWORD` y conectividad RabbitMQ
   con los nombres reales descritos en [messaging/rabbitmq/README.md](messaging/rabbitmq/README.md).
   No guardar secretos en Git. El broker ERP usa `/` por defecto; no mezclarlo
   silenciosamente con `/odontoclinic`.
5. Desactivar integraciones no autorizadas: `N8N_ENABLED=false`; no ejecutar
   operaciones de IA ni proveedores reales durante estas comprobaciones. El
   webhook solo documenta el flujo mock; no habilita PagoFácil productivo.

Nginx gestiona CORS de su frontera y transporta `Authorization`,
`Idempotency-Key` y cabeceras MCP. El backend sigue validando JWT, roles y reglas
de negocio. `ERP_CORS_ALLOWED_ORIGINS` gobierna el acceso directo al ERP; su
allowlist debe ser coherente si se habilita ese acceso. La cabecera de desarrollo
se elimina al pasar por Nginx. Restringir el puerto directo del ERP por red.

## Contratos

| Superficie | Fuente / estado |
|---|---|
| [GraphQL ERP](contracts/graphql/README.md) | SDL e introspección canónicos, revisión y SHA-256 en `source.json`; cuatro ejemplos reales |
| [REST MS1 histórico](contracts/rest/ms1-seguridad.yaml) | **Obsoleto, no implementado por ms-erp**; login es responsabilidad de Keycloak |
| [REST MS2](contracts/rest/ms2-clinico.yaml) / [REST MS3](contracts/rest/ms3-agendamiento.yaml) | Conservados sin cambios |
| [Eventos ERP](contracts/events/README.md) | Consulta finalizada plana; seis eventos `catalogo.*` sin envelope inventado |
| [RabbitMQ ERP](messaging/rabbitmq/topology-erp.json) | Topología adicional, sin alterar `topology.json` legacy |

El ERP reconoce **`Idempotency-Key`**, no `X-Idempotency-Key`; no existe input
GraphQL `idempotencyKey`. La convención anterior de otros servicios no se cambia.
MCP ERP usa Streamable HTTP/SSE, no WebSocket y no el servidor clínico MS2.

## Verificación reproducible y límites

Requiere Python 3, Docker activo y `nginx:1.28-alpine` **ya local**. Estos scripts
no instalan herramientas ni descargan imágenes. No reinician servicios compartidos.

```powershell
python -B scripts/test_gateway.py
python -B -m unittest discover -s scripts/tests -v
.\scripts\test-gateway.ps1
```

El runner valida `nginx -t` real y usa upstreams sintéticos aislados: comprueba
URI, query, método, body, cabeceras, rutas antiguas, CORS, streaming, descargas y
fallos. Un 502 es un caso negativo, nunca éxito de integración. Los puertos del
gateway son efímeros de loopback. Los mocks solo contienen datos sintéticos; no
exponerlos fuera de una estación confiable. La verificación estructural de
GraphQL/identidad/eventos no reemplaza servicios reales.

Pendiente de una prueba E2E **autorizada**, sin datos ni cobros reales:
- JWT firmado, issuer/roles, PKCE y vínculo de auditoría con Keycloak/BD.
- GraphQL con resolvers reales, deduplicación persistida y negociación/sesión MCP.
- Webhook mock ERP y propiedad/autorización de exportaciones reales.
- Productor MS2, referencias compartidas, bindings, DLQ y consumidores `catalogo.*`.

No se instaló ni desplegó RabbitMQ/Keycloak en este trabajo. Los productores y
consumidores ajenos deben acordarse antes de conectar el envelope histórico al
consumidor plano ERP. El backend publicado no valida audiencia JWT: el mapper
`ms-erp` del realm no reemplaza ese control. Push, PR, merge y cualquier despliegue
requieren autorización posterior.
