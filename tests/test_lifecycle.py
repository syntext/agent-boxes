import contextlib
from dataclasses import replace
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import urllib.request
from unittest.mock import patch

from boxes import agent, cli, runtime
from boxes.model import BoxError, Instance, atomic_json, box_type


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {
            "BOXES_STATE_DIR": str(self.root / "state"),
            "BOXES_DATA_DIR": str(self.root / "data"),
            "BOXES_PROJECT_PREFIX": "boxes-test-review",
            "BOXES_PASSWORD_FILE": str(self.root / "state/.passwd"),
        })
        self.environment.start()
        self.instance = Instance(box_type("browser"))
        self.config = self.instance.load(create=True)

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def labels(self, instance=None):
        instance = instance or self.instance
        return {"io.boxes.owner": instance.owner, "io.boxes.type": instance.kind.name,
                "io.boxes.name": instance.name}

    def test_password_options_persist_without_status_disclosure(self):
        for command in ("up", "recreate", "update"):
            with self.subTest(command=command):
                output = io.StringIO()
                with patch.object(runtime, "ensure"), \
                     patch.object(runtime, "inspect", side_effect=[{"State": {"Running": False}}, None]), \
                     contextlib.redirect_stdout(output):
                    self.assertEqual(cli.main([command, "browser", "--password", "fixture-雪-password"]), 0)
                saved = self.instance.load()
                self.assertTrue(saved["password"] == "fixture-雪-password")
                self.assertNotIn(saved["password"], output.getvalue())
                args = cli.parser().parse_args([command, "browser"])
                cli.configure(args, saved)
                self.instance.save(saved)
                self.assertTrue(self.instance.load()["password"] == "fixture-雪-password")

    def test_password_starting_with_a_hyphen_is_rejected_before_startup(self):
        output = io.StringIO()
        with patch.object(runtime, "ensure") as ensure, contextlib.redirect_stderr(output):
            self.assertEqual(cli.main(["up", "browser", "--password=-fixture"]), 1)
        ensure.assert_not_called()
        self.assertEqual(output.getvalue(), "box: --password must not begin with a hyphen.\n")
        self.assertTrue(self.instance.load()["password"] == self.config["password"])

    def test_new_instance_omitted_password_retains_random_fallback(self):
        other = Instance(box_type("browser"), "other").load(create=True)
        original = other["password"]
        cli.configure(cli.parser().parse_args(["up", "browser", "other"]), other)
        self.assertTrue(bool(original) and other["password"] == original)
        self.assertTrue(original != self.config["password"])

    def test_existing_instance_keeps_its_password_when_the_default_file_appears(self):
        path = Path(os.environ["BOXES_PASSWORD_FILE"])
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text("fixture-shared-password\n")
        path.chmod(0o600)
        self.assertEqual(self.instance.load()["password"], self.config["password"])
        self.assertEqual(Instance(box_type("browser"), "later").load(create=True)["password"],
                         "fixture-shared-password")

    def test_invalid_password_is_rejected_without_echo_or_saved_change(self):
        for password in ("", "fixture\nsecret", "fixture\x00secret", "fixture\x7fsecret", "fixture\x85secret"):
            output = io.StringIO()
            with patch.object(runtime, "ensure") as ensure, contextlib.redirect_stderr(output):
                self.assertEqual(cli.main(["up", "browser", "--password", password]), 1)
            ensure.assert_not_called()
            self.assertTrue(self.instance.load()["password"] == self.config["password"])
            self.assertEqual(output.getvalue(), "box: --password must be nonempty and contain no control characters.\n")

    def docker(self, labels=None, absent=False):
        calls = []

        def run(arguments, **kwargs):
            calls.append(arguments)
            if arguments[:3] == ["docker", "container", "inspect"] and arguments[3] != "fixture-id" and absent:
                return subprocess.CompletedProcess(arguments, 1, "", "No such container")
            if "inspect" in arguments:
                return subprocess.CompletedProcess(arguments, 0, json.dumps([
                    {"Config": {"Labels": self.labels() if labels is None else labels}}
                ]), "")
            if arguments[:2] == ["docker", "ps"]:
                return subprocess.CompletedProcess(arguments, 0, "fixture-id\n", "")
            return subprocess.CompletedProcess(arguments, 0, "", "")

        return calls, run

    def test_named_container_requires_each_exact_identity_label(self):
        for key in self.labels():
            for value in (None, "foreign", 42):
                with self.subTest(key=key, value=value):
                    labels = self.labels() | {key: value}
                    _, run = self.docker(labels)
                    with patch("boxes.runtime.run", side_effect=run):
                        with self.assertRaises(BoxError):
                            runtime.inspect(self.instance)

    def test_every_compose_mutation_refuses_foreign_project_container(self):
        for operation in (["pull"], ["build"], ["up", "--force-recreate"], ["create"], ["down"]):
            for key in self.labels():
                with self.subTest(operation=operation, key=key):
                    calls, run = self.docker(self.labels() | {key: "foreign"})
                    with patch("boxes.runtime.run", side_effect=run):
                        with self.assertRaises(BoxError):
                            runtime.compose(self.instance, self.root / "compose.json", operation)
                    self.assertFalse(any(call[:2] == ["docker", "compose"] for call in calls))

    def test_prefix_collision_does_not_share_container_identity(self):
        with patch.dict(os.environ, {"BOXES_PROJECT_PREFIX": "boxes-test"}):
            browser = Instance(box_type("browser"), "android-probe")
        with patch.dict(os.environ, {"BOXES_PROJECT_PREFIX": "boxes-test-browser"}):
            android = Instance(box_type("android"), "probe")
        self.assertEqual(browser.project, android.project)
        self.assertEqual(browser.owner, android.owner)
        _, run = self.docker(self.labels(android))
        with patch("boxes.runtime.run", side_effect=run), self.assertRaises(BoxError):
            runtime.inspect(browser)

    def test_project_scan_checks_containers_after_owned_service(self):
        responses = [
            subprocess.CompletedProcess([], 0, "owned-id foreign-id\n", ""),
            subprocess.CompletedProcess([], 0, json.dumps([{"Config": {"Labels": self.labels()}}]), ""),
            subprocess.CompletedProcess([], 0, json.dumps([
                {"Config": {"Labels": self.labels() | {"io.boxes.name": "other"}}}]), ""),
        ]
        with patch("boxes.runtime.run", side_effect=responses) as run:
            with self.assertRaises(BoxError):
                runtime.compose(self.instance, self.root / "compose.json", ["up"])
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args.args[0], ["docker", "container", "inspect", "foreign-id"])

    def test_equal_and_nested_roots_are_rejected_before_lock_creation(self):
        for state, data in (("overlap", "overlap"), ("overlap/state", "overlap"),
                            ("overlap", "overlap/data")):
            with self.subTest(state=state, data=data), patch.dict(os.environ, {
                "BOXES_STATE_DIR": str(self.root / state), "BOXES_DATA_DIR": str(self.root / data),
            }):
                with self.assertRaises(BoxError):
                    Instance(box_type("browser"))
                self.assertFalse((self.root / state / "browser/default/lock").exists())

    def test_saved_data_cannot_contain_state_even_after_environment_changes(self):
        for data in (self.instance.directory, self.instance.state_root.parent):
            with self.subTest(data=data):
                atomic_json(self.instance.directory / "instance.json", self.config | {"data": str(data)})
                with self.assertRaises(BoxError):
                    self.instance.load()

    def test_symlinked_roots_and_saved_paths_are_resolved(self):
        link = self.root / "alias"
        link.symlink_to(self.instance.state_root, target_is_directory=True)
        with patch.dict(os.environ, {"BOXES_DATA_DIR": str(link)}):
            with self.assertRaises(BoxError):
                Instance(box_type("browser"))
        atomic_json(self.instance.directory / "instance.json", self.config | {"data": str(link)})
        with self.assertRaises(BoxError):
            self.instance.load()

    def test_per_instance_symlinks_cannot_put_state_inside_managed_data(self):
        for target in ("data", "state"):
            with self.subTest(target=target):
                name = "alias-" + target
                if target == "data":
                    link = self.instance.data_root / "browser" / name
                    destination = self.instance.state_root
                else:
                    link = self.instance.state_root / "browser" / name
                    destination = self.instance.data_root
                link.parent.mkdir(parents=True, exist_ok=True)
                link.symlink_to(destination, target_is_directory=True)
                with self.assertRaises(BoxError):
                    Instance(box_type("browser"), name)

    def test_purge_rejects_unsafe_saved_path_before_docker_or_deletion(self):
        atomic_json(self.instance.directory / "instance.json", self.config | {
            "data": str(self.instance.state_root.parent)})
        marker = self.root / "retained"
        marker.write_text("keep")
        with patch("boxes.runtime.run") as run, contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["remove", "browser", "--purge", "--yes"]), 1)
        run.assert_not_called()
        self.assertEqual(marker.read_text(), "keep")
        self.assertTrue((self.instance.directory / "lock").exists())

    def test_remove_refuses_foreign_project_when_named_container_is_absent(self):
        calls, run = self.docker(self.labels() | {"io.boxes.name": "other"}, absent=True)
        with patch("boxes.runtime.run", side_effect=run), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(cli.main(["remove", "browser"]), 1)
        self.assertTrue(any(call[:2] == ["docker", "ps"] for call in calls))
        self.assertFalse(any(call[:2] == ["docker", "compose"] for call in calls))

    def test_remove_ignores_missing_mount_device_and_unsupported_architecture(self):
        for kind in ("browser", "android"):
            with self.subTest(kind=kind):
                instance = Instance(box_type(kind))
                config = instance.load(create=True)
                config["mounts"] = [{"source": str(self.root / "missing"),
                                     "target": "/mnt/gone", "read_only": False}]
                instance.save(config)
                calls, run = self.docker(self.labels(instance), absent=True)
                with patch("boxes.runtime.run", side_effect=run), \
                     patch("boxes.model.platform.machine", return_value="unsupported"), \
                     contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(cli.main(["remove", kind]), 0)
                down = [call for call in calls if call[:2] == ["docker", "compose"]]
                self.assertEqual(len(down), 1)
                self.assertEqual(down[0][-1], "down")
                teardown = json.loads(Path(down[0][down[0].index("--file") + 1]).read_text())
                self.assertEqual(teardown, {"name": instance.project, "services": {
                    "desktop": {"image": instance.kind.image}}})
                self.assertTrue((Path(config["data"]) / "work").exists())
                self.assertTrue((instance.directory / "instance.json").exists())
                with self.assertRaises(BoxError):
                    instance.compose(config)

    def test_remove_works_without_required_device_but_startup_refuses(self):
        kind = replace(box_type("android"), devices=[str(self.root / "missing-kvm")])
        instance = Instance(kind)
        config = instance.load(create=True)
        with self.assertRaisesRegex(BoxError, "Required device"):
            instance.compose(config)
        calls, run = self.docker(self.labels(instance))
        with patch("boxes.cli.box_type", return_value=kind), \
             patch("boxes.runtime.run", side_effect=run), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["remove", "android"]), 0)
        self.assertTrue(any(call[:2] == ["docker", "compose"] and call[-1] == "down" for call in calls))

    def test_project_with_matching_identity_allows_each_compose_mutation(self):
        for operation in (["pull"], ["build"], ["up"], ["down"]):
            with self.subTest(operation=operation):
                calls, run = self.docker()
                with patch("boxes.runtime.run", side_effect=run):
                    runtime.compose(self.instance, self.root / "compose.json", operation)
                self.assertEqual(calls[0], ["docker", "ps", "--all", "--quiet", "--filter",
                                           f"label=com.docker.compose.project={self.instance.project}"])
                self.assertEqual(calls[1], ["docker", "container", "inspect", "fixture-id"])
                self.assertEqual(calls[2][-len(operation):], operation)

    def test_startup_connection_reset_retries_instead_of_escaping_as_oserror(self):
        container = {"State": {"Running": True},
                     "NetworkSettings": {"Ports": {"3000/tcp": [{"HostPort": "39223"}]}}}
        config = {"bind": "0.0.0.0", "user": "box", "password": "boxbox",
                  "http": True, "tls_verify": False}
        with patch.object(agent, "inspect", return_value=container), \
             patch("urllib.request.build_opener") as build:
            build.return_value.open.side_effect = ConnectionResetError(104, "Connection reset by peer")
            with self.assertRaisesRegex(BoxError, "Pelorus request failed"):
                agent.request(self.instance, config, "state")

    def test_https_requests_use_the_secure_port(self):
        container = {"State": {"Running": True},
                     "NetworkSettings": {"Ports": {"3001/tcp": [{"HostPort": "39223"}]}}}
        config = {"bind": "0.0.0.0", "user": "box", "password": "boxbox",
                  "http": False, "tls_verify": False}
        with patch.object(agent, "inspect", return_value=container), \
             patch("urllib.request.build_opener") as build:
            build.return_value.open.return_value = io.BytesIO(b'{"state": "ok"}')
            self.assertEqual(agent.request(self.instance, config, "state"), {"state": "ok"})
            request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://127.0.0.1:39223/pelorus/api/state")
        self.assertEqual([type(handler) for handler in build.call_args.args],
                         [urllib.request.ProxyHandler, urllib.request.HTTPSHandler])

    def test_http_requests_skip_the_tls_handler(self):
        container = {"State": {"Running": True},
                     "NetworkSettings": {"Ports": {"3000/tcp": [{"HostPort": "39223"}]}}}
        config = {"bind": "0.0.0.0", "user": "box", "password": "boxbox",
                  "http": True, "tls_verify": False}
        with patch.object(agent, "inspect", return_value=container), \
             patch("urllib.request.build_opener") as build:
            build.return_value.open.return_value = io.BytesIO(b'{"state": "ok"}')
            agent.request(self.instance, config, "state")
            request = build.return_value.open.call_args.args[0]
        self.assertEqual(request.full_url, "http://127.0.0.1:39223/pelorus/api/state")
        self.assertEqual([type(handler) for handler in build.call_args.args],
                         [urllib.request.ProxyHandler])


if __name__ == "__main__":
    unittest.main()
