# Digital Pressure Recorder — Application Workflow & Code Guide

**Version:** 1.0 (November 2026)  
**Platform:** Windows 11 · Python 3.12 · Tkinter  
**Repository:** `spinxsunyi/modbuspressurelogger`

This is developer-oriented documentation of the current application. It complements the user-facing root `README.md` (which mirrors the in-app About page).

## 1. What the application does

Digital Pressure Recorder monitors an Aplisens PMS-970 over USB–RS485 / Modbus RTU, or uses its built-in pressure simulator. It shows a live trend, records time-stamped samples to SQLite, attaches job metadata and events, lets operators review history, and exports data and reports. Hardware access is **read-only**.

### High-level architecture

```text
PMS-970 -- USB/RS485 -- ModbusSource ----+
                                         |     Engine (background thread)
Simulator -------------------------------+----> acquisition messages
                                                    |
                                                    v
                                            App (Tkinter UI)
                                                    |
                               +--------------------+-------------------+
                               v                                        v
                         Store (SQLite)                           Live chart/status
                       sessions/samples/events                          |
                               |                                         |
                               +--> History / Viewer / Reporting <-------+
                                              |
                                              v
                                        exports.py
                                   CSV / XLSX / PDF / image
```

The UI must not block on serial reads or long-running database operations. `core.py` intentionally has no GUI dependencies.

## 2. Operator workflow

1. **Launch** — The app loads defaults and any saved settings, opens/initializes the SQLite database, recovers unfinished sessions as `Interrupted`, starts the acquisition engine, and displays Live Monitor.
2. **Configure** — In Settings choose **Simulation** or **Modbus RTU**. For hardware, select COM port, baud rate, parity, stop bits, slave address, sampling interval, display unit, and UTC offset. The Help page contains a connection checklist.
3. **Connect** — Connect to the simulated source or the PMS-970. Verify the connection indicator and plausible live pressure before recording. Serial/Modbus errors must not be mistaken for valid measurements.
4. **Record** — Start a session. The app creates a session ID and records timestamped samples, quality, and available raw/status/latency information. Enter well/job/operator details as needed.
5. **Annotate** — Add operational events while recording. Event timestamps are retained for review. Viewer annotations can also be added/edited/deleted later.
6. **Stop** — End recording. Completed sessions remain available in History.
7. **Review** — Open History, select a recording, and inspect the Viewer graph, annotations, job details, pressure statistics, time window, pan/zoom, and scale.
8. **Report/export** — Select a recording in Reporting, configure the range and presentation, then export. The Viewer also exposes exports. Check exported time zone, range, units, and resolution.
9. **Exit/reopen** — Stored recordings persist across application restarts; unfinished sessions are marked Interrupted on next startup.

### Page responsibilities

| Page | Main responsibility |
| --- | --- |
| Live Monitor | Connection, live pressure/trend, start/stop recording, live events, chart controls |
| History | Find/select/delete recordings and open Viewer or Reporting |
| Viewer | Inspect saved trends, change time/pressure view, pan/zoom, manage annotations, export |
| Reporting | Choose recording, metadata, time range, chart/report settings, preview, export |
| Settings | Modbus/Simulation source and acquisition/display preferences |
| Help | Hardware connection and configuration checklist |
| About | Product description, supported device, status legend, developer information |

## 3. Files and code responsibilities

| Path | Role |
| --- | --- |
| `app.py` | Tkinter entry point, UI layout, navigation, status polling, charts, user actions, history/viewer/reporting workflow |
| `core.py` | Default settings, PMS-970 register decoding, simulator, Modbus client, SQLite Store, background Engine |
| `exports.py` | CSV/XLSX/PDF/image output, chart rendering, timestamp formatting, export range/resolution logic |
| `app_icon.py` | Draws the navy/teal gauge, sets Tk window icon, generates Windows `.ico` for packaging |
| `seed_demo.py` | Creates synthetic example recordings for development/testing; **not** required for normal user startup |
| `requirements.txt` | Python runtime dependencies |
| `build_windows.bat` | Local Windows virtual environment, PyInstaller build, folder/ZIP packaging |
| `.github/workflows/windows.yml` | GitHub Actions Windows build, tests, icon generation, ZIP verification, SHA256 artifact |
| `README.md` | Public-facing product overview, matching the About page |
| `docs/APP_WORKFLOW_AND_CODE_GUIDE.md` | This workflow and code-maintenance guide |

### `app.py` key areas

- `App.__init__`: initializes settings, Store and Engine, creates pages and status/navigation.
- `make_live`, `connect`, `record`, `add_live_event`, `tick`: monitoring, connection state, recording and periodic UI updates.
- `make_history`, `refresh_history`, `open_selected`: recording list and navigation.
- `make_viewer`, `load_viewer`, `paint_viewer`, `chart_tools`, `chart_click`: saved chart and pan/zoom/annotation interaction.
- `add_annotation`, `edit_annotation`, `delete_annotation`, `annotation_pressure`: event management and nearest-valid-sample pressure lookup.
- `make_reporting`, `show_report_step`, `export_reporting`: multi-step reporting and output.
- `make_settings`, `apply_settings`, `make_help`, `make_about`: configuration and reference pages.
- `close`: application shutdown and resource cleanup.

### `core.py` key areas

- `DEFAULTS` and `FIELDS`: acquisition preferences and session metadata fields.
- `decode(registers)`: decodes the PMS-970's two registers into pressure, quality, raw value, and status.
- `Simulator`: deterministic simulated pressure profile and simulated disconnect.
- `ModbusSource`: PyModbus serial connection and read of two holding registers at wire address 1, with configured slave ID.
- `Store`: creates/updates SQLite schema and provides session, sample, event, statistics and plot-data operations.
- `Engine`: background acquisition/command thread; communicates results to the UI.

### `exports.py` key areas

- `stamp(ts, offset)`: formats timestamps using the configured UTC offset.
- `figure(...)`: creates an export chart with event markers.
- `export(...)`: obtains a consistent database snapshot and writes the requested output through a temporary `.partial` file.

## 4. Database and file storage

By default, the packaged app uses a `data` directory **beside the executable**; when running from source, it uses `data` beside `app.py`. The `PMS_LOGGER_DATA` environment variable can override this path.

```text
DigitalPressureRecorder/
├── DigitalPressureRecorder.exe
├── _internal/                 # PyInstaller support files (onedir build)
├── README.md
└── data/                      # Created automatically if missing and writable
    ├── recordings.sqlite
    └── settings.json          # Written when settings are saved
```

SQLite tables:

| Table | Purpose |
| --- | --- |
| `sessions` | Session ID/name, start/end, state, acquisition settings, job details, saved view |
| `samples` | Session ID, timestamp, elapsed time, pressure, quality, raw/status registers, latency |
| `events` | Session ID, event time, label/type, created/modified timestamps |

SQLite uses **WAL mode**; when backing up a running database, account for `-wal` and `-shm` files or use SQLite's backup API. The safest simple manual copy is after fully closing the application. The default data folder must be writable.

**Distribution caution:** Current local and GitHub build scripts run `seed_demo.py` and copy `data/` into the packaged output. Thus a built ZIP may include synthetic recordings. For a clean release, remove demo seeding/data copying from packaging or explicitly clean the distribution database. Merely omitting `data/` from the final distribution is supported: Store creates the folder and schema at first launch.

## 5. Pressure values, time and sample quality

- The device and simulator produce **PSI** source values. The Store records the original PSI values; display-unit conversion belongs in the UI. Do not relabel stored PSI as another unit.
- `samples.ts` stores an absolute timestamp; the configured UTC offset controls presentation/export formatting.
- Quality flags (for example `OK`, `UNDERRANGE`, `OVERRANGE`, `BUSY` or failures) must be preserved. Invalid readings must not be graphed as valid pressure.
- The configured acquisition interval defaults to **0.5 seconds**, but actual timing must be validated under real serial hardware and system load.
- Exporting **All Data** preserves original stored sample rows. Reduced-resolution export selects actual samples by time interval; it does **not** average or interpolate readings.
- The Viewer's annotation pressure field finds the nearest valid stored sample, which may not coincide exactly with the event timestamp. Interpret with care if readings are sparse or interrupted.
- Viewer `All data` means the complete recording time range; plotting may be optimized and should not be confused with an unmodified row-by-row export.

## 6. Building and running

### Development (Windows PowerShell)

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe app.py
```

### Windows portable EXE

- **GitHub Actions:** Manually run `.github/workflows/windows.yml`; it runs tests, generates `assets/pressure_gauge.ico`, builds PyInstaller `--onedir` with `--icon`, verifies ZIP members, and publishes a SHA256 checksum.
- **Local:** Run `build_windows.bat`; note that, at the time of writing, the local batch file does **not** specify the custom `--icon` argument, unlike GitHub Actions.
- Distribute the **entire** PyInstaller `DigitalPressureRecorder` directory (including `_internal`), not the EXE alone. A target machine does not need a Python installation.
- The built `README.md` is copied from the repository root and mirrors the in-app About page.

## 7. Validation priorities before v1.0 release

1. Confirm real PMS-970 register decoding, port settings, USB disconnect/reconnect, and valid/invalid sample quality.
2. Run multi-hour 0.5-second recordings; compare timestamps, row counts, data gaps, UI responsiveness, and restart recovery.
3. Cross-check stored SQLite pressure/timestamps against History, annotations, CSV and Excel All Data exports.
4. Verify Pan/Zoom/Reset and right-click annotations with Pan inactive, at Windows 150% scaling.
5. Test fresh portable install **without** bundled `data/`, as well as an upgrade retaining an existing database.
6. Verify EXE gauge icon, README contents, ZIP integrity, and behavior on a separate Windows PC.

## 8. Maintenance conventions

- Preserve recorded sample values and acquisition semantics during UI refactoring.
- Keep serial I/O and persistence in `core.py`; UI concerns in `app.py`; file rendering/export in `exports.py`.
- Test with Simulation first, then real hardware. Never treat simulator results as hardware validation.
- Keep the About page and packaged README synchronized when product information changes.
- Update this guide when workflows, storage schema, build packaging or major code responsibilities change.
