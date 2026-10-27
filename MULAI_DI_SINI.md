# PMS Logger v0.1 — Prototype simulasi

Program memakai tampilan desktop Python/Tkinter. Mode awal SIMULATION, sehingga tidak memerlukan PMS-970 atau adapter USB untuk menguji alurnya.

## Isi repository
- Source program (`app.py`, `core.py`, `exports.py`, `instance.py`).
- Skrip `seed_demo.py untuk membuat database dan dua rekaman contoh DEMO / Simulation.
- Tes otomatis dan skrip build Windows.
- Workflow Windows melalui GitHub Actions.

Database demo dan hasil export tidak disimpan di repository. Jalankan `python seed_demo.py` untuk membuat database contoh.

## Status portable
Repository ini berisi source, belum berisi PMSLogger.exe.
Untuk menghasilkan aplikasi portable, build satu kali pada mesin Windows dengan Python 3.12 dan internet:
1. Clone atau unduh repository, lalu buka foldernya.
2. Jalankan `build_windows.bat`. Skrip ini membuat database demo sebelum build.
3. Hasilnya `dist/PMSLogger-Windows-portable.zip`.
4. Ekstrak paket hasil build di laptop pemakaian dan buka `PMSLogger.exe`.

Laptop pemakaian tidak perlu Python, Node, Excel, atau instalasi database. Seluruh folder hasil build harus ikut dipindahkan. Driver USB mungkin tetap dibutuhkan untuk adapter asli.

Alternatif: gunakan workflow Windows yang disertakan melalui GitHub Actions (manual workflow_dispatch) jika tidak ingin memasang Python pada laptop sendiri. Workflow belum dijalankan.

## Cara mencoba
1. Jalankan `python seed_demo.py` untuk membuat database berisi rekaman demo.
2. Buka aplikasi. Grafik langsung bergerak dari sensor virtual dengan siklus naik, hold, turun.
3. Tekan Record. Nama rekaman dibuat otomatis; waktu pada nama menggunakan UTC agar tidak ambigu.
4. Isi well, job, engineer, job ID dan lainnya selama recording. Perubahan disimpan otomatis.
5. Add Event menangkap waktu saat tombol ditekan, lalu kamu mengisi keterangan.
6. Centang Simulate disconnect untuk mencoba data putus. Hilangkan centang untuk melanjutkan.
7. Buka History saat masih recording: acquisition tetap berjalan.
8. Stop, lalu buka rekaman dengan Open in Viewer atau klik dua kali.
9. Atur skala atau zoom. Use current view menyalin zoom ke konfigurasi export.
10. Klik grafik untuk memilih waktu annotation; Add review annotation memberi catatan setelah job.
11. Export ke Excel, CSV, PDF atau PNG. Centang Export selected time range untuk membatasi rentang.

## Batas versi ini
- Pembacaan Modbus sudah disiapkan dari manual, tetapi belum diuji dengan meter asli.
- Belum ada executable Windows yang diuji; build Windows merupakan langkah berikutnya.
- Layout mengikuti konsep, belum identik dengan mockup.
- Pan/zoom dan range angka tersedia; slider overview timeline belum dibuat.
- PDF berupa laporan satu halaman, belum report designer lengkap.
- Annotation bisa digeser secara visual; posisi label hasil geser belum disimpan ke export.
- Unit hanya label dan harus sesuai unit meter; belum ada konversi otomatis.

Lihat README.md untuk detail teknis, pengujian, dan checklist koneksi alat.
