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
a.settings['mode']='Simulation'
a.settings['interval']=.1
a.connect()  # Default production mode is Modbus; smoke test explicitly selects simulation.
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
    a.live_min.set('0');a.live_max.set('3000');a.apply_live_scale();assert a.lax.get_ylim()==(0,3000)
    a.slide_live(0);assert not a.follow.get();a.follow.set(True)
    # A native scrollbar replaces the miniature pressure plot.
    assert a.live_slider.winfo_class()=='TScrollbar'
    assert a.history_slider.winfo_class()=='TScrollbar'
    a.live_slider.on_scroll('moveto','0')
    assert not a.follow.get()
    a.follow.set(True)
    a.show_live_options();pump(.1)
    assert a.live_options.winfo_exists()
    a.live_options.destroy()
    a.paint_live_events();assert len(a.live_events.get_children())==1
    # Chart-focused layout: event list starts hidden and can be expanded on demand.
    assert not a.events_expanded
    assert not a.live_events.winfo_manager()
    assert a.live_chart_tools.winfo_manager()=='pack'
    a.toggle_live_events();pump(.1)
    assert a.events_expanded and a.live_events.winfo_manager()=='pack'
    assert 'Events (1)' in a.live_event_toggle.cget('text')
    a.toggle_live_events();pump(.1)
    assert not a.events_expanded and not a.live_events.winfo_manager()
    a.toggle_details();a.toggle_details();pump(.2)
    # Compact-window layout must remain operational and restore the metadata panel.
    a.geometry('850x600');pump(.3)
    assert a.compact
    assert str(a.details_panel) not in a.live_pane.panes()
    a.geometry('1280x820');pump(.3)
    assert not a.compact
    assert str(a.details_panel) in a.live_pane.panes()
    # Notes widget is editable when a recording has loaded.
    assert str(a.notes.cget('state')) == 'normal'
    a.notes.insert('end','UI NOTES')
    a.notes.edit_modified(True);a.notes.event_generate('<<Modified>>')
    pump(.8)
    assert 'UI NOTES' in json.loads(a.store.get(sid)['details'])['notes']
    a.engine.send('drop',True);pump(.7);assert a.latest['quality']=='TIMEOUT'
    a.engine.send('drop',False);pump(.7);assert a.latest['quality']=='OK'
    a.show('History');pump(.3);assert a.sid==sid
    a.show('Settings');pump(.3);assert a.sid==sid
    # Settings must remain scrollable at the supported minimum window size.
    a.geometry('820x560');pump(.3)
    assert a.settings_canvas.winfo_ismapped()
    assert a.settings_canvas.cget('yscrollcommand')
    assert float(a.settings_canvas.cget('height')) >= 0
    a.settings_canvas.yview_moveto(1)
    pump(.1)
    assert a.settings_canvas.yview()[1] > 0.95
    a.geometry('1280x820');pump(.3)
    a.show('Live Monitor');a.record();pump(.4);assert not a.sid
    a.load_viewer(sid);pump(.4);a.history_window.set('1 min');a.slide_history(0);a.history_labels.set(False);a.paint_viewer();a.history_labels.set(True);a.view_vars['ymax'].set('3000');a.apply_view();a.capture_view();pump(.2)
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
