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
2. Start it with `"$BOXES_ROOT/box" up TYPE NAME` when needed. Omit `--password` to preserve saved credentials or generate a random password for a new box. A new Android desktop does not start an emulator.
3. Run `"$BOXES_ROOT/box" agent TYPE NAME state` and take a screenshot with `"$BOXES_ROOT/box" agent TYPE NAME screenshot --output /absolute/path.png`. Read the image before choosing coordinates.
4. Send one deliberate action with `move`, `click`, `key`, `text`, or `scroll`. Read fresh state or a screenshot to verify the result. Input completion is asynchronous.
5. Use `"$BOXES_ROOT/box" exec TYPE NAME -- COMMAND ARG...` for explicit noninteractive work. Use `shell` only for an interactive terminal.

The human and agent share one pointer, keyboard, and focus. Pause when the human takes over. Resume only after agreement. Do not compete with another agent's input.

Use stdin for sensitive text. Do not print `instance.json`, credentials, cookies, or private environment values. Use `"$BOXES_ROOT/box" login` only when a human requests credentials at a terminal. Never embed credentials in a URL.

Save application work before mount changes, update, or recreation. Those operations replace the desktop container. Do not purge data without explicit permission. Do not touch sibling legacy projects or containers.

## Learn from the user

When the human says to learn from them, watch them work, or do it the way they
just did, record the desktop while they act:

1. Confirm which box they mean, then run
   `"$BOXES_ROOT/box" record TYPE NAME start`. Add `--overlay` when they want to
   see the clicks and keys drawn on the live desktop as they work. Say plainly
   that the screen is recorded and that their typing is logged in full, and offer
   `"$BOXES_ROOT/box" record TYPE NAME pause` for a password or anything else
   private, then `resume` afterwards.
2. Send no input while they work. The desktop has one pointer and keyboard.
3. When they say they are done, run `"$BOXES_ROOT/box" record TYPE NAME stop`.
   It returns the recording directory, an annotated video, and a frame index.
   Recordings are kept until `box record TYPE NAME forget RECORDING` removes one,
   and only when the human asks.
4. Read `events.jsonl` in the recording directory for what they did — clicks with
   their positions, drags, scrolls, and the text they typed — then read the
   frames the index names, in order, for what was on screen. Take the intent from
   the two together; do not guess an action that no event shows.
5. Draft the lesson, show it to the human, and save it only once they agree:
   `"$BOXES_ROOT/box" lessons TYPE record SLUG` reads the Markdown from stdin.
   Lessons live per type under `BOXES_DATA_DIR/lessons`, so any box of that type
   can use them.

Before a task, run `"$BOXES_ROOT/box" lessons TYPE list`. When a lesson matches,
follow it step by step and check a fresh screenshot after each step. Stop and ask
when the screen does not match what the lesson expects. The usual limits still
apply: no external submissions and no account changes without permission.

A recording holds the desktop as it was, private content included. Keep the
directory private, never commit it, and never paste it into a report or a
message. Coordinates in a lesson are a hint, not the instruction: describe what
to click by its visible label or landmark, because coordinates break when a page
or window layout changes.

`record` and `lessons` need a keyboard and pointer that the box can see. A
recording of a box nobody is viewing still captures the screen, but the tap only
sees input that arrives over the box's own viewer connection, so ask the human to
work in that viewer.

State can omit menus and custom-rendered content. Use screenshots rather than inventing missing elements. `cursor_position` is unsupported: Pelorus returns HTTP 500 for any computer-use response that omits `result`, which `cursor_position` does. Do not report it as supported. Send a drag with `coordinate`; the upstream contract's `end_coordinate` field is ignored. Pelorus requests use the authenticated viewer port, which serves HTTPS unless the box was started with `--http`; an HTTP box's web client only renders from `http://localhost`. Do not publish raw control ports or configure model credentials. A new box listens on every host IPv4 interface. Pass `--bind 127.0.0.1` when the human wants loopback only. `"$BOXES_ROOT/box" list` shows each box's bind address, port, and URL.

One global `~/.config/opencode/skills/boxes` link to this repository root registers this skill and its nested children. Do not create or change global skill links unless asked.

Each box keeps one account named `box`. Password arguments are visible in shell history and host process listings. Omitting `--password` retains saved credentials or generates a random password for a new box.
