# Guía de Arquitectura e Integración GraphQL (MS1 - ERP y Finanzas)

Este documento describe la especificación técnica, justificación arquitectónica y guía de extensión para el esquema GraphQL propuesto para el módulo de **ERP, Finanzas y Administración** alojado en **MS1** (Dennis - Spring Boot + PostgreSQL).

---

## 1. Justificación Arquitectónica: ¿Por qué GraphQL para ERP y REST para Operaciones Clínicas?

En el sistema médico-odontológico se adoptó un modelo híbrido pragmático:

| Dimensión | REST (MS1 Seguridad, MS2 Expediente, MS3 Agendamiento) | GraphQL (MS1 ERP / Finanzas / Reportes) |
|---|---|---|
| **Naturaleza del Dominio** | Operacional, clínico, altamente transaccional y basado en recursos puntuales (citas, historias, login). | Analítico, agregador, financiero y con relaciones multidimensionales (facturas, comisiones, pagos, proveedores). |
| **Problema que Resuelve** | Semántica estándar HTTP, caching predecible por URI, cumplimiento estricto de RFC 7807 en salud. | Elimina el **Under-fetching** (tener que hacer 5 llamadas HTTP separadas para armar el estado contable de un dentista) y el **Over-fetching** (descargar todo el detalle de una factura cuando el dashboard solo necesita el total). |
| **Punto de Entrada** | Múltiples URIs por recurso (`/api/expediente/recetas`, `/api/agendamiento/citas`). | **Single Endpoint**: Un único punto de entrada `POST /graphql` (o `/api/erp/graphql`). |
| **Respuesta HTTP** | Códigos de estado HTTP semánticos (`200`, `201`, `404`, `409`, `422`). | Código de estado HTTP de transporte casi siempre `200 OK`; los errores se inspeccionan en el campo `errors[]`. |

---

## 2. Convenciones de Diseño en el Esquema GraphQL

1. **Tipado Estricto (Schema First):**
   - El archivo canónico de verdad es [contracts/graphql/ms1-erp.graphql](file:///c:/2-2026/sw2/p2/platform-infrastructure/contracts/graphql/ms1-erp.graphql).
   - Nombres de tipos en `PascalCase` (`Factura`, `LiquidacionOdontologo`).
   - Nombres de campos y argumentos en `camelCase` (`numeroFactura`, `saldoPendiente`).
   - Enums en mayúsculas sostenidas (`EMITIDA`, `PAGADA`).
2. **Mutaciones con Tipos de Retorno (Payload Pattern):**
   - Toda mutación retorna un tipo `*Payload` que contiene un flag booleano `exito: Boolean!`, un mensaje legible `mensaje: String!` y la entidad afectada nullable. Esto permite manejar fallas esperadas de negocio sin romper la ejecución de la consulta.
3. **Idempotencia (`X-Idempotency-Key`):**
   - Para mutaciones financieras críticas (`generarFactura`, `registrarPago`, `liquidarHonorarios`), el cliente envía un UUID v4 tanto en el campo `idempotencyKey` del input como en el encabezado HTTP estándar `X-Idempotency-Key`.
4. **Trazabilidad (`X-Correlation-ID`):**
   - El cliente envía `X-Correlation-ID` en las cabeceras HTTP de la petición POST a `/graphql`. Spring Boot debe capturarlo en un `WebGraphQlInterceptor` y propagarlo al `MDC` de logs y a los errores.

---

## 3. Manejo de Errores: REST (RFC 7807) vs GraphQL Extensions

A diferencia de las APIs REST donde el status HTTP refleja el error (ej: 422 o 409), en GraphQL el error se serializa en el payload JSON. Para mantener coherencia con el estándar Problem Details, se estructuran las extensiones del error:

### Ejemplo de Petición con Error de Negocio:
```graphql
mutation {
  liquidarHonorarios(input: {
    idempotencyKey: "8f7e6d5c-4b3a-2109-8765-43210fedcba9"
    odontologoId: "e28bbd98-1e43-4dc3-9c8e-5b1234567890"
    periodo: "2026-10"
    porcentajeComision: -5.0
  }) {
    exito
    mensaje
  }
}
```

### Respuesta de Error compatible con Problem Details:
```json
{
  "data": null,
  "errors": [
    {
      "message": "Validación de parámetros de liquidación fallida.",
      "locations": [{ "line": 2, "column": 3 }],
      "path": ["liquidarHonorarios"],
      "extensions": {
        "code": "BAD_USER_INPUT",
        "status": 422,
        "type": "https://api.odontoclinic.local/errors/invalid-commission",
        "timestamp": "2026-10-21T18:45:00Z",
        "correlationId": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
        "invalidArgs": [
          {
            "field": "porcentajeComision",
            "reason": "El porcentaje de comisión debe ser un valor entre 0 y 100.",
            "value": -5.0
          }
        ]
      }
    }
  ]
}
```

---

## 4. Guía para Extender el Esquema en Spring Boot (Dennis)

Para implementar y ampliar este esquema en **Spring Boot 3.x**:

### 1. Dependencia en `pom.xml`:
```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-graphql</artifactId>
</dependency>
```

### 2. Ubicación del archivo de esquema:
Copia o vincula [ms1-erp.graphql](file:///c:/2-2026/sw2/p2/platform-infrastructure/contracts/graphql/ms1-erp.graphql) dentro del directorio de recursos de Spring Boot:
```
src/main/resources/graphql/schema.graphqls
```

### 3. Implementación de Controladores con Anotaciones de Spring:
```java
@Controller
public class FacturaGraphQLController {

    @Autowired
    private FacturaService facturaService;

    @QueryMapping
    public Factura factura(@Argument String id) {
        return facturaService.buscarPorId(UUID.fromString(id));
    }

    @MutationMapping
    public FacturaPayload generarFactura(@Argument GenerarFacturaInput input) {
        // Validación de idempotencia usando input.getIdempotencyKey()
        Factura facturaCreada = facturaService.generar(input);
        return new FacturaPayload(true, "Factura emitida correctamente", facturaCreada);
    }
}
```

### 4. Resolver Relaciones bajo Demanda (`@SchemaMapping`):
Para evitar problemas de rendimiento N+1 al cargar los ítems o pagos de una factura:
```java
@Controller
public class FacturaSchemaResolver {

    @SchemaMapping(typeName = "Factura", field = "items")
    public List<DetalleFactura> getItems(Factura factura) {
        return detalleFacturaService.buscarPorFacturaId(factura.getId());
    }
}
```

---

## 5. Exposición en el API Gateway (Nginx)

Actualmente en [gateway.conf](file:///c:/2-2026/sw2/p2/platform-infrastructure/gateway/nginx/gateway.conf) se enruta:
- `/api/seguridad/` -> `http://127.0.0.1:8081`

Cuando Dennis habilite el endpoint GraphQL en Spring Boot en `/graphql` o `/api/erp/graphql`, la regla de Nginx podrá extenderse (sin modificar las rutas existentes) de la siguiente manera:
```nginx
# Propuesta futura para Gateway
location /api/erp/graphql {
    proxy_pass http://127.0.0.1:8081/graphql;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Correlation-ID $http_x_correlation_id;
}
```
*(Nota: No se aplica este cambio a Nginx todavía, esperando la validación y despliegue del controlador en MS1).*
