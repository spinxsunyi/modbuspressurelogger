"""Single-page report preview and PDF/JPEG export for Digital Pressure Recorder."""
import json
import math
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator, FuncFormatter
from exports import stamp
from units import from_psi

def report_figure(store, sid, unit='psi', time_range=None, time_axis='Elapsed Time',show_events=True,show_grid=True):
    session=store.get(sid)
    if not session: raise ValueError('Recording no longer exists')
    details=json.loads(session['details'])
    settings=json.loads(session['settings'])
    offset=settings.get('utc_offset',8)
    rows=store.plot_rows(sid)
    events=store.events(sid)
    if time_range is not None:
        lo,hi=time_range
        rows=[r for r in rows if lo<=r['ts']<=hi]
        events=[e for e in events if lo<=e['ts']<=hi]
    with store.connect() as db:
        clause=' AND ts>=? AND ts<=?' if time_range is not None else ''
        args=(sid,*time_range) if time_range is not None else (sid,)
        ext=db.execute("SELECT MIN(value),MAX(value) FROM samples WHERE session=? AND quality='OK' AND value IS NOT NULL"+clause,args).fetchone()
        first=db.execute("SELECT value FROM samples WHERE session=? AND quality='OK' AND value IS NOT NULL"+clause+" ORDER BY ts,id LIMIT 1",args).fetchone()
        last=db.execute("SELECT value FROM samples WHERE session=? AND quality='OK' AND value IS NOT NULL"+clause+" ORDER BY ts DESC,id DESC LIMIT 1",args).fetchone()
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
    ax=fig.add_axes([.105,.425,.83,.265])
    start=session['started']
    xx=[(r['ts']-start)/60 for r in rows]
    yy=[from_psi(r['value'],unit) if r['quality']=='OK' and r['value'] is not None else math.nan for r in rows]
    ax.plot(xx,yy,color=teal,lw=1.1)
    for i,e in enumerate(events[:20],1):
        x=(e['ts']-start)/60
        ax.axvline(x,color='#bb852c',lw=.75,ls='--',alpha=.8)
        ax.annotate(str(i),(x,.96),xycoords=('data','axes fraction'),fontsize=7,color='#925b10',ha='center',va='top')
    configure_time_axis(ax,start,offset,time_axis)
    ax.set(ylabel=f'Pressure ({unit})')
    if time_range is not None:ax.set_xlim((time_range[0]-start)/60,(time_range[1]-start)/60)
    ax.xaxis.set_major_locator(MaxNLocator(6))
    ax.grid(alpha=.22,visible=show_grid)
    ax.tick_params(labelsize=8)
    txt(.06,.383,'MIN  '+fmt(ext[0]),8,True)
    txt(.31,.383,'MAX  '+fmt(ext[1]),8,True)
    txt(.56,.383,'FIRST  '+fmt(first['value'] if first else None),8,True)
    txt(.79,.383,'LAST  '+fmt(last['value'] if last else None),8,True)
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

def graph_figure(store,sid,unit='psi',time_range=None,time_axis='Elapsed Time'):
    session=store.get(sid)
    if not session:raise ValueError('Recording no longer exists')
    rows=store.plot_rows(sid);events=store.events(sid) if show_events else []
    offset=json.loads(session['settings']).get('utc_offset',8)
    if time_range is not None:
        lo,hi=time_range
        rows=[r for r in rows if lo<=r['ts']<=hi]
        events=[e for e in events if lo<=e['ts']<=hi]
    fig=Figure(figsize=(12,6),dpi=140,facecolor='white');ax=fig.add_subplot(111)
    start=session['started']
    ax.plot([(r['ts']-start)/60 for r in rows],
            [from_psi(r['value'],unit) if r['quality']=='OK' and r['value'] is not None else math.nan for r in rows],
            color='#008b92',lw=1.2)
    for i,e in enumerate(events,1):
        x=(e['ts']-start)/60;ax.axvline(x,color='#bb852c',ls='--',lw=.8)
        if i<=30:ax.annotate(str(i),(x,.96),xycoords=('data','axes fraction'),ha='center',va='top',fontsize=8)
    configure_time_axis(ax,start,offset,time_axis)
    ax.set(title=session['name'],ylabel=f'Pressure ({unit})')
    if time_range is not None:ax.set_xlim((time_range[0]-start)/60,(time_range[1]-start)/60)
    ax.grid(alpha=.2,visible=show_grid);fig.tight_layout()
    return fig

def configure_time_axis(ax,start,offset,mode):
    if mode=='Date & Time':
        ax.set_xlabel('Date & time (UTC%+g)' % float(offset))
        ax.xaxis.set_major_formatter(FuncFormatter(
            lambda x,pos:stamp(start+x*60,offset).replace('T',' ')[11:19]))
    else:
        ax.set_xlabel('Elapsed time (minutes)')
