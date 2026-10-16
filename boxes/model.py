from __future__ import annotations

import contextlib
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import secrets
import tempfile
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parents[1]
IDENTIFIER = re.compile(r"[a-z0-9][a-z0-9-]{0,39}\Z")
MANAGED_ENV = {"CUSTOM_USER", "PASSWORD", "PUID", "PGID", "HOME", "PELORUS", "PIXELFLUX_WAYLAND"}


class BoxError(Exception):
    pass


@dataclass(frozen=True)
class BoxType:
    name: str
    directory: str
    image: str
    architectures: list[str]
    devices: list[str]
    environment: dict[str, str]
    commands: dict[str, list[str]]
    build: str | None = None


def registry() -> dict[str, BoxType]:
    values = json.loads((ROOT / "registry.json").read_text())
    return {key: BoxType(name=key, **value) for key, value in values.items()}


def box_type(value: str) -> BoxType:
    for item in registry().values():
        if value in (item.name, item.directory):
            return item
    raise BoxError(f"Unknown type {value!r}. Choose browser, android, or bambu.")


def identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise BoxError("Names must use 1 to 40 lowercase letters, digits, or hyphens.")
    return value


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def compose_literals(value):
    if isinstance(value, str):
        return value.replace("$", "$$")
    if isinstance(value, dict):
        return {key: compose_literals(item) for key, item in value.items()}
    if isinstance(value, list):
        return [compose_literals(item) for item in value]
    return value


def mount(source: str, target: str, mode: str = "rw") -> dict:
    path = Path(source)
    if not path.is_absolute() or not path.exists():
        raise BoxError("A mount source must be an existing absolute path.")
    path = path.resolve(strict=True)
    if path in {Path("/"), Path("/proc"), Path("/sys"), Path("/dev")} or path.is_socket() or str(path).startswith(("/proc/", "/sys/", "/dev/")):
        raise BoxError("Mount sources cannot be root, a socket, or a kernel device path.")
    destination = PurePosixPath(target)
    if not destination.is_absolute() or str(destination) != target or ".." in destination.parts:
        raise BoxError("A mount target must be a normalized absolute container path.")
    if target != "/work" and not target.startswith(("/work/", "/mnt/")):
        raise BoxError("Mount targets must be /work or a child of /work or /mnt.")
    if mode not in {"ro", "rw"}:
        raise BoxError("Mount mode must be ro or rw.")
    return {"source": str(path), "target": target, "read_only": mode == "ro"}


def validate_mounts(values: list[dict]) -> list[dict]:
    result = [mount(v["source"], v["target"], "ro" if v["read_only"] else "rw") for v in values]
    targets = [PurePosixPath(v["target"]) for v in result]
    for index, target in enumerate(targets):
        for other in targets[index + 1:]:
            if target == other or target in other.parents or other in target.parents:
                raise BoxError("Mount targets cannot duplicate or mask another configured mount.")
    return result


def env_pair(value: str) -> tuple[str, str]:
    key, separator, content = value.partition("=")
    if not separator or not re.fullmatch(r"[A-Z][A-Z0-9_]*", key) or "\x00" in content:
        raise BoxError("Environment options must be KEY=VALUE with an uppercase key.")
    if key in MANAGED_ENV or key.startswith("FILE__"):
        raise BoxError(f"{key} is managed by boxes and cannot be overridden.")
    return key, content


def host_bind(value: str) -> str:
    try:
        address = ipaddress.ip_address(value)
    except ValueError as error:
        raise BoxError("--bind must be a numeric IPv4 address.") from error
    if address.version != 4:
        raise BoxError("Only IPv4 bind addresses are supported.")
    return str(address)


@dataclass
class Instance:
    kind: BoxType
    name: str = "default"

    def __post_init__(self):
        identifier(self.name)
        self.state_root = Path(os.environ.get("BOXES_STATE_DIR", Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "boxes")).expanduser().resolve()
        self.data_root = Path(os.environ.get("BOXES_DATA_DIR", Path.home() / "work/boxes")).expanduser().resolve()
        self.directory = self.state_root / self.kind.name / self.name
        self.data = self.data_root / self.kind.name / self.name
        self.validate_data(self.data_root)
        self.validate_data(self.data)
        self.project = f"{identifier(os.environ.get('BOXES_PROJECT_PREFIX', 'boxes'))}-{self.kind.name}-{self.name}"
        self.owner = hashlib.sha256(str(self.state_root).encode()).hexdigest()[:20]

    @property
    def labels(self) -> dict[str, str]:
        return {"io.boxes.owner": self.owner, "io.boxes.type": self.kind.name, "io.boxes.name": self.name}

    def validate_data(self, data: Path):
        data = data.resolve()
        for state in (self.state_root.resolve(), self.directory.resolve()):
            if data == state or data in state.parents or state in data.parents:
                raise BoxError("State and data paths must not overlap. Instance locks must remain outside managed data.")

    @contextlib.contextmanager
    def lock(self):
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        with (self.directory / "lock").open("a") as stream:
            os.chmod(self.directory / "lock", 0o600)
            fcntl.flock(stream, fcntl.LOCK_EX)
            yield

    def load(self, create: bool = False) -> dict:
        path = self.directory / "instance.json"
        if path.exists():
            value = json.loads(path.read_text())
            if value.get("version") != 1 or value.get("type") != self.kind.name or value.get("name") != self.name:
                raise BoxError(f"Invalid instance configuration {path}.")
            self.validate_data(Path(value["data"]))
            return value
        if not create:
            raise BoxError("Instance is not configured. Run box up first.")
        for child in ("config", "work"):
            (self.data / child).mkdir(mode=0o700, parents=True, exist_ok=True)
        value = {"version": 1, "type": self.kind.name, "name": self.name,
                 "data": str(self.data), "bind": "127.0.0.1", "port": None,
                 "environment": {}, "mounts": [], "image": None,
                 "user": "box", "password": secrets.token_urlsafe(32),
                 "tls_verify": False, "published_port": None}
        self.save(value)
        return value

    def save(self, value: dict):
        self.validate_data(Path(value["data"]))
        atomic_json(self.directory / "instance.json", value)

    def compose(self, config: dict) -> dict:
        arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
        if arch not in self.kind.architectures:
            raise BoxError(f"{self.kind.name} does not support host architecture {arch}.")
        runtime = json.loads((ROOT / "runtime.json").read_text())
        environment = runtime.pop("environment") | self.kind.environment | config["environment"]
        environment.update(PUID=str(os.getuid()), PGID=str(os.getgid()), PELORUS="true",
                           CUSTOM_USER=config["user"], PASSWORD=config["password"])
        volumes = [{"type": "bind", "source": str(Path(config["data"]) / "config"), "target": "/config"},
                   {"type": "bind", "source": str(Path(config["data"]) / "work"), "target": "/work"}]
        mounts = validate_mounts(config["mounts"])
        if any(v["target"] == "/work" for v in mounts):
            volumes.pop()
        volumes.extend({"type": "bind", **value} for value in mounts)
        service = {**runtime, "image": config["image"] or self.kind.image,
                   "container_name": self.project, "environment": environment,
                    "labels": self.labels,
                   "volumes": volumes,
                   "ports": [{"target": 3001, "published": str(config["port"] or config["published_port"] or 0),
                              "host_ip": config["bind"], "protocol": "tcp"}],
                   "restart": "unless-stopped"}
        if self.kind.build and not config["image"]:
            service["build"] = {"context": str(ROOT / self.kind.build)}
            service["pull_policy"] = "never"
        if self.kind.devices:
            for device in self.kind.devices:
                if not Path(device).exists():
                    raise BoxError(f"Required device {device} is missing.")
            service["devices"] = list(self.kind.devices)
            service["group_add"] = [str(Path(device).stat().st_gid) for device in self.kind.devices]
        return {"name": self.project, "services": {"desktop": service}}

    def write_compose(self, config: dict) -> tuple[Path, str]:
        value = self.compose(config)
        path = self.directory / "compose.json"
        atomic_json(path, compose_literals(value))
        digest = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
        return path, digest
