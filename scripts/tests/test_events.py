"""Contratos de eventos y topología; solo stdlib, sin broker ni checkout del ERP."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


class EventsTest(unittest.TestCase):
    def test_flat_consulta_fields(self):
        schema = load("contracts/events/consulta-finalizada.schema.json")
        self.assertEqual(schema["type"], "object")
        self.assertEqual(set(schema["properties"]), {
            "eventId", "consultaId", "citaId", "pacienteId", "odontologoId",
            "serviciosRealizados", "observacionesCobro"})
        self.assertEqual(set(schema["required"]), {
            "consultaId", "pacienteId", "serviciosRealizados"})
        self.assertNotEqual(schema.get("additionalProperties"), False)
        for field in ("eventId", "citaId", "odontologoId"):
            self.assertIn("null", schema["properties"][field]["type"])
        for field in ("eventId", "consultaId", "citaId", "pacienteId", "odontologoId"):
            self.assertEqual(schema["properties"][field]["format"], "uuid")
            self.assertNotIn("pattern", schema["properties"][field])

    def test_service_shape_and_money_not_overconstrained(self):
        services = load("contracts/events/consulta-finalizada.schema.json")["properties"]["serviciosRealizados"]
        self.assertEqual(services["minItems"], 1)
        item = services["items"]
        self.assertEqual(set(item["properties"]), {
            "servicioId", "piezaDental", "cantidad", "precioUnitarioBs"})
        self.assertEqual(set(item["required"]), {"servicioId", "cantidad", "precioUnitarioBs"})
        self.assertEqual(item["properties"]["cantidad"], {"type": "integer", "minimum": 1, "maximum": 2147483647})
        self.assertEqual(item["properties"]["piezaDental"]["maxLength"], 10)
        # Money redondea HALF_UP antes de rechazar negativos: no imponer minimum ni multipleOf.
        self.assertEqual(item["properties"]["precioUnitarioBs"]["type"], "number")
        self.assertNotIn("minimum", item["properties"]["precioUnitarioBs"])
        self.assertNotIn("multipleOf", item["properties"]["precioUnitarioBs"])

    def test_catalog_exact_documented_shapes(self):
        doc = (ROOT / "contracts/events/README.md").read_text(encoding="utf-8")
        shapes = {
            "paciente": "eventId, pacienteId, ciNit, nombreCompleto, telefonoWhatsapp, fechaNacimiento",
            "odontologo": "eventId, odontologoId, nombreCompleto, matriculaProfesional, especialidades",
            "consultorio": "eventId, consultorioId, codigo, nombre, estado",
        }
        for entity, fields in shapes.items():
            for action in ("creado", "actualizado"):
                expected = fields + (", activo" if action == "actualizado" and entity != "consultorio" else "")
                self.assertIn(f"| `catalogo.{entity}.{action}` | `{expected}` |", doc)
        for term in ("consultaId", "eventId", "HALF_UP", "MS2", "extremo a extremo", "sin timestamp"):
            self.assertIn(term, doc)

    def test_erp_topology(self):
        topology = load("messaging/rabbitmq/topology-erp.json")
        self.assertEqual(topology["vhosts"], [{"name": "/"}])
        self.assertNotIn("users", topology)
        self.assertNotIn("permissions", topology)
        exchanges = {e["name"]: e for e in topology["exchanges"]}
        self.assertEqual(set(exchanges), {"dental.topic.exchange", "dental.dlx.exchange"})
        self.assertEqual(exchanges["dental.topic.exchange"]["type"], "topic")
        self.assertEqual(exchanges["dental.dlx.exchange"]["type"], "direct")
        queues = {q["name"]: q for q in topology["queues"]}
        self.assertEqual(set(queues), {"erp.consulta.finalizada.queue", "erp.consulta.finalizada.dlq"})
        self.assertEqual(queues["erp.consulta.finalizada.queue"]["arguments"], {
            "x-dead-letter-exchange": "dental.dlx.exchange",
            "x-dead-letter-routing-key": "erp.consulta.finalizada.dlq"})
        self.assertEqual(queues["erp.consulta.finalizada.dlq"]["arguments"], {})
        for entry in topology["exchanges"] + topology["queues"]:
            self.assertEqual(entry["vhost"], "/")
            self.assertTrue(entry["durable"])
            self.assertFalse(entry["auto_delete"])
        self.assertEqual(topology["bindings"], [
            {"source": "dental.topic.exchange", "vhost": "/", "destination": "erp.consulta.finalizada.queue",
             "destination_type": "queue", "routing_key": "clinica.consulta.finalizada", "arguments": {}},
            {"source": "dental.dlx.exchange", "vhost": "/", "destination": "erp.consulta.finalizada.dlq",
             "destination_type": "queue", "routing_key": "erp.consulta.finalizada.dlq", "arguments": {}}])

    def test_legacy_topology_preserved(self):
        topology = load("messaging/rabbitmq/topology.json")
        self.assertEqual(topology["vhosts"], [{"name": "/odontoclinic"}])
        self.assertEqual([(e["name"], e["type"]) for e in topology["exchanges"]],
                         [("odontoclinic.events", "topic"), ("odontoclinic.dlx", "direct")])
        expected = [("ms2.cita-notificacion.queue", "agendamiento.cita.*"),
                    ("ms3.seguridad-sync.queue", "seguridad.usuario.*"),
                    ("ms3.cita-completada.queue", "expediente.evolucion.*")]
        self.assertEqual([q["name"] for q in topology["queues"]], [q for q, _ in expected])
        self.assertEqual(topology["bindings"], [
            {"source": "odontoclinic.events", "vhost": "/odontoclinic", "destination": queue,
             "destination_type": "queue", "routing_key": key, "arguments": {}} for queue, key in expected])
        for queue in topology["queues"]:
            self.assertEqual(queue["arguments"], {"x-dead-letter-exchange": "odontoclinic.dlx"})
            self.assertEqual(queue["vhost"], "/odontoclinic")
            self.assertTrue(queue["durable"])
            self.assertFalse(queue["auto_delete"])

    def test_configuration_and_compatibility_documented(self):
        doc = (ROOT / "messaging/rabbitmq/README.md").read_text(encoding="utf-8")
        for term in ("topology-erp.json", "SPRING_RABBITMQ_VIRTUAL_HOST", "spring.rabbitmq.virtual-host",
                     "erp.messaging.exchange", "ERP_RABBIT_HOST", "compatibilidad", "MS2"):
            self.assertIn(term, doc)
        self.assertNotIn("ERP_RABBIT_VHOST", doc)


if __name__ == "__main__":
    unittest.main()
