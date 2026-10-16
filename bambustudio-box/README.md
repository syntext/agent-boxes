# Bambu Studio box reference

`"$BOXES_ROOT/box" up bambu [NAME]` starts the stock `lscr.io/linuxserver/bambustudio` amd64 image. Upstream launches the app. First startup shows Bambu Studio's setup wizard. Printer, filament, and account choices remain the user's decisions.

Set `BOXES_ROOT` using the [root README](../README.md#commands) or the skill tool's base directory as shown in the [Bambu skill](SKILL.md). The root README covers shared commands and security boundaries.

```sh
"$BOXES_ROOT/box" agent bambu state
"$BOXES_ROOT/box" agent bambu screenshot --output /absolute/bambu.png
"$BOXES_ROOT/box" exec bambu -- /opt/bambustudio/AppRun --help
"$BOXES_ROOT/box" exec bambu -- /opt/bambustudio/AppRun --info /work/model.stl
"$BOXES_ROOT/box" exec bambu -- /opt/bambustudio/AppRun --slice 0 --export-3mf /work/sliced.3mf /work/project.3mf
```

The observed upstream launcher is `/opt/bambustudio/AppRun`. It sets `LD_LIBRARY_PATH` before executing `bin/bambu-studio`. Use the launcher for CLI work. The verified `--help` output lists `--slice`, `--export-3mf`, `--load-settings`, and `--load-filaments`.

Slicing needs valid machine, process, and filament settings or a prepared 3MF that contains them. A raw STL alone is not a portable slicing preset. Use `--load-settings` and `--load-filaments` for explicit presets. Review generated files before printing. Boxes never sends a job to a printer by itself.

The development smoke test sliced a private copy of an existing prepared 3MF and verified that the exported archive contains G-code. The CLI reported that OpenGL initialization failed and skipped thumbnail generation. That test proves slicing and export, not headless thumbnail rendering.
