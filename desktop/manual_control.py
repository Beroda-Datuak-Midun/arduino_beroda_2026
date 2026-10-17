#!/usr/bin/env python3
"""Ubuntu keyboard control and commissioning console for OMNI1 firmware."""
import argparse
import math
import sys
import time
import tkinter as tk
from tkinter import messagebox, ttk

import serial
from serial.tools import list_ports

if __package__:
    from .control import Keys, Lines, parse_telemetry
else:
    from control import Keys, Lines, parse_telemetry


class Application:
    def __init__(self, root, port=""):
        self.root = root
        self.link = None
        self.keys = Keys()
        self.lines = Lines()
        self.telemetry = None
        self.connected_at = self.last_rx = self.last_send = 0.0
        self.handshake = 0
        self.last_clock = None
        self.service_command = None
        self.service_hold = None
        self.releases = {}
        self.closing = False
        self.pending = None
        self.port = tk.StringVar(value=port)
        self.speed = tk.DoubleVar(value=15)
        self.status = tk.StringVar(value="Terputus")
        self.notice = tk.StringVar(value="Konfigurasi dan verifikasi encoder sebelum gerak normal.")
        self.motor = tk.StringVar(value="1")
        self.service_pwm = tk.StringVar(value="20")
        self.service_rpm = tk.StringVar(value="5")
        self.values = [tk.StringVar(value="") for _ in range(5)]
        self.service_ack = False
        self.focused = False
        self.build()
        root.bind("<KeyPress>", self.key_press)
        root.bind("<KeyRelease>", self.key_release)
        root.bind("<FocusOut>", lambda event: root.after_idle(self.check_focus))
        root.bind("<FocusIn>", lambda event: root.after_idle(self.check_focus))
        root.protocol("WM_DELETE_WINDOW", self.close)
        root.after(20, self.tick)

    def build(self):
        self.root.title("Beroda 2026 — Kendali manual")
        self.root.geometry("840x650")
        frame = ttk.Frame(self.root, padding=16)
        frame.pack(fill="both", expand=True)
        connection = ttk.Frame(frame)
        connection.pack(fill="x")
        ttk.Label(connection, text="Port USB").pack(side="left")
        self.ports = ttk.Combobox(connection, textvariable=self.port, width=27)
        self.ports.pack(side="left", padx=6)
        ttk.Button(connection, text="Cari port", command=self.refresh_ports).pack(side="left")
        ttk.Button(connection, text="Sambung", command=self.connect).pack(side="left", padx=6)
        ttk.Button(connection, text="Putus", command=self.disconnect).pack(side="left")
        ttk.Label(frame, textvariable=self.status).pack(anchor="w", pady=(12, 4))
        ttk.Label(frame, textvariable=self.notice, wraplength=790).pack(anchor="w")
        self.tabs = ttk.Notebook(frame)
        self.tabs.pack(fill="both", expand=True, pady=12)
        drive = ttk.Frame(self.tabs, padding=12)
        service = ttk.Frame(self.tabs, padding=12)
        self.tabs.add(drive, text="Kendali keyboard")
        self.tabs.add(service, text="Servis & kalibrasi")
        self.tabs.bind("<<NotebookTabChanged>>", self.tab_changed)
        ttk.Label(drive, text="Tahan W / S: maju / mundur\nTahan A / D: putar kiri / kanan\nSpace atau Escape: berhenti", font=("TkDefaultFont", 16)).pack(pady=15)
        ttk.Label(drive, text="Kecepatan (% dari batas RPM roda)").pack()
        ttk.Scale(drive, from_=1, to=50, variable=self.speed).pack(fill="x", padx=50)
        ttk.Label(drive, text="Lepas tombol sebelum memulai lagi setelah stop atau perubahan fokus.").pack(pady=12)
        ttk.Label(service, text="Angkat roda. Masuk servis menonaktifkan kendali WASD.").grid(row=0, column=0, columnspan=6, sticky="w")
        ttk.Button(service, text="Masuk servis", command=lambda: self.setting("SERVICE")).grid(row=1, column=0, pady=8)
        ttk.Button(service, text="Keluar servis", command=lambda: self.setting("EXIT")).grid(row=1, column=1)
        ttk.Label(service, text="Motor").grid(row=1, column=2)
        motor_choice = ttk.Combobox(service, textvariable=self.motor, values=("1", "2", "3"), state="readonly", width=4)
        motor_choice.grid(row=1, column=3)
        motor_choice.bind("<<ComboboxSelected>>", lambda event: self.stop())
        for i, label in enumerate(("CPR ×4", "Batas RPM", "Kp", "Ki", "Kd")):
            ttk.Label(service, text=label).grid(row=2, column=i, padx=4)
            ttk.Entry(service, textvariable=self.values[i], width=10).grid(row=3, column=i, padx=4)
        ttk.Button(service, text="Terapkan ke RAM", command=self.configure).grid(row=4, column=0, columnspan=2, pady=8)
        ttk.Button(service, text="Nolkan hitungan", command=lambda: self.setting("ZERO")).grid(row=4, column=2, columnspan=2)
        ttk.Button(service, text="ARM: kalibrasi terverifikasi", command=self.arm).grid(row=5, column=0, columnspan=5, pady=4)
        ttk.Label(service, text="PWM uji (1–40)").grid(row=6, column=0)
        ttk.Entry(service, textvariable=self.service_pwm, width=8).grid(row=6, column=1)
        ttk.Label(service, text="RPM uji").grid(row=7, column=0)
        ttk.Entry(service, textvariable=self.service_rpm, width=8).grid(row=7, column=1)
        for row, kind in ((6, "PWM"), (7, "RPM")):
            for column, sign, label in ((2, -1, "Tahan −"), (3, 1, "Tahan +")):
                button = ttk.Button(service, text=label)
                button.grid(row=row, column=column, padx=4, pady=4)
                button.bind("<ButtonPress-1>", lambda event, k=kind, s=sign: self.start_service(k, s))
                button.bind("<ButtonRelease-1>", lambda event: self.stop())
                button.bind("<Leave>", lambda event: self.stop())
        ttk.Label(service, text="Pengaturan RAM hilang saat reset. Salin hasil final ke robot_config.h.").grid(row=8, column=0, columnspan=5, sticky="w", pady=8)
        self.table = ttk.Treeview(frame, columns=("motor", "target", "rpm", "ticks", "pwm"), show="headings", height=3)
        for name, title in zip(self.table["columns"], ("Motor", "Target RPM", "RPM aktual", "Encoder ×4", "PWM")):
            self.table.heading(name, text=title)
            self.table.column(name, width=130, anchor="center")
        for i in range(3):
            self.table.insert("", "end", iid=str(i), values=(f"M{i+1}", "—", "—", "—", "—"))
        self.table.pack(fill="x")
        ttk.Button(frame, text="BERHENTI — Space / Escape", command=self.stop).pack(fill="x", pady=(12, 0))
        self.refresh_ports()

    def refresh_ports(self):
        ports = [p.device for p in list_ports.comports()]
        self.ports["values"] = ports
        if not self.port.get() and ports:
            self.port.set(ports[0])

    def send(self, command):
        if not self.link:
            return False
        try:
            data = (command + "\n").encode("ascii")
            if self.link.write(data) != len(data):
                raise serial.SerialTimeoutException("Partial write")
            return True
        except (serial.SerialException, OSError) as exc:
            self.disconnect(f"Serial terputus: {exc}")
            return False

    def connect(self):
        if self.link:
            return
        self.keys.stop()
        try:
            self.link = serial.Serial(self.port.get(), 115200, timeout=0, write_timeout=0.05, exclusive=True)
        except (serial.SerialException, OSError, ValueError) as exc:
            self.notice.set(f"Gagal membuka port: {exc}")
            return
        self.lines = Lines()
        self.telemetry = None
        self.handshake = 0
        self.last_clock = None
        self.pending = None
        self.service_ack = False
        self.connected_at = time.monotonic()
        self.last_rx = self.connected_at
        self.status.set("Menunggu Mega dan telemetri…")
        self.notice.set("Lepas WASD; koneksi baru tidak melanjutkan gerakan sebelumnya.")
        self.send("EXIT")

    def disconnect(self, reason="Terputus"):
        self.keys.stop()
        self.service_command = self.service_hold = None
        self.pending = None
        self.service_ack = False
        link, self.link = self.link, None
        if link:
            try:
                link.write(b"STOP\n")
            except (serial.SerialException, OSError):
                pass
            finally:
                link.close()
        self.telemetry = None
        self.handshake = 0
        self.status.set(reason)

    def stop(self):
        self.keys.stop()
        self.service_command = self.service_hold = None
        if self.link:
            self.send("STOP")

    def check_focus(self):
        focused = self.root.focus_displayof() is not None
        if self.focused and (not focused or self.editing()):
            self.stop()
        self.focused = focused

    def editing(self):
        widget = self.root.focus_get()
        return widget is not None and widget.winfo_class() in {"Entry", "TEntry", "TCombobox", "Text", "Spinbox", "TSpinbox"}

    def tab_changed(self, event=None):
        self.stop()

    def driving_allowed(self):
        return (self.link is not None and self.handshake == 2 and self.focused and not self.editing()
                and self.pending is None and self.telemetry is not None
                and self.telemetry.ready and self.telemetry.mode != "SERVICE"
                and self.tabs.index("current") == 0)

    def key_press(self, event):
        key = event.keysym.lower()
        # X11 autorepeat generates release/press pairs. Cancel deferred release.
        if key in self.releases:
            self.root.after_cancel(self.releases.pop(key))
        if key in {"space", "escape"}:
            self.stop()
            return "break" if self.tabs.index("current") == 0 else None
        self.keys.press(key, self.driving_allowed())
        if key in {"w", "a", "s", "d"} and self.keys.command(self.speed.get() / 100) == "STOP":
            if self.link:
                self.send("STOP")
        if key in {"w", "a", "s", "d"} and self.tabs.index("current") == 0:
            return None if self.editing() else "break"
        return None

    def key_release(self, event):
        key = event.keysym.lower()
        if key not in {"w", "a", "s", "d"}:
            return
        if key in self.releases:
            self.root.after_cancel(self.releases[key])
        self.releases[key] = self.root.after_idle(lambda: self.finish_release(key))

    def finish_release(self, key):
        self.releases.pop(key, None)
        self.keys.release(key)
        if self.link and self.keys.command(self.speed.get() / 100) == "STOP":
            self.send("STOP")

    def setting(self, command):
        if not self.link or self.handshake != 2:
            self.notice.set("Sambungkan Mega dan tunggu telemetri dahulu.")
            return
        if self.pending:
            self.notice.set("Tunggu jawaban pengaturan sebelumnya.")
            return
        self.stop()
        self.pending = (command, time.monotonic())
        if not self.send(command):
            self.pending = None

    def configure(self):
        try:
            cpr, maximum, kp, ki, kd = (float(v.get()) for v in self.values)
            if (not all(map(math.isfinite, (cpr, maximum, kp, ki, kd)))
                    or not 1 <= cpr <= 10000000 or not 0 < maximum <= 10000
                    or not 0 < kp <= 1000 or not 0 <= ki <= 1000 or not 0 <= kd <= 1000):
                raise ValueError
        except ValueError:
            self.notice.set("Isi CPR ≥1, batas RPM >0, Kp >0, Ki/Kd ≥0 dengan angka valid.")
            return
        self.setting(f"SET {self.motor.get()} {cpr:g} {maximum:g} {kp:g} {ki:g} {kd:g}")

    def arm(self):
        self.stop()
        if messagebox.askyesno("Konfirmasi kalibrasi", "Arah ketiga motor/encoder, CPR, batas RPM, dan PID sudah diverifikasi dengan roda terangkat?"):
            self.setting("ARM")

    def start_service(self, kind, sign):
        if (not self.link or self.handshake != 2 or self.pending or not self.service_ack
                or not self.telemetry or self.telemetry.mode != "SERVICE"):
            self.notice.set("Masuk servis dan tunggu konfirmasi Mega sebelum uji motor.")
            return
        try:
            value = float(self.service_pwm.get() if kind == "PWM" else self.service_rpm.get())
            if not math.isfinite(value) or value <= 0 or (kind == "PWM" and (value > 40 or not value.is_integer())):
                raise ValueError
        except ValueError:
            self.notice.set("Nilai uji harus positif; PWM harus bilangan bulat 1–40.")
            return
        self.stop()
        self.service_command = f"{kind} {self.motor.get()} {sign * value:g}"
        self.service_hold = time.monotonic()
        self.send(self.service_command)

    def receive(self, now):
        try:
            data = self.link.read(min(self.link.in_waiting, 2048))
        except (serial.SerialException, OSError) as exc:
            self.disconnect(f"Serial terputus: {exc}")
            return
        for line in self.lines.feed(data):
            if line.startswith("TEL "):
                try:
                    reading = parse_telemetry(line)
                except ValueError:
                    continue
                self.last_rx = now
                # A reset/wrapped clock must never resume an old key hold.
                if self.last_clock is not None and reading.milliseconds < self.last_clock:
                    self.disconnect("Mega reset/clock berubah; sambungkan ulang.")
                    return
                self.last_clock = reading.milliseconds
                self.telemetry = reading
                if self.handshake == 0:
                    self.stop()
                    if not self.send("EXIT"):
                        return
                    self.handshake = 1
                elif self.handshake == 1 and reading.mode == "IDLE":
                    self.handshake = 2
                readiness = "siap" if reading.ready else "belum dikalibrasi / belum ARM"
                self.status.set(f"{self.port.get()} — {reading.mode} — {readiness}")
                for i, wheel in enumerate(reading.wheels):
                    self.table.item(str(i), values=(f"M{i+1}", f"{wheel.target:.2f}", f"{wheel.rpm:.2f}", wheel.ticks, wheel.pwm))
            elif line.startswith("BOOT "):
                if self.handshake == 2:
                    self.disconnect("Mega reset; sambungkan ulang.")
                    return
            elif line.startswith("OK "):
                if self.pending and line[3:] == self.pending[0].split()[0]:
                    command, _ = self.pending
                    self.pending = None
                    self.service_ack = command == "SERVICE" or (self.service_ack and command != "EXIT")
                    self.notice.set(f"Diterima Mega: {command}")
            elif line.startswith("ERR "):
                self.pending = None
                self.stop()
                self.notice.set(f"Mega menolak perintah: {line[4:]}")

    def tick(self):
        if self.closing:
            return
        now = time.monotonic()
        if self.link:
            self.receive(now)
        if self.link:
            if (self.handshake < 2 and now - self.connected_at > 5
                    or self.handshake == 2 and now - self.last_rx > 0.5):
                self.disconnect("Telemetri timeout; sambungkan ulang.")
            elif self.pending and now - self.pending[1] > 1:
                self.disconnect("Konfirmasi perintah timeout; sambungkan ulang.")
            elif self.service_hold is not None and now - self.service_hold >= 2:
                self.stop()
                self.notice.set("Uji servis dibatasi 2 detik. Lepas lalu tekan lagi untuk melanjutkan.")
            elif now - self.last_send >= 0.05:
                if self.service_command and self.focused and not self.pending:
                    self.send(self.service_command)
                elif self.driving_allowed():
                    command = self.keys.command(self.speed.get() / 100)
                    if command != "STOP":
                        self.send(command)
                self.last_send = now
        self.root.after(20, self.tick)

    def close(self):
        self.closing = True
        self.disconnect()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", default="", help="Contoh: /dev/ttyACM0 atau /dev/serial/by-id/…")
    args = parser.parse_args()
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        sys.exit(f"Jendela tidak tersedia: {exc}. Jalankan dalam sesi desktop Ubuntu.")
    Application(root, args.port)
    root.mainloop()


if __name__ == "__main__":
    main()
