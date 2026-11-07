"""Pressure report pages and PDF/JPEG export for Digital Pressure Recorder."""
import json
import math
import re
from datetime import datetime
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator, FuncFormatter, AutoMinorLocator, MultipleLocator
from exports import stamp
from units import from_psi
from app_icon import gauge_image
from chart_scale import engineering_time_scale,apply_report_time_scale,apply_engineering_grid,apply_pressure_grid
import numpy as np

def report_name(session):
    """Readable, Windows-safe basename shared by PDF, JPEG and detailed exports."""
    details=json.loads(session['details'])
    offset=json.loads(session['settings']).get('utc_offset',8)
    local=stamp(session['started'],offset)
    date=local[:10]
    def clean(value):
        value=re.sub(r'[<>:"/\\|?*\x00-\x1f]', ' ',str(value or ''))
        value=re.sub(r'\s+',' ',value).strip(' .')
        return value[:90].rstrip(' .')
    fields=[clean(details.get(key)) for key in ('well','job')]
    fields=[value for value in fields if value]
    if fields:
        return '_'.join(['Pressure Recording Report']+fields+[date])
    return 'Digital Pressure Report_'+re.sub(r'[^0-9]','',local[:19])


def report_figure(store, sid, unit='psi', time_range=None, time_axis='Elapsed Time',show_events=True,show_grid=True,y_limits=None):
    session=store.get(sid)
    if not session: raise ValueError('Recording no longer exists')
    details=json.loads(session['details'])
    settings=json.loads(session['settings'])
    offset=settings.get('utc_offset',8)
    rows=store.plot_rows(sid)
    events=store.events(sid) if show_events else []
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
    # Use the same gauge artwork as the application icon, rendered at 512px
    # for a crisp print-quality mark rather than enlarging the 16/32px icon.
    logo_ax=fig.add_axes([.06,.929,.060,.043])
    logo_ax.imshow(np.asarray(gauge_image(512)),interpolation='lanczos')
    logo_ax.set_axis_off()
    txt(.132,.966,'Digital Pressure Recorder',18,True)
    txt(.132,.937,'PRESSURE RECORDING REPORT',9,True,color=teal)
    txt(.94,.963,'Version 1.0',8,color=gray,ha='right')
    rule(.914)
    # Repeat the prominent well/job identifier used on continuation pages.
    heading='  |  '.join(str(details.get(key) or '').strip() for key in ('well','job') if str(details.get(key) or '').strip())
    if heading:
        txt(.06,.895,heading[:85],12,True)
    txt(.06,.863,'RECORDING METADATA',10,True)
    started=stamp(session['started'],offset).replace('T',' ')[:23]
    ended=stamp(session['ended'],offset).replace('T',' ')[:23] if session['ended'] else 'In progress'
    left=[('Well',details.get('well')),('Job',details.get('job')),('Job ID',details.get('job_id')),('Engineer',details.get('engineer')),('Client',details.get('client'))]
    right=[('Recording ID',session['id']),('Start',started),('End',ended),('Source',session['mode']),('Location',details.get('location'))]
    for x,items in ((.06,left),(.53,right)):
        for i,(label,value) in enumerate(items):
            txt(x,.841-i*.024,label+':',8,True)
            txt(x+.13,.841-i*.024,str(value or '—')[:37],8)
    rule(.706)
    txt(.06,.691,'NOTES',10,True)
    import textwrap
    notes=(details.get('notes') or 'No notes provided').replace('\\r','')
    wrapped=[]
    for para in notes.split('\\n'):
        wrapped.extend(textwrap.wrap(para,width=108) or [''])
    for i,line in enumerate(wrapped[:3]):
        txt(.06,.671-i*.017,line,8,color=gray)
    if len(wrapped)>3:
        txt(.06,.613,'Notes truncated for first-page layout',7,color=gray)
    rule(.641)
    txt(.06,.626,'PRESSURE TREND',10,True)
    ax=fig.add_axes([.105,.355,.83,.240])
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
    if y_limits is not None:ax.set_ylim(*y_limits)
    lo=(time_range[0]-start)/60 if time_range is not None else xx[0]
    hi=(time_range[1]-start)/60 if time_range is not None else xx[-1]
    apply_report_time_scale(ax,lo,hi)
    apply_pressure_grid(ax,*ax.get_ylim())
    apply_engineering_grid(ax,show_grid)
    ax.tick_params(labelsize=8)
    # The four statistics are computed from the selected interval above, not the full recording.
    # Keep the summary well below the X-axis title and its two-line date/time ticks.
    txt(.06,.298,'MIN  '+fmt(ext[0]),9,True)
    txt(.31,.298,'MAX  '+fmt(ext[1]),9,True)
    txt(.56,.298,'FIRST  '+fmt(first['value'] if first else None),9,True)
    txt(.79,.298,'LAST  '+fmt(last['value'] if last else None),9,True)
    rule(.265)
    txt(.06,.252,'EVENT LIST',11,True)
    txt(.06,.229,'NO.',8,True,color=gray)
    txt(.125,.229,'TIME',8,True,color=gray)
    txt(.25,.229,'PRESSURE',8,True,color=gray)
    txt(.46,.229,'EVENT',8,True,color=gray)
    if not events:
        txt(.06,.207,'No event annotations in the selected interval',9,color=gray)
    else:
        with store.connect() as db:
            for i,e in enumerate(events[:5],1):
                label=str(e['label']).replace('\\n',' ')[:50]
                reading=db.execute(
                    "SELECT value FROM samples WHERE session=? AND quality='OK' AND value IS NOT NULL "
                    "ORDER BY ABS(ts-?) LIMIT 1",(sid,e['ts'])).fetchone()
                pressure=fmt(reading['value'] if reading else None)
                y=.207-(i-1)*.024
                txt(.06,y,f'{i:02d}',9)
                txt(.125,y,stamp(e['ts'],offset)[11:19],9)
                txt(.25,y,pressure,9)
                txt(.46,y,label,9)
                rule(y-.014)
        if len(events)>5:
            txt(.06,.073,f'{len(events)-5} additional events on the following page(s)',8,color=gray)
    rule(.038)
    txt(.06,.029,'Digital Pressure Recorder v1.0  •  A software by Eka Yudhi Pratama',7,color=gray)
    txt(.94,.029,f'Page 1 of {2+math.ceil(max(0,len(events)-5)/25)}',7,color=gray,ha='right')
    return fig

def report_figures(store, sid, unit='psi', time_range=None, time_axis='Elapsed Time',
                   show_events=True, show_grid=True, y_limits=None):
    """Return all A4 report pages, including overflow event-list pages."""
    first=report_figure(store,sid,unit,time_range,time_axis,show_events,show_grid,y_limits)
    session=store.get(sid)
    settings=json.loads(session['settings'])
    offset=settings.get('utc_offset',8)
    events=store.events(sid) if show_events else []
    if time_range is not None:
        lo,hi=time_range
        events=[event for event in events if lo<=event['ts']<=hi]

    navy='#17334c'; teal='#008b92'; gray='#566779'
    pages=[first]
    with store.connect() as db:
        readings=[]
        for event in events[5:]:
            reading=db.execute(
                "SELECT value FROM samples WHERE session=? AND quality='OK' "
                "AND value IS NOT NULL ORDER BY ABS(ts-?) LIMIT 1",
                (sid,event['ts'])).fetchone()
            readings.append(reading['value'] if reading else None)

    remainder=events[5:]
    total=2+math.ceil(len(remainder)/25)
    for start_index in range(0,len(remainder),25):
        page_number=2+start_index//25
        fig=Figure(figsize=(8.27,11.69),dpi=110,facecolor='white')
        def label(x,y,value,size=9,bold=False,color=navy,**kwargs):
            fig.text(x,y,str(value),fontsize=size,color=color,
                     fontweight='bold' if bold else 'normal',va='top',**kwargs)
        def rule(y):
            from matplotlib.lines import Line2D
            fig.add_artist(Line2D([.055,.945],[y,y],transform=fig.transFigure,
                                  color='#c9d3dc',lw=.8))
        logo_ax=fig.add_axes([.06,.929,.060,.043])
        logo_ax.imshow(np.asarray(gauge_image(512)),interpolation='lanczos')
        logo_ax.set_axis_off()
        label(.132,.966,'Digital Pressure Recorder',18,True)
        label(.132,.937,'EVENT LIST — CONTINUED',9,True,color=teal)
        label(.94,.963,'Version 1.0',8,color=gray,ha='right')
        rule(.914)
        details=json.loads(session['details'])
        label(.06,.897,(details.get('well') or session['name'])+
              ('  |  '+details['job'] if details.get('job') else ''),10,True)
        label(.06,.862,'NO.',9,True,color=gray)
        label(.125,.862,'TIME',9,True,color=gray)
        label(.25,.862,'PRESSURE',9,True,color=gray)
        label(.46,.862,'EVENT',9,True,color=gray)
        rule(.837)
        for local_index,event in enumerate(remainder[start_index:start_index+25]):
            event_index=start_index+local_index
            y=.817-local_index*.029
            pressure=readings[event_index]
            formatted=('—' if pressure is None else
                       f'{from_psi(pressure,unit):,.2f} {unit}')
            name=str(event['label']).replace('\\n',' ')[:60]
            label(.06,y,f'{event_index+6:02d}',9)
            label(.125,y,stamp(event['ts'],offset)[11:19],9)
            label(.25,y,formatted,9)
            label(.46,y,name,9)
            rule(y-.016)
        rule(.038)
        label(.06,.029,'Digital Pressure Recorder v1.0  •  A software by Eka Yudhi Pratama',7,color=gray)
        label(.94,.029,f'Page {page_number} of {total}',7,color=gray,ha='right')
        pages.append(fig)
    pages.append(full_size_chart_figure(store,sid,unit,time_range,time_axis,show_events,show_grid,y_limits,len(pages)+1))
    return pages


def full_size_chart_figure(store, sid, unit='psi', time_range=None,
                           time_axis='Elapsed Time', show_events=True,
                           show_grid=True, y_limits=None, page_number=2):
    """Final PDF page: A4 landscape, shared report branding, maximum chart area."""
    session=store.get(sid)
    if not session:
        raise ValueError('Recording no longer exists')
    details=json.loads(session['details'])
    offset=json.loads(session['settings']).get('utc_offset',8)
    rows=store.plot_rows(sid)
    events=store.events(sid) if show_events else []
    if time_range is not None:
        lo,hi=time_range
        rows=[r for r in rows if lo<=r['ts']<=hi]
        events=[e for e in events if lo<=e['ts']<=hi]
    fig=Figure(figsize=(11.69,8.27),dpi=110,facecolor='white')
    navy='#17334c';teal='#008b92';gray='#566779'
    def label(x,y,value,size=9,bold=False,color=navy,**kwargs):
        fig.text(x,y,str(value),fontsize=size,color=color,
                 fontweight='bold' if bold else 'normal',va='top',**kwargs)
    from matplotlib.lines import Line2D
    def rule(y):
        fig.add_artist(Line2D([.04,.96],[y,y],transform=fig.transFigure,
                              color='#c9d3dc',lw=.8))
    logo=fig.add_axes([.045,.925,.042,.053])
    logo.imshow(np.asarray(gauge_image(512)),interpolation='lanczos')
    logo.set_axis_off()
    label(.10,.969,'Digital Pressure Recorder',18,True)
    label(.10,.936,'PRESSURE RECORDING REPORT',9,True,color=teal)
    label(.955,.964,'Version 1.0',8,color=gray,ha='right')
    rule(.915)
    heading='  |  '.join(str(details.get(k) or '').strip()
                        for k in ('well','job') if str(details.get(k) or '').strip())
    label(.045,.899,'FULL SIZE CHART',12,True)
    if heading:
        label(.955,.897,heading[:110],10,True,ha='right')
    ax=fig.add_axes([.09,.145,.855,.715])
    start=session['started']
    ax.plot([(r['ts']-start)/60 for r in rows],
            [from_psi(r['value'],unit) if r['quality']=='OK' and r['value'] is not None
             else math.nan for r in rows],color=teal,lw=1.15)
    for i,event in enumerate(events,1):
        x=(event['ts']-start)/60
        ax.axvline(x,color='#bb852c',ls='--',lw=.75,alpha=.8)
        if i<=30:
            ax.annotate(str(i),(x,.97),xycoords=('data','axes fraction'),
                        ha='center',va='top',fontsize=8,color='#925b10')
    configure_time_axis(ax,start,offset,time_axis)
    ax.set_ylabel(f'Pressure ({unit})')
    if y_limits is not None:
        ax.set_ylim(*y_limits)
    lo=(time_range[0]-start)/60 if time_range is not None else (rows[0]['ts']-start)/60
    hi=(time_range[1]-start)/60 if time_range is not None else (rows[-1]['ts']-start)/60
    apply_report_time_scale(ax,lo,hi)
    apply_pressure_grid(ax,*ax.get_ylim())
    apply_engineering_grid(ax,show_grid)
    ax.tick_params(labelsize=9)
    rule(.057)
    label(.045,.041,'Digital Pressure Recorder v1.0  •  A software by Eka Yudhi Pratama',
          7,color=gray)
    label(.955,.041,f'Page {page_number} of {page_number}',7,color=gray,ha='right')
    return fig


def graph_figure(store,sid,unit='psi',time_range=None,time_axis='Elapsed Time',show_events=True,show_grid=True,y_limits=None):
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
    ax.set(title=report_name(session),ylabel=f'Pressure ({unit})')
    if y_limits is not None:ax.set_ylim(*y_limits)
    lo=(time_range[0]-start)/60 if time_range is not None else (rows[0]['ts']-start)/60
    hi=(time_range[1]-start)/60 if time_range is not None else (rows[-1]['ts']-start)/60
    apply_report_time_scale(ax,lo,hi)
    apply_pressure_grid(ax,*ax.get_ylim())
    apply_engineering_grid(ax,show_grid);fig.tight_layout()
    return fig

def configure_time_axis(ax,start,offset,mode):
    if mode=='Date & Time':
        ax.set_xlabel('Date & time (UTC%+g)' % float(offset))
        ax.xaxis.set_major_formatter(FuncFormatter(
            lambda x,pos:datetime.fromisoformat(stamp(start+x*60,offset)).strftime('%d %b\n%H:%M:%S')))
    else:
        ax.set_xlabel('Elapsed time (minutes)')
