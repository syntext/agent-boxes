---
name: bambustudio-box
description: Operate Bambu Studio in bambustudio-box through its shared desktop API or the upstream AppRun slicing CLI. Use for inspecting models, configuring slicing, and exporting files.
---

# Bambu Studio operations

Read [the core operating skill](../SKILL.md) before startup. Replace `<skill-base>` with this child skill's base directory supplied by the skill tool.

```sh
BOXES_SKILL_BASE='<skill-base>'
BOXES_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().parent)' "$BOXES_SKILL_BASE")"
```

Run `"$BOXES_ROOT/box"` from any working directory. Start the desktop with `"$BOXES_ROOT/box" up bambu NAME`. Omit `--password` to preserve saved credentials or generate a random password for a new box; `BOXES_STATE_DIR/.passwd` supplies the default instead. Read [the Bambu reference](README.md) for the observed CLI launcher and preset requirements.

Use type `bambu`. Inspect a screenshot before choosing input coordinates. The first-run setup wizard needs user choices. Do not guess a printer, account region, filament, or license acceptance.

Run CLI commands through `"$BOXES_ROOT/box" exec bambu NAME -- /opt/bambustudio/AppRun ...`. Read `--help` on the installed version before constructing a slicing command. Prefer a prepared 3MF with machine, process, and filament settings. Keep input models read-only when possible and write outputs under `/work`.

Verify that an export exists and contains the expected result. Do not infer success from a running GUI. Do not send a print job, connect a printer, or upload private designs without the user's explicit authorization.

## Recording and lessons

`"$BOXES_ROOT/box" record bambu NAME start --overlay` is the way to capture how a
human prepares a slice by hand, which the CLI cannot express. Read the frames for
the settings they chose and check that the same values appear in the saved
preset before relying on them. Boxes still never sends a print job.
