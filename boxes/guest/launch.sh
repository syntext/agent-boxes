#!/bin/sh
# Start one recording segment inside the box: the screen recorder, the input tap,
# and the optional live overlay.
#
# The host passes the recording directory, the segment number, the frame rate,
# and the interfaces to read, so this script keeps no state of its own. Running it
# again for a segment that is still running leaves that segment alone, which is
# how the host resumes after a pause.
set -eu

segment=''
overlay='0'
fps='15'
directory=''
interfaces=''
while [ $# -gt 0 ]; do
    case "$1" in
        --segment) segment=$2; shift 2 ;;
        --overlay) overlay='1'; shift ;;
        --fps) fps=$2; shift 2 ;;
        --directory) directory=$2; shift 2 ;;
        --interface) interfaces="$interfaces --interface $2"; shift 2 ;;
        *) echo "launch: unknown option $1" >&2; exit 2 ;;
    esac
done
[ -n "$segment" ] || { echo "launch: --segment is required" >&2; exit 2; }
[ -n "$directory" ] || { echo "launch: --directory is required" >&2; exit 2; }

root=/config/.boxes
guest=$root/guest
account=abc
log=$directory/events.jsonl
pid=$directory/pids
mkdir -p "$root" "$pid"
: >> "$log"
chmod 777 "$pid" 2>/dev/null || true
chown -R "$account:$account" "$directory" 2>/dev/null || true

# The overlay shows what the tap logs, so both read one file: the overlay tails
# it for new events and prints nothing back.
running() {
    [ -s "$pid/$1" ] && kill -0 "$(cat "$pid/$1")" 2>/dev/null
}

desktop=$root/desktop
cat > "$desktop" <<SCRIPT
#!/bin/sh
# Run a command as the desktop account. The tap opens its capture socket as root
# and drops privileges itself, so only the other tools need this.
exec setpriv --reuid $account --regid $account --init-groups "\$@"
SCRIPT
chmod 755 "$desktop"

start() {
    if running "$1"; then
        return 0
    fi
    name=$1
    shift
    nohup setsid "$@" >>"$root/tool.log" 2>&1 &
    echo $! > "$pid/$name"
}

# The tap's events are the recording's log; its diagnostics still belong with the
# other tools.
start_events() {
    if running "$1"; then
        return 0
    fi
    name=$1
    shift
    nohup setsid "$@" >>"$log" 2>>"$root/tool.log" &
    echo $! > "$pid/$name"
}

export XDG_RUNTIME_DIR=${XDG_RUNTIME_DIR:-/config/.XDG}
export WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-wayland-0}
export DISPLAY=${DISPLAY:-:0}

file=$(printf '%s/segment-%02d.mp4' "$directory" "$segment")
if ! running recorder; then
    command -v wf-recorder >/dev/null || { echo "launch: wf-recorder is not installed; recreate the box to install it" >&2; exit 3; }
    rm -f "$file"
    start recorder "$desktop" wf-recorder -f "$file" -c libx264 -p preset=ultrafast -r "$fps"
fi

python=$(command -v python3)
start_events tap "$python" "$guest/tap.py" --drop-to "$account" $interfaces
if [ "$overlay" = '1' ]; then
    overlay_python=$python
    for candidate in /usr/bin/python3 "$python"; do
        if [ -x "$candidate" ] && "$candidate" -c 'import gi, cairo' >/dev/null 2>&1; then
            overlay_python=$candidate
            break
        fi
    done
    start overlay "$desktop" "$overlay_python" "$guest/overlay.py" --log "$log"
fi

echo "$file"
