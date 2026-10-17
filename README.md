# Beroda 2026 — kendali manual omni tiga roda

Kendali keyboard Ubuntu untuk tiga motor PG45 dengan encoder internal, tiga modul
BTS7960 dua arah, dan Arduino Mega 2560. Mini PC mengirim perintah melalui USB;
Mega menghitung target roda, membaca encoder kuadratur ×4, dan menjalankan PID
kecepatan setiap 10 ms.

**Firmware awal mengunci gerak normal.** CPR, batas RPM, dan PID belum diketahui;
nilainya harus diukur. Mode servis tersedia sebelum kalibrasi untuk memeriksa satu
motor dengan PWM terbatas. Pengujian fisik dan tuning belum dilakukan oleh kode ini.

## Posisi roda dan wiring

Dilihat dari atas, depan robot adalah +X dan kiri adalah +Y. Sudut diukur
berlawanan arah jarum jam dari depan menuju posisi as roda:

```text
                     DEPAN (+X)
          M3 kiri depan      M2 kanan depan
                60°              300°
                         ●
                         |
                     M1 belakang
                        180°
```

Roda positif bergerak tangensial berlawanan arah jarum jam mengelilingi pusat
robot. Untuk maju, target M1 nol, M2 positif, dan M3 negatif. Bila posisi aktual
berbeda, sesuaikan `WheelAngles` dan penomoran motor sebelum uji gerak.

| Sambungan ke Mega | M1 belakang | M2 kanan depan | M3 kiri depan |
|---|---:|---:|---:|
| BTS7960 RPWM | 5 | 7 | 9 |
| BTS7960 LPWM | 6 | 8 | 10 |
| BTS7960 R_EN | 22 | 24 | 26 |
| BTS7960 L_EN | 23 | 25 | 27 |
| Encoder A | 2 | 18 | 20 |
| Encoder B | 3 | 19 | 21 |

- Hubungkan USB mini PC ke konektor USB Mega. Pin 0/1 tidak dipakai periferal lain.
- Hubungkan terminal keluaran motor pada setiap modul driver ke satu PG45.
  Terminal daya motor driver menggunakan suplai yang sesuai motor dan modul,
  **bukan pin 5 V Mega**. Pastikan label terminal pada modul sebenarnya.
- Suplai logika modul BTS7960 sesuai spesifikasinya; hubungkan GND Mega, GND
  logika driver, GND encoder, dan ground suplai motor bersama dengan wiring daya
  yang sesuai. R_IS/L_IS belum dipakai firmware.
- Gunakan pull-down eksternal pada R_EN dan L_EN (misalnya 10 kΩ ke GND bila
  sesuai rangkaian modul) agar driver tetap nonaktif ketika Mega reset/pin masih
  high impedance. Jangan mengikat EN langsung ke 5 V karena firmware memakainya
  untuk menonaktifkan penggerak.
- Verifikasi pinout, tegangan suplai, tegangan sinyal, dan tipe keluaran encoder
  PG45 sebelum menyambungkan A/B. Mega memakai logika 5 V; sinyal dengan tegangan
  lain memerlukan penyesuaian level yang sesuai. Jangan mengasumsikan warna kabel.
- `EncoderPullups` awalnya `false`. Pilih pull-up/level shifter setelah identifikasi
  encoder, bukan untuk menutupi wiring yang belum jelas.
- Keenam pin encoder adalah interrupt eksternal. Susunan ini menggunakan fungsi
  alternatif Serial1 (18/19) dan I²C (20/21); keduanya tidak tersedia pada pin itu.
  Serial2/Serial3 masih tersedia.

Pemetaan lengkap, tanda motor/encoder, sudut roda, dan data kalibrasi ada di
[`include/robot_config.h`](include/robot_config.h).

## Instalasi dan menjalankan

Firmware memakai proyek PlatformIO yang sudah tersedia:

```bash
pio run
pio run --target upload --upload-port /dev/ttyACM0
```

Gunakan port Mega sebenarnya. Jangan membuka serial monitor bersamaan dengan
aplikasi. Membuka port USB dapat me-reset Mega; aplikasi menunggu telemetri hingga
5 detik dan memastikan mode IDLE sebelum kendali aktif.

Pada desktop Ubuntu:

```bash
sudo apt install python3-venv python3-tk
python3 -m venv .venv
.venv/bin/pip install -r desktop/requirements.txt
.venv/bin/python desktop/manual_control.py
```

Pilih port lalu **Sambung**, atau tentukan port awal:

```bash
.venv/bin/python desktop/manual_control.py --port /dev/ttyACM0
```

Port `/dev/serial/by-id/...` dapat dimasukkan agar identitas perangkat lebih stabil.
Jika muncul izin serial ditolak, tambahkan pengguna Ubuntu ke grup serial:

```bash
sudo usermod -aG dialout "$USER"
```

Keluar dan masuk sesi Ubuntu lagi setelah perubahan grup. Aplikasi membutuhkan
sesi desktop dengan display; tidak perlu menjalankan aplikasi sebagai root.

## Kendali keyboard

Setelah kalibrasi dan ARM, pilih tab **Kendali keyboard** dan fokuskan jendelanya
(klik area kosong atau tab, bukan kolom teks).

| Input | Gerak |
|---|---|
| Tahan W | Maju |
| Tahan S | Mundur |
| Tahan A | Putar badan ke kiri |
| Tahan D | Putar badan ke kanan |
| W/S bersama A/D | Translasi sekaligus berputar |
| Space, Escape, atau tombol BERHENTI | Hentikan semua motor |
| Lepas tombol arah | Hentikan komponen gerak tersebut |

Slider awal 15%, dengan rentang 1–50% dari batas RPM roda paling rendah. Kecepatan
ini bersifat relatif, belum m/s. Target kombinasi gerak dinormalisasi bersama agar
rasio target tetap sama dan batas roda tidak terlampaui. Firmware juga mendukung
`vy` untuk pergeseran samping, tetapi tahap ini tidak memberi tombol untuknya.

Kehilangan fokus aplikasi, pindah tab, masuk kolom teks, putus koneksi, atau reset
Mega menghapus gerakan aktif. Setelah stop, lepaskan tombol sebelum menekan lagi;
autorepeat tombol yang masih ditahan tidak boleh melanjutkan gerak. Bila tombol
dilepas di luar jendela, tekan-lepas sekali di jendela untuk membersihkan status
sebelum menekannya lagi.

Host mengirim gerak tiap sekitar 50 ms. Mega menonaktifkan motor setelah **300 ms
sejak perintah gerak valid terakhir**. Aplikasi juga memutus sesi bila telemetri
hilang lebih dari 500 ms dan tidak menyambung ulang otomatis.

STOP menonaktifkan kedua PWM dan enable; roda bisa meluncur karena inersia.
Penghentian ini bukan rem mekanis atau emergency stop perangkat keras.

## Kalibrasi sebelum uji lantai

Ikuti [`docs/calibration.md`](docs/calibration.md). Urutannya:

1. Angkat roda, identifikasi listrik encoder, dan verifikasi wiring.
2. Ukur CPR ×4 setiap poros keluaran gearbox menggunakan hitungan mentah.
3. Verifikasi arah motor dan tanda encoder menggunakan PWM rendah per motor.
4. Masukkan CPR, batas RPM yang aman, dan gain awal yang dipilih untuk pengujian.
5. Tuning PID satu motor, kemudian ulangi untuk ketiganya.
6. Konfirmasikan kalibrasi dengan **ARM**, keluar servis, lalu uji arah pada
   kecepatan rendah. Salin hasil final ke konfigurasi firmware agar tidak hilang.

Pengaturan lewat jendela disimpan di RAM Mega saja. Tidak ada penyimpanan EEPROM
atau tuning PID otomatis. Setiap `SET` membatalkan ARM. Jika firmware tetap memakai
`CalibrationConfirmed=false`, lakukan ARM lagi setelah reset meskipun data final
sudah disalin ke header.

## Protokol dan pengujian

Protokol, telemetri, batas nilai, dan error dijelaskan di
[`docs/protocol.md`](docs/protocol.md).

Tes logika tanpa motor:

```bash
g++ -std=c++11 -Wall -Wextra -Werror -fsanitize=undefined,address -Iinclude tests/test_core.cpp -o /tmp/beroda-test-core
/tmp/beroda-test-core
.venv/bin/python -m unittest discover -s tests -v
pio run
```

Tes firmware mencakup parser, recovery frame, kinematika, PID anti-windup, mode
servis, penguncian kalibrasi, dan timeout termasuk overflow `millis()`. Tes Python
mencakup keyboard, framing telemetri, handshake, kehilangan fokus, reset, kegagalan
serial, konfirmasi pengaturan, dan batas durasi servis. Tes aplikasi membutuhkan
pySerial dari `desktop/requirements.txt`; tanpa itu tes aplikasi ditandai skip.

Untuk memeriksa widget Tk dalam sesi desktop tanpa membuka port serial fisik:

```bash
.venv/bin/python tests/gui_smoke.py
```

Sebelum di lantai, uji pelepasan tombol, kehilangan fokus, penutupan aplikasi,
pencabutan USB, dan reset Mega dengan roda terangkat. Verifikasi bahwa keluaran
driver nonaktif saat boot/STOP dan paling lambat 300 ms setelah perintah terakhir.
Ukur juga pembacaan encoder pada RPM tertinggi yang dipakai: batas laju interrupt
bergantung pada encoder PG45 sebenarnya. Tes software tidak memvalidasi wiring,
CPR, arah motor, kemampuan daya driver, atau kestabilan PID pada robot.

Referensi: [Arduino Mega](https://docs.arduino.cc/hardware/mega-2560),
[pinout Mega](https://docs.arduino.cc/resources/pinouts/A000067-full-pinout.pdf),
[pySerial](https://pyserial.readthedocs.io/en/latest/pyserial_api.html),
[Tkinter](https://docs.python.org/3/library/tkinter.html).
