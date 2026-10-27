"""Create optional demo sessions. Never overwrites an existing database."""
from pathlib import Path
import math, time, json
from core import Store,DEFAULTS

def seed(path):
    if path.exists():return
    store=Store(path)
    for n in range(2):
        start=time.time()-(n+1)*3600
        sid=store.start(DEFAULTS,start)
        store.update(sid,'details',dict(well='DEMO — Tambora-66',job='Simulated pressure test',job_id=f'DEMO-{n+1:03}',engineer='Eka Yudhi',client='Demo only',location='Virtual sensor',job_date='2026-10-27',notes='Synthetic data for interface testing. Not a real well measurement.'))
        for i in range(241):
            t=i*.5;v=2450*(t/25 if t<25 else 1 if t<85 else max(0,1-(t-85)/25));v=max(0,v+3*math.sin(t*3))
            missing=n==1 and 55<=t<=58
            store.add_sample(sid,dict(ts=start+t,elapsed=t,value=None if missing else round(v,1),quality='TIMEOUT' if missing else 'OK',raw=None,status=None,latency=.001))
        for t,label in [(0,'Pump start'),(25,'Hold start'),(85,'Bleed off')]:store.event(sid,start+t,label)
        store.event(sid,start+110,'Review: pressure released','Review')
        with store.connect() as c:c.execute("UPDATE sessions SET ended=?,state='Completed' WHERE id=?",(start+120,sid))
    return store
if __name__=='__main__':seed(Path(__file__).parent/'data'/'recordings.sqlite')
