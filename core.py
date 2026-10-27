"""Acquisition and persistence. No GUI dependencies. Hardware driver is read-only."""
from __future__ import annotations
import json, math, random, sqlite3, threading, queue, time, uuid
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass

DEFAULTS = dict(mode='Simulation', port='', baud=19200, parity='E', stopbits=1,
                address=1, interval=.5, unit='psi', utc_offset=8, auto_connect=True)
FIELDS = ['well', 'job', 'job_id', 'engineer', 'client', 'location', 'job_date', 'notes']

def decode(registers):
    if len(registers) != 2: raise ValueError('Expected readout and status registers')
    raw, status = registers
    signed = raw - 65536 if raw & 0x8000 else raw
    decimals = (0, 3, 2, 1)[(status >> 12) & 3]
    quality = 'UNDERRANGE' if status & 16 else 'OVERRANGE' if status & 32 else 'BUSY' if status & 7 else 'OK'
    return signed / 10**decimals, quality, raw, status

class Simulator:
    def __init__(self, settings): self.start = time.monotonic(); self.drop = False; self.rng = random.Random(970)
    def read(self):
        if self.drop: raise TimeoutError('Simulated cable disconnected')
        t = (time.monotonic() - self.start) % 120
        v = 2450 * (t/25 if t < 25 else 1 if t < 85 else max(0, 1-(t-85)/25))
        return round(max(0,v+self.rng.uniform(-4,4)),1), 'OK', None, None
    def close(self): pass

class ModbusSource:
    def __init__(self, settings):
        from pymodbus.client import ModbusSerialClient
        self.settings = settings
        self.client = ModbusSerialClient(port=settings['port'], baudrate=int(settings['baud']),
            parity=settings['parity'], stopbits=int(settings['stopbits']), bytesize=8,
            timeout=min(.3, float(settings['interval'])*.8), retries=0)
    def read(self):
        if not self.client.connect(): raise ConnectionError('Cannot open serial port')
        # Manual p23: 400002 = wire address 0x0001, FC03, two contiguous registers.
        try:
            result = self.client.read_holding_registers(address=1,count=2,device_id=int(self.settings['address']))
            if result.isError(): raise IOError(str(result))
            return decode(result.registers)
        except Exception:
            self.client.close()
            raise
    def close(self): self.client.close()

class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, name TEXT, started REAL, ended REAL,
                state TEXT, mode TEXT, unit TEXT, settings TEXT, details TEXT, view TEXT DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS samples (
                id INTEGER PRIMARY KEY, session TEXT, ts REAL, elapsed REAL,
                value REAL, quality TEXT, raw INTEGER, status INTEGER, latency REAL,
                FOREIGN KEY(session) REFERENCES sessions(id));
            CREATE INDEX IF NOT EXISTS sample_time ON samples(session,ts);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, session TEXT, ts REAL, label TEXT, kind TEXT,
                created REAL, modified REAL);
            ''')
    @contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=5)
        c.row_factory = sqlite3.Row
        try:
            with c: yield c
        finally: c.close()
    def recover(self):
        with self.connect() as c: c.execute("UPDATE sessions SET state='Interrupted' WHERE state='Recording'")
    def start(self, settings, ts=None):
        ts = time.time() if ts is None else ts
        sid=uuid.uuid4().hex
        name=datetime.fromtimestamp(ts,timezone.utc).strftime('REC_%Y-%m-%d_%H%M%S_UTC')+'_'+sid[:4]
        details={k:'' for k in FIELDS}; details['job_date']=datetime.now().strftime('%Y-%m-%d')
        with self.connect() as c:
            c.execute('INSERT INTO sessions(id,name,started,state,mode,unit,settings,details) VALUES(?,?,?,?,?,?,?,?)',
                (sid,name,ts,'Recording',settings['mode'],settings['unit'],json.dumps(settings),json.dumps(details)))
        return sid
    def finish(self,sid,state='Completed'):
        with self.connect() as c: c.execute('UPDATE sessions SET ended=?,state=? WHERE id=?',(time.time(),state,sid))
    def add_sample(self,sid,sample):
        with self.connect() as c:
            c.execute('INSERT INTO samples(session,ts,elapsed,value,quality,raw,status,latency) VALUES(?,?,?,?,?,?,?,?)',
                (sid,)+tuple(sample[k] for k in ['ts','elapsed','value','quality','raw','status','latency']))
    def get(self,sid):
        with self.connect() as c: return dict(c.execute('SELECT * FROM sessions WHERE id=?',(sid,)).fetchone())
    def sessions(self,search=''):
        with self.connect() as c:
            return [dict(r) for r in c.execute('SELECT * FROM sessions WHERE name LIKE ? OR details LIKE ? ORDER BY started DESC',('%'+search+'%','%'+search+'%'))]
    def update(self,sid,field,value):
        if field not in ('details','view'): raise ValueError(field)
        with self.connect() as c: c.execute(f'UPDATE sessions SET {field}=? WHERE id=?',(json.dumps(value),sid))
    def event(self,sid,ts,label,kind='Recorded'):
        with self.connect() as c:
            return c.execute('INSERT INTO events(session,ts,label,kind,created,modified) VALUES(?,?,?,?,?,?)',
                (sid,ts,label,kind,time.time(),time.time())).lastrowid
    def edit_event(self,eid,ts,label):
        with self.connect() as c: c.execute('UPDATE events SET ts=?,label=?,modified=? WHERE id=?',(ts,label,time.time(),eid))
    def events(self,sid):
        with self.connect() as c: return [dict(r) for r in c.execute('SELECT * FROM events WHERE session=? ORDER BY ts',(sid,))]
    def stats(self,sid):
        with self.connect() as c:
            return dict(c.execute("SELECT count(*) n, sum(quality!='OK') errors,min(ts) first,max(ts) last FROM samples WHERE session=?",(sid,)).fetchone())
    def plot_rows(self,sid,limit=2400):
        with self.connect() as c:
            bounds=c.execute('SELECT min(ts),max(ts),count(*) FROM samples WHERE session=?',(sid,)).fetchone()
            if not bounds[2]: return []
            if bounds[2] <= limit: return [dict(r) for r in c.execute('SELECT * FROM samples WHERE session=? ORDER BY ts,id',(sid,))]
            # Retain extrema AND a missing sample per bucket; original rows remain intact.
            width=max((bounds[1]-bounds[0])/(limit/3),.001)
            sql='''WITH ranked AS (SELECT *,
              row_number() OVER(PARTITION BY cast((ts-?)/? AS INTEGER) ORDER BY (value IS NULL), value ASC) lo,
              row_number() OVER(PARTITION BY cast((ts-?)/? AS INTEGER) ORDER BY value DESC) hi,
              row_number() OVER(PARTITION BY cast((ts-?)/? AS INTEGER) ORDER BY (value IS NOT NULL),ts) gap
              FROM samples WHERE session=?)
              SELECT * FROM ranked WHERE lo=1 OR hi=1 OR (gap=1 AND value IS NULL) ORDER BY ts,id'''
            return [dict(r) for r in c.execute(sql,(bounds[0],width,bounds[0],width,bounds[0],width,sid))]

class Engine(threading.Thread):
    def __init__(self,store):
        super().__init__(daemon=True); self.store=store; self.commands=queue.Queue(); self.messages=queue.Queue()
        self.source=None; self.sid=None; self.settings=dict(DEFAULTS); self.running=True; self.deadline=0; self.origin=0
    def send(self,cmd,*args): self.commands.put((cmd,args))
    def emit(self,kind,**data): self.messages.put((kind,data))
    def run(self):
        while self.running:
            try:
                cmd,args=self.commands.get(timeout=max(.001,min(.05,self.deadline-time.monotonic())) if self.source else .05)
                self.command(cmd,*args)
            except queue.Empty: pass
            except Exception as e: self.emit('error',text=str(e))
            if self.running and self.source and time.monotonic()>=self.deadline: self.poll()
        if self.source: self.source.close()
    def command(self,cmd,*args):
        if cmd=='connect':
            if self.sid: raise RuntimeError('Stop recording before changing connection')
            if self.source: self.source.close()
            self.settings=dict(args[0]); self.source=Simulator(self.settings) if self.settings['mode']=='Simulation' else ModbusSource(self.settings)
            self.deadline=time.monotonic(); self.origin=self.deadline; self.emit('connected',settings=self.settings)
        elif cmd=='disconnect':
            if self.sid: raise RuntimeError('Stop recording first')
            if self.source: self.source.close()
            self.source=None; self.emit('disconnected')
        elif cmd=='start':
            if not self.source or self.sid: raise RuntimeError('Connect first; only one recording can run')
            self.sid=self.store.start(self.settings); self.origin=time.monotonic(); self.emit('started',sid=self.sid)
        elif cmd=='stop':
            if self.sid:
                sid=self.sid; self.store.finish(sid); self.sid=None; self.emit('stopped',sid=sid)
        elif cmd=='drop':
            if isinstance(self.source,Simulator): self.source.drop=bool(args[0])
        elif cmd=='quit':
            try: self.command('stop')
            finally: self.running=False
    def poll(self):
        began=time.monotonic()
        try: value,quality,raw,status=self.source.read()
        except Exception as e: value,quality,raw,status=None,'TIMEOUT',None,None
        sample=dict(ts=time.time(),elapsed=time.monotonic()-self.origin,value=value,quality=quality,raw=raw,status=status,latency=time.monotonic()-began)
        if self.sid:
            try: self.store.add_sample(self.sid,sample)
            except Exception as e:
                sid=self.sid; self.sid=None
                try: self.store.finish(sid,'Storage error')
                except Exception: pass
                self.emit('storage_error',text=str(e),sid=sid)
        self.emit('sample',sample=sample,sid=self.sid)
        step=float(self.settings['interval']); self.deadline+=step
        if self.deadline<time.monotonic(): self.deadline=time.monotonic()+step
