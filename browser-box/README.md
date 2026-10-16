# Browser box reference

`"$BOXES_ROOT/box" up browser [NAME] --password boxbox` starts the stock `lscr.io/linuxserver/chromium` desktop. The default name is `default`. Chromium's profile persists under the instance's `/config`. Downloads and user work belong under `/work`.

Set `BOXES_ROOT` using the [root README](../README.md#commands) or the skill tool's base directory as shown in the [browser skill](SKILL.md). The root README covers shared commands, login, mounting rules, and security limits.

```sh
"$BOXES_ROOT/box" up browser research --password boxbox --workspace /absolute/project
"$BOXES_ROOT/box" agent browser research state
"$BOXES_ROOT/box" agent browser research key ctrl+l
printf '%s' 'https://example.com' | "$BOXES_ROOT/box" agent browser research text
"$BOXES_ROOT/box" agent browser research key Return
"$BOXES_ROOT/box" agent browser research screenshot --output /absolute/browser.png
```

`CHROME_CLI` is an upstream runtime setting. Boxes defaults it to `https://www.example.com`. A saved `--env CHROME_CLI=...` overrides that default. No public CDP port is enabled. Desktop agent control does not require CDP.
