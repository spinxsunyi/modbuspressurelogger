# Validation — v0.1

Environment: Linux, Python 3.12.14, Tk 9.0 with virtual X display, Matplotlib 3.10.8.

Automated core tests: 6 passed.
- Signed integer and decimal position decoding; underrange and overrange flags.
- Threaded simulator recording, disconnection null samples, reconnection and clean stop.
- Database reopening, selected-range export, CSV/XLSX/PNG/PDF outputs and interrupted-session recovery.
- Plot reduction retains a pressure peak and missing-data marker.
- Injected disk failure stops recording with Storage error state.
- Second instance lock rejected; lock released for subsequent opening.

GUI smoke test: passed.
- Startup and auto-connect simulator.
- One-click recording and metadata autosave to SQLite.
- Event captured, details panel collapse/expand.
- Simulated dropout and recovery.
- Navigation to History and Settings while recording continues.
- Stop, open Viewer, change/save scales and clean shutdown.
- Four actual application screenshots captured and reviewed.

Not validated: Windows executable, real serial device or loopback, multi-hour soak, OS sleep/resume,
Windows DPI scaling, exact resource footprint, and field deployment.

This is an engineering prototype for user review, not a commissioned measurement system.
