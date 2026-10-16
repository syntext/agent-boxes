---
name: boxes
description: Operate persistent browser, Android, or Bambu Studio desktops through the boxes CLI. Use for starting named boxes, sharing workspaces, inspecting screenshots, sending desktop input, or running commands in those sessions.
---

# Operate a box

Resolve the base directory supplied by the skill tool before running commands. Replace `<skill-base>` below with that exact directory, not the current working directory.

```sh
BOXES_SKILL_BASE='<skill-base>'
BOXES_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$BOXES_SKILL_BASE")"
```

Use `"$BOXES_ROOT/box"` from any working directory. No PATH entry or global CLI shim is needed. Read [the root reference](README.md) for options and security boundaries. Read the [browser](browser-box/SKILL.md), [Android](android-devbox/SKILL.md), or [Bambu Studio](bambustudio-box/SKILL.md) skill for app-specific commands.

1. Select a type and instance name. Run `"$BOXES_ROOT/box" status TYPE NAME --json` or `"$BOXES_ROOT/box" list --json` before changing it.
2. Start it with `"$BOXES_ROOT/box" up TYPE NAME --password boxbox` when needed. Pass the password explicitly for default and named instances. A new Android desktop does not start an emulator.
3. Run `"$BOXES_ROOT/box" agent TYPE NAME state` and take a screenshot with `"$BOXES_ROOT/box" agent TYPE NAME screenshot --output /absolute/path.png`. Read the image before choosing coordinates.
4. Send one deliberate action with `move`, `click`, `key`, `text`, or `scroll`. Read fresh state or a screenshot to verify the result. Input completion is asynchronous.
5. Use `"$BOXES_ROOT/box" exec TYPE NAME -- COMMAND ARG...` for explicit noninteractive work. Use `shell` only for an interactive terminal.

The human and agent share one pointer, keyboard, and focus. Pause when the human takes over. Resume only after agreement. Do not compete with another agent's input.

Use stdin for sensitive text. Do not print `instance.json`, credentials, cookies, or private environment values. Use `"$BOXES_ROOT/box" login` only when a human requests credentials at a terminal. Never embed credentials in a URL.

Save application work before mount changes, update, or recreation. Those operations replace the desktop container. Do not purge data without explicit permission. Do not touch sibling legacy projects or containers.

State can omit menus and custom-rendered content. Use screenshots rather than inventing missing elements. The upstream `cursor_position` action is known to fail with HTTP 500. Do not report it as supported. Pelorus requests use the authenticated HTTPS viewer port. Do not publish raw control ports or configure model credentials.

One global `~/.config/opencode/skills/boxes` link to this repository root registers this skill and its nested children. Do not create or change global skill links unless asked.

Each box keeps one account named `box`. Password arguments are visible in shell history and host process listings. Omitting `--password` retains saved credentials or generates a random password for a new box.
