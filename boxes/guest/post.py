#!/usr/bin/env python3
"""Turn a finished recording into an annotated video and a frame index.

Run inside the box, which has the recording, ffmpeg, and ffprobe. It writes:

  screen.mp4            the segments joined, if the recording was paused
  screen-annotated.mp4  the same video with clicks, drags, scrolls, and typing
  frames/NNNN.jpg       a frame just before and just after each click, plus one
                        for each scene change and each idle second
  index.json            each frame's time in the recording and why it was kept

The recorded video holds only the parts of the session that were recorded, so an
event's place in it is its offset into the segment that covers it.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

RING = "m 0 -16 b 8 -16 16 -8 16 0 b 16 8 8 16 0 16 b -8 16 -16 8 -16 0 b -16 -8 -8 -16 0 -16"
TRAIL = "m 0 0 l {dx} {dy}"
BUTTON_COLOURS = {"right": "&H40B4FF&", "middle": "&H70DCFF&", "left": "&HFFFFFF&"}
MODIFIERS = {"Shift", "Ctrl", "Alt", "Meta", "AltGr"}
ARROWS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
SHOWINFO = re.compile(r"n:\s*\d+.*?pts_time:([0-9.]+)")
BRIGHTNESS = re.compile(r"lavfi\.signalstats\.YAVG=([0-9.]+)")


def run(arguments):
    result = subprocess.run(arguments, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError(f"{arguments[0]} failed with exit code {result.returncode}.\n{result.stdout or ''}")
    return result.stdout or ""


def duration(path):
    text = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)])
    value = float(text.strip())
    if value <= 0:
        raise RuntimeError(f"{path} has no duration.")
    return value


def has_frames(path):
    text = run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_frames",
                "-show_entries", "stream=nb_read_frames", "-of", "default=nw=1:nk=1", str(path)])
    return int(text.strip() or 0) > 0


def mean_brightness(path):
    text = run(["ffmpeg", "-v", "info", "-i", str(path), "-frames:v", "1", "-vf", "signalstats,metadata=print",
                "-f", "null", "-"])
    match = BRIGHTNESS.search(text)
    return float(match.group(1)) if match else None


def load_events(path):
    events = []
    if not path.exists():
        return events
    for line in path.read_text(errors="replace").splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict) and "time" in value and value.get("event") not in {"started", "stopped"}:
            events.append(value)
    return events


def timestamp(second):
    second = max(second, 0.0)
    hours, rest = divmod(second, 3600)
    minutes, rest = divmod(rest, 60)
    return f"{int(hours)}:{int(minutes):02d}:{rest:05.2f}"


def clean(text):
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\r", " ").replace("\n", " ")


def key_caption(event):
    name = event.get("name", "")
    if len(name) == 1:
        name = name.upper()
    return "+".join((event.get("modifiers") or []) + [name])


class Timeline:
    """Map wall-clock moments onto the joined recording."""

    def __init__(self, starts, lengths, lead=0.35, tail=2.5):
        self.spans, self.total = [], 0.0
        for start, length in zip(starts, lengths):
            self.spans.append((start - 1.0, start + length, self.total, length))
            self.total += length
        self.lead = lead
        self.tail = tail

    def at(self, moment, duration=None):
        """The moment in the recording, or None when it falls outside it."""
        for opened, closed, begin, length in reversed(self.spans):
            if opened <= moment <= closed:
                place = begin + max(moment - (closed - length), 0.0)
                if duration and place + duration > self.total:
                    return None
                return place
        return None

    def lead_in(self, moment):
        return self.at(moment - self.lead) or 0.0


def subtitles(events, timeline):
    lines = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1920", "PlayResY: 1080", "WrapStyle: 2", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
             "MarginL, MarginR, MarginV, Encoding",
             "Style: Ring,Arial,24,&H00FFFFFF,&H000000FF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,2,0,7,0,0,0,1",
             "Style: Caption,Arial,26,&H00FFFFFF,&H000000FF,&HB0000000,&HB0000000,0,0,0,0,100,100,0,0,3,1,0,2,40,40,40,1",
             "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    events = sorted(events, key=lambda event: event["time"])
    for index, event in enumerate(events):
        kind = event.get("event")
        if kind == "click" and event.get("action") == "down":
            lines.extend(ring_lines(event, timeline))
        elif kind == "click" and event.get("action") == "up" and event.get("origin"):
            x, y = event["origin"]
            dx, dy = event["x"] - x, event["y"] - y
            if abs(dx) > 8 or abs(dy) > 8:
                place = timeline.at(event["time"])
                if place is None:
                    continue
                shape = f"{{\\an7\\pos({x},{y})\\p1}}" + TRAIL.format(dx=dx, dy=dy)
                lines.append(f"Dialogue: 9,{timestamp(place)},{timestamp(place + 2.5)},Ring,,0,0,0,,{shape}")
                lines.extend(ring_lines({"x": event["x"], "y": event["y"], "button": "left", "time": event["time"]},
                                        timeline))
        elif kind == "scroll":
            place = timeline.at(event["time"], 1.2)
            if place is None:
                continue
            caption = f"scroll {event.get('direction')} x{event.get('amount', 1)}"
            lines.append(caption_line(place, 1.2, caption, event["x"], event["y"], event.get("direction")))
        elif kind == "text" and event.get("text"):
            place = timeline.at(event["time"], 1.6)
            if place is None:
                continue
            lines.append(caption_line(place, 1.6, event["text"], None, None))
        elif kind == "key" and event.get("action") == "down" and len(event.get("name", "")) > 1:
            if event.get("name") in {"Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
                                     "Super_L", "Super_R", "Meta_L", "Meta_R", "Caps_Lock"}:
                continue
            place = timeline.at(event["time"], 1.4)
            if place is None:
                continue
            lines.append(caption_line(place, 1.4, key_caption(event), None, None))
        elif kind == "move" and index % 5 == 0:
            place = timeline.at(event["time"], 0.3)
            if place is None:
                continue
            held = "  ".join(name for name in (event.get("modifiers") or []) if name in MODIFIERS)
            lines.append(caption_line(place, 0.3, f"{event['x']},{event['y']}  {held}".strip(), None, None))
    return "\n".join(lines) + "\n"


def ring_lines(event, timeline):
    place = timeline.at(event["time"], 1.0)
    if place is None:
        return []
    colour = BUTTON_COLOURS.get(event.get("button"), BUTTON_COLOURS["left"])
    x, y = event["x"], event["y"]
    outer = (f"{{\\an7\\pos({x},{y})\\p1\\1c{colour}\\fscx50\\fscy50\\alpha&H20&"
             f"\\t(0,900,\\fscx215,\\fscy215,\\alpha&HFF&)}}{RING}")
    inner = f"{{\\an7\\pos({x},{y})\\p1\\1c{colour}\\alpha&H40&}}{RING}"
    return [f"Dialogue: 10,{timestamp(place)},{timestamp(place + 1.0)},Ring,,0,0,0,,{outer}",
            f"Dialogue: 10,{timestamp(place)},{timestamp(place + 0.8)},Ring,,0,0,0,,{inner}"]


def caption_line(place, life, caption, x, y, arrow=None):
    if x is None:
        body = f"{{\\an2}}{clean(caption)}"
    else:
        body = f"{{\\an2\\pos({x},{max(y - 30, 40)})}}{clean(caption)}"
        if arrow in ARROWS:
            body += " " + {"up": "▲", "down": "▼", "left": "◀", "right": "▶"}[arrow]
    return f"Dialogue: 5,{timestamp(place)},{timestamp(place + life)},Caption,,0,0,0,,{body}"


def extract(video, at, destination):
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{max(at, 0):.3f}", "-i", str(video), "-frames:v", "1",
         "-q:v", "3", str(destination)])


def keyframes(video, events, timeline, total, scene, minimum):
    """Pick the moments worth reading later: around each click, scene changes, and idle seconds."""
    chosen = []

    def keep(moment):
        moment = round(max(moment, 0.0), 3)
        if moment > total - 0.05 or any(abs(moment - other) < 0.2 for other in chosen):
            return
        chosen.append(moment)

    for event in events:
        if event.get("event") == "click":
            place = timeline.at(event["time"]) or 0.0
            keep(place - 0.35)
            keep(place)
    detection = run(["ffmpeg", "-v", "info", "-i", str(video),
                     "-vf", f"select=gt(scene\\,{scene}),showinfo", "-vsync", "vfr", "-f", "null", "-"])
    for match in SHOWINFO.finditer(detection):
        keep(float(match.group(1)))
    second = 1.0
    while len(chosen) < minimum and second < total:
        keep(second)
        second += 1.0
    return sorted(chosen)


def main():
    parser = argparse.ArgumentParser(description="Render a recording's annotations and frame index.")
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--events", required=True, type=Path)
    parser.add_argument("--recording", required=True, type=Path, help="The recording state written by the host")
    parser.add_argument("--lead", type=float, default=0.35)
    parser.add_argument("--scene", type=float, default=0.12)
    parser.add_argument("--minimum-frames", type=int, default=12)
    arguments = parser.parse_args()

    directory = arguments.directory
    state = json.loads(arguments.recording.read_text())
    segments = [directory / f"segment-{item['segment']:02d}.mp4" for item in state["segments"]]
    starts = [float(item["start"]) for item in state["segments"]]
    missing = [segment for segment in segments if not segment.exists()]
    if missing:
        raise RuntimeError("Missing recorded segments: " + ", ".join(str(segment) for segment in missing))
    lengths = [duration(segment) for segment in segments]
    joined = directory / "screen.mp4"
    if len(segments) == 1:
        shutil.copyfile(segments[0], joined)
    else:
        listing = directory / "segments.txt"
        listing.write_text("".join(f"file '{segment}'\n" for segment in segments))
        run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(listing), "-c", "copy", str(joined)])
    if not has_frames(joined):
        raise RuntimeError("The recording contains no video frames.")

    timeline = Timeline(starts, lengths, arguments.lead)
    events = load_events(arguments.events)
    pressed = any(event.get("event") == "click" for event in events)
    brightness = mean_brightness(joined)
    if pressed and brightness is not None and brightness < 8:
        raise RuntimeError("The recording is black while input was logged. The capture path is wrong for this desktop.")

    highlights = directory / "highlights.ass"
    highlights.write_text(subtitles(events, timeline))
    annotated = directory / "screen-annotated.mp4"
    escaped = str(highlights).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    run(["ffmpeg", "-v", "error", "-y", "-i", str(joined), "-vf", f"subtitles='{escaped}'", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "22", str(annotated)])

    moments = keyframes(joined, events, timeline, timeline.total, arguments.scene, arguments.minimum_frames)
    pictures = directory / "frames"
    pictures.mkdir(exist_ok=True)
    for index, moment in enumerate(moments):
        extract(joined, moment, pictures / f"{index:04d}.jpg")
    index_file = directory / "index.json"
    index_file.write_text(json.dumps({"video": str(joined), "annotated": str(annotated),
                                      "duration": round(timeline.total, 3), "frames_directory": str(pictures),
                                      "brightness": brightness,
                                      "frames": [{"file": f"{index:04d}.jpg", "time": moment}
                                                 for index, moment in enumerate(moments)],
                                      "events": len(events)}, indent=2) + "\n")
    print(index_file)


if __name__ == "__main__":
    sys.exit(main())
