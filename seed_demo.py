"""Seed clearly labelled synthetic PCE/lubricator pressure-test sessions on first launch only."""
from pathlib import Path
from datetime import datetime
import math
import time

from core import Store, DEFAULTS

SAMPLE_INTERVAL = 0.5
FILL_END = 300.0
LOW_PRESSURE_END = 315.0
LOW_HOLD_END = 615.0
STEP_END = 715.0
HIGH_HOLD_END = 1315.0
TEST_END = 1495.0
# Each tuple is (target psi, pump seconds, pause seconds).
STEPS = ((1500, 15, 5), (2500, 15, 5), (3500, 15, 5),
         (4500, 15, 5), (5000, 15, 5))


def pressure_at(t, variant=0):
    """Illustrative waveform in psi, not an equipment acceptance criterion."""
    if t < FILL_END:
        # Filling at essentially zero gauge pressure.
        base, pumping = 0.0, False
    elif t < LOW_PRESSURE_END:
        f = (t - FILL_END) / (LOW_PRESSURE_END - FILL_END)
        base, pumping = 500 * f, True
    elif t < LOW_HOLD_END:
        # Low-pressure hold with small early settling.
        base = 500 - 3 * (1 - math.exp(-(t - LOW_PRESSURE_END) / 55))
        pumping = False
    elif t < STEP_END:
        elapsed = t - LOW_HOLD_END
        prior = 500.0
        base, pumping = 500.0, False
        for target, pump_seconds, pause_seconds in STEPS:
            if elapsed < pump_seconds:
                f = elapsed / pump_seconds
                base = prior + (target - prior) * f
                pumping = True
                break
            elapsed -= pump_seconds
            if elapsed < pause_seconds:
                base = target - 3 * (1 - math.exp(-elapsed / 2))
                break
            elapsed -= pause_seconds
            prior = float(target)
        else:
            base = 5000.0
    elif t < HIGH_HOLD_END:
        hold = t - STEP_END
        # 2% drop over first five minutes, then a flat 4900 psi plateau.
        # Smooth settling rather than a sudden linear kink.
        if hold < 300:
            x = hold / 300
            base = 5000 - 100 * (1 - (1 - x) ** 2)
        else:
            base = 4900.0
        pumping = False
    else:
        # Bleed down from the stabilized pressure over three minutes.
        x = min(1.0, (t - HIGH_HOLD_END) / (TEST_END - HIGH_HOLD_END))
        base = 4900 * (1 - x) ** 1.25
        pumping = False

    # Deterministic sensor ripple; larger irregular spikes only while pumping.
    noise = (1.0 * math.sin(0.81 * t + variant) +
             0.5 * math.sin(2.39 * t + variant * 0.7))
    if pumping:
        noise += (12 * math.sin(3.7 * t + variant) +
                  8 * math.sin(1.93 * t + 0.4) +
                  6 * math.sin(7.11 * t))
    return round(max(0.0, base + noise), 1)


def seed(path):
    path = Path(path)
    if path.exists():
        return  # Preserve every existing recording and database.
    store = Store(path)
    for n in range(2):
        start = time.time() - (n + 1) * 7200
        sid = store.start({**DEFAULTS, 'mode': 'Simulation'}, start)
        store.update(sid, 'details', dict(
            well='DEMO — PCE Test', job='Synthetic lubricator and PCE pressure test',
            job_id=f'DEMO-{n+1:03}', engineer='Demo operator', client='DEMO ONLY',
            location='Virtual sensor',
            job_date=datetime.fromtimestamp(start).strftime('%Y-%m-%d'),
            notes=('SYNTHETIC DEMO — NOT A REAL WELL OR PCE MEASUREMENT. '
                   'The 2% pressure decline is illustrative, not a PASS/FAIL criterion.')))
        with store.connect() as db:
            for i in range(int(TEST_END / SAMPLE_INTERVAL) + 1):
                t = i * SAMPLE_INTERVAL
                # Second recording demonstrates a short communications gap.
                missing = n == 1 and 790 <= t <= 793
                db.execute(
                    'INSERT INTO samples(session,ts,elapsed,value,quality,raw,status,latency) '
                    'VALUES(?,?,?,?,?,?,?,?)',
                    (sid, start + t, t, None if missing else pressure_at(t, n),
                     'TIMEOUT' if missing else 'OK', None, None, .001))
            events = [
                (0, 'Begin filling'),
                (FILL_END, 'Pressurize to 500 psi'),
                (LOW_PRESSURE_END, '500 psi hold start'),
                (LOW_HOLD_END, 'Incremental pumping start'),
                (STEP_END, '5000 psi hold start'),
                (STEP_END + 300, 'Pressure stabilized near 4900 psi'),
                (HIGH_HOLD_END, 'Bleed off start'),
                (TEST_END, 'Pressure released'),
            ]
            for elapsed, label in events:
                db.execute(
                    'INSERT INTO events(session,ts,label,kind,created,modified) '
                    'VALUES(?,?,?,?,?,?)',
                    (sid, start + elapsed, label, 'Recorded', start, start))
            db.execute(
                "UPDATE sessions SET ended=?,state='Completed' WHERE id=?",
                (start + TEST_END, sid))
    return store


if __name__ == '__main__':
    seed(Path(__file__).parent / 'data' / 'recordings.sqlite')
