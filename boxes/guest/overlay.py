#!/usr/bin/env python3
"""Draw a click, drag, scroll, and typing overlay on the box desktop.

The window sits on the layer-shell overlay layer: always above the applications,
transparent, and with an empty input region so the pointer passes through to
whatever is underneath. It reads the events the tap logs, so a click shows as a
ring where it landed, a drag leaves a trail, and typing collects into a caption
along the bottom of the screen.

Only recording needs this. Run it under the desktop account with the desktop's
own Python, which carries the GTK bindings; do not run it with a second Python.
"""

import argparse
import json
import os
import time

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import GLib, Gtk, GtkLayerShell  # noqa: E402

gi.require_foreign("cairo")  # GTK's draw signal hands the callback a cairo context

MODIFIER_NAMES = {"Shift", "Ctrl", "Alt", "Meta", "AltGr"}
CLICK_LIFE = 1.1
SCROLL_LIFE = 0.9
TRAIL_LIFE = 0.7
CAPTION_LIFE = 3.5
BUTTON_COLOURS = {"left": (1.0, 1.0, 1.0), "middle": (0.55, 0.85, 1.0), "right": (1.0, 0.72, 0.45)}


class Canvas(Gtk.Window):
    def __init__(self, font):
        super().__init__(type=Gtk.WindowType.TOPLEVEL)
        GtkLayerShell.init_for_window(self)
        GtkLayerShell.set_layer(self, GtkLayerShell.Layer.OVERLAY)
        for edge in (GtkLayerShell.Edge.TOP, GtkLayerShell.Edge.BOTTOM,
                     GtkLayerShell.Edge.LEFT, GtkLayerShell.Edge.RIGHT):
            GtkLayerShell.set_anchor(self, edge, True)
        GtkLayerShell.set_keyboard_mode(self, GtkLayerShell.KeyboardMode.NONE)
        GtkLayerShell.set_namespace(self, "boxes-overlay")
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual:
            self.set_visual(visual)
        self.set_app_paintable(True)
        self.set_decorated(False)
        self.set_accept_focus(False)
        self.set_can_focus(False)
        self.set_skip_taskbar_hint(True)
        self.font = font
        self.clicks = []
        self.scrolls = []
        self.trail = []
        self.held = []
        self.caption = None
        self.connect("draw", self.draw)
        self.connect("realize", self.input_region)
        GLib.timeout_add(40, self.tick)

    def input_region(self, _widget=None):
        """Pass every click through to the desktop underneath."""
        window = self.get_window()
        if window:
            window.set_pass_through(True)

    def tick(self):
        moment = time.monotonic()
        self.clicks = [item for item in self.clicks if moment - item["at"] < CLICK_LIFE]
        self.scrolls = [item for item in self.scrolls if moment - item["at"] < SCROLL_LIFE]
        self.trail = [item for item in self.trail if moment - item["at"] < TRAIL_LIFE]
        if self.caption and moment - self.caption["at"] > CAPTION_LIFE:
            self.caption = None
        self.queue_draw()
        return True

    def draw(self, _widget, context):
        context.set_line_cap(1)
        for item in self.trail:
            age = (time.monotonic() - item["at"]) / TRAIL_LIFE
            context.set_source_rgba(1.0, 0.85, 0.2, 0.55 * (1 - age))
            context.set_line_width(4)
            context.move_to(*item["from"])
            context.line_to(*item["to"])
            context.stroke()
        for item in self.scrolls:
            age = (time.monotonic() - item["at"]) / SCROLL_LIFE
            context.set_source_rgba(0.4, 0.9, 1.0, 0.8 * (1 - age))
            context.set_line_width(2)
            for step in range(item["amount"]):
                offset = step * 16
                if item["direction"] in {"up", "down"}:
                    sign = 1 if item["direction"] == "up" else -1
                    context.move_to(item["x"] - 12, item["y"] + offset * sign)
                    context.line_to(item["x"] + 12, item["y"] + offset * sign)
                    context.line_to(item["x"], item["y"] + offset * sign + 10 * sign)
                    context.close_path()
                else:
                    sign = 1 if item["direction"] == "right" else -1
                    context.move_to(item["x"] + offset * sign, item["y"] - 12)
                    context.line_to(item["x"] + offset * sign, item["y"] + 12)
                    context.line_to(item["x"] + offset * sign + 10 * sign, item["y"])
                    context.close_path()
            context.fill()
        for item in self.clicks:
            age = (time.monotonic() - item["at"]) / CLICK_LIFE
            red, green, blue = BUTTON_COLOURS.get(item["button"], (1.0, 1.0, 1.0))
            context.set_source_rgba(red, green, blue, 0.9 * (1 - age))
            context.set_line_width(3)
            context.arc(item["x"], item["y"], 10 + 26 * age, 0, 6.283185)
            context.stroke()
            context.set_source_rgba(red, green, blue, 0.5 * (1 - age))
            context.arc(item["x"], item["y"], 3, 0, 6.283185)
            context.fill()
        if self.caption:
            age = (time.monotonic() - self.caption["at"]) / CAPTION_LIFE
            text = self.caption["text"]
            context.select_font_face(self.font, 0, 1)
            context.set_font_size(22)
            extent = context.text_extents(text)
            width = min(max(extent.width + 28, 120), self.get_allocated_width() - 40)
            height = 42
            left = (self.get_allocated_width() - width) / 2
            bottom = self.get_allocated_height() - 64
            context.set_source_rgba(0.05, 0.05, 0.08, 0.72 * (1 - age))
            rounded(context, left, bottom, width, height, 10)
            context.fill()
            context.set_source_rgba(1.0, 1.0, 1.0, 0.95 * (1 - age))
            context.move_to(left + 14, bottom + 28)
            clipped = text
            while clipped and context.text_extents(clipped).width > width - 28:
                clipped = clipped[:-1]
            context.show_text(clipped)
        return False

    def event(self, value):
        kind = value.get("event")
        moment = time.monotonic()
        if kind == "click" and value.get("action") == "down":
            self.clicks.append({"at": moment, "x": value["x"], "y": value["y"], "button": value.get("button", "left")})
        elif kind == "click" and value.get("action") == "up" and value.get("origin"):
            self.trail.append({"at": moment, "from": value["origin"], "to": [value["x"], value["y"]]})
        elif kind == "scroll":
            self.scrolls.append({"at": moment, "x": value["x"], "y": value["y"],
                                 "direction": value.get("direction", "down"), "amount": min(value.get("amount", 1), 4)})
        elif kind == "text":
            self.caption = {"at": moment, "text": value.get("text", "")}
        elif kind == "key" and value.get("action") == "down":
            if value.get("name") not in self.held:
                self.held.append(value.get("name"))
            self.caption = {"at": moment, "text": caption(value)}
        elif kind == "key" and value.get("action") == "up":
            if value.get("name") in self.held:
                self.held.remove(value.get("name"))
        elif kind == "move":
            self.coordinates(value)
        self.queue_draw()

    def coordinates(self, value):
        """Show where the pointer is, with any held key, as a small readout."""
        held = "  ".join(name for name in self.held if name in MODIFIER_NAMES)
        self.caption = {"at": time.monotonic(), "text": f"{value['x']},{value['y']}  {held}".strip(), "pointer": True}


def rounded(context, left, top, width, height, radius):
    context.new_sub_path()
    context.arc(left + width - radius, top + radius, radius, -1.5708, 0)
    context.arc(left + width - radius, top + height - radius, radius, 0, 1.5708)
    context.arc(left + radius, top + height - radius, radius, 1.5708, 3.1416)
    context.arc(left + radius, top + radius, radius, 3.1416, 4.7124)
    context.close_path()


def caption(value):
    name = value.get("name", "")
    if len(name) == 1:
        name = name.upper()
    modifiers = value.get("modifiers") or []
    if modifiers:
        return "+".join(modifiers + [name])
    return name


def main():
    parser = argparse.ArgumentParser(description="Show clicks, drags, scrolls, and typing above the box desktop.")
    parser.add_argument("--log", required=True, help="Event log the tap writes")
    parser.add_argument("--font", default="Sans")
    arguments = parser.parse_args()

    log = open(arguments.log, "r", encoding="utf-8", errors="replace")
    log.seek(0, os.SEEK_END)
    window = Canvas(arguments.font)
    window.show_all()

    def poll():
        for line in log.readlines():
            try:
                window.event(json.loads(line))
            except (ValueError, KeyError, TypeError):
                continue
        return True

    GLib.timeout_add(60, poll)
    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
