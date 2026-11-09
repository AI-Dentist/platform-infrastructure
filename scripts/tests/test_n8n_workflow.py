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

    def test_multichannel_workflow_mirrors_ms1_contract(self):
        multichannel_path = ROOT / "workflows/n8n-workflow-multicanal.json"
        self.assertTrue(multichannel_path.exists(), "Mirror workflow n8n-workflow-multicanal.json is missing")
        flow = json.loads(multichannel_path.read_text(encoding="utf-8"))
        nodes = {node["name"]: node for node in flow["nodes"]}
        webhook_nodes = [n for n in flow["nodes"] if n.get("type") == "n8n-nodes-base.webhook"]
        self.assertEqual(len(webhook_nodes), 1)
        self.assertEqual(webhook_nodes[0]["parameters"].get("path"), "erp-notificaciones")
        self.assertEqual(webhook_nodes[0]["parameters"].get("httpMethod"), "POST")
        raw = json.dumps(flow, ensure_ascii=False)
        self.assertIn("graph.facebook.com/v20.0", raw)
        self.assertIn("n8n-nodes-base.telegram", raw)
        self.assertIn("Aviso de Cobranza - Clínica Dental", raw)
        self.assertIn("n8n-nodes-base.respondToWebhook", raw)
        for source, outputs in flow["connections"].items():
            self.assertIn(source, nodes)
            for branch in outputs["main"]:
                for link in branch:
                    self.assertIn(link["node"], nodes)


if __name__ == "__main__":
    unittest.main()
