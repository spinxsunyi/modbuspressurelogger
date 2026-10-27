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
        e.send('connect',{**DEFAULTS,'interval':.1});wait(e,'sample');e.send('start');sid=wait(e,'started')['sid']
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
        e.send('connect',{**DEFAULTS,'interval':.1});wait(e,'sample');e.send('start');sid=wait(e,'started')['sid'];st.add_sample=fail
        wait(e,'storage_error');assert e.sid is None;assert st.get(sid)['state']=='Storage error'
    finally:e.send('quit');e.join(3)

def test_second_instance_rejected(tmp_path):
    from instance import InstanceLock
    import pytest
    lock=InstanceLock(tmp_path/'lock')
    with pytest.raises(RuntimeError):InstanceLock(tmp_path/'lock')
    lock.close();second=InstanceLock(tmp_path/'lock');second.close()
