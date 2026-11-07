"""Shared engineering-chart policy. Display scaling never changes stored samples."""
from __future__ import annotations
import math
from matplotlib.ticker import MultipleLocator, AutoMinorLocator, MaxNLocator

WINDOWS = {
    '1 min': (60, 10, 2),
    '5 min': (300, 60, 12),
    '10 min': (600, 120, 30),
    '15 min': (900, 180, 30),
    '30 min': (1800, 300, 60),
    '1 hour': (3600, 600, 120),
    '12 hours': (43200, 3600, 900),
    '24 hours': (86400, 7200, 1800),
}

def engineering_time_scale(lo, hi):
    """Return rounded display limits and major/minor ticks in elapsed minutes."""
    if not (math.isfinite(lo) and math.isfinite(hi) and hi > lo):
        raise ValueError('Invalid chart time limits')
    duration = hi-lo
    quantum = 5 if duration <= 60 else 10 if duration <= 180 else 30 if duration <= 720 else 60
    width = max(quantum, math.ceil((duration-1e-9)/quantum)*quantum)
    # Prefer a readable 4-10 major divisions instead of nearest raw step.
    # Examples: 18->20/5, 48->50/10, 73->80/10, 118->120/20.
    if width <= 5: major=1
    elif width <= 10: major=2
    elif width <= 30: major=5
    elif width <= 100: major=10
    elif width <= 180: major=20
    else:
        raw=width/6
        steps=(30,60,120,180,240,360,720,1440)
        major=min(steps,key=lambda step:(abs(step-raw),step))
    return lo,lo+width,major,major/5

def apply_report_time_scale(ax, lo, hi):
    left,right,major,minor = engineering_time_scale(lo,hi)
    ax.set_xlim(left,right)
    ax.xaxis.set_major_locator(MultipleLocator(major))
    ax.xaxis.set_minor_locator(MultipleLocator(minor))

def apply_window_time_grid(ax, window, units='seconds'):
    """Fixed time grid; return False for auto/buffer view."""
    if window not in WINDOWS:
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5,min_n_ticks=2))
        ax.xaxis.set_minor_locator(AutoMinorLocator(5))
        return False
    _,major,minor=WINDOWS[window]
    factor = 1 if units=='seconds' else 1/60 if units=='minutes' else None
    if factor is None:raise ValueError('Invalid axis time unit')
    ax.xaxis.set_major_locator(MultipleLocator(major*factor))
    ax.xaxis.set_minor_locator(MultipleLocator(minor*factor))
    return True

def apply_engineering_grid(ax, visible=True):
    """Do not overwrite fixed time tick locators installed by callers."""
    if not isinstance(ax.xaxis.get_minor_locator(),(MultipleLocator,AutoMinorLocator)):
        ax.xaxis.set_minor_locator(AutoMinorLocator(5))
    if not isinstance(ax.yaxis.get_minor_locator(),MultipleLocator):
        ax.yaxis.set_minor_locator(AutoMinorLocator(5))
    ax.grid(visible=visible,which='major',color='#8d98a3',alpha=.30,linewidth=.8)
    ax.grid(visible=visible,which='minor',color='#aab4bd',alpha=.16,linewidth=.45)
    ax.set_axisbelow(True)

def nice_pressure_step(span, target=6):
    """Engineering-friendly major pressure interval in displayed units."""
    if not math.isfinite(span) or span<=0:raise ValueError('Invalid pressure span')
    raw=span/target
    power=10**math.floor(math.log10(raw))
    return min((1,2,2.5,5,10),key=lambda v:abs(v*power-raw))*power

def apply_pressure_grid(ax, low, high):
    """Configure major pressure ticks without changing the operator's Y limits."""
    step=nice_pressure_step(high-low)
    ax.yaxis.set_major_locator(MultipleLocator(step))
    ax.yaxis.set_minor_locator(MultipleLocator(step/5))
    return step

def reduce_live_samples(rows, max_points=4000):
    """Bound plotted samples, retaining extrema and every invalid reading.

    NaN values from invalid samples create visible breaks. When invalid readings
    alone exceed max_points, keep them rather than silently hiding failures.
    """
    if len(rows)<=max_points:return rows
    bucket_size=max(1,math.ceil(len(rows)/max(1,max_points//4)))
    reduced=[]
    for start in range(0,len(rows),bucket_size):
        bucket=rows[start:start+bucket_size]
        picks={0,len(bucket)-1}
        valid=[(i,r['value']) for i,r in enumerate(bucket)
               if r['quality']=='OK' and r['value'] is not None and math.isfinite(r['value'])]
        if valid:
            picks.add(min(valid,key=lambda p:p[1])[0])
            picks.add(max(valid,key=lambda p:p[1])[0])
        for i,r in enumerate(bucket):
            if r['quality']!='OK' or r['value'] is None:
                picks.add(i)
                if i:picks.add(i-1)
                if i+1<len(bucket):picks.add(i+1)
        reduced.extend(bucket[i] for i in sorted(picks))
    return reduced
