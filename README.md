# PMS Logger

Python/Tkinter prototype for reading the Aplisens PMS-970 pressure indication over USB–RS485 (Modbus RTU). It starts in SIMULATION mode and can be exercised without the meter.

## Run from source

Requires Python 3.12 with Tk support.

```powershell
py -3.12 -m venv .venv
.venv\\Scripts\\Activate.ps1
python -m pip install -r requirements.txt
python seed_demo.py  # optional: create demo sessions in data/recordings.sqlite
python app.py
```

On Windows, run `build_windows.bat` to create a portable `dist/PMSLogger` folder and ZIP. Building requires internet once. The target laptop does not need Python installed. The USB adapter may need its CH343 driver.

## App workflow

- Live Monitor opens directly, connects to the virtual sensor by default, and plots readings.
- Record starts a session with an automatic ID. Job details autosave while recording.
- Add Event records the button-click time before asking for its label.
- History and Viewer remain usable while an acquisition continues.
- Viewer supports pan/zoom, manual axis limits, annotations, and CSV/XLSX/PDF/PNG export.
- SQLite saves each sample. Failed readings are null quality-marked rows so graph gaps remain visible.

## PMS-970 profile

Read-only Modbus RTU FC03, holding-register wire address `0x0001`, count 2 (display value + status), slave ID and serial format configured in Settings. The decoder handles signed 16-bit values, decimal-position bits, underrange, overrange and busy flags. Profile comes from the supplied PMS-970 manual, EN.IO.PMS-970 rev. 01.A.002/2019.10, printed page 23.

Hardware reads, exact COM settings, adapter wiring, and long-run timing still need bench validation with the arriving adapter and instrument. Begin at 0.5 seconds. The displayed unit is a label and must match the meter's scale; this prototype does not convert units or write device settings.

## Validation

Six automated tests cover register decoding, disconnect/reconnect recording, persistence, output files, plot extrema/gaps, storage failure and single-instance locking. A Linux virtual-display GUI smoke test exercised recording, autosave, events, recovery, navigation, viewer and shutdown. Windows packaging and real hardware remain unvalidated. See `TEST_RESULTS.md` for scope and limits.

## Files

- `app.py`: Tk desktop views and user actions
- `core.py`: serial/simulation sources, acquisition thread and SQLite
- `exports.py`: CSV, Excel, PDF and PNG output
- `seed_demo.py`: optional synthetic history data
- `build_windows.bat`: portable Windows package
- `.github/workflows/windows.yml`: manual Windows build workflow
