# Convenciones de Contratos, Integración y Arquitectura de APIs

Este documento define los estándares arquitectónicos obligatorios para la comunicación síncrona entre clientes (microfrontends / frontend web), el API Gateway (Nginx) y los microservicios del sistema médico-odontológico:
- **MS1 - Seguridad y ERP/Finanzas** (Spring Boot + PostgreSQL - Dennis): REST preliminar para seguridad y GraphQL para ERP.
- **MS2 - Expediente Clínico Odontológico e IA** (NestJS + MongoDB - Henry): API REST.
- **MS3 - Agendamiento, Citas y Stock** (Laravel + DynamoDB - Wendy): API REST.

---

## 1. Convención Unificada de Identificadores

En un ecosistema distribuido con bases de datos heterogéneas (PostgreSQL relacional en MS1, MongoDB documental en MS2 y DynamoDB clave-valor en MS3), los identificadores autonuméricos incrementales (`1, 2, 3`) generan colisiones entre dominios y exponen vulnerabilidades de enumeración.

### Reglas para IDs de Recursos:
1. **Identificadores Canónicos de Entidades:**
   - **Formato obligatorio:** **UUID v4** en formato canónico de 36 caracteres minúsculos con guiones (ejemplo: `f47ac10b-58cc-4372-a567-0e02b2c3d479`).
   - Todo recurso público expuesto en endpoints REST (`pacienteId`, `odontologoId`, `citaId`, `expedienteId`, `consultaId`, `recetaId`, `insumoId`) o en tipos GraphQL (`id: ID!`) debe utilizar UUID v4.
2. **Identificadores de Dominio Legibles:**
   - Para seguimiento de turnos y citas: `CIT-YYYY-XXXXXX` (ejemplo: `CIT-2026-000452`).
   - Para Número de Historia Clínica Odontológica: `HCO-YYYY-XXXXX` (ejemplo: `HCO-2026-00012`).
   - Para Facturas y Órdenes de Compra: `FAC-YYYY-XXXXXX` / `OC-YYYY-XXXXXX`.
   - Estos códigos legibles son atributos de búsqueda y presentación comercial, pero el identificador de referencia en las URLs y mutaciones siempre es el UUID v4.

---

## 2. Encabezados HTTP Comunes (Cross-Cutting Headers)

Para garantizar trazabilidad distribuida, seguridad e idempotencia a través del API Gateway (Nginx):

| Encabezado HTTP | Tipo | Presencia | Propósito |
|---|---|---|---|
| `X-Correlation-ID` | UUID v4 | **Obligatorio** en todas las peticiones | Identificador único de trazabilidad extremo a extremo. Generado por el cliente frontend o inyectado por el Gateway si no viene presente. Debe propagarse en logs y eventos asíncronos. |
| `X-Idempotency-Key` | UUID v4 | **Obligatorio** en `POST` de mutación crítica | Clave de deduplicación contra reintentos por fallas de red. Unifica el estándar en todos los microservicios. |
| `Authorization` | `Bearer <JWT>` | Obligatorio en rutas autenticadas | Token de acceso JWT con firma criptográfica y claims de usuario/rol. |
| `X-User-ID` | UUID v4 | Inyectado o propagado | Identificador único del usuario autenticado. |
| `Content-Type` | MIME | Obligatorio en requests con body | `application/json` en REST, `application/problem+json` en errores REST, `application/json` en GraphQL. |

---

## 3. Convenciones de Idempotencia (`X-Idempotency-Key`)

En arquitecturas distribuidas sobre redes no confiables, los clientes pueden reintentar solicitudes de creación tras timeouts, arriesgando duplicidad de datos sensibles (duplicar una reserva de turno, emitir dos veces una factura o registrar doble atención).

### Principios Operativos:
1. **Métodos Idempotentes por Estándar HTTP:**
   - `GET`, `HEAD`, `OPTIONS`: No deben alterar estado (seguros e idempotentes).
   - `PUT`: Idempotente por diseño (reemplazo íntegro del recurso).
   - `DELETE`: Idempotente por diseño (el resultado final tras una o varias ejecuciones es el mismo: recurso eliminado).
2. **Idempotencia en Operaciones `POST` y Mutaciones:**
   - El cliente genera un UUID v4 único para la acción y lo envía en el encabezado `X-Idempotency-Key` (ejemplo: `X-Idempotency-Key: 9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d`).
   - Endpoints REST críticos obligados:
     - `POST /api/agendamiento/citas`
     - `POST /api/agendamiento/stock/movimientos`
     - `POST /api/expediente/consultas`
     - `POST /api/expediente/recetas`
     - `POST /api/expediente/planes-tratamiento`
     - `POST /api/seguridad/usuarios`
   - En GraphQL, las mutaciones aceptan la clave tanto en el encabezado HTTP `X-Idempotency-Key` como en el campo `idempotencyKey: String!` de los Inputs.
   - El microservicio almacena la clave en cache o base de datos con un TTL de 24 horas junto con la respuesta procesada. Si llega una petición con la misma clave dentro del TTL, se devuelve la respuesta en caché sin reprocesar.

---

## 4. Estándar de Errores: REST (RFC 7807) vs GraphQL

El sistema adopta dos enfoques diferenciados según el protocolo de transporte, manteniendo compatibilidad conceptual:

### A. Formato de Error en REST (RFC 7807 - Problem Details)
Todas las APIs REST (`/api/seguridad`, `/api/expediente`, `/api/agendamiento`) retornan errores bajo el estándar RFC 7807 con Content-Type `application/problem+json` y el código de estado HTTP adecuado (4xx, 5xx):

```json
{
  "type": "https://api.odontoclinic.local/errors/conflict",
  "title": "Horario no disponible para cita",
  "status": 409,
  "detail": "El odontólogo seleccionado ya cuenta con una cita en el intervalo 2026-10-22T09:30:00Z - 10:15:00Z.",
  "instance": "/api/agendamiento/citas",
  "timestamp": "2026-10-21T18:45:00Z",
  "traceId": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "invalidParams": [
    {
      "name": "fechaHoraInicio",
      "reason": "Solapamiento de turno detectado",
      "value": "2026-10-22T09:30:00Z"
    }
  ]
}
```

### B. Formato de Error en GraphQL (GraphQL Error Extensions)
En GraphQL, las peticiones HTTP retornan casi siempre `200 OK` a nivel de transporte (a menos que falle la infraestructura o el Gateway). Los errores de negocio y validación se encapsulan en el array `errors[]` con un bloque `extensions` compatible con Problem Details:

```json
{
  "data": null,
  "errors": [
    {
      "message": "Saldo insuficiente para registrar la liquidación de honorarios.",
      "locations": [{ "line": 2, "column": 3 }],
      "path": ["liquidarHonorarios"],
      "extensions": {
        "code": "BAD_USER_INPUT",
        "status": 422,
        "type": "https://api.odontoclinic.local/errors/insufficient-balance",
        "timestamp": "2026-10-21T18:45:00Z",
        "correlationId": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "invalidArgs": [
          {
            "field": "montoTotal",
            "reason": "El monto excede el saldo acumulado del periodo.",
            "value": 1500.00
          }
        ]
      }
    }
  ]
}
```

---

## 5. Matriz de Catálogos de Contratos

| Archivo | Protocolo | Microservicio | Responsable | Estado |
|---|---|---|---|---|
| [contracts/rest/ms1-seguridad.yaml](file:///c:/2-2026/sw2/p2/platform-infrastructure/contracts/rest/ms1-seguridad.yaml) | REST (OpenAPI 3.0) | MS1 Seguridad | Dennis | Preliminar funcional |
| [contracts/rest/ms2-clinico.yaml](file:///c:/2-2026/sw2/p2/platform-infrastructure/contracts/rest/ms2-clinico.yaml) | REST (OpenAPI 3.0) | MS2 Expediente Clínico e IA | Henry | Propuesta ampliada |
| [contracts/rest/ms3-agendamiento.yaml](file:///c:/2-2026/sw2/p2/platform-infrastructure/contracts/rest/ms3-agendamiento.yaml) | REST (OpenAPI 3.0) | MS3 Agendamiento y Stock | Wendy | Propuesta ampliada |
| [contracts/graphql/ms1-erp.graphql](file:///c:/2-2026/sw2/p2/platform-infrastructure/contracts/graphql/ms1-erp.graphql) | GraphQL SDL | MS1 ERP / Finanzas | Dennis | Propuesta inicial |
| [contracts/graphql/README.md](file:///c:/2-2026/sw2/p2/platform-infrastructure/contracts/graphql/README.md) | Documentación | Guía GraphQL vs REST | Dennis / Equipo | Guía de arquitectura |
