# Boxes

Boxes runs persistent desktop apps in Docker. You open the desktop in a browser over HTTPS, and an agent can work in the same session. Use it when a task needs a GUI that you can inspect, take over, and return to later. No model credentials are required.

## What you can do

- Keep persistent named desktops. Each one has its own apps, files, credentials, and saved configuration.
- Open a desktop in a browser over HTTPS and sign in with one account.
- Control the same desktop from an agent, or run commands inside a box yourself.
- Share a host project through `/work` and add read-only or writable mounts.
- Record a demonstration and keep Markdown lessons so an agent can repeat the task later.
- Manage several boxes, including updates, recreation, and removal.
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

Open the printed HTTPS URL. Sign in with the credentials that `login` shows in your terminal. New boxes receive a random password. A `.passwd` file in the state directory supplies a default instead, and `box list` shows each box's password. Repeating `up` without `--password` preserves saved credentials. First startup can take several minutes while the image installs utilities.

The upstream certificate is self-signed, so your browser shows a certificate warning. Proceed only for a host you trust. HTTPS provides the secure context that the web viewer requires away from localhost.

New boxes bind to `0.0.0.0`, every host IPv4 interface. Restrict access with a firewall or use `--bind 127.0.0.1` for local-only HTTPS access. Do not expose the desktop to the public internet. HTTP is an explicit agent-only mode that belongs on loopback with `--bind 127.0.0.1`.

See [human access and TLS](USAGE.md#human-access-and-tls) for bind addresses, hostnames, certificates, and HTTP options.

## Browser performance

Apps render inside the container. Selkies streams desktop output to your browser and sends your input back. The browser does not run the desktop app.

This generally keeps interaction responsive on a local or private network. That is an expectation from the design, not a measured performance result. Actual responsiveness depends on network latency and bandwidth, host CPU and GPU capacity or software rendering, the selected app, resolution, and frame rate. Software-rendered emulators can be a heavier workload.

## Agent control

An agent works on the same desktop through the box's authenticated port. It can read the current state and window list, take a screenshot, and send one move, click, key, text, or scroll action at a time.

```sh
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" state
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" screenshot --output /absolute/screen.png
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" click 600 400
printf '%s' 'example text' | "$BOXES_ROOT/box" agent "$TYPE" "$NAME" text
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" key Return
```

The human and the agent share one pointer, keyboard, and focus. An agent pauses while you take over, and it does not send input that competes with yours. Input is asynchronous, so an agent reads fresh state or a screenshot before the next action rather than assuming the previous one landed. The [agent control reference](USAGE.md#agent-control) lists every action, the API endpoints, and the known limits.

## Learning from a demonstration

A box can record its own desktop and the input that drives it. Show an agent a task once, and it can turn the recording into a lesson to repeat later.

```sh
"$BOXES_ROOT/box" record "$TYPE" "$NAME" start
"$BOXES_ROOT/box" record "$TYPE" "$NAME" pause
"$BOXES_ROOT/box" record "$TYPE" "$NAME" resume
"$BOXES_ROOT/box" record "$TYPE" "$NAME" stop
"$BOXES_ROOT/box" lessons "$TYPE" list
```

`start` records the screen and logs the clicks, drags, scrolls, and keystrokes that reach the viewer. `pause` stops both, so you can type a password in private, and `resume` continues in a new segment.

`stop` joins the segments and writes an annotated video, an event log, and a frame index into the instance's data directory. An agent reads those, drafts the lesson, shows it to you, and saves it only once you agree.

Lessons are Markdown files. Every box of the same type shares them, so a workflow learned in one box is available in the others. The [recording reference](USAGE.md#recording-and-lessons) covers the file list, `forget`, and the tools the recording needs.

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
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" set /absolute/source /mnt/reference --mode ro
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" list
"$BOXES_ROOT/box" update "$TYPE" "$NAME"
"$BOXES_ROOT/box" recreate "$TYPE" "$NAME"
"$BOXES_ROOT/box" remove "$TYPE" "$NAME"
```

`stop` retains files and settings, and `start` returns you to the desktop. The `--` in `exec` separates the instance name from the command and its arguments. `mount set` binds an absolute host directory at `/work` or under `/mnt`, and `--mode ro` makes the mount read-only.

`update` pulls the selected image or rebuilds a registered build, then recreates the container. `recreate` rebuilds the container from the current source and saved configuration. `remove` deletes the container and its Compose network, and keeps the saved configuration, credentials, and data.

Save your app work before `update`, `recreate`, or a mount change. Each one replaces the running container. Data directories survive, but unsaved application state does not.

`--image` and `--env` save an explicit image or upstream environment setting for the instance. `--bind` and `--port` choose the published listener, and `--http` selects the agent-only HTTP mode. The [command reference](USAGE.md#commands) covers every option and the JSON output for automation.

## Safety and persistence

Each named box keeps its own `/config`, `/work`, credentials, and saved configuration. `remove` retains these by default. Purge permanently deletes managed instance data. See [storage behavior](USAGE.md#persistent-configuration-and-mounts) and [removal semantics](USAGE.md#lifecycle) before changing or deleting data.

Containers share the host kernel. They are not strong sandboxes for hostile code. A desktop can read its mounts and modify writable ones. Keep host secrets and Docker sockets out of untrusted sessions.

Recordings contain screen contents and typed text in full, so treat them and the saved state directory as secrets. The [security reference](USAGE.md#security-boundaries) describes the limits.

## Install as an agent skill

For a new skill installation, clone into the shared skills directory. The destination must not already exist.

```sh
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/syntext/agent-boxes.git "$HOME/.agents/skills/boxes"
```

OpenCode discovers the core skill and nested type skills in that checkout. Other agents may need separate registration for nested skills. Runtime requirements still apply. For an existing checkout, use the [skill registration reference](USAGE.md#agent-skills).

## Development

The [usage reference](USAGE.md) covers runtime ownership and adding types. The [checks reference](USAGE.md#evidence-and-checks) describes the unit suite and real-Docker verifier.
