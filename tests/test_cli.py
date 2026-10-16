import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from boxes import cli


class PassThroughTests(unittest.TestCase):
    def test_adb_arguments_and_instance_names_are_unambiguous(self):
        cases = [
            (["--", "reboot"], "default", ["reboot"]),
            (["--", "devices"], "default", ["devices"]),
            (["--", "-s", "SERIAL", "shell", "id"], "default", ["-s", "SERIAL", "shell", "id"]),
            (["phone", "--", "reboot"], "phone", ["reboot"]),
            (["phone", "--", "-s", "SERIAL", "shell"], "phone", ["-s", "SERIAL", "shell"]),
            (["default", "--", "devices"], "default", ["devices"]),
            (["reboot", "--", "reboot"], "reboot", ["reboot"]),
            (["devices", "--", "shell", "id"], "devices", ["shell", "id"]),
        ]
        for arguments, name, expected in cases:
            with self.subTest(arguments=arguments), patch.object(cli.Instance, "load", return_value={}), \
                    patch.object(cli.runtime, "execute", return_value=0) as execute:
                self.assertEqual(cli.main(["adb", "android", *arguments]), 0)
                instance, actual = execute.call_args.args
                self.assertEqual(instance.name, name)
                self.assertEqual(actual, ["adb", *expected])
                execute.assert_called_once()

    def test_pass_through_requires_delimiter_and_arguments(self):
        for command in ("adb", "exec"):
            for arguments in (["reboot"], ["phone", "reboot"], ["--"], ["phone", "--"]):
                with self.subTest(command=command, arguments=arguments), contextlib.redirect_stderr(io.StringIO()), \
                        patch.object(cli.Instance, "load") as load, self.assertRaises(SystemExit) as error:
                    cli.main([command, "android", *arguments])
                self.assertEqual(error.exception.code, 2)
                load.assert_not_called()

    def test_exec_preserves_flag_first_arguments(self):
        with patch.object(cli.Instance, "load", return_value={}), \
                patch.object(cli.runtime, "execute", return_value=0) as execute:
            self.assertEqual(cli.main(["exec", "browser", "--", "env", "--", "printf", "hello"]), 0)
            self.assertEqual(execute.call_args.args[0].name, "default")
            self.assertEqual(execute.call_args.args[1], ["env", "--", "printf", "hello"])


class ListTests(unittest.TestCase):
    def test_list_does_not_require_a_browser_registry_entry(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.dict(os.environ, {"BOXES_STATE_DIR": temporary + "/state", "BOXES_DATA_DIR": temporary + "/data"}), \
                patch.object(cli, "registry", return_value={"bambu": cli.box_type("bambu")}), \
                patch.object(cli, "box_type", side_effect=AssertionError("list must use the registry")), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(cli.main(["list", "--json"]), 0)
        self.assertEqual(json.loads(output.getvalue()), [])

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {"BOXES_STATE_DIR": str(directory / "state"),
                                                  "BOXES_DATA_DIR": str(directory / "data")})
        self.environment.start()

    def tearDown(self):
        self.environment.stop()
        self.temporary.cleanup()

    def run_list(self, *options):
        stdout = io.StringIO()
        with patch.object(cli.runtime, "inspect", return_value=None), contextlib.redirect_stdout(stdout):
            self.assertEqual(cli.main(["list", *options]), 0)
        return stdout.getvalue()

    def test_list_shows_bind_port_and_url_without_password(self):
        with patch("boxes.runtime.socket.gethostname", return_value="desktop-host"):
            for name, bind, port in (("open", "0.0.0.0", 41001), ("local", "127.0.0.1", None)):
                instance = cli.Instance(cli.box_type("browser"), name)
                config = instance.load(create=True)
                config.update(bind=bind, published_port=port)
                instance.save(config)
            plain = self.run_list()
            listed = self.run_list("--json")
        self.assertEqual(plain.splitlines(), [
            "TYPE     NAME   STATE   BIND       PORT   URL",
            "browser  local  absent  127.0.0.1  -      -",
            "browser  open   absent  0.0.0.0    41001  https://desktop-host:41001/"])
        self.assertEqual([(value["bind"], value["port"]) for value in json.loads(listed)],
                         [("127.0.0.1", None), ("0.0.0.0", 41001)])
        self.assertNotIn(config["password"], plain + listed)
