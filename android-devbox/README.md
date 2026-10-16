# Android box reference

`"$BOXES_ROOT/box" up android [NAME]` starts a labwc desktop with a terminal. The emulator stays stopped. This amd64 image needs `/dev/kvm`, but does not need privileged mode, host networking, or Android Studio.

Set `BOXES_ROOT` using the [root README](../README.md#commands) or the skill tool's base directory as shown in the [Android skill](SKILL.md).

The SDK lives in `/config/sdk`. AVDs and emulator logs live in `/config/.android`. Both survive recreation. App projects belong in `/work`. Each instance has its own SDK and AVD data.

## SDK provisioning

No SDK license is accepted during build or desktop startup. Command-line tools are downloaded at build time. Package installation and license acceptance require explicit commands.

```sh
"$BOXES_ROOT/box" shell android
box-sdk licenses
box-sdk install
exit
```

`box-sdk licenses` runs the official interactive `sdkmanager --licenses` flow. `box-sdk install` installs platform-tools, emulator, Android 36, build-tools 36.1.0, and the Android 36 Google APIs x86_64 system image. `box-sdk install --accept-licenses` explicitly accepts the SDK licenses before installation. Use that flag only if you are authorized to accept those terms.

An existing licensed SDK can seed a private copy without modifying the source.

```sh
"$BOXES_ROOT/box" mount android set /absolute/existing-sdk /mnt/sdk --mode ro
"$BOXES_ROOT/box" exec android -- box-sdk seed /mnt/sdk
"$BOXES_ROOT/box" mount android remove /mnt/sdk
"$BOXES_ROOT/box" exec android -- box-sdk status
```

The seed command copies only command-line tools, licenses, and the required packages. It retains packages already present in the destination. It does not share the live SDK, AVDs, or writable files with the source. The copied license records are not a new acceptance of terms.

## Emulator control

```sh
"$BOXES_ROOT/box" emu android status
"$BOXES_ROOT/box" exec android -- emulator -accel-check
"$BOXES_ROOT/box" emu android start --wait 240
"$BOXES_ROOT/box" adb android -- devices
"$BOXES_ROOT/box" adb android -- shell getprop sys.boot_completed
"$BOXES_ROOT/box" agent android screenshot --output /absolute/android.png
"$BOXES_ROOT/box" emu android stop
```

`start` creates a `boxes` Pixel 8 AVD when none exists. It uses KVM, a software SwiftShader GPU, four vCPUs, 2 GiB RAM, no audio, and no snapshots. `--wait SECONDS` waits for `sys.boot_completed=1`, with a maximum of 900 seconds. A timeout leaves the emulator running for diagnosis. Repeating start or stop is safe. Instance restart never starts an emulator automatically.

Boot completion is not an app-readiness check. On the development host, Android's first launcher and Settings startup continued after that property became `1`. An early Settings launch timed out before the app later rendered normally. Observe the actual app before sending input. Software rendering and concurrent emulator instances can make cold starts slow.

The emulator uses the upstream labwc Xwayland display `:0` with `QT_QPA_PLATFORM=xcb`. The image includes its Qt XCB dependencies. `box emu` serializes operations inside the container. `box adb android [NAME] -- ARGS...` requires the delimiter and passes arbitrary arguments to the instance's private adb executable. Adb is not published to the host network.

The log is `/config/.android/emulator.log`. `"$BOXES_ROOT/box" exec android -- cat /config/.android/emulator.log` reads it. The [root README](../README.md) covers authentication, workspace mounts, persistence, and removal. The [Android skill](SKILL.md) adds agent-specific rules.
