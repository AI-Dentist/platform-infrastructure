# Arquitectura de Mensajería Asíncrona: RabbitMQ

> **ESTADO DEL COMPONENTE: PLANIFICADO (NO INSTALAR EN ESTA FASE)**  
> Este documento describe las responsabilidades, topología de eventos y futuras configuraciones para la integración asíncrona entre microservicios. No se debe realizar la instalación local ni levantar contenedores hasta contar con la autorización formal.

---

## ERP: topología adicional, no migración de la existente

`topology.json` conserva sin cambios `/odontoclinic`, `odontoclinic.events`, `odontoclinic.dlx`, sus colas y bindings. Las secciones históricas siguientes no describen la API efectiva del ERP; en particular, el sobre genérico de la sección 3 **no aplica al ERP**.

[topology-erp.json](topology-erp.json) describe por separado los defaults de `RabbitMQConfig` y `application.yml` del backend publicado `c6abae67109719113a2767e547ff0fce5553c740`. Es un artefacto declarativo, no un despliegue ejecutado. No contiene usuarios ni permisos; su provisión requiere autorización independiente.

| Recurso ERP | Valor predeterminado |
|---|---|
| Vhost | `/` (default Spring AMQP; el YAML no declara otro) |
| Topic exchange durable | `dental.topic.exchange` |
| Cola durable | `erp.consulta.finalizada.queue` |
| Binding de entrada | `clinica.consulta.finalizada` |
| DLX durable, tipo direct | `dental.dlx.exchange` |
| DLQ durable y clave de dead letter | `erp.consulta.finalizada.dlq` |

La cola declara `x-dead-letter-exchange` y `x-dead-letter-routing-key`; la DLQ se enlaza al DLX con esa misma clave. El listener tiene `spring.rabbitmq.listener.simple.default-requeue-rejected=false`: los mensajes rechazados no se reencolan indefinidamente. No se define un binding de catálogo hacia la cola de consultas.

### Conexión y overrides reales

| Propiedad Spring | Variable/configuración |
|---|---|
| `spring.rabbitmq.host` | `ERP_RABBIT_HOST` (default `localhost`) |
| `spring.rabbitmq.port` | `ERP_RABBIT_PORT` (default `5672`) |
| `spring.rabbitmq.username` | `ERP_RABBIT_USER` |
| `spring.rabbitmq.password` | `ERP_RABBIT_PASSWORD` (gestionar como secreto; no guardar valores aquí) |
| `spring.rabbitmq.virtual-host` | Override estándar `SPRING_RABBITMQ_VIRTUAL_HOST`; default `/` |
| `erp.messaging.exchange` | `dental.topic.exchange` |
| `erp.messaging.consulta-finalizada-queue` | `erp.consulta.finalizada.queue` |
| `erp.messaging.consulta-finalizada-routing-key` | `clinica.consulta.finalizada` |
| `erp.messaging.dead-letter-exchange` | `dental.dlx.exchange` |
| `erp.messaging.consulta-finalizada-dlq` | `erp.consulta.finalizada.dlq` |

Las propiedades `erp.messaging.*` pueden sobreescribirse mediante configuración Spring externa (por ejemplo `--erp.messaging.exchange=...`). Si se selecciona otro vhost mediante `SPRING_RABBITMQ_VIRTUAL_HOST` o `--spring.rabbitmq.virtual-host=...`, todos los recursos y bindings ERP deben existir en ese mismo vhost, con permisos apropiados; el JSON entregado representa únicamente `/`. No mezclar automáticamente con `/odontoclinic`. Entre contenedores, `localhost` apunta al propio contenedor: configurar el host accesible del broker.

### Brecha de compatibilidad y aceptación pendiente

El consumidor espera [JSON plano](../../contracts/events/README.md), no el sobre `payload` histórico. No crear bindings entre productores existentes y el ERP sin confirmar formato, semántica, vhost y clave. El productor MS2 y la entrega extremo a extremo permanecen pendientes; tampoco se inventan colas ni bindings consumidores para los seis `catalogo.*`. Sin consumidores enlazados, la publicación obligatoria de catálogo puede retornar `NO_ROUTE` y el outbox seguirá reintentando: no equivale a entrega completada.

Verificación local: `python -m unittest discover -s scripts/tests -p test_events.py -v` comprueba estructura, campos y bindings ERP y preservación de la topología previa. No importa definiciones ni inicia servicios. Faltan una prueba autorizada con broker real, publicación MS2, deduplicación de consultas, DLQ y consumidores de catálogo antes de afirmar integración operativa.

## 1. Responsabilidades en el Sistema Médico-Odontológico

RabbitMQ actuará como el **Message Broker** del sistema basado en una Arquitectura Dirigida por Eventos (EDA - Event-Driven Architecture), resolviendo desacoplamiento temporal y consistencia eventual:

1. **Desacoplamiento entre dominios:**
   - Evita llamadas HTTP síncronas bloqueantes entre microservicios cuando una acción no requiere respuesta inmediata.
2. **Propagación de eventos de dominio:**
   - Cuando en **MS3 (Agendamiento)** se reserva una cita (`CitaAgendada`), se notifica asíncronamente a **MS2 (Expediente Clínico)** para preparar o precargar la ficha del paciente.
   - Cuando en **MS1 (Seguridad)** se registra o actualiza un profesional de la salud (`OdontologoRegistrado`), se sincroniza el catálogo de profesionales en MS3.
3. **Resiliencia y Reintentos:**
   - Garantiza que si un microservicio destino está temporalmente inactivo, los mensajes permanezcan encolados sin pérdida de información, soportando colas de mensajes fallidos (*Dead Letter Queues - DLQ*).

---

## 2. Topología Propuesta (Exchanges, Queues y Routing Keys)

La topología prevista utilizará un **Topic Exchange** principal para permitir filtrado y suscripción selectiva:

- **Exchange Principal:** `odontoclinic.events` (Tipo: `topic`, Durable: `true`)
- **Dead Letter Exchange (DLX):** `odontoclinic.dlx` (Tipo: `direct`, Durable: `true`)

### Mapa de Eventos y Enrutamiento:

| Routing Key | Microservicio Productor | Colas Consumidoras | Propósito |
|---|---|---|---|
| `seguridad.usuario.creado` | MS1 (Seguridad) | `ms3.seguridad-sync.queue` | Notificar nuevo odontólogo o asistente registrado |
| `agendamiento.cita.creada` | MS3 (Agendamiento) | `ms2.cita-notificacion.queue` | Notificar cita para preparar expediente clínico |
| `agendamiento.cita.cancelada` | MS3 (Agendamiento) | `ms2.cita-cancelacion.queue` | Liberar bloqueos o alertas en historia médica |
| `expediente.evolucion.registrada` | MS2 (Expediente) | `ms3.cita-completada.queue` | Marcar la cita como completada tras registrar atención clínica |

---

## 3. Especificación de Configuración Futura

Cuando se autorice la instalación local de RabbitMQ (vía binario o servicio de Windows):

- **Puerto de Protocolo AMQP:** `5672`
- **Puerto de Consola de Administración (Management UI):** `15672` (`http://localhost:15672`)
- **Virtual Host:** `/odontoclinic`
- **Estructura canónica del Payload de Evento:**
```json
{
  "eventId": "c7a8b9d0-1234-4567-89ab-cdef01234567",
  "eventType": "CitaAgendadaEvent",
  "producer": "ms3-agendamiento",
  "timestamp": "2026-10-21T18:30:00Z",
  "correlationId": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "payload": {
    "citaId": "3f2e1d0c-ba98-7654-3210-fedcba987654",
    "pacienteId": "a1b2c3d4-e5f6-7a8b-9c0d-1e2f3a4b5c6d",
    "odontologoId": "e28bbd98-1e43-4dc3-9c8e-5b1234567890",
    "fechaHora": "2026-10-22T09:30:00Z"
  }
}
```

---

## 4. Estado de Implementación

- [x] Especificación de arquitectura y topología de eventos documentada.
- [ ] Instalación de RabbitMQ en Windows (Pendiente de autorización).
- [ ] Creación de vhost, usuarios y permisos en broker local.
- [ ] Conectores cliente en Spring Boot (Spring AMQP), NestJS (Microservices RMQ) y Laravel (Laravel Queue / Enqueue).
