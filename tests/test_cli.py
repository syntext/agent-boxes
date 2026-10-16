import contextlib
import io
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
