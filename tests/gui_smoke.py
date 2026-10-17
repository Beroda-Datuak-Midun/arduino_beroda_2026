"""Optional real-Tk smoke test. Does not open or command a physical serial port."""
import sys
from pathlib import Path
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from desktop.manual_control import Application


class Port:
    def __init__(self):
        self.data = b"TEL 1000 IDLE 0 0 0 10 0 0 0 20 0 0 0 -30 0\n"
        self.writes = []
        self.closed = False
    @property
    def in_waiting(self):
        return len(self.data)
    def read(self, count):
        result, self.data = self.data[:count], self.data[count:]
        return result
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def close(self):
        self.closed = True


root = tk.Tk()
root.withdraw()
app = Application(root)
try:
    root.update()
    assert len(app.tabs.tabs()) == 2
    app.tabs.select(1)
    root.update()
    port = Port()
    app.link = port
    app.receive(1.0)
    assert app.telemetry.wheels[2].ticks == -30
    assert str(app.table.item("2", "values")[3]) == "-30"
    assert b"EXIT\n" in port.writes
    app.handshake = 2
    for value, text in zip(app.values, ("1000", "100", "1", "0", "0")):
        value.set(text)
    app.configure()
    assert port.writes[-1] == b"SET 1 1000 100 1 0 0\n"
    port.data = b"OK STOP\nOK SET\n"
    app.receive(1.1)
    assert app.pending is None
    app.stop()
    assert port.writes[-1] == b"STOP\n"
finally:
    app.close()
print("Tk smoke: widgets, tabs, telemetry, configuration and STOP passed")
