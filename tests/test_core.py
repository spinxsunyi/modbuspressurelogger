import json, time, sys, zipfile, sqlite3
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Store,Engine,DEFAULTS,decode
from exports import export

def test_decode():
    assert decode([1234,0])[0]==1234
    assert decode([1234,1<<12])[0]==1.234
    assert decode([1234,2<<12])[0]==12.34
    assert decode([65526,3<<12])[0]==-1
    assert decode([1,16])[1]=='UNDERRANGE'
    assert decode([1,32])[1]=='OVERRANGE'

def wait(engine,kind,timeout=3):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        name,data=engine.messages.get(timeout=timeout)
        if name==kind:return data
    raise AssertionError(kind)

def test_record_disconnect_recovery(tmp_path):
    store=Store(tmp_path/'db'); e=Engine(store);e.start()
    try:
        e.send('connect',{**DEFAULTS,'mode':'Simulation','interval':.1});wait(e,'sample');e.send('start');sid=wait(e,'started')['sid']
        wait(e,'sample');e.send('drop',True);time.sleep(.25);e.send('drop',False);time.sleep(.25)
        e.send('stop');wait(e,'stopped');rows=store.plot_rows(sid)
        assert any(r['quality']=='TIMEOUT' and r['value'] is None for r in rows)
        assert rows[-1]['quality']=='OK'; assert store.get(sid)['state']=='Completed'
        assert all(b['ts']>a['ts'] for a,b in zip(rows,rows[1:]))
    finally:e.send('quit');e.join(3)

def test_persistence_and_exports(tmp_path):
    st=Store(tmp_path/'db');sid=st.start(DEFAULTS,1000)
    for i in range(10):st.add_sample(sid,dict(ts=1000+i*.5,elapsed=i*.5,value=i if i!=4 else None,quality='OK' if i!=4 else 'TIMEOUT',raw=None,status=None,latency=.01))
    st.update(sid,'details',{'well':'=DANGEROUS()','engineer':'Eka'})
    st.event(sid,1002,'Hold','Review');st.finish(sid)
    st2=Store(tmp_path/'db');assert st2.stats(sid)['n']==10
    view=dict(title='Simulation test',xmin=0,xmax=.1,ymin=0,ymax=10)
    for ext in ['csv','xlsx','png','pdf']:
        dest=tmp_path/('test.'+ext);export(st,sid,dest,view);assert dest.stat().st_size>200
    with zipfile.ZipFile(tmp_path/'test.xlsx') as z:assert b'<f>' not in z.read('xl/worksheets/sheet1.xml')
    export(st,sid,tmp_path/'range.csv',{**view,'xmin':.025,'xmax':.05},True)
    import csv
    with open(tmp_path/'range.csv',encoding='utf-8-sig') as f:assert len(list(csv.reader(f)))==5
    interrupted=st.start(DEFAULTS);st.recover();assert st.get(interrupted)['state']=='Interrupted'

def test_plot_retains_peak_and_gap(tmp_path):
    st=Store(tmp_path/'db');sid=st.start(DEFAULTS,0)
    for i in range(300):st.add_sample(sid,dict(ts=i,elapsed=i,value=9999 if i==123 else None if i==124 else 0,quality='TIMEOUT' if i==124 else 'OK',raw=None,status=None,latency=0))
    rows=st.plot_rows(sid,30)
    assert any(r['value']==9999 for r in rows)
    assert any(r['value'] is None for r in rows)
    assert len(rows)<=30

def test_storage_failure_stops_recording(tmp_path):
    st=Store(tmp_path/'db');e=Engine(st);e.start()
    def fail(*a):raise OSError('disk full')
    try:
        e.send('connect',{**DEFAULTS,'mode':'Simulation','interval':.1});wait(e,'sample');e.send('start');sid=wait(e,'started')['sid'];st.add_sample=fail
        wait(e,'storage_error');assert e.sid is None;assert st.get(sid)['state']=='Storage error'
    finally:e.send('quit');e.join(3)

def test_second_instance_rejected(tmp_path):
    from instance import InstanceLock
    import pytest
    lock=InstanceLock(tmp_path/'lock')
    with pytest.raises(RuntimeError):InstanceLock(tmp_path/'lock')
    lock.close();second=InstanceLock(tmp_path/'lock');second.close()

def test_delete_annotation_and_recording(tmp_path):
    st=Store(tmp_path/'db')
    sid=st.start(DEFAULTS,1000)
    sample=dict(ts=1001,elapsed=1,value=1200,quality='OK',raw=None,status=None,latency=.01)
    st.add_sample(sid,sample)
    st.event(sid,1001,'RIH','Review')
    event=st.events(sid)[0]
    assert not st.delete_event(event['id'],'wrong-session')
    assert len(st.events(sid))==1
    assert st.delete_event(event['id'],sid)
    assert st.events(sid)==[]
    st.event(sid,1001,'POOH','Review')
    import pytest
    with pytest.raises(ValueError,match='active'):
        st.delete_session(sid)
    assert st.get(sid) is not None
    st.finish(sid)
    assert st.delete_session(sid)
    assert st.sessions()==[]
    assert st.stats(sid)['n']==0
    assert st.events(sid)==[]
    assert not st.delete_session(sid)

def test_canonical_psi_storage_and_display_conversion(tmp_path):
    import pytest
    from units import from_psi,to_psi
    assert from_psi(5000,'psi')==5000
    assert from_psi(5000,'bar')==pytest.approx(344.738,rel=1e-5)
    assert from_psi(5000,'kPa')==pytest.approx(34473.786,rel=1e-5)
    assert from_psi(5000,'MPa')==pytest.approx(34.4738,rel=1e-5)
    for unit in ('psi','bar','kPa','MPa'):
        assert to_psi(from_psi(5000,unit),unit)==pytest.approx(5000)

    st=Store(tmp_path/'data.sqlite')
    sid=st.start({**DEFAULTS,'unit':'kPa'},1000)
    assert st.get(sid)['unit']=='psi'
    st.add_sample(sid,dict(ts=1001,elapsed=1,value=5000.0,quality='OK',raw=5000,status=0,latency=.01))
    st.finish(sid)
    assert st.plot_rows(sid)[0]['value']==5000.0  # Never convert stored samples.
    csv_path=tmp_path/'pressure.csv'
    export(st,sid,csv_path,dict(xmin=0,xmax=1,ymin=0,ymax=5100))
    import csv
    with csv_path.open(encoding='utf-8-sig',newline='') as stream:
        # Export includes three provenance rows and a blank line before the CSV header.
        header=next(i for i,line in enumerate(stream) if line.startswith('timestamp,'))
        stream.seek(0)
        rows=list(csv.DictReader(list(stream)[header:]))
    assert rows[0]['pressure']=='5000.0'
    assert rows[0]['unit']=='psi'

def test_legacy_unit_metadata_migration_preserves_values(tmp_path):
    db=tmp_path/'legacy.sqlite'
    st=Store(db)
    sid=st.start({**DEFAULTS,'unit':'kPa'},1000)
    st.add_sample(sid,dict(ts=1001,elapsed=1,value=5000.0,quality='OK',raw=5000,status=0,latency=.01))
    with st.connect() as c:
        c.execute("UPDATE sessions SET unit='kPa' WHERE id=?",(sid,))
    reopened=Store(db)
    assert reopened.get(sid)['unit']=='psi'
    assert reopened.plot_rows(sid)[0]['value']==5000.0


def test_demo_seed_first_launch_only(tmp_path):
    from seed_demo import seed
    import json
    db = tmp_path / 'data' / 'recordings.sqlite'
    seed(db)
    store = Store(db)
    sessions = store.sessions()
    assert len(sessions) == 2
    assert all(s['state'] == 'Completed' and s['mode'] == 'Simulation' for s in sessions)
    for session in sessions:
        details = json.loads(session['details'])
        assert details['job_id'].startswith('DEMO-')
        assert 'SYNTHETIC' in details['notes'].upper()
        assert store.stats(session['id'])['n'] == 2991
        assert len(store.events(session['id'])) == 8
    original_ids = {s['id'] for s in sessions}
    seed(db)
    assert {s['id'] for s in Store(db).sessions()} == original_ids


def test_demo_seed_preserves_existing_real_database(tmp_path):
    from seed_demo import seed
    db = tmp_path / 'recordings.sqlite'
    store = Store(db)
    sid = store.start(DEFAULTS, 1000)
    store.finish(sid)
    seed(db)
    assert [s['id'] for s in Store(db).sessions()] == [sid]


def test_demo_pce_pressure_profile():
    from seed_demo import pressure_at, FILL_END, LOW_PRESSURE_END, LOW_HOLD_END, STEP_END, HIGH_HOLD_END, TEST_END
    assert pressure_at(150) < 5
    assert abs(pressure_at(LOW_PRESSURE_END) - 500) < 10
    assert abs(pressure_at(LOW_HOLD_END - 1) - 497) < 10
    assert abs(pressure_at(STEP_END) - 5000) < 10
    assert abs(pressure_at(STEP_END + 300) - 4900) < 10
    assert abs(pressure_at(STEP_END + 450) - 4900) < 10
    assert pressure_at(TEST_END) < 5
    assert HIGH_HOLD_END - STEP_END == 600
