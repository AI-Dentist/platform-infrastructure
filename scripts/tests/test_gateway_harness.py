"""Guards of the gateway test harness; no Docker needed (fake runner)."""
import contextlib
import importlib.util
import io
import http.client
import os
import socket
import tempfile
from pathlib import Path
import subprocess
import unittest
from unittest import mock

SCRIPT = Path(__file__).resolve().parents[1] / "test_gateway.py"
LABEL = "gentle.gateway.test.run"


def load_harness():
    spec = importlib.util.spec_from_file_location("gateway_harness_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDocker:
    """In-memory docker CLI: create/ls/inspect/rm for containers and networks."""

    def __init__(self):
        self.items = {}  # id -> {kind, name, label}
        self.calls = []
        self.counter = 0
        self.fail_after_create = False
        self.garbage_id = False

    def add(self, kind, name, label):
        self.counter += 1
        identifier = f"{self.counter:064x}"
        self.items[identifier] = {"kind": kind, "name": name, "label": label}
        return identifier

    def __call__(self, args):
        self.calls.append(list(args))
        assert args[0] == "docker"
        kind, action = args[1], args[2]
        if action == "create":
            label = args[args.index("--label") + 1].split("=", 1)[1]
            name = args[args.index("--name") + 1] if "--name" in args else args[-1]
            identifier = self.add(kind, name, label)
            if self.fail_after_create:
                raise RuntimeError("docker timed out after create")
            return "not-an-id" if self.garbage_id else identifier
        if action == "ls":
            wanted = args[args.index("--filter") + 1].split("=", 2)[2]
            return "\n".join(i for i, v in self.items.items()
                             if v["kind"] == kind and v["label"] == wanted)
        if action == "inspect":
            item = self.items[args[-1]]
            if "{{.Name}}" in args[args.index("--format") + 1]:
                return f'/{item["name"]}|{item["label"]}'
            return item["label"]
        if action == "rm":
            del self.items[args[-1]]
            return args[-1]
        raise AssertionError(args)


class HarnessGuardTests(unittest.TestCase):
    def setUp(self):
        self.mod = load_harness()

    def test_fake_upstreams_bind_loopback_only(self):
        self.assertNotIn("0.0.0.0", SCRIPT.read_text(encoding="utf-8"))
        server = self.mod.start_fake_upstream()
        try:
            self.assertEqual(server.server_address[0], "127.0.0.1")
        finally:
            server.shutdown()
            server.server_close()

    def test_linux_transport_and_generated_fixture_mount(self):
        for platform, engine, native in (("linux", "Docker Engine", True),
                                         ("linux", "Docker Desktop", False),
                                         ("win32", "Docker Desktop", False),
                                         ("darwin", "Docker Desktop", False)):
            with self.subTest(platform=platform, engine=engine):
                docker = FakeDocker()
                def run(args):
                    if args[1:3] == ["info", "--format"]:
                        return engine
                    if args[1:3] == ["image", "inspect"]:
                        return ""
                    if args[1:3] == ["container", "start"]:
                        if "-a" in args:
                            return ""
                        raise RuntimeError("stop before live HTTP")
                    if args[1:3] == ["inspect", "--format"]:
                        return "0"
                    return docker(args)
                servers = [mock.Mock(server_port=9000 + i) for i in range(3)]
                generated = []
                def start(*args):
                    generated.append(args)
                    return servers[len(generated) - 1]
                config = self.mod.ROOT / "gateway/nginx/gateway.conf"
                temporary = tempfile.TemporaryDirectory
                def tempdir(*args, **kwargs):
                    if os.name == "nt" and kwargs.get("dir") == "/tmp":
                        kwargs.pop("dir")  # emulate Linux's short system temp on Windows
                    return temporary(*args, **kwargs)
                with mock.patch.object(self.mod.tempfile, "TemporaryDirectory", side_effect=tempdir), \
                     mock.patch.object(self.mod.sys, "platform", platform), \
                     mock.patch.dict(self.mod.os.environ, {}, clear=True), \
                     mock.patch.object(self.mod, "make_runner", return_value=run), \
                     mock.patch.object(self.mod, "start_fake_upstream", side_effect=start), \
                     mock.patch.object(self.mod.os, "chmod") as chmod, \
                     contextlib.redirect_stdout(io.StringIO()), \
                     mock.patch.object(Path, "write_text") as write:
                    with self.assertRaisesRegex(RuntimeError, "stop before live HTTP"):
                        with self.mod.Harness(config):
                            pass
                text = write.call_args_list[0].args[0]
                creates = [c for c in docker.calls if c[1:3] == ["container", "create"]]
                for name in ("erp", "ms2", "ms3"):
                    if native:
                        self.assertIn(f"unix:/fixtures/{name}.sock", text)
                self.assertIn("proxy_pass http://unix:/fixtures/ms3.sock:;" if native else
                              "proxy_pass http://host.docker.internal:9002;", text)
                self.assertIn("server unix:/fixtures/erp.sock;" if native else
                              "server host.docker.internal:9000;", text)
                self.assertIn("proxy_pass http://unix:/fixtures/ms2.sock:;" if native else
                              "proxy_pass http://host.docker.internal:9001;", text)
                self.assertEqual(all(bool(args) for args in generated), native)
                for create in creates:
                    self.assertEqual(any("dst=/fixtures,readonly" in a for a in create), native)
                self.assertEqual(docker.items, {})
                if native:
                    self.assertEqual([c.args[1] for c in chmod.call_args_list], [0o700, 0o755])
                    self.assertFalse(generated[0][0].parent.exists())
                for server in servers:
                    server.shutdown.assert_called_once()
                    server.server_close.assert_called_once()

    def test_remote_native_linux_rejected_before_fixture_creation(self):
        run = mock.Mock(side_effect=["", "Docker Engine"])
        with mock.patch.object(self.mod.sys, "platform", "linux"), \
             mock.patch.dict(self.mod.os.environ, {"DOCKER_HOST": "tcp://remote:2375"}, clear=True), \
             mock.patch.object(self.mod, "make_runner", return_value=run), \
             mock.patch.object(self.mod, "start_fake_upstream") as start:
            with self.assertRaisesRegex(RuntimeError, "require a local Unix Docker endpoint"):
                with self.mod.Harness(SCRIPT):
                    pass
            start.assert_not_called()
            self.assertEqual(run.call_count, 2)

    def test_partial_fixture_start_is_cleaned(self):
        server = mock.Mock()
        with mock.patch.object(self.mod.sys, "platform", "darwin"), \
             mock.patch.object(self.mod, "make_runner", return_value=mock.Mock()), \
             mock.patch.object(self.mod, "start_fake_upstream",
                               side_effect=[server, RuntimeError("fixture failed")]):
            with self.assertRaisesRegex(RuntimeError, "fixture failed"):
                with self.mod.Harness(SCRIPT):
                    pass
        server.shutdown.assert_called_once()
        server.server_close.assert_called_once()

    @unittest.skipUnless(os.name == "posix" and hasattr(socket, "AF_UNIX"),
                         "native Unix HTTP fixture unavailable on Windows")
    def test_unix_fixture_serves_http_and_preserves_request(self):
        with tempfile.TemporaryDirectory(prefix="gw-test-") as directory:
            path = Path(directory) / "erp.sock"
            server = self.mod.start_fake_upstream(path)
            connection = http.client.HTTPConnection("localhost")
            connection.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                connection.sock.connect(str(path))
                connection.request("POST", "/graphql?a=1", b"synthetic")
                response = connection.getresponse()
                self.assertEqual((response.status, response.read()), (200, b'{"simulated":true}'))
                method, uri, body, _ = server.records.get(timeout=2)
                self.assertEqual((method, uri, body), ("POST", "/graphql?a=1", b"synthetic"))
                self.assertEqual(path.stat().st_mode & 0o777, 0o666)
            finally:
                connection.close()
                server.shutdown()
                server.server_close()

    def test_child_env_is_allowlist_with_pinned_docker_engine(self):
        source = {"PATH": "p", "SystemRoot": "r", "AWS_SECRET_ACCESS_KEY": "s",
                  "DOCKER_HOST": "tcp://elsewhere", "DOCKER_CONFIG": "private",
                  "HTTP_PROXY": "x"}
        env = self.mod.child_env(source, {"DOCKER_CONFIG": "empty",
                                          "DOCKER_HOST": self.mod.DOCKER_HOST})
        self.assertEqual(env["DOCKER_CONFIG"], "empty")
        self.assertEqual(env["DOCKER_HOST"], "npipe:////./pipe/dockerDesktopLinuxEngine")
        self.assertEqual(env["PATH"], "p")
        for leaked in ("AWS_SECRET_ACCESS_KEY", "HTTP_PROXY"):
            self.assertNotIn(leaked, env)

    def test_docker_endpoint_follows_platform_without_private_config(self):
        class StopBeforeDocker(RuntimeError):
            pass

        cases = [("linux", None), ("darwin", None),
                 ("linux", "unix:///run/user/1000/docker.sock"),
                 ("win32", "unix:///ignored.sock")]
        for platform, endpoint in cases:
            with self.subTest(platform=platform, endpoint=endpoint):
                source = {"PATH": "p", "DOCKER_CONFIG": "private"}
                if endpoint:
                    source["DOCKER_HOST"] = endpoint
                with mock.patch.dict(self.mod.os.environ, source, clear=True), \
                     mock.patch.object(self.mod.sys, "platform", platform), \
                     mock.patch.object(self.mod, "make_runner") as runner:
                    runner.return_value.side_effect = StopBeforeDocker()
                    with self.assertRaises(StopBeforeDocker):
                        with self.mod.Harness(SCRIPT):
                            pass
                    env = runner.call_args.args[0]
                expected = self.mod.DOCKER_HOST if platform == "win32" else endpoint
                self.assertEqual(env.get("DOCKER_HOST"), expected)
                self.assertNotEqual(env["DOCKER_CONFIG"], "private")

    def test_docker_runner_always_bounds_time_and_uses_given_env(self):
        env = {"DOCKER_CONFIG": "empty"}
        done = subprocess.CompletedProcess([], 0, stdout="ok\n", stderr="")
        with mock.patch.object(self.mod.subprocess, "run", return_value=done) as run:
            self.assertEqual(self.mod.make_runner(env)(["docker", "ps"]), "ok")
        self.assertEqual(run.call_args.kwargs["env"], env)
        self.assertGreater(run.call_args.kwargs["timeout"], 0)
        expired = subprocess.TimeoutExpired(["docker"], 1)
        with mock.patch.object(self.mod.subprocess, "run", side_effect=expired):
            with self.assertRaisesRegex(RuntimeError, "timed out"):
                self.mod.make_runner(env)(["docker", "ps"])

    def test_created_resources_are_recorded_by_immutable_id_and_removed(self):
        docker = FakeDocker()
        owned = self.mod.OwnedResources(docker, "owner-1")
        network = owned.create("network", "net")
        container = owned.create("container", "web", "--network", network)
        self.assertRegex(network, "^[0-9a-f]{64}$")
        self.assertEqual(owned.ids, {"container": [container], "network": [network]})
        create = next(c for c in docker.calls if c[2] == "create" and c[1] == "container")
        self.assertIn("--pull=never", create)
        self.assertIn(f"{LABEL}=owner-1", create)
        self.assertEqual(owned.cleanup(), [])
        self.assertEqual(docker.items, {})

    def test_cleanup_never_touches_foreign_resources(self):
        docker = FakeDocker()
        foreign = docker.add("container", "owner-1-web", "someone-else")
        unlabeled = docker.add("network", "owner-1-net", "")
        owned = self.mod.OwnedResources(docker, "owner-1")
        owned.create("container", "web")
        self.assertEqual(owned.cleanup(), [])
        self.assertEqual(set(docker.items), {foreign, unlabeled})
        removed = [c for c in docker.calls if c[2] == "rm"]
        self.assertTrue(all(foreign not in c and unlabeled not in c for c in removed))

    def test_remove_refuses_foreign_resource_by_label(self):
        docker = FakeDocker()
        foreign = docker.add("container", "x", "someone-else")
        with self.assertRaisesRegex(RuntimeError, "Refusing cleanup"):
            self.mod.remove_owned(docker, foreign, "container", "owner-1")
        self.assertIn(foreign, docker.items)
        owned = self.mod.OwnedResources(docker, "owner-1")
        owned.intended["container"].add("x")
        owned.ids["container"].append(foreign)  # a mis-recorded ID must still be refused
        self.assertEqual(len(owned.cleanup()), 1)
        self.assertIn(foreign, docker.items)

    def test_uncertain_create_is_recovered_by_label_and_intended_name(self):
        for mode in ("fail_after_create", "garbage_id"):
            with self.subTest(mode=mode):
                docker = FakeDocker()
                same_name_foreign = docker.add("container", "owner-1-web", "someone-else")
                unintended = docker.add("container", "owner-1-other", "owner-1")
                setattr(docker, mode, True)
                owned = self.mod.OwnedResources(docker, "owner-1")
                with self.assertRaises(RuntimeError):
                    owned.create("container", "web")
                self.assertEqual(owned.ids["container"], [])
                self.assertEqual(owned.cleanup(), [])
                self.assertEqual(set(docker.items), {same_name_foreign, unintended})


if __name__ == "__main__":
    unittest.main()
