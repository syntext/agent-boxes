# Boxes

Boxes runs persistent desktop apps in Docker. You open the desktop in a browser over HTTPS, and an agent can work in the same session. Use it when a task needs a GUI that you can inspect, take over, and return to later. No model credentials are required.

## What you can do

- Keep persistent named desktops with separate app settings, files, and credentials.
- Share human and agent control of the same desktop through the web viewer and the Pelorus API.
- Run explicit commands inside a box with `box exec` or open a shell with `box shell`.
- Share a project through `/work` and add read-only or writable host mounts.
- Record demonstrations and keep reusable Markdown lessons for agents.
- Choose registered desktop types from [registry.json](registry.json). Each entry's `directory` contains its setup guide and agent skill.

## Requirements

- Linux with Docker Engine and the Docker Compose plugin. Docker access grants host-level control.
- Python 3.11 or newer. The host CLI uses only the standard library.
- A host architecture and devices supported by your selected type. Check its `architectures` and `devices` in [registry.json](registry.json).
- Disk space for images and persistent data under `~/work/boxes`.
- Network access for image pulls, builds, and package installation.

Check the selected type's README for storage, provisioning, and other app requirements before starting it.

## Install

Clone the repository and enter its directory. No global CLI installation is needed.

```sh
git clone https://github.com/syntext/agent-boxes.git
cd agent-boxes
```

## First run

Choose a key from [registry.json](registry.json). Replace `<registered-type>` below with that key, then start a named desktop.

```sh
BOXES_ROOT="$(pwd -P)"
TYPE='<registered-type>'
NAME=research
"$BOXES_ROOT/box" up "$TYPE" "$NAME"
"$BOXES_ROOT/box" url "$TYPE" "$NAME"
"$BOXES_ROOT/box" login "$TYPE" "$NAME"
```

Open the printed HTTPS URL. Sign in with the credentials that `login` shows in your terminal. New boxes receive a random password. Repeating `up` without `--password` preserves saved credentials. First startup can take several minutes while the image installs utilities.

The upstream certificate is self-signed, so your browser shows a certificate warning. Proceed only for a host you trust. HTTPS provides the secure context that the web viewer requires away from localhost.

New boxes bind to `0.0.0.0`, every host IPv4 interface. Restrict access with a firewall or use `--bind 127.0.0.1` for local-only HTTPS access. Do not expose the desktop to the public internet. HTTP is an explicit agent-only mode that belongs on loopback with `--bind 127.0.0.1`.

See [human access and TLS](USAGE.md#human-access-and-tls) for bind addresses, hostnames, certificates, and HTTP options.

## Browser performance

Apps render inside the container. Selkies streams desktop output to your browser and sends your input back. The browser does not run the desktop app.

This generally keeps interaction responsive on a local or private network. That is an expectation from the design, not a measured performance result. Actual responsiveness depends on network latency and bandwidth, host CPU and GPU capacity or software rendering, the selected app, resolution, and frame rate. Software-rendered emulators can be a heavier workload.

## Commands

Set `BOXES_ROOT="$(pwd -P)"` in the repository root. You can then invoke `"$BOXES_ROOT/box"` from any directory. These examples reuse `TYPE` and `NAME` from the first run.

```sh
"$BOXES_ROOT/box" list
"$BOXES_ROOT/box" status "$TYPE" "$NAME"
"$BOXES_ROOT/box" stop "$TYPE" "$NAME"
"$BOXES_ROOT/box" start "$TYPE" "$NAME"
"$BOXES_ROOT/box" logs "$TYPE" "$NAME" --tail 100
"$BOXES_ROOT/box" exec "$TYPE" "$NAME" -- id
"$BOXES_ROOT/box" shell "$TYPE" "$NAME"
```

Save your app work before changing configuration. `stop` retains files and settings. Use `start` to return to the desktop. The `--` in `exec` separates the instance name from the command and its arguments.

The [command reference](USAGE.md#commands) covers recreation, updates, removal, and JSON output. See [workspaces and mounts](USAGE.md#persistent-configuration-and-mounts), [agent control](USAGE.md#agent-control), and [recording and lessons](USAGE.md#recording-and-lessons) for other tasks.

## Safety and persistence

Each named box keeps its own `/config`, `/work`, credentials, and saved configuration. `remove` retains these by default. Purge permanently deletes managed instance data. See [storage behavior](USAGE.md#persistent-configuration-and-mounts) and [removal semantics](USAGE.md#lifecycle) before changing or deleting data.

Containers share the host kernel. They are not strong sandboxes for hostile code. A desktop can read its mounts and modify writable ones. Keep host secrets and Docker sockets out of untrusted sessions.

The human and agent share one pointer, keyboard, and focus. An agent must pause when you take over. Recordings contain screen contents and typed text, so treat them and saved state as secrets. The [security reference](USAGE.md#security-boundaries) describes the limits.

## Install as an agent skill

For a new skill installation, clone into the shared skills directory. The destination must not already exist.

```sh
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/syntext/agent-boxes.git "$HOME/.agents/skills/boxes"
```

OpenCode discovers the core skill and nested type skills in that checkout. Other agents may need separate registration for nested skills. Runtime requirements still apply. For an existing checkout, use the [skill registration reference](USAGE.md#agent-skills).

## Development

The [usage reference](USAGE.md) covers runtime ownership and adding types. The [checks reference](USAGE.md#evidence-and-checks) describes the unit suite and real-Docker verifier.
