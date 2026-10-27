"""End-to-end Tk smoke check; run with an available display. Uses temp data."""
import os,sys,tempfile,time,json,traceback
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
tmp=tempfile.TemporaryDirectory();os.environ['PMS_LOGGER_DATA']=tmp.name
from seed_demo import seed
seed(Path(tmp.name)/'recordings.sqlite')
from app import App
from tkinter import messagebox, simpledialog
errors=[]
messagebox.showerror=lambda *a,**k:errors.append(str(a))
messagebox.showinfo=lambda *a,**k:None
messagebox.askyesno=lambda *a,**k:True
simpledialog.askstring=lambda *a,**k:'Smoke-test event'
a=App()
a.report_callback_exception=lambda *exc:errors.append(''.join(traceback.format_exception(*exc)))
def pump(seconds=.5):
    until=time.monotonic()+seconds
    while time.monotonic()<until:a.update();time.sleep(.02)
try:
    pump(1.2);assert a.latest and a.latest['quality']=='OK'
    a.record();pump(.5);assert a.sid
    sid=a.sid;a.detail_vars['well'].set('UI TEST');pump(.8)
    assert json.loads(a.store.get(sid)['details'])['well']=='UI TEST'
    a.add_live_event();assert len(a.store.events(sid))==1
    a.toggle_details();a.toggle_details();pump(.2)
    a.engine.send('drop',True);pump(.7);assert a.latest['quality']=='TIMEOUT'
    a.engine.send('drop',False);pump(.7);assert a.latest['quality']=='OK'
    a.show('History');pump(.3);assert a.sid==sid
    a.show('Settings');pump(.3);assert a.sid==sid
    a.show('Live Monitor');a.record();pump(.4);assert not a.sid
    a.load_viewer(sid);pump(.4);a.view_vars['ymax'].set('3000');a.apply_view();a.capture_view();pump(.2)
    assert a.store.get(sid)['state']=='Completed'
    # Produce actual UI screenshots, using seeded two-minute recording for viewer.
    out=Path(__file__).resolve().parents[1]/'screenshots';out.mkdir(exist_ok=True)
    from PIL import ImageGrab
    demo=next(s for s in a.store.sessions() if 'DEMO' in s['details'])
    for page,name in [('Live Monitor','live'),('History','history'),('Settings','settings'),('Viewer','viewer')]:
        if page=='Viewer':a.load_viewer(demo['id'])
        else:a.show(page)
        pump(.4)
        import io
        b=io.BytesIO();ImageGrab.grab(xdisplay=os.environ.get('DISPLAY')).crop((0,0,a.winfo_width(),a.winfo_height())).save(b,format='PNG')
        (out/(name+'.png')).write_bytes(b.getvalue())
        assert (out/(name+'.png')).stat().st_size>1000
        print(name,len(b.getvalue()),flush=True)
    assert not errors,errors
    a.close();pump(.3)
    print('UI SMOKE PASS: launch, connect, record, autosave, event, disconnect/recover, navigation, stop, viewer, close')
finally:
    if a.engine.is_alive():a.engine.send('quit');a.engine.join(3)
    tmp.cleanup()
