import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class AndroidTests(unittest.TestCase):
    def test_unprovisioned_emulator_can_be_stopped_repeatedly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            helper = root / "box-emulator"
            helper.symlink_to(Path("android-devbox/box-android").resolve())
            environment = os.environ | {"ANDROID_HOME": str(root / "sdk"), "ANDROID_AVD_HOME": str(root / "android/avd")}
            status = subprocess.run(["python3", str(helper), "status"], env=environment, capture_output=True, text=True)
            self.assertEqual(status.returncode, 0)
            self.assertEqual(json.loads(status.stdout), {"state": "sdk-missing", "booted": False})
            for _ in range(2):
                stopped = subprocess.run(["python3", str(helper), "stop"], env=environment, capture_output=True, text=True)
                self.assertEqual(stopped.returncode, 0)
                self.assertEqual(stopped.stdout.strip(), "Emulator already stopped. SDK is not installed.")
            start = subprocess.run(["python3", str(helper), "start"], env=environment, capture_output=True, text=True)
            self.assertEqual(start.returncode, 1)
            self.assertIn("Install or seed the SDK", start.stderr)


if __name__ == "__main__":
    unittest.main()
