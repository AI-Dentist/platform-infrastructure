# Integración REST: rutas reales y propuestas históricas

**Consultar este mapa antes de usar los YAML.** `ms2-clinico.yaml` y
`ms3-agendamiento.yaml` conservan propuestas históricas, no son exports OpenAPI
canónicos. Este inventario de código no prueba despliegue ni ejecución conjunta.
El contrato versionado del ERP es [GraphQL](../graphql/README.md).

## Transporte

| Receptor | Acceso directo previsto | Prefijo que Nginx conserva |
|---|---|---|
| MS2 | `http://127.0.0.1:3001/api/expediente` | `/api/expediente/` |
| MS3 | `http://127.0.0.1:8001/api/agendamiento` | `/api/agendamiento/` |

No reemplazar estos prefijos por `/api/clinico` o `/api/agenda-stock`: no son
aliases de la configuración actual. Solo `/api/erp/graphql` se reescribe a
`/graphql`. Ver [configuración del Gateway](../../gateway/nginx/README.md).
El health MS2 es `GET /api/expediente/health`; el de MS3 es `GET /health` directo
al servicio. El prefijo MS3 no convierte `/api/agendamiento/health` en `/health`.
El Gateway no publica un health global ni Actuator por su ruta raíz.

## MS2: historia y atención

Las escrituras clínicas requieren Bearer y rol `ODONTOLOGO` o `ADMIN`.

| Operación | Ruta bajo `/api/expediente` | Input relevante |
|---|---|---|
| Crear historia | `POST /historias-clinicas` | `pacienteId` UUID; opcionales `odontologoResponsableId`, `antecedentes`, `observacionesGenerales` |
| Leer historia | `GET /historias-clinicas/{id}` | ID devuelto por MS2 |
| Buscar historias | `GET /historias-clinicas?pacienteId=...` | UUID del paciente ERP |
| Abrir consulta | `POST /consultas-odontologicas` | `historiaClinicaId`, `pacienteId`, `motivoConsulta`; `citaId` opcional |
| Completar consulta | `POST /consultas-odontologicas/{id}/completar` | `versionEsperada` entero >= 1; `serviciosFacturables` opcional |

El detalle clínico admite campos tipados de anamnesis, exploración, diagnósticos,
procedimientos y evolución SOAP; usar los DTO del servicio, no los DTO propuestos
en `/consultas`. Una consulta devuelve un ID `cons_<uuid>`: no asumir que todos
los IDs locales son UUID desnudos. El cierre devuelve `estado: COMPLETADA`,
`cerradaEn` y `totalFacturableBs` como string. Los servicios facturables usan
`servicioId`, `cantidad` y `piezaDental` opcional; no identifican insumos físicos.

### Identidad y autenticación de llamadas ERP

El odontólogo canónico se obtiene mediante `obtenerMiOdontologoId` usando el
Bearer del usuario actual. No usar JWT `sub` como PK ni una credencial estática
para esa consulta. El vínculo ADMIN está descrito en la [guía GraphQL](../graphql/README.md).

Los adaptadores de paciente y catálogo de servicios usan actualmente
`MS1_BEARER_TOKEN`, no el Bearer del caller. Si no está configurado, omiten
Authorization y un ERP autenticado rechaza esas lecturas. Es una dependencia
operativa distinta de la resolución de identidad: configurar una credencial
válida con permisos adecuados y gestionar su vigencia fuera de este contrato.
No guardar credenciales en este repositorio, logs ni ejemplos; no inferir que
el reenvío del token propio ya resuelve también esos dos adaptadores.

El validador de citas MS3 usa de forma equivalente `MS3_BEARER_TOKEN`; si falta,
no envía Authorization al consultar citas. Debe configurarse un token válido
para ese receptor y gestionar su vigencia. El Bearer del usuario no se propaga
automáticamente a esta llamada por el solo hecho de resolver su identidad ERP.

## MS3: agenda y stock

Las citas admiten `ADMIN`, `RECEPCIONISTA` y `ODONTOLOGO`; los horarios de lectura
requieren autenticación. Mantener las reglas específicas del servicio para stock.

| Operación | Ruta bajo `/api/agendamiento` | Input relevante |
|---|---|---|
| Consultar horarios | `GET /horarios` | `odontologo_id` opcional |
| Crear horario (solo ADMIN) | `POST /horarios` | `odontologo_id`, `consultorio_id`, `especialidad`, `fecha`, `hora_inicio`, `hora_fin`; `disponible` opcional |
| Listar / leer cita | `GET /citas`, `GET /citas/{id}` | Filtros / ID del servicio |
| Reservar cita | `POST /citas` | `odontologo_id`, `consultorio_id`, `paciente_id`, `fecha_hora`; clave de idempotencia requerida |
| Cancelar | `PATCH /citas/{id}/cancelar` | Sin body |
| Reprogramar | `PUT /citas/{id}/reprogramar` | `nueva_fecha_hora`; conserva el ID |
| Completar | `PATCH /citas/{id}/completar` | `insumos_utilizados: [{insumo_id, cantidad}]` opcional |
| Marcar ausencia | `PATCH /citas/{id}/no-asistio` | ID de la cita |
| Leer stock / movimientos / kardex | `GET /stock`, `POST /stock/movimientos`, `GET /stock/{id}/kardex` | DTO de insumos físicos del servicio |

El alta de horarios exige un JWT ADMIN válido. Consulta los catálogos ERP con
el Bearer del caller, valida odontólogo activo y consultorio `estado: ACTIVO`,
y persiste los UUID canónicos devueltos, no una representación elegida por el
caller. Genera un nuevo ID `hor-<uuid>`; no migra ni reemplaza seeds existentes.
`fecha` usa `YYYY-MM-DD`; ambos horarios exigen `HH:MM` de 24 horas e inicio
anterior al fin. `disponible` tiene valor predeterminado `true`.

Configurar `MS1_GRAPHQL_URL` (predeterminado `http://127.0.0.1:8081/graphql`)
y `MS1_TIMEOUT_MS` (predeterminado `2000`). El token debe servir también para
el recurso ERP. Los rechazos de autenticación/rol usan 401/403; los datos o
referencias inválidos, 422. Fallos de transporte, errores GraphQL o respuestas
de catálogo inesperadas producen 502 genérico, sin reenviar mensajes internos,
URLs ni tokens. Las respuestas exitosas devuelven `201` y el horario en `data`;
se puede leer mediante `GET /horarios`. No hay sincronización automática de
catálogos ni escritura directa en la BD por parte del cliente.

La reserva acepta aliases camelCase documentados por MS3, pero no obliga a
cambiar IDs maestros por números de sillón. `paciente_id` es obligatorio: no se
admite un paciente nulo. MS3 reconoce `Idempotency-Key` o `X-Idempotency-Key` en
la reserva y distingue creación de replay; no trasladar ese comportamiento a
otras operaciones sin evidencia.

Estados reales: `RESERVADA`, `EN_ATENCION`, `COMPLETADA`, `CANCELADA`,
`REPROGRAMADA`, `NO_ASISTIO`. Una cita reprogramada conserva su ID y puede
iniciar atención en MS2 sin confirmación adicional, siempre que coincida el
paciente y se cumplan las demás validaciones. Las citas cerradas siguen
rechazándose. No existen los aliases MS3 `PROGRAMADA`, `CONFIRMADA` o `FINALIZADA`. Las acciones explícitas sustituyen la propuesta
`PATCH /citas/{id}/estado`; `/horarios` no es `/disponibilidad`.

El envelope MS3 usa `success`, `data` y `timestamp`; algunas listas conservan
campos duplicados de compatibilidad. Los errores usan `success: false`, `error`,
`code` y `timestamp`, no una promesa general de Problem Details.
Completar con insumos aplica la operación atómica de cita, stock y movimientos
propia de MS3. Cerrar la consulta clínica no ejecuta automáticamente esa acción:
el cliente debe aportar los insumos efectivamente usados. No deducirlos del
catálogo de servicios facturables ni suponer un consumidor Rabbit inexistente.

## Límite de evidencia

Este mapa no acredita importación de Keycloak, tokens reales entre procesos,
sincronización automática de catálogos, migración de seeds ni integración E2E.
Los UUID maestros deben conservar su identidad al cruzar servicios; no adivinar
correspondencias por nombre, email, número de sillón o posición de una lista.
