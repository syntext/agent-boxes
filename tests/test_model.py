import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from boxes.cli import configure, parser
from boxes.model import (BoxError, Instance, atomic_json, box_type, env_pair, mount, new_password, password_file,
                         validate_mounts)
from boxes.runtime import inspect


class ModelTests(unittest.TestCase):
    def test_unknown_type_choices_come_from_the_registry(self):
        with patch("boxes.model.registry", return_value={"studio": box_type("bambu")}):
            with self.assertRaisesRegex(BoxError, r"Choose from studio\.$"):
                box_type("unknown")

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"BOXES_STATE_DIR": str(self.directory / "state"),
                                                  "BOXES_DATA_DIR": str(self.directory / "data"),
                                                  "BOXES_PASSWORD_FILE": str(self.directory / "state/.passwd")})
        self.environment.start()

    def write_password_file(self, content):
        path = Path(os.environ["BOXES_PASSWORD_FILE"])
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.write_text(content)
        path.chmod(0o600)
        return path

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def test_saved_overrides_survive_new_instance_object(self):
        instance = Instance(box_type("browser-box"), "research")
        with instance.lock():
            config = instance.load(create=True)
            configure(parser().parse_args(["up", "browser", "research", "--env", "TZ=Europe/Amsterdam", "--port", "41001"]), config)
            instance.save(config)
        reopened = Instance(box_type("browser"), "research")
        config = reopened.load()
        self.assertEqual((config["environment"], config["port"]), ({"TZ": "Europe/Amsterdam"}, 41001))
        self.assertEqual((reopened.directory / "instance.json").stat().st_mode & 0o777, 0o600)
        self.assertEqual(reopened.compose(config)["services"]["desktop"]["ports"],
                         [{"target": 3001, "published": "41001", "host_ip": "0.0.0.0", "protocol": "tcp"}])

    def test_generated_passwords_avoid_a_leading_hyphen(self):
        with patch("boxes.model.secrets.token_urlsafe", side_effect=["-openssl-option", "-again", "usable"]):
            self.assertEqual(new_password(), "usable")
        self.assertFalse(new_password().startswith("-"))

    def test_password_file_defaults_to_the_state_root(self):
        with patch.dict(os.environ, {"BOXES_PASSWORD_FILE": ""}):
            self.assertEqual(password_file(self.directory / "state"), self.directory / "state/.passwd")

    def test_password_file_supplies_the_default_for_a_new_instance(self):
        self.write_password_file("fixture-shared-password\n")
        self.assertEqual(Instance(box_type("browser"), "shared").load(create=True)["password"],
                         "fixture-shared-password")

    def test_password_option_replaces_the_password_file_default(self):
        self.write_password_file("fixture-shared-password\n")
        instance = Instance(box_type("browser"), "shared")
        config = instance.load(create=True)
        configure(parser().parse_args(["up", "browser", "shared", "--password", "fixture-option-password"]), config)
        self.assertEqual(config["password"], "fixture-option-password")

    def test_password_file_must_be_private(self):
        path = self.write_password_file("fixture-shared-password\n")
        path.chmod(0o644)
        with self.assertRaisesRegex(BoxError, r"readable by other users\. Run: chmod 600 ") as error:
            Instance(box_type("browser"), "shared").load(create=True)
        self.assertNotIn("fixture-shared-password", str(error.exception))

    def test_password_file_is_validated_without_echo(self):
        for content in ("", "\n", "fixture\nsecret\n", "-fixture\n", "fixture\x85secret\n"):
            path = self.write_password_file(content)
            with self.subTest(content=content), self.assertRaises(BoxError) as error:
                Instance(box_type("browser"), "shared").load(create=True)
            self.assertIn(str(path), str(error.exception))
            self.assertNotIn("fixture", str(error.exception))

    def test_password_file_directory_is_rejected(self):
        path = Path(os.environ["BOXES_PASSWORD_FILE"])
        path.mkdir(parents=True, mode=0o700)
        with self.assertRaisesRegex(BoxError, r"is a directory"):
            Instance(box_type("browser"), "shared").load(create=True)

    def test_password_file_broken_symlink_is_rejected(self):
        path = Path(os.environ["BOXES_PASSWORD_FILE"])
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        path.symlink_to(path.parent / "missing-password")
        with self.assertRaisesRegex(BoxError, r"is a broken symbolic link\."):
            Instance(box_type("browser"), "shared").load(create=True)

    def test_http_is_opt_in_and_new_instances_use_https(self):
        instance = Instance(box_type("browser"), "plain")
        config = instance.load(create=True)
        self.assertFalse(config["http"])
        configure(parser().parse_args(["up", "browser", "plain", "--http"]), config)
        instance.save(config)
        self.assertEqual(instance.load()["http"], True)
        self.assertEqual(instance.compose(config)["services"]["desktop"]["ports"],
                         [{"target": 3000, "published": "0", "host_ip": "0.0.0.0", "protocol": "tcp"}])
        configure(parser().parse_args(["up", "browser", "plain", "--no-http"]), config)
        self.assertEqual(instance.compose(config)["services"]["desktop"]["ports"][0]["target"], 3001)
        legacy = instance.load(create=False)
        del legacy["http"]
        instance.save(legacy)
        self.assertFalse(instance.load()["http"])
        self.assertEqual(instance.compose(instance.load())["services"]["desktop"]["ports"][0]["target"], 3001)

    def test_new_instance_binds_all_interfaces_unless_overridden(self):
        instance = Instance(box_type("browser"), "loopback")
        config = instance.load(create=True)
        self.assertEqual(config["bind"], "0.0.0.0")
        configure(parser().parse_args(["up", "browser", "loopback", "--bind", "127.0.0.1"]), config)
        instance.save(config)
        self.assertEqual(instance.load()["bind"], "127.0.0.1")

    def test_instance_data_is_separate(self):
        first = Instance(box_type("browser"), "first")
        second = Instance(box_type("browser"), "second")
        a = first.load(create=True)
        b = second.load(create=True)
        (Path(a["data"]) / "work/marker").write_text("first")
        self.assertEqual((Path(a["data"]) / "work/marker").read_text(), "first")
        self.assertFalse((Path(b["data"]) / "work/marker").exists())
        self.assertNotEqual(a["password"], b["password"])

    def test_workspace_replaces_default_without_duplicate_mount(self):
        instance = Instance(box_type("browser"))
        config = instance.load(create=True)
        configure(parser().parse_args(["up", "browser", "--workspace", str(self.directory)]), config)
        volumes = instance.compose(config)["services"]["desktop"]["volumes"]
        self.assertEqual([v for v in volumes if v["target"] == "/work"],
                         [{"type": "bind", "source": str(self.directory), "target": "/work", "read_only": False}])

    def test_mount_validation_and_read_only(self):
        result = mount(str(self.directory), "/mnt/fixture", "ro")
        self.assertEqual(result, {"source": str(self.directory), "target": "/mnt/fixture", "read_only": True})
        for target in ("/config", "/", "/etc", "/mnt/../config", "/mnt/a/", "relative"):
            with self.subTest(target=target), self.assertRaises(BoxError):
                mount(str(self.directory), target)
        with self.assertRaises(BoxError):
            mount("relative", "/mnt/fixture")
        for source in ("/", "/proc", "/sys", "/dev"):
            with self.subTest(source=source), self.assertRaises(BoxError):
                mount(source, "/mnt/kernel")
        with self.assertRaises(BoxError):
            validate_mounts([result, mount(str(self.directory), "/mnt/fixture/child")])

    def test_security_environment_cannot_be_overridden(self):
        self.assertEqual(env_pair("TZ=UTC"), ("TZ", "UTC"))
        for value in ("PASSWORD=bad", "CUSTOM_USER=bad", "PELORUS=false", "FILE__PASSWORD=/work/secret", "bad=x", "PUID=0"):
            with self.subTest(value=value), self.assertRaises(BoxError):
                env_pair(value)

    def test_atomic_file_is_complete_and_private(self):
        path = self.directory / "private/config.json"
        atomic_json(path, {"value": "old"})
        atomic_json(path, {"value": "new"})
        self.assertEqual(json.loads(path.read_text()), {"value": "new"})
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(list(path.parent.glob(".write-*")), [])

    def test_compose_preserves_literal_dollars(self):
        instance = Instance(box_type("browser"))
        config = instance.load(create=True)
        config["environment"]["LITERAL"] = "$HOME ${DO_NOT_EXPAND}"
        path, _ = instance.write_compose(config)
        service = json.loads(path.read_text())["services"]["desktop"]
        self.assertEqual(service["environment"]["LITERAL"], "$$HOME $${DO_NOT_EXPAND}")

    def test_cli_reports_invalid_type_without_traceback(self):
        result = subprocess.run(["./box", "up", "unknown"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Unknown type 'unknown'", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_cli_rejects_path_traversal_name(self):
        result = subprocess.run(["./box", "up", "browser", "../other"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("Names must use", result.stderr)

    def test_concurrent_writers_keep_both_explicit_options(self):
        script = """
import sys, time
from boxes.model import Instance, box_type
instance = Instance(box_type('browser'), 'race')
with instance.lock():
    config = instance.load(create=True)
    config['environment'][sys.argv[1]] = sys.argv[2]
    time.sleep(0.1)
    instance.save(config)
"""
        writers = [subprocess.Popen(["python3", "-c", script, key, value]) for key, value in (("FIRST", "one"), ("SECOND", "two"))]
        self.assertEqual([writer.wait() for writer in writers], [0, 0])
        self.assertEqual(Instance(box_type("browser"), "race").load()["environment"], {"FIRST": "one", "SECOND": "two"})

    def test_container_without_labels_is_not_owned(self):
        response = subprocess.CompletedProcess([], 0, stdout='[{"Config":{"Labels":null}}]', stderr="")
        with patch("boxes.runtime.run", return_value=response):
            with self.assertRaisesRegex(BoxError, "Refusing to touch unrelated container boxes-browser-default"):
                inspect(Instance(box_type("browser")))


if __name__ == "__main__":
    unittest.main()
