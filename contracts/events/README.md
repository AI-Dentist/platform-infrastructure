# Eventos efectivos del ERP

El ERP recibe y publica **JSON plano**, no el sobre `payload` propuesto históricamente para otros servicios. Referencia: backend publicado `c6abae67109719113a2767e547ff0fce5553c740`. No se cambia el formato de MS2/MS3 ni se acredita entrega extremo a extremo.

## Consulta finalizada: MS2 → ERP

Routing key `clinica.consulta.finalizada` en `dental.topic.exchange`; consumidor `ConsultaFinalizadaRabbitListener`, DTO `ConsultaFinalizadaPayload`. [Schema](consulta-finalizada.schema.json) para una consulta nueva:

| Campo | Regla efectiva |
|---|---|
| `consultaId` | UUID no nulo; clave de deduplicación y bloqueo transaccional. Una consulta ya existente retorna sin validar nuevamente sus referencias/servicios. |
| `pacienteId` | UUID no nulo; debe existir en catálogo. |
| `odontologoId` | UUID opcional/nulo; si se informa, debe existir (se consulta incluso inactivos). |
| `serviciosRealizados` | Lista no nula, no vacía; elementos no nulos. |
| `servicioId` | UUID no nulo por ítem; servicio existente y activo. |
| `cantidad` | Entero Java positivo (hasta 2147483647). |
| `precioUnitarioBs` | Número no nulo; Money redondea a dos decimales HALF_UP y después rechaza negativos. Admite cero y más de dos decimales de entrada. |
| `piezaDental` | Texto opcional/nulo, hasta 10 caracteres. |
| `observacionesCobro` | Texto opcional/nulo, pasado al dominio. |
| `eventId`, `citaId` | UUID opcionales/nulos del DTO, no se trasladan al comando ni se usan para deduplicar. |

El schema no fija versión UUID, no prohíbe propiedades adicionales y no inventa `eventType`, `version` ni timestamp. `format: uuid` requiere un validador con soporte de formatos. Describe la forma válida de entrada nueva, no todos los comportamientos de deserialización ni el atajo de duplicados. No basta con pasar JSON Schema: la existencia de referencias, estado del servicio y reglas monetarias se verifican en el backend. Por ejemplo `-0.004` se redondea a `0.00`, mientras `-0.005` es rechazado; por eso no se impone `minimum: 0` ni `multipleOf: 0.01`. El cálculo de subtotales también pasa por Money.

```json
{
  "consultaId": "00000000-0000-0000-0000-000000000001",
  "pacienteId": "00000000-0000-0000-0000-000000000002",
  "serviciosRealizados": [{
    "servicioId": "00000000-0000-0000-0000-000000000003",
    "cantidad": 1,
    "precioUnitarioBs": 100.125
  }]
}
```

Ejemplo de forma, con IDs sintéticos: no garantiza referencias válidas ni autoriza publicación. Los fallos del listener se rechazan sin requeue infinito, hacia la DLQ configurada; esto no implementa recuperación automática.

## Catálogo: ERP → consumidores por acordar

`RabbitMQCatalogEventPublisher` serializa los componentes de los records directamente en el outbox. `routingKey()` es un método, no un campo JSON. Los seis eventos usan `dental.topic.exchange`:

| Routing key | Campos planos exactos |
|---|---|
| `catalogo.paciente.creado` | `eventId, pacienteId, ciNit, nombreCompleto, telefonoWhatsapp, fechaNacimiento` |
| `catalogo.paciente.actualizado` | `eventId, pacienteId, ciNit, nombreCompleto, telefonoWhatsapp, fechaNacimiento, activo` |
| `catalogo.odontologo.creado` | `eventId, odontologoId, nombreCompleto, matriculaProfesional, especialidades` |
| `catalogo.odontologo.actualizado` | `eventId, odontologoId, nombreCompleto, matriculaProfesional, especialidades, activo` |
| `catalogo.consultorio.creado` | `eventId, consultorioId, codigo, nombre, estado` |
| `catalogo.consultorio.actualizado` | `eventId, consultorioId, codigo, nombre, estado` |

Tipos de los records: `eventId` e IDs de entidad son UUID; `fechaNacimiento` es fecha ISO `YYYY-MM-DD` (LocalDate); `especialidades` es lista de nombres de texto, no IDs; `activo` es booleano. Los demás campos son textos. Esta tabla documenta componentes y tipos, no agrega restricciones de nulabilidad que los records no declaran. `estado` admite `DISPONIBLE`, `MANTENIMIENTO`, `INACTIVO` según el contrato de dominio.

Son estados completos, no diffs. La baja lógica publica `actualizado` con `activo: false` o `estado: "INACTIVO"`. No hay envoltorio, versión ni campo temporal: **sin timestamp**, no se puede ordenar actualizaciones por contenido. Cuando importa el estado final, releer el catálogo ERP. Especialidades, servicios y usuarios no publican eventos propios.

El outbox persiste evento, agregado y auditoría en la misma transacción. La entrega es al menos una vez: consumidores deduplican por **eventId** (no por entidad); un reintento conserva ID y payload. El dispatcher requiere confirmación ACK sin retorno obligatorio; ACK con `NO_ROUTE` no es éxito. No garantiza orden global ni procesamiento del consumidor; conserva filas para reintento, sin descarte terminal automático. Ver `docs/catalog-outbox.md` del backend para límites y operación.

## Compatibilidad y verificación pendiente

La topología histórica sigue intacta y separada de la [topología ERP](../../messaging/rabbitmq/README.md). No se enlazan productores con sobre genérico al consumidor plano ni se inventan colas consumidoras de catálogo. Falta confirmar productor MS2, IDs compartidos, contrato plano, vhost y bindings acordados con MS2/MS3. Esto es una **brecha de compatibilidad pendiente**, no entrega completada.

Pruebas estructurales locales (stdlib): `python -m unittest discover -s scripts/tests -p test_events.py -v`. Verifican campos y bindings, no ejecutan JSON Schema completo, Java ni RabbitMQ. Quedan pendientes pruebas autorizadas extremo a extremo con broker real: publicación MS2, orden y auditoría únicas ante duplicados, rechazo a DLQ y recepción/deduplicación de los seis eventos de catálogo. Sin despliegues ni pruebas sobre datos reales en esta unidad.
