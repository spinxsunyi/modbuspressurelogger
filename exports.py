"""Snapshot-based exports. Original sample rows are streamed, not resampled."""
import csv, json, io, math, time
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
    ax.set(xlabel='Elapsed time (minutes)',ylabel=f"Pressure ({session['unit']})",title=view.get('title') or session['name'])
    if view.get('ymin') is not None and view.get('ymax') is not None: ax.set_ylim(view['ymin'],view['ymax'])
    if view.get('xmin') is not None and view.get('xmax') is not None: ax.set_xlim(view['xmin'],view['xmax'])
    ax.grid(alpha=.2); fig.text(.01,.01,f"{session['mode'].upper()} | Start: {stamp(start,offset)}",fontsize=8); fig.tight_layout(rect=(0,.04,1,1)); return fig

def export(store,sid,path,view,selected=False):
    path=Path(path); tmp=path.with_name(path.stem+'.partial'+path.suffix)
    session=store.get(sid); events=store.events(sid); settings=json.loads(session['settings']); offset=settings.get('utc_offset',8)
    lo=session['started']+view.get('xmin',0)*60 if selected else -1e20
    hi=session['started']+view.get('xmax',0)*60 if selected else time.time()
    if hi<=lo: raise ValueError('Invalid export range')
    events=[e for e in events if lo<=e['ts']<=hi]
    view=dict(view)
    if not selected:
        view.pop('xmin',None); view.pop('xmax',None)
    columns=['timestamp','elapsed_seconds','pressure','unit','quality','raw_register','status_register','latency_seconds']
    def values(r): return [stamp(r['ts'],offset),r['elapsed'],r['value'],session['unit'],r['quality'],r['raw'],r['status'],r['latency']]
    try:
        with store.connect() as c:
            c.execute('BEGIN')
            cursor=c.execute('SELECT * FROM samples WHERE session=? AND ts>=? AND ts<=? ORDER BY ts,id',(sid,lo,hi))
            if path.suffix=='.csv':
                with tmp.open('w',newline='',encoding='utf-8-sig') as f:
                    w=csv.writer(f); w.writerow(columns)
                    for r in cursor: w.writerow(values(r))
            elif path.suffix=='.xlsx':
                import xlsxwriter
                with xlsxwriter.Workbook(tmp,{'constant_memory':True,'strings_to_formulas':False,'strings_to_urls':False}) as book:
                    sh=book.add_worksheet('Summary'); sh.set_column(0,0,24); sh.set_column(1,1,65)
                    meta={**{k:session[k] for k in ['name','mode','state','unit']},**json.loads(session['details']), 'start':stamp(session['started'],offset),'exported_at':stamp(__import__('time').time(),offset)}
                    for n,(k,v) in enumerate(meta.items()): sh.write_row(n,0,[k,str(v)])
                    sheet=None; row=0; part=0
                    for r in cursor:
                        if sheet is None or row>=1048576:
                            part+=1; sheet=book.add_worksheet('Data_'+str(part)); sheet.write_row(0,0,columns); sheet.freeze_panes(1,0); sheet.set_column(0,0,34); row=1
                        sheet.write_row(row,0,values(r)); row+=1
                    ev=book.add_worksheet('Events'); ev.write_row(0,0,['timestamp','label','kind'])
                    for n,e in enumerate(events,1): ev.write_row(n,0,[stamp(e['ts'],offset),e['label'],e['kind']])
                    rows=[r for r in store.plot_rows(sid) if lo<=r['ts']<=hi]
                    fig=figure(rows,events,session,view); image=io.BytesIO(); fig.savefig(image,format='png'); image.seek(0)
                    chart=book.add_worksheet('Chart'); chart.insert_image('A1','chart.png',{'image_data':image,'x_scale':.8,'y_scale':.8})
            elif path.suffix in ('.png','.pdf'):
                rows=[r for r in store.plot_rows(sid) if lo<=r['ts']<=hi]
                fig=figure(rows,events,session,view)
                if path.suffix=='.png': fig.savefig(tmp,dpi=160)
                else:
                    from reportlab.pdfgen import canvas
                    from reportlab.lib.utils import ImageReader
                    from reportlab.lib.pagesizes import A4, landscape
                    pdf=canvas.Canvas(str(tmp),pagesize=landscape(A4)); w,h=landscape(A4)
                    pdf.setFont('Helvetica-Bold',16); pdf.drawString(30,h-35,'PMS Logger | Pressure Report')
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
