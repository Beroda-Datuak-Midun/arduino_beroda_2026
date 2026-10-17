"""Input and wire format, independent of Tk and serial hardware."""
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Wheel:
    target: float
    rpm: float
    ticks: int
    pwm: int


@dataclass(frozen=True)
class Telemetry:
    milliseconds: int
    mode: str
    ready: bool
    wheels: tuple[Wheel, ...]


def parse_telemetry(line: str) -> Telemetry:
    fields = line.split()
    if len(fields) != 16 or fields[0] != "TEL":
        raise ValueError("Invalid telemetry length")
    milliseconds = int(fields[1])
    if not 0 <= milliseconds <= 0xFFFFFFFF:
        raise ValueError("Invalid firmware clock")
    if fields[2] not in {"IDLE", "DRIVE", "SERVICE"} or fields[3] not in {"0", "1"}:
        raise ValueError("Invalid firmware state")
    wheels = []
    for index in range(4, 16, 4):
        target, rpm = float(fields[index]), float(fields[index + 1])
        ticks, pwm = int(fields[index + 2]), int(fields[index + 3])
        if not all(map(math.isfinite, (target, rpm))) or abs(pwm) > 255:
            raise ValueError("Invalid wheel reading")
        if not -(2**31) <= ticks < 2**31:
            raise ValueError("Invalid encoder count")
        wheels.append(Wheel(target, rpm, ticks, pwm))
    return Telemetry(milliseconds, fields[2], fields[3] == "1", tuple(wheels))


class Keys:
    """Only a new press can start movement after a stop/focus/connection boundary."""
    def __init__(self):
        self.down: set[str] = set()
        self.active: set[str] = set()

    def press(self, key: str, enabled: bool):
        if key not in {"w", "a", "s", "d"}:
            return
        if key not in self.down and enabled:
            self.active.add(key)
        self.down.add(key)

    def release(self, key: str):
        self.down.discard(key)
        self.active.discard(key)

    def stop(self):
        self.active.clear()

    def command(self, speed: float) -> str:
        vx = (int("w" in self.active) - int("s" in self.active)) * speed
        wz = (int("a" in self.active) - int("d" in self.active)) * speed
        if vx == 0 and wz == 0:
            return "STOP"
        return f"MOVE {vx:.3f} 0 {wz:.3f}"


class Lines:
    """Bounded receive buffer, including resynchronisation after a long frame."""
    def __init__(self):
        self.buffer = bytearray()
        self.dropping = False

    def feed(self, data: bytes) -> list[str]:
        lines = []
        for byte in data:
            if byte == 10:
                if not self.dropping:
                    try:
                        lines.append(self.buffer.decode("ascii").rstrip("\r"))
                    except UnicodeDecodeError:
                        pass
                self.buffer.clear()
                self.dropping = False
            elif not self.dropping:
                if len(self.buffer) >= 239:
                    self.buffer.clear()
                    self.dropping = True
                else:
                    self.buffer.append(byte)
        return lines
