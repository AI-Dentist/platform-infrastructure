# Arquitectura de Mensajería Asíncrona: RabbitMQ

> **ESTADO DEL COMPONENTE: PLANIFICADO (NO INSTALAR EN ESTA FASE)**  
> Este documento describe las responsabilidades, topología de eventos y futuras configuraciones para la integración asíncrona entre microservicios. No se debe realizar la instalación local ni levantar contenedores hasta contar con la autorización formal.

---

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
