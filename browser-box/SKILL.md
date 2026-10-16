---
name: browser-box
description: Control the Chromium desktop in browser-box, including named profiles, page navigation through desktop input, screenshots, and workspace files.
---

# Browser operations

Read [the core operating skill](../SKILL.md) before startup. Replace `<skill-base>` with this child skill's base directory supplied by the skill tool.

```sh
BOXES_SKILL_BASE='<skill-base>'
BOXES_ROOT="$(python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve().parent)' "$BOXES_SKILL_BASE")"
```

Run `"$BOXES_ROOT/box"` from any working directory. Start the desktop with `"$BOXES_ROOT/box" up browser NAME --password boxbox`.

Use type `browser`. Choose a named instance for an isolated profile. Chromium profile data persists in `/config`. User files belong in `/work`.

Navigate with `"$BOXES_ROOT/box" agent browser NAME key ctrl+l`, send the URL with `text`, and press `Return`. Inspect a fresh screenshot after navigation. Do not enable a public CDP port. Use the stock desktop API unless the task explicitly requires a different integration.

Read [the browser reference](README.md) for startup settings. Preserve the user's existing tabs, credentials, and downloads. Ask before external submissions or account changes.
