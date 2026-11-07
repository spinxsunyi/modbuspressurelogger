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
NAVY = '#17334c'
INK = '#102b48'
TEAL = '#008b92'
TEAL_DARK = '#006e75'
BG = '#f3f6f8'
SURFACE = '#ffffff'
BORDER = '#bfcbd5'
PALE_TEAL = '#e5f5f3'
BASE=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).parent
DATA=Path(os.environ.get('PMS_LOGGER_DATA',str(BASE/'data')))

class Timeline(tk.Canvas):
    """Draw the available pressure trace and drag the visible time interval."""
    def __init__(self, parent, move):
        super().__init__(parent, height=48, background='white', highlightthickness=1,
                         highlightbackground='#c5d0dc')
        self.move = move
        self.percent = 100
        self.fraction = 1
        self.bind('<Button-1>', self.drag)
        self.bind('<B1-Motion>', self.drag)

    def drag(self, event):
        width = max(1, self.winfo_width() - 16)
        span = 1 - self.fraction
        if span > 0:
            self.percent = 100 * max(0, min(1, ((event.x - 8) / width - self.fraction / 2) / span))
            self.move(self.percent)

    def get(self):
        return self.percent

    def show_range(self, rows, left, right, offset):
        self.delete('all')
        if not rows:
            return
        first, last = rows[0]['ts'], rows[-1]['ts']
        duration = max(last - first, .001)
        width = max(1, self.winfo_width() - 16)
        def x(t):
            return 8 + width * max(0, min(1, (t-first)/duration))
        left, right = max(first, left), min(last, right)
        self.fraction = max(0, min(1, (right-left)/duration))
        self.percent = 100*(left-first)/max(.001, duration-(right-left))
        self.create_rectangle(x(left), 2, x(right), 29, fill='#c6ebe6', outline='#008b86')
        values = [r['value'] for r in rows if r['quality']=='OK' and r['value'] is not None]
        if values:
            lo, hi = min(values), max(values)
            points = []
            for r in rows[::max(1,len(rows)//500)]:
                if r['quality']=='OK' and r['value'] is not None:
                    points.extend((x(r['ts']), 25-19*(r['value']-lo)/max(.001,hi-lo)))
                else:
                    if len(points)>=4: self.create_line(*points, fill='#008b86')
                    points=[]
            if len(points)>=4: self.create_line(*points, fill='#008b86')
        label = 'Timeline    '+stamp(left,offset)[11:19]+' – '+stamp(right,offset)[11:19]
        self.create_text(8,39,text=label,anchor='w',fill='#17334c')

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('Digital Pressure Recorder 0.2'); self.geometry(f'{min(1440,self.winfo_screenwidth()-40)}x{min(900,self.winfo_screenheight()-100)}'); self.minsize(820,560)
        DATA.mkdir(parents=True,exist_ok=True)
        self.instance_lock=InstanceLock(DATA/'app.lock')
        self.exporting=False
        self.settings=dict(DEFAULTS)
        try: self.settings.update(json.loads((DATA/'settings.json').read_text()))
        except (OSError,ValueError): pass
        self.store=Store(DATA/'recordings.sqlite'); self.store.recover(); self.engine=Engine(self.store); self.engine.start()
        self.sid=None; self.detail_sid=None; self.connected=False; self.latest=None; self.buffer=deque(maxlen=7200); self.viewer_sid=None
        self.save_job=None; self.edit_loading=False; self.closing=False; self.last_plot=0; self.rec_count=0; self.rec_errors=0; self.pending=False; self.details_user_visible=True
        self.configure(bg=BG); style=ttk.Style(self); style.theme_use('clam')
        style.configure('.',font=(UI_FONT,10),background=BG,foreground=INK)
        style.configure('TFrame',background=BG)
        style.configure('TLabel',background=BG,foreground=INK)
        style.configure('TButton',padding=(12,8),background='#edf2f6',foreground=INK,borderwidth=1)
        style.map('TButton',background=[('pressed','#cddde7'),('active','#dce8ef')])
        style.configure('Accent.TButton',background=TEAL,foreground='white',padding=(14,9),font=(UI_FONT,10,'bold'))
        style.map('Accent.TButton',background=[('pressed',TEAL_DARK),('active',TEAL_DARK)],
                  foreground=[('disabled','#6d818b'),('!disabled','white')])
        style.configure('Stop.TButton',background='#d52e36',foreground='white',padding=(14,9),font=(UI_FONT,10,'bold'))
        style.map('Stop.TButton',background=[('pressed','#a91d27'),('active','#bd232e')])
        style.configure('Section.TLabel',background=NAVY,foreground='white',padding=(12,8),font=(UI_FONT,11,'bold'))
        style.configure('TEntry',fieldbackground=SURFACE,padding=4)
        style.configure('TCombobox',fieldbackground=SURFACE,padding=3)
        style.configure('Treeview',rowheight=30,background=SURFACE,fieldbackground=SURFACE,foreground=INK)
        style.map('Treeview',background=[('selected',TEAL)],foreground=[('selected','white')])
        style.configure('Treeview.Heading',font=(UI_FONT,10,'bold'),background='#e8eef3',foreground=INK,padding=(8,7))
        style.configure('Title.TLabel',font=(UI_FONT,20,'bold'))
        style.configure('TLabelframe',background=BG,relief='solid',borderwidth=1)
        style.configure('TLabelframe.Label',font=(UI_FONT,11,'bold'),foreground=NAVY,background=BG)
        nav=tk.Frame(self,bg='#17334c'); nav.pack(fill='x')
        self.brand=tk.Label(nav,text='Digital Pressure Recorder',font=(UI_FONT,20,'bold'),bg=NAVY,fg='white',padx=18,pady=10); self.brand.pack(side='left')
        self.nav_buttons={}
        for page in ['Live Monitor','History','Settings','About']:
            button=tk.Button(nav,text=page,command=lambda p=page:self.show(p),bg=NAVY,fg='white',activebackground=TEAL_DARK,activeforeground='white',relief='flat',bd=0,padx=15,pady=12,font=(UI_FONT,10))
            button.pack(side='left'); self.nav_buttons[page]=button
        self.global_status=tk.Label(nav,text='SIMULATION',bg='#17334c',fg='#ffcb72',padx=15); self.global_status.pack(side='right')
        self.credit=tk.Label(self,text='Created by Eka Yudhi Pratama  •  November 2026',bg='#17334c',fg='white')
        self.credit.pack(side='bottom',fill='x')
        self.host=ttk.Frame(self,padding=14); self.host.pack(fill='both',expand=True)
        self.pages={name:ttk.Frame(self.host) for name in ['Live Monitor','History','Settings','Viewer']}
        self.footer=ttk.Label(self,text='Ready',padding=8); self.footer.pack(fill='x')
        self.make_live(); self.make_history(); self.make_settings(); self.make_viewer(); self.enhance(); self.show('Live Monitor')
        self.protocol('WM_DELETE_WINDOW',self.close); self.after(50,self.tick)
        if self.settings.get('auto_connect') and (self.settings['mode']=='Simulation' or self.settings['port']): self.after(200,self.connect)
    def show(self,name):
        if name=='About':
            self.show('Settings'); return
        for p in self.pages.values(): p.pack_forget()
        self.pages[name].pack(fill='both',expand=True); self.page=name
        for key,button in self.nav_buttons.items(): button.config(bg=TEAL if key==('History' if name=='Viewer' else name) else NAVY)
        if name=='History': self.refresh_history()
    def plot(self,parent):
        fig=Figure(figsize=(4,2),dpi=100,facecolor='white'); ax=fig.add_subplot(111); fig.subplots_adjust(left=.09,right=.98,bottom=.15,top=.92)
        canvas=FigureCanvasTkAgg(fig,master=parent); canvas.get_tk_widget().pack(fill='both',expand=True)
        return fig,ax,canvas
    def chart_tools(self,canvas,parent,live):
        tools=NavigationToolbar2Tk(canvas,parent,pack_toolbar=False)
        bar=ttk.Frame(parent)
        bar.pack(side='bottom',fill='x')
        def zoom(factor):
            ax=canvas.figure.axes[0]
            lo,hi=ax.get_xlim()
            center=(lo+hi)/2
            radius=(hi-lo)*factor/2
            if live: self.follow.set(False)
            ax.set_xlim(center-radius,center+radius)
            canvas.draw_idle()
        def reset():
            if live:
                self.live_auto.set(True)
                self.follow.set(True)
                self.lax.set_autoscaley_on(True)
            else:
                self.history_window.set('All time')
                self.auto_history_scale()
                self.slide_history(0)
        for label,cmd in [('Reset view',reset),('Zoom −',lambda:zoom(1.5)),('Zoom +',lambda:zoom(2/3)),('Pan',tools.pan)]:
            ttk.Button(bar,text=label,command=cmd).pack(side='right',padx=2)

    def auto_history_scale(self):
        valid=[r['value'] for r in self.vrows if r['quality']=='OK' and r['value'] is not None]
        if valid:
            lo,hi=min(valid),max(valid)
            pad=max((hi-lo)*.05,.01)
            self.view_vars['ymin'].set(str(lo-pad))
            self.view_vars['ymax'].set(str(hi+pad))
            self.paint_viewer()

    def make_live(self):
        p=self.pages['Live Monitor']; top=ttk.Frame(p); top.pack(fill='x')
        self.connection=ttk.Label(top,text='Waiting for device'); self.connection.pack(side='left')
        self.connect_btn=ttk.Button(top,text='Connect',command=self.toggle_connect); self.connect_btn.pack(side='left',padx=12)
        self.drop=tk.BooleanVar(); ttk.Checkbutton(top,text='Simulate disconnect',variable=self.drop,command=lambda:self.engine.send('drop',self.drop.get())).pack(side='right')
        body=ttk.Panedwindow(p,orient='horizontal'); body.pack(fill='both',expand=True,pady=10)
        main=ttk.Frame(body); self.details_panel=ttk.LabelFrame(body,text='Recording details  |  autosaved',padding=12); body.add(main,weight=4); body.add(self.details_panel,weight=1); self.live_pane=body
        readings=ttk.Frame(main);readings.pack(fill='x',pady=(2,10))
        for col in range(3):readings.columnconfigure(col,weight=1,uniform='metric')
        def metric_card(column,title,highlight=False):
            bg=PALE_TEAL if highlight else SURFACE
            panel=tk.Frame(readings,bg=bg,highlightthickness=1,
                           highlightbackground='#a9d6d4' if highlight else BORDER)
            panel.grid(row=0,column=column,sticky='nsew',padx=(0,8) if column<2 else (0,0))
            tk.Label(panel,text=title,bg=bg,fg=NAVY,font=(UI_FONT,11,'bold'),
                     anchor='w').pack(fill='x',padx=12,pady=(9,2))
            return panel,bg
        live_card,live_bg=metric_card(0,'Live pressure',True)
        self.value=tk.Label(live_card,text='—',font=(UI_FONT,27,'bold'),bg=live_bg,
                            fg=TEAL_DARK,anchor='w')
        self.value.pack(fill='x',padx=12)
        self.reading_status=tk.Label(live_card,text='Waiting for first reading',
                                     bg=live_bg,fg=INK,font=(UI_FONT,9),anchor='w')
        self.reading_status.pack(fill='x',padx=12,pady=(0,10))
        self.metric=[]
        for col,title in [(1,'Recording minimum'),(2,'Recording maximum')]:
            panel,panel_bg=metric_card(col,title)
            label=tk.Label(panel,text='—',bg=panel_bg,fg=NAVY,
                           font=(UI_FONT,20,'bold'),anchor='w')
            label.pack(fill='x',padx=12,pady=(4,20))
            self.metric.append(label)
        toolbar=ttk.Frame(main); toolbar.pack(fill='x',pady=6)
        self.follow=tk.BooleanVar(value=True); ttk.Checkbutton(toolbar,text='Auto-follow',variable=self.follow).pack(side='left')
        ttk.Label(toolbar,text='Time window').pack(side='left',padx=4)
        self.window=tk.StringVar(value='5 min'); ttk.Combobox(toolbar,textvariable=self.window,values=['1 min','5 min','10 min','15 min','30 min','1 hour','All time'],state='readonly',width=10).pack(side='left',padx=8)
        ttk.Button(toolbar,text='Go to Live',command=lambda:self.follow.set(True)).pack(side='left')
        ttk.Button(toolbar,text='Details +/-',command=self.toggle_details).pack(side='right')
        self.lfig,self.lax,self.lcanvas=self.plot(main); self.lax.set(xlabel='Time',ylabel='Pressure'); self.lax.grid(alpha=.2)
        self.line,=self.lax.plot([],[],color='#008b92',lw=1.2)
        self.lcanvas.mpl_connect('button_press_event',lambda e:self.follow.set(False) if e.inaxes else None)
        self.chart_tools(self.lcanvas,main,True)
        controls=ttk.Frame(main); controls.pack(side='bottom',before=readings,fill='x',pady=4)
        self.record_btn=ttk.Button(controls,text='Start recording',style='Accent.TButton',command=self.record); self.record_btn.pack(side='left')
        self.event_btn=ttk.Button(controls,text='+ Add Event',command=self.add_live_event,state='disabled'); self.event_btn.pack(side='left',padx=10)
        self.rec_label=ttk.Label(controls,text='Preview only  |  not saved'); self.rec_label.pack(side='left')
        self.detail_vars={}; self.detail_entries=[]
        self.session_name=ttk.Label(self.details_panel,text='Press Record to create a session',wraplength=250); self.session_name.pack(anchor='w',pady=(0,8))
        form=ttk.Frame(self.details_panel);form.pack(fill='x')
        form.columnconfigure(1,weight=1)
        for index,k in enumerate(FIELDS):
            ttk.Label(form,text=k.replace('_',' ').title()).grid(row=index,column=0,sticky='nw',padx=(0,5),pady=4)
            v=tk.StringVar()
            self.detail_vars[k]=v
            if k=='notes':
                en=tk.Text(form,width=18,height=4,wrap='word',state='disabled',font=(UI_FONT,10))
                self.notes=en
                en.bind('<<Modified>>',self.notes_changed)
            else:
                en=ttk.Entry(form,textvariable=v,width=18,state='disabled')
            en.grid(row=index,column=1,sticky='ew',pady=3)
            if k=='job_date':
                ttk.Button(form,text='▾',width=2,command=self.pick_date).grid(row=index,column=2)
            self.detail_entries.append(en)
            v.trace_add('write',self.schedule_save)
        self.saved=ttk.Label(self.details_panel,text=''); self.saved.pack(anchor='w')
    def notes_changed(self,event):
        if self.notes.edit_modified():
            self.notes.edit_modified(False)
            self.detail_vars['notes'].set(self.notes.get('1.0','end-1c'))

    def pick_date(self):
        if not self.detail_sid: return
        import calendar
        from datetime import date
        try: current=date.fromisoformat(self.detail_vars['job_date'].get())
        except ValueError: current=date.today()
        dialog=tk.Toplevel(self);dialog.title('Job date');dialog.transient(self)
        def choose(day):
            self.detail_vars['job_date'].set(day.isoformat())
            dialog.destroy()
        def draw(year,month):
            for child in dialog.winfo_children(): child.destroy()
            for col,delta,label in [(0,-1,'‹'),(6,1,'›')]:
                index=year*12+month-1+delta
                ttk.Button(dialog,text=label,width=3,command=lambda i=index:draw(i//12,i%12+1)).grid(row=0,column=col)
            ttk.Label(dialog,text=f'{calendar.month_name[month]} {year}').grid(row=0,column=1,columnspan=5)
            for col,name in enumerate(calendar.day_abbr): ttk.Label(dialog,text=name).grid(row=1,column=col)
            for row,week in enumerate(calendar.monthcalendar(year,month),2):
                for col,n in enumerate(week):
                    if n: ttk.Button(dialog,text=str(n),width=3,command=lambda n=n:choose(date(year,month,n))).grid(row=row,column=col)
        draw(current.year,current.month)
    def toggle_details(self):
        visible=str(self.details_panel) in self.live_pane.panes()
        self.details_user_visible=not visible
        if visible:self.live_pane.forget(self.details_panel)
        else:self.live_pane.add(self.details_panel,weight=1)
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
        self.notes.delete('1.0','end');self.notes.insert('1.0',d.get('notes',''));self.notes.edit_modified(False)
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
            self.history.tag_configure('alternate',background='#edf4f6')
            self.history.insert('', 'end',iid=s['id'],tags=('alternate',) if len(self.history.get_children())%2 else (),values=(stamp(s['started'],self.settings['utc_offset'])[:19].replace('T',' '),d.get('well') or s['name'],d.get('job',''),f"{max(0,end-s['started'])/60:.1f} min",s['mode'],s['state']))
    def open_selected(self):
        sel=self.history.selection()
        if sel:self.load_viewer(sel[0])
    def make_settings(self):
        p=self.pages['Settings']; ttk.Label(p,text='Settings',style='Title.TLabel').pack(anchor='w',pady=8)
        ttk.Label(p,text='Connection and unit changes apply after reconnecting. Stop recording before applying settings.').pack(anchor='w')
        columns=ttk.Frame(p);columns.pack(fill='x',pady=5)
        grid=ttk.LabelFrame(columns,text='Device connection',padding=8);grid.grid(row=0,column=0,sticky='ew')
        display=ttk.LabelFrame(columns,text='Acquisition & display',padding=8);display.grid(row=1,column=0,sticky='ew')
        about=ttk.LabelFrame(columns,text='About',padding=14);about.grid(row=0,column=1,rowspan=2,sticky='nsew',padx=12)
        ttk.Label(about,text='Digital Pressure Recorder',font=(UI_FONT,16,'bold')).pack(anchor='w')
        ttk.Label(about,text='Aplisens PMS-970 / Modbus RTU').pack(anchor='w',pady=8)
        ttk.Label(about,text='Created by Eka Yudhi Pratama\nNovember 2026').pack(anchor='w')
        for label,color in [('LIVE','#137a45'),('DISCONNECTED','#b55c00'),('RECORDING','#c92c38'),('REC OFF','#576677')]:
            tk.Label(about,text='● '+label,fg=color).pack(anchor='w',pady=2)
        self.config_vars={}
        choices={'mode':['Simulation','Modbus RTU'],'baud':[2400,4800,9600,19200],'parity':['E','N','O'],'stopbits':[1,2],'interval':[.5,1,.2,.1],'unit':['psi','bar','kPa','MPa'],'utc_offset':[7,8,0]}
        for n,k in enumerate(['mode','port','baud','parity','stopbits','address','interval','unit','utc_offset']):
            parent=grid if n<6 else display
            ttk.Label(parent,text={'utc_offset':'UTC offset','interval':'Interval (seconds)','baud':'Baud rate','stopbits':'Stop bits'}.get(k,k.title())).grid(row=n,column=0,sticky='w',padx=8,pady=2)
            v=tk.StringVar(value=str(self.settings[k])); self.config_vars[k]=v
            if k=='port':
                en=ttk.Combobox(parent,textvariable=v,state='readonly',width=30); self.port_combo=en
            elif k in choices:en=ttk.Combobox(parent,textvariable=v,values=choices[k],state='readonly',width=30)
            else:en=ttk.Entry(parent,textvariable=v,width=32)
            en.grid(row=n,column=1,sticky='ew')
        ttk.Button(grid,text='Refresh ports',command=self.find_ports).grid(row=1,column=2,padx=10)
        self.port_count=ttk.Label(grid);self.port_count.grid(row=2,column=2)
        self.auto=tk.BooleanVar(value=self.settings['auto_connect']); ttk.Checkbutton(p,text='Auto-connect last configuration at startup',variable=self.auto).pack(anchor='w',pady=8)
        ttk.Label(p,text='Hardware profile: PMS-970  |  FC03  |  address 0x0001  |  readout + status\nUnit labels must match the meter; this version does not convert pressure units.\nDevice communication confirmed by user at 9600 baud, November 2026.\n\nData: '+str(DATA),wraplength=900).pack(anchor='w',pady=12)
        ttk.Button(p,text='Save and reconnect',command=self.apply_settings,style='Accent.TButton').pack(anchor='w')
    def find_ports(self):
        from serial.tools.list_ports import comports
        ports=list(comports()); names=[p.device+' — '+p.description for p in ports]
        self.port_combo.configure(values=names)
        previous=self.config_vars['port'].get().split(' — ',1)[0]
        self.config_vars['port'].set(next((n for n in names if n.split(' — ',1)[0]==previous),names[0] if names else ''))
        self.port_count.config(text=f'{len(names)} ports detected')
    def apply_settings(self):
        if self.sid or self.pending:messagebox.showinfo('Recording','Stop recording before changing settings.');return
        try:
            s={k:v.get() for k,v in self.config_vars.items()}
            s['port']=s['port'].split(' — ',1)[0]
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
        self.vfig,self.vax,self.vcanvas=self.plot(left); self.chart_tools(self.vcanvas,left,False)
        self.vcanvas.mpl_connect('button_press_event',self.chart_click)
        ttk.Label(left,text='Click chart to capture annotation time. Toolbar: pan / zoom / reset.').pack(anchor='w')
        self.events_tree=ttk.Treeview(left,columns=('minute','label','kind'),show='headings',height=4)
        for col in ('minute','label','kind'):self.events_tree.heading(col,text='Time' if col=='minute' else col.title())
        self.events_tree.pack(fill='x'); self.events_tree.bind('<Double-1>',lambda e:self.edit_annotation())
        self.viewer_details=ttk.Label(right,wraplength=270,justify='left')
        ttk.Label(right,text='Job details & report',style='Section.TLabel').pack(fill='x')
        self.viewer_details.pack(anchor='w',pady=4)
        self.view_vars={}
        for k,label,default in [('title','Report title',''),('xmin','From (elapsed minutes)','0'),('xmax','To (elapsed minutes)','1'),('ymin','Pressure minimum','0'),('ymax','Pressure maximum','3000')]:
            v=tk.StringVar(value=default); self.view_vars[k]=v
            if k in ('ymin','ymax'): continue
            ttk.Label(right,text=label).pack(anchor='w'); ttk.Entry(right,textvariable=v,width=26).pack(fill='x',pady=(2,8))
        ttk.Button(right,text='Apply scale / Save view',command=self.apply_view).pack(fill='x',pady=4)
        ttk.Button(right,text='Use current view',command=self.capture_view).pack(fill='x',pady=4)
        ttk.Button(right,text='Edit job details',command=self.edit_viewer_details).pack(fill='x',pady=4)
        ttk.Separator(right).pack(fill='x',pady=12)
        ttk.Label(right,text='Annotations',style='Section.TLabel').pack(fill='x')
        ttk.Button(right,text='Edit selected',command=self.edit_annotation).pack(fill='x')
        self.annotation_time=tk.StringVar(value='0'); ttk.Label(right,text='Annotation time (elapsed minutes)').pack(anchor='w'); ttk.Entry(right,textvariable=self.annotation_time).pack(fill='x')
        ttk.Button(right,text='+ Add review annotation',command=self.add_annotation).pack(fill='x',pady=6)
        ttk.Label(right,text='Export',style='Section.TLabel').pack(fill='x')
        self.selected_export=tk.BooleanVar(); ttk.Checkbutton(right,text='Export selected time range',variable=self.selected_export).pack(anchor='w',pady=8)
        exports=ttk.Frame(right);exports.pack(fill='x');exports.columnconfigure((0,1),weight=1)
        for n,fmt in enumerate(['xlsx','csv','pdf','png']):ttk.Button(exports,text='Export '+fmt.upper(),command=lambda f=fmt:self.do_export(f)).grid(row=n//2,column=n%2,sticky='ew',padx=2,pady=3)
    def load_viewer(self,sid):
        if not sid:return
        self.viewer_sid=sid; self.vsession=self.store.get(sid); self.vrows=self.store.plot_rows(sid); self.vevents=self.store.events(sid)
        d=json.loads(self.vsession['details']); self.viewer_title.config(text=(d.get('well') or 'Unnamed well')+'  |  '+(d.get('job') or 'Recording'))
        self.viewer_details.config(text='\n'.join(f'{k.replace("_"," ").title()}: {d.get(k) or "—"}' for k in ('well','job','job_id','engineer','client','job_date')))
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
        from matplotlib.ticker import FuncFormatter
        ax.xaxis.set_major_formatter(FuncFormatter(lambda x,pos:stamp(start+x*60,self.settings['utc_offset'])[11:19]))
        ax.set(xlabel='Time',ylabel='Pressure ('+self.vsession['unit']+')',title=v['title'],xlim=(v['xmin'],v['xmax']),ylim=(v['ymin'],v['ymax'])); ax.grid(alpha=.2)
        for i in self.events_tree.get_children():self.events_tree.delete(i)
        for e in self.vevents:
            x=(e['ts']-start)/60; ax.axvline(x,ls='--',lw=.7,color='#bd7b1c')
            annotation=ax.annotate(e['label'] if self.history_labels.get() else '',(x,.95),xycoords=('data','axes fraction'),rotation=0,va='top',fontsize=8,bbox=dict(facecolor='#fff0b6',edgecolor='#d6ad45',pad=2),clip_on=True); annotation.draggable()
            self.events_tree.insert('','end',iid=str(e['id']),values=(stamp(e['ts'],self.settings['utc_offset'])[11:19],e['label'],e['kind']))
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
                    self.last_recording=d['sid'];self.sid=d['sid'];self.pending=False;self.rec_started=time.monotonic();self.rec_count=0;self.rec_errors=0;self.record_btn.config(text='Stop recording',style='Stop.TButton',state='normal');self.event_btn.config(state='normal');self.load_details(self.sid)
                elif kind in ('stopped','storage_error'):
                    self.sid=None;self.pending=False;self.record_btn.config(text='Start recording',style='Accent.TButton',state='normal');self.event_btn.config(state='disabled');self.rec_label.config(text='Preview only  |  not saved')
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
            self.last_plot=time.monotonic(); rows=list(self.buffer); end=rows[-1]['ts']; seconds={'1 min':60,'5 min':300,'10 min':600,'15 min':900,'30 min':1800,'1 hour':3600,'All time':1e20}[self.window.get()]
            rows=[r for r in rows if r['ts']>=end-seconds] if self.follow.get() else rows
            from matplotlib.ticker import FuncFormatter
            self.line.set_data([r['ts'] for r in rows],[r['value'] if r['quality']=='OK' else math.nan for r in rows]);self.lax.set_ylabel('Pressure ('+self.settings['unit']+')')
            self.lax.xaxis.set_major_formatter(FuncFormatter(lambda x,pos:stamp(x,self.settings['utc_offset'])[11:19]))
            if self.follow.get():
                self.lax.set_autoscaley_on(self.live_auto.get());self.lax.relim();self.lax.autoscale_view(scaley=self.live_auto.get());self.lax.set_xlim(max(rows[0]['ts'],end-seconds),max(end,rows[0]['ts']+1))
            self.lcanvas.draw_idle()
        self.update_enhancements()
        if self.closing:
            if not self.engine.is_alive():self.instance_lock.close();self.destroy();return
        self.after(80,self.tick)
    def close(self):
        if self.exporting:messagebox.showinfo('Export running','Please wait for the export to finish before closing.');return
        if self.sid and not messagebox.askyesno('Stop and exit?','Stop recording, save and exit?'):return
        if self.save_job:self.after_cancel(self.save_job);self.save_details()
        self.closing=True;self.engine.send('quit');self.footer.config(text='Saving and closing...')

    def enhance(self):
        self.last_recording=None; self.enhanced_last=0; self.live_artists=[]
        self.global_status.pack_forget()
        self.status_live=tk.Label(self.global_status.master,text='DISCONNECTED',foreground='#b45309')
        self.status_live.pack(side='right',padx=12)
        self.status_rec=tk.Label(self.global_status.master,text='REC OFF',foreground='#777777'); self.status_rec.pack(side='right',padx=12)
        self.bind('<Configure>', self.adapt_width, add='+')
        bar=ttk.Frame(self.lcanvas.get_tk_widget().master);bar.pack(before=self.lcanvas.get_tk_widget(),fill='x')
        self.live_min=tk.StringVar(value='0');self.live_max=tk.StringVar(value='3000');self.live_auto=tk.BooleanVar(value=True)
        for label,var in [('Pressure min',self.live_min),('Pressure max',self.live_max)]:
            ttk.Label(bar,text=label).pack(side='left');ttk.Entry(bar,textvariable=var,width=9).pack(side='left',padx=5)
        ttk.Button(bar,text='Apply',command=self.apply_live_scale).pack(side='left')
        ttk.Checkbutton(bar,text='Auto scale',variable=self.live_auto,command=lambda:self.lax.set_autoscaley_on(self.live_auto.get())).pack(side='left')
        self.live_labels=tk.BooleanVar(value=True);ttk.Checkbutton(bar,text='Show event labels',variable=self.live_labels,command=self.paint_live_events).pack(side='left')
        self.live_slider=Timeline(self.lcanvas.get_tk_widget().master,self.slide_live)
        self.live_slider.pack(after=self.lcanvas.get_tk_widget(),fill='x')
        self.live_events=ttk.Treeview(self.lcanvas.get_tk_widget().master,columns=('time','event'),show='headings',height=2)
        self.live_events.heading('time',text='Time');self.live_events.heading('event',text='Event');self.live_events.pack(after=self.live_slider,fill='x')
        self.live_events.insert('','end',iid='empty',values=('','No events yet'))
        self.live_events.bind('<<TreeviewSelect>>',self.select_live_event)
        self.live_events.bind('<Double-1>',self.edit_live_event)
        viewer=self.pages['Viewer']
        summary=ttk.Frame(viewer)
        summary.pack(before=viewer.winfo_children()[1],fill='x')
        self.viewer_metrics=[]
        for index,title in enumerate(('Recording minimum','Recording maximum','Duration')):
            summary.columnconfigure(index,weight=1,uniform='summary')
            tk.Label(summary,text=title,anchor='w',bg='white',fg='#17334c',padx=8).grid(row=0,column=index,sticky='ew',padx=2)
            label=tk.Label(summary,text='—',bg='white',fg='#17334c',font=(UI_FONT,16,'bold'),anchor='w',padx=8)
            label.grid(row=1,column=index,sticky='ew',padx=2)
            self.viewer_metrics.append(label)
        bar=ttk.Frame(self.vcanvas.get_tk_widget().master);bar.pack(before=self.vcanvas.get_tk_widget(),fill='x')
        self.history_window=tk.StringVar(value='All time')
        ttk.Label(bar,text='Time window').pack(side='left')
        box=ttk.Combobox(bar,textvariable=self.history_window,values=['1 min','5 min','10 min','15 min','30 min','1 hour','All time'],state='readonly',width=12)
        box.pack(side='left');box.bind('<<ComboboxSelected>>',lambda e:self.slide_history(0))
        ttk.Button(bar,text='Auto scale',command=self.auto_history_scale).pack(side='left',padx=4)
        for key,title in [('ymin','Min'),('ymax','Max')]:
            ttk.Label(bar,text=title).pack(side='left')
            ttk.Entry(bar,textvariable=self.view_vars[key],width=6).pack(side='left')
        ttk.Button(bar,text='Apply',command=self.apply_view).pack(side='left')
        self.history_labels=tk.BooleanVar(value=True)
        ttk.Checkbutton(bar,text='Show event labels',variable=self.history_labels,command=self.paint_viewer).pack(side='left')
        self.history_slider=Timeline(self.vcanvas.get_tk_widget().master,self.slide_history)
        self.history_slider.pack(after=self.vcanvas.get_tk_widget(),fill='x')
        self.events_tree.bind('<<TreeviewSelect>>',self.select_history_event)
        self.lcanvas.mpl_connect('motion_notify_event',lambda e:self.hover(e,False))
        self.vcanvas.mpl_connect('motion_notify_event',lambda e:self.hover(e,True))
        self.ltip=None;self.vtip=None;self.hover_artists={}
        for canvas in (self.lcanvas,self.vcanvas):
            widget=canvas.get_tk_widget()
            widget.pack_forget()
            # Bottom controls and navigator claim their space before the flexible plot.
            siblings = [self.live_events,self.live_slider] if canvas==self.lcanvas else [self.events_tree,self.history_slider]
            for item in siblings:
                item.pack_forget()
                item.pack(side='bottom',fill='x')
            widget.pack(fill='both',expand=True)
        self.find_ports()

    def adapt_width(self,event):
        if event.widget!=self: return
        compact=event.width<1150
        if compact!=getattr(self,'compact',None):
            self.compact=compact
            self.brand.config(font=(UI_FONT,14 if compact else 20,'bold'),padx=6 if compact else 20)
            for button in self.nav_buttons.values():button.config(padx=6 if compact else 18)
            visible=str(self.details_panel) in self.live_pane.panes()
            if compact and visible: self.live_pane.forget(self.details_panel)
            elif not compact and not visible: self.live_pane.add(self.details_panel,weight=1)

    def apply_live_scale(self):
        try:
            lo,hi=float(self.live_min.get()),float(self.live_max.get())
            if not math.isfinite(lo) or not math.isfinite(hi) or lo>=hi:raise ValueError('Minimum must be less than maximum; use finite numbers.')
            self.live_auto.set(False);self.lax.set_ylim(lo,hi);self.lcanvas.draw_idle()
        except ValueError as exc:messagebox.showerror('Pressure scale',str(exc))

    def window_seconds(self,name):
        return {'1 min':60,'5 min':300,'10 min':600,'15 min':900,'30 min':1800,'1 hour':3600,'All time':float('inf')}[name]

    def slide_live(self,value):
        if not self.buffer:return
        lo,hi=self.buffer[0]['ts'],self.buffer[-1]['ts']; width=min(self.window_seconds(self.window.get()),max(hi-lo,1))
        start=lo+max(0,hi-lo-width)*float(value)/100
        self.follow.set(False);self.lax.set_xlim(start,start+width)
        rows=list(self.buffer);self.line.set_data([r['ts'] for r in rows],[r['value'] if r['quality']=='OK' else math.nan for r in rows])
        self.lcanvas.draw_idle()

    def slide_history(self,value):
        if not self.viewer_sid or not self.vrows:return
        duration=max((self.vrows[-1]['ts']-self.vsession['started'])/60,.01)
        width=min(duration,self.window_seconds(self.history_window.get())/60)
        start=max(0,duration-width)*float(value)/100
        self.view_vars['xmin'].set(str(start));self.view_vars['xmax'].set(str(start+width));self.paint_viewer()

    def hover(self,event,history):
        ax=self.vax if history else self.lax;canvas=self.vcanvas if history else self.lcanvas
        attr='vtip' if history else 'ltip';old=getattr(self,attr,None)
        for artist in self.hover_artists.pop(attr,()):
            try:artist.remove()
            except (ValueError,NotImplementedError):pass
        if old is not None:
            try:old.remove()
            except (ValueError,NotImplementedError):pass
            setattr(self,attr,None)
        if event.inaxes!=ax or event.xdata is None:canvas.draw_idle();return
        events=self.vevents if history and self.viewer_sid else self.store.events(self.last_recording) if not history and self.last_recording else []
        base=self.vsession['started'] if history and self.viewer_sid else 0
        target=base+event.xdata*60 if history else event.xdata
        def xpos(ts):return (ts-base)/60 if history else ts
        near=next((e for e in events if abs(ax.transData.transform((xpos(e['ts']),0))[0]-event.x)<8),None)
        if near:text=stamp(near['ts'],self.settings['utc_offset'])+'\n'+near['label'];x=event.xdata;y=event.ydata
        else:
            if history:
                if not self.viewer_sid:return
                with self.store.connect() as c:
                    rows=[dict(r) for r in c.execute('SELECT * FROM samples WHERE session=? AND ts BETWEEN ? AND ? ORDER BY ts',(self.viewer_sid,target-5,target+5))]
            else:rows=list(self.buffer)
            if not rows:canvas.draw_idle();return
            row=min(rows,key=lambda r:abs(r['ts']-target));x=xpos(row['ts']);y=row['value']
            if row['quality']!='OK' or y is None:canvas.draw_idle();return
            unit=self.vsession['unit'] if history else self.settings['unit']
            text=f"Time: {stamp(row['ts'],self.settings['utc_offset'])[11:23]}\nPressure: {y:,.2f} {unit}"
        if not near:
            marker,=ax.plot([x],[y],'o',color='#008b86',ms=5)
            guide=ax.axvline(x,color='#66798a',ls='--',lw=.7)
            self.hover_artists[attr]=(marker,guide)
        tip=ax.annotate(text,(x,y),xytext=(-12 if event.x>ax.bbox.xmax-160 else 12,-16 if event.y>ax.bbox.ymax-60 else 16),ha='right' if event.x>ax.bbox.xmax-160 else 'left',va='top' if event.y>ax.bbox.ymax-60 else 'bottom',textcoords='offset points',bbox=dict(boxstyle='round',fc='white',ec='#17334c'),fontsize=9)
        setattr(self,attr,tip);canvas.draw_idle()

    def recording_extrema(self,sid):
        with self.store.connect() as c:
            return c.execute("SELECT min(value),max(value) FROM samples WHERE session=? AND quality='OK'",(sid,)).fetchone()

    def update_enhancements(self):
        valid=self.connected and self.latest and self.latest['quality']=='OK' and time.time()-self.latest['ts']<=max(2,3*self.settings['interval'])
        self.status_live.config(text=('SIMULATION' if self.settings['mode']=='Simulation' else '● LIVE') if valid else 'DISCONNECTED / NO DATA',bg=('#415875' if self.settings['mode']=='Simulation' else '#137a45') if valid else '#b55c00',fg='white',padx=8,pady=4)
        self.status_rec.config(text=f'● REC {int(time.monotonic()-self.rec_started)//60:02}:{int(time.monotonic()-self.rec_started)%60:02}' if self.sid else 'REC OFF',bg='#c92c38' if self.sid else '#576677',fg='white',padx=8,pady=4)
        if time.monotonic()-self.enhanced_last<1:return
        self.enhanced_last=time.monotonic()
        if self.page=='Live Monitor' and self.buffer:
            self.live_slider.show_range(list(self.buffer),*self.lax.get_xlim(),self.settings['utc_offset'])
        if self.page=='Viewer' and self.viewer_sid:
            bounds=[self.vsession['started']+m*60 for m in self.vax.get_xlim()]
            self.history_slider.show_range(self.vrows,*bounds,self.settings['utc_offset'])
        if self.last_recording:
            lo,hi=self.recording_extrema(self.last_recording)
            for label,value in zip(self.metric,(lo,hi)):
                label.config(text='—' if value is None else f'{value:,.2f} {self.store.get(self.last_recording)["unit"]}')
            self.paint_live_events()
        if self.viewer_sid:
            lo,hi=self.recording_extrema(self.viewer_sid)
            seconds=int(max(0,(self.vsession['ended'] or time.time())-self.vsession['started']))
            for widget,value in zip(self.viewer_metrics[:2],(lo,hi)):
                widget.config(text='—' if value is None else f'{value:,.2f} {self.vsession["unit"]}')
            self.viewer_metrics[2].config(text=f'{seconds//60} min {seconds%60:02} sec')

    def paint_live_events(self):
        for artist in self.live_artists:
            try:artist.remove()
            except ValueError:pass
        self.live_artists=[]
        if not self.last_recording:return
        events=self.store.events(self.last_recording)
        for e in events:
            self.live_artists.append(self.lax.axvline(e['ts'],color='#bd7b1c',ls='--',lw=.8))
            if self.live_labels.get():self.live_artists.append(self.lax.annotate(e['label'],(e['ts'],.95),xycoords=('data','axes fraction'),rotation=0,va='top',fontsize=8,bbox=dict(facecolor='#fff0b6',edgecolor='#d6ad45',pad=2),clip_on=True))
        existing=set(self.live_events.get_children());wanted={str(e['id']) for e in events}
        if not events: wanted.add('empty')
        for key in existing-wanted:self.live_events.delete(key)
        if not events and 'empty' not in existing:
            self.live_events.insert('','end',iid='empty',values=('','No events yet'))
        for e in events:
            key=str(e['id']);values=(stamp(e['ts'],self.settings['utc_offset'])[11:23],e['label'])
            if key in existing:self.live_events.item(key,values=values)
            else:self.live_events.insert('','end',iid=key,values=values)
        self.lcanvas.draw_idle()

    def select_live_event(self,event=None):
        selected=self.live_events.selection()
        if not selected or selected[0]=='empty':return
        e=next(e for e in self.store.events(self.last_recording) if str(e['id'])==selected[0])
        width=self.lax.get_xlim()[1]-self.lax.get_xlim()[0];self.follow.set(False)
        self.slide_live(self.live_slider.get());self.lax.set_xlim(e['ts']-width/2,e['ts']+width/2);self.lcanvas.draw_idle()

    def edit_live_event(self,event=None):
        selected=self.live_events.selection()
        if not selected or selected[0]=='empty':return
        e=next(e for e in self.store.events(self.last_recording) if str(e['id'])==selected[0])
        text=simpledialog.askstring('Edit event','Label:',initialvalue=e['label'],parent=self)
        if text:self.store.edit_event(e['id'],e['ts'],text);self.paint_live_events()

    def select_history_event(self,event=None):
        selected=self.events_tree.selection()
        if not selected or selected[0]=='empty':return
        e=next(e for e in self.vevents if str(e['id'])==selected[0]);center=(e['ts']-self.vsession['started'])/60
        lo,hi=self.vax.get_xlim();width=hi-lo;self.vax.set_xlim(center-width/2,center+width/2);self.vcanvas.draw_idle()

if __name__=='__main__':
    try:
        app=App();app.mainloop()
    except Exception as exc:
        try:messagebox.showerror('PMS Logger startup error',str(exc))
        except Exception:print(exc,file=sys.stderr)
        raise
