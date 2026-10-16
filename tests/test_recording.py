import importlib.util
import json
import os
from pathlib import Path
import signal
import struct
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

from boxes import cli, recording


def load(name, directory="boxes/guest"):
    path = Path(__file__).resolve().parents[1] / directory / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"guest_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tap = load("tap")
post = load("post")
viewer_input = load("viewer_input", "scripts")


class ViewerInputTests(unittest.TestCase):
    def test_http_uses_the_plain_socket_and_waits_for_the_upgrade(self):
        connection = Mock()
        connection.recv.side_effect = [b"HTTP/1.1 101 Switching", b" Protocols\r\n\r\n"]
        with patch.object(viewer_input.socket, "create_connection", return_value=connection) as create, \
                patch.object(viewer_input.ssl, "SSLContext") as tls:
            self.assertIs(viewer_input.connect("http", 3000, "test-user", "test-password"), connection)
        create.assert_called_once_with(("127.0.0.1", 3000), 10)
        tls.assert_not_called()
        self.assertIn(b"Authorization: Basic dGVzdC11c2VyOnRlc3QtcGFzc3dvcmQ=\r\n", connection.sendall.call_args.args[0])

    def test_https_wraps_the_socket_before_the_upgrade(self):
        plain, encrypted, context = Mock(), Mock(), Mock()
        context.wrap_socket.return_value = encrypted
        encrypted.recv.return_value = b"HTTP/1.1 101 Switching Protocols\r\n\r\n"
        with patch.object(viewer_input.socket, "create_connection", return_value=plain), \
                patch.object(viewer_input.ssl, "SSLContext", return_value=context):
            self.assertIs(viewer_input.connect("https", 3001, "user", "secret"), encrypted)
        context.wrap_socket.assert_called_once_with(plain, server_hostname="127.0.0.1")
        plain.sendall.assert_not_called()
        encrypted.sendall.assert_called_once()

    def test_failed_or_incomplete_upgrade_closes_the_socket(self):
        for response in (b"HTTP/1.1 401 Unauthorized\r\n\r\n", b"HTTP/1.1 200 OK\r\n\r\n", b""):
            connection = Mock()
            connection.recv.return_value = response
            with self.subTest(response=response), \
                    patch.object(viewer_input.socket, "create_connection", return_value=connection):
                with self.assertRaises(RuntimeError):
                    viewer_input.connect("http", 3000, "user", "secret")
                connection.close.assert_called_once()

    def test_main_defaults_to_https_and_reads_credentials_from_stdin(self):
        import io
        with patch.object(viewer_input.sys, "argv", ["viewer_input.py"]), \
                patch.object(viewer_input.sys, "stdin", io.StringIO('{"user":"test","password":"private"}')), \
                patch.object(viewer_input, "connect") as connect, \
                patch.object(viewer_input.time, "sleep"), patch("builtins.print"):
            viewer_input.main()
        connect.assert_called_once_with("https", 3001, "test", "private")


def websocket(payload, opcode=1, mask=b"\x01\x02\x03\x04"):
    body = payload.encode() if isinstance(payload, str) else payload
    masked = bytes(byte ^ mask[index % 4] for index, byte in enumerate(body))
    header = bytes([0x80 | opcode, 0x80 | len(body)])
    return header + mask + masked


def segment(sequence, payload, source_port=40000, destination_port=8082, source=b"\x0a\x00\x00\x05",
            destination=b"\x0a\x00\x00\x02"):
    body = payload.encode() if isinstance(payload, str) else payload
    tcp = struct.pack(">HHIIBBHHH", source_port, destination_port, sequence, 0, 5 << 4, 0x18, 65535, 0, 0)
    total = 20 + len(tcp) + len(body)
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, total, 0, 0x4000, 64, 6, 0, source, destination)
    ethernet = b"\x00" * 12 + struct.pack(">H", 0x0800)
    return ethernet + ip + tcp + body


class TapParsingTests(unittest.TestCase):
    def translate(self, messages):
        events = []
        translator = tap.Translator(lambda event, **fields: events.append({"event": event, **fields}))
        for message in messages:
            fields = message.split(" ", 1)[0].split(",")
            kind = fields[0]
            if kind in {"kd", "ku"}:
                translator.key(int(fields[1]), kind == "kd")
            elif kind in {"m", "m2"}:
                x, y, mask, scroll = (int(value) for value in fields[1:5])
                translator.pointer(x, y, mask, tap.scroll_count(scroll), relative=kind == "m2")
        return events

    def test_click_press_release_and_drag_origin(self):
        events = self.translate(["m,300,400,0,0,1", "m,300,400,1,0,2", "m,360,470,1,0,3", "m,360,470,0,0,4"])
        kinds = [event["event"] for event in events]
        self.assertEqual(kinds, ["move", "click", "click"])
        self.assertEqual(events[1]["action"], "down")
        self.assertEqual(events[1]["button"], "left")
        self.assertEqual(events[2]["action"], "up")
        self.assertEqual(events[2]["origin"], (300, 400))
        self.assertEqual((events[2]["x"], events[2]["y"]), (360, 470))

    def test_right_and_middle_buttons_are_named(self):
        events = self.translate(["m,10,20,4,0,1", "m,10,20,0,0,2", "m,10,20,2,0,3", "m,10,20,0,0,4"])
        pressed = [event["button"] for event in events if event["event"] == "click" and event["action"] == "down"]
        self.assertEqual(pressed, ["right", "middle"])

    def test_each_wheel_bit_becomes_its_own_direction(self):
        events = self.translate(["m,5,6,8,3,1", "m,5,6,16,2,2", "m,5,6,64,1,3", "m,5,6,128,4,4"])
        self.assertEqual([event["direction"] for event in events], ["up", "down", "left", "right"])
        self.assertEqual([event["amount"] for event in events], [3, 2, 1, 4])

    def test_wheel_bits_with_no_count_are_back_and_forward(self):
        events = self.translate(["m,5,6,8,0,1", "m,5,6,16,0,2"])
        self.assertEqual([event["direction"] for event in events], ["back", "forward"])
        self.assertTrue(all(event["event"] == "navigate" for event in events))

    def test_a_scroll_while_the_pointer_moves_does_not_click(self):
        events = self.translate(["m,5,6,8,2,1", "m,20,30,0,0,2"])
        self.assertEqual([event["event"] for event in events], ["scroll", "move"])

    def test_typed_text_collects_and_flushes_on_break(self):
        events = self.translate(["kd,104", "ku,104", "kd,105", "ku,105", "kd,65293", "ku,65293"])
        self.assertEqual([event["event"] for event in events if event["event"] == "text"],
                         ["text", "text", "text"])
        final = [event for event in events if event["event"] == "text"][-1]
        self.assertEqual(final["text"], "hi")
        self.assertNotIn("partial", final)
        self.assertEqual(final["reason"], "interrupted")

    def test_pressed_key_reports_modifiers(self):
        events = self.translate(["kd,65507", "kd,108", "ku,108", "ku,65507"])
        press = next(event for event in events if event["event"] == "key" and event["action"] == "down"
                     and event["name"] == "l")
        self.assertEqual(press["modifiers"], ["Control_L"])

    def test_named_keys_and_unknown_keysyms(self):
        self.assertEqual(tap.keysym_name(0xFF0D), "Return")
        self.assertEqual(tap.keysym_name(ord("A")), "A")
        self.assertEqual(tap.keysym_name(0x1000041), "Unicode_0041")
        self.assertEqual(tap.keysym_name(0xFF51), "Left")

    def test_leave_keys_are_not_typed_text(self):
        events = self.translate(["kd,65307", "ku,65307"])
        self.assertEqual([event["event"] for event in events if event["event"] == "text"], [])
        self.assertEqual(events[0]["name"], "Escape")


class PacketTests(unittest.TestCase):
    def test_out_of_order_chunks_drain_without_losing_the_next_frame(self):
        sniffer, events = self.sniffer()
        frame = websocket("kd,104") + websocket("ku,104")
        sniffer.packet(segment(1000, frame[:4]))
        sniffer.packet(segment(1012, frame[12:]))
        sniffer.packet(segment(1004, frame[4:12]))
        self.assertEqual(next(iter(sniffer.connections.values()))["next"], 1024)
        sniffer.packet(segment(1024, websocket("kd,105")))
        self.assertEqual([event["event"] for event in events], ["key", "text", "key", "key"])
        self.assertEqual(events[-1]["name"], "i")

    def sniffer(self):
        events = []
        return tap.Sniffer(["lo"], lambda event, **fields: events.append({"event": event, **fields})), events

    def test_messages_are_decoded_from_tcp_segments(self):
        sniffer, events = self.sniffer()
        sequence = 1000
        for message in ["m,300,400,1,0,1", "m,300,400,0,0,2", "kd,104", "ku,104"]:
            payload = websocket(message)
            sniffer.packet(segment(sequence, payload))
            sequence += len(payload)
        sniffer.translator.flush("test")
        self.assertEqual([event["event"] for event in events],
                         ["click", "click", "key", "text", "key", "text"])
        self.assertEqual([event["text"] for event in events if event["event"] == "text"], ["h", "h"])

    def test_a_message_split_across_segments_is_rejoined(self):
        sniffer, events = self.sniffer()
        frame = websocket("m,321,654,0,0,1")
        sniffer.packet(segment(2000, frame[:5]))
        sniffer.packet(segment(2005, frame[5:]))
        self.assertEqual([event["event"] for event in events], ["move"])
        self.assertEqual(events[0]["x"], 321)

    def test_two_messages_in_one_segment_are_both_read(self):
        sniffer, events = self.sniffer()
        first, second = websocket("m,1,2,0,0,1"), websocket("kd,104")
        sniffer.packet(segment(3000, first + second))
        self.assertEqual([event["event"] for event in events], ["move", "key"])

    def test_another_port_is_ignored(self):
        sniffer, events = self.sniffer()
        sniffer.packet(segment(4000, websocket("m,1,2,0,0,1"), destination_port=9100))
        self.assertEqual(events, [])

    def test_a_duplicate_segment_is_read_once(self):
        sniffer, events = self.sniffer()
        frame = segment(5000, websocket("m,7,8,0,0,1"))
        sniffer.packet(frame)
        sniffer.packet(frame)
        self.assertEqual(len(events), 1)

    def test_a_segment_that_arrives_after_later_bytes_is_ignored(self):
        sniffer, events = self.sniffer()
        first, second = websocket("m,11,22,0,0,1"), websocket("kd,104")
        sniffer.packet(segment(6000, first))
        sniffer.packet(segment(6000 + len(first), second))
        sniffer.packet(segment(6000, first))
        self.assertEqual([event["event"] for event in events], ["move", "key"])

    def test_binary_frames_do_not_disturb_text_frames(self):
        sniffer, events = self.sniffer()
        payload = websocket(b"\x00\x01\x02\x03", opcode=2) + websocket("m,9,9,0,0,1")
        sniffer.packet(segment(7000, payload))
        self.assertEqual([event["event"] for event in events], ["move"])

    def test_a_lost_segment_does_not_stall_the_connection(self):
        sniffer, events = self.sniffer()
        missed = websocket("m,1,1,0,0,1")
        later = websocket("kd,104") + websocket("ku,104")
        hole = len(missed) + 500
        sniffer.packet(segment(8000, missed))
        sniffer.packet(segment(8000 + hole, later))
        sniffer.packet(segment(8000 + hole + len(later), websocket("kd,111") + websocket("ku,111")))
        self.assertEqual([event["event"] for event in events], ["move"])
        for connection_id, held in list(sniffer.connections.items()):
            sniffer.recover(connection_id, held, time.monotonic() + 5)
        sniffer.translator.flush("test")
        self.assertEqual([event["event"] for event in events],
                         ["move", "key", "text", "key", "key", "text", "key", "text"])

    def test_the_capture_loop_waits_before_abandoning_a_gap(self):
        sniffer, _ = self.sniffer()
        connection = (b"source", 1, b"destination", 2)
        sniffer.connections[connection] = {"next": 1000, "buffer": b"", "pending": {1100: websocket("kd,104")},
                                           "progress": 500.0}
        sock = Mock()
        sock.recv.side_effect = tap.socket.timeout
        sniffer.sockets = [("lo", sock)]

        with patch.object(tap.time, "monotonic", return_value=500.5):
            sniffer.run(stopping={"asked": True})
        self.assertTrue(sniffer.connections[connection]["pending"])

        with patch.object(tap.time, "monotonic", return_value=502.0):
            sniffer.run(stopping={"asked": True})
        self.assertFalse(sniffer.connections[connection]["pending"])

    def test_a_corrupted_frame_is_resynced_to_the_next_message(self):
        sniffer, events = self.sniffer()
        broken = b"\x81\x05garbage"
        sniffer.packet(segment(9000, broken + websocket("kd,104") + websocket("ku,104")))
        self.assertEqual([event["event"] for event in events], ["key", "text", "key"])
        sniffer.translator.flush("test")
        self.assertEqual([event["text"] for event in events if event["event"] == "text"], ["h", "h"])


class ShutdownTests(unittest.TestCase):
    def test_the_stop_handlers_ask_the_loop_to_finish(self):
        stopping = {"asked": False}
        tap.install_stop_handlers(stopping)
        self.assertFalse(stopping["asked"])
        os.kill(os.getpid(), signal.SIGTERM)
        for _ in range(50):
            if stopping["asked"]:
                break
            time.sleep(0.01)
        self.assertTrue(stopping["asked"], "SIGTERM must end the capture loop, not kill the process")

    def test_stopping_flushes_a_half_typed_word(self):
        events = []
        translator = tap.Translator(lambda event, **fields: events.append({"event": event, **fields}))
        translator.key(ord("w"), True)
        translator.key(ord("w"), False)
        translator.flush("stopped")
        self.assertEqual([event["text"] for event in events if event["event"] == "text"], ["w", "w"])


class SubtitleTests(unittest.TestCase):
    def timeline(self):
        return post.Timeline([1000.0, 1200.0], [10.0, 5.0])

    def test_pauses_do_not_shift_later_events(self):
        timeline = self.timeline()
        self.assertAlmostEqual(timeline.at(1004.0), 4.0, places=2)
        self.assertAlmostEqual(timeline.at(1202.0), 12.0, places=2)
        self.assertAlmostEqual(timeline.at(1204.0), 14.0, places=2)
        self.assertIsNone(timeline.at(1190.0))
        self.assertIsNone(timeline.at(1210.0))

    def test_click_draws_a_ring_at_the_click(self):
        events = [{"time": 1002.0, "event": "click", "action": "down", "x": 640, "y": 480, "button": "right"}]
        text = post.subtitles(events, self.timeline())
        self.assertIn("Dialogue: 10,", text)
        self.assertIn("\\pos(640,480)", text)
        self.assertIn(post.BUTTON_COLOURS["right"], text)

    def test_typed_text_becomes_a_caption(self):
        events = [{"time": 1003.0, "event": "text", "text": "shopee.co.th", "partial": False}]
        text = post.subtitles(events, self.timeline())
        self.assertIn("shopee.co.th", text)

    def test_events_outside_the_recording_are_dropped(self):
        events = [{"time": 900.0, "event": "click", "action": "down", "x": 1, "y": 1, "button": "left"}]
        self.assertNotIn("Dialogue: 10,", post.subtitles(events, self.timeline()))

    def test_keyframes_cover_clicks_and_scene_changes(self):
        events = [{"time": 1002.0, "event": "click", "action": "down", "x": 5, "y": 5, "button": "left"}]
        with patch.object(post, "run", return_value="n: 1 pts_time:3.5\nn: 2 pts_time:8.25\n"):
            moments = post.keyframes(Path("video.mp4"), events, self.timeline(), 15.0, 0.12, 2)
        rounded = [round(moment, 2) for moment in moments]
        self.assertIn(1.65, rounded)
        self.assertIn(2.0, rounded)
        self.assertIn(3.5, rounded)
        self.assertIn(8.25, rounded)

    def test_timestamps_are_ass_time(self):
        self.assertEqual(post.timestamp(3661.5), "1:01:01.50")
        self.assertEqual(post.timestamp(-5), "0:00:00.00")


class RecordingLayoutTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {
            "BOXES_STATE_DIR": str(root / "state"), "BOXES_DATA_DIR": str(root / "data")})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.instance = cli.Instance(cli.box_type("browser"), "research")

    def test_recordings_and_lessons_live_under_the_type(self):
        self.assertEqual(recording.recordings_root(self.instance),
                         self.instance.data_root / "recordings/browser/research")
        self.assertEqual(recording.lessons_root(self.instance),
                         self.instance.data_root / "lessons/browser")

    def test_a_lesson_is_written_and_read_back(self):
        result = recording.record_lesson(self.instance, "shopee-search", "# Search Shopee\n\nSteps.\n")
        self.assertEqual(Path(result["file"]).name, "shopee-search.md")
        listed = recording.lessons(self.instance, "list")
        self.assertEqual([lesson["slug"] for lesson in listed["lessons"]], ["shopee-search"])
        self.assertEqual(listed["lessons"][0]["title"], "Search Shopee")
        shown = recording.lessons(self.instance, "show", "shopee-search")
        self.assertIn("Steps.", shown["markdown"])

    def test_a_lesson_slug_cannot_escape_the_directory(self):
        for slug in ("../escape", "sub/dir", "", ".hidden"):
            with self.subTest(slug=slug), self.assertRaisesRegex(Exception, "slug"):
                recording.record_lesson(self.instance, slug, "# x")

    def test_forget_removes_only_a_kept_recording(self):
        directory = recording.recordings_root(self.instance) / "2026-01-01T00-00-00Z"
        directory.mkdir(parents=True)
        (directory / "index.json").write_text("{}")
        with self.assertRaisesRegex(Exception, "No recording"):
            recording.forget(self.instance, "../escape")
        recording.forget(self.instance, directory.name)
        self.assertFalse(directory.exists())

    def test_forget_rejects_paths_and_preserves_siblings(self):
        root = recording.recordings_root(self.instance)
        root.mkdir(parents=True)
        sentinel = root.parent / "sentinel"
        sentinel.write_text("keep")
        for name in ("..", ".", "", str(root), "/", "child/..", "../sentinel", "child/"):
            with self.subTest(name=name), self.assertRaisesRegex(Exception, "No recording"):
                recording.forget(self.instance, name)
            self.assertEqual(sentinel.read_text(), "keep")
            self.assertTrue(root.is_dir())

    def test_forget_rejects_symlinks(self):
        root = recording.recordings_root(self.instance)
        target = root / "kept"
        target.mkdir(parents=True)
        sentinel = target / "sentinel"
        sentinel.write_text("keep")
        (root / "link").symlink_to(target, target_is_directory=True)
        with self.assertRaisesRegex(Exception, "No recording"):
            recording.forget(self.instance, "link")
        self.assertEqual(sentinel.read_text(), "keep")
        self.assertTrue((root / "link").is_symlink())

    def test_forget_refuses_the_active_recording(self):
        directory = recording.recordings_root(self.instance) / "current"
        directory.mkdir(parents=True)
        with patch.object(recording, "active", return_value={"name": "current"}):
            with self.assertRaisesRegex(Exception, "active"):
                recording.forget(self.instance, "current")
        self.assertTrue(directory.is_dir())

    def test_status_without_a_recording_lists_kept_names(self):
        (recording.recordings_root(self.instance) / "kept").mkdir(parents=True)
        value = recording.status(self.instance)
        self.assertFalse(value["active"])
        self.assertEqual(value["recordings"], ["kept"])

    def test_stop_without_a_recording_is_refused(self):
        with self.assertRaisesRegex(Exception, "No recording is active"):
            recording.stop(self.instance)


class RecordCommandTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.environment = patch.dict(os.environ, {
            "BOXES_STATE_DIR": str(root / "state"), "BOXES_DATA_DIR": str(root / "data")})
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def run_command(self, arguments, **patches):
        import contextlib
        import io
        stack = [patch.object(cli.Instance, "load", return_value={"data": self.temporary.name})]
        for name, value in patches.items():
            stack.append(patch.object(recording, name, **value))
        with contextlib.ExitStack() as exit_stack:
            for item in stack:
                exit_stack.enter_context(item)
            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                code = cli.main(arguments)
        return code, stdout.getvalue()

    def test_start_passes_fps_and_overlay(self):
        value = {"name": "one", "overlay": True, "fps": 12}
        code, printed = self.run_command(["record", "browser", "start", "--fps", "12", "--overlay"],
                                         start={"return_value": value})
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(printed), value)

    def test_fps_outside_the_range_is_rejected(self):
        code, _ = self.run_command(["record", "browser", "start", "--fps", "0"], start={"return_value": {}})
        self.assertEqual(code, 1)

    def test_the_operation_names_do_not_need_a_delimiter(self):
        for operation in ("status", "list", "stop", "pause", "resume"):
            with self.subTest(operation=operation):
                code, _ = self.run_command(["record", "browser", operation],
                                           **{operation: {"return_value": {"operation": operation}}})
                self.assertEqual(code, 0)

    def test_a_named_instance_is_still_addressable(self):
        code, _ = self.run_command(["record", "browser", "shopping", "status"],
                                   status={"return_value": {"name": "shopping"}})
        self.assertEqual(code, 0)

    def test_lessons_record_reads_markdown_from_stdin(self):
        import contextlib
        import io
        written = {}
        with patch.object(cli.Instance, "load", return_value={}), \
                patch.object(recording, "record_lesson", side_effect=lambda instance, slug, text: written.update(
                    {"slug": slug, "text": text})) as _record, \
                patch("sys.stdin", io.StringIO("# Title\n\nBody\n")), \
                contextlib.redirect_stdout(io.StringIO()):
            code = cli.main(["lessons", "browser", "record", "example"])
        self.assertEqual(code, 0)
        self.assertEqual(written, {"slug": "example", "text": "# Title\n\nBody\n"})

    def test_lessons_record_refuses_empty_input(self):
        import contextlib
        import io
        with patch.object(cli.Instance, "load", return_value={}), \
                patch.object(recording, "record_lesson") as write, \
                patch("sys.stdin", io.StringIO("   \n")), \
                contextlib.redirect_stderr(io.StringIO()):
            code = cli.main(["lessons", "browser", "record", "example"])
        self.assertEqual(code, 1)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
