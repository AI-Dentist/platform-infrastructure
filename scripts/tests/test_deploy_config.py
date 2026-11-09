"""Static checks of the production edge/gateway deployment files; no Docker needed."""
import re
import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[2] / "deploy"
TEMPLATE = DEPLOY / "azure/gateway.conf.template"


LOCATION = re.compile(
    r"^    location\s+([^{\n]+?)\s*\{(?:([^\n]*)\}[ \t]*$|(.*?)\n    \})", re.M | re.S)


def locations(text):
    """Map each server-level `location` matcher to its body (one-line or multi-line)."""
    return {m.group(1).strip(): m.group(2) if m.group(2) is not None else m.group(3)
            for m in LOCATION.finditer(text)}


def server_level(text):
    """Directives of the server block outside any location."""
    return LOCATION.sub("", text[text.index("server {"):])


class ProductionGatewayTest(unittest.TestCase):
    def setUp(self):
        self.text = TEMPLATE.read_text(encoding="utf-8")
        self.blocks = locations(self.text)

    def test_dev_header_auth_is_cleared_on_every_proxied_route(self):
        # nginx: a location declaring any proxy_set_header inherits none from server.
        self.assertIn('proxy_set_header X-Dev-User "";', server_level(self.text))
        for matcher, body in self.blocks.items():
            if "proxy_pass" in body and "proxy_set_header" in body:
                self.assertIn('proxy_set_header X-Dev-User "";', body, matcher)

    def test_only_declared_environment_placeholders(self):
        placeholders = set(re.findall(r"\$\{([A-Z0-9_]+)\}", self.text))
        self.assertEqual(placeholders, {"MS1_UPSTREAM", "AWS_PUBLIC_HOST"})
        compose = (DEPLOY / "azure/compose.yml").read_text(encoding="utf-8")
        self.assertIn('NGINX_ENVSUBST_FILTER: "^(MS1_UPSTREAM|AWS_PUBLIC_HOST)$"', compose)

    def test_routes_and_limits(self):
        graphql = next(b for k, b in self.blocks.items() if "/api/erp/graphql$" in k)
        self.assertIn("rewrite ^/api/erp/graphql$ /graphql break;", graphql)
        self.assertIn("proxy_buffering off;", graphql)
        self.assertIn("proxy_read_timeout 300s;", self.blocks["= /mcp"])
        expediente = self.blocks["/api/expediente/"]
        self.assertIn("client_max_body_size 25M;", expediente)
        self.assertIn("return 503", expediente)
        aws = next(b for k, b in self.blocks.items() if "/api/agendamiento/" in k)
        self.assertIn("proxy_ssl_verify on;", aws)
        self.assertIn("proxy_pass $aws_edge;", aws)
        self.assertEqual(self.blocks["= /api/agendamiento"].strip(),
                         "return 301 /api/agendamiento/$is_args$args;")
        self.assertIn("proxy_connect_timeout 60s;", server_level(self.text))
        self.assertIn("proxy_read_timeout 120s;", server_level(self.text))

    def test_cors_allowlist_is_https_platform_origins_only(self):
        allowed = re.findall(r'"(https?://[^"]+)" \$http_origin;', self.text)
        self.assertEqual(sorted(allowed), ["https://100-60-248-245.sslip.io",
                                           "https://20-83-242-208.sslip.io"])


class EdgeComposeTest(unittest.TestCase):
    def test_only_edge_publishes_host_ports(self):
        for cloud in ("azure", "aws"):
            compose = (DEPLOY / cloud / "compose.yml").read_text(encoding="utf-8")
            services = re.split(r"\n  (?=[a-z-]+:\n)", compose.split("\nservices:\n", 1)[1].split("\nvolumes:", 1)[0])
            for service in services:
                name = service.split(":", 1)[0].strip()
                self.assertEqual("ports:" in service, name == "edge", f"{cloud}/{name}")
            self.assertRegex(compose, r"dental-net:\n\s+external: true")

    def test_caddy_routes(self):
        azure = (DEPLOY / "azure/Caddyfile").read_text(encoding="utf-8")
        self.assertIn("@api path /api/* /api /mcp", azure)
        self.assertIn("reverse_proxy api-gateway:8080", azure)
        self.assertIn("handle /remotes/erp/* {\n\t\treverse_proxy mf-erp-web:80", azure)
        self.assertIn("reverse_proxy shell-web:80", azure)
        aws = (DEPLOY / "aws/Caddyfile").read_text(encoding="utf-8")
        self.assertIn("reverse_proxy ms3-agenda:8001", aws)
        self.assertIn("header Access-Control-Allow-Origin {$SHELL_ORIGIN}", aws)
        self.assertIn("reverse_proxy mf2-web:80", aws)


if __name__ == "__main__":
    unittest.main()
