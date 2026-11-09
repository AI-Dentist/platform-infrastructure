"""Static checks of gateway.conf limits for AI traffic (S2-S3); no Docker needed."""
import re
import unittest
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[2] / "gateway/nginx/gateway.conf"


def locations(text):
    """Map each `location` matcher to its block body (blocks here never nest)."""
    found = {}
    for match in re.finditer(r"location\s+([^{]+?)\s*\{(.*?)\n    \}", text, re.S):
        found[match.group(1).strip()] = match.group(2)
    return found


def directive(body, name):
    values = re.findall(rf"^\s*{name}\s+([^;]+);", body, re.M)
    return values[-1] if values else None


class GatewayAiLimitsTest(unittest.TestCase):
    def setUp(self):
        self.blocks = locations(CONFIG.read_text(encoding="utf-8"))

    def block(self, needle):
        matches = [body for key, body in self.blocks.items() if needle in key]
        self.assertEqual(len(matches), 1, f"expected one location containing {needle!r}: {list(self.blocks)}")
        return matches[0]

    def test_service_routes_use_ai_timeouts(self):
        for needle in ("/api/erp/graphql", "/api/expediente/", "/api/agendamiento/"):
            body = self.block(needle)
            self.assertEqual(directive(body, "proxy_read_timeout"), "120s", needle)
            self.assertEqual(directive(body, "proxy_connect_timeout"), "60s", needle)

    def test_mcp_stream_keeps_its_longer_idle_interval(self):
        body = self.block("= /mcp")
        self.assertEqual(directive(body, "proxy_read_timeout"), "300s")
        self.assertEqual(directive(body, "proxy_connect_timeout"), "60s")
        self.assertEqual(directive(body, "proxy_buffering"), "off")

    def test_expediente_accepts_25m_images(self):
        self.assertEqual(directive(self.block("/api/expediente/"), "client_max_body_size"), "25M")

    def test_slashless_agendamiento_redirects_like_other_service_prefixes(self):
        body = self.blocks.get("= /api/agendamiento")
        self.assertIsNotNone(body, f"missing exact slashless agendamiento location: {list(self.blocks)}")
        self.assertEqual(directive(body, "return"), "301 /api/agendamiento/$is_args$args")
        self.assertIsNone(directive(body, "proxy_pass"), "slashless redirect must not reach MS3")

    def test_report_export_is_unbuffered(self):
        body = self.block("/api/erp/graphql")
        self.assertIn("/api/v1/reports/export", list(k for k in self.blocks if "/api/erp/graphql" in k)[0])
        self.assertEqual(directive(body, "proxy_buffering"), "off")


if __name__ == "__main__":
    unittest.main()
