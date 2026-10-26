#!/usr/bin/env python3
"""Pruebas HTTP aisladas con Nginx real; no certifica JWT/MCP/PagoFácil."""
import argparse
import contextlib
import http.client
import json
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

IMAGE = "nginx:1.28-alpine"
ROOT = Path(__file__).resolve().parents[1]
HEADERS = {
    "Authorization": "Bearer synthetic-test-token",
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
    "Idempotency-Key": "test-key",
    "Mcp-Session-Id": "session-test",
    "MCP-Protocol-Version": "2025-03-26",
    "Last-Event-ID": "resume-event-test",
    "X-Dev-User": "must-not-reach-erp",
    "X-Correlation-Id": "transport-only",
}
ORIGIN = "http://localhost:4201"
ALLOWED = ["Authorization", "Content-Type", "Accept", "Idempotency-Key",
           "Mcp-Session-Id", "MCP-Protocol-Version", "Last-Event-ID", "X-Correlation-ID"]
PDF = b"%PDF-1.7\n\x00synthetic\xff"
XLSX = b"PK\x03\x04\x00synthetic-xlsx\xff"


def docker(*args):
    result = subprocess.run(["docker", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"docker {' '.join(args)}: {result.stderr.strip()}")
    return result.stdout.strip()


class FakeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *_):
        pass

    def do_OPTIONS(self):
        self.do_POST()

    def do_GET(self):
        self.do_POST()

    def do_DELETE(self):
        self.do_POST()

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        self.server.records.put((self.command, self.path, body, dict(self.headers)))
        status = int(self.headers.get("X-Test-Status", "200"))
        stream = self.headers.get("X-Test-Stream") == "yes"
        payload = PDF if self.path.split("?")[0].endswith("/pdf") else XLSX
        if "/reports/export/" not in self.path:
            payload = b'{"simulated":true}'
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "https://upstream.invalid")
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Expose-Headers", "X-Upstream")
        self.send_header("Access-Control-Allow-Headers", "X-Upstream")
        self.send_header("Access-Control-Allow-Methods", "TRACE")
        self.send_header("Mcp-Session-Id", "returned-session")
        self.send_header("Idempotency-Replayed", "true")
        if "/reports/export/" in self.path:
            kind = "pdf" if payload == PDF else "xlsx"
            content_type = ("application/pdf" if kind == "pdf" else
                            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Disposition", f'attachment; filename="report.{kind}"')
        if stream:
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Transfer-Encoding", "chunked")
        else:
            self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if stream:
            try:
                for part in (b"data: first\n\n", b"data: last\n\n"):
                    self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
                    self.wfile.flush()
                    if part.startswith(b"data: first"):
                        time.sleep(1.5)
                self.wfile.write(b"0\r\n\r\n")
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.wfile.write(payload)


class Harness:
    def __init__(self, config):
        self.config = config
        self.servers = []
        self.containers = []
        self.checks = 0

    def check(self, condition, message):
        if not condition:
            raise AssertionError(message)
        self.checks += 1

    def __enter__(self):
        self.stack = contextlib.ExitStack()
        try:
            docker("image", "inspect", IMAGE)
            for _ in range(3):
                server = ThreadingHTTPServer(("0.0.0.0", 0), FakeHandler)
                server.daemon_threads = True
                server.records = queue.Queue()
                self.servers.append(server)
                threading.Thread(target=server.serve_forever, daemon=True).start()
            self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix=".gateway-test-", dir=ROOT)))
            text = self.config.read_text(encoding="utf-8")
            for port, server in zip((8081, 3001, 8001), self.servers):
                text = text.replace(f"127.0.0.1:{port}",
                                    f"host.docker.internal:{server.server_port}")
            (self.temp / "gateway.conf").write_text(text, encoding="utf-8")
            (self.temp / "nginx.conf").write_text(
                "events {}\nhttp { access_log off; include /test/gateway.conf; }\n",
                encoding="utf-8")
            self.common = ["--pull=never", "--add-host=host.docker.internal:host-gateway",
                           "--mount", f"type=bind,src={self.temp},dst=/test,readonly"]
            name = "erp-gateway-check-" + uuid.uuid4().hex
            self.containers.append(name)
            output = docker("run", "--name", name, *self.common, IMAGE,
                            "nginx", "-t", "-c", "/test/nginx.conf")
            print("PASS nginx -t (real container)")
            self.name = "erp-gateway-test-" + uuid.uuid4().hex
            self.containers.append(self.name)
            docker("run", "-d", "--name", self.name, *self.common,
                   "-p", "127.0.0.1::80", IMAGE,
                   "nginx", "-g", "daemon off;", "-c", "/test/nginx.conf")
            binding = json.loads(docker("inspect", self.name))[0]["NetworkSettings"]["Ports"]["80/tcp"][0]
            self.port = int(binding["HostPort"])
            for _ in range(50):
                try:
                    self.request("GET", "/unmapped")
                    return self
                except OSError:
                    time.sleep(0.1)
            raise RuntimeError("Nginx no respondió en el puerto aislado")
        except BaseException:
            self.__exit__(*sys.exc_info())
            raise

    def __exit__(self, *_):
        errors = []
        for name in reversed(self.containers):
            try:
                docker("rm", "-f", name)
            except RuntimeError as error:
                errors.append(str(error))
        for server in self.servers:
            server.shutdown()
            server.server_close()
        self.stack.close()
        if errors:
            raise RuntimeError("Falló limpieza de recursos propios: " + "; ".join(errors))

    def request(self, method, path, body=None, headers=None):
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        try:
            connection.request(method, path, body=body, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            connection.close()

    def route(self, public, internal, index=0, method="POST", strip_dev=True):
        body = b'{"query":"synthetic","bytes":"preserved"}'
        result = self.request(method, public + "?a=one%20two&a=3", body, HEADERS)
        self.check(result[0] == 200, f"{public}: esperado 200, recibido {result[0]}")
        command, path, received, headers = self.servers[index].records.get(timeout=2)
        normalized = {k.lower(): v for k, v in headers.items()}
        self.check((command, path, received) == (method, internal + "?a=one%20two&a=3", body),
                   f"{public}: método/URI/query/body alterados")
        for key, value in HEADERS.items():
            if key == "X-Dev-User" and strip_dev:
                self.check(key.lower() not in normalized, f"{public}: filtró X-Dev-User")
            else:
                self.check(normalized.get(key.lower()) == value, f"{public}: cabecera {key}")
        print(f"PASS route {public} -> {internal} ({method}, query/body/headers)")

    def legacy(self, baseline=False):
        for index, path in enumerate(("/api/seguridad/probe", "/api/expediente/probe",
                                      "/api/agendamiento/probe")):
            self.route(path, path, index, strip_dev=(index == 0 and not baseline))

    def full(self):
        for public, internal, method in (
            ("/api/erp/graphql", "/graphql", "POST"),
            ("/mcp", "/mcp", "POST"), ("/mcp", "/mcp", "GET"),
            ("/mcp", "/mcp", "DELETE"),
            ("/api/v1/webhooks/pagofacil", "/api/v1/webhooks/pagofacil", "POST"),
            ("/api/v1/reports/export/r/pdf", "/api/v1/reports/export/r/pdf", "GET"),
            ("/api/v1/reports/export/r/xlsx", "/api/v1/reports/export/r/xlsx", "GET")):
            self.route(public, internal, method=method)
        self.legacy()
        for kind, payload in (("pdf", PDF), ("xlsx", XLSX)):
            status, headers, data = self.request("GET", "/api/v1/reports/export/r/" + kind)
            headers = dict(headers)
            expected_type = ("application/pdf" if kind == "pdf" else
                             "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            self.check(status == 200 and data == payload, f"{kind}: bytes/status")
            self.check(headers.get("Content-Type") == expected_type, f"{kind}: Content-Type")
            self.check(headers.get("Content-Disposition") == f'attachment; filename="report.{kind}"',
                       f"{kind}: Content-Disposition")
            self.servers[0].records.get(timeout=2)
        self.cors()
        for status in (401, 403, 500):
            result = self.request("POST", "/api/erp/graphql", headers={"X-Test-Status": str(status), "Origin": ORIGIN})
            self.check(result[0] == status and result[2] == b'{"simulated":true}', f"error {status} alterado")
            self.check(dict(result[1]).get("Access-Control-Allow-Origin") == ORIGIN, "CORS en errores")
            self.servers[0].records.get(timeout=2)
        for path in ("/unknown", "/actuator", "/actuator/health", "/actuator/info",
                     "/api/erp/health", "/api/erp/health/details", "/api/erp/graphql/extra", "/mcp/extra"):
            self.check(self.request("GET", path)[0] == 404, f"ruta restringida {path}")
        self.check(self.servers[0].records.empty(), "ruta desconocida alcanzó upstream")
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=6)
        try:
            start = time.monotonic()
            connection.request("POST", "/mcp", headers={"X-Test-Stream": "yes"})
            response = connection.getresponse()
            first = response.read(len(b"data: first\n\n"))
            elapsed = time.monotonic() - start
            self.check(response.status == 200 and first == b"data: first\n\n" and elapsed < 1.2,
                       f"stream retenido hasta final: {elapsed:.2f}s")
            self.check(response.read() == b"data: last\n\n", "stream final alterado")
            print("PASS streaming: primer evento antes de completar upstream")
        finally:
            connection.close()
        self.servers[0].records.get(timeout=2)
        self.servers[0].shutdown()
        self.servers[0].server_close()
        self.check(self.request("POST", "/api/erp/graphql")[0] == 502,
                   "upstream caído no produjo 502")
        print("PASS upstream caído: 502 observado, no éxito de integración")

    def cors(self):
        for origin in (ORIGIN, "https://evil.invalid", "null"):
            for requested in (", ".join(ALLOWED), "X-Dev-User", "X-Forbidden"):
                status, headers, _ = self.request("OPTIONS", "/mcp", headers={
                    "Origin": origin, "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": requested})
                headers = dict(headers)
                permitted = origin == ORIGIN and requested == ", ".join(ALLOWED)
                self.check(status == (204 if permitted else 403), f"preflight {origin} {requested}: {status}")
                if permitted:
                    self.check(headers.get("Access-Control-Allow-Origin") == ORIGIN, "origin preflight")
                    returned = {h.strip().lower() for h in headers.get("Access-Control-Allow-Headers", "").split(",")}
                    self.check(returned == {h.lower() for h in ALLOWED}, "allow headers preflight")
                else:
                    self.check("Access-Control-Allow-Origin" not in headers, "preflight rechazado autorizó origen")
        self.check(self.servers[0].records.empty(), "OPTIONS alcanzó backend")
        self.check(self.request("OPTIONS", "/mcp", headers={
            "Origin": ORIGIN, "Access-Control-Request-Method": "TRACE"})[0] == 403, "TRACE permitido")
        for path in ("/api/erp/graphql", "/mcp", "/api/v1/webhooks/pagofacil",
                     "/api/v1/reports/export/r/pdf", "/api/seguridad/probe"):
            status, headers, _ = self.request("POST", path, headers={"Origin": ORIGIN})
            values = [v for k, v in headers if k.lower() == "access-control-allow-origin"]
            self.check(status == 200 and values == [ORIGIN], f"CORS duplicado {path}: {values}")
            normalized = {k.lower(): v for k, v in headers}
            self.check("access-control-allow-credentials" not in normalized, "credenciales CORS inesperadas")
            self.check(normalized.get("access-control-expose-headers") == "Mcp-Session-Id, Content-Disposition, Idempotency-Replayed", "expose headers")
            self.check(normalized.get("idempotency-replayed") == "true", "replay header perdido")
            self.check("Origin" in normalized.get("vary", ""), "falta Vary Origin")
            self.servers[0].records.get(timeout=2)
        status, headers, _ = self.request("GET", "/mcp", headers={"Origin": "https://evil.invalid"})
        self.check(status == 200 and not any(k.lower().startswith("access-control-") for k, _ in headers),
                   "origen no permitido obtuvo cabeceras CORS")
        self.servers[0].records.get(timeout=2)
        print("PASS CORS: allowlist/preflight/errores/sin duplicados")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-config", type=Path, help="Configuración previa externa; no consulta historial Git")
    parser.add_argument("--legacy-only", action="store_true", help="Diferencial de URI/método/query/body/cabeceras legacy")
    args = parser.parse_args()
    config = args.baseline_config or ROOT / "gateway/nginx/gateway.conf"
    try:
        with Harness(config) as harness:
            if args.legacy_only:
                harness.legacy(baseline=bool(args.baseline_config))
            else:
                harness.full()
            print(f"PASS {harness.checks} assertions; transporte simulado, no certificación backend")
        return 0
    except (AssertionError, OSError, RuntimeError, queue.Empty) as error:
        print(f"FAIL: {type(error).__name__}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
