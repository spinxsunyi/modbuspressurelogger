"""Single-page report preview and PDF/JPEG export for Digital Pressure Recorder."""
import json
import math
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from exports import stamp
from units import from_psi

def report_figure(store, sid, unit='psi'):
    session=store.get(sid)
    if not session: raise ValueError('Recording no longer exists')
    details=json.loads(session['details'])
    settings=json.loads(session['settings'])
    offset=settings.get('utc_offset',8)
    rows=store.plot_rows(sid)
    events=store.events(sid)
    stats=store.stats(sid)
    with store.connect() as db:
        ext=db.execute("SELECT MIN(value),MAX(value) FROM samples WHERE session=? AND quality='OK' AND value IS NOT NULL",(sid,)).fetchone()
        first=db.execute("SELECT value FROM samples WHERE session=? AND quality='OK' AND value IS NOT NULL ORDER BY ts,id LIMIT 1",(sid,)).fetchone()
        last=db.execute("SELECT value FROM samples WHERE session=? AND quality='OK' AND value IS NOT NULL ORDER BY ts DESC,id DESC LIMIT 1",(sid,)).fetchone()
    def fmt(v):
        return '—' if v is None else f'{from_psi(v,unit):,.2f} {unit}'
    fig=Figure(figsize=(8.27,11.69),dpi=110,facecolor='white')
    navy='#17334c'; teal='#008b92'; gray='#566779'
    def txt(x,y,s,size=9,bold=False,color=navy,**kw):
        fig.text(x,y,str(s),fontsize=size,color=color,fontweight='bold' if bold else 'normal',va='top',**kw)
    def rule(y):
        fig.add_artist(__import__('matplotlib').lines.Line2D([.055,.945],[y,y],transform=fig.transFigure,color='#c9d3dc',lw=.8))
    txt(.06,.966,'Digital Pressure Recorder',18,True)
    txt(.06,.937,'PRESSURE RECORDING REPORT',9,True,color=teal)
    txt(.94,.963,'Version 1.0',8,color=gray,ha='right')
    rule(.914)
    txt(.06,.898,'RECORDING METADATA',10,True)
    started=stamp(session['started'],offset).replace('T',' ')[:23]
    ended=stamp(session['ended'],offset).replace('T',' ')[:23] if session['ended'] else 'In progress'
    left=[('Well',details.get('well')),('Job',details.get('job')),('Job ID',details.get('job_id')),('Engineer',details.get('engineer')),('Client',details.get('client'))]
    right=[('Recording ID',session['id']),('Start',started),('End',ended),('Source',session['mode']),('Location',details.get('location'))]
    for x,items in ((.06,left),(.53,right)):
        for i,(label,value) in enumerate(items):
            txt(x,.875-i*.024,label+':',8,True)
            txt(x+.13,.875-i*.024,str(value or '—')[:37],8)
    rule(.741)
    txt(.06,.726,'PRESSURE TREND',10,True)
    ax=fig.add_axes([.105,.385,.83,.31])
    start=session['started']
    xx=[(r['ts']-start)/60 for r in rows]
    yy=[from_psi(r['value'],unit) if r['quality']=='OK' and r['value'] is not None else math.nan for r in rows]
    ax.plot(xx,yy,color=teal,lw=1.1)
    for i,e in enumerate(events[:20],1):
        x=(e['ts']-start)/60
        ax.axvline(x,color='#bb852c',lw=.75,ls='--',alpha=.8)
        ax.annotate(str(i),(x,.96),xycoords=('data','axes fraction'),fontsize=7,color='#925b10',ha='center',va='top')
    ax.set(xlabel='Elapsed time (minutes)',ylabel=f'Pressure ({unit})')
    ax.xaxis.set_major_locator(MaxNLocator(6))
    ax.grid(alpha=.22)
    ax.tick_params(labelsize=8)
    txt(.06,.366,'MIN  '+fmt(ext[0]),8,True)
    txt(.31,.366,'MAX  '+fmt(ext[1]),8,True)
    txt(.56,.366,'FIRST  '+fmt(first['value'] if first else None),8,True)
    txt(.79,.366,'LAST  '+fmt(last['value'] if last else None),8,True)
    rule(.346)
    txt(.06,.333,'EVENT LIST',10,True)
    if not events: txt(.06,.309,'No event annotations',8,color=gray)
    else:
        for i,e in enumerate(events[:6],1):
            label=str(e['label']).replace('\n',' ')[:58]
            txt(.06,.309-(i-1)*.026,f"{i:02d}  {stamp(e['ts'],offset)[11:19]}    {label}",8)
        if len(events)>6:txt(.06,.151,f'+ {len(events)-6} more events (see recording history)',8,color=gray)
    rule(.14)
    txt(.06,.128,'NOTES',10,True)
    import textwrap
    notes=(details.get('notes') or 'No notes provided').replace('\r','')
    wrapped=[]
    for para in notes.split('\n'):
        wrapped.extend(textwrap.wrap(para,width=108) or [''])
    for i,line in enumerate(wrapped[:3]):txt(.06,.107-i*.018,line,8,color=gray)
    if len(wrapped)>3:txt(.06,.051,'Notes truncated for single-page layout',7,color=gray)
    rule(.038)
    txt(.06,.029,'Digital Pressure Recorder v1.0  •  A software by Eka Yudhi Pratama',7,color=gray)
    txt(.94,.029,'Page 1 of 1',7,color=gray,ha='right')
    return fig

def graph_figure(store,sid,unit='psi'):
    session=store.get(sid)
    if not session:raise ValueError('Recording no longer exists')
    rows=store.plot_rows(sid);events=store.events(sid)
    fig=Figure(figsize=(12,6),dpi=140,facecolor='white');ax=fig.add_subplot(111)
    start=session['started']
    ax.plot([(r['ts']-start)/60 for r in rows],
            [from_psi(r['value'],unit) if r['quality']=='OK' and r['value'] is not None else math.nan for r in rows],
            color='#008b92',lw=1.2)
    for i,e in enumerate(events,1):
        x=(e['ts']-start)/60;ax.axvline(x,color='#bb852c',ls='--',lw=.8)
        if i<=30:ax.annotate(str(i),(x,.96),xycoords=('data','axes fraction'),ha='center',va='top',fontsize=8)
    ax.set(title=session['name'],xlabel='Elapsed time (minutes)',ylabel=f'Pressure ({unit})')
    ax.grid(alpha=.2);fig.tight_layout()
    return fig
