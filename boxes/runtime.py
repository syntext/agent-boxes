from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path

from .model import BoxError, Instance, atomic_json


def run(arguments: list[str], *, capture: bool = False, check: bool = True) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(arguments, text=True, stdout=subprocess.PIPE if capture else sys.stderr,
                                stderr=subprocess.PIPE if capture else None)
    except FileNotFoundError as error:
        raise BoxError(f"Required executable {arguments[0]} is not installed.") from error
    if check and result.returncode:
        raise BoxError(f"{arguments[0]} failed with exit code {result.returncode}." + (f"\n{result.stderr.strip()}" if capture else ""))
    return result


def validate_identity(instance: Instance, container: dict):
    labels = container["Config"]["Labels"] or {}
    if any(labels.get(key) != value for key, value in instance.labels.items()):
        raise BoxError(f"Refusing to touch unrelated container {instance.project}.")


def inspect(instance: Instance) -> dict | None:
    result = run(["docker", "container", "inspect", instance.project], capture=True, check=False)
    if result.returncode:
        if "No such" in result.stderr:
            return None
        raise BoxError(result.stderr.strip())
    value = json.loads(result.stdout)[0]
    validate_identity(instance, value)
    return value


def compose(instance: Instance, path: Path, arguments: list[str]):
    result = run(["docker", "ps", "--all", "--quiet", "--filter",
                  f"label=com.docker.compose.project={instance.project}"], capture=True)
    for container_id in result.stdout.split():
        container = json.loads(run(["docker", "container", "inspect", container_id], capture=True).stdout)[0]
        validate_identity(instance, container)
    run(["docker", "compose", "--project-name", instance.project, "--file", str(path), *arguments])


def remove(instance: Instance):
    inspect(instance)
    path = instance.directory / "teardown.json"
    atomic_json(path, {"name": instance.project, "services": {"desktop": {"image": instance.kind.image}}})
    compose(instance, path, ["down"])


def port(container: dict | None) -> int | None:
    if not container:
        return None
    ports = container["NetworkSettings"]["Ports"].get("3001/tcp")
    return int(ports[0]["HostPort"]) if ports else None


def status(instance: Instance, config: dict, container: dict | None = None) -> dict:
    container = inspect(instance) if container is None else container
    published = port(container) or config.get("published_port") or config.get("port")
    host = os.environ.get("BOXES_HOSTNAME", "localhost" if config["bind"].startswith("127.") else socket.gethostname())
    return {"type": instance.kind.name, "name": instance.name, "project": instance.project,
            "state": container["State"]["Status"] if container else "absent",
            "image": container["Config"]["Image"] if container else config["image"] or instance.kind.image,
            "image_id": container["Image"] if container else None,
            "url": f"https://{host}:{published}/" if published else None,
            "bind": config["bind"], "port": published,
            "config_file": str(instance.directory / "instance.json"),
            "data": config["data"], "mounts": config["mounts"],
            "tls_verify": config["tls_verify"]}


def ensure(instance: Instance, config: dict, action: str):
    container = inspect(instance)
    if not (config["port"] or config["published_port"]):
        assigned = port(container)
        if not assigned:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
                candidate.bind((config["bind"], 0))
                assigned = candidate.getsockname()[1]
        config["published_port"] = assigned
        instance.save(config)
    path, digest = instance.write_compose(config)
    applied_path = instance.directory / "applied.json"
    applied = json.loads(applied_path.read_text()) if applied_path.exists() else {}
    running = bool(container and container["State"]["Running"])
    preserve_stopped = action in {"recreate", "update"} and not running
    service = instance.compose(config)["services"]["desktop"]
    if action == "update":
        compose(instance, path, ["build", "--pull"] if "build" in service else ["pull"])
    elif "build" in service:
        available = run(["docker", "image", "inspect", service["image"]], capture=True, check=False)
        if available.returncode:
            compose(instance, path, ["build"])
    changed = applied.get("digest") != digest
    if container and running and action == "up" and not changed:
        return
    if container and not running and action == "up" and not changed:
        run(["docker", "start", instance.project])
        return
    if container:
        print("Recreating the desktop. Save unsaved application work before changing configuration.", file=sys.stderr)
    arguments = ["create" if preserve_stopped else "up", "--force-recreate"]
    if not preserve_stopped:
        arguments.append("--detach")
    compose(instance, path, arguments)
    container = inspect(instance)
    assigned = port(container)
    if assigned:
        config["published_port"] = assigned
        instance.save(config)
    _, final_digest = instance.write_compose(config)
    atomic_json(applied_path, {"digest": final_digest})


def execute(instance: Instance, arguments: list[str], interactive: bool = False) -> int:
    container = inspect(instance)
    if not container or not container["State"]["Running"]:
        raise BoxError("The instance is not running.")
    options = ["-it"] if interactive else ["-i"]
    command = ["docker", "exec", *options, "--user", "abc", "--workdir", "/work",
               "--env", "DISPLAY=:0", "--env", "XDG_RUNTIME_DIR=/config/.XDG",
               "--env", "WAYLAND_DISPLAY=wayland-0", instance.project, *arguments]
    return subprocess.run(command).returncode
