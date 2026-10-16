---
name: android-devbox
description: Operate the Android SDK and KVM emulator inside android-devbox. Use for explicit emulator start, stop, boot checks, adb commands, and shared desktop screenshots.
---

# Android operations

Read [the core operating skill](../SKILL.md) before startup. Replace `<skill-base>` with this child skill's base directory supplied by the skill tool.

```sh
BOXES_SKILL_BASE='<skill-base>'
BOXES_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().parent)' "$BOXES_SKILL_BASE")"
```

Run `"$BOXES_ROOT/box"` from any working directory. Start the desktop with `"$BOXES_ROOT/box" up android NAME --password boxbox`. Read [the Android reference](README.md) before SDK provisioning.

Use type `android`. Run `"$BOXES_ROOT/box" emu android NAME status` before starting an emulator. Start it only when the task needs Android. Use `"$BOXES_ROOT/box" emu android NAME start --wait 240` for a bounded boot check. Use `"$BOXES_ROOT/box" adb android NAME -- shell getprop sys.boot_completed` to check Android itself. Always include `--` before adb arguments. Omit `NAME` to use `default`.

The desktop starts without an emulator. Stop it with `"$BOXES_ROOT/box" emu android NAME stop` when the task no longer needs it. Do not start Android Studio or publish adb.

SDK and AVD data are private to `/config`. Never point a new instance at a legacy live writable SDK or AVD directory. Use a read-only seed and a private copy. SDK license acceptance is a legal decision. Do not pass `--accept-licenses` unless the user explicitly authorized that acceptance.

Use `"$BOXES_ROOT/box" agent android NAME screenshot --output /absolute/path.png` for the shared desktop. Use adb for Android app commands. Verify that boot completed before installing or launching an app.

## Recording and lessons

`"$BOXES_ROOT/box" record android NAME start` records the emulator screen and logs
input. The emulator window is one part of the desktop, so crop or reason about its
region when reading frames. A recording does not replace the emulator lifecycle
commands: start and stop the emulator explicitly before and after.
