# Contrato efectivo GraphQL del ERP

El contrato MS1 replica los artefactos canónicos de la **revisión feature publicada**
[587ba426bd684e37f85b0adaf05db4adc8ae8fd2 de ms-erp](https://github.com/AI-Dentist/ms-erp/tree/587ba426bd684e37f85b0adaf05db4adc8ae8fd2).
Esta referencia inmutable incluye la API de identidad; no implica incorporación a
main, release ni despliegue. No modifica los contratos MS2/MS3.

## Fuente y verificación

| Archivo local | Fuente publicada |
|---|---|
| `ms1-erp.graphql` | `docs/graphql/schema.graphqls` |
| Referencia en `source.json` | `docs/graphql/introspection.json` completo, URL fijada a commit y SHA-256; no se duplica el JSON generado |
| `source.json` | Revisión y SHA-256 del SDL y la introspección canónicos |
| `examples.json` | Cuatro operaciones reales y variables ficticias |

Ejecutar desde la raíz, sin servicios ni instalaciones:

```powershell
python -B -m unittest discover -s scripts/tests -p test_graphql_contract.py -v
```

Las comprobaciones verifican la integridad del SDL completo y de la referencia
versionada a la introspección canónica, las referencias de todos los tipos,
operaciones, argumentos, selección de campos e inputs de los ejemplos contra el
SDL. El lector estructural admite la sintaxis de este release y rechaza la que
no conoce; no pretende reemplazar un parser GraphQL general. La introspección
completa del backend sigue siendo fuente de contraste; su revisión y SHA-256
permiten comprobarla sin mantener otra copia generada en este repositorio. No ejecutan resolvers ni certifican JWT, permisos, persistencia,
deduplicación o integración con Nginx. Los UUID de ejemplo son marcadores: una
mutación real necesita entidades existentes en un entorno aislado autorizado.

## Transporte e idempotencia

El backend recibe `POST /graphql`. `/api/erp/graphql` es la convención pública
prevista para el gateway; su disponibilidad debe verificarse en la configuración
y pruebas del proxy, no inferirse de este contrato. No se convierte
`/api/seguridad/graphql` en `/graphql` automáticamente.

Para enviar un elemento de `examples.json`, usar un body JSON con `query`,
`operationName` y `variables`, más estas cabeceras:

```http
Authorization: Bearer <access-token>
Content-Type: application/json
Idempotency-Key: accion-unica-por-reintento
```

- **`Idempotency-Key`**, no `X-Idempotency-Key`, activa el filtro ERP en POST.
  Es opcional para el backend; para reintentos financieros el cliente debe
  reutilizarla para la misma acción. Admite entre 1 y 100 caracteres tras trim.
- No existe un campo GraphQL `idempotencyKey`. No agregarlo a los inputs.
- TTL predeterminado: 24 horas. Una clave en curso responde 409; una clave
  reutilizada para otra solicitud responde 422. El replay devuelve
  `Idempotency-Replayed: true`. El alcance JWT incluye issuer, subject y roles.
- El webhook mock queda fuera del filtro HTTP y posee su propia validación.
- Nginx reenvía las cabeceras de solicitud por defecto. La falta de una directiva
  explícita por cabecera no demuestra pérdida de Authorization o Idempotency-Key.
- `X-Correlation-ID` puede transportarse, pero el ERP publicado no promete
  inyección, MDC ni propagación extremo a extremo. No es una credencial.

## Operaciones que sustituyen la propuesta anterior

| Necesidad | Operación efectiva |
|---|---|
| Orden manual | `crearOrdenCobroManual(input: CrearOrdenCobroInput!)` |
| Plan de cuotas | `configurarPlanDePagos(input: ConfigurarPlanPagosInput!)` |
| Cobro efectivo | `cobrarCuotaEnEfectivo(input: CobrarEfectivoInput!)` |
| Consulta de órdenes | `listarOrdenesCobro(estado: EstadoOrdenCobro, pacienteId: UUID)` |

El esquema completo incluye catálogos, usuarios y configuración. Los escalares
son `UUID`, `BigDecimal`, `Date` y `DateTime`; no sustituirlos por `ID`/`Float`.
Las mutaciones devuelven las entidades indicadas por el SDL, no un wrapper
inventado `exito/mensaje`. `generarFactura`, `registrarPago` y
`liquidarHonorarios` eran propuestas obsoletas, no operaciones publicadas.

## Identidad canónica del odontólogo

Estas operaciones son aditivas: se mantienen las operaciones, tipos y escalares
anteriores. Los permisos y las reglas de vínculo son del backend; el SDL por sí
solo no los aplica.

| Operación | Resultado | Roles del token |
|---|---|---|
| `obtenerMiOdontologoId: UUID!` | PK canónica del odontólogo del actor autenticado | `ODONTOLOGO` o `ADMIN` |
| `vincularIdentidadOdontologo(input: VincularIdentidadOdontologoInput!): UUID!` | PK canónica vinculada | Solo `ADMIN` |

### Consulta propia (sin argumentos)

```graphql
query ObtenerMiOdontologoId {
  obtenerMiOdontologoId
}
```

Enviar el access token del usuario autenticado de esta solicitud, no una
credencial estática de servicio. El subject verificado se resuelve por
`usuarios.keycloak_id` → `usuarios.id` → `odontologos.usuario_id` →
`odontologos.id`. No enviar subject ni doctor elegido por el caller. La PK
resultante puede ser distinta del subject JWT; no usar este último como PK del
catálogo ni adivinar identidad por email/nombre. No se expone un directorio.

### Aprovisionamiento controlado (ADMIN)

```graphql
mutation VincularIdentidadOdontologo($input: VincularIdentidadOdontologoInput!) {
  vincularIdentidadOdontologo(input: $input)
}
```

Variables sintéticas; no son cuentas ni vínculos reales:

```json
{
  "input": {
    "usuarioId": "11111111-1111-4111-8111-111111111111",
    "odontologoId": "22222222-2222-4222-8222-222222222222",
    "keycloakSubject": "subject-Sintetico-A"
  }
}
```

El input exige `usuarioId: UUID!`, `odontologoId: UUID!` y
`keycloakSubject: String!`. El subject es opaco, sensible a mayúsculas,
no vacío ni compuesto solo de espacios y de **máximo 100 caracteres**; no debe
normalizarse como nombre/email. Usuario y odontólogo deben estar activos y
corresponder a la asociación exacta autorizada. Repetir un vínculo exactamente
consistente es idempotente. Los vínculos ausentes en la consulta, entidades
inactivas, asociaciones incorrectas o conflictos fallan cerrados; no se
reasignan identidades ni se sobrescriben conflictos. Un rechazo no debe mutar
los vínculos almacenados. La idempotencia de un vínculo consistente es una regla
de dominio, distinta del replay HTTP mediante `Idempotency-Key`.

Las pruebas locales comprueban las firmas y los inputs publicados, no ejecutan
resolvers ni prueban estos permisos o invariantes en un servicio vivo.

## Errores, identidad y límites

Comprobar tanto el status HTTP como `errors[]`: un HTTP 200 no demuestra éxito de
negocio. Un 401/403 o 502 tampoco demuestra integración. El realm compatible del
ERP es `dental-platform`, con roles sin prefijo `ROLE_` en el token. No usar
`X-Dev-User` ni el perfil `dev` como sustituto de JWT. La publicación de esta API
no demuestra enforcement de audiencia ERP: requiere una versión backend compatible;
no se afirma su despliegue ni integración completa entre servicios.

Los reportes generan URLs relativas `/api/v1/reports/export/{reporteId}/{format}`
(PDF/XLSX). Su descarga exige ADMIN y propietario del reporte. El webhook
`POST /api/v1/webhooks/pagofacil` es **mock local**, con
`X-Local-Mock-Secret`; no acredita integración productiva con PagoFácil.

La antigua especificación REST `../rest/ms1-seguridad.yaml` se conserva marcada
como propuesta obsoleta no implementada. Login OAuth/OIDC corresponde a Keycloak,
no a endpoints REST de seguridad inventados en el ERP.
