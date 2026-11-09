#!/usr/bin/env python3
"""Pruebas HTTP aisladas con Nginx real; no certifica JWT/MCP/PagoFácil."""
import argparse
import contextlib
import http.client
import json
import os
from pathlib import Path
import queue
import re
import socketserver
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
ORIGIN_LOCAL = "http://localhost:4200"
ALLOWED = ["Authorization", "Content-Type", "Accept", "Origin", "X-Requested-With", "Idempotency-Key",
           "Mcp-Session-Id", "MCP-Protocol-Version", "Last-Event-ID", "X-Correlation-ID"]
METHODS = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
# Shell (4200) and the remote dev servers may call every browser surface.
BROWSER_ORIGINS = ("http://localhost:4200", "http://localhost:4201", "http://localhost:4202",
                   "http://localhost:4203", "http://localhost:5173")
# (path, upstream index) of every browser-facing surface.
BROWSER_ROUTES = (("/api/erp/graphql", 0), ("/api/v1/reports/export", 0),
                  ("/api/v1/reports/export/r/pdf", 0), ("/api/expediente/estudios/analizar-imagen", 1),
                  ("/api/agendamiento/ml/clusters", 2))
MB = 1024 * 1024
EXPOSED = "Mcp-Session-Id, Content-Disposition, Idempotency-Replayed"
PDF = b"%PDF-1.7\n\x00synthetic\xff"
XLSX = b"PK\x03\x04\x00synthetic-xlsx\xff"
# 4200 is scoped to these two public surfaces; everything else is 4201-only.
UNSCOPED_FOR_4200 = (
    "/mcp", "/api/v1/webhooks/pagofacil", "/api/seguridad/probe",
    "//mcp", "/api/erp/graphql/../../../mcp",
    "/api/erp/graphql/%2e%2e/%2e%2e/%2e%2e/mcp",
    "/api/erp/graphql/%2E%2E/%2E%2E/%2E%2E/mcp",
    "/api/erp/graphql/../../../api/v1/webhooks/pagofacil",
    "/api/erp/graphql/../../../api/seguridad/probe",
    "/api/v1/reports/export/../../../../mcp",
    "/api/v1/reports/export/%2e%2e/%2e%2e/%2e%2e/%2e%2e/mcp",
    "/api/v1/reports/export/../../../../api/v1/webhooks/pagofacil",
    "/api/v1/reports/export/../../../../api/seguridad/probe",
    "/api/v1/reports/export/../../../../api/erp/graphql/extra",
)

# Harness safety: bounded docker calls, allowlisted environment, owned resources only.
LABEL_KEY = "gentle.gateway.test.run"
DOCKER_HOST = "npipe:////./pipe/dockerDesktopLinuxEngine"
DOCKER_TIMEOUT = 60
OS_KEYS = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP"}
ID_PATTERN = re.compile(r"[0-9a-f]{64}")
KINDS = ("container", "network")


def child_env(source, overrides):
    """Allowlisted child environment; nothing else is inherited."""
    return {**{k: v for k, v in source.items() if k.upper() in OS_KEYS}, **overrides}


def make_runner(env, timeout=DOCKER_TIMEOUT):
    """Run an argv with a bounded time and the given environment only."""
    def run(args):
        try:
            result = subprocess.run(args, env=env, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{' '.join(args[:3])}: timed out after {timeout}s") from None
        if result.returncode:
            raise RuntimeError(f"{' '.join(args[:3])}: {result.stderr.strip()}")
        return result.stdout.strip()
    return run


def label_template(kind):
    labels = ".Config.Labels" if kind == "container" else ".Labels"
    return "{{index " + labels + ' "' + LABEL_KEY + '"}}'


def recover_owned(run, kind, owner, intended_names):
    """Find resources carrying this owner label AND one of the intended names."""
    if kind not in KINDS or not owner:
        raise RuntimeError("Invalid recovery scope")
    args = ["docker", kind, "ls", "-q", "--no-trunc"]
    if kind == "container":
        args.append("-a")
    args += ["--filter", f"label={LABEL_KEY}={owner}"]
    found = []
    for identifier in run(args).split():
        value = run(["docker", kind, "inspect", "--format",
                     "{{.Name}}|" + label_template(kind), identifier])
        name, separator, label = value.partition("|")
        if separator and label == owner and name.lstrip("/") in intended_names:
            found.append(identifier)
    return found


def remove_owned(run, resource, kind, owner):
    """Remove a resource only after re-reading its ownership label."""
    if kind not in KINDS or not resource or not owner:
        raise RuntimeError("Invalid cleanup scope")
    label = run(["docker", kind, "inspect", "--format", label_template(kind), resource])
    if label != owner:
        raise RuntimeError("Refusing cleanup: resource ownership does not match this run")
    run(["docker", kind, "rm", *(["-f", "-v"] if kind == "container" else []), resource])


class OwnedResources:
    """Journal of created resources: immutable IDs plus intended names for recovery."""

    def __init__(self, run, owner):
        self.run, self.owner = run, owner
        self.ids = {kind: [] for kind in KINDS}
        self.intended = {kind: set() for kind in KINDS}

    def create(self, kind, suffix, *extra):
        name = f"{self.owner}-{suffix}"
        self.intended[kind].add(name)  # journaled first: an uncertain create stays recoverable
        label = f"{LABEL_KEY}={self.owner}"
        if kind == "container":
            args = ["docker", "container", "create", "--pull=never", "--name", name,
                    "--label", label, *extra]
        else:
            args = ["docker", "network", "create", "--label", label, *extra, name]
        identifier = self.run(args)
        if not ID_PATTERN.fullmatch(identifier):
            raise RuntimeError(f"Uncertain {kind} identifier; left for label+name recovery")
        self.ids[kind].append(identifier)
        return identifier

    def cleanup(self):
        errors = []
        for kind in KINDS:
            if not self.intended[kind]:
                continue
            try:
                recovered = recover_owned(self.run, kind, self.owner, self.intended[kind])
                for identifier in dict.fromkeys([*self.ids[kind], *recovered]):
                    remove_owned(self.run, identifier, kind, self.owner)
                if recover_owned(self.run, kind, self.owner, self.intended[kind]):
                    raise RuntimeError("owned resources remain")
            except RuntimeError as error:
                errors.append(f"{kind}: {error}")
        return errors


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

    def do_PUT(self):
        self.do_POST()

    def do_PATCH(self):
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


def start_fake_upstream(socket_path=None):
    """Desktop loopback TCP by default; private Unix HTTP on native Linux."""
    if socket_path is None:
        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeHandler)
    else:
        factory = getattr(socketserver, "ThreadingUnixStreamServer", None)
        if factory is None:
            raise RuntimeError("Unix HTTP fixtures unavailable on this platform")
        server = factory(str(socket_path), FakeHandler)
        try:
            os.chmod(socket_path, 0o666)  # connectable only inside the private outer directory
        except BaseException:
            server.server_close()
            raise
    server.daemon_threads = True
    server.records = queue.Queue()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class Harness:
    def __init__(self, config):
        self.config = config
        self.servers = []
        self.resources = None
        self.checks = 0

    def check(self, condition, message):
        if not condition:
            raise AssertionError(message)
        self.checks += 1

    def __enter__(self):
        self.stack = contextlib.ExitStack()
        try:
            docker_config = self.stack.enter_context(
                tempfile.TemporaryDirectory(prefix="gateway-docker-config-"))
            overrides = {"DOCKER_CONFIG": docker_config,
                         "HOME": docker_config, "USERPROFILE": docker_config}
            if sys.platform == "win32":
                overrides["DOCKER_HOST"] = DOCKER_HOST
            elif os.environ.get("DOCKER_HOST"):
                overrides["DOCKER_HOST"] = os.environ["DOCKER_HOST"]
            env = child_env(os.environ, overrides)
            self.run = make_runner(env)
            self.run(["docker", "image", "inspect", IMAGE])
            native_linux = False
            if sys.platform == "linux":
                engine = self.run(["docker", "info", "--format", "{{.OperatingSystem}}"])
                native_linux = "docker desktop" not in engine.lower()
                if native_linux and not overrides.get("DOCKER_HOST", "unix://").startswith("unix://"):
                    raise RuntimeError("Native Linux fixtures require a local Unix Docker endpoint")
            fixtures = None
            if native_linux:
                outer = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix="gw-", dir="/tmp")))
                os.chmod(outer, 0o700)
                fixtures = outer / "fixtures"
                fixtures.mkdir(mode=0o755)
                os.chmod(fixtures, 0o755)
            for name in ("erp", "ms2", "ms3"):
                server = start_fake_upstream(fixtures / f"{name}.sock") if fixtures else start_fake_upstream()
                self.servers.append(server)  # retain each fixture even if the next creation fails
            self.temp = Path(self.stack.enter_context(tempfile.TemporaryDirectory(prefix=".gateway-test-", dir=ROOT)))
            text = self.config.read_text(encoding="utf-8")
            for name, port, server in zip(("erp", "ms2", "ms3"), (8081, 3001, 8001), self.servers):
                if fixtures:
                    endpoint = f"unix:/fixtures/{name}.sock" + (":" if name != "erp" else "")
                else:
                    endpoint = f"host.docker.internal:{server.server_port}"
                text = text.replace(f"127.0.0.1:{port}", endpoint)
            (self.temp / "gateway.conf").write_text(text, encoding="utf-8")
            (self.temp / "nginx.conf").write_text(
                "events {}\nhttp { access_log off; include /test/gateway.conf; }\n",
                encoding="utf-8")
            self.resources = OwnedResources(self.run, "gateway-test-" + uuid.uuid4().hex)
            network = self.resources.create("network", "net")
            common = ["--network", network,
                      "--mount", f"type=bind,src={self.temp},dst=/test,readonly"]
            if fixtures:
                common += ["--mount", f"type=bind,src={fixtures},dst=/fixtures,readonly"]
            checker = self.resources.create("container", "check", *common, IMAGE,
                                            "nginx", "-t", "-c", "/test/nginx.conf")
            self.run(["docker", "container", "start", "-a", checker])
            exit_code = self.run(["docker", "inspect", "--format", "{{.State.ExitCode}}", checker])
            self.check(exit_code == "0", f"nginx -t falló: {exit_code}")
            print("PASS nginx -t (real container)")
            server = self.resources.create("container", "server", *common, "-p", "127.0.0.1::80", IMAGE,
                                           "nginx", "-g", "daemon off;", "-c", "/test/nginx.conf")
            self.run(["docker", "container", "start", server])
            binding = json.loads(self.run(["docker", "inspect", server]))[0]["NetworkSettings"]["Ports"]["80/tcp"][0]
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
        errors = self.resources.cleanup() if self.resources else []
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

    def upstream_calls(self, index=0):
        calls = []
        while True:
            try:
                calls.append(self.servers[index].records.get_nowait())
            except queue.Empty:
                return calls

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
        # Slashless proxy prefixes historically redirect locally, including POST
        # and the original query string. No request may reach an upstream here.
        for prefix in ("/api/seguridad", "/api/expediente", "/api/agendamiento"):
            for method in ("GET", "POST"):
                for query in ("", "?a=one%20two&a=3"):
                    status, headers, body = self.request(method, prefix + query, b"synthetic")
                    self.check(status == 301, f"{prefix}: redirect legacy esperado 301, recibido {status}")
                    self.check(dict(headers).get("Location") == "http://127.0.0.1" + prefix + "/" + query,
                               f"{prefix}: Location/query legacy alterado")
                    self.check(b"<title>301 Moved Permanently</title>" in body,
                               f"{prefix}: body de redirect legacy alterado")
                    self.check(all(server.records.empty() for server in self.servers),
                               f"{prefix}: redirect alcanzó upstream")
        print("PASS legacy: redirects sin barra, GET/POST y query preservados")
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
        self.local_browser_profile()
        self.ai_traffic()
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

    def preflight(self, path, origin, method="POST", requested=", ".join(ALLOWED)):
        headers = {"Origin": origin, "Access-Control-Request-Method": method}
        if requested is not None:
            headers["Access-Control-Request-Headers"] = requested
        status, response, _ = self.request("OPTIONS", path, headers=headers)
        return status, [(k.lower(), v) for k, v in response]

    def authorized_cors(self, path, origin, method, requested, payload=None):
        """Valid preflight plus actual request on a route that allows this origin."""
        status, headers = self.preflight(path, origin, method, requested)
        values = dict(headers)
        self.check(status == 204, f"{origin} {path}: preflight {status}")
        self.check([v for k, v in headers if k == "access-control-allow-origin"] == [origin],
                   f"{origin} {path}: ACAO preflight")
        self.check("access-control-allow-credentials" not in values, f"{origin} {path}: credenciales")
        self.check(values.get("access-control-allow-methods") == METHODS, "métodos")
        self.check("origin" in values.get("vary", "").lower(), f"{origin} {path}: Vary")
        self.check(not self.upstream_calls(), f"{origin} {path}: preflight alcanzó upstream")
        status, headers, data = self.request(method, path, headers={"Origin": origin})
        values = dict(headers)
        self.check(status == 200, f"{origin} {path}: actual {status}")
        self.check([v for k, v in headers if k.lower() == "access-control-allow-origin"] == [origin],
                   f"{origin} {path}: ACAO duplicado/ausente")
        self.check("access-control-allow-credentials" not in {k.lower() for k in values},
                   f"{origin} {path}: credenciales")
        self.check({k.lower(): v for k, v in headers}.get("access-control-expose-headers") == EXPOSED,
                   f"{origin} {path}: expose")
        self.check("Content-Disposition" in EXPOSED, "Content-Disposition no expuesto")
        if payload is not None:
            self.check(data == payload, f"{origin} {path}: bytes alterados")
            self.check(values.get("Content-Disposition", "").startswith("attachment; filename="),
                       f"{origin} {path}: Content-Disposition")
        self.check(len(self.upstream_calls()) == 1, f"{origin} {path}: llamadas upstream")

    def ai_traffic(self):
        """S1-S3: shell and remotes reach every browser surface; image uploads up to 25M."""
        for origin in BROWSER_ORIGINS:
            for path, index in BROWSER_ROUTES:
                for method in ("POST", "PATCH"):
                    status, headers = self.preflight(path, origin, method, "Authorization, Content-Type, Origin, X-Requested-With, Idempotency-Key")
                    values = dict(headers)
                    self.check(status == 204, f"{origin} {path} {method}: preflight {status}")
                    self.check(values.get("access-control-allow-origin") == origin, f"{origin} {path}: ACAO preflight")
                    self.check(values.get("access-control-allow-methods") == METHODS, f"{origin} {path}: métodos")
                    self.check(all(s.records.empty() for s in self.servers), f"{origin} {path}: preflight alcanzó upstream")
                status, headers, _ = self.request("GET", path, headers={"Origin": origin})
                self.check(status == 200, f"{origin} {path}: GET {status}")
                self.check([v for k, v in headers if k.lower() == "access-control-allow-origin"] == [origin],
                           f"{origin} {path}: ACAO duplicado/ausente")
                self.servers[index].records.get(timeout=2)
        for method in ("GET", "POST"):
            self.route("/api/v1/reports/export", "/api/v1/reports/export", method=method)
        image = b"\xff\xd8" + b"0" * (20 * MB)
        status, _, _ = self.request("POST", "/api/expediente/estudios/analizar-imagen", image,
                                    {"Content-Type": "image/jpeg"})
        self.check(status == 200, f"imagen 20M rechazada: {status}")
        command, path, received, _ = self.servers[1].records.get(timeout=10)
        self.check(len(received) == len(image), "imagen 20M alterada")
        status, _, _ = self.request("POST", "/api/expediente/estudios/analizar-imagen", b"0" * (26 * MB),
                                    {"Content-Type": "image/jpeg"})
        self.check(status == 413, f"imagen 26M no rechazada: {status}")
        self.check(self.servers[1].records.empty(), "imagen 26M alcanzó MS2")
        print("PASS IA: CORS shell/remotos en superficies del navegador, export base GET/POST, límite 25M")

    def local_browser_profile(self):
        for origin in (ORIGIN, ORIGIN_LOCAL):
            self.authorized_cors("/api/erp/graphql", origin, "POST", ", ".join(ALLOWED))
            self.authorized_cors("/api/v1/reports/export/r/pdf", origin, "GET", "Authorization, Accept", PDF)
            self.authorized_cors("/api/v1/reports/export/r/xlsx", origin, "GET", None, XLSX)
        for origin in ("null", "https://evil.invalid", "http://localhost:4200/", "https://localhost:4200",
                       "http://localhost:42000", "http://localhost:4200.evil.invalid",
                       "http://127.0.0.1:4200", "http://localhost:4204"):
            for path in ("/api/erp/graphql", "/api/v1/reports/export/r/pdf"):
                status, headers = self.preflight(path, origin)
                self.check(status == 403 and not any(k.startswith("access-control-allow") for k, _ in headers),
                           f"{origin} {path}: preflight ajeno {status}")
                status, headers, _ = self.request("POST", path, headers={"Origin": origin})
                self.check(not any(k.lower().startswith("access-control-") for k, _ in headers),
                           f"{origin} {path}: actual ajeno autorizado")
                self.check(len(self.upstream_calls()) == 1, f"{origin} {path}: llamadas upstream")
        # 4200 is never authorized outside the two scoped surfaces, however the path is spelled.
        for path in UNSCOPED_FOR_4200:
            status, headers = self.preflight(path, ORIGIN_LOCAL)
            self.check(status != 204 and not any(k.startswith("access-control-") and k != "vary" for k, _ in headers),
                       f"4200 {path}: preflight autorizado ({status})")
            self.check(not self.upstream_calls(), f"4200 {path}: preflight alcanzó upstream")
            for method in ("POST", "GET"):
                _, headers, _ = self.request(method, path, headers={"Origin": ORIGIN_LOCAL})
                self.check(not any(k.lower().startswith("access-control-") for k, _ in headers),
                           f"4200 {path}: {method} autorizado")
                self.upstream_calls()
        print("PASS CORS 4200: solo GraphQL/export, 4201 intacto, rutas normalizadas sin autorización")


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
