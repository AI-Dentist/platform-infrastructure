"""Guards of the gateway test harness; no Docker needed (fake runner)."""
import importlib.util
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
