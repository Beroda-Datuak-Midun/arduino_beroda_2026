"""Exercise GUI safety transitions with a serial double, without a display."""
import importlib.util
import unittest
from unittest.mock import MagicMock, patch

from desktop.control import Keys, Lines, parse_telemetry

HAS_SERIAL = importlib.util.find_spec("serial") is not None
if HAS_SERIAL:
    import serial
    from desktop.manual_control import Application

TEL = b"TEL 1000 IDLE 1 0 0 0 0 0 0 0 0 0 0 0 0\n"


class Value:
    def __init__(self, value=None):
        self.value = value
    def get(self):
        return self.value
    def set(self, value):
        self.value = value


class Port:
    def __init__(self, incoming=b""):
        self.incoming = incoming
        self.writes = []
        self.closed = False
    @property
    def in_waiting(self):
        return len(self.incoming)
    def read(self, count):
        result, self.incoming = self.incoming[:count], self.incoming[count:]
        return result
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def close(self):
        self.closed = True


@unittest.skipUnless(HAS_SERIAL, "Install desktop/requirements.txt for application tests")
class ApplicationTests(unittest.TestCase):
    def app(self):
        app = Application.__new__(Application)
        app.root = MagicMock()
        app.root.focus_get.return_value = None
        app.root.focus_displayof.return_value = object()
        app.link = Port()
        app.keys = Keys()
        app.lines = Lines()
        app.telemetry = parse_telemetry(TEL.decode())
        app.connected_at = app.last_rx = app.last_send = 10.0
        app.handshake = 2
        app.last_clock = 1000
        app.service_command = app.service_hold = None
        app.releases = {}
        app.closing = False
        app.pending = None
        app.port = Value("fake-port")
        app.speed = Value(15)
        app.status, app.notice = Value(), Value()
        app.service_ack = False
        app.focused = True
        app.table = MagicMock()
        app.tabs = MagicMock()
        app.tabs.index.return_value = 0
        return app

    def test_handshake_stops_old_motion_and_does_not_resume_keys(self):
        app = self.app()
        app.handshake = 0
        app.last_clock = None
        app.keys.press("w", True)
        app.link.incoming = TEL
        app.receive(10.1)
        self.assertEqual(app.handshake, 1)
        self.assertIn(b"EXIT\n", app.link.writes)
        self.assertEqual(app.keys.command(.15), "STOP")
        app.link.incoming = TEL
        app.receive(10.2)
        self.assertEqual(app.handshake, 2)
        app.keys.press("w", True)
        self.assertEqual(app.keys.command(.15), "STOP")

    def test_acknowledgements_are_correlated(self):
        app = self.app()
        app.setting("SERVICE")
        self.assertEqual(app.link.writes, [b"STOP\n", b"SERVICE\n"])
        app.link.incoming = b"OK STOP\n"
        app.receive(10.1)
        self.assertIsNotNone(app.pending)
        app.link.incoming = b"OK SERVICE\n"
        app.receive(10.2)
        self.assertIsNone(app.pending)
        self.assertTrue(app.service_ack)

    def test_lost_focus_and_editing_stop_motion(self):
        app = self.app()
        app.keys.press("w", True)
        app.root.focus_displayof.return_value = None
        app.check_focus()
        self.assertIn(b"STOP\n", app.link.writes)
        self.assertFalse(app.keys.active)
        app.focused = True
        app.root.focus_displayof.return_value = object()
        app.root.focus_get.return_value = MagicMock()
        app.root.focus_get.return_value.winfo_class.return_value = "TEntry"
        self.assertFalse(app.driving_allowed())

    def test_autorepeat_and_real_release(self):
        app = self.app()
        event = MagicMock(keysym="w")
        app.key_press(event)
        self.assertIn("w", app.keys.active)
        app.key_release(event)
        app.key_press(event)
        app.root.after_cancel.assert_called_once()
        self.assertIn("w", app.keys.active)
        app.key_release(event)
        app.finish_release("w")
        self.assertFalse(app.keys.active)
        self.assertEqual(app.link.writes[-1], b"STOP\n")

    def test_opposing_keys_stop_immediately(self):
        app = self.app()
        app.key_press(MagicMock(keysym="w"))
        app.key_press(MagicMock(keysym="s"))
        self.assertEqual(app.link.writes[-1], b"STOP\n")

    def test_telemetry_timeout_closes_connection(self):
        app = self.app()
        port = app.link
        app.keys.press("w", True)
        with patch("desktop.manual_control.time.monotonic", return_value=10.6):
            app.tick()
        self.assertIsNone(app.link)
        self.assertTrue(port.closed)
        self.assertEqual(port.writes[-1], b"STOP\n")
        self.assertFalse(app.keys.active)

    def test_firmware_reset_and_invalid_telemetry(self):
        app = self.app()
        app.link.incoming = b"TEL invalid\n"
        app.receive(10.1)
        self.assertEqual(app.last_rx, 10.0)
        app.link.incoming = b"BOOT OMNI1\n"
        app.receive(10.2)
        self.assertIsNone(app.link)

    def test_read_and_partial_write_fail_closed(self):
        app = self.app()
        port = app.link
        port.read = MagicMock(side_effect=serial.SerialException("unplugged"))
        app.receive(10.1)
        self.assertIsNone(app.link)
        self.assertTrue(port.closed)
        app = self.app()
        port = app.link
        port.write = MagicMock(return_value=1)
        self.assertFalse(app.send("MOVE 1 0 0"))
        self.assertIsNone(app.link)
        self.assertTrue(port.closed)

    def test_service_hold_has_absolute_two_second_limit(self):
        app = self.app()
        app.service_command = "PWM 1 20"
        app.service_hold = 8.5
        app.link.incoming = TEL
        with patch("desktop.manual_control.time.monotonic", return_value=10.5):
            app.tick()
        self.assertIsNone(app.service_command)
        self.assertEqual(app.link.writes[-1], b"STOP\n")

    def test_pending_timeout_and_firmware_error_stop(self):
        app = self.app()
        app.pending = ("ARM", 9.0)
        app.link.incoming = TEL
        with patch("desktop.manual_control.time.monotonic", return_value=10.1):
            app.tick()
        self.assertIsNone(app.link)
        app = self.app()
        app.pending = ("ARM", 10)
        app.keys.press("w", True)
        app.link.incoming = b"ERR NOT_CALIBRATED\n"
        app.receive(10.1)
        self.assertIsNone(app.pending)
        self.assertFalse(app.keys.active)
        self.assertEqual(app.link.writes[-1], b"STOP\n")


if __name__ == "__main__":
    unittest.main()
