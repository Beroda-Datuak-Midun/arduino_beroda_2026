import unittest
from desktop.control import Keys, Lines, parse_telemetry


class InputTests(unittest.TestCase):
    def test_held_keys_and_combined_commands(self):
        keys = Keys()
        keys.press("w", True)
        keys.press("a", True)
        self.assertEqual(keys.command(.2), "MOVE 0.200 0 0.200")
        keys.press("s", True)
        keys.press("d", True)
        self.assertEqual(keys.command(.2), "STOP")
        keys.release("s")
        self.assertEqual(keys.command(.2), "MOVE 0.200 0 0.000")
        keys.release("w")
        self.assertEqual(keys.command(.2), "STOP")

    def test_stop_reconnect_and_focus_need_new_press(self):
        keys = Keys()
        keys.press("w", True)
        keys.stop()
        keys.press("w", True)  # Autorepeat is not a fresh press.
        self.assertEqual(keys.command(.2), "STOP")
        keys.release("w")
        keys.press("w", True)
        self.assertNotEqual(keys.command(.2), "STOP")
        keys.stop()
        keys.release("w")
        keys.press("w", False)  # Press while disconnected/not ready.
        keys.press("w", True)
        self.assertEqual(keys.command(.2), "STOP")

    def test_bounded_lines_and_recovery(self):
        lines = Lines()
        self.assertEqual(lines.feed(b"TE"), [])
        self.assertEqual(lines.feed(b"L 123\r\nOK STOP\n"), ["TEL 123", "OK STOP"])
        self.assertEqual(lines.feed(b"x" * 1000 + b"\nOK\n"), ["OK"])
        self.assertEqual(lines.feed(b"\xff\nOK\n"), ["OK"])

    def test_telemetry_validation(self):
        valid = "TEL 123 SERVICE 0 0 0 100 20 0 -1 -200 -20 0 0 0 0"
        reading = parse_telemetry(valid)
        self.assertEqual(reading.wheels[1].ticks, -200)
        self.assertFalse(reading.ready)
        for invalid in (valid + " 1", valid.replace("SERVICE", "BOGUS"),
                        valid.replace(" 20 ", " 256 "), valid.replace("0 -1", "0 nan"),
                        valid.replace("123", "-1"), "TEL junk"):
            with self.assertRaises(ValueError):
                parse_telemetry(invalid)


if __name__ == "__main__":
    unittest.main()
