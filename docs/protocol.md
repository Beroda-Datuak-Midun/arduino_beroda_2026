# Protokol serial OMNI1

USB serial 115200 baud, 8N1, ASCII, terminator LF (`\n`); CRLF diterima. Satu
perintah per baris. Huruf perintah kapital. Panjang maksimal 95 karakter sebelum
LF (CR diabaikan). Overflow atau byte non-ASCII/kontrol membatalkan seluruh frame
hingga LF; suffix frame tidak pernah dijalankan sebagai perintah baru.

## Perintah

| Pesan | Fungsi dan syarat |
|---|---|
| `STOP` | Nolkan target/PWM, reset PID, nonaktifkan EN. Tetap di servis bila sedang servis. |
| `MOVE vx vy wz` | Gerak normal, hanya setelah kalibrasi dan ARM, di luar servis. Setiap nilai harus finite dan −1…1. |
| `SERVICE` | Berhenti lalu masuk mode servis. |
| `EXIT` | Berhenti lalu keluar servis ke IDLE. |
| `ZERO` | Nolkan ketiga hitungan encoder; hanya servis dan target/PWM nol. |
| `PWM motor nilai` | Servis satu motor, bilangan bulat −40…40. Tidak memerlukan CPR atau ARM. |
| `RPM motor nilai` | Servis satu motor memakai PID; konfigurasi motor harus valid dan target di dalam batas RPM-nya. Tidak memerlukan ARM. |
| `SET motor cpr maxRpm kp ki kd` | Konfigurasi RAM satu motor; hanya servis dan target/PWM nol. Membatalkan ARM. |
| `ARM` | Hanya servis, keadaan berhenti, dan ketiga konfigurasi valid. Konfirmasi operator bahwa arah dan kalibrasi sudah diverifikasi. |

Nomor motor pada wire adalah **1, 2, 3**. Rentang konfigurasi: CPR 1…10.000.000,
0 < maxRpm ≤10.000, 0 < Kp ≤1000, 0 ≤Ki/Kd ≤1000. Batas protokol tersebut bukan
rekomendasi nilai motor. Semua nilai berasal dari pengukuran/tuning.

Sumbu +X depan, +Y kiri, +wz berlawanan arah jarum jam dilihat dari atas. Untuk
sudut posisi as roda θ, target relatif adalah:

```text
u[i] = -sin(θ[i]) * vx + cos(θ[i]) * vy + wz
rpm[i] = u[i] * min(maxRpm ketiga roda) / max(1, max(abs(u)))
```

Ini antarmuka relatif, bukan kecepatan metrik: koefisien rotasi belum menggunakan
radius sasis. Perintah gabungan tetap mempertahankan rasio target roda.

Host memperbarui MOVE/PWM/RPM tiap sekitar 50 ms. Mega berhenti ketika waktu sejak
perintah gerak valid terakhir mencapai 300 ms, termasuk mode servis. Pesan tidak
valid, `SET`, `ARM`, atau pesan status tidak memperpanjang gerak. Setelah timeout,
mode DRIVE menjadi IDLE; mode SERVICE tetap SERVICE tetapi keluarannya nol.
Perintah valid berikutnya dapat memulai gerak lagi; host resmi memastikan tombol
lama tidak digunakan setelah kehilangan fokus/koneksi.

Aplikasi memberi batas tambahan 2 detik per penahanan tombol uji servis. Batas ini
berada di host; klien serial lain wajib menerapkan prosedur servisnya sendiri.

## Respons

Saat boot:

```text
BOOT OMNI1
```

Perintah non-heartbeat yang diterima menghasilkan `OK <nama-perintah>`, misalnya
`OK SERVICE`, `OK SET`, `OK ZERO`, atau `OK STOP`. MOVE/PWM/RPM yang diterima tidak
menghasilkan ACK untuk menghemat lalu lintas; perubahannya tampak di telemetri.

Penolakan menghasilkan `ERR <kode>`:

| Kode | Arti |
|---|---|
| `BAD_COMMAND` | Framing, sintaks, nilai non-finite, jumlah argumen, nomor motor, atau batas MOVE/PWM salah. |
| `SERVICE_ACTIVE` | MOVE diterima saat servis aktif. |
| `SERVICE_REQUIRED` | Perintah servis diterima di luar servis. |
| `NOT_CALIBRATED` | MOVE belum siap atau ARM dilakukan sebelum semua konfigurasi valid. |
| `STOP_REQUIRED` | ZERO/SET/ARM diminta saat target atau PWM masih aktif. |
| `BAD_CONFIG` | Data SET di luar batas valid. |
| `BAD_RPM` | Konfigurasi motor belum valid atau target melebihi batas RPM. |

TX dibatasi dan dikirim nonblocking agar host lambat tidak menghalangi watchdog.
Saat antrean penuh, respons diagnostik dapat dibuang. Aplikasi hanya mengizinkan
satu pengaturan tertunda, mencocokkan nama ACK (sehingga `OK STOP` tidak dianggap
`OK SET`), dan memutus sesi jika konfirmasi tidak tiba dalam 1 detik. Aplikasi
menghentikan gerak saat menerima ERR; firmware tidak memperpanjang timeout pada
perintah yang ditolak.

## Telemetri

Setiap sekitar 100 ms, bila antrean respons kosong:

```text
TEL millis mode ready t1 r1 c1 p1 t2 r2 c2 p2 t3 r3 c3 p3
```

- `mode`: IDLE, DRIVE, atau SERVICE.
- `ready`: 1 jika ketiga konfigurasi valid dan ARM aktif, selain itu 0.
- `t`: target RPM, `r`: RPM terukur (nol bila CPR belum tersedia).
- `c`: hitungan encoder kuadratur bertanda ×4; `p`: PWM bertanda logis −255…255,
  sebelum dikalikan `motorSign` untuk keluaran pin.
- `millis`: waktu Mega uint32; `c`: representasi int32 yang dapat wrap. Penghitungan
  selisih internal memakai aritmetika wrap sehingga kecepatan tetap dihitung.

Contoh sesi pengukuran awal tanpa data encoder:

```text
SERVICE
ZERO
PWM 1 20
STOP
EXIT
```

Ulangi PWM selama pengujian; satu pesan PWM berhenti otomatis setelah 300 ms.
Untuk kalibrasi, kirim SET masing-masing motor memakai hasil pengukuran, uji RPM
per motor, STOP, ARM, lalu EXIT. SET runtime tidak bertahan melewati reset.
