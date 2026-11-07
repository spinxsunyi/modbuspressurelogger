"""Regression test for the actual Tk WM_DELETE_WINDOW protocol while idle.

Run: .venv\\Scripts\\python.exe tests\\close_smoke.py
Uses temporary settings and database; no physical device required.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

with tempfile.TemporaryDirectory() as temp:
    os.environ['PMS_LOGGER_DATA']=temp
    Path(temp,'settings.json').write_text(json.dumps({'auto_connect':False,'mode':'Modbus RTU'}))
    from app import App

    app=App()
    try:
        app.update()
        assert not app.sid
        assert not app.connected
        # Trigger the same Tcl callback registered for the window's X button.
        wm_callback=app.tk.call('wm','protocol',app._w,'WM_DELETE_WINDOW')
        assert wm_callback, 'WM_DELETE_WINDOW handler is not registered'
        app.tk.call(wm_callback)
        assert app.closing, 'WM_DELETE_WINDOW callback did not start shutdown'
        deadline=time.monotonic()+5
        while not app._shutdown_complete and time.monotonic()<deadline:
            app.update()
            time.sleep(.02)
        assert app._shutdown_complete, 'Window did not reach shutdown completion'
        assert not app.engine.is_alive(), 'Worker thread remained active'
        log=Path(temp,'shutdown.log').read_text(encoding='utf-8')
        assert 'close requested' in log and 'worker stopped; destroying window' in log,log
        print('IDLE CLOSE PASS: X handler, worker shutdown, destroyed window')
    finally:
        if not app._shutdown_complete:app.destroy()
        if app.engine.is_alive():
            app.engine.send('quit')
            app.engine.join(timeout=3)
