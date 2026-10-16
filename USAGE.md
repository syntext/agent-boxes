# Boxes usage reference

This reference describes the shared CLI, storage, access, and runtime behavior. The [README](README.md) covers installation and the first desktop.

## Commands

The examples use variables set in the repository root. `TYPE` is a key from [registry.json](registry.json), not the literal placeholder below.

```sh
BOXES_ROOT="$(pwd -P)"
TYPE='<registered-type>'
NAME=research
```

`"$BOXES_ROOT/box"` works from any directory. No global CLI installation is needed. Agents use the base directory supplied by the skill tool, as described in the [core skill](SKILL.md).

A registered directory name is also accepted as a type alias. An omitted instance name means `default`. The selected registry entry's `directory` contains its README and skill. Additional app commands belong to that type's reference.

Pass-through execution requires `exec TYPE [NAME] -- COMMAND ARG...`. The delimiter separates the optional instance name from arbitrary arguments, including flags.

For an instance name that also names an agent or mount action, `--` follows the name. For example, `"$BOXES_ROOT/box" agent "$TYPE" state -- screenshot` addresses the instance named `state`.

```sh
"$BOXES_ROOT/box" up "$TYPE"
"$BOXES_ROOT/box" up "$TYPE" "$NAME"
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

### Lifecycle

`up` creates or starts an instance. Repeating it with unchanged options leaves the running container untouched. Changed options trigger recreation and are saved. First startup can take several minutes when the type uses the shared package-install mod.

`up`, `start`, and running recreations wait for the desktop API for up to 180 seconds. `up`, `recreate`, and `update` accept `--wait SECONDS`, up to 900. A timeout leaves the container available for diagnosis. `"$BOXES_ROOT/box" agent "$TYPE" "$NAME" state` checks agent readiness.

`start` reconciles saved configuration and current source defaults. `restart` restarts the existing container without applying configuration changes. `recreate` replaces the container with the local image and current source defaults.

`update` pulls the selected image or rebuilds a registered build with `--pull`, then recreates the container. Update failures leave the existing container in place. A stopped instance stays stopped during `recreate`, `update`, and mount changes.

`remove` deletes the container and Compose network. It retains saved configuration, credentials, `/config`, and the default `/work`. `up` can recreate that instance.

`remove TYPE NAME --purge --yes` permanently deletes the instance's managed data and saved configuration. External workspace and mount sources are not purged. A backup is required to recover purged data.

### List and status output

`list` prints an aligned table with one row per saved box. The columns are type, name, state, bind address, host port, and URL. An unassigned value appears as `-`. A stopped or absent box shows its saved port even though nothing listens on it.

`list --json` and `status --json` provide machine-readable output. Status and list output never include the password. `status` reports the location of the private `instance.json` file.

## Human access and TLS

### Account and credentials

Each box has one account named `box`. `up`, `recreate`, and `update` accept `--password` to replace its password. Omitting the option retains saved credentials. A new box without the option receives a random password.

Empty passwords, control characters, and a leading hyphen are rejected. The upstream image passes the password to `openssl passwd`, which reads a leading hyphen as an option and leaves the box unreachable. Password arguments are visible in shell history and host process listings.

`url` prints the viewer URL. `login` displays credentials only in a terminal. Credentials also reside in the mode-600 `instance.json` reported by `status`. The whole state directory is secret. Credentials never appear in URLs.

### Listener and hostname

A new box binds to `0.0.0.0`, every host IPv4 interface, and its URL uses the machine hostname. Docker publishes this listener on IPv4 only. Existing boxes retain their saved bind address.

`--bind 127.0.0.1` restricts a box to loopback. Its URL then uses `localhost`. An explicit bind address and hostname are also supported.

```sh
BOXES_HOSTNAME=desktop-host "$BOXES_ROOT/box" up "$TYPE" "$NAME" --bind 100.100.1.2 --port 3443
```

The example address must be assigned to the host, and `desktop-host` must be its reachable hostname. `BOXES_HOSTNAME` changes displayed URLs only. `--bind` changes the Docker listener.

Remote access to a loopback listener requires an SSH tunnel or a trusted authenticated reverse proxy. The raw desktop is not suitable for public internet exposure.

### HTTPS and HTTP

HTTPS is the default. The upstream certificate is self-signed, so browsers show a certificate warning. Proceeding past that warning is appropriate only for a trusted host.

HTTPS provides the secure context required by the web viewer away from localhost. Outside a secure context, the web client displays "This application requires a secure connection (HTTPS)". The localhost exception does not make HTTP the supported human access path.

`--http` selects the upstream HTTP port. HTTP is an explicit agent-only loopback mode, paired with `--bind 127.0.0.1`. `--no-http` restores HTTPS.

```sh
"$BOXES_ROOT/box" up "$TYPE" "$NAME" --http --bind 127.0.0.1
"$BOXES_ROOT/box" up "$TYPE" "$NAME" --no-http
```

The agent client works over either scheme and does not use host HTTP proxies. It skips certificate verification by default. `--tls-verify` enables the system trust store and requires a certificate trusted by Python and valid for the bound address. `--no-tls-verify` disables that check. These options affect the agent client, not the browser's certificate trust.

## Persistent configuration and mounts

### State and data

Small state defaults to `${XDG_STATE_HOME:-~/.local/state}/boxes`. `BOXES_STATE_DIR` overrides it. Data defaults to `~/work/boxes`. `BOXES_DATA_DIR` overrides it for new instances. An existing instance retains its saved data path. Independent installations must not share a data path.

State and data paths must not overlap, including through symlinks or a saved data path. Boxes rejects equal or nested roots so purge cannot delete an instance's held lock.

Each type and name has its own `/config`, `/work`, credentials, Compose project, and lock. The first host port is selected from available ports and saved before container creation. Docker receives an explicit binding, so stop, start, restart, and recreation retain the port.

A box serves HTTPS on internal port 3001 by default. `--http` publishes internal port 3000 instead. A box saved without a recorded scheme stays on HTTPS. If another process takes the selected port before Docker binds it, startup fails rather than selecting another port. An explicit occupied port also fails.

### Workspaces and mounts

The following examples require existing absolute host directories.

```sh
"$BOXES_ROOT/box" up "$TYPE" "$NAME" --workspace /absolute/project --env TZ=Europe/Amsterdam
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" set /absolute/reference /mnt/reference --mode ro
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" list
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" remove /mnt/reference
"$BOXES_ROOT/box" mount "$TYPE" "$NAME" remove /work
"$BOXES_ROOT/box" recreate "$TYPE" "$NAME" --unset-env TZ
```

`--workspace` replaces `/work` with an existing host directory. Removing its explicit `/work` mount restores the instance's original managed workspace. Mount mode defaults to `rw`. `--mode ro` selects a read-only mount.

Mount sources must be absolute existing real paths. Targets must be `/work` or children of `/work` or `/mnt`. Explicit mounts cannot overlap or mask each other. Mounts cannot replace system directories or `/config`. Socket and kernel-device sources are rejected.

Mount or configuration changes gracefully recreate a running desktop. Data directories survive, but unsaved application state does not. There is no atomic data rollback. Saving app work before a change prevents that loss.

Mount configuration is saved before reconciliation, so a failed operation can be retried without repeating flags. Host directories are not recursively chowned. LinuxServer maps the desktop user through the caller's PUID and PGID.

### Image and environment overrides

`--image IMAGE` saves an explicit image override and bypasses a registered build. `--image ''` restores the registry default. `--env KEY=VALUE` saves an upstream runtime setting. `--unset-env KEY` removes an override.

Environment defaults merge from [runtime.json](runtime.json), then the type's registry entry, then saved instance overrides. Boxes applies account credentials, PUID, PGID, and Pelorus enablement after that merge. The CLI also reserves `HOME`, Wayland mode, and `FILE__` settings against user overrides. Other upstream settings retain their upstream behavior.

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

These commands use the upstream `/pelorus/api/state`, `/windows`, `/desktop/screenshot`, `/desktop/explore/{pid}`, and `/desktop/control` endpoints through the authenticated viewer port. `explore` requires the target process ID. Click buttons include `left`, `right`, `middle`, and `double`.

`screenshot` without `--output` returns the upstream base64 JSON. `text` without an argument reads stdin. A positional text argument is visible to host process inspection and is unsuitable for secrets.

`control` sends the payload to Pelorus unchanged. The computer-use backend's field names determine behavior. The upstream contract declares `end_coordinate` for drags, but the backend reads `coordinate`.

Input is asynchronous. A fresh screenshot or app state is needed before the next consequential action. Pelorus returns HTTP 500 for any computer-use response that omits `result`. `cursor_position` returns only `text`, so it fails. Menu text can be absent from `state`. Failures are not hidden or replaced with invented state. Screenshots provide evidence when accessibility data is incomplete.

The human and agent share one focus, pointer, and keyboard. An agent must pause on human takeover and wait for permission before resuming. There is no automatic ownership arbitration. Conflicting input from multiple agents is unsafe.

## Recording and lessons

A box records its own desktop and viewer input. The resulting video, events, and frames provide material for an agent to draft a repeatable lesson after a human demonstration.

```sh
"$BOXES_ROOT/box" record "$TYPE" "$NAME" start --fps 15 --overlay
"$BOXES_ROOT/box" record "$TYPE" "$NAME" pause
"$BOXES_ROOT/box" record "$TYPE" "$NAME" resume
"$BOXES_ROOT/box" record "$TYPE" "$NAME" stop
"$BOXES_ROOT/box" record "$TYPE" "$NAME" status
"$BOXES_ROOT/box" record "$TYPE" "$NAME" list
"$BOXES_ROOT/box" lessons "$TYPE" list
"$BOXES_ROOT/box" lessons "$TYPE" path
printf '%s\n' '# Example workflow' | "$BOXES_ROOT/box" lessons "$TYPE" record example-workflow
"$BOXES_ROOT/box" lessons "$TYPE" show example-workflow
```

`start` records the screen and logs the viewer's clicks, drags, scrolls, and keystrokes with timestamps. The default frame rate is 15. `--fps` accepts 1 to 60. The optional `--overlay` draws input on the live desktop.

`pause` stops both the recorder and the input log. `resume` continues in a new segment. A pause excludes input entered during the pause, but private content still visible after resume can appear in the video.

`stop` joins the segments and renders an annotated video with clicks, drags, scrolls, and typed text. It extracts frames around clicks and scene changes. The result is copied to `BOXES_DATA_DIR/recordings/<type>/<name>/<timestamp>/` under the instance's saved data root. The directory contains `screen.mp4`, `screen-annotated.mp4`, `events.jsonl`, `index.json`, `frames/`, and `recording.json`.

Typed text is recorded in full. Screen contents and input can include private information. Recordings are secrets and must not be committed. Nothing deletes a recording automatically. `record TYPE NAME forget RECORDING` removes the named recording when a person requests it. `list` supplies recording names.

The input log comes from the box's own viewer connection. Human demonstrations must take place in that viewer's desktop. The tools require `ffmpeg` and `wf-recorder`. The optional overlay requires `gir1.2-gtklayershell-0.1` and `python3-gi-cairo` for PyGObject's cairo binding. Shared defaults install these packages. Boxes created before those defaults need `recreate` or `update` first.

The input tap opens its capture socket as the container's root account, then drops to the desktop account before writing. It reads only the box's own loopback traffic and changes no upstream service.

Lessons are Markdown files under `BOXES_DATA_DIR/lessons/<type>/`. Every box of that type shares them. An agent loads lessons before a task, follows a matching lesson step by step, and drafts new lessons for review after a recording.

## Type-specific setup and tools

Each entry in [registry.json](registry.json) names a `directory`. Its `README.md` documents the image, architecture, devices, storage, provisioning, and app commands. Its `SKILL.md` contains type-specific agent instructions. The registry is the type directory index.

The shared defaults in [runtime.json](runtime.json) use `linuxserver/mods:universal-package-install` to install Mousepad, imv, and the [recording tools](#recording-and-lessons). The mod needs package-network access after recreation. A type can override those settings when its image already includes the utilities.

`box exec` and `box shell` provide access to tools in the selected image. GUI execution uses the upstream Xwayland display `:0`. The CLI does not replace upstream service definitions or desktop menus.

## Security boundaries

Containers share the host kernel. They are not strong sandboxes for hostile code. Desktop sessions can run commands, read their mounts, and access the network. The upstream desktop user has sudo access inside the container.

A writable bind mount lets the session modify its source. Even a read-only socket mount can grant control of its service. Docker sockets, sensitive host directories, and credentials are unsuitable mounts for untrusted sessions.

Boxes does not use privileged mode, host networking, or a Docker socket mount. Only the authenticated viewer port is published. It uses internal port 3001 for default HTTPS and internal port 3000 for `--http`.

A new box publishes its viewer on every host IPv4 interface. Anyone who can reach the host can reach the login prompt. A host firewall, loopback binding, or private-address binding limits exposure on untrusted networks. Strong random Basic Auth does not make an internet-facing remote desktop safe.

Raw control ports 5000 and 5100 are not published. Device access comes from the selected registry entry.

## Runtime ownership

[registry.json](registry.json) defines each type's image or build, app commands, architecture, device access, and app defaults. [runtime.json](runtime.json) defines inherited Selkies settings. The generated private Compose file lives beside each `instance.json`.

Docker Compose owns containers and networking. Python owns validation, atomic per-instance configuration, file locking, and authenticated API calls. No Boxes daemon or global mutable instance registry runs.

Types use upstream images directly or build child images that retain upstream entrypoints and services. Shared runtime settings apply through generated Compose configuration. Types do not need a locally built base image.

Image builds and runtime settings are separate. A Dockerfile edit takes effect after rebuilding with `update`, not just after `recreate`.

## Adding a type

Registry entries use the fields accepted by `BoxType` in [boxes/model.py](boxes/model.py). The registry key supplies `name`. Required fields are `directory`, `image`, `architectures`, `devices`, `environment`, and `commands`. Only `build` is optional.

The following illustrative entry contains a placeholder image. It requires a compatible upstream desktop image before use.

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

`directory` names the type's repository directory, which contains its `README.md` and `SKILL.md`. `architectures` lists supported host architectures. `devices` lists required host device paths. `environment` maps settings to string defaults. `commands` maps command hooks to argument lists. The optional `build` names a repository-relative Docker build context.

A command hook does not create a CLI subcommand. Hooks work only where the existing dispatcher handles them. Extending the CLI requires explicit dispatcher changes and tests. Type-specific verifier checks are added separately. Its fixture set is not generated from the registry.

## Evidence and checks

The unit suite runs from the repository root. The verifier's help lists integration fixture options.

```sh
python3 -m unittest discover -s tests -v
python3 scripts/verify.py --help
```

The real-Docker verifier checks its implemented fixtures, not arbitrary registry types. It creates unique `boxes-test-*` projects with isolated state and data under `~/work/boxes/verification`.

Shared checks cover authenticated APIs, input, screenshots, persistence, mount recreation, and lifecycle behavior. Type-specific checks depend on the selected fixtures and their prerequisites. `--viewer` adds rendered-viewer checks and requires the separately installed `agent-browser` CLI and its browser.

The verifier removes only its own containers unless `--keep-running` is supplied. It retains data, command logs, screenshots, and a JSON report. A test command or earlier report does not prove that current fixtures pass. The report records failures and skips.

## Agent skills

The [core skill](SKILL.md) lives beside the CLI and its runtime assets. Each type keeps its own `SKILL.md` and `README.md` in the directory named by [registry.json](registry.json). Behavioral eval cases live in [tests/skill-evals/evals.json](tests/skill-evals/evals.json).

The [README's skill installation](README.md#install-as-an-agent-skill) uses the shared `~/.agents/skills` directory. Other agents may require separate registration for nested skills.

For an existing checkout, one `~/.config/opencode/skills/boxes` symlink registers the core skill and nested children. OpenCode V2 discovers nested `SKILL.md` files recursively. Each containing directory's name determines its skill ID. Frontmatter `name` is a display label. Separate child links are not needed.

The following commands request global registration. They use `BOXES_ROOT` from [Commands](#commands). `ln` refuses to replace an existing entry.

```sh
mkdir -p "$HOME/.config/opencode/skills"
ln -sT -- "$BOXES_ROOT" "$HOME/.config/opencode/skills/boxes"
```

Project-local registration uses `.opencode/skills/boxes` instead. The repository root itself must not be configured as a skill source. V2 treats a source-root `SKILL.md` as the ID `SKILL`.
