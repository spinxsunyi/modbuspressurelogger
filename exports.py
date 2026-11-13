"""Snapshot-based exports. Original sample rows are streamed, not resampled."""
import csv, json, io, math, time
from app_icon import gauge_image
from datetime import datetime
from pathlib import Path
from matplotlib.figure import Figure
from chart_scale import apply_report_time_scale, apply_pressure_grid, apply_engineering_grid

def stamp(ts,offset=None):
    """Return computer-local wall time (legacy offset argument ignored)."""
    return datetime.fromtimestamp(ts).isoformat(timespec='milliseconds')

def figure(rows,events,session,view):
    fig=Figure(figsize=(11,5),dpi=120); ax=fig.add_subplot(111)
    start=session['started']; offset=json.loads(session['settings']).get('utc_offset',8)
    ax.plot([(r['ts']-start)/60 for r in rows], [r['value'] if r['quality']=='OK' and r['value'] is not None else math.nan for r in rows],color='#008b92',lw=1.3)
    for e in events:
        x=(e['ts']-start)/60; ax.axvline(x,color='#cc8b19',lw=.8,ls='--'); ax.annotate(e['label'],(x,.97),xycoords=('data','axes fraction'),rotation=90,va='top',fontsize=8)
    ax.set(xlabel='Elapsed time (minutes)',ylabel=f"Pressure ({'psi'})",title=view.get('title') or session['name'])
    if view.get('ymin') is not None and view.get('ymax') is not None: ax.set_ylim(view['ymin'],view['ymax'])
    if view.get('xmin') is not None and view.get('xmax') is not None:
        left,right=view['xmin'],view['xmax']
    elif rows:
        left,right=(rows[0]['ts']-start)/60,(rows[-1]['ts']-start)/60
    else:
        left,right=0,1
    # The Excel embedded image and legacy PNG/PDF exports share the same
    # engineering time/pressure divisions as the dedicated report charts.
    apply_report_time_scale(ax,left,right if right>left else left+1/60)
    apply_pressure_grid(ax,*ax.get_ylim())
    apply_engineering_grid(ax)
    fig.text(.01,.01,f"{session['mode'].upper()} | Start: {stamp(start,offset)}",fontsize=8); fig.text(.5,.01,f"Recording min: {view.get('recording_min', '—')} | max: {view.get('recording_max', '—')} {'psi'}",fontsize=8); fig.tight_layout(rect=(0,.04,1,1)); return fig

def export(store,sid,path,view,selected=False,resolution=None):
    path=Path(path); tmp=path.with_name(path.stem+'.partial'+path.suffix)
    session=store.get(sid); events=store.events(sid); settings=json.loads(session['settings']); offset=settings.get('utc_offset',8)
    lo=session['started']+view.get('xmin',0)*60 if selected else -1e20
    hi=session['started']+view.get('xmax',0)*60 if selected else time.time()
    if hi<=lo: raise ValueError('Invalid export range')
    events=[e for e in events if lo<=e['ts']<=hi]
    view=dict(view)
    if not selected:
        view.pop('xmin',None); view.pop('xmax',None)
    if resolution not in (None,0.5,1.0,60.0):
        raise ValueError('Unsupported data resolution')
    columns=['timestamp','elapsed_seconds','pressure','unit','quality','raw_register','status_register','latency_seconds']
    def values(r): return [stamp(r['ts'],offset),r['elapsed'],r['value'],'psi',r['quality'],r['raw'],r['status'],r['latency']]
    def data_rows(cursor,interval):
        # Each target is aligned to recording start, never to row count.
        # Keep the first actual sample at or after each target, provided it
        # falls within that target's interval. Missing intervals stay missing.
        if interval is None:
            for r in cursor:
                yield values(r)
            return
        start=session['started']
        last_bucket=None
        for r in cursor:
            elapsed=max(0.0,r['ts']-start)
            bucket=math.floor((elapsed+1e-7)/interval)
            # For a selected range beginning between targets, skip samples
            # until the next scheduled boundary.
            if elapsed+1e-7 < bucket*interval:
                continue
            if bucket==last_bucket:
                continue
            last_bucket=bucket
            yield values(r)
    try:
        with store.connect() as c:
            c.execute('BEGIN')
            extrema=c.execute("SELECT min(value),max(value) FROM samples WHERE session=? AND quality='OK'",(sid,)).fetchone()
            view['recording_min']=extrema[0];view['recording_max']=extrema[1]
            cursor=c.execute('SELECT * FROM samples WHERE session=? AND ts>=? AND ts<=? ORDER BY ts,id',(sid,lo,hi))
            if path.suffix=='.csv':
                with tmp.open('w',newline='',encoding='utf-8-sig') as f:
                    w=csv.writer(f)
                    w.writerow(['# Recording acquisition interval (configured)',str(settings.get('interval','Unknown'))+' s'])
                    w.writerow(['# Export resolution','All Data' if resolution is None else f'{resolution:g} s'])
                    w.writerow(['# Data treatment','Original samples' if resolution is None else 'Downsampled: original samples retained; no averaging or interpolation'])
                    w.writerow([]);w.writerow(columns)
                    for row_values in data_rows(cursor,resolution): w.writerow(row_values)
            elif path.suffix=='.xlsx':
                import xlsxwriter
                with xlsxwriter.Workbook(tmp,{'constant_memory':True,'strings_to_formulas':False,'strings_to_urls':False}) as book:
                    navy='#17334C'; teal='#008B92'; pale='#DDEFF6'
                    heading=book.add_format({'bold':True,'font_size':18,'font_color':navy})
                    subheading=book.add_format({'bold':True,'font_size':11,'font_color':teal})
                    label_style=book.add_format({'bold':True,'font_color':navy,'bg_color':pale,'bottom':1,'bottom_color':'#C5D7E0'})
                    value_style=book.add_format({'font_color':navy})
                    excel_datetime=book.add_format({'num_format':'yyyy-mm-dd hh:mm:ss.000'})
                    table_header=book.add_format({'bold':True,'font_color':navy,'bg_color':pale,'border':1,'border_color':'#C5D7E0','text_wrap':True,'valign':'vcenter'})
                    details=json.loads(session['details'])
                    sh=book.add_worksheet('Summary')
                    sh.set_column(0,0,25);sh.set_column(1,1,45);sh.set_column(2,3,20)
                    sh.set_row(0,34)
                    logo=io.BytesIO();gauge_image(512).save(logo,format='PNG');logo.seek(0)
                    sh.insert_image('A1','gauge.png',{'image_data':logo,'x_scale':0.11,'y_scale':0.11,'object_position':1})
                    sh.merge_range('B1:D1','Digital Pressure Recorder',heading)
                    sh.merge_range('B2:D2','PRESSURE RECORDING REPORT',subheading)
                    sh.merge_range('A4:D4','  |  '.join(str(details.get(k) or '').strip() for k in ('well','job') if details.get(k)) or session['name'],subheading)
                    meta={'Recording name':session['name'],'Source':session['mode'],'State':session['state'],
                          **{k.replace('_',' ').title():v for k,v in details.items()},
                          'Start':stamp(session['started'],offset),'End':stamp(session['ended'],offset) if session['ended'] else 'In progress',
                          'Exported at':stamp(time.time(),offset),
                          'Selected from':stamp(lo if selected else session['started'],offset),
                          'Selected to':stamp(hi if selected else (session['ended'] or time.time()),offset),'Data sheets':'All Data; 1 Second; 1 Minute; 10 Minutes',
                          'Recording acquisition interval (configured)':str(settings.get('interval','Unknown'))+' s',
                          'Timestamp timezone':'Computer local time',
                          'Data treatment':'All Data: original samples; other sheets: downsampled original samples (no averaging or interpolation)',
                          'Recording minimum (psi)':extrema[0],'Recording maximum (psi)':extrema[1]}
                    for n,(key,value) in enumerate(meta.items(),6):
                        sh.write(n,0,key,label_style);sh.write(n,1,str(value if value is not None else ''),value_style)
                    # One workbook contains full-resolution data plus three independently
                    # downsampled views. Re-query the same transaction snapshot for each.
                    # Streaming rows avoids loading long recordings into memory.
                    data_sets=[('All Data',None),('1 Second',1.0),('1 Minute',60.0),('10 Minutes',600.0)]
                    for title,interval in data_sets:
                        cursor=c.execute('SELECT * FROM samples WHERE session=? AND ts>=? AND ts<=? ORDER BY ts,id',(sid,lo,hi))
                        sheet=None;row=0;part=0
                        include_minutes=title in ('1 Minute','10 Minutes')
                        sheet_columns=(columns[:2]+['elapsed_minute']+columns[2:]) if include_minutes else columns
                        for row_values in data_rows(cursor,interval):
                            if sheet is None or row>=1048576:
                                part+=1
                                name=title if part==1 else f'{title} {part}'
                                sheet=book.add_worksheet(name)
                                sheet.set_row(0,32)
                                sheet.write_row(0,0,sheet_columns,table_header)
                                sheet.freeze_panes(1,0)
                                sheet.set_column(0,0,32)
                                sheet.set_column(1,len(sheet_columns)-1,23)
                                row=1
                            local_dt=datetime.fromisoformat(row_values[0]).replace(tzinfo=None)
                            sheet.write_datetime(row,0,local_dt,excel_datetime)
                            sheet_values=(row_values[:2]+[row_values[1]/60]+row_values[2:]) if include_minutes else row_values
                            sheet.write_row(row,1,sheet_values[1:]);row+=1
                        if sheet is None:
                            sheet=book.add_worksheet(title)
                            sheet.write_row(0,0,columns,table_header)
                            sheet.freeze_panes(1,0)
                            sheet.set_column(0,0,32)
                            sheet.set_column(1,len(columns)-1,23)
                    ev=book.add_worksheet('Events');ev.set_column(0,0,32);ev.set_column(1,1,55)
                    ev.write_row(0,0,['timestamp','label','kind'],table_header)
                    ev.freeze_panes(1,0)
                    for n,e in enumerate(events,1):
                        ev.write_datetime(n,0,datetime.fromtimestamp(e['ts']),excel_datetime)
                        ev.write_row(n,1,[e['label'],e['kind']])
                    rows=[r for r in store.plot_rows(sid) if lo<=r['ts']<=hi]
                    fig=figure(rows,events,session,view);image=io.BytesIO();fig.savefig(image,format='png');image.seek(0)
                    chart=book.add_worksheet('Chart');chart.insert_image('A1','chart.png',{'image_data':image,'x_scale':.8,'y_scale':.8})
            elif path.suffix in ('.png','.pdf'):
                rows=[r for r in store.plot_rows(sid) if lo<=r['ts']<=hi]
                fig=figure(rows,events,session,view)
                if path.suffix=='.png': fig.savefig(tmp,dpi=160)
                else:
                    from reportlab.pdfgen import canvas
                    from reportlab.lib.utils import ImageReader
                    from reportlab.lib.pagesizes import A4, landscape
                    pdf=canvas.Canvas(str(tmp),pagesize=landscape(A4)); w,h=landscape(A4)
                    pdf.setFont('Helvetica-Bold',16); pdf.drawString(30,h-35,'Digital Pressure Recorder | Pressure Report')
                    pdf.setFont('Helvetica',9); y=h-54
                    details=json.loads(session['details'])
                    for label in [f"{session['mode'].upper()} | {stamp(session['started'],offset)}",f"Well: {details.get('well','')} | Job: {details.get('job','')} | ID: {details.get('job_id','')}",f"Engineer: {details.get('engineer','')} | Client: {details.get('client','')}"]:
                        pdf.drawString(30,y,label[:145]); y-=14
                    image=io.BytesIO(); fig.savefig(image,format='png'); image.seek(0)
                    pdf.drawImage(ImageReader(image),25,70,width=w-50,height=h-185,preserveAspectRatio=True,anchor='c')
                    pdf.drawString(30,35,'Chart is a display overview; full-resolution samples are available in CSV / Excel.')
                    pdf.save()
            else: raise ValueError('Unsupported export format')
        tmp.replace(path)
    except Exception:
        tmp.unlink(missing_ok=True); raise
