# Kalibrasi PG45 dan tuning kecepatan

Lakukan tahap ini dengan roda terangkat. Tidak ada nilai CPR, rasio gearbox,
tegangan encoder, atau gain PID yang diasumsikan dari nama PG45.

## 1. Identifikasi encoder dan ukur CPR

1. Cari kode lengkap motor/encoder, pinout, serta spesifikasi listriknya. Cocokkan
   suplai dan level sinyal sebelum menghubungkan A/B ke Mega.
2. Sambung aplikasi, pilih tab **Servis & kalibrasi**, lalu **Masuk servis**.
   Tunggu status `SERVICE` dan pesan `Diterima Mega: SERVICE`.
3. Tanpa menjalankan motor, **Nolkan hitungan**. Tunggu pesan `Diterima Mega: ZERO`
   dan telemetri nol. Tandai poros keluaran atau roda.
4. Putar poros keluaran tepat beberapa putaran penuh dengan tangan jika mekanik
   memungkinkan. CPR = nilai absolut selisih hitungan / jumlah putaran.
   Contohnya, angka yang dimasukkan adalah hasil pengukuran Anda sendiri, bukan
   PPR encoder mentah. Ulangi untuk memastikan konsisten.
5. Firmware menghitung semua edge A dan B (×4). Jika data pabrikan menyebut PPR
   sebelum gearbox, pastikan definisinya sebelum mengalikan faktor ×4 dan rasio
   gearbox. Jangan mengalikan ×4 lagi pada pengukuran langsung di atas.

Tanpa CPR, kolom RPM tetap nol tetapi kolom encoder tetap melaporkan hitungan
mentah. Putaran tangan saat EN nonaktif tetap terbaca.

## 2. Verifikasi arah

Pilih motor dan nilai PWM rendah (awal aplikasi 20 dari 255). Tahan **PWM +**;
lepaskan untuk berhenti. Satu penahanan dibatasi 2 detik dan PWM maksimal 40.
Jika motor belum bergerak, periksa suplai/beban dan naikkan secara bertahap dalam
batas servis; jangan menyalin nilai PWM servis menjadi gain PID.

Arah fisik positif yang dipakai kinematika adalah arah tangensial berlawanan
jarum jam mengelilingi pusat robot, dilihat dari atas. Sesuaikan `motorSign` menjadi
`1` atau `-1` untuk setiap motor di `include/robot_config.h`, kemudian upload ulang.
Saat motor positif bergerak ke arah tersebut, hitungan encoder harus bertambah.
Jika berkurang, ubah `encoderSign` motor itu menjadi `-1`, kemudian upload ulang.
Sesudah upload, sambungkan ulang aplikasi dan ulangi verifikasi.

Jangan menguji PID sebelum arah encoder cocok dengan arah motor. Firmware tahap
ini belum mendeteksi encoder terputus atau motor macet; umpan balik yang salah
dapat membuat PID terus meminta PWM besar.

## 3. Masukkan konfigurasi dan ukur batas kecepatan

Dalam servis dan keadaan berhenti, isi lima kolom lalu **Terapkan ke RAM**:

- **CPR ×4:** hitungan untuk satu putaran poros keluaran yang sudah diukur.
- **Batas RPM:** batas konservatif untuk pengujian awal, berdasarkan spesifikasi
  varian motor atau pengukuran RPM pada kondisi suplai/beban yang dipakai.
- **Kp:** gain P positif yang dipilih untuk uji awal; mulai kecil.
- **Ki, Kd:** mulai dari nol.

Ulangi untuk M1–M3. `SET` berlaku hanya bagi motor terpilih; kolom isian tidak
secara otomatis membaca konfigurasi motor lain. Catat hasil setiap motor secara
terpisah. `SET` yang diterima akan membatalkan ARM sebelumnya.

Saat CPR sudah diterapkan, RPM muncul di telemetri. Gunakan PWM servis untuk
mengamati RPM rendah dan konsistensi encoder. Batas RPM final perlu diverifikasi
pada rentang kerja sebenarnya; PWM servis 40 bukan pengukuran kecepatan penuh.
Naikkan batas RPM uji dan target secara bertahap saat tuning sudah stabil.

## 4. Tuning PID satu roda

1. Pilih motor. Isi RPM uji rendah di bawah batasnya; tekan-tahan **RPM +** atau
   **RPM −**. Mode servis hanya menjalankan motor tersebut.
2. Bandingkan target dan RPM aktual. Naikkan Kp secara bertahap sampai mengikuti
   target tanpa osilasi berlebih. Lepas tombol sebelum mengubah konfigurasi.
3. Tambahkan Ki bertahap untuk mengurangi galat menetap. Kd boleh tetap nol;
   pembacaan encoder 10 ms dapat berisik pada hitungan rendah.
4. Uji kedua arah, beberapa target, pelepasan tombol, dan perpindahan target.
   Ulangi pada ketiga roda dan dengan kondisi beban yang sesuai sebelum uji cepat.
5. Catat CPR, batas RPM stabil, Kp, Ki, Kd, serta kedua tanda arah setiap motor.

Keluaran PID adalah PWM bertanda −255 sampai 255. Satuan Kp adalah PWM/RPM, Ki
adalah PWM/(RPM·detik), Kd adalah PWM·detik/RPM. Derivative dihitung terhadap
pengukuran agar perubahan target tidak menghasilkan derivative kick. Integral
dibatasi dan tidak ditambah ketika memperparah saturasi. STOP menghapus integral.
Target nol menonaktifkan penggerak, tidak melakukan pengereman PID.

RPM dihitung dari selisih encoder dan waktu sebenarnya setiap interval kontrol.
Jika encoder beresolusi rendah membuat RPM kasar, evaluasi `ControlMs` dan tuning
berdasarkan pengukuran; jangan menganggap encoder rusak hanya karena kuantisasi.

## 5. ARM, simpan hasil, dan uji arah

Ketika ketiga motor sudah diverifikasi, berhenti lalu klik **ARM: kalibrasi
terverifikasi**, konfirmasikan, dan tunggu `OK ARM`. Keluar servis, pilih tab
keyboard, lepaskan semua tombol arah, dan uji W/S/A/D dengan kecepatan rendah.

Salin data final ke `CalibrationData` di `include/robot_config.h`, sesuai urutan:

```cpp
// {cpr, maxRpm, kp, ki, kd} -- isi semua dengan hasil pengukuran masing-masing.
```

Nilai awal nol memang tidak valid. Konfigurasi runtime tidak ditulis ke EEPROM dan
hilang saat reset (termasuk reset akibat membuka port). Dengan data final di header,
`CalibrationConfirmed=false` tetap memerlukan masuk servis → ARM → keluar servis
setiap sesi baru. Ubah menjadi `true` hanya jika data dan arah final sudah
terverifikasi dan Anda memang ingin status siap saat boot. Status siap sendiri
tidak menggerakkan robot; host masih membutuhkan penekanan tombol baru.

Uji di lantai setelah uji roda terangkat lulus. Untuk maju, M1 diam, M2 positif,
M3 negatif. Untuk putar kiri, ketiga target positif. Bila arah berbeda, cocokkan
posisi, sudut, tanda motor, dan tanda encoder sebelum menaikkan kecepatan.
