from __future__ import annotations

import argparse
import contextlib
import json
from pathlib import Path
import sys

from . import agent, recording, runtime
from .model import BoxError, Instance, box_type, env_pair, host_bind, mount, registry, validate_mounts, validate_password


def parser():
    root = argparse.ArgumentParser(description="Persistent LinuxServer desktops with authenticated agent control.")
    commands = root.add_subparsers(dest="command", required=True)
    listing = commands.add_parser("list", help="List saved instances and their credentials")
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--no-password", action="store_true", help="Omit passwords from output that may be shared")
    usages = {"exec": "box exec TYPE [NAME] -- ARGS...", "adb": "box adb TYPE [NAME] -- ARGS...",
              "record": "box record TYPE [NAME] {start,stop,pause,resume,status,list,forget}",
              "lessons": "box lessons TYPE [NAME] {list,path,show,record}"}
    for command in ("up", "start", "stop", "restart", "update", "recreate", "status", "url", "login", "remove",
                    "exec", "shell", "logs", "mount", "agent", "emu", "adb", "record", "lessons"):
        p = commands.add_parser(command, usage=usages.get(command))
        p.add_argument("type", **({"nargs": "?"} if command == "status" else {}))
        p.add_argument("name", nargs="?", default="default")
        if command in {"up", "recreate", "update"}:
            p.add_argument("--workspace", type=Path)
            p.add_argument("--env", action="append", default=[], metavar="KEY=VALUE")
            p.add_argument("--unset-env", action="append", default=[], metavar="KEY")
            p.add_argument("--bind", type=host_bind)
            p.add_argument("--port", type=int)
            p.add_argument("--image")
            p.add_argument("--password", help="Set the box account password; omitted retains saved credentials")
            p.add_argument("--tls-verify", action=argparse.BooleanOptionalAction, default=None)
            p.add_argument("--http", action=argparse.BooleanOptionalAction, default=None)
            p.add_argument("--wait", type=int, default=180, metavar="SECONDS")
        if command == "status":
            p.add_argument("--json", action="store_true")
        if command == "remove":
            p.add_argument("--purge", action="store_true")
            p.add_argument("--yes", action="store_true")
        if command in {"exec", "adb", "emu", "agent", "mount", "record", "lessons"}:
            p.add_argument("arguments", nargs=argparse.REMAINDER)
        if command == "logs":
            p.add_argument("--follow", action="store_true")
            p.add_argument("--tail", type=int, default=100)
    return root


def output(value):
    print(json.dumps(value, indent=2))


def table(values):
    if not values:
        print("No boxes.")
        return
    headings = ["TYPE", "NAME", "STATE", "BIND", "PORT", "URL"]
    rows = [[v["type"], v["name"], v["state"], v["bind"], str(v["port"] or "-"), v["url"] or "-"] for v in values]
    if "password" in values[0]:
        headings.append("PASSWORD")
        for row, value in zip(rows, values):
            row.append(value["password"])
    widths = [max(len(row[column]) for row in [headings, *rows]) for column in range(len(headings))]
    for row in [headings, *rows]:
        print("  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip())


def configure(args, config):
    if args.password is not None:
        config["password"] = validate_password(args.password)
    if not 1 <= args.wait <= 900:
        raise BoxError("--wait must be between 1 and 900 seconds.")
    for key in ("bind", "port", "image", "http", "tls_verify"):
        value = getattr(args, key, None)
        if value is not None:
            if key == "port" and not 1 <= value <= 65535:
                raise BoxError("--port must be between 1 and 65535.")
            config[key] = value
    for value in args.env:
        key, content = env_pair(value)
        config["environment"][key] = content
    for key in args.unset_env:
        config["environment"].pop(key, None)
    if args.workspace:
        workspace = mount(str(args.workspace), "/work")
        config["mounts"] = [v for v in config["mounts"] if v["target"] != "/work"] + [workspace]
    validate_mounts(config["mounts"])


def mounts(instance, config, arguments):
    p = argparse.ArgumentParser(prog="box mount TYPE [NAME]")
    sub = p.add_subparsers(dest="operation", required=True)
    sub.add_parser("list")
    add = sub.add_parser("set")
    add.add_argument("source")
    add.add_argument("target")
    add.add_argument("--mode", choices=["ro", "rw"], default="rw")
    remove = sub.add_parser("remove")
    remove.add_argument("target")
    args = p.parse_args(arguments)
    if args.operation == "list":
        output(config["mounts"])
        return
    values = [value for value in config["mounts"] if value["target"] != args.target]
    if args.operation == "set":
        values.append(mount(args.source, args.target, args.mode))
    validate_mounts(values)
    if values == config["mounts"]:
        return
    config["mounts"] = values
    instance.save(config)
    if runtime.inspect(instance):
        runtime.ensure(instance, config, "recreate")
        if runtime.inspect(instance)["State"]["Running"]:
            agent.wait_ready(instance, config)
    output(values)


def control(instance, config, arguments):
    p = argparse.ArgumentParser(prog="box agent TYPE [NAME]")
    sub = p.add_subparsers(dest="operation", required=True)
    for name in ("state", "windows"):
        sub.add_parser(name)
    shot = sub.add_parser("screenshot")
    shot.add_argument("--output", type=Path)
    explore = sub.add_parser("explore")
    explore.add_argument("pid", type=int)
    for name in ("move", "click"):
        item = sub.add_parser(name)
        item.add_argument("x", type=int)
        item.add_argument("y", type=int)
        if name == "click":
            item.add_argument("--button", choices=["left", "right", "middle", "double"], default="left")
    for name in ("key", "text"):
        item = sub.add_parser(name)
        item.add_argument("text", nargs="?")
    scroll = sub.add_parser("scroll")
    scroll.add_argument("direction", choices=["up", "down", "left", "right"])
    scroll.add_argument("amount", type=int)
    raw = sub.add_parser("control")
    raw.add_argument("json", help="Control action JSON for the computer-use backend")
    args = p.parse_args(arguments)
    operation = args.operation
    if operation in {"state", "windows"}:
        return agent.request(instance, config, operation)
    if operation == "explore":
        return agent.request(instance, config, f"desktop/explore/{args.pid}")
    if operation == "screenshot":
        return agent.screenshot(instance, config, args.output)
    payload = {}
    if operation in {"move", "click"}:
        actions = {"left": "left_click", "right": "right_click", "middle": "middle_click", "double": "double_click"}
        payload = {"action": "mouse_move" if operation == "move" else actions[args.button], "coordinate": [args.x, args.y]}
    elif operation in {"key", "text"}:
        payload = {"action": "key" if operation == "key" else "type",
                   "text": args.text if args.text is not None else sys.stdin.read()}
    elif operation == "scroll":
        payload = {"action": "scroll", "scroll_direction": args.direction, "scroll_amount": args.amount}
    elif operation == "control":
        payload = json.loads(args.json)
    return agent.request(instance, config, "desktop/control", payload)


def records(instance, config, arguments):
    p = argparse.ArgumentParser(prog="box record TYPE [NAME]")
    sub = p.add_subparsers(dest="operation", required=True)
    start = sub.add_parser("start", help="Begin recording the desktop and logging input")
    start.add_argument("--fps", type=int, default=15)
    start.add_argument("--overlay", action="store_true",
                       help="Also draw clicks, drags, scrolls, and typing on the live desktop")
    for name in ("stop", "pause", "resume", "status", "list"):
        sub.add_parser(name)
    forget = sub.add_parser("forget", help="Delete one kept recording")
    forget.add_argument("name")
    args = p.parse_args(arguments)
    if args.operation == "start":
        if not 1 <= args.fps <= 60:
            raise BoxError("--fps must be between 1 and 60.")
        output(recording.start(instance, args.fps, args.overlay))
    elif args.operation == "list":
        output(recording.list_recordings(instance))
    elif args.operation == "forget":
        output(recording.forget(instance, args.name))
    else:
        output(getattr(recording, args.operation)(instance))


def study(instance, config, arguments):
    p = argparse.ArgumentParser(prog="box lessons TYPE [NAME]")
    sub = p.add_subparsers(dest="operation", required=True)
    for name in ("list", "path"):
        sub.add_parser(name)
    show = sub.add_parser("show")
    show.add_argument("slug")
    write = sub.add_parser("record", help="Save a lesson written to stdin")
    write.add_argument("slug")
    args = p.parse_args(arguments)
    if args.operation == "record":
        markdown = sys.stdin.read()
        if not markdown.strip():
            raise BoxError("A lesson needs Markdown on stdin.")
        output(recording.record_lesson(instance, args.slug, markdown))
    else:
        output(recording.lessons(instance, args.operation, getattr(args, "slug", None)))


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = parser()
    if argv and argv[0] in {"exec", "adb"}:
        boundary = argv.index("--") if "--" in argv else -1
        if boundary not in {2, 3} or boundary == len(argv) - 1:
            root.error(f"{argv[0]} requires TYPE [NAME] -- ARGS...")
        if boundary == 2:
            argv.insert(2, "default")
    default_actions = {
        "agent": {"state", "windows", "screenshot", "explore", "move", "click", "key", "text", "scroll", "control"},
        "record": {"start", "stop", "pause", "resume", "status", "list", "forget"},
        "lessons": {"list", "path", "show", "record"},
        "mount": {"list", "set", "remove"}, "emu": {"start", "stop", "status"}}
    explicit_name = len(argv) >= 4 and argv[3] == "--"
    if len(argv) >= 3 and not explicit_name and argv[2] in default_actions.get(argv[0], set()):
        argv.insert(2, "default")
    args = root.parse_args(argv)
    if args.command == "status" and args.type is None:
        args.command = "list"
    try:
        if args.command == "list":
            results = []
            for kind in registry().values():
                sample = Instance(kind)
                for path in sorted((sample.state_root / kind.name).glob("*/instance.json")):
                    instance = Instance(kind, path.parent.name)
                    with instance.lock():
                        config = instance.load()
                        entry = runtime.status(instance, config)
                        if not args.no_password:
                            entry["password"] = config["password"]
                        results.append(entry)
            if args.json:
                output(results)
            else:
                table(results)
            return 0
        instance = Instance(box_type(args.type), args.name)
        arguments = getattr(args, "arguments", [])
        if arguments[:1] == ["--"]:
            arguments = arguments[1:]
        mutating = args.command in {"up", "start", "stop", "restart", "update", "recreate", "mount", "remove", "record", "lessons"}
        with instance.lock() if mutating else contextlib.nullcontext():
            config = instance.load(create=args.command == "up")
            command = args.command
            if command in {"up", "recreate", "update"}:
                configure(args, config)
                instance.compose(config)
                instance.save(config)
                runtime.ensure(instance, config, command)
                if runtime.inspect(instance)["State"]["Running"]:
                    agent.wait_ready(instance, config, args.wait)
                output(runtime.status(instance, config))
            elif command in {"status", "url"}:
                value = runtime.status(instance, config)
                if command == "url":
                    print(value["url"] or "No published URL")
                elif args.json:
                    output(value)
                else:
                    table([value])
            elif command == "login":
                if not sys.stdout.isatty():
                    raise BoxError("Login prints a password only to a terminal. Use box list, or read the private instance.json, for automation.")
                print(f"User {config['user']}\nPassword {config['password']}")
            elif command in {"start", "stop", "restart"}:
                container = runtime.inspect(instance)
                if command == "start":
                    runtime.ensure(instance, config, "up")
                    agent.wait_ready(instance, config)
                elif container:
                    runtime.run(["docker", command, "--timeout", "30", instance.project])
            elif command == "mount":
                mounts(instance, config, arguments)
            elif command == "record":
                records(instance, config, arguments)
            elif command == "lessons":
                study(instance, config, arguments)
            elif command == "agent":
                output(control(instance, config, arguments))
            elif command in {"exec", "shell", "emu", "adb"}:
                if command in {"emu", "adb"}:
                    if command not in instance.kind.commands:
                        raise BoxError(f"{command} is not available for {instance.kind.name}.")
                    arguments = instance.kind.commands[command] + arguments
                if command == "shell":
                    arguments = ["/bin/bash"]
                if not arguments:
                    raise BoxError("exec requires a command after --. Use shell for an interactive terminal.")
                return runtime.execute(instance, arguments, interactive=command == "shell")
            elif command == "logs":
                if not runtime.inspect(instance):
                    raise BoxError("The instance has no container.")
                runtime.run(["docker", "logs", "--tail", str(args.tail), *(["--follow"] if args.follow else []), instance.project])
            elif command == "remove":
                if args.purge and not args.yes:
                    raise BoxError("Purge permanently deletes this instance's data. Repeat with --purge --yes after backing up.")
                runtime.remove(instance)
                if args.purge:
                    import shutil
                    data = Path(config["data"]).resolve()
                    if data != instance.data or data in {Path.home(), Path("/")}:
                        raise BoxError("Data path differs from the configured data root. Refusing purge.")
                    shutil.rmtree(data)
                    for filename in ("instance.json", "compose.json", "applied.json", "teardown.json"):
                        (instance.directory / filename).unlink(missing_ok=True)
                else:
                    print("Container removed. Saved configuration, credentials, and data are retained.")
        return 0
    except (BoxError, ValueError, OSError) as error:
        print(f"box: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
