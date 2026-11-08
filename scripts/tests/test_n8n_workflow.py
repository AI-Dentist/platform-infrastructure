"""Structural checks of the n8n collection-alert workflow consumed by MS1 (S4-S5)."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "automation/n8n"
PAYLOAD = ("pacienteNombre", "telefono", "montoBs", "concepto", "fechaVencimiento")


class N8nWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.flow = json.loads((ROOT / "workflows/cobranza-whatsapp.json").read_text(encoding="utf-8"))
        self.nodes = {node["name"]: node for node in self.flow["nodes"]}

    def test_webhook_is_post_erp_cobranza(self):
        hook = self.nodes["Webhook ERP"]["parameters"]
        self.assertEqual((hook["httpMethod"], hook["path"]), ("POST", "erp-cobranza"))

    def test_message_uses_every_payload_field(self):
        body = self.nodes["Enviar WhatsApp"]["parameters"]["jsonBody"]
        for field in PAYLOAD:
            self.assertIn(f"$json.body.{field}", body, field)

    def test_requests_without_shared_secret_are_rejected(self):
        rules = json.dumps(self.nodes["Secreto y telefono validos"]["parameters"])
        self.assertIn("x-erp-webhook-secret", rules)
        self.assertIn("$env.ERP_WEBHOOK_SECRET", rules)
        rejected = self.nodes["Responder rechazado"]["parameters"]
        self.assertEqual(rejected["options"]["responseCode"], 401)
        branches = self.flow["connections"]["Secreto y telefono validos"]["main"]
        self.assertEqual(branches[1][0]["node"], "Responder rechazado")

    def test_every_connection_targets_an_existing_node(self):
        for source, outputs in self.flow["connections"].items():
            self.assertIn(source, self.nodes)
            for branch in outputs["main"]:
                for link in branch:
                    self.assertIn(link["node"], self.nodes)

    def test_compose_binds_loopback_and_keeps_secrets_out_of_git(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn('"127.0.0.1:5678:5678"', compose)
        self.assertIn("${ERP_WEBHOOK_SECRET:?", compose)
        self.assertNotRegex(compose, r"WHATSAPP_ACCESS_TOKEN=[A-Za-z0-9]")


if __name__ == "__main__":
    unittest.main()
