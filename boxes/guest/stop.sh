#!/bin/sh
# Stop one recording segment inside the box.
#
# Stopping the recorder with SIGINT rather than SIGTERM lets wf-recorder finish
# writing the MP4. The tap is stopped first, so its final typed-text run is
# flushed to the log before the recorder closes the last frame.
set -eu

segment=''
overlay='0'
directory=''
while [ $# -gt 0 ]; do
    case "$1" in
        --segment) segment=$2; shift 2 ;;
        --overlay) overlay='1'; shift ;;
        --directory) directory=$2; shift 2 ;;
        *) echo "stop: unknown option $1" >&2; exit 2 ;;
    esac
done
[ -n "$segment" ] || { echo "stop: --segment is required" >&2; exit 2; }
[ -n "$directory" ] || { echo "stop: --directory is required" >&2; exit 2; }

pid=$directory/pids

kill_it() {
    name=$1
    signal=$2
    [ -s "$pid/$name" ] || return 0
    process=$(cat "$pid/$name")
    if kill -0 "$process" 2>/dev/null; then
        kill "-$signal" "$process" 2>/dev/null || true
        waited=0
        while kill -0 "$process" 2>/dev/null && [ "$waited" -lt 200 ]; do
            sleep 0.1
            waited=$((waited + 1))
        done
    fi
    rm -f "$pid/$name"
}

kill_it tap TERM
if [ "$overlay" = '1' ]; then
    kill_it overlay TERM
fi
kill_it recorder INT

file=$(printf '%s/segment-%02d.mp4' "$directory" "$segment")
if [ -s "$file" ]; then
    echo "$file"
else
    echo "stop: the recorder produced no $file" >&2
    exit 4
fi
