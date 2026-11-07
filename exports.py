"""Snapshot-based exports. Original sample rows are streamed, not resampled."""
import csv, json, io, math, time
from app_icon import gauge_image
from datetime import datetime, timezone, timedelta
from pathlib import Path
from matplotlib.figure import Figure

def stamp(ts,offset=8):
    return datetime.fromtimestamp(ts,timezone(timedelta(hours=float(offset)))).isoformat(timespec='milliseconds')

def figure(rows,events,session,view):
    fig=Figure(figsize=(11,5),dpi=120); ax=fig.add_subplot(111)
    start=session['started']; offset=json.loads(session['settings']).get('utc_offset',8)
    ax.plot([(r['ts']-start)/60 for r in rows], [r['value'] if r['quality']=='OK' and r['value'] is not None else math.nan for r in rows],color='#008b92',lw=1.3)
    for e in events:
        x=(e['ts']-start)/60; ax.axvline(x,color='#cc8b19',lw=.8,ls='--'); ax.annotate(e['label'],(x,.97),xycoords=('data','axes fraction'),rotation=90,va='top',fontsize=8)
    ax.set(xlabel='Elapsed time (minutes)',ylabel=f"Pressure ({'psi'})",title=view.get('title') or session['name'])
    if view.get('ymin') is not None and view.get('ymax') is not None: ax.set_ylim(view['ymin'],view['ymax'])
    if view.get('xmin') is not None and view.get('xmax') is not None: ax.set_xlim(view['xmin'],view['xmax'])
    ax.grid(alpha=.2); fig.text(.01,.01,f"{session['mode'].upper()} | Start: {stamp(start,offset)}",fontsize=8); fig.text(.5,.01,f"Recording min: {view.get('recording_min', '—')} | max: {view.get('recording_max', '—')} {'psi'}",fontsize=8); fig.tight_layout(rect=(0,.04,1,1)); return fig

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
    raw_columns=['timestamp','elapsed_seconds','pressure','unit','quality','raw_register','status_register','latency_seconds']
    summary_columns=['timestamp','elapsed_seconds','average_pressure_psi','minimum_pressure_psi','maximum_pressure_psi','sample_count','unit']
    columns=raw_columns if resolution is None else summary_columns
    def values(r): return [stamp(r['ts'],offset),r['elapsed'],r['value'],'psi',r['quality'],r['raw'],r['status'],r['latency']]
    def summarized(cursor):
        # Buckets are anchored to the recording start; invalid readings are excluded.
        bucket=None; count=0; total=0.0; minimum=maximum=None
        def result(index):
            ts=session['started']+index*resolution
            return [stamp(ts,offset),round(index*resolution,3),total/count,minimum,maximum,count,'psi']
        for r in cursor:
            if r['quality']!='OK' or r['value'] is None or not math.isfinite(r['value']):
                continue
            index=int(math.floor((r['ts']-session['started'])/resolution+1e-9))
            if bucket is not None and index!=bucket:
                yield result(bucket)
                count=0;total=0.0;minimum=maximum=None
            bucket=index
            value=r['value'];count+=1;total+=value
            minimum=value if minimum is None else min(minimum,value)
            maximum=value if maximum is None else max(maximum,value)
        if bucket is not None:
            yield result(bucket)
    def data_rows(cursor):
        return (values(r) for r in cursor) if resolution is None else summarized(cursor)
    try:
        with store.connect() as c:
            c.execute('BEGIN')
            extrema=c.execute("SELECT min(value),max(value) FROM samples WHERE session=? AND quality='OK'",(sid,)).fetchone()
            view['recording_min']=extrema[0];view['recording_max']=extrema[1]
            cursor=c.execute('SELECT * FROM samples WHERE session=? AND ts>=? AND ts<=? ORDER BY ts,id',(sid,lo,hi))
            if path.suffix=='.csv':
                with tmp.open('w',newline='',encoding='utf-8-sig') as f:
                    w=csv.writer(f); w.writerow(columns)
                    for row_values in data_rows(cursor): w.writerow(row_values)
            elif path.suffix=='.xlsx':
                import xlsxwriter
                with xlsxwriter.Workbook(tmp,{'constant_memory':True,'strings_to_formulas':False,'strings_to_urls':False}) as book:
                    navy='#17334C'; teal='#008B92'; pale='#DDEFF6'
                    heading=book.add_format({'bold':True,'font_size':18,'font_color':navy})
                    subheading=book.add_format({'bold':True,'font_size':11,'font_color':teal})
                    label_style=book.add_format({'bold':True,'font_color':navy,'bg_color':pale,'bottom':1,'bottom_color':'#C5D7E0'})
                    value_style=book.add_format({'font_color':navy})
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
                          'Exported at':stamp(time.time(),offset),'Selected from':stamp(lo,offset),
                          'Selected to':stamp(hi,offset),'Data resolution':'All Data' if resolution is None else f'{resolution:g} seconds',
                          'Aggregation':'Valid readings: mean, min, max and count' if resolution is not None else 'Original samples',
                          'Recording minimum (psi)':extrema[0],'Recording maximum (psi)':extrema[1]}
                    for n,(key,value) in enumerate(meta.items(),6):
                        sh.write(n,0,key,label_style);sh.write(n,1,str(value if value is not None else ''),value_style)
                    sheet=None;row=0;part=0
                    for row_values in data_rows(cursor):
                        if sheet is None or row>=1048576:
                            part+=1;sheet=book.add_worksheet('Data_'+str(part))
                            sheet.set_row(0,32)
                            sheet.write_row(0,0,columns,table_header)
                            sheet.freeze_panes(1,0);sheet.set_column(0,0,32)
                            sheet.set_column(1,len(columns)-1,23)
                            row=1
                        sheet.write_row(row,0,row_values);row+=1
                    if sheet is None:
                        sheet=book.add_worksheet('Data_1');sheet.write_row(0,0,columns,table_header)
                    ev=book.add_worksheet('Events');ev.set_column(0,0,32);ev.set_column(1,1,55)
                    ev.write_row(0,0,['timestamp','label','kind'],table_header)
                    ev.freeze_panes(1,0)
                    for n,e in enumerate(events,1):ev.write_row(n,0,[stamp(e['ts'],offset),e['label'],e['kind']])
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
