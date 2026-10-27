from __future__ import annotations
import json, math, os, sys, time, queue, threading
from pathlib import Path
from collections import deque
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from core import DEFAULTS,FIELDS,Store,Engine
from instance import InstanceLock
from exports import export,stamp

UI_FONT='Segoe UI' if os.name=='nt' else 'Helvetica'
BASE=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
DATA=Path(os.environ.get('PMS_LOGGER_DATA',str(BASE/'data')))

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('PMS Logger - Simulation Preview 0.1'); self.geometry('1280x820'); self.minsize(1000,680)
        DATA.mkdir(parents=True,exist_ok=True)
        self.instance_lock=InstanceLock(DATA/'app.lock')
        self.exporting=False
        self.settings=dict(DEFAULTS)
        try: self.settings.update(json.loads((DATA/'settings.json').read_text()))
        except (OSError,ValueError): pass
        self.store=Store(DATA/'recordings.sqlite'); self.store.recover(); self.engine=Engine(self.store); self.engine.start()
        self.sid=None; self.detail_sid=None; self.connected=False; self.latest=None; self.buffer=deque(maxlen=7200); self.viewer_sid=None
        self.save_job=None; self.edit_loading=False; self.closing=False; self.last_plot=0; self.rec_count=0; self.rec_errors=0; self.pending=False
        self.configure(bg='#f3f6f8'); style=ttk.Style(self); style.theme_use('clam')
        style.configure('.',font=(UI_FONT,10),background='#f3f6f8',foreground='#17334c')
        style.configure('TButton',padding=(12,7)); style.configure('Accent.TButton',background='#008b92',foreground='white')
        style.configure('TEntry',fieldbackground='white'); style.configure('Treeview',rowheight=30,fieldbackground='white')
        style.configure('Treeview.Heading',font=(UI_FONT,10,'bold')); style.configure('Title.TLabel',font=(UI_FONT,20,'bold'))
        nav=tk.Frame(self,bg='#17334c'); nav.pack(fill='x')
        tk.Label(nav,text='PMS Logger',font=(UI_FONT,20,'bold'),bg='#17334c',fg='white',padx=20,pady=12).pack(side='left')
        for page in ['Live Monitor','History','Settings']:
            tk.Button(nav,text=page,command=lambda p=page:self.show(p),bg='#17334c',fg='white',bd=0,padx=18,pady=15).pack(side='left')
        self.global_status=tk.Label(nav,text='SIMULATION',bg='#17334c',fg='#ffcb72',padx=15); self.global_status.pack(side='right')
        self.host=ttk.Frame(self,padding=14); self.host.pack(fill='both',expand=True)
        self.pages={name:ttk.Frame(self.host) for name in ['Live Monitor','History','Settings','Viewer']}
        self.footer=ttk.Label(self,text='Ready',padding=8); self.footer.pack(fill='x')
        self.make_live(); self.make_history(); self.make_settings(); self.make_viewer(); self.show('Live Monitor')
        self.protocol('WM_DELETE_WINDOW',self.close); self.after(50,self.tick)
        if self.settings.get('auto_connect'): self.after(200,self.connect)
    def show(self,name):
        for p in self.pages.values(): p.pack_forget()
        self.pages[name].pack(fill='both',expand=True); self.page=name
        if name=='History': self.refresh_history()
    def plot(self,parent):
        fig=Figure(figsize=(8,4),dpi=100,facecolor='white'); ax=fig.add_subplot(111); fig.subplots_adjust(left=.09,right=.98,bottom=.15,top=.92)
        canvas=FigureCanvasTkAgg(fig,master=parent); canvas.get_tk_widget().pack(fill='both',expand=True)
        return fig,ax,canvas
    def make_live(self):
        p=self.pages['Live Monitor']; top=ttk.Frame(p); top.pack(fill='x')
        self.connection=ttk.Label(top,text='Waiting for device'); self.connection.pack(side='left')
        self.connect_btn=ttk.Button(top,text='Connect',command=self.toggle_connect); self.connect_btn.pack(side='left',padx=12)
        self.drop=tk.BooleanVar(); ttk.Checkbutton(top,text='Simulate disconnect',variable=self.drop,command=lambda:self.engine.send('drop',self.drop.get())).pack(side='right')
        body=ttk.Panedwindow(p,orient='horizontal'); body.pack(fill='both',expand=True,pady=10)
        main=ttk.Frame(body); self.details_panel=ttk.LabelFrame(body,text='Recording details  |  autosaved',padding=12); body.add(main,weight=4); body.add(self.details_panel,weight=1); self.live_pane=body
        self.value=ttk.Label(main,text='-',font=(UI_FONT,42,'bold'),foreground='#008b92'); self.value.pack(anchor='w')
        self.reading_status=ttk.Label(main,text='Waiting for first reading'); self.reading_status.pack(anchor='w')
        toolbar=ttk.Frame(main); toolbar.pack(fill='x',pady=6)
        self.follow=tk.BooleanVar(value=True); ttk.Checkbutton(toolbar,text='Auto-follow',variable=self.follow).pack(side='left')
        self.window=tk.StringVar(value='5 min'); ttk.Combobox(toolbar,textvariable=self.window,values=['1 min','5 min','30 min','Buffer'],state='readonly',width=10).pack(side='left',padx=8)
        ttk.Button(toolbar,text='Live',command=lambda:self.follow.set(True)).pack(side='left')
        ttk.Button(toolbar,text='Details +/-',command=self.toggle_details).pack(side='right')
        self.lfig,self.lax,self.lcanvas=self.plot(main); self.lax.set(xlabel='Time',ylabel='Pressure'); self.lax.grid(alpha=.2)
        self.line,=self.lax.plot([],[],color='#008b92',lw=1.2)
        self.lcanvas.mpl_connect('button_press_event',lambda e:self.follow.set(False) if e.inaxes else None)
        NavigationToolbar2Tk(self.lcanvas,main).update()
        controls=ttk.Frame(main); controls.pack(fill='x',pady=8)
        self.record_btn=ttk.Button(controls,text='REC Record',style='Accent.TButton',command=self.record); self.record_btn.pack(side='left')
        self.event_btn=ttk.Button(controls,text='+ Add Event',command=self.add_live_event,state='disabled'); self.event_btn.pack(side='left',padx=10)
        self.rec_label=ttk.Label(controls,text='Preview only  |  not saved'); self.rec_label.pack(side='left')
        self.detail_vars={}; self.detail_entries=[]
        self.session_name=ttk.Label(self.details_panel,text='Press Record to create a session',wraplength=250); self.session_name.pack(anchor='w',pady=(0,8))
        for k in FIELDS:
            ttk.Label(self.details_panel,text=k.replace('_',' ').title()).pack(anchor='w')
            v=tk.StringVar(); en=ttk.Entry(self.details_panel,textvariable=v,width=28,state='disabled'); en.pack(fill='x',pady=(1,7)); self.detail_vars[k]=v; self.detail_entries.append(en)
            v.trace_add('write',self.schedule_save)
        self.saved=ttk.Label(self.details_panel,text=''); self.saved.pack(anchor='w')
    def toggle_details(self):
        if str(self.details_panel) in [str(p) for p in self.live_pane.panes()]: self.live_pane.forget(self.details_panel)
        else: self.live_pane.add(self.details_panel,weight=1)
    def schedule_save(self,*_):
        if self.edit_loading or not self.detail_sid:return
        if self.save_job:self.after_cancel(self.save_job)
        self.saved.config(text='Saving...'); self.save_job=self.after(600,self.save_details)
    def save_details(self):
        self.save_job=None
        if self.detail_sid:
            try: self.store.update(self.detail_sid,'details',{k:v.get() for k,v in self.detail_vars.items()}); self.saved.config(text='Saved')
            except Exception as e: self.saved.config(text='SAVE FAILED'); messagebox.showerror('Save failed',str(e))
    def load_details(self,sid):
        if self.save_job:self.after_cancel(self.save_job); self.save_details()
        self.detail_sid=sid; s=self.store.get(sid); d=json.loads(s['details']); self.edit_loading=True
        for k,v in self.detail_vars.items():v.set(d.get(k,''))
        self.edit_loading=False
        for en in self.detail_entries:en.config(state='normal')
        self.session_name.config(text=s['name']); self.saved.config(text='Saved')
    def connect(self):
        self.drop.set(False); self.engine.send('connect',dict(self.settings))
    def toggle_connect(self):
        if self.sid:messagebox.showinfo('Recording','Stop recording before disconnecting.');return
        self.engine.send('disconnect') if self.connected else self.connect()
    def record(self):
        if self.pending:return
        if not self.sid and (not self.connected or not self.latest or self.latest['quality']!='OK' or time.time()-self.latest['ts']>max(2,3*self.settings['interval'])):
            messagebox.showinfo('Not ready','Connect and wait for a valid reading first.');return
        self.pending=True; self.record_btn.config(state='disabled'); self.engine.send('stop' if self.sid else 'start')
    def add_live_event(self):
        if not self.sid:return
        sid=self.sid; ts=time.time() # Capture before the operator types.
        label=simpledialog.askstring('Add event','Event label (timestamp captured now):',parent=self)
        if label:self.store.event(sid,ts,label.strip()); self.footer.config(text='Event saved')
    def make_history(self):
        p=self.pages['History']; ttk.Label(p,text='Recordings',style='Title.TLabel').pack(anchor='w')
        bar=ttk.Frame(p); bar.pack(fill='x',pady=12); self.search=tk.StringVar()
        ttk.Entry(bar,textvariable=self.search,width=45).pack(side='left'); ttk.Button(bar,text='Search / Refresh',command=self.refresh_history).pack(side='left',padx=8)
        ttk.Label(bar,text='Search well, job, engineer or record ID').pack(side='left')
        cols=('start','well','job','duration','mode','status'); self.history=ttk.Treeview(p,columns=cols,show='headings',selectmode='browse')
        for col in cols:self.history.heading(col,text=col.title());self.history.column(col,width=150)
        self.history.pack(fill='both',expand=True); self.history.bind('<Double-1>',lambda e:self.open_selected())
        ttk.Button(p,text='Open in Viewer',style='Accent.TButton',command=self.open_selected).pack(anchor='e',pady=12)
    def refresh_history(self):
        for i in self.history.get_children():self.history.delete(i)
        for s in self.store.sessions(self.search.get()):
            d=json.loads(s['details']); end=s['ended'] or self.store.stats(s['id'])['last'] or s['started']
            self.history.insert('', 'end',iid=s['id'],values=(stamp(s['started'],self.settings['utc_offset'])[:19],d.get('well') or s['name'],d.get('job',''),f"{max(0,end-s['started'])/60:.1f} min",s['mode'],s['state']))
    def open_selected(self):
        sel=self.history.selection()
        if sel:self.load_viewer(sel[0])
    def make_settings(self):
        p=self.pages['Settings']; ttk.Label(p,text='Settings',style='Title.TLabel').pack(anchor='w',pady=8)
        ttk.Label(p,text='Connection and unit changes apply after reconnecting. Stop recording before applying settings.').pack(anchor='w')
        grid=ttk.Frame(p); grid.pack(anchor='w',pady=18); self.config_vars={}
        choices={'mode':['Simulation','Modbus RTU'],'baud':[2400,4800,9600,19200],'parity':['E','N','O'],'stopbits':[1,2],'interval':[.5,1,.2,.1],'unit':['psi','bar','kPa','MPa'],'utc_offset':[7,8,0]}
        for n,k in enumerate(['mode','port','baud','parity','stopbits','address','interval','unit','utc_offset']):
            ttk.Label(grid,text=k.replace('_',' ').title()).grid(row=n,column=0,sticky='w',padx=8,pady=8)
            v=tk.StringVar(value=str(self.settings[k])); self.config_vars[k]=v
            if k in choices:en=ttk.Combobox(grid,textvariable=v,values=choices[k],state='readonly',width=30)
            else:en=ttk.Entry(grid,textvariable=v,width=32)
            en.grid(row=n,column=1,sticky='ew')
        ttk.Button(grid,text='Find COM ports',command=self.find_ports).grid(row=1,column=2,padx=10)
        self.auto=tk.BooleanVar(value=self.settings['auto_connect']); ttk.Checkbutton(p,text='Auto-connect last configuration at startup',variable=self.auto).pack(anchor='w',pady=8)
        ttk.Label(p,text='Hardware profile: PMS-970  |  FC03  |  address 0x0001  |  readout + status\nUnit labels must match the meter; this version does not convert pressure units.\nHardware connection has not yet been validated.\n\nData: '+str(DATA),wraplength=900).pack(anchor='w',pady=12)
        ttk.Button(p,text='Save and reconnect',command=self.apply_settings,style='Accent.TButton').pack(anchor='w')
    def find_ports(self):
        from serial.tools.list_ports import comports
        ports=list(comports()); messagebox.showinfo('COM ports','\n'.join(f'{p.device}: {p.description}' for p in ports) or 'No serial devices found')
        if len(ports)==1:self.config_vars['port'].set(ports[0].device)
    def apply_settings(self):
        if self.sid or self.pending:messagebox.showinfo('Recording','Stop recording before changing settings.');return
        try:
            s={k:v.get() for k,v in self.config_vars.items()}
            for k in ['baud','stopbits','address']:s[k]=int(s[k])
            for k in ['interval','utc_offset']:s[k]=float(s[k])
            if not 1<=s['address']<=247:raise ValueError('Slave address must be 1-247')
            if s['mode']=='Modbus RTU' and not s['port']:raise ValueError('Specify a COM port')
            s['auto_connect']=self.auto.get(); tmp=DATA/'settings.tmp'; tmp.write_text(json.dumps(s,indent=2)); tmp.replace(DATA/'settings.json')
            self.settings=s; self.buffer.clear(); self.latest=None; self.connect(); self.show('Live Monitor')
        except Exception as e:messagebox.showerror('Settings',str(e))
    def make_viewer(self):
        p=self.pages['Viewer']; top=ttk.Frame(p); top.pack(fill='x'); ttk.Button(top,text='< History',command=lambda:self.show('History')).pack(side='left')
        self.viewer_title=ttk.Label(top,text='Recording Viewer',style='Title.TLabel'); self.viewer_title.pack(side='left',padx=12)
        ttk.Button(top,text='Refresh',command=lambda:self.load_viewer(self.viewer_sid)).pack(side='right')
        body=ttk.Panedwindow(p,orient='horizontal'); body.pack(fill='both',expand=True,pady=8); left=ttk.Frame(body); side=ttk.Frame(body); body.add(left,weight=4); body.add(side,weight=1)
        scroll=tk.Canvas(side,width=285,bg='#f3f6f8',highlightthickness=0); sb=ttk.Scrollbar(side,orient='vertical',command=scroll.yview)
        sb.pack(side='right',fill='y');scroll.pack(side='left',fill='both',expand=True);scroll.configure(yscrollcommand=sb.set)
        right=ttk.Frame(scroll,padding=10); item=scroll.create_window((0,0),window=right,anchor='nw')
        right.bind('<Configure>',lambda e:scroll.configure(scrollregion=scroll.bbox('all')))
        scroll.bind('<Configure>',lambda e:scroll.itemconfigure(item,width=e.width))
        self.vfig,self.vax,self.vcanvas=self.plot(left); NavigationToolbar2Tk(self.vcanvas,left).update()
        self.vcanvas.mpl_connect('button_press_event',self.chart_click)
        ttk.Label(left,text='Click chart to capture annotation time. Toolbar: pan / zoom / reset.').pack(anchor='w')
        self.events_tree=ttk.Treeview(left,columns=('minute','label','kind'),show='headings',height=4)
        for col in ('minute','label','kind'):self.events_tree.heading(col,text=col.title())
        self.events_tree.pack(fill='x'); self.events_tree.bind('<Double-1>',lambda e:self.edit_annotation())
        self.view_vars={}
        for k,label,default in [('title','Report title',''),('xmin','From (elapsed minutes)','0'),('xmax','To (elapsed minutes)','1'),('ymin','Pressure minimum','0'),('ymax','Pressure maximum','3000')]:
            ttk.Label(right,text=label).pack(anchor='w'); v=tk.StringVar(value=default); self.view_vars[k]=v; ttk.Entry(right,textvariable=v,width=26).pack(fill='x',pady=(2,8))
        ttk.Button(right,text='Apply scale / Save view',command=self.apply_view).pack(fill='x',pady=4)
        ttk.Button(right,text='Use current view',command=self.capture_view).pack(fill='x',pady=4)
        ttk.Button(right,text='Edit job details',command=self.edit_viewer_details).pack(fill='x',pady=4)
        ttk.Separator(right).pack(fill='x',pady=12)
        self.annotation_time=tk.StringVar(value='0'); ttk.Label(right,text='Annotation time (elapsed minutes)').pack(anchor='w'); ttk.Entry(right,textvariable=self.annotation_time).pack(fill='x')
        ttk.Button(right,text='+ Add review annotation',command=self.add_annotation).pack(fill='x',pady=6)
        self.selected_export=tk.BooleanVar(); ttk.Checkbutton(right,text='Export selected time range',variable=self.selected_export).pack(anchor='w',pady=8)
        exports=ttk.Frame(right);exports.pack(fill='x');exports.columnconfigure((0,1),weight=1)
        for n,fmt in enumerate(['xlsx','csv','pdf','png']):ttk.Button(exports,text='Export '+fmt.upper(),command=lambda f=fmt:self.do_export(f)).grid(row=n//2,column=n%2,sticky='ew',padx=2,pady=3)
    def load_viewer(self,sid):
        if not sid:return
        self.viewer_sid=sid; self.vsession=self.store.get(sid); self.vrows=self.store.plot_rows(sid); self.vevents=self.store.events(sid)
        d=json.loads(self.vsession['details']); self.viewer_title.config(text=(d.get('well') or 'Unnamed well')+'  |  '+(d.get('job') or 'Recording'))
        end=max(.01,((self.vrows[-1]['ts'] if self.vrows else self.vsession['started']+60)-self.vsession['started'])/60)
        vals=[r['value'] for r in self.vrows if r['value'] is not None]; maximum=max(vals) if vals else 3000
        v={'title':d.get('well') or self.vsession['name'],'xmin':0,'xmax':end,'ymin':min(0,min(vals)) if vals else 0,'ymax':max(1,maximum*1.1),**json.loads(self.vsession['view'])}
        for k,var in self.view_vars.items():var.set(str(v[k]))
        self.paint_viewer(); self.show('Viewer')
    def view_values(self):
        v={k:var.get() if k=='title' else float(var.get()) for k,var in self.view_vars.items()}
        if any(not math.isfinite(v[k]) for k in ['xmin','xmax','ymin','ymax']):raise ValueError('Scale must be finite')
        if v['xmax']<=v['xmin'] or v['ymax']<=v['ymin']:raise ValueError('Maximum must exceed minimum')
        return v
    def paint_viewer(self):
        v=self.view_values(); ax=self.vax; ax.clear(); start=self.vsession['started']
        ax.plot([(r['ts']-start)/60 for r in self.vrows],[r['value'] if r['quality']=='OK' and r['value'] is not None else math.nan for r in self.vrows],color='#008b92',lw=1.1)
        ax.set(xlabel='Elapsed minutes',ylabel='Pressure ('+self.vsession['unit']+')',title=v['title'],xlim=(v['xmin'],v['xmax']),ylim=(v['ymin'],v['ymax'])); ax.grid(alpha=.2)
        for i in self.events_tree.get_children():self.events_tree.delete(i)
        for e in self.vevents:
            x=(e['ts']-start)/60; ax.axvline(x,ls='--',lw=.7,color='#bd7b1c')
            annotation=ax.annotate(e['label'],(x,.95),xycoords=('data','axes fraction'),rotation=90,va='top',fontsize=8); annotation.draggable()
            self.events_tree.insert('','end',iid=str(e['id']),values=(f'{x:.3f}',e['label'],e['kind']))
        self.vcanvas.draw_idle()
    def apply_view(self):
        try:v=self.view_values();self.store.update(self.viewer_sid,'view',v);self.paint_viewer();self.footer.config(text='Viewer configuration saved')
        except Exception as e:messagebox.showerror('Chart settings',str(e))
    def capture_view(self):
        for k,n in zip(['xmin','xmax','ymin','ymax'],[*self.vax.get_xlim(),*self.vax.get_ylim()]):self.view_vars[k].set(f'{n:.5f}')
        self.apply_view()
    def chart_click(self,event):
        if event.inaxes==self.vax and event.xdata is not None:self.annotation_time.set(f'{event.xdata:.5f}')
    def add_annotation(self):
        try:
            ts=self.vsession['started']+float(self.annotation_time.get())*60
            last=self.store.stats(self.viewer_sid)['last'] or self.vsession['started']
            if not self.vsession['started']<=ts<=last:raise ValueError('Choose a time within the recording')
            label=simpledialog.askstring('Review annotation','Label:',parent=self)
            if label:self.store.event(self.viewer_sid,ts,label,'Review');self.vevents=self.store.events(self.viewer_sid);self.paint_viewer()
        except Exception as e:messagebox.showerror('Annotation',str(e))
    def edit_annotation(self):
        sel=self.events_tree.selection()
        if not sel:return
        event=next(e for e in self.vevents if e['id']==int(sel[0])); label=simpledialog.askstring('Edit annotation','Label:',initialvalue=event['label'],parent=self)
        if label:self.store.edit_event(event['id'],event['ts'],label);self.vevents=self.store.events(self.viewer_sid);self.paint_viewer()
    def edit_viewer_details(self):
        if self.save_job:self.after_cancel(self.save_job);self.save_details()
        sid=self.viewer_sid; d=json.loads(self.store.get(sid)['details']); win=tk.Toplevel(self);win.title('Job details'); vars={}
        for i,k in enumerate(FIELDS):
            ttk.Label(win,text=k.replace('_',' ').title()).grid(row=i,column=0,padx=10,pady=5);var=tk.StringVar(value=d.get(k,''));vars[k]=var;ttk.Entry(win,textvariable=var,width=45).grid(row=i,column=1,padx=10,pady=5)
        def save():
            self.store.update(sid,'details',{k:v.get() for k,v in vars.items()})
            if sid==self.detail_sid:self.load_details(sid)
            win.destroy();self.load_viewer(sid)
        ttk.Button(win,text='Save',command=save).grid(row=len(FIELDS),column=1,pady=12)
    def do_export(self,fmt):
        if self.exporting:messagebox.showinfo('Export','Wait for the current export to finish.');return
        try:v=self.view_values()
        except Exception as e:messagebox.showerror('Export',str(e));return
        path=filedialog.asksaveasfilename(defaultextension='.'+fmt,initialfile=self.vsession['name']+'.'+fmt,filetypes=[(fmt.upper(),'*.'+fmt)])
        if not path:return
        self.exporting=True;sid=self.viewer_sid; selected=self.selected_export.get();self.footer.config(text='Exporting... recording continues')
        def work():
            try:export(self.store,sid,path,v,selected);self.engine.emit('exported',path=path)
            except Exception as e:self.engine.emit('export_error',text='Export failed: '+str(e))
        threading.Thread(target=work,daemon=True).start()
    def tick(self):
        try:
            while True:
                kind,d=self.engine.messages.get_nowait()
                if kind=='sample':
                    s=d['sample'];self.latest=s;self.buffer.append(s)
                    if s['quality']=='OK':self.value.config(text=f"{s['value']:,.2f} {self.settings['unit']}")
                    self.reading_status.config(text=f"{self.settings['mode'].upper()}  |  {s['quality']}  |  {stamp(s['ts'],self.settings['utc_offset'])[11:23]}",foreground='#008b92' if s['quality']=='OK' else '#b45309')
                    if d['sid']:self.rec_count+=1;self.rec_errors+=s['quality']!='OK'
                elif kind=='connected':self.connected=True;self.connection.config(text=d['settings']['mode']+'  |  '+(d['settings']['port'] or 'virtual sensor'));self.connect_btn.config(text='Disconnect')
                elif kind=='disconnected':self.connected=False;self.connection.config(text='Disconnected');self.connect_btn.config(text='Connect');self.reading_status.config(text='STALE  |  disconnected');self.latest=None
                elif kind=='started':
                    self.sid=d['sid'];self.pending=False;self.rec_started=time.monotonic();self.rec_count=0;self.rec_errors=0;self.record_btn.config(text='STOP Stop',state='normal');self.event_btn.config(state='normal');self.load_details(self.sid)
                elif kind in ('stopped','storage_error'):
                    self.sid=None;self.pending=False;self.record_btn.config(text='REC Record',state='normal');self.event_btn.config(state='disabled');self.rec_label.config(text='Preview only  |  not saved')
                    if kind=='storage_error':messagebox.showerror('RECORDING STOPPED - storage failure',d['text'])
                elif kind=='exported':self.exporting=False;self.footer.config(text='Export saved: '+d['path'])
                elif kind=='export_error':self.exporting=False;messagebox.showerror('Export failed',d['text'])
                elif kind=='error':self.pending=False;self.record_btn.config(state='normal');messagebox.showerror('PMS Logger',d['text'])
        except queue.Empty:pass
        if self.sid:
            elapsed=int(time.monotonic()-self.rec_started);self.global_status.config(text=f"REC RECORDING {elapsed//60:02}:{elapsed%60:02} | {self.settings['mode'].upper()}")
            self.rec_label.config(text=f'{self.rec_count:,} samples  |  {self.rec_errors} errors')
        else:self.global_status.config(text=self.settings['mode'].upper()+'  |  PREVIEW')
        if self.latest and time.time()-self.latest['ts']>max(2,3*self.settings['interval']):self.reading_status.config(text='STALE  |  waiting for new reading',foreground='#b45309')
        if self.page=='Live Monitor' and self.buffer and time.monotonic()-self.last_plot>.5:
            self.last_plot=time.monotonic(); rows=list(self.buffer); end=rows[-1]['ts']; seconds={'1 min':60,'5 min':300,'30 min':1800,'Buffer':1e20}[self.window.get()]
            rows=[r for r in rows if r['ts']>=end-seconds]
            from matplotlib.ticker import FuncFormatter
            self.line.set_data([r['ts'] for r in rows],[r['value'] if r['quality']=='OK' else math.nan for r in rows]);self.lax.set_ylabel('Pressure ('+self.settings['unit']+')')
            self.lax.xaxis.set_major_formatter(FuncFormatter(lambda x,pos:stamp(x,self.settings['utc_offset'])[11:19]))
            if self.follow.get():
                self.lax.relim();self.lax.autoscale_view();self.lax.set_xlim(max(rows[0]['ts'],end-seconds),max(end,rows[0]['ts']+1))
            self.lcanvas.draw_idle()
        if self.closing:
            if not self.engine.is_alive():self.instance_lock.close();self.destroy();return
        self.after(80,self.tick)
    def close(self):
        if self.exporting:messagebox.showinfo('Export running','Please wait for the export to finish before closing.');return
        if self.sid and not messagebox.askyesno('Stop and exit?','Stop recording, save and exit?'):return
        if self.save_job:self.after_cancel(self.save_job);self.save_details()
        self.closing=True;self.engine.send('quit');self.footer.config(text='Saving and closing...')

if __name__=='__main__':
    try:
        app=App();app.mainloop()
    except Exception as exc:
        try:messagebox.showerror('PMS Logger startup error',str(exc))
        except Exception:print(exc,file=sys.stderr)
        raise
