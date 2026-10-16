#!/usr/bin/env python3
import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import secrets
import ssl
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="Run isolated real-Docker checks. Keeps evidence and data. Removes only its own containers.")
    parser.add_argument("--types", nargs="+", choices=["browser", "bambu", "android"], default=["browser", "bambu", "android"])
    parser.add_argument("--sdk-seed", type=Path)
    parser.add_argument("--viewer", action="store_true", help="Also render the shared desktop with agent-browser")
    parser.add_argument("--https", action="store_true", help="Verify boxes on the HTTPS viewer port instead of the default HTTP one")
    parser.add_argument("--keep-running", action="store_true")
    args = parser.parse_args()
    scheme = "https" if args.https else "http"
    internal = 3001 if args.https else 3000
    context = ssl._create_unverified_context() if args.https else None
    tls = ["--https"] if args.https else []
    directory = Path.home() / "work/boxes/verification" / (time.strftime("%Y%m%d-%H%M%S") + "-" + secrets.token_hex(3))
    directory.mkdir(parents=True)
    environment = os.environ | {"BOXES_STATE_DIR": str(directory / "state"), "BOXES_DATA_DIR": str(directory / "data"),
                                "BOXES_PROJECT_PREFIX": "boxes-test-" + secrets.token_hex(3)}
    source_paths = [ROOT / "registry.json", ROOT / "runtime.json", ROOT / "android-devbox/Dockerfile",
                    ROOT / "android-devbox/box-android", *sorted((ROOT / "scripts").glob("*.py")),
                    *sorted((ROOT / "boxes").glob("*.py")), *sorted((ROOT / "tests").glob("*.py"))]

    def source_hashes():
        return {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_paths}

    report = {"directory": str(directory), "checks": [], "passed": False,
              "environment": {key: environment[key] for key in ("BOXES_STATE_DIR", "BOXES_DATA_DIR", "BOXES_PROJECT_PREFIX")},
              "source_sha256": source_hashes()}
    instances = []

    def check(name, condition):
        if not condition:
            raise AssertionError(name)
        report["checks"].append({"name": name, "passed": True})
        print("PASS " + name, flush=True)

    def box(*arguments, parse=True, succeeds=True):
        logged = list(map(str, arguments))
        for index, value in enumerate(logged[:-1]):
            if value == "--password":
                logged[index + 1] = "<redacted>"
        result = subprocess.run([str(ROOT / "box"), *map(str, arguments)], env=environment,
                                capture_output=True, text=True, cwd=ROOT)
        with (directory / "commands.log").open("a") as log:
            log.write(json.dumps(logged) + "\n" + result.stderr + "\n")
        if succeeds and result.returncode:
            raise RuntimeError(f"box {' '.join(logged)} failed. {result.stderr}")
        if not succeeds:
            return result
        return json.loads(result.stdout) if parse else result.stdout

    def ready(kind, name="first"):
        deadline = time.monotonic() + 300
        last = None
        while time.monotonic() < deadline:
            last = box("agent", kind, name, "state", succeeds=False)
            if last.returncode == 0:
                return json.loads(last.stdout)
            time.sleep(2)
        raise RuntimeError(f"{kind} agent did not become ready. {last.stderr}")

    def inspect(kind, name="first"):
        project = box("status", kind, name, "--json")["project"]
        return json.loads(subprocess.check_output(["docker", "inspect", project]))[0]

    def viewer(kind, config, status):
        session = environment["BOXES_PROJECT_PREFIX"] + "-" + kind
        private = directory / f"viewer-{kind}.json"
        auth = base64.b64encode(f'{config["user"]}:{config["password"]}'.encode()).decode()
        private.write_text(json.dumps({"session": session, "ignoreHttpsErrors": args.https,
                                      "headers": json.dumps({"Authorization": "Basic " + auth})}))
        private.chmod(0o600)
        command = ["agent-browser", "--config", str(private)]
        try:
            subprocess.run([*command, "batch", "--json"],
                           input=json.dumps([["set", "credentials", config["user"], config["password"]]]),
                           text=True, check=True, capture_output=True)
            subprocess.run([*command, "open", f'{scheme}://localhost:{status["port"]}/'], check=True, capture_output=True)
            subprocess.run([*command, "wait", "--fn", "Array.from(document.querySelectorAll('video')).some(v => v.readyState === 4 && v.videoWidth > 0)"],
                           check=True, capture_output=True, timeout=90)
            subprocess.run([*command, "set", "viewport", "1920", "1080"], check=True, capture_output=True)
            subprocess.run([*command, "screenshot", str(directory / f"{kind}-viewer.png")], check=True, capture_output=True)
            result = subprocess.check_output([*command, "eval", "JSON.stringify(Array.from(document.querySelectorAll('video')).map(v=>({width:v.videoWidth,height:v.videoHeight,ready:v.readyState})))"], text=True)
            (directory / f"{kind}-viewer.txt").write_text(result)
            check(f"{kind} rendered viewer", "1920" in result and "1080" in result)
        finally:
            subprocess.run(["agent-browser", "--session", session, "close"], capture_output=True)
            private.unlink(missing_ok=True)

    try:
        for kind in args.types:
            instances.append((kind, "first"))
            status = box("up", kind, "first", *tls)
            initial = inspect(kind)
            ready(kind)
            check(f"{kind} running with agent API", status["state"] == "running")
            check(f"{kind} no privileged mode or host network", not initial["HostConfig"]["Privileged"] and initial["HostConfig"]["NetworkMode"] != "host")
            check(f"{kind} exposes only {scheme.upper()}", set(initial["HostConfig"]["PortBindings"]) == {f"{internal}/tcp"})
            config = json.loads(Path(status["config_file"]).read_text())
            check(f"{kind} password absent from status", config["password"] not in json.dumps(status))
            old_password = config["password"]
            replacement = secrets.token_urlsafe(32)
            rotated = box("up", kind, "first", "--password", replacement, "--wait", "900")
            config = json.loads(Path(status["config_file"]).read_text())
            check(f"{kind} supplied password saved", config["password"] == replacement)
            check(f"{kind} password rotation retains port", rotated["port"] == status["port"])
            def authentication(password):
                token = base64.b64encode(f'{config["user"]}:{password}'.encode()).decode()
                request = urllib.request.Request(f'{scheme}://localhost:{status["port"]}/pelorus/api/state',
                                                 headers={"Authorization": "Basic " + token})
                try:
                    with urllib.request.urlopen(request, context=context, timeout=15) as response:
                        return response.status
                except urllib.error.HTTPError as error:
                    code = error.code
                    error.close()
                    return code
            check(f"{kind} old password rejected", authentication(old_password) == 401)
            check(f"{kind} incorrect password rejected", authentication(secrets.token_urlsafe(32)) == 401)
            check(f"{kind} replacement password authenticates", authentication(replacement) == 200)
            box("up", kind, "first")
            check(f"{kind} omitted password preserves credentials", authentication(replacement) == 200 and
                  json.loads(Path(status["config_file"]).read_text())["password"] == replacement)
            initial = inspect(kind)
            requests = [urllib.request.Request(f'{scheme}://localhost:{status["port"]}{endpoint}')
                        for endpoint in ("/", "/pelorus/api/state", "/pelorus/api/desktop/screenshot")]
            requests.append(urllib.request.Request(f'{scheme}://localhost:{status["port"]}/pelorus/api/desktop/control',
                                                  data=json.dumps({"action": "mouse_move", "coordinate": [600, 400]}).encode(),
                                                  headers={"Content-Type": "application/json"}))
            for request in requests:
                try:
                    with urllib.request.urlopen(request, context=context, timeout=15) as response:
                        code = response.status
                except urllib.error.HTTPError as error:
                    code = error.code
                    error.close()
                check(f"{kind} authentication protects {request.get_method()} {request.selector}", code == 401)
            connection = (http.client.HTTPSConnection if args.https else http.client.HTTPConnection)(
                "localhost", status["port"], **({"context": context} if args.https else {}), timeout=15)
            try:
                connection.request("GET", "/api/websockets", headers={
                    "Connection": "Upgrade", "Upgrade": "websocket", "Sec-WebSocket-Version": "13",
                    "Sec-WebSocket-Key": base64.b64encode(secrets.token_bytes(16)).decode()})
                check(f"{kind} authentication protects websocket upgrade /api/websockets", connection.getresponse().status == 401)
            finally:
                connection.close()
            shot = directory / f"{kind}-api.png"
            box("agent", kind, "first", "screenshot", "--output", shot)
            check(f"{kind} actual PNG screenshot", shot.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n")
            check(f"{kind} 1920x1080 desktop", struct.unpack(">II", shot.read_bytes()[16:24]) == (1920, 1080))
            for operation in (("move", "600", "400"), ("key", "Escape")):
                result = box("agent", kind, "first", *operation)
                check(f"{kind} input {' '.join(operation)}", result["result"] == "ok")
            subprocess.run(["docker", "cp", str(ROOT / "scripts/terminal_input.py"),
                            f'{status["project"]}:/work/boxes-terminal-input.py'], check=True, capture_output=True)
            box("exec", kind, "first", "--", "python3", "/work/boxes-terminal-input.py",
                "/work/agent-input.txt", "--launch", parse=False)
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                windows = box("agent", kind, "first", "windows")["windows"]
                terminal = next((window for window in windows if window["title"] == "Boxes-input-proof"
                                 and window["width"] >= 100 and window["height"] >= 100 and window["focused"]), None)
                if terminal:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"{kind} terminal did not open for input verification")
            box("agent", kind, "first", "screenshot", "--output", directory / f"{kind}-terminal.png")
            x, y, width, height = (terminal[key] for key in ("x", "y", "width", "height"))
            check(f"{kind} click endpoint", box("agent", kind, "first", "click", str(x + width // 2), str(y + height // 2))["result"] == "ok")
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                windows = box("agent", kind, "first", "windows")["windows"]
                if any(window["title"] == "Boxes-input-proof" and window["focused"] for window in windows):
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"{kind} terminal lost focus before input")
            box("agent", kind, "first", "text", f"boxes-{kind}-proof")
            box("agent", kind, "first", "key", "Return")
            deadline = time.monotonic() + 20
            while time.monotonic() < deadline:
                result = box("exec", kind, "first", "--", "cat", "/work/agent-input.txt", succeeds=False)
                if result.returncode == 0 and result.stdout == f"boxes-{kind}-proof":
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError(f"{kind} actual terminal did not receive typed text and Return")
            check(f"{kind} typed text reached real terminal", result.stdout == f"boxes-{kind}-proof")
            again = box("up", kind, "first")
            check(f"{kind} up is idempotent", inspect(kind)["Id"] == initial["Id"] and again["port"] == status["port"])
            box("stop", kind, "first", parse=False)
            box("start", kind, "first", parse=False)
            check(f"{kind} stop/start retains port", box("status", kind, "first", "--json")["port"] == status["port"])
            box("restart", kind, "first", parse=False)
            ready(kind)
            check(f"{kind} restart retains port", box("status", kind, "first", "--json")["port"] == status["port"])
            if args.viewer:
                viewer(kind, config, status)
            box("exec", kind, "first", "--", "sh", "-c", "printf first > /config/marker; printf work > /work/marker", parse=False)
            fixture = directory / f"fixture-{kind}"
            fixture.mkdir()
            (fixture / "marker").write_text("read-only fixture")
            box("mount", kind, "first", "set", fixture, "/mnt/fixture", "--mode", "ro")
            check(f"{kind} mount visible", box("exec", kind, "first", "--", "cat", "/mnt/fixture/marker", parse=False) == "read-only fixture")
            denied = box("exec", kind, "first", "--", "touch", "/mnt/fixture/no-write", succeeds=False)
            check(f"{kind} read-only mount enforced", denied.returncode != 0 and not (fixture / "no-write").exists())
            for phase, command in (("running recreate", ("recreate", kind, "first")),
                                   ("running mount removal", ("mount", kind, "first", "remove", "/mnt/fixture"))):
                before = inspect(kind)["Id"]
                box(*command)
                check(f"{kind} {phase} replaces running container", inspect(kind)["Id"] != before and inspect(kind)["State"]["Running"])
                check(f"{kind} {phase} persists config and work", box("exec", kind, "first", "--", "cat", "/config/marker", "/work/marker", parse=False) == "firstwork")
                check(f"{kind} {phase} retains port", box("status", kind, "first", "--json")["port"] == status["port"])
            absent = box("exec", kind, "first", "--", "test", "!", "-e", "/mnt/fixture/marker", succeeds=False)
            check(f"{kind} removed mount absent", absent.returncode == 0)
            box("stop", kind, "first", parse=False)
            for operation in (("set", fixture, "/mnt/fixture", "--mode", "ro"), ("remove", "/mnt/fixture")):
                box("mount", kind, "first", *operation)
                check(f"{kind} stopped mount {operation[0]} stays stopped", not inspect(kind)["State"]["Running"])
            box("up", kind, "first")
            check(f"{kind} stopped mount changes persist config and work", box("exec", kind, "first", "--", "cat", "/config/marker", "/work/marker", parse=False) == "firstwork")
            check(f"{kind} stopped mount changes retain port", box("status", kind, "first", "--json")["port"] == status["port"])
            if kind == "bambu":
                help_text = box("exec", kind, "first", "--", "/opt/bambustudio/AppRun", "--help", parse=False)
                (directory / "bambu-help.txt").write_text(help_text)
                check("Bambu CLI supports slicing", "--slice option" in help_text)
            if kind == "android":
                check("Android starts with emulator stopped", box("emu", kind, "first", "status")["state"] == "sdk-missing")
                if args.sdk_seed:
                    box("mount", kind, "first", "set", args.sdk_seed.resolve(), "/mnt/sdk", "--mode", "ro")
                    ready(kind)
                    box("exec", kind, "first", "--", "box-sdk", "seed", "/mnt/sdk", parse=False)
                    box("mount", kind, "first", "remove", "/mnt/sdk")
                    ready(kind)
                    acceleration = box("exec", kind, "first", "--", "emulator", "-accel-check", parse=False)
                    (directory / "android-acceleration.txt").write_text(acceleration)
                    check("Android KVM acceleration", "KVM" in acceleration)
                    box("emu", kind, "first", "start", "--wait", "240", parse=False)
                    check("Android boot completed", box("emu", kind, "first", "status")["booted"])
                    check("Android adb named instance pass-through", box("adb", kind, "first", "--", "shell", "getprop", "sys.boot_completed", parse=False).strip() == "1")
                    box("agent", kind, "first", "screenshot", "--output", directory / "android-emulator.png")
                    box("emu", kind, "first", "stop", parse=False)
                    box("restart", kind, "first", parse=False)
                    ready(kind)
                    check("Android restart does not start emulator", box("emu", kind, "first", "status")["state"] == "stopped")
                else:
                    report["checks"].append({"name": "Android boot", "skipped": "Supply --sdk-seed or provision a licensed SDK separately."})
        if "browser" in args.types:
            instances.append(("browser", "second"))
            box("up", "browser", "second", *tls)
            ready("browser", "second")
            second = box("exec", "browser", "second", "--", "sh", "-c", "test ! -e /config/marker && test ! -e /work/marker && printf isolated", parse=False)
            check("Browser instance data isolation", second == "isolated")
            box("update", "browser", "first")
            ready("browser")
            check("Update keeps config and work data", box("exec", "browser", "first", "--", "sh", "-c", "cat /config/marker /work/marker", parse=False) == "firstwork")
            box("recreate", "browser", "first", "--env", "TZ=Europe/Amsterdam")
            ready("browser")
            check("Changed option takes effect", box("exec", "browser", "first", "--", "printenv", "TZ", parse=False).strip() == "Europe/Amsterdam")
            box("recreate", "browser", "first")
            ready("browser")
            check("Saved option survives recreation", box("exec", "browser", "first", "--", "printenv", "TZ", parse=False).strip() == "Europe/Amsterdam")
            fixture_image = environment["BOXES_PROJECT_PREFIX"] + "/browser:fixture"
            try:
                for revision in ("one", "two"):
                    dockerfile = f"FROM lscr.io/linuxserver/chromium:latest\nLABEL io.boxes.fixture={revision}\n"
                    build = subprocess.run(["docker", "build", "--tag", fixture_image, "-"], input=dockerfile, text=True, capture_output=True)
                    if build.returncode:
                        raise RuntimeError("Fixture build failed. " + build.stderr)
                    before = inspect("browser")["Image"]
                    box("up" if revision == "one" else "recreate", "browser", "first", *(["--image", fixture_image] if revision == "one" else []))
                    ready("browser")
                    check(f"Image revision {revision} takes effect", inspect("browser")["Image"] != before)
                check("Image rebuild preserves data", box("exec", "browser", "first", "--", "sh", "-c", "cat /config/marker /work/marker", parse=False) == "firstwork")
            finally:
                subprocess.run(["docker", "image", "rm", fixture_image], capture_output=True)
        report["passed"] = True
    except Exception as error:
        report["error"] = str(error)
        print("FAIL " + str(error), file=sys.stderr)
    finally:
        if source_hashes() != report["source_sha256"]:
            report["passed"] = False
            report["error"] = "Source changed during verification. Rerun against a stable checkout."
        if not args.keep_running:
            for kind, name in reversed(instances):
                result = box("remove", kind, name, succeeds=False)
                report["checks"].append({"name": f"cleanup {kind} {name}", "passed": result.returncode == 0})
                if result.returncode:
                    report["passed"] = False
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(f"Evidence {directory}")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
