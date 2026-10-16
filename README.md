# Boxes

Persistent, isolated GUI desktop instances for people and agents. A person opens the Selkies web viewer. An agent controls the same desktop through Pelorus or runs explicit commands with `box exec`. No model credentials are required. Available types come from [registry.json](registry.json), not a fixed catalog in this README.

## Install as an agent skill

Clone the repository into the shared skills directory used by OpenCode and other compatible agents. The destination must not already exist.

```sh
mkdir -p "$HOME/.agents/skills"
git clone https://github.com/syntext/agent-boxes.git "$HOME/.agents/skills/boxes"
```

OpenCode discovers the core skill and nested type skills from that checkout. Other agents may require separate registration for nested skills. Install the runtime prerequisites below before starting containers. If you already have a checkout, use the symlink instructions under [Agent skills](#agent-skills) instead.

## Requirements

- Linux with Docker Engine and the Docker Compose plugin. Docker access grants host-level control.
- Python 3.11 or newer on the host. The CLI uses only the standard library.
- A host architecture and device access supported by the selected type. Check its `architectures` and `devices` in [registry.json](registry.json).
- Disk space for images and persistent data under `~/work/boxes`. The selected type's README describes additional storage and provisioning requirements.
- Network access for image pulls, builds, and package installation as required by the selected type.

## Commands

In the repository root, set `BOXES_ROOT="$(pwd -P)"`. Then invoke `"$BOXES_ROOT/box"` from any working directory. Agents loading a skill use its supplied base directory instead, as shown in [the core skill](SKILL.md). No global CLI installation is needed.

Select a key from [registry.json](registry.json). Its `directory` identifies the type's README and skill. A registered directory name is also accepted as a type alias. An omitted instance name means `default`.

Set the variables below before using any examples. Replace `<registered-type>` with an actual registry key, not the literal placeholder.

```sh
BOXES_ROOT="$(pwd -P)"
TYPE='<registered-type>'
NAME=research
```

Pass-through execution requires `"$BOXES_ROOT/box" exec "$TYPE" "$NAME" -- COMMAND ARG...`. The delimiter separates the optional instance name from arbitrary arguments, including flags. Additional type-specific commands are documented in the selected type's README.

For an instance name that also names an agent or mount action, put `--` after the name. For example, `"$BOXES_ROOT/box" agent "$TYPE" state -- screenshot` addresses the instance named `state`.

```sh
"$BOXES_ROOT/box" up "$TYPE" --password boxbox
"$BOXES_ROOT/box" up "$TYPE" "$NAME" --password boxbox
"$BOXES_ROOT/box" list
"$BOXES_ROOT/box" list --json
"$BOXES_ROOT/box" status --json
"$BOXES_ROOT/box" status "$TYPE" "$NAME" --json
"$BOXES_ROOT/box" url "$TYPE" "$NAME"
"$BOXES_ROOT/box" login "$TYPE" "$NAME"
"$BOXES_ROOT/box" stop "$TYPE" "$NAME"
"$BOXES_ROOT/box" start "$TYPE" "$NAME"
"$BOXES_ROOT/box" restart "$TYPE" "$NAME"
"$BOXES_ROOT/box" recreate "$TYPE" "$NAME"
"$BOXES_ROOT/box" update "$TYPE" "$NAME"
"$BOXES_ROOT/box" logs "$TYPE" "$NAME" --tail 100
"$BOXES_ROOT/box" logs "$TYPE" "$NAME" --follow
"$BOXES_ROOT/box" exec "$TYPE" "$NAME" -- id
"$BOXES_ROOT/box" shell "$TYPE" "$NAME"
"$BOXES_ROOT/box" remove "$TYPE" "$NAME"
```

`up` creates or starts an instance. Repeating it with unchanged options leaves the running container untouched. Changed options trigger recreation and are saved. If the type uses the shared package-install mod, first startup can take several minutes to install utilities. `up`, `start`, and running recreations wait for the desktop API for up to 180 seconds. `up`, `recreate`, and `update` accept `--wait SECONDS`, up to 900. A timeout leaves the container available for diagnosis. `"$BOXES_ROOT/box" agent "$TYPE" "$NAME" state` checks agent readiness.

`start` reconciles saved configuration and current source defaults. `restart` restarts the existing container without applying configuration changes. `recreate` replaces the container with the local image and current source defaults. `update` pulls the selected image or rebuilds a registered build with `--pull`, then recreates the container. Update failures leave the existing container in place. A stopped instance stays stopped during `recreate`, `update`, and mount changes.

`remove` deletes the container and Compose network. It retains the saved configuration, credentials, `/config`, and default `/work`. `up` can recreate that instance. `"$BOXES_ROOT/box" remove "$TYPE" "$NAME" --purge --yes` permanently deletes the instance's managed data and saved configuration. External workspace and mount sources are not purged. Back up before using purge.

## Human access

Each box keeps one account named `box`. `up`, `recreate`, and `update` accept `--password` to replace its password. Omit the option to retain saved credentials. A new box without the option receives a random password. Empty passwords and control characters are rejected. Password arguments are visible in shell history and host process listings.

`"$BOXES_ROOT/box" url "$TYPE" "$NAME"` prints the viewer URL. `"$BOXES_ROOT/box" login "$TYPE" "$NAME"` displays its credentials only in a terminal. The credentials also reside in the mode-600 `instance.json` reported by `status`. `"$BOXES_ROOT/box" list` prints an aligned table with one row per saved box: type, name, state, bind address, host port, and URL, with `-` for a value that is not assigned yet. A stopped or absent box shows its saved port even though nothing listens on it. Status and list output never include the password. Treat the whole state directory as secret.

A new box listens on `0.0.0.0`, every host IPv4 interface, and its URL uses the machine hostname. Docker publishes that listener on IPv4 only. Existing boxes keep their saved bind address. `--bind 127.0.0.1` restricts a box to loopback, and its URL then uses `localhost`. An explicit bind address and hostname are also supported.

```sh
BOXES_HOSTNAME=desktop-host "$BOXES_ROOT/box" up "$TYPE" "$NAME" --password boxbox --bind 100.100.1.2 --port 3443
```

Replace the example address with an address assigned to your host, and `desktop-host` with its reachable hostname. `BOXES_HOSTNAME` changes displayed URLs only. `--bind` changes the Docker listener. For a remote loopback listener, use an SSH tunnel or a trusted authenticated reverse proxy. Do not publish the raw desktop to the public internet.

The upstream certificate is self-signed. A new box serves plain HTTP, and `--https` switches it to the upstream HTTPS port. The agent client works over either scheme and does not use host HTTP proxies. Browsers only expose video and audio in a secure context, so `http://localhost` works while a hostname or private address does not: use `--https`, `--bind 127.0.0.1`, or a TLS-terminating proxy when a person needs the rendered desktop over the network. With `--https` the local agent client skips certificate verification by default; `--tls-verify` enables the system trust store and requires a certificate trusted by Python and valid for the bound address. Credentials never appear in URLs.

## Persistent configuration and mounts

Small state defaults to `${XDG_STATE_HOME:-~/.local/state}/boxes`. `BOXES_STATE_DIR` overrides it. Data defaults to `~/work/boxes`. `BOXES_DATA_DIR` overrides it for new instances. An existing instance keeps its saved data path. Do not point multiple independent installations at the same data path.

State and data paths must not overlap, including through symlinks or a saved data path. Boxes rejects equal or nested roots so purge cannot delete an instance's held lock.

Each type and name has its own `/config`, `/work`, credentials, Compose project, and lock. The first host port is selected from an available host port and saved before container creation. A box serves HTTP on internal port 3000 by default; `--https` publishes internal port 3001 instead, and `--no-https` returns it to HTTP. A box saved without a recorded scheme stays on HTTPS. Docker receives an explicit binding so stop, start, restart, and recreation retain that port. If another process takes the port before Docker binds it, startup fails instead of silently selecting another port. An explicit occupied port also fails.

```sh
"$BOXES_ROOT/box" up "$TYPE" "$NAME" --password boxbox --https
"$BOXES_ROOT/box" up "$TYPE" "$NAME" --password boxbox --workspace /absolute/project --env TZ=Europe/Amsterdam
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" set /absolute/reference /mnt/reference --mode ro
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" list
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" remove /mnt/reference
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" remove /work
"$BOXES_ROOT/box" recreate "$TYPE" "$NAME" --unset-env TZ
```

`--workspace` replaces `/work` with an existing host directory. Removing its explicit `/work` mount restores the instance's original managed workspace. Mount sources must be absolute existing real paths. Targets must be `/work` or children of `/work` or `/mnt`. Explicit mounts cannot overlap or mask each other. Mounts cannot replace system directories or `/config`. Socket and kernel-device sources are rejected.

Save app work before changing mounts or configuration. A change gracefully recreates a running desktop. Data directories are preserved, but unsaved application state is not. There is no atomic data rollback. Mount configuration is saved before reconciliation so a failed operation can be retried without repeating flags. Host directories are not recursively chowned. LinuxServer maps the desktop user through the caller's PUID and PGID.

`--image IMAGE` saves an explicit image override and bypasses a registered build. `--image ''` restores the registry default. `--env KEY=VALUE` saves an upstream runtime setting. `--unset-env KEY` removes an override. `--https` and `--no-https` choose the viewer scheme for the box.

Environment defaults merge from [runtime.json](runtime.json), then the type's registry entry, then saved instance overrides. Boxes applies the account credentials, PUID, PGID, and Pelorus enablement after that merge. The CLI also reserves `HOME`, Wayland mode, and `FILE__` settings against user overrides. Other upstream settings remain upstream behavior, not a separate tuning framework.

## Agent control

```sh
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" state
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" windows
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" screenshot --output /absolute/screen.png
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" move 600 400
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" click 600 400
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" click 600 400 --button right
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" key Escape
printf '%s' 'example text' | "$BOXES_ROOT/box" agent "$TYPE" "$NAME" text
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" key Return
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" scroll down 3
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" explore 1234
"$BOXES_ROOT/box" agent "$TYPE" "$NAME" control '{"action":"left_click_drag","start_coordinate":[100,100],"coordinate":[300,300]}'
```

These commands use the upstream `/pelorus/api/state`, `/windows`, `/desktop/screenshot`, `/desktop/explore/{pid}`, and `/desktop/control` endpoints through the authenticated viewer port. `screenshot` without `--output` returns the upstream base64 JSON. `text` without an argument reads stdin. A positional text argument is visible to host process inspection. Do not put secrets in positional arguments. `control` sends the payload to Pelorus unchanged. Use the field names the computer-use backend reads. The upstream contract declares `end_coordinate` for drags, but the backend reads `coordinate`.

Input is asynchronous. Observe a fresh screenshot or app state before the next consequential action. Pelorus returns HTTP 500 for any computer-use response that omits `result`. `cursor_position` returns only `text`, so it fails. Menu text can be absent from `state`. No failure is hidden or replaced with invented state. Use screenshots when accessibility data is incomplete.

The human and agent share one focus, pointer, and keyboard. An agent must pause on human takeover and wait for permission before resuming. There is no automatic ownership arbitration. Do not send conflicting input from multiple agents.

## Type-specific setup and tools

For the selected registry entry, open `README.md` in its `directory`. That reference covers the image, architecture, devices, storage, provisioning, and application commands. Its `SKILL.md` adds type-specific agent instructions.

The shared defaults in [runtime.json](runtime.json) use the upstream `linuxserver/mods:universal-package-install` mod to install Mousepad and imv. The mod needs package-network access after recreation. A type can override those settings, for example when its image already includes the utilities. Use `box exec` or `box shell` for tools provided by the selected image. GUI execution uses the upstream Xwayland display `:0`. The CLI does not replace upstream service definitions or desktop menus.

## Security boundaries

Containers share the host kernel. They are not strong sandboxes for hostile code. Desktop sessions can run commands, read their mounts, and access the network. The upstream desktop user has sudo access inside the container. A writable bind mount gives that session the ability to modify its source. Even a read-only socket mount can grant control of its service. Do not mount Docker sockets, sensitive host directories, or credentials into untrusted sessions.

Boxes does not use privileged mode, host networking, or a Docker socket mount. Only the authenticated viewer port is published: internal port 3000 for the default HTTP box and internal port 3001 for `--https`. A new box publishes it on every host IPv4 interface by default, so anyone who can reach the host can reach the login prompt. Use a host firewall, or `--bind 127.0.0.1` or a private address, on untrusted networks. Raw control ports 5000 and 5100 are not published. Device access comes from the selected registry entry. Strong random Basic Auth does not make an internet-facing remote desktop safe.

## Runtime ownership

[registry.json](registry.json) defines image or build, app commands, architecture, device access, and app defaults. [runtime.json](runtime.json) defines inherited Selkies settings. The generated private Compose file lives beside each `instance.json`. Docker Compose owns containers and networking. Python owns validation, atomic per-instance configuration, file locking, and authenticated API calls. No boxes daemon or global mutable registry runs.

Types use upstream images directly or build child images that retain upstream entrypoints and services. Shared runtime settings apply locally through generated Compose configuration. They do not require every type to inherit a locally built base image. Image builds and runtime settings are separate. A Dockerfile edit takes effect after rebuilding with `update`, not just after `recreate`.

## Add a type

Add an entry to [registry.json](registry.json) using the fields accepted by `BoxType` in [boxes/model.py](boxes/model.py). The registry key supplies `name`. Required fields are `directory`, `image`, `architectures`, `devices`, `environment`, and `commands`. Only `build` is optional.

This illustrative entry uses a placeholder image. Replace it with a compatible upstream desktop image before use.

```json
{
	"example": {
		"directory": "example-box",
		"image": "<compatible-desktop-image>",
		"architectures": ["amd64"],
		"devices": [],
		"environment": {},
		"commands": {}
	}
}
```

`directory` names the type's repository directory. Add its `README.md` and `SKILL.md` there. `architectures` lists supported host architectures. `devices` lists required host device paths. `environment` maps settings to string defaults. `commands` maps command hooks to argument lists. An optional `build` names a repository-relative Docker build context.

Registering a command hook does not create a new CLI subcommand. Hooks work only where the existing dispatcher handles them. Extending the CLI requires explicit dispatcher changes and tests. Add type-specific checks to the verifier when needed. Its fixture set is not generated from the registry.

## Evidence and checks

Run the unit suite from the repository root. Inspect the verifier's options before selecting integration fixtures.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/verify.py --help
```

The real-Docker verifier checks its currently implemented fixtures, not arbitrary new registry types. It creates unique `boxes-test-*` projects with isolated state and data under `~/work/boxes/verification`. Shared checks cover authenticated APIs, input, screenshots, persistence, mount recreation, and lifecycle behavior. Type-specific checks depend on the selected fixtures and their prerequisites. `--viewer` adds rendered-viewer checks and requires the separately installed `agent-browser` CLI and its browser.

The verifier removes only its own containers unless `--keep-running` is supplied. It retains data, command logs, screenshots, and a JSON report. A test command or an earlier report is not proof that the current fixtures pass. Inspect the report for failures and skips.

## Agent skills

The [core skill](SKILL.md) lives beside the CLI and its runtime assets. Each registered type keeps its own `SKILL.md` and `README.md` in the directory named by [registry.json](registry.json). Behavioral eval cases live in [tests/skill-evals/evals.json](tests/skill-evals/evals.json).

One `~/.config/opencode/skills/boxes` symlink to the repository root registers the core skill and its nested children. OpenCode V2 discovers nested `SKILL.md` files recursively. Each containing directory's name determines its skill ID. Frontmatter `name` is a display label. No separate child links are needed.

For an installation elsewhere, run the following only when global registration is wanted. Set `BOXES_ROOT` as described under Commands first. `ln` refuses to replace an existing entry.

```sh
mkdir -p "$HOME/.config/opencode/skills"
ln -sT -- "$BOXES_ROOT" "$HOME/.config/opencode/skills/boxes"
```

For project-local registration, link the repository root as `.opencode/skills/boxes` instead. Do not configure the repository root itself as a skill source. V2 treats a source-root `SKILL.md` as the ID `SKILL`.
