#!/usr/bin/env python3
"""Read Selkies input from the box's websocket traffic and log it as events.

The desktop websocket protocol is a small comma-separated text one. A viewer
sends:

    kd,<keysym>                    key down
    ku,<keysym>                    key up
    m,<x>,<y>,<buttons>,<wheel>    pointer position, buttons, and wheel
    m2,<dx>,<dy>,...               pointer motion relative to the last position

The button field is a bit mask: bit 0 to 2 are the left, middle, and right
buttons, and bits 3, 4, 6, and 7 are the four wheel directions whose repeat
count is the last field. A count of zero makes those bits the back and forward
buttons instead.

Messages travel unencrypted over the box's loopback from nginx to Selkies, so a
passive raw socket reads them without changing or replacing any upstream
service. That socket needs root and CAP_NET_RAW, which boxes already grants; the
process drops to the desktop account as soon as it is open.

Every event is one JSON object per line on stdout, which the caller appends to
the recording's log. Typed text is logged in full, so a person who is about to
enter a secret pauses the recording instead. Diagnostics, including a periodic
capture summary, go to stderr.
"""

import argparse
import json
import os
import signal
import socket
import struct
import sys
import time

ETH_P_ALL = 3
ETH_P_IP = 0x0800
IPPROTO_TCP = 6
VLAN = 0x8100
HTTP_WEBSOCKET = 8082
FRAME_LIMIT = 1 << 20
TEXT_GAP = 0.8
MOVE_GAP = 0.004
MOVE_MINIMUM = 3

BUTTONS = {1: "left", 2: "middle", 4: "right"}
SCROLL_BITS = {8: "up", 16: "down", 64: "left", 128: "right"}
NAVIGATE_BITS = {8: "back", 16: "forward"}
MODIFIERS = {"Shift_L": "Shift", "Shift_R": "Shift", "Control_L": "Ctrl", "Control_R": "Ctrl",
             "Alt_L": "Alt", "Alt_R": "Alt", "Meta_L": "Meta", "Super_L": "Meta", "Super_R": "Meta",
             "ISO_Level3_Shift": "AltGr", "Caps_Lock": "Caps"}

NAMES = {
    0xff08: "BackSpace", 0xff09: "Tab", 0xff0d: "Return", 0xff1b: "Escape", 0xffff: "Delete",
    0xff50: "Home", 0xff51: "Left", 0xff52: "Up", 0xff53: "Right", 0xff54: "Down",
    0xff55: "Page_Up", 0xff56: "Page_Down", 0xff57: "End", 0xff63: "Insert",
    0xffe1: "Shift_L", 0xffe2: "Shift_R", 0xffe3: "Control_L", 0xffe4: "Control_R",
    0xffe7: "Meta_L", 0xffe8: "Meta_R", 0xffe9: "Alt_L", 0xffea: "Alt_R",
    0xffeb: "Super_L", 0xffec: "Super_R", 0xfe03: "ISO_Level3_Shift",
    0xffe5: "Caps_Lock", 0xff7f: "Num_Lock", 0xff14: "Scroll_Lock",
    0xff13: "Pause", 0xff61: "Print", 0xff6b: "Cancel", 0xff0b: "Clear",
    0xff20: "Multi_key",
}
for index in range(1, 25):
    NAMES[0xffbe + index - 1] = f"F{index}"
for index, name in enumerate(("KP_0", "KP_1", "KP_2", "KP_3", "KP_4", "KP_5", "KP_6", "KP_7", "KP_8", "KP_9"), 0xffb0):
    NAMES[index] = name


def keysym_name(keysym):
    if keysym in NAMES:
        return NAMES[keysym]
    if 0x20 <= keysym <= 0x7e:
        return chr(keysym)
    if keysym >= 0x1000000:
        return f"Unicode_{keysym - 0x1000000:04X}"
    return f"0x{keysym:x}"


def printable(keysym):
    return 0x20 <= keysym <= 0x7e


def now():
    return time.time()


def scroll_count(value):
    """A wheel repeat count. The desktop protocol sends 1 to 64, or 0 for none."""
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 0
    return value if 0 < value <= 64 else 0


class Translator:
    """Turn the raw key and pointer messages into named events.

    A pointer message carries the pressed buttons as a bit mask. Bits 0 to 2 are
    the left, middle, and right buttons; bits 3, 4, 6, and 7 are the four wheel
    directions, whose repeat count arrives as a separate field. With a count of
    zero those same bits mean the browser's back and forward buttons.
    """

    def __init__(self, publish):
        self.publish = publish
        self.buttons = set()
        self.specials = set()
        self.origin = None
        self.held = []
        self.text = []
        self.last_text = None
        self.last_move = None
        self.last_pointer = None

    def flush(self, reason):
        if self.text:
            self.publish("text", text="".join(self.text), reason=reason)
            self.text = []
        self.last_text = None

    def key(self, keysym, down):
        name = keysym_name(keysym)
        if down:
            changed = bool(printable(keysym)) != bool(self.text)
            if changed or (self.last_text and now() - self.last_text > TEXT_GAP):
                self.flush("interrupted")
            if name not in self.held:
                self.held.append(name)
            self.publish("key", action="down", name=name, keysym=keysym, modifiers=list(self.held[:-1]))
        else:
            if printable(keysym):
                self.text.append(chr(keysym))
                self.last_text = now()
                self.publish("text", text="".join(self.text), partial=True, reason="typing")
            if name in self.held:
                self.held.remove(name)
            self.publish("key", action="up", name=name, keysym=keysym)

    def pointer(self, x, y, mask, scroll, relative=False):
        if relative:
            if not self.last_pointer:
                return
            x, y = self.last_pointer[0] + x, self.last_pointer[1] + y
        self.last_pointer = (x, y)
        specials = {bit for bit in SCROLL_BITS if mask & bit}
        fresh = specials - self.specials
        self.specials = specials
        pressed = {bit for bit in BUTTONS if mask & bit}
        changed = bool(pressed - self.buttons) or bool(self.buttons - pressed) or bool(fresh)
        if pressed - self.buttons:
            button = sorted(pressed - self.buttons)[0]
            self.flush("clicked")
            self.origin = (x, y)
            self.publish("click", action="down", x=x, y=y, button=BUTTONS[button])
        elif self.buttons - pressed:
            button = sorted(self.buttons - pressed)[0]
            self.publish("click", action="up", x=x, y=y, button=BUTTONS[button], origin=self.origin)
            self.origin = None
        self.buttons = pressed
        for bit in sorted(fresh):
            if scroll:
                self.flush("scrolled")
                self.publish("scroll", x=x, y=y, direction=SCROLL_BITS[bit], amount=scroll)
            elif bit in NAVIGATE_BITS:
                self.flush("navigated")
                self.publish("navigate", x=x, y=y, direction=NAVIGATE_BITS[bit])
        if not changed and not specials and not pressed:
            self.move(x, y)

    def move(self, x, y):
        moment = now()
        if self.last_move and moment - self.last_move[0] < MOVE_GAP:
            if abs(x - self.last_move[1]) < MOVE_MINIMUM and abs(y - self.last_move[2]) < MOVE_MINIMUM:
                return
        self.last_move = (moment, x, y)
        self.publish("move", x=x, y=y)


INPUT_PREFIXES = ("m,", "m2,", "kd,", "ku,", "kh,", "kr,")
RESYNC_SECONDS = 1.2
IDLE_SECONDS = 300.0


def messages(buffer):
    """Split a websocket byte buffer into text messages and the remaining bytes.

    The third value says the bytes could not be a websocket frame, which happens
    after a lost packet; the caller then rebuilds the stream from the next
    plausible frame boundary. Messages already read are returned either way.
    """
    found = []
    while True:
        if len(buffer) < 2:
            return found, buffer, False
        opcode = buffer[0] & 0x0f
        masked = bool(buffer[1] & 0x80)
        length = buffer[1] & 0x7f
        offset = 2
        if opcode not in {0, 1, 2, 8, 9, 10}:
            return found, buffer, True
        if length == 126:
            if len(buffer) < 4:
                return found, buffer, False
            length = struct.unpack(">H", buffer[2:4])[0]
            offset = 4
        elif length == 127:
            if len(buffer) < 10:
                return found, buffer, False
            length = struct.unpack(">Q", buffer[2:10])[0]
            offset = 10
        if length > FRAME_LIMIT:
            return found, buffer, True
        if masked:
            if len(buffer) < offset + 4:
                return found, buffer, False
            key = buffer[offset:offset + 4]
            offset += 4
        if len(buffer) < offset + length:
            return found, buffer, False
        body = buffer[offset:offset + length]
        if masked:
            body = bytes(byte ^ key[index % 4] for index, byte in enumerate(body))
        if opcode == 1:
            text = body.decode("utf-8", "replace")
            if not text.startswith(INPUT_PREFIXES):
                return found, buffer, True
            found.append(text)
        buffer = buffer[offset + length:]


def resync(buffer):
    """Find the next plausible frame boundary after a lost packet.

    A client frame is masked, so a candidate is only accepted once its payload
    unmasks to a message the desktop protocol sends.
    """
    for start in range(len(buffer) - 6):
        if buffer[start] & 0x0f != 1 or not buffer[start + 1] & 0x80:
            continue
        length = buffer[start + 1] & 0x7f
        if length == 0 or length > 126 or length < 2:
            continue
        if len(buffer) < start + 6 + length:
            break
        key = buffer[start + 2:start + 6]
        body = buffer[start + 6:start + 6 + length]
        text = bytes(byte ^ key[index % 4] for index, byte in enumerate(body)).decode("utf-8", "replace")
        if text.startswith(INPUT_PREFIXES):
            return buffer[start:]
    return buffer[-8:] if len(buffer) > 8 else b""


class Sniffer:
    """Reassemble the box's loopback websocket traffic and decode input messages."""

    def __init__(self, interfaces, emit, port=HTTP_WEBSOCKET):
        self.port = port
        self.emit = emit
        self.translator = Translator(lambda event, **fields: emit(event, **fields))
        self.connections = {}
        self.sockets = []
        self.interfaces = interfaces
        self.messages = 0
        self.packets = 0
        self.bytes = 0
        self.last_message = 0.0
        self.stats = 0.0

    def open(self):
        for name in self.interfaces:
            try:
                sock = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.ntohs(ETH_P_ALL))
                sock.bind((name, 0))
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 8 << 20)
                self.sockets.append((name, sock))
            except OSError as error:
                print(f"tap: cannot capture on {name}: {error}", file=sys.stderr)
        return bool(self.sockets)

    def handle(self, message):
        self.messages += 1
        self.last_message = time.monotonic()
        fields = message.split(" ", 1)[0].split(",")
        kind = fields[0]
        if kind in {"kd", "ku"}:
            if len(fields) < 2:
                return
            try:
                self.translator.key(int(fields[1]), kind == "kd")
            except ValueError:
                return
        elif kind in {"m", "m2"}:
            if len(fields) < 5:
                return
            try:
                x, y, mask, scroll = (int(value) for value in fields[1:5])
            except ValueError:
                return
            self.translator.pointer(x, y, mask, scroll_count(scroll), relative=kind == "m2")

    def deliver(self, connection_id, sequence, data):
        """Place in-order bytes, drain any that waited for them, then decode.

        A packet the socket buffer dropped would otherwise stall the connection
        for good, because every later segment waits behind the hole. Instead the
        hole is abandoned after a moment and the stream resumes from the next
        frame boundary that looks like real input.
        """
        moment = time.monotonic()
        held = self.connections.get(connection_id)
        if held is None:
            held = self.connections[connection_id] = {"next": sequence, "buffer": b"", "pending": {},
                                                      "progress": moment}
        if sequence < held["next"]:
            if sequence + len(data) <= held["next"]:
                return
            data = data[held["next"] - sequence:]
            sequence = held["next"]
        if sequence > held["next"]:
            held["pending"][sequence] = data
            if moment - held["progress"] > RESYNC_SECONDS:
                self.recover(connection_id, held, moment)
            return
        held["buffer"] += data
        held["next"] = sequence + len(data)
        held["progress"] = moment
        while held["next"] in held["pending"]:
            chunk = held["pending"].pop(held["next"])
            held["buffer"] += chunk
            held["next"] += len(chunk)
        self.decode(held)

    def recover(self, connection_id, held, moment):
        """Skip the hole and continue from the earliest bytes that did arrive."""
        if not held["pending"]:
            return
        sequence = min(held["pending"])
        data = held["pending"].pop(sequence)
        held["buffer"] = b""
        held["next"] = sequence
        held["progress"] = moment
        self.deliver(connection_id, sequence, data)

    def decode(self, held):
        if len(held["buffer"]) > 8 << 20:
            held["buffer"] = b""
            return
        while True:
            found, rest, desynced = messages(held["buffer"])
            for text in found:
                self.handle(text)
            if not desynced:
                held["buffer"] = rest
                return
            recovered = resync(rest)
            if recovered == rest:
                held["buffer"] = rest
                return
            held["buffer"] = recovered

    def packet(self, packet):
        self.packets += 1
        if len(packet) < 34:
            return
        ethertype, offset = struct.unpack(">H", packet[12:14])[0], 14
        if ethertype == VLAN:
            if len(packet) < 38:
                return
            ethertype, offset = struct.unpack(">H", packet[16:18])[0], 18
        if ethertype != ETH_P_IP:
            return
        header = packet[offset:]
        if len(header) < 40 or header[0] >> 4 != 4:
            return
        header_length = (header[0] & 0x0f) * 4
        protocol = header[9]
        if protocol != IPPROTO_TCP or len(header) < header_length + 20:
            return
        source, destination = header[12:16], header[16:20]
        tcp = header[header_length:]
        source_port, destination_port = struct.unpack(">HH", tcp[0:4])
        if self.port not in (source_port, destination_port):
            return
        data_offset = (tcp[12] >> 4) * 4
        if data_offset < 20:
            return
        body = tcp[data_offset:]
        if not body:
            return
        self.bytes += len(body)
        connection = (source, source_port, destination, destination_port)
        self.deliver(connection, struct.unpack(">I", tcp[4:8])[0], body)

    def run(self, seconds=None, stats=0.0, stopping=None):
        deadline = time.monotonic() + seconds if seconds else None
        for _, sock in self.sockets:
            sock.settimeout(0.25)
        while True:
            for _, sock in self.sockets:
                try:
                    packet = sock.recv(65535)
                except (socket.timeout, OSError):
                    pass
                else:
                    self.packet(packet)
            moment = time.monotonic()
            for connection_id, held in list(self.connections.items()):
                if held["pending"] and moment - held["progress"] > RESYNC_SECONDS:
                    self.recover(connection_id, held, moment)
                elif moment - held["progress"] > IDLE_SECONDS:
                    self.connections.pop(connection_id, None)
            if stats and moment - self.stats > stats:
                self.stats = moment
                print(f"tap: {self.packets} packets, {self.bytes} bytes, {self.messages} input messages, "
                      f"{len(self.connections)} connections", file=sys.stderr, flush=True)
            if stopping and stopping["asked"]:
                return
            if deadline and moment > deadline:
                return

    def close(self):
        self.translator.flush("stopped")
        for _, sock in self.sockets:
            sock.close()


def install_stop_handlers(stopping):
    def handle(*_arguments):
        stopping["asked"] = True
    signal.signal(signal.SIGTERM, handle)
    signal.signal(signal.SIGINT, handle)


def main():
    parser = argparse.ArgumentParser(description="Log Selkies input events from the box's loopback traffic.")
    parser.add_argument("--interface", action="append", default=[])
    parser.add_argument("--port", type=int, default=HTTP_WEBSOCKET)
    parser.add_argument("--seconds", type=float, default=0.0)
    parser.add_argument("--drop-to", default="abc", help="Account to become once the capture socket is open")
    parser.add_argument("--stats", type=float, default=30.0, help="Seconds between capture summaries on stderr")
    arguments = parser.parse_args()

    def emit(event, **fields):
        print(json.dumps({"time": round(now(), 3), "event": event, **fields}, separators=(",", ":")), flush=True)

    stopping = {"asked": False}
    install_stop_handlers(stopping)
    sniffer = Sniffer(arguments.interface, emit, arguments.port)
    opening = sniffer.open()
    drop_privileges(arguments.drop_to)
    if not opening:
        print("tap: no usable interface; only video will be recorded", file=sys.stderr)
        return 2
    emit("started", interfaces=arguments.interface)
    try:
        sniffer.run(arguments.seconds or None, arguments.stats, stopping)
    except KeyboardInterrupt:
        pass
    finally:
        sniffer.close()
        emit("stopped", messages=sniffer.messages)
    return 0


def drop_privileges(account):
    """Become the desktop account, so logs and frames stay owned by it.

    Opening an `AF_PACKET` socket needs a capability the desktop account does not
    carry. The caller starts this as root for that one call, and the process
    sheds the extra privilege before it writes anything.
    """
    if os.geteuid() != 0 or not account:
        return
    try:
        import pwd
        entry = pwd.getpwnam(account)
    except (ImportError, KeyError):
        return
    os.setgroups([entry.pw_gid])
    os.setgid(entry.pw_gid)
    os.setuid(entry.pw_uid)


if __name__ == "__main__":
    raise SystemExit(main())
