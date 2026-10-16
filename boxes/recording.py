"""Record a box desktop, log the input driving it, and keep both for review.

The recorder, the input tap, and the optional live overlay all run inside the
box, which keeps upstream images and services untouched. A recording is written
to `/config/.boxes` in the box while it runs and copied to
`BOXES_DATA_DIR/recordings/TYPE/NAME/` when it stops, so it survives recreation
and stays out of the skill checkout. Nothing here deletes a recording on its own;
a person reviews them and removes what they no longer want.

The tap reads the box's own loopback websocket traffic, which carries a viewer's
clicks, scrolls, and keystrokes as plain text. Typed text is logged in full by
design, which is why a recording can be paused while a secret is entered.
"""

from __future__ import annotations

import datetime
import json
import shutil
import time
from pathlib import Path

from . import runtime
from .model import BoxError, Instance, atomic_json

GUEST = Path(__file__).resolve().parent / "guest"
GUEST_FILES = ("tap.py", "overlay.py", "post.py", "launch.sh", "stop.sh")
CONTAINER_ROOT = "/config/.boxes"
RECORDING_STATE = "recording.json"
# Where the box's own input traffic travels: nginx terminates the viewer
# connection and forwards each websocket message to Selkies over the box's
# loopback, so the plain text of every click and keystroke appears there. One
# interface is enough, and it keeps the tap off the box's external network.
INPUT_INTERFACES = ["lo"]


def now():
    return round(time.time(), 3)


def stamp(moment=None):
    return datetime.datetime.fromtimestamp(moment or time.time(), datetime.timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def recordings_root(instance: Instance) -> Path:
    return instance.data_root / "recordings" / instance.kind.name / instance.name


def lessons_root(instance: Instance) -> Path:
    return instance.data_root / "lessons" / instance.kind.name


def active(instance: Instance) -> dict | None:
    path = instance.directory / RECORDING_STATE
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except ValueError as error:
        raise BoxError(f"Invalid recording state {path}.") from error
    return value


def save(instance: Instance, value: dict | None):
    path = instance.directory / RECORDING_STATE
    if value is None:
        path.unlink(missing_ok=True)
        return
    atomic_json(path, value)
    host = Path(value["host"])
    if host.exists():
        atomic_json(host / RECORDING_STATE, value)


def inside(instance: Instance, arguments: list[str], user: str = "abc", detached: bool = False) -> list[str]:
    """A docker exec carrying the same display environment the CLI already uses."""
    return ["docker", "exec", "-d" if detached else "-i", "--user", user, "--workdir", "/work",
            "--env", "DISPLAY=:0", "--env", "XDG_RUNTIME_DIR=/config/.XDG",
            "--env", "WAYLAND_DISPLAY=wayland-0", instance.project, *arguments]


def execute(instance: Instance, arguments: list[str], user: str = "abc"):
    return runtime.run(inside(instance, arguments, user=user), capture=True)


def guest(name: str) -> str:
    return f"{CONTAINER_ROOT}/guest/{name}"


def session_file(value: dict, name: str) -> str:
    return f"{value['directory']}/{name}"


def verify_tools(instance: Instance, overlay: bool = False):
    """Fail with the fix rather than the symptom when the image lacks a tool."""
    for name, tool in (("wf-recorder", "wf-recorder"), ("ffmpeg", "ffmpeg"), ("ffprobe", "ffprobe")):
        result = runtime.run(inside(instance, ["sh", "-c", f"command -v {tool}"]), capture=True, check=False)
        if result.returncode:
            raise BoxError(f"The box image has no {name}. Install it by recreating the box: "
                           f"box recreate {instance.kind.name} {instance.name}.")
    if overlay:
        verify_overlay(instance)


def verify_overlay(instance: Instance):
    """The overlay needs a Python that carries GTK, layer shell, and cairo."""
    probe = ("import gi; gi.require_version('Gtk', '3.0'); gi.require_version('GtkLayerShell', '0.1'); "
             "gi.require_foreign('cairo')")
    for python in ("/usr/bin/python3", "python3"):
        result = runtime.run(inside(instance, [python, "-c", probe]), capture=True, check=False)
        if not result.returncode:
            return
    raise BoxError("The live overlay needs PyGObject with its cairo binding and gtk-layer-shell. Install them by "
                   f"recreating the box: box recreate {instance.kind.name} {instance.name}. "
                   "Without --overlay the recording still keeps its drawn highlights.")


def prepare(instance: Instance):
    execute(instance, ["mkdir", "-p", f"{CONTAINER_ROOT}/guest"])
    for name in GUEST_FILES:
        result = runtime.run(["docker", "cp", str(GUEST / name), f"{instance.project}:{guest(name)}"],
                             capture=True, check=False)
        if result.returncode:
            raise BoxError(f"Could not copy {name} into the box. {result.stderr.strip()}")
    execute(instance, ["sh", "-c", f"chmod 755 {CONTAINER_ROOT}/guest/*.py {CONTAINER_ROOT}/guest/*.sh"])


def bytes_in(instance: Instance, path: str) -> int:
    result = runtime.run(inside(instance, ["sh", "-c", f"wc -c < {path} 2>/dev/null || true"]),
                         capture=True, check=False)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


def launch(instance: Instance, value: dict, segment: int, overlay: bool) -> str:
    arguments = ["--segment", str(segment), "--fps", str(value["fps"]), "--directory", value["directory"]]
    if overlay:
        arguments.append("--overlay")
    for interface in value.get("interfaces", []):
        arguments += ["--interface", interface]
    result = runtime.run(inside(instance, [guest("launch.sh"), *arguments], user="root"), capture=True, check=False)
    if result.returncode:
        raise BoxError(f"Could not start the recording in the box. {(result.stderr or result.stdout).strip()}")
    file = session_file(value, f"segment-{segment:02d}.mp4")
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if bytes_in(instance, file) >= 1024:
            return file
        time.sleep(0.5)
    raise BoxError("The recorder did not start writing frames. Check the box logs and try again.")


def finish(instance: Instance, value: dict, segment: int, overlay: bool) -> str:
    arguments = ["--segment", str(segment), "--directory", value["directory"]]
    if overlay:
        arguments.append("--overlay")
    result = runtime.run(inside(instance, [guest("stop.sh"), *arguments]), capture=True, check=False)
    if result.returncode:
        raise BoxError(f"Could not stop the recording cleanly. {(result.stderr or result.stdout).strip()}")
    file = session_file(value, f"segment-{segment:02d}.mp4")
    if bytes_in(instance, file) < 1024:
        raise BoxError("The recording stopped without producing usable video.")
    return file


def upload(instance: Instance, value: dict):
    """Keep the recording state inside the box too, where rendering reads it."""
    source = Path(value["host"]) / RECORDING_STATE
    if not source.exists():
        return
    runtime.run(["docker", "cp", str(source), f"{instance.project}:{session_file(value, RECORDING_STATE)}"],
                capture=True, check=False)


def render(instance: Instance, value: dict):
    """Build the joined video, the annotated video, and the frame index in the box."""
    save(instance, value)
    upload(instance, value)
    result = runtime.run(inside(instance, ["python3", guest("post.py"), "--directory", value["directory"],
                                           "--recording", session_file(value, RECORDING_STATE),
                                           "--events", session_file(value, "events.jsonl")]),
                         capture=True, check=False)
    if result.returncode:
        raise BoxError(f"Could not render the recording. {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def segment_file(item: dict) -> str:
    return f"segment-{item['segment']:02d}.mp4"


def copy_out(instance: Instance, value: dict) -> Path:
    """Copy the whole recording out of the box with one `docker cp`.

    The segment files stay behind: `screen.mp4` holds the same frames joined.
    """
    destination = Path(value["host"])
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = runtime.run(["docker", "cp", f"{instance.project}:{value['directory']}/.",
                          f"{destination}/"], capture=True, check=False)
    if result.returncode:
        raise BoxError(f"Could not copy the recording out of the box. {result.stderr.strip()}")
    for item in value["segments"]:
        (destination / segment_file(item)).unlink(missing_ok=True)
    return destination


def load_events(path: Path) -> list[dict]:
    events = []
    if not path.exists():
        return events
    for line in path.read_text(errors="replace").splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "event" in value:
            events.append(value)
    return events


def start(instance: Instance, fps: int = 15, overlay: bool = False) -> dict:
    if not running(instance):
        raise BoxError("The instance is not running.")
    if active(instance):
        raise BoxError("A recording is already active. Stop it before starting another.")
    verify_tools(instance, overlay)
    prepare(instance)
    moment = now()
    name = stamp(moment)
    value = {"version": 1, "name": name, "started": moment, "fps": fps, "overlay": overlay,
             "interfaces": list(INPUT_INTERFACES),
             "directory": f"{CONTAINER_ROOT}/{name}", "host": str(recordings_root(instance) / name),
             "segment": 1, "segments": [{"segment": 1, "start": moment, "finished": None}],
             "paused": False, "pause_started": None}
    Path(value["host"]).mkdir(mode=0o700, parents=True, exist_ok=True)
    execute(instance, ["mkdir", "-p", value["directory"]])
    launch(instance, value, 1, overlay)
    save(instance, value)
    return value


def pause(instance: Instance) -> dict:
    value = active(instance)
    if not value:
        raise BoxError("No recording is active.")
    if value["paused"]:
        raise BoxError("The recording is already paused.")
    finish(instance, value, value["segment"], value["overlay"])
    value["segments"][-1]["finished"] = now()
    value["paused"] = True
    value["pause_started"] = now()
    save(instance, value)
    return value


def resume(instance: Instance) -> dict:
    value = active(instance)
    if not value:
        raise BoxError("No recording is active.")
    if not value["paused"]:
        raise BoxError("The recording is not paused.")
    value["segment"] += 1
    moment = now()
    launch(instance, value, value["segment"], value["overlay"])
    value["segments"].append({"segment": value["segment"], "start": moment, "finished": None})
    value["paused"] = False
    value["pause_started"] = None
    save(instance, value)
    return value


def stop(instance: Instance) -> dict:
    value = active(instance)
    if not value:
        raise BoxError("No recording is active.")
    if not value["paused"]:
        finish(instance, value, value["segment"], value["overlay"])
        value["segments"][-1]["finished"] = now()
    value["stopped"] = now()
    value["paused"] = False
    value["pause_started"] = None
    save(instance, value)
    render(instance, value)
    copy_out(instance, value)
    events = load_events(Path(value["host"]) / "events.jsonl")
    summary = {"directory": value["host"], "name": value["name"], "started": value["started"],
               "stopped": value["stopped"], "segments": len(value["segments"]), "overlay": value["overlay"],
               "events": len(events), "actions": [event for event in events if event.get("event") != "move"],
               "video": str(Path(value["host"]) / "screen.mp4"),
               "annotated": str(Path(value["host"]) / "screen-annotated.mp4"),
               "index": str(Path(value["host"]) / "index.json"),
               "frames": str(Path(value["host"]) / "frames")}
    save(instance, None)
    return summary


def running(instance: Instance) -> bool:
    container = runtime.inspect(instance)
    return bool(container and container["State"]["Running"])


def status(instance: Instance) -> dict:
    value = active(instance)
    if not value:
        directory = recordings_root(instance)
        kept = sorted(path.name for path in directory.iterdir() if path.is_dir()) if directory.exists() else []
        return {"active": False, "recordings": kept, "directory": str(directory)}
    return {"active": True, "paused": value["paused"], "name": value["name"], "segments": len(value["segments"]),
            "overlay": value["overlay"], "started": value["started"], "host": value["host"],
            "pause_started": value["pause_started"]}


def list_recordings(instance: Instance) -> dict:
    directory = recordings_root(instance)
    found = []
    if directory.exists():
        for path in sorted(directory.iterdir()):
            if not path.is_dir():
                continue
            value = {"name": path.name, "directory": str(path)}
            index = path / "index.json"
            if index.exists():
                try:
                    value.update(json.loads(index.read_text()))
                except ValueError:
                    pass
            found.append(value)
    return {"directory": str(directory), "recordings": found}


def forget(instance: Instance, name: str) -> dict:
    root = recordings_root(instance)
    directory = root / name
    if (not name or name in {".", ".."} or Path(name).name != name or "\x00" in name
            or directory.is_symlink() or directory.resolve().parent != root.resolve() or not directory.is_dir()):
        raise BoxError(f"No recording named {name!r}.")
    current = active(instance)
    if current and current["name"] == name:
        raise BoxError("Cannot forget the active recording. Stop it first.")
    shutil.rmtree(directory)
    return {"removed": str(directory)}


def lessons(instance: Instance, operation: str, slug: str | None = None) -> dict:
    directory = lessons_root(instance)
    if operation == "path":
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        return {"directory": str(directory), "type": instance.kind.name}
    if operation == "list":
        found = []
        if directory.exists():
            for path in sorted(directory.glob("*.md")):
                found.append({"slug": path.stem, "file": str(path), "title": first_heading(path)})
        return {"directory": str(directory), "lessons": found}
    if operation == "show":
        if not slug:
            raise BoxError("lessons show requires a slug.")
        path = directory / f"{slug}.md"
        if not path.exists():
            raise BoxError(f"No lesson named {slug!r} for {instance.kind.name}.")
        return {"slug": slug, "file": str(path), "markdown": path.read_text()}
    raise BoxError("lessons takes list, path, or show.")


def record_lesson(instance: Instance, slug: str, markdown: str) -> dict:
    if not slug or len(slug) > 80 or "/" in slug or slug.startswith("."):
        raise BoxError("A lesson slug must be a short filename without slashes.")
    directory = lessons_root(instance)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / f"{slug}.md"
    path.write_text(markdown if markdown.endswith("\n") else markdown + "\n")
    return {"slug": slug, "file": str(path), "type": instance.kind.name}


def first_heading(path: Path) -> str:
    for line in path.read_text(errors="replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem
