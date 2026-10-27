# PMS Logger v0.1 — Prototype simulasi

Program sudah memakai tampilan desktop Python/Tkinter. Mode awal SIMULATION, sehingga tidak memerlukan PMS-970 atau adapter USB untuk menguji alurnya.

## Isi paket
- Source program (`app.py`, `core.py`, `exports.py`, `instance.py`).
- Dua rekaman contoh berlabel DEMO / Simulation di folder data.
- Contoh hasil Excel, CSV, PDF, PNG di folder examples.
- Screenshot dari program yang benar-benar dijalankan di Linux, bukan gambar desain.
- Tes otomatis dan skrip build Windows.

## Status portable
ZIP ini adalah paket SOURCE, belum berisi PMSLogger.exe.
Untuk menghasilkan aplikasi portable, build satu kali pada mesin Windows dengan Python 3.12 dan internet:
1. Ekstrak ZIP ke folder yang dapat ditulis.
2. Jalankan build_windows.bat.
3. Hasilnya PMSLogger-Windows-portable.zip.
4. Ekstrak paket hasil build di laptop pemakaian dan buka PMSLogger.exe.

Laptop pemakaian tidak perlu Python, Node, Excel, atau instalasi database. Seluruh folder hasil build harus ikut dipindahkan. Driver USB mungkin tetap dibutuhkan untuk adapter asli.

Alternatif: gunakan workflow Windows yang disertakan melalui GitHub Actions (manual workflow_dispatch) jika tidak ingin memasang Python pada laptop sendiri. Source perlu ditempatkan di root repository. Workflow belum dijalankan pada pengiriman ini.

## Cara mencoba
1. Buka aplikasi. Grafik langsung bergerak dari sensor virtual dengan siklus naik, hold, turun.
2. Tekan Record. Nama rekaman dibuat otomatis; waktu pada nama menggunakan UTC agar tidak ambigu.
3. Isi well, job, engineer, job ID dan lainnya selama recording. Perubahan disimpan otomatis.
4. Add Event menangkap waktu saat tombol ditekan, lalu kamu mengisi keterangan.
5. Centang Simulate disconnect untuk mencoba data putus. Hilangkan centang untuk melanjutkan.
6. Buka History saat masih recording: acquisition tetap berjalan.
7. Stop, lalu buka rekaman dengan Open in Viewer atau klik dua kali.
8. Atur skala atau zoom. Use current view menyalin zoom ke konfigurasi export.
9. Klik grafik untuk memilih waktu annotation; Add review annotation memberi catatan setelah job.
10. Export ke Excel, CSV, PDF atau PNG. Centang Export selected time range untuk membatasi rentang.

## Batas versi ini
- Pembacaan Modbus sudah disiapkan dari manual, tetapi belum diuji dengan meter asli.
- Belum ada executable Windows yang diuji; build Windows merupakan langkah berikutnya.
- Layout mengikuti konsep, belum identik dengan mockup.
- Pan/zoom dan range angka tersedia; slider overview timeline belum dibuat.
- PDF berupa laporan satu halaman, belum report designer lengkap.
- Annotation bisa digeser secara visual; posisi label hasil geser belum disimpan ke export.
- Unit hanya label dan harus sesuai unit meter; belum ada konversi otomatis.

Lihat README.md untuk detail teknis, pengujian, dan checklist koneksi alat.
