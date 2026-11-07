from __future__ import annotations
import json, math, os, sys, time, queue, threading, ctypes
from pathlib import Path
from collections import deque
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
from core import DEFAULTS,FIELDS,Store,Engine
from units import from_psi,to_psi
from instance import InstanceLock
from exports import export,stamp
from report_page import report_figure,graph_figure
from app_icon import set_window_icon

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

class TimeScrollbar(ttk.Scrollbar):
    """Native-feeling time scrollbar: update the thumb before chart rendering."""
    def __init__(self,parent,move):
        super().__init__(parent,orient='horizontal',command=self.on_scroll)
        self.move=move
        self.percent=100.0
        self.fraction=1.0
        self._pending=None
        self._target=None

    def on_scroll(self,*args):
        span=max(0.0,1.0-self.fraction)
        if span<=1e-9:return
        start=self.percent/100.0*span
        if args[0]=='moveto':
            start=float(args[1])
        elif args[0]=='scroll':
            increment=max(.002,self.fraction*.15)
            start+=int(args[1])*increment*({'pages':5,'units':1}.get(args[2],1))
        start=max(0.0,min(span,start))
        self.percent=100*start/span
        # Move the native thumb immediately; defer expensive Matplotlib work.
        super().set(start,min(1.0,start+self.fraction))
        self._target=self.percent
        if self._pending is None:
            self._pending=self.after(16,self._flush)

    def _flush(self):
        self._pending=None
        target=self._target
        self._target=None
        if target is not None and self.winfo_exists():
            self.move(target)

    def get(self):
        return self.percent

    def show_range(self,rows,left,right,offset):
        if not rows:
            self.fraction=1.0
            self.percent=100.0
            super().set(0,1)
            return
        first,last=rows[0]['ts'],rows[-1]['ts']
        duration=max(last-first,.001)
        start=max(0.0,min(1.0,(left-first)/duration))
        end=max(start,min(1.0,(right-first)/duration))
        self.fraction=max(0.0,min(1.0,end-start))
        span=max(0.0,1.0-self.fraction)
        # During dragging, do not snap the thumb back to a delayed plot position.
        if self._pending is not None or self._target is not None:
            return
        self.percent=100*min(span,start)/span if span>0 else 100.0
        super().set(start,end)


class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title('Digital Pressure Recorder 1.0'); set_window_icon(self); self.geometry(f'{min(1440,self.winfo_screenwidth()-40)}x{min(900,self.winfo_screenheight()-100)}'); self.minsize(820,560); self.state('zoomed') if os.name=='nt' else None
        DATA.mkdir(parents=True,exist_ok=True)
        self.instance_lock=InstanceLock(DATA/'app.lock')
        self.exporting=False
        self.settings=dict(DEFAULTS)
        try: self.settings.update(json.loads((DATA/'settings.json').read_text()))
        except (OSError,ValueError): pass
        self.store=Store(DATA/'recordings.sqlite'); self.store.recover(); self.engine=Engine(self.store); self.engine.start()
        self.sid=None; self.detail_sid=None; self.connected=False; self.latest=None; self.connection_generation=0; self.connection_pending=False; self.connect_started=0; self.retired_engines=[]; self.simulation_recovery_attempted=False; self.connection_timed_out=False; self.buffer=deque(maxlen=14400); self.viewer_sid=None
        self.save_job=None; self.edit_loading=False; self.closing=False; self._shutdown_complete=False; self._tick_after_id=None; self.shutdown_warning_shown=False; self.last_plot=0; self.rec_count=0; self.rec_errors=0; self.pending=False; self.details_user_visible=True
        # Keep Windows awake for unattended acquisition; let the display turn off.
        # SetThreadExecutionState is thread-scoped and must be cleared on exit.
        self.sleep_prevention_active=False
        if os.name=='nt':
            try:
                flags=0x80000000 | 0x00000001  # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
                self.sleep_prevention_active=bool(ctypes.windll.kernel32.SetThreadExecutionState(flags))
            except (AttributeError,OSError):
                pass
        self.configure(bg=BG); style=ttk.Style(self); style.theme_use('clam')
        style.configure('.',font=(UI_FONT,10),background=BG,foreground=INK)
        style.configure('TFrame',background=BG)
        style.configure('TLabel',background=BG,foreground=INK)
        # Compact is the default for routine controls throughout the application.
        style.configure('TButton',padding=(6,3),font=(UI_FONT,9),background='#edf2f6',foreground=INK,borderwidth=1)
        style.configure('Compact.TButton',padding=(6,3),font=(UI_FONT,9),background='#edf2f6',foreground=INK,borderwidth=1)
        style.map('Compact.TButton',background=[('pressed','#cddde7'),('active','#dce8ef')])
        style.map('TButton',background=[('pressed','#cddde7'),('active','#dce8ef')])
        style.configure('Accent.TButton',background=TEAL,foreground='white',padding=(14,9),font=(UI_FONT,10,'bold'))
        style.map('Accent.TButton',background=[('pressed',TEAL_DARK),('active',TEAL_DARK)],
                  foreground=[('disabled','#6d818b'),('!disabled','white')])
        style.configure('Report.TButton',background='#21834b',foreground='white',padding=(15,9),font=(UI_FONT,11,'bold'))
        style.map('Report.TButton',background=[('pressed','#176538'),('active','#176538')],foreground=[('!disabled','white')])
        style.configure('Record.TButton',background='#d52e36',foreground='white',padding=(14,9),font=(UI_FONT,10,'bold'))
        style.map('Record.TButton',background=[('pressed','#a91d27'),('active','#bd232e')],foreground=[('!disabled','white')])
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
        self.brand=tk.Label(nav,text='Digital Pressure Recorder',font=(UI_FONT,15,'bold'),bg=NAVY,fg='white',padx=12,pady=2); self.brand.pack(side='left')
        self.nav_buttons={}
        for page in ['Live Monitor','History','Reporting','Settings','About']:
            button=tk.Button(nav,text=page,command=lambda p=page:self.show(p),bg=NAVY,fg='white',activebackground=TEAL_DARK,activeforeground='white',relief='flat',bd=0,padx=10,pady=2,font=(UI_FONT,9))
            button.pack(side='left'); self.nav_buttons[page]=button
        # Independent indicators: acquisition mode/health and recording state.
        self.status_live=tk.Label(nav,text='DISCONNECTED / NO DATA',bg='#b55c00',fg='white',padx=8,pady=4)
        self.status_live.pack(side='right',padx=12)
        self.status_rec=tk.Label(nav,text='REC OFF',bg='#576677',fg='white',padx=8,pady=4)
        self.status_rec.pack(side='right',padx=12)
        # Reserve the bottom strip before the expanding content so it remains visible.
        self.status_bar=tk.Frame(self,bg=NAVY)
        self.status_bar.pack(side='bottom',fill='x')
        self.footer=tk.Label(self.status_bar,text='Ready',bg=NAVY,fg='white',anchor='w',padx=10,pady=4)
        self.footer.pack(side='left')
        self.credit=tk.Label(self.status_bar,text='A software by Eka Yudhi Pratama  •  November 2026',bg=NAVY,fg='white',anchor='e',padx=10,pady=4)
        self.credit.pack(side='right')
        self.host=ttk.Frame(self,padding=14); self.host.pack(fill='both',expand=True)
        self.pages={name:ttk.Frame(self.host) for name in ['Live Monitor','History','Reporting','Settings','About','Viewer']}
        self.make_live(); self.make_history(); self.make_reporting(); self.make_settings(); self.make_about(); self.make_viewer(); self.enhance(); self.show('Live Monitor')
        # Route mouse-wheel scrolling to the active scrollable page.
        self.bind_all('<MouseWheel>',self.scroll_page,add='+')
        self.bind_all('<Button-4>',self.scroll_page,add='+')
        self.bind_all('<Button-5>',self.scroll_page,add='+')
        self.protocol('WM_DELETE_WINDOW',self.close)
        self.bind_all('<Control-q>',lambda event:self.close(),add='+')
        self._tick_after_id=self.after(50,self.tick)
        if self.settings.get('auto_connect') and (self.settings['mode']=='Simulation' or self.settings['port']): self.after(200,self.connect)
    def show(self,name):
        for p in self.pages.values(): p.pack_forget()
        self.pages[name].pack(fill='both',expand=True); self.page=name
        for key,button in self.nav_buttons.items(): button.config(bg=TEAL if key==('History' if name=='Viewer' else name) else NAVY)
        if name=='History': self.refresh_history()
        if name=='Reporting': self.refresh_reporting()
    def plot(self,parent):
        fig=Figure(figsize=(4,2),dpi=100,facecolor='white'); ax=fig.add_subplot(111); fig.subplots_adjust(left=.10,right=.98,bottom=.17,top=.91)
        canvas=FigureCanvasTkAgg(fig,master=parent); canvas.get_tk_widget().pack(fill='both',expand=True)
        return fig,ax,canvas
    def chart_scroll(self,event,live):
        """Zoom time around the cursor; never modify the recorded samples."""
        ax=self.lax if live else self.vax
        if event.inaxes!=ax or event.xdata is None:return
        direction=getattr(event,'button',None)
        if direction not in ('up','down'):return
        lo,hi=ax.get_xlim()
        factor=.8 if direction=='up' else 1.25
        width=max((hi-lo)*factor,.02 if not live else .5)
        ratio=max(0,min(1,(event.xdata-lo)/(hi-lo))) if hi>lo else .5
        new_lo=event.xdata-ratio*width
        ax.set_xlim(new_lo,new_lo+width)
        if live:
            self.follow.set(False)
            self.lcanvas.draw_idle()
        else:
            self.history_window.set('Buffer data')
            self.view_vars['xmin'].set(str(new_lo))
            self.view_vars['xmax'].set(str(new_lo+width))
            self.vcanvas.draw_idle()

    def chart_double_click(self,event,live):
        if event.inaxes is None or not getattr(event,'dblclick',False):return
        if live:
            self.follow.set(True)
            self.live_auto.set(True)
            self.scale_mode.set('Auto')
        else:
            self.history_window.set('Buffer data')
            self.viewer_scale_mode.set('Auto')
            self.auto_history_scale()
            self.slide_history(0)

    def chart_tools(self,canvas,parent,live):
        tools=NavigationToolbar2Tk(canvas,parent,pack_toolbar=False)
        canvas.mpl_connect('scroll_event',lambda event:self.chart_scroll(event,live))
        canvas.mpl_connect('button_press_event',lambda event:self.chart_double_click(event,live))
        if live:
            bar=self.live_toolbar
            self.live_chart_tools=bar
        else:
            bar=self.viewer_toolbar
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
                self.scale_mode.set('Auto')
                self.follow.set(True)
                self.lax.set_autoscaley_on(True)
            else:
                self.history_window.set('Buffer data')
                self.viewer_scale_mode.set('Auto')
                self.auto_history_scale()
                self.slide_history(0)
        labels=[('Reset',reset),('−',lambda:zoom(1.5)),('+',lambda:zoom(2/3)),('Pan',tools.pan)]
        for label,cmd in labels:
            ttk.Button(bar,text=label,command=cmd,style='Compact.TButton',
                       width=6 if label!='Reset' else 7).pack(side='right',padx=2)

    def auto_history_scale(self):
        valid=[r['value'] for r in self.vrows if r['quality']=='OK' and r['value'] is not None]
        if valid:
            lo,hi=min(valid),max(valid)
            pad=max((hi-lo)*.05,.01)
            self.view_vars['ymin'].set(str(lo-pad))
            self.view_vars['ymax'].set(str(hi+pad))
            self.paint_viewer()

    def make_live(self):
        p=self.pages['Live Monitor']; top=ttk.Frame(p); top.pack(fill='x',pady=(0,1))
        self.connection=ttk.Label(top,text='Waiting for device'); self.connection.pack(side='left')
        self.connect_btn=ttk.Button(top,text='Connect',style='Compact.TButton',command=self.toggle_connect); self.connect_btn.pack(side='left',padx=(10,8))
        self.reading_status=tk.Label(top,text='Waiting for first reading',bg=BG,fg=INK,font=(UI_FONT,9),anchor='w')
        self.reading_status.pack(side='left',padx=(0,8))
        self.drop=tk.BooleanVar(); ttk.Checkbutton(top,text='Simulate disconnect',variable=self.drop,command=lambda:self.engine.send('drop',self.drop.get())).pack(side='right')
        body=ttk.Panedwindow(p,orient='horizontal'); body.pack(fill='both',expand=True,pady=(2,2))
        main=ttk.Frame(body); self.details_panel=ttk.LabelFrame(body,text='Recording details',padding=10); body.add(main,weight=5); body.add(self.details_panel,weight=1); self.live_pane=body
        readings=ttk.Frame(main);readings.pack(fill='x',pady=(0,2))
        for col in range(3):readings.columnconfigure(col,weight=1,uniform='metric')
        def metric_card(column,title,highlight=False):
            bg=PALE_TEAL if highlight else SURFACE
            panel=tk.Frame(readings,bg=bg,highlightthickness=1,
                           highlightbackground='#a9d6d4' if highlight else BORDER)
            panel.grid(row=0,column=column,sticky='nsew',padx=(0,8) if column<2 else (0,0))
            tk.Label(panel,text=title,bg=bg,fg=NAVY,font=(UI_FONT,10,'bold'),
                     anchor='w').pack(fill='x',padx=12,pady=(2,0))
            return panel,bg
        live_card,live_bg=metric_card(0,'Live pressure',True)
        self.value=tk.Label(live_card,text='—',font=(UI_FONT,20,'bold'),bg=live_bg,
                            fg=TEAL_DARK,anchor='w')
        self.value.pack(fill='x',padx=12,pady=(0,2))
        self.metric=[]
        for col,title in [(1,'Recording minimum'),(2,'Recording maximum')]:
            panel,panel_bg=metric_card(col,title)
            label=tk.Label(panel,text='—',bg=panel_bg,fg=NAVY,
                           font=(UI_FONT,20,'bold'),anchor='w')
            label.pack(fill='x',padx=12,pady=(1,5))
            self.metric.append(label)
        self.live_toolbar=ttk.Frame(main); toolbar=self.live_toolbar
        toolbar.pack(fill='x',pady=(2,4))
        self.follow=tk.BooleanVar(value=True)
        ttk.Checkbutton(toolbar,text='Follow',variable=self.follow).pack(side='left')
        ttk.Label(toolbar,text='Window').pack(side='left',padx=(9,3))
        self.window=tk.StringVar(value='5 min')
        ttk.Combobox(toolbar,textvariable=self.window,values=['1 min','5 min','10 min','15 min','30 min','1 hour','Buffer data'],state='readonly',width=9).pack(side='left',padx=(0,5))
        ttk.Button(toolbar,text='Go to Live',style='Compact.TButton',command=lambda:self.follow.set(True)).pack(side='left')
        self.scale_mode=tk.StringVar(value='Auto')
        ttk.Radiobutton(toolbar,text='Auto scale',value='Auto',variable=self.scale_mode,command=self.select_live_scale).pack(side='left',padx=(10,0))
        ttk.Radiobutton(toolbar,text='Manual scale',value='Manual',variable=self.scale_mode,command=self.select_live_scale).pack(side='left',padx=(5,0))
        ttk.Button(toolbar,text='Manual scale options',style='Compact.TButton',command=self.show_live_options).pack(side='left',padx=(8,0))
        ttk.Button(top,text='Details +/−',style='Compact.TButton',command=self.toggle_details).pack(side='right',padx=10)
        self.lfig,self.lax,self.lcanvas=self.plot(main); self.lax.set(xlabel='Time',ylabel='Pressure'); self.lax.grid(alpha=.2)
        self.line,=self.lax.plot([],[],color='#008b92',lw=1.2)
        self.lcanvas.mpl_connect('button_press_event',lambda e:self.follow.set(False) if e.inaxes else None)
        self.chart_tools(self.lcanvas,main,True)
        controls=ttk.Frame(main); controls.pack(side='bottom',before=readings,fill='x',pady=(3,2))
        self.record_btn=ttk.Button(controls,text='⏺ Start recording',style='Record.TButton',command=self.record); self.record_btn.pack(side='left')
        self.event_btn=ttk.Button(controls,text='+ Add Event',style='Compact.TButton',command=self.add_live_event,state='disabled'); self.event_btn.pack(side='left',padx=10)
        self.rec_label=ttk.Label(controls,text='Preview only  |  not saved'); self.rec_label.pack(side='left')
        self.detail_vars={}; self.detail_entries=[]
        self.session_name=ttk.Label(self.details_panel,text='Press "Start Recording" to create a session',wraplength=250); self.session_name.pack(anchor='w',pady=(0,8))
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
            if not self.edit_loading:
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
            try:
                self.store.update(self.detail_sid,'details',{k:v.get() for k,v in self.detail_vars.items()})
                self.saved.config(text='Saved')
            except Exception as e:
                self.saved.config(text='SAVE FAILED')
                messagebox.showerror('Save failed',str(e))
                return False
        return True
    def load_details(self,sid):
        if self.save_job:self.after_cancel(self.save_job); self.save_details()
        self.detail_sid=sid; s=self.store.get(sid); d=json.loads(s['details']); self.edit_loading=True
        for k,v in self.detail_vars.items():v.set(d.get(k,''))
        for en in self.detail_entries:en.config(state='normal')
        self.notes.delete('1.0','end')
        self.notes.insert('1.0',d.get('notes',''))
        self.notes.edit_modified(False)
        self.edit_loading=False
        self.session_name.config(text=s['name']); self.saved.config(text='Saved')
    def connect(self):
        self.connection_generation+=1
        self.connection_pending=True
        self.connect_started=time.monotonic()
        self.simulation_recovery_attempted=False
        self.connection_timed_out=False
        self.connected=False
        self.latest=None
        self.buffer.clear()
        self.value.config(text='—')
        self.reading_status.config(text='CONNECTING  |  waiting for valid reading',fg=INK)
        self.connection.config(text='Connecting  |  '+self.settings['mode']+'  |  '+(self.settings['port'] or 'virtual sensor'))
        self.connect_btn.config(text='Connecting...',state='disabled')
        self.drop.set(False)
        self.engine.send('connect',dict(self.settings),self.connection_generation)
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
        p=self.pages['History']
        heading=ttk.Frame(p);heading.pack(fill='x',pady=(0,6))
        ttk.Label(heading,text='Recordings',style='Title.TLabel').pack(side='left')
        self.history_count=ttk.Label(heading,text='0 recordings',foreground='#576677')
        self.history_count.pack(side='right',pady=(9,0))

        bar=ttk.Frame(p);bar.pack(fill='x',pady=(2,10))
        self.search=tk.StringVar()
        search_box=ttk.Entry(bar,textvariable=self.search,width=43)
        search_box.pack(side='left',fill='x',expand=True)
        search_box.bind('<Return>',lambda event:self.refresh_history())
        ttk.Button(bar,text='Search',style='Compact.TButton',
                   command=self.refresh_history).pack(side='left',padx=(8,4))
        ttk.Button(bar,text='Clear',style='Compact.TButton',
                   command=self.clear_history_search).pack(side='left',padx=(0,4))
        ttk.Button(bar,text='Refresh',style='Compact.TButton',
                   command=self.refresh_history).pack(side='left')
        ttk.Label(p,text='Search by well, job, engineer or record ID. Double-click a recording to open it.',
                  foreground='#576677').pack(anchor='w',pady=(0,5))
        ttk.Label(p,text='To prepare a report, select a recording and open it in Viewer, then click Create Report.',
                  foreground=TEAL_DARK,wraplength=1100).pack(anchor='w',pady=(0,10))

        table=ttk.Frame(p);table.pack(fill='both',expand=True)
        cols=('start','well','job','engineer','duration','mode','status')
        self.history=ttk.Treeview(table,columns=cols,show='headings',selectmode='browse')
        widths={'start':(175,145),'well':(240,130),'job':(200,115),
                'engineer':(190,120),'duration':(105,85),'mode':(125,95),'status':(125,90)}
        labels={'start':'Started','well':'Well / Recording','job':'Job',
                'engineer':'Engineer','duration':'Duration','mode':'Source','status':'Status'}
        for col in cols:
            self.history.heading(col,text=labels[col])
            width,minimum=widths[col]
            self.history.column(col,width=width,minwidth=minimum,stretch=True,
                                anchor='w' if col in ('start','well','job','engineer') else 'center')
        vertical=ttk.Scrollbar(table,orient='vertical',command=self.history.yview)
        horizontal=ttk.Scrollbar(table,orient='horizontal',command=self.history.xview)
        self.history.configure(yscrollcommand=vertical.set,xscrollcommand=horizontal.set)
        table.rowconfigure(0,weight=1);table.columnconfigure(0,weight=1)
        self.history.grid(row=0,column=0,sticky='nsew')
        vertical.grid(row=0,column=1,sticky='ns')
        horizontal.grid(row=1,column=0,sticky='ew')
        self.history.tag_configure('alternate',background='#edf4f6')
        self.history.bind('<Double-1>',lambda e:self.open_selected())
        self.history.bind('<<TreeviewSelect>>',self.update_history_selection)
        footer=ttk.Frame(p);footer.pack(fill='x',pady=(10,0))
        self.history_selection=ttk.Label(footer,text='Select a recording to review',foreground='#576677')
        self.history_selection.pack(side='left')
        self.history_open=ttk.Button(footer,text='Open in Viewer',style='Accent.TButton',
                                     command=self.open_selected,state='disabled')
        self.history_open.pack(side='right')
        self.history_delete=ttk.Button(footer,text='Delete recording',style='Compact.TButton',
                                       command=self.delete_selected_recording,state='disabled')
        self.history_delete.pack(side='right',padx=(0,10))
        self.history_report=ttk.Button(footer,text='Create Report',style='Accent.TButton',
                                       command=self.report_selected_recording,state='disabled')
        self.history_report.pack(side='right',padx=(0,10))

    def clear_history_search(self):
        self.search.set('')
        self.refresh_history()

    def update_history_selection(self,event=None):
        chosen=self.history.selection()
        valid=bool(chosen and self.history.exists(chosen[0]))
        self.history_open.configure(state='normal' if valid else 'disabled')
        self.history_delete.configure(state='normal' if valid else 'disabled')
        self.history_report.configure(state='normal' if valid else 'disabled')
        self.history_selection.configure(text='1 recording selected' if valid else 'Select a recording to review')

    def refresh_history(self):
        previous=self.history.selection()
        previous=previous[0] if previous else None
        for item in self.history.get_children():self.history.delete(item)
        records=self.store.sessions(self.search.get().strip())
        for index,session in enumerate(records):
            details=json.loads(session['details'])
            finish=session['ended'] or self.store.stats(session['id'])['last'] or session['started']
            duration=max(0,finish-session['started'])
            minutes,seconds=divmod(int(duration),60)
            duration_text=f'{minutes}m {seconds:02d}s'
            self.history.insert('','end',iid=session['id'],
                tags=('alternate',) if index%2 else (),
                values=(stamp(session['started'],self.settings['utc_offset'])[:19].replace('T',' '),
                        details.get('well') or session['name'],
                        details.get('job') or '—',
                        details.get('engineer') or '—',
                        duration_text,session['mode'],session['state']))
        count=len(records)
        self.history_count.configure(text=f'{count} recording'+('' if count==1 else 's')+
                                     (' found' if self.search.get().strip() else ''))
        if previous and self.history.exists(previous):
            self.history.selection_set(previous)
            self.history.see(previous)
        self.update_history_selection()

    def open_selected(self):
        chosen=self.history.selection()
        if chosen and self.history.exists(chosen[0]):
            self.load_viewer(chosen[0])

    def delete_selected_recording(self):
        chosen=self.history.selection()
        if not chosen or not self.history.exists(chosen[0]):return
        sid=chosen[0]
        session=self.store.get(sid)
        if not session:return
        if session['state']=='Recording' or sid==self.sid:
            messagebox.showwarning('Delete recording','Stop recording before deleting this session.',parent=self)
            return
        details=json.loads(session['details'])
        name=(details.get('well') or session['name'])
        if not messagebox.askyesno('Delete recording',
                f'Permanently delete recording "{name}"?\n\n'
                'All pressure samples and annotations in this recording will be deleted. '
                'This cannot be undone.',icon='warning',parent=self):
            return
        try:
            if self.store.delete_session(sid):
                if sid==getattr(self,'reporting_sid',None):
                    self.reporting_sid=None
                if sid==self.viewer_sid:
                    self.viewer_sid=None
                    self.vsession=None
                    self.vrows=[]
                    self.vevents=[]
                self.refresh_history()
                self.footer.configure(text='Recording deleted')
        except Exception as exc:
            messagebox.showerror('Delete recording',str(exc),parent=self)

    def report_selected_recording(self):
        chosen=self.history.selection()
        if chosen and self.history.exists(chosen[0]):
            self.open_reporting(chosen[0])

    def make_reporting(self):
        p=self.pages['Reporting']
        bar=ttk.Frame(p);bar.pack(fill='x',pady=(0,8))
        ttk.Label(bar,text='Reporting',style='Title.TLabel').pack(side='left')
        self.reporting_record=tk.StringVar(value='No recording selected')
        selected=ttk.Frame(p);selected.pack(fill='x',pady=(0,10))
        ttk.Label(selected,textvariable=self.reporting_record,font=(UI_FONT,12,'bold')).pack(side='left',padx=(0,14))
        ttk.Button(selected,text='Select from History',style='Compact.TButton',command=lambda:self.show('History')).pack(side='left')

        navigation=ttk.Frame(p);navigation.pack(fill='x',pady=(0,10))
        self.report_step=1
        self.report_step_buttons=[]
        for number,name in enumerate(('1. Time Range','2. Graph Options','3. Preview & Export'),1):
            button=tk.Button(navigation,text=name,relief='flat',bd=1,padx=16,pady=9,
                              command=lambda n=number:self.show_report_step(n))
            button.pack(side='left',padx=(0,10))
            self.report_step_buttons.append(button)

        self.report_steps=[]
        for _ in range(3):
            frame=ttk.Frame(p)
            self.report_steps.append(frame)

        one=self.report_steps[0]
        section=ttk.LabelFrame(one,text='Step 1 — Select Reporting Interval',padding=16)
        section.pack(fill='both',expand=True,pady=(0,10))
        self.report_start=tk.StringVar(value='0')
        self.report_end=tk.StringVar(value='0')
        self.report_range_mode=tk.StringVar(value='full')
        modes=ttk.Frame(section);modes.pack(fill='x',pady=(0,10))
        ttk.Radiobutton(modes,text='Full Recording',value='full',variable=self.report_range_mode,
                        command=self.change_report_range_mode).pack(side='left',padx=(0,25))
        ttk.Radiobutton(modes,text='Select Time Range on Graph',value='custom',variable=self.report_range_mode,
                        command=self.change_report_range_mode).pack(side='left')
        fields=ttk.Frame(section);fields.pack(fill='x',pady=(0,8))
        ttk.Label(fields,text='From (minutes)').pack(side='left')
        self.report_from_entry=ttk.Entry(fields,textvariable=self.report_start,width=12)
        self.report_from_entry.pack(side='left',padx=(6,16))
        ttk.Label(fields,text='To (minutes)').pack(side='left')
        self.report_to_entry=ttk.Entry(fields,textvariable=self.report_end,width=12)
        self.report_to_entry.pack(side='left',padx=(6,16))
        ttk.Label(section,text='Select a span directly on the full recording graph, or edit the minute values precisely.',
                  foreground='#576677').pack(anchor='w',pady=(0,8))
        scale=ttk.Frame(section);scale.pack(fill='x',pady=(0,8))
        self.report_view_xmin=tk.StringVar(value='0')
        self.report_view_xmax=tk.StringVar(value='0')
        self.report_ymin=tk.StringVar(value='')
        self.report_ymax=tk.StringVar(value='')
        for label,var in [('X from (min)',self.report_view_xmin),('X to (min)',self.report_view_xmax),('Y min',self.report_ymin),('Y max',self.report_ymax)]:
            ttk.Label(scale,text=label).pack(side='left',padx=(8,3))
            ttk.Entry(scale,textvariable=var,width=9).pack(side='left')
        ttk.Button(scale,text='Apply Scale',style='Compact.TButton',command=self.apply_report_scale).pack(side='left',padx=8)
        ttk.Button(scale,text='Reset Zoom',style='Compact.TButton',command=self.reset_report_zoom).pack(side='left')
        self.report_range_chart=ttk.Frame(section)
        self.report_range_chart.pack(fill='both',expand=True)
        self.report_range_hint=ttk.Label(self.report_range_chart,
                 text='Select a recording from History to display its pressure timeline.',
                 foreground='#576677')
        self.report_range_hint.pack(pady=55)
        self.report_inline_sid=None
        self.report_range_canvas=None
        footer=ttk.Frame(one);footer.pack(fill='x')
        ttk.Button(footer,text='Continue to Graph Options  >',style='Compact.TButton',
                   command=lambda:self.show_report_step(2)).pack(side='right')
        self.change_report_range_mode()

        two=self.report_steps[1]
        ttk.Label(two,text='Step 2 — Graph options',font=(UI_FONT,12,'bold')).pack(anchor='w',pady=(0,10))
        opts=ttk.LabelFrame(two,text='Graph appearance',padding=14);opts.pack(fill='x',pady=(0,12))
        ttk.Label(opts,text='X-axis').grid(row=0,column=0,sticky='w',padx=(0,12),pady=6)
        self.report_axis=tk.StringVar(value='Elapsed Time')
        ttk.Combobox(opts,textvariable=self.report_axis,state='readonly',width=22,
                     values=('Elapsed Time','Date & Time')).grid(row=0,column=1,sticky='w',pady=6)
        ttk.Label(opts,text='Pressure unit').grid(row=1,column=0,sticky='w',padx=(0,12),pady=6)
        self.report_unit=tk.StringVar(value=self.settings['unit'])
        ttk.Combobox(opts,textvariable=self.report_unit,state='readonly',width=22,
                     values=('psi','bar','kPa','MPa')).grid(row=1,column=1,sticky='w',pady=6)
        self.report_events=tk.BooleanVar(value=True)
        self.report_grid=tk.BooleanVar(value=True)
        ttk.Checkbutton(opts,text='Show event markers',variable=self.report_events).grid(row=2,column=0,columnspan=2,sticky='w',pady=5)
        ttk.Checkbutton(opts,text='Show gridlines',variable=self.report_grid).grid(row=3,column=0,columnspan=2,sticky='w',pady=5)
        ttk.Button(two,text='Continue to Preview & Export  >',style='Compact.TButton',
                   command=lambda:self.show_report_step(3)).pack(anchor='e')

        three=self.report_steps[2]
        ttk.Label(three,text='Step 3 — Preview & Export',font=(UI_FONT,12,'bold')).pack(anchor='w',pady=(0,6))
        actions=ttk.Frame(three);actions.pack(fill='x',pady=(0,8))
        ttk.Label(actions,text='Output type:').pack(side='left',padx=(0,8))
        self.report_format=tk.StringVar(value='pdf')
        choices=[('PDF Report','pdf'),('JPEG Graph','jpg'),('Excel — Detailed Data','xlsx'),('CSV — Detailed Data','csv')]
        for label,fmt in choices:
            ttk.Radiobutton(actions,text=label,value=fmt,variable=self.report_format,
                            command=self.refresh_reporting).pack(side='left',padx=(0,12))
        ttk.Button(actions,text='Export Selected',style='Compact.TButton',
                   command=lambda:self.export_reporting(self.report_format.get())).pack(side='right')
        self.report_preview_info=tk.StringVar(value='')
        ttk.Label(three,textvariable=self.report_preview_info,foreground='#576677').pack(anchor='w',pady=(0,6))
        area=ttk.LabelFrame(three,text='Preview',padding=8);area.pack(fill='both',expand=True)
        self.reporting_canvas=tk.Canvas(area,bg='#e2e8ed',highlightthickness=0)
        scroll=ttk.Scrollbar(area,orient='vertical',command=self.reporting_canvas.yview)
        scroll.pack(side='right',fill='y')
        self.reporting_canvas.pack(side='left',fill='both',expand=True)
        self.reporting_canvas.configure(yscrollcommand=scroll.set)
        self.reporting_preview=ttk.Frame(self.reporting_canvas)
        self.reporting_window=self.reporting_canvas.create_window((0,0),window=self.reporting_preview,anchor='n')
        self.reporting_preview.bind('<Configure>',lambda e:self.reporting_canvas.configure(scrollregion=self.reporting_canvas.bbox('all')))
        self.reporting_canvas.bind('<Configure>',lambda e:self.reporting_canvas.coords(self.reporting_window,e.width/2,0))
        self.reporting_placeholder=ttk.Label(self.reporting_preview,text='Select a recording to preview its report.')
        self.reporting_placeholder.pack(pady=40)
        self.reporting_preview_sid=None
        self.report_range_sid=None
        self.show_report_step(1,validate=False)

    def show_report_step(self,step,validate=True):
        if step not in (1,2,3):return
        if validate and step>1 and getattr(self,'reporting_sid',None):
            try:self.get_report_range()
            except ValueError as exc:
                messagebox.showerror('Time range',str(exc),parent=self)
                self.show_report_step(1,validate=False)
                return
        for frame in self.report_steps:frame.pack_forget()
        self.report_step=step
        self.report_steps[step-1].pack(fill='both',expand=True)
        for index,button in enumerate(self.report_step_buttons,1):
            active=index==step
            button.configure(bg=TEAL if active else SURFACE,
                             fg='white' if active else INK,
                             activebackground=TEAL_DARK if active else PALE_TEAL,
                             activeforeground='white' if active else INK,
                             highlightthickness=0)
        if step==1:self.refresh_inline_range_graph()
        if step==3:self.refresh_reporting()

    def open_reporting(self,sid):
        if not sid or not self.store.get(sid):
            messagebox.showwarning('Reporting','Please select a valid recording.',parent=self)
            return
        self.reporting_sid=sid
        self.report_range_mode.set('full')
        self.report_range_sid=None
        self.report_inline_sid=None
        self.show_report_step(1,validate=False)
        self.show('Reporting')

    def refresh_reporting(self):
        sid=getattr(self,'reporting_sid',None)
        session=self.store.get(sid) if sid else None
        if not session:
            self.reporting_sid=None
            self.reporting_record.set('No recording selected')
            return
        details=json.loads(session['details'])
        self.reporting_record.set((details.get('well') or session['name'])+'  |  '+(details.get('job') or 'Recording'))
        if self.report_range_sid!=sid:self.reset_report_range()
        try:time_range=self.get_report_range()
        except ValueError as exc:
            messagebox.showerror('Time range',str(exc),parent=self);return
        if self.report_step!=3:return
        try:y_limits=self.get_report_y_limits()
        except ValueError as exc:
            messagebox.showerror('Graph scale',str(exc),parent=self);return
        # Recreate on each visit so edits to notes/events are reflected.
        for child in self.reporting_preview.winfo_children():child.destroy()
        try:
            fmt=self.report_format.get()
            self.report_preview_info.set('PDF report preview' if fmt=='pdf' else 'JPEG graph preview' if fmt=='jpg' else 'Detailed recorded data will be exported; graph preview is not applicable.')
            if fmt in ('xlsx','csv'):
                ttk.Label(self.reporting_preview,text='Detailed data export includes original samples within the selected time range.').pack(padx=24,pady=40)
                return
            fig=report_figure(self.store,sid,self.report_unit.get(),time_range,self.report_axis.get(),self.report_events.get(),self.report_grid.get(),y_limits) if fmt=='pdf' else graph_figure(self.store,sid,self.report_unit.get(),time_range,self.report_axis.get(),self.report_events.get(),self.report_grid.get(),y_limits)
            canvas=FigureCanvasTkAgg(fig,master=self.reporting_preview)
            widget=canvas.get_tk_widget()
            widget.pack(padx=12,pady=12)
            canvas.draw()
            self.reporting_figure=fig
            self.reporting_figure_canvas=canvas
        except Exception as exc:
            ttk.Label(self.reporting_preview,text='Preview unavailable: '+str(exc)).pack(pady=30)

    def change_report_range_mode(self):
        custom=self.report_range_mode.get()=='custom'
        if not custom and getattr(self,'report_range_sid',None):
            self.reset_report_range()
        if hasattr(self,'report_from_entry'):
            for widget in (self.report_from_entry,self.report_to_entry):
                widget.configure(state='normal' if custom else 'disabled')
        if getattr(self,'report_range_canvas',None):
            self.report_range_selector.set_active(custom)
            self.report_range_shade.set_visible(custom)
            self.report_excluded_left.set_visible(custom)
            self.report_excluded_right.set_visible(custom)
            self.report_range_left.set_visible(custom)
            self.report_range_right.set_visible(custom)
            self.report_range_canvas.draw_idle()

    def refresh_inline_range_graph(self):
        sid=getattr(self,'reporting_sid',None)
        session=self.store.get(sid) if sid else None
        if not session:return
        if self.report_range_sid!=sid:self.reset_report_range()
        if self.report_inline_sid==sid:return
        self.report_view_xmin.set('0')
        self.report_view_xmax.set(f'{max(((session["ended"] or self.store.stats(sid)["last"] or session["started"])-session["started"])/60,.001):.3f}')
        self.report_ymin.set('');self.report_ymax.set('')
        from matplotlib.widgets import SpanSelector
        from matplotlib.ticker import MaxNLocator
        rows=self.store.plot_rows(sid)
        if not rows:return
        for widget in self.report_range_chart.winfo_children():widget.destroy()
        start=session['started']
        end=session['ended'] or self.store.stats(sid)['last'] or rows[-1]['ts']
        duration=max((end-start)/60,.001)
        fig=Figure(figsize=(10,4),dpi=100,facecolor='white')
        ax=fig.add_subplot(111)
        fig.subplots_adjust(left=.07,right=.98,top=.95,bottom=.17)
        ax.plot([(r['ts']-start)/60 for r in rows],
                [from_psi(r['value'],self.settings['unit']) if r['quality']=='OK' and r['value'] is not None else math.nan for r in rows],
                color=TEAL,lw=1.2)
        ax.set_xlim(0,duration)
        ax.set_ylabel('Pressure ('+self.settings['unit']+')')
        ax.set_xlabel('Elapsed time (minutes)')
        ax.xaxis.set_major_locator(MaxNLocator(9))
        ax.grid(alpha=.2)
        canvas=FigureCanvasTkAgg(fig,master=self.report_range_chart)
        canvas.get_tk_widget().pack(fill='both',expand=True)
        self.report_range_shade=ax.axvspan(0,duration,color='#44b99f',alpha=.28)
        self.report_excluded_left=ax.axvspan(0,0,color='#8a929b',alpha=.48)
        self.report_excluded_right=ax.axvspan(duration,duration,color='#8a929b',alpha=.48)
        self.report_range_axes=ax
        self.report_range_duration=duration
        self.report_range_left=ax.axvline(0,color=TEAL,lw=1.5,ls='--')
        self.report_range_right=ax.axvline(duration,color=TEAL,lw=1.5,ls='--')
        def redraw(lo,hi):
            self.report_range_shade.set_xy([[lo,0],[lo,1],[hi,1],[hi,0],[lo,0]])
            self.report_excluded_left.set_xy([[0,0],[0,1],[lo,1],[lo,0],[0,0]])
            self.report_excluded_right.set_xy([[hi,0],[hi,1],[duration,1],[duration,0],[hi,0]])
            self.report_range_left.set_xdata([lo,lo])
            self.report_range_right.set_xdata([hi,hi])
            canvas.draw_idle()
        def selected(lo,hi):
            lo=max(0,min(duration,lo));hi=max(0,min(duration,hi))
            if hi-lo<.001:return
            self.report_start.set(f'{lo:.3f}')
            self.report_end.set(f'{hi:.3f}')
            redraw(lo,hi)
        self.report_range_selector=SpanSelector(ax,selected,'horizontal',useblit=True,
                            interactive=True,drag_from_anywhere=True,
                            props=dict(facecolor=TEAL,alpha=.12))
        def sync_fields(*_):
            if self.report_range_mode.get()!='custom':return
            try:
                lo=float(self.report_start.get());hi=float(self.report_end.get())
                if 0<=lo<hi<=duration+.002:redraw(lo,hi)
            except ValueError:pass
        self.report_start.trace_add('write',sync_fields)
        self.report_end.trace_add('write',sync_fields)
        def wheel(event):
            if event.inaxes is not ax or event.xdata is None:return
            lo,hi=ax.get_xlim()
            factor=.8 if event.button=='up' else 1.25
            span=max(.01,min(duration,(hi-lo)*factor))
            center=max(span/2,min(duration-span/2,event.xdata))
            ax.set_xlim(center-span/2,center+span/2)
            self.report_view_xmin.set(f'{ax.get_xlim()[0]:.3f}')
            self.report_view_xmax.set(f'{ax.get_xlim()[1]:.3f}')
            canvas.draw_idle()
        canvas.mpl_connect('scroll_event',wheel)
        self.report_range_canvas=canvas
        self.report_inline_sid=sid
        self.change_report_range_mode()
        canvas.draw()

    def apply_report_scale(self):
        if not getattr(self,'report_range_canvas',None):return
        try:
            xmin=float(self.report_view_xmin.get());xmax=float(self.report_view_xmax.get())
            if not (math.isfinite(xmin) and math.isfinite(xmax) and 0<=xmin<xmax<=self.report_range_duration+.002):
                raise ValueError('X limits must be within the recording.')
            y_limits=self.get_report_y_limits()
        except ValueError as exc:
            messagebox.showerror('Graph scale',str(exc),parent=self);return
        ax=self.report_range_axes
        ax.set_xlim(xmin,xmax)
        if y_limits:ax.set_ylim(*y_limits)
        else:ax.relim();ax.autoscale(axis='y')
        self.report_range_canvas.draw_idle()

    def reset_report_zoom(self):
        if not getattr(self,'report_range_canvas',None):return
        self.report_view_xmin.set('0')
        self.report_view_xmax.set(f'{self.report_range_duration:.3f}')
        self.report_ymin.set('');self.report_ymax.set('')
        self.apply_report_scale()

    def get_report_y_limits(self):
        low=self.report_ymin.get().strip();high=self.report_ymax.get().strip()
        if not low and not high:return None
        if not low or not high:raise ValueError('Enter both Y scale limits or clear both.')
        try:a=float(low);b=float(high)
        except ValueError:raise ValueError('Y scale limits must be numbers.')
        if not (math.isfinite(a) and math.isfinite(b) and a<b):
            raise ValueError('Y minimum must be smaller than Y maximum.')
        return a,b

    def reset_report_and_preview(self):
        self.reset_report_range()
        self.refresh_reporting()

    def select_report_range(self):
        """Select a report interval using the entire recording timeline."""
        sid=getattr(self,'reporting_sid',None)
        session=self.store.get(sid) if sid else None
        if not session:return
        if getattr(self,'report_range_dialog',None) and self.report_range_dialog.winfo_exists():
            self.report_range_dialog.lift();return
        from matplotlib.widgets import SpanSelector
        from matplotlib.ticker import FuncFormatter,MaxNLocator
        rows=self.store.plot_rows(sid)
        if not rows:
            messagebox.showinfo('Time range','No samples available.',parent=self);return
        start=session['started']
        end=session['ended'] or self.store.stats(sid)['last'] or rows[-1]['ts']
        duration=max((end-start)/60,.001)
        try:
            selected=self.get_report_range()
            initial=[(selected[0]-start)/60,(selected[1]-start)/60]
        except ValueError:initial=[0,duration]
        win=tk.Toplevel(self);win.title('Select Reporting Time Range')
        win.geometry('1050x650');win.minsize(700,440);win.transient(self)
        self.report_range_dialog=win
        body=ttk.Frame(win,padding=14);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Select Reporting Time Range',font=(UI_FONT,15,'bold')).pack(anchor='w')
        ttk.Label(body,text='Drag across the full recording to select a range. Use the minute fields for precise adjustments.',
                  foreground='#576677').pack(anchor='w',pady=(3,10))
        chart=ttk.Frame(body);chart.pack(fill='both',expand=True)
        fig=Figure(figsize=(10,4),dpi=100,facecolor='white')
        ax=fig.add_subplot(111);fig.subplots_adjust(left=.09,right=.98,top=.94,bottom=.20)
        ax.plot([(r['ts']-start)/60 for r in rows],
                [from_psi(r['value'],self.settings['unit']) if r['quality']=='OK' and r['value'] is not None else math.nan for r in rows],
                color=TEAL,lw=1.2)
        ax.set_xlim(0,duration);ax.set_ylabel('Pressure ('+self.settings['unit']+')')
        ax.grid(alpha=.2);ax.xaxis.set_major_locator(MaxNLocator(8))
        if self.report_axis.get()=='Date & Time':
            offset=json.loads(session['settings']).get('utc_offset',8)
            ax.xaxis.set_major_formatter(FuncFormatter(lambda x,pos:stamp(start+x*60,offset)[11:19]))
            ax.set_xlabel('Time (UTC%+g)' % float(offset))
        else:ax.set_xlabel('Elapsed time (minutes)')
        graph=FigureCanvasTkAgg(fig,master=chart)
        graph.get_tk_widget().pack(fill='both',expand=True)
        fields=ttk.Frame(body);fields.pack(fill='x',pady=(10,6))
        left=tk.StringVar(value=f'{initial[0]:.3f}')
        right=tk.StringVar(value=f'{initial[1]:.3f}')
        ttk.Label(fields,text='From (min)').pack(side='left')
        ttk.Entry(fields,textvariable=left,width=12).pack(side='left',padx=(6,18))
        ttk.Label(fields,text='To (min)').pack(side='left')
        ttk.Entry(fields,textvariable=right,width=12).pack(side='left',padx=(6,18))
        status=ttk.Label(fields,text='',foreground='#576677');status.pack(side='left')
        shade=ax.axvspan(*initial,color=TEAL,alpha=.18)
        lmark=ax.axvline(initial[0],color=TEAL,lw=1.5,ls='--')
        rmark=ax.axvline(initial[1],color=TEAL,lw=1.5,ls='--')
        def redraw(lo,hi):
            shade.set_xy([[lo,0],[lo,1],[hi,1],[hi,0],[lo,0]])
            lmark.set_xdata([lo,lo]);rmark.set_xdata([hi,hi])
            status.config(text=f'{hi-lo:.2f} minutes selected')
            graph.draw_idle()
        def chosen(lo,hi):
            lo=max(0,min(duration,lo));hi=max(0,min(duration,hi))
            if hi-lo<.001:return
            left.set(f'{lo:.3f}');right.set(f'{hi:.3f}')
            redraw(lo,hi)
        selector=SpanSelector(ax,chosen,'horizontal',useblit=True,interactive=True,
                              props=dict(facecolor=TEAL,alpha=.12),drag_from_anywhere=True)
        win.report_selector=selector
        def apply():
            try:lo=float(left.get());hi=float(right.get())
            except ValueError:
                messagebox.showerror('Invalid range','Enter numeric minute values.',parent=win);return
            if not (math.isfinite(lo) and math.isfinite(hi) and 0<=lo<hi<=duration+.002):
                messagebox.showerror('Invalid range',f'Choose 0 <= From < To <= {duration:.3f} minutes.',parent=win);return
            self.report_start.set(f'{lo:.3f}');self.report_end.set(f'{hi:.3f}')
            win.destroy()
            if self.report_step==3:self.refresh_reporting()
        def reset():
            left.set('0');right.set(f'{duration:.3f}');redraw(0,duration)
        buttons=ttk.Frame(body);buttons.pack(fill='x',pady=(8,0))
        ttk.Button(buttons,text='Reset to Full Recording',command=reset).pack(side='left')
        ttk.Button(buttons,text='Apply Range',style='Accent.TButton',command=apply).pack(side='right')
        ttk.Button(buttons,text='Cancel',command=win.destroy).pack(side='right',padx=8)
        redraw(*initial)

    def reset_report_range(self):
        sid=getattr(self,'reporting_sid',None)
        session=self.store.get(sid) if sid else None
        if not session:return
        end=session['ended'] or self.store.stats(sid)['last'] or session['started']
        self.report_start.set('0')
        self.report_end.set(f'{max((end-session["started"])/60,0.001):.3f}')
        self.report_range_sid=sid

    def get_report_range(self):
        sid=getattr(self,'reporting_sid',None)
        session=self.store.get(sid) if sid else None
        if not session:raise ValueError('Select a recording first')
        try:
            start=float(self.report_start.get())
            end=float(self.report_end.get())
        except ValueError:raise ValueError('Enter valid numeric start and end minutes')
        duration=max(0,((session['ended'] or self.store.stats(sid)['last'] or session['started'])-session['started'])/60)
        if not (math.isfinite(start) and math.isfinite(end) and 0<=start<end<=duration+.002):
            raise ValueError(f'Time range must satisfy 0 <= From < To <= {duration:.3f} minutes')
        return (session['started']+start*60,session['started']+end*60)

    def export_reporting(self,fmt):
        sid=getattr(self,'reporting_sid',None)
        session=self.store.get(sid) if sid else None
        if not session:
            messagebox.showwarning('Reporting','Select a recording first.',parent=self);return
        if self.exporting:
            messagebox.showinfo('Export','Wait for the current export to finish.',parent=self);return
        suffix='jpg' if fmt=='jpg' else fmt
        path=filedialog.asksaveasfilename(parent=self,defaultextension='.'+suffix,
            initialfile=session['name']+('_graph' if fmt=='jpg' else '_report' if fmt=='pdf' else '_data')+'.'+suffix,
            filetypes=[('PDF report','*.pdf')] if fmt=='pdf' else [('JPEG image','*.jpg')] if fmt=='jpg' else [('Excel workbook','*.xlsx')] if fmt=='xlsx' else [('CSV data','*.csv')])
        if not path:return
        self.exporting=True
        self.footer.config(text='Exporting '+fmt.upper()+'...')
        unit=self.report_unit.get()
        try:time_range=self.get_report_range()
        except ValueError as exc:
            self.exporting=False
            messagebox.showerror('Time range',str(exc),parent=self);return
        axis_mode=self.report_axis.get()
        try:y_limits=self.get_report_y_limits()
        except ValueError as exc:
            self.exporting=False
            messagebox.showerror('Graph scale',str(exc),parent=self);return
        show_events=self.report_events.get();show_grid=self.report_grid.get()
        def work():
            try:
                if fmt in ('pdf','jpg'):
                    from pathlib import Path
                    target=Path(path)
                    temp=target.with_name(target.stem+'.partial'+target.suffix)
                    try:
                        fig=report_figure(self.store,sid,unit,time_range,axis_mode,show_events,show_grid,y_limits) if fmt=='pdf' else graph_figure(self.store,sid,unit,time_range,axis_mode,show_events,show_grid,y_limits)
                        fig.savefig(temp,format='pdf' if fmt=='pdf' else 'jpeg',dpi=180,facecolor='white')
                        temp.replace(target)
                    finally:temp.unlink(missing_ok=True)
                else:
                    export(self.store,sid,path,{'xmin':(time_range[0]-session['started'])/60,'xmax':(time_range[1]-session['started'])/60},True)
                self.engine.emit('exported',path=path)
            except Exception as exc:
                self.engine.emit('export_error',text='Export failed: '+str(exc))
        threading.Thread(target=work,daemon=True).start()

    def review_reporting_record(self):
        sid=getattr(self,'reporting_sid',None)
        if sid and self.store.get(sid):self.load_viewer(sid)
        else:self.show('History')

    def make_settings(self):
        # Keep every setting reachable when the window is narrow or display scaling is high.
        host=self.pages['Settings']
        canvas=tk.Canvas(host,bg=BG,highlightthickness=0)
        scrollbar=ttk.Scrollbar(host,orient='vertical',command=canvas.yview)
        scrollbar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        p=ttk.Frame(canvas,padding=(4,4,12,16))
        window=canvas.create_window((0,0),window=p,anchor='nw')
        p.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(window,width=e.width))
        self.settings_canvas=canvas
        ttk.Label(p,text='Settings',style='Title.TLabel').pack(anchor='w',pady=8)
        ttk.Label(p,text='Connection and unit changes apply after reconnecting. Stop recording before applying settings.').pack(anchor='w')
        columns=ttk.Frame(p);columns.pack(fill='both',expand=True,pady=(12,8))
        self.settings_columns=columns
        columns.columnconfigure(0,weight=3);columns.columnconfigure(1,weight=2)
        grid=ttk.LabelFrame(columns,text='Device connection',padding=14)
        grid.grid(row=0,column=0,sticky='nsew',padx=(0,8),pady=(0,10))
        display=ttk.LabelFrame(columns,text='Acquisition & display',padding=14)
        display.grid(row=1,column=0,sticky='nsew',padx=(0,8))
        actions=ttk.LabelFrame(columns,text='Connection preferences & actions',padding=14)
        actions.grid(row=0,column=1,rowspan=2,sticky='nsew',padx=(8,0),pady=(0,10))
        self.settings_device=grid;self.settings_display=display;self.settings_actions=actions
        grid.columnconfigure(1,weight=1);display.columnconfigure(1,weight=1)
        self.config_vars={}
        self.utc_offset_labels={
            7:'UTC+7 — WIB (Jakarta)',
            8:'UTC+8 — WITA (Balikpapan)',
            9:'UTC+9 — WIT (Jayapura)',
            0:'UTC+0 — UTC (Universal Time)',
        }
        choices={'mode':['Simulation','Modbus RTU'],'baud':[2400,4800,9600,19200],'parity':['E','N','O'],'stopbits':[1,2],'interval':[.5,1,.2,.1],'unit':['psi','bar','kPa','MPa'],'utc_offset':list(self.utc_offset_labels.values())}
        for n,k in enumerate(['mode','port','baud','parity','stopbits','address','interval','unit','utc_offset']):
            parent=grid if n<6 else display
            row=n if n<6 else n-6
            ttk.Label(parent,text={'utc_offset':'UTC offset','interval':'Interval (seconds)','baud':'Baud rate','stopbits':'Stop bits'}.get(k,k.title())).grid(row=row,column=0,sticky='w',padx=(0,12),pady=5)
            initial=(self.utc_offset_labels.get(int(float(self.settings[k])),str(self.settings[k])) if k=='utc_offset' else str(self.settings[k]))
            v=tk.StringVar(value=initial); self.config_vars[k]=v
            if k=='port':
                en=ttk.Combobox(parent,textvariable=v,state='readonly',width=30); self.port_combo=en
            elif k in choices:en=ttk.Combobox(parent,textvariable=v,values=choices[k],state='readonly',width=30)
            else:en=ttk.Entry(parent,textvariable=v,width=32)
            en.grid(row=row,column=1,sticky='ew',pady=4)
        port_actions=ttk.Frame(grid)
        port_actions.grid(row=1,column=2,sticky='w',padx=10)
        ttk.Button(port_actions,text='Refresh ports',command=self.find_ports).pack(side='left')
        self.port_count=ttk.Label(port_actions)
        self.port_count.pack(side='left',padx=(8,0))
        ttk.Label(grid,text='Recommended: 9600 baud',foreground='#576677').grid(row=2,column=2,sticky='w',padx=10)
        ttk.Label(display,text='Recommended: 0.5 s',foreground='#576677').grid(row=0,column=2,sticky='w',padx=10)
        ttk.Label(display,text='0.5 s means one reading is requested every half-second. Actual sampling may be slower if communication is delayed.',foreground='#576677',wraplength=350,justify='left').grid(row=1,column=2,rowspan=2,sticky='nw',padx=10,pady=(4,0))

        self.auto=tk.BooleanVar(value=self.settings['auto_connect'])
        ttk.Checkbutton(actions,text='Auto-connect last configuration at startup',variable=self.auto).pack(anchor='w',pady=(4,16))
        ttk.Label(actions,text='Hardware profile: PMS-970  |  FC03  |  address 0x0001  |  readout + status',wraplength=360).pack(anchor='w',pady=(0,8))
        ttk.Label(actions,text='Sensor/storage unit: PSI. Display units are converted for viewing; stored samples remain PSI.',wraplength=360).pack(anchor='w',pady=(0,8))
        ttk.Label(actions,text='Device communication confirmed by user at 9600 baud, November 2026.',wraplength=360).pack(anchor='w',pady=(0,12))
        ttk.Label(actions,text='Data directory:',font=(UI_FONT,9,'bold')).pack(anchor='w')
        ttk.Label(actions,text=str(DATA),wraplength=360).pack(anchor='w',pady=(2,18))
        ttk.Button(actions,text='Save and reconnect',command=self.apply_settings,style='Accent.TButton').pack(anchor='w')
    def make_about(self):
        host=self.pages['About']
        canvas=tk.Canvas(host,bg=BG,highlightthickness=0)
        scrollbar=ttk.Scrollbar(host,orient='vertical',command=canvas.yview)
        scrollbar.pack(side='right',fill='y')
        canvas.pack(side='left',fill='both',expand=True)
        canvas.configure(yscrollcommand=scrollbar.set)
        outer=ttk.Frame(canvas,padding=(4,4,18,24))
        window=canvas.create_window((0,0),window=outer,anchor='nw')
        outer.bind('<Configure>',lambda event:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda event:canvas.itemconfigure(window,width=event.width))
        self.about_canvas=canvas
        ttk.Label(outer,text='About Digital Pressure Recorder',style='Title.TLabel').pack(anchor='w',pady=(8,16))
        content=ttk.Frame(outer)
        content.pack(anchor='w',fill='x')
        # Let the canvas control page width. Avoid configuring a packed frame
        # from its parent's Configure event, which can trigger a layout loop.
        # Lightweight, offline vector icons drawn directly by Tkinter.
        # No image files, external packages, or network requests required.
        def icon(parent,kind,color='#21657b'):
            c=tk.Canvas(parent,width=30,height=30,bg=BG,highlightthickness=0)
            kw=dict(fill='',outline=color,width=2)
            def line(*coords):c.create_line(*coords,fill=color,width=2,capstyle='round',joinstyle='round')
            if kind=='activity':
                line(3,16,8,16,11,8,15,23,19,12,22,16,27,16)
            elif kind=='database':
                c.create_oval(5,4,25,12,**kw)
                c.create_arc(5,4,25,23,start=180,extent=180,style='arc',outline=color,width=2)
                line(5,8,5,23);line(25,8,25,23)
                c.create_arc(5,18,25,28,start=180,extent=180,style='arc',outline=color,width=2)
                c.create_arc(5,11,25,19,start=180,extent=180,style='arc',outline=color,width=2)
            elif kind=='flag':
                line(7,26,7,4);line(7,5,24,5,20,12,24,19,7,19)
            elif kind=='chart':
                line(5,4,5,25,27,25);line(8,20,14,14,19,17,26,7)
            elif kind=='file':
                line(7,3,19,3,25,9,25,27,7,27,7,3)
                line(19,3,19,9,25,9);line(11,15,21,15);line(11,20,21,20)
            elif kind=='sliders':
                for y,x in ((7,11),(15,21),(23,14)):
                    line(4,y,26,y)
                    c.create_rectangle(x-3,y-4,x+3,y+4,fill=BG,outline=color,width=2)
            elif kind=='flask':
                line(11,3,19,3);line(13,3,13,12,5,25,7,27,23,27,25,25,17,12,17,3)
                line(9,20,21,20)
            elif kind=='check':
                c.create_oval(4,4,26,26,**kw);line(9,15,13,19,21,10)
            elif kind=='plus':
                c.create_oval(4,4,26,26,**kw);line(15,9,15,21);line(9,15,21,15)
            elif kind=='mail':
                c.create_rectangle(4,7,26,23,**kw);line(4,8,15,17,26,8)
            return c
        def section_title(text):
            ttk.Label(content,text=text,font=(UI_FONT,12,'bold')).pack(anchor='w',pady=(14,7))
        def paragraph(text,space=7):
            ttk.Label(content,text=text,wraplength=880,justify='left').pack(anchor='w',fill='x',pady=(0,space))
        ttk.Label(content,text='Digital Pressure Recorder',font=(UI_FONT,18,'bold')).pack(anchor='w',pady=(0,4))
        ttk.Label(content,text='A software by Eka Yudhi Pratama',font=(UI_FONT,10,'bold')).pack(anchor='w')
        ttk.Label(content,text='Version 1.0  •  November 2026').pack(anchor='w',pady=(5,12))
        paragraph('A Windows desktop application for real-time pressure monitoring, recording, and analysis using industrial pressure transmitters via Modbus RTU.')
        ttk.Separator(content).pack(fill='x',pady=(8,4))
        section_title('Key features')
        features=[
            ('Real-Time Pressure Monitoring','View live pressure readings with a continuously updating graph, connection status, and configurable display units (psi, bar, kPa, MPa).'),
            ('Pressure Data Recording','Record pressure measurements into organized sessions, with a configurable acquisition interval. Recommended interval: 0.5 seconds.'),
            ('Event Annotations','Mark important operational events during recording to provide context when reviewing pressure trends.'),
            ('Recording History & Analysis','Review previously recorded sessions with interactive graphs, zoom and pan controls, pressure statistics, and event markers.'),
            ('Reporting','Generate reports from recorded pressure data for documentation and operational review.'),
            ('Device Configuration','Configure serial port, baud rate, Modbus parameters, sampling interval, display units, and UTC offset.'),
            ('Simulation Mode','Test the monitoring and recording workflow without connecting physical hardware.'),
        ]
        feature_icons=['activity','database','flag','chart','file','sliders','flask']
        for (name,description),kind in zip(features,feature_icons):
            feature_row=ttk.Frame(content)
            feature_row.pack(fill='x',pady=(10,3))
            icon(feature_row,kind).pack(side='left',anchor='n',padx=(0,12))
            feature_text=ttk.Frame(feature_row)
            feature_text.pack(side='left',fill='x',expand=True)
            ttk.Label(feature_text,text=name,font=(UI_FONT,10,'bold')).pack(anchor='w')
            ttk.Label(feature_text,text=description,wraplength=820,justify='left').pack(anchor='w',pady=(3,0))
        ttk.Separator(content).pack(fill='x',pady=(14,4))
        section_title('Supported devices')
        for kind,description in [
            ('check','Aplisens PMS-970 — Modbus RTU'),
            ('plus','More devices coming soon. Contact the developer to request support for additional hardware.'),
        ]:
            device_row=ttk.Frame(content);device_row.pack(fill='x',pady=4)
            icon(device_row,kind,'#137a45' if kind=='check' else '#576677').pack(side='left',padx=(0,12))
            ttk.Label(device_row,text=description,wraplength=820,justify='left').pack(side='left',anchor='center')
        ttk.Separator(content).pack(fill='x',pady=(14,4))
        section_title('Status key')
        for name,description,color in [
            ('LIVE','Receiving valid readings','#137a45'),
            ('DISCONNECTED','No active device connection','#b55c00'),
            ('RECORDING','Saving pressure data','#c92c38'),
            ('REC OFF','Recording inactive','#576677'),
        ]:
            line=ttk.Frame(content);line.pack(fill='x',pady=4)
            tk.Label(line,text='●  '+name,bg=BG,fg=color,font=(UI_FONT,10),width=18,anchor='w').pack(side='left')
            ttk.Label(line,text=description).pack(side='left')
        ttk.Separator(content).pack(fill='x',pady=(14,4))
        section_title('Developer & Contact')
        paragraph('Eka Yudhi Pratama')
        for address in ('epratama2@slb.com','just_eka@ymail.com'):
            email_row=ttk.Frame(content);email_row.pack(fill='x',pady=2)
            icon(email_row,'mail','#576677').pack(side='left',padx=(0,10))
            ttk.Label(email_row,text=address).pack(side='left')
        ttk.Label(content,text='Digital Pressure Recorder  •  Version 1.0  •  November 2026').pack(anchor='w',pady=(15,10))

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
            s['interval']=float(s['interval'])
            s['utc_offset']=next(offset for offset,label in self.utc_offset_labels.items() if label==s['utc_offset'])
            if not 1<=s['address']<=247:raise ValueError('Slave address must be 1-247')
            if s['mode']=='Modbus RTU' and not s['port']:raise ValueError('Specify a COM port')
            s['auto_connect']=self.auto.get(); tmp=DATA/'settings.tmp'; tmp.write_text(json.dumps(s,indent=2)); tmp.replace(DATA/'settings.json')
            old_unit=self.settings['unit']
            self.settings=s
            if old_unit!=s['unit']:
                # Manual scale inputs reflect the selected display unit.
                self.live_min.set(f'{from_psi(to_psi(float(self.live_min.get()),old_unit),s["unit"]):.5f}')
                self.live_max.set(f'{from_psi(to_psi(float(self.live_max.get()),old_unit),s["unit"]):.5f}')
            self.connect(); self.show('Live Monitor')
        except Exception as e:messagebox.showerror('Settings',str(e))
    def make_viewer(self):
        p=self.pages['Viewer']
        top=ttk.Frame(p);top.pack(fill='x',pady=(0,7))
        ttk.Button(top,text='‹ History',style='Compact.TButton',
                   command=lambda:self.show('History')).pack(side='left')
        self.viewer_title=ttk.Label(top,text='Recording Viewer',style='Title.TLabel')
        self.viewer_title.pack(side='left',padx=12)
        ttk.Button(top,text='Create Report',style='Report.TButton',
                   command=lambda:self.open_reporting(self.viewer_sid)).pack(side='right',padx=(0,10))
        ttk.Button(top,text='Refresh',style='Compact.TButton',
                   command=lambda:self.load_viewer(self.viewer_sid)).pack(side='right')

        strip=ttk.Frame(p,padding=(10,7),relief='solid',borderwidth=1)
        strip.pack(fill='x',pady=(0,8))
        self.viewer_summary_vars={}
        summary_fields=(('min','Min pressure'),('max','Max pressure'),
                        ('first_pressure','Start pressure'),('last_pressure','Last pressure'),
                        ('start','Start time'),('stop','Stop time'),('duration','Duration'))
        for index,(key,label) in enumerate(summary_fields):
            strip.columnconfigure(index,weight=1,uniform='summary')
            cell=ttk.Frame(strip)
            cell.grid(row=0,column=index,sticky='ew',padx=3)
            ttk.Label(cell,text=label,font=(UI_FONT,8),foreground='#576677').pack(anchor='w')
            var=tk.StringVar(value='—')
            self.viewer_summary_vars[key]=var
            ttk.Label(cell,textvariable=var,font=(UI_FONT,10,'bold')).pack(anchor='w')

        self.viewer_toolbar=ttk.Frame(p);toolbar=self.viewer_toolbar
        toolbar.pack(fill='x',pady=(0,7))
        self.history_window=tk.StringVar(value='Buffer data')
        ttk.Label(toolbar,text='Window').pack(side='left')
        time_box=ttk.Combobox(toolbar,textvariable=self.history_window,
                             values=['1 min','5 min','10 min','15 min','30 min','1 hour','Buffer data'],
                             state='readonly',width=10)
        time_box.pack(side='left',padx=(5,12))
        time_box.bind('<<ComboboxSelected>>',lambda e:self.slide_history(0))
        ttk.Label(toolbar,text='Time display').pack(side='left')
        self.viewer_time_display=tk.StringVar(value='Date & time')
        time_display=ttk.Combobox(toolbar,textvariable=self.viewer_time_display,
                                  values=['Elapsed time','Date & time'],state='readonly',width=14)
        time_display.pack(side='left',padx=(5,10))
        time_display.bind('<<ComboboxSelected>>',lambda e:self.paint_viewer())
        self.viewer_scale_mode=tk.StringVar(value='Auto')
        ttk.Radiobutton(toolbar,text='Auto scale',value='Auto',variable=self.viewer_scale_mode,
                        command=self.select_viewer_scale).pack(side='left',padx=(0,5))
        ttk.Radiobutton(toolbar,text='Manual scale',value='Manual',variable=self.viewer_scale_mode,
                        command=self.select_viewer_scale).pack(side='left')
        ttk.Button(toolbar,text='Manual scale options',style='Compact.TButton',
                   command=self.show_viewer_scale_options).pack(side='left',padx=(8,0))

        self.viewer_bottom=ttk.Frame(p)
        self.viewer_bottom.pack(side='bottom',fill='x',pady=(4,0))
        self.viewer_bottom_toggle=ttk.Button(self.viewer_bottom,text='Hide detail and annotation',
                                             style='Compact.TButton',command=self.toggle_viewer_panel)
        self.viewer_bottom_toggle.pack(anchor='w')
        self.viewer_bottom_content=ttk.Frame(self.viewer_bottom)
        self.viewer_bottom_content.pack(fill='x',pady=(4,0))
        self.viewer_bottom_content.columnconfigure(0,weight=1,uniform='bottom')
        self.viewer_bottom_content.columnconfigure(1,weight=1,uniform='bottom')
        details=ttk.LabelFrame(self.viewer_bottom_content,text='Job details',padding=8)
        details.grid(row=0,column=0,sticky='nsew',padx=(0,7))
        annotations=ttk.LabelFrame(self.viewer_bottom_content,text='Annotations',padding=8)
        annotations.grid(row=0,column=1,sticky='nsew',padx=(7,0))
        details.columnconfigure(0,weight=1);details.columnconfigure(1,weight=1)
        self.viewer_details=ttk.Label(details,text='—',justify='left',anchor='nw')
        self.viewer_details.grid(row=0,column=0,sticky='nw',padx=(4,12),pady=(2,6))
        self.viewer_details_right=ttk.Label(details,text='—',justify='left',anchor='nw')
        self.viewer_details_right.grid(row=0,column=1,sticky='nw',padx=(4,0),pady=(2,6))
        ttk.Button(details,text='Edit job details',style='Compact.TButton',
                   command=self.edit_viewer_details).grid(row=1,column=0,columnspan=2,sticky='w')
        actions=ttk.Frame(annotations);actions.pack(fill='x',pady=(0,5))
        ttk.Label(actions,text='Right-click chart to annotate; left-click to select time',
                  foreground='#576677').pack(side='left')
        ttk.Button(actions,text='Delete selected',style='Compact.TButton',
                   command=self.delete_annotation).pack(side='right',padx=(5,0))
        ttk.Button(actions,text='Edit selected',style='Compact.TButton',
                   command=self.edit_annotation).pack(side='right',padx=(5,0))
        ttk.Button(actions,text='+ Add annotation',style='Compact.TButton',
                   command=self.add_annotation).pack(side='right')
        self.events_tree=ttk.Treeview(annotations,columns=('minute','label','kind'),
                                      show='headings',height=3,selectmode='browse')
        for col,width in [('minute',130),('label',220),('kind',110)]:
            self.events_tree.heading(col,text='Time' if col=='minute' else col.title())
            self.events_tree.column(col,width=width,minwidth=70,stretch=True)
        self.events_tree.pack(fill='x')
        self.events_tree.bind('<Double-1>',lambda e:self.edit_annotation())
        self.events_tree.bind('<<TreeviewSelect>>',self.select_history_event)
        self.annotation_time=tk.StringVar(value='')

        chart=ttk.Frame(p);chart.pack(fill='both',expand=True)
        self.vfig,self.vax,self.vcanvas=self.plot(chart)
        self.vcanvas.mpl_connect('button_press_event',self.chart_click)
        self.viewer_annotation_menu=tk.Menu(self,tearoff=0)
        self.viewer_annotation_menu.add_command(label='Add annotation here',
                                                 command=self.add_annotation)
        self.history_slider=TimeScrollbar(chart,self.slide_history)
        self.history_slider.pack(side='bottom',before=self.vcanvas.get_tk_widget(),fill='x')
        self.history_labels=tk.BooleanVar(value=True)
        # Retain export configuration for the future Reporting workspace.
        self.selected_export=tk.BooleanVar(value=False)
        self.view_vars={key:tk.StringVar(value=default)
                        for key,default in [('title',''),('xmin','0'),('xmax','1'),
                                            ('ymin','0'),('ymax','3000')]}
        self.chart_tools(self.vcanvas,chart,False)

    def toggle_viewer_panel(self):
        content=self.viewer_bottom_content
        if content.winfo_manager():
            content.pack_forget()
            self.viewer_bottom_toggle.configure(text='Show detail and annotation')
        else:
            content.pack(fill='x',pady=(4,0))
            self.viewer_bottom_toggle.configure(text='Hide detail and annotation')

    def load_viewer(self,sid):
        if not sid:return
        self.viewer_sid=sid; self.vsession=self.store.get(sid); self.vrows=self.store.plot_rows(sid); self.vevents=self.store.events(sid)
        d=json.loads(self.vsession['details']); self.viewer_title.config(text=(d.get('well') or 'Unnamed well')+'  |  '+(d.get('job') or 'Recording'))
        self.viewer_details.config(text='\n'.join(f'{label}: {d.get(key) or "—"}' for key,label in
                                                (('well','Well'),('job','Job'),('job_id','Job ID'),('engineer','Engineer'))))
        self.viewer_details_right.config(text='\n'.join((
            f'Client: {d.get("client") or "—"}',
            f'Job date: {d.get("job_date") or "—"}',
            f'Mode: {self.vsession["mode"]}',
            f'Notes: {d.get("notes") or "—"}'
        )))
        self.update_viewer_summary()
        self.annotation_time.set('')
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
        from matplotlib.ticker import FuncFormatter, MaxNLocator
        ax.xaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=2))
        def time_label(x,pos):
            if self.viewer_time_display.get()=='Elapsed time':
                seconds=int(round(x*60))
                return f'{seconds//60:02}:{seconds%60:02}'
            return stamp(start+x*60,self.settings['utc_offset'])[11:19]
        ax.xaxis.set_major_formatter(FuncFormatter(time_label))
        ax.tick_params(axis='x',labelrotation=0)
        ax.set(xlabel='Elapsed time (mm:ss)' if self.viewer_time_display.get()=='Elapsed time' else 'Date & time',
               ylabel='Pressure ('+self.settings['unit']+')',
               xlim=(v['xmin'],v['xmax']),ylim=(v['ymin'],v['ymax']))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda p,pos:f'{from_psi(p,self.settings["unit"]):,.1f}'))
        ax.grid(alpha=.2)
        if self.viewer_time_display.get()=='Date & time':
            from datetime import datetime,timezone,timedelta
            date=datetime.fromtimestamp(start+v['xmin']*60,timezone(timedelta(hours=self.settings['utc_offset']))).strftime('%d %b %Y')
            ax.set_xlabel(date+'  |  UTC'+f'{self.settings["utc_offset"]:+g}')
        for i in self.events_tree.get_children():self.events_tree.delete(i)
        for e in self.vevents:
            x=(e['ts']-start)/60; ax.axvline(x,ls='--',lw=.7,color='#bd7b1c')
            annotation=ax.annotate(e['label'] if self.history_labels.get() else '',(x,.95),xycoords=('data','axes fraction'),rotation=0,va='top',fontsize=8,bbox=dict(facecolor='#fff0b6',edgecolor='#d6ad45',pad=2),clip_on=True); annotation.draggable()
            self.events_tree.insert('','end',iid=str(e['id']),values=(stamp(e['ts'],self.settings['utc_offset'])[11:19],e['label'],e['kind']))
        self.vcanvas.draw_idle()
    def apply_view(self):
        try:v=self.view_values();self.store.update(self.viewer_sid,'view',v);self.viewer_scale_mode.set('Manual');self.paint_viewer();self.footer.config(text='Viewer configuration saved')
        except Exception as e:messagebox.showerror('Chart settings',str(e))
    def capture_view(self):
        for k,n in zip(['xmin','xmax','ymin','ymax'],[*self.vax.get_xlim(),*self.vax.get_ylim()]):self.view_vars[k].set(f'{n:.5f}')
        self.apply_view()
    def update_viewer_summary(self):
        if not self.viewer_sid:return
        lo,hi=self.recording_extrema(self.viewer_sid)
        with self.store.connect() as c:
            first=c.execute("SELECT value FROM samples WHERE session=? AND quality='OK' AND value IS NOT NULL ORDER BY ts ASC,id ASC LIMIT 1",(self.viewer_sid,)).fetchone()
            last=c.execute("SELECT value FROM samples WHERE session=? AND quality='OK' AND value IS NOT NULL ORDER BY ts DESC,id DESC LIMIT 1",(self.viewer_sid,)).fetchone()
        session=self.vsession
        begin=session['started']
        stop=session['ended'] or self.store.stats(self.viewer_sid)['last']
        elapsed=max(0,int((stop or begin)-begin))
        values={'min':'—' if lo is None else f'{from_psi(lo,self.settings["unit"]):,.2f} {self.settings["unit"]}',
                'max':'—' if hi is None else f'{from_psi(hi,self.settings["unit"]):,.2f} {self.settings["unit"]}',
                'first_pressure':'—' if first is None else f'{from_psi(first["value"],self.settings["unit"]):,.2f} {self.settings["unit"]}',
                'last_pressure':'—' if last is None else f'{from_psi(last["value"],self.settings["unit"]):,.2f} {self.settings["unit"]}',
                'start':stamp(begin,self.settings['utc_offset'])[11:19],
                'stop':stamp(stop,self.settings['utc_offset'])[11:19] if stop else '—',
                'duration':f'{elapsed//60}m {elapsed%60:02}s'}
        for name,value in values.items():self.viewer_summary_vars[name].set(value)

    def select_viewer_scale(self):
        if self.viewer_scale_mode.get()=='Auto':
            self.auto_history_scale()
        else:
            self.apply_view()

    def show_viewer_scale_options(self):
        if getattr(self,'viewer_scale_dialog',None) and self.viewer_scale_dialog.winfo_exists():
            self.viewer_scale_dialog.lift();return
        win=tk.Toplevel(self);win.title('Manual scale options');win.transient(self)
        win.resizable(False,False);self.viewer_scale_dialog=win
        content=ttk.Frame(win,padding=14);content.pack(fill='both',expand=True)
        display_limits={}
        for i,(label,key) in enumerate((('Pressure min','ymin'),('Pressure max','ymax'))):
            ttk.Label(content,text=label+' ('+self.settings['unit']+')').grid(row=i,column=0,sticky='w',pady=5,padx=(0,12))
            display_limits[key]=tk.StringVar(value=f'{from_psi(float(self.view_vars[key].get()),self.settings["unit"]):.5f}')
            ttk.Entry(content,textvariable=display_limits[key],width=14).grid(row=i,column=1,pady=5)
        def apply_display_limits():
            try:
                lo=to_psi(float(display_limits['ymin'].get()),self.settings['unit'])
                hi=to_psi(float(display_limits['ymax'].get()),self.settings['unit'])
                if not math.isfinite(lo) or not math.isfinite(hi) or lo>=hi:
                    raise ValueError('Minimum must be lower than maximum.')
                self.view_vars['ymin'].set(str(lo))
                self.view_vars['ymax'].set(str(hi))
                self.apply_view()
            except ValueError as exc:messagebox.showerror('Pressure scale',str(exc),parent=win)
        ttk.Checkbutton(content,text='Show event labels',variable=self.history_labels,
                        command=self.paint_viewer).grid(row=2,column=0,columnspan=2,sticky='w',pady=8)
        ttk.Button(content,text='Apply manual scale',style='Compact.TButton',
                   command=apply_display_limits).grid(row=3,column=0,columnspan=2,sticky='ew',pady=(6,3))
        ttk.Button(content,text='Close',style='Compact.TButton',
                   command=win.destroy).grid(row=4,column=0,columnspan=2,sticky='ew')

    def chart_click(self,event):
        if event.inaxes!=self.vax or event.xdata is None or not self.viewer_sid:
            return
        # Ignore middle-button pan and other navigation modes.
        if event.button not in (1,3):return
        if getattr(self.vcanvas.toolbar,'mode',''):return
        self.annotation_time.set(f'{event.xdata:.8f}')
        if event.button==3:
            # Matplotlib button_press_event exposes GUI pixel coordinates.
            widget=self.vcanvas.get_tk_widget()
            self.viewer_annotation_menu.tk_popup(widget.winfo_rootx()+int(event.x),
                                                 widget.winfo_rooty()+widget.winfo_height()-int(event.y))
            self.viewer_annotation_menu.grab_release()
        else:
            self.footer.config(text='Annotation position selected — right-click to add annotation')
    def add_annotation(self):
        if not self.viewer_sid:return
        try:
            selected=self.annotation_time.get().strip()
            if not selected:
                messagebox.showinfo('Add annotation','Left-click a time on the chart, or right-click the chart and select Add annotation here.')
                return
            ts=self.vsession['started']+float(selected)*60
            last=self.vsession['ended'] or self.store.stats(self.viewer_sid)['last'] or self.vsession['started']
            if not self.vsession['started']<=ts<=last:
                raise ValueError('Choose a time within the recording.')
            label=simpledialog.askstring('Review annotation',
                                         'Label for '+stamp(ts,self.settings['utc_offset'])[11:19]+':',
                                         parent=self)
            if label and label.strip():
                self.store.event(self.viewer_sid,ts,label.strip(),'Review')
                self.vevents=self.store.events(self.viewer_sid)
                self.paint_viewer()
        except ValueError as e:messagebox.showerror('Annotation',str(e))
    def delete_annotation(self):
        selected=self.events_tree.selection()
        if not selected or not self.viewer_sid:return
        event=next((e for e in self.vevents if str(e['id'])==selected[0]),None)
        if event is None:return
        when=stamp(event['ts'],self.settings['utc_offset'])[11:19]
        if not messagebox.askyesno('Delete annotation',
                f'Delete annotation "{event["label"]}" at {when}?\n\n'
                'This cannot be undone.',icon='warning',parent=self):
            return
        try:
            if self.store.delete_event(event['id'],self.viewer_sid):
                self.vevents=self.store.events(self.viewer_sid)
                self.paint_viewer()
                self.footer.configure(text='Annotation deleted')
        except Exception as exc:
            messagebox.showerror('Delete annotation',str(exc),parent=self)

    def edit_annotation(self):
        selected=self.events_tree.selection()
        if not selected:return
        event=next((e for e in self.vevents if str(e['id'])==selected[0]),None)
        if not event:return
        start=self.vsession['started']
        elapsed=max(0,int(round(event['ts']-start)))
        win=tk.Toplevel(self);win.title('Edit annotation');win.transient(self)
        win.resizable(False,False)
        body=ttk.Frame(win,padding=14);body.pack(fill='both',expand=True)
        ttk.Label(body,text='Elapsed time (mm:ss)').grid(row=0,column=0,sticky='w',padx=(0,12),pady=6)
        time_var=tk.StringVar(value=f'{elapsed//60:02}:{elapsed%60:02}')
        ttk.Entry(body,textvariable=time_var,width=20).grid(row=0,column=1,sticky='ew',pady=6)
        ttk.Label(body,text='Label').grid(row=1,column=0,sticky='w',padx=(0,12),pady=6)
        label_var=tk.StringVar(value=event['label'])
        ttk.Entry(body,textvariable=label_var,width=30).grid(row=1,column=1,sticky='ew',pady=6)
        def save():
            try:
                raw=time_var.get().strip()
                parts=raw.split(':')
                if len(parts)!=2 or not all(part.isdigit() for part in parts):
                    raise ValueError('Enter elapsed time as mm:ss, for example 01:30.')
                minutes,seconds=map(int,parts)
                if seconds>=60:raise ValueError('Seconds must be between 00 and 59.')
                ts=start+minutes*60+seconds
                last=self.vsession['ended'] or self.store.stats(self.viewer_sid)['last'] or start
                if not start<=ts<=last:raise ValueError('Annotation time must be within the recording.')
                label=label_var.get().strip()
                if not label:raise ValueError('Annotation label cannot be empty.')
                self.store.edit_event(event['id'],ts,label)
                self.vevents=self.store.events(self.viewer_sid)
                self.paint_viewer()
                self.events_tree.selection_set(str(event['id']))
                self.events_tree.see(str(event['id']))
                win.destroy()
            except ValueError as exc:messagebox.showerror('Edit annotation',str(exc),parent=win)
        buttons=ttk.Frame(body);buttons.grid(row=2,column=0,columnspan=2,sticky='e',pady=(12,0))
        ttk.Button(buttons,text='Cancel',style='Compact.TButton',command=win.destroy).pack(side='right',padx=(6,0))
        ttk.Button(buttons,text='Save changes',style='Compact.TButton',command=save).pack(side='right')
        win.bind('<Return>',lambda e:save())
        win.grab_set()

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
        # Give shutdown priority over drawing charts or processing queued samples.
        # Otherwise the UI can look frozen even after the window's X is clicked.
        if self.closing:
            # Shutdown completion is handled by _finish_close, independent from the
            # acquisition/chart refresh timer.
            return
        try:
            while True:
                kind,d=self.engine.messages.get_nowait()
                if kind in ('sample','connected','communication_error') and d.get('generation')!=self.connection_generation:
                    continue
                if kind=='sample':
                    s=d['sample'];self.latest=s;self.buffer.append(s)
                    self.connection_pending=False
                    self.connection_timed_out=False
                    self.connect_btn.config(state='normal')
                    if s['quality']=='OK':self.value.config(text=f"{from_psi(s['value'],self.settings['unit']):,.2f} {self.settings['unit']}")
                    self.reading_status.config(text=f"{self.settings['mode'].upper()}  |  {s['quality']}  |  {stamp(s['ts'],self.settings['utc_offset'])[11:23]}",fg='#008b92' if s['quality']=='OK' else '#b45309')
                    if d['sid']:self.rec_count+=1;self.rec_errors+=s['quality']!='OK'
                elif kind=='connected':
                    self.connected=True
                    self.connection.config(text=d['settings']['mode']+'  |  '+(d['settings']['port'] or 'virtual sensor'))
                    self.connect_btn.config(text='Disconnect',state='normal')
                    self.reading_status.config(text='WAITING FOR FIRST READING',fg=INK)
                elif kind=='disconnected':
                    if self.connection_pending:continue
                    self.connected=False;self.connection.config(text='Disconnected');self.connect_btn.config(text='Connect',state='normal');self.reading_status.config(text='STALE  |  disconnected',fg='#b45309');self.latest=None
                elif kind=='started':
                    self.last_recording=d['sid'];self.sid=d['sid'];self.pending=False;self.rec_started=time.monotonic();self.rec_count=0;self.rec_errors=0;self.record_btn.config(text='■ Stop Recording',style='Stop.TButton',state='normal');self.event_btn.config(state='normal');self.load_details(self.sid)
                elif kind in ('stopped','storage_error'):
                    self.sid=None;self.pending=False;self.record_btn.config(text='⏺ Start recording',style='Record.TButton',state='normal');self.event_btn.config(state='disabled');self.rec_label.config(text='Preview only  |  not saved')
                    if kind=='storage_error':messagebox.showerror('RECORDING STOPPED - storage failure',d['text'])
                elif kind=='communication_error':
                    self.footer.config(text='Modbus communication error: '+d['text'][:160])
                elif kind=='exported':self.exporting=False;self.footer.config(text='Export saved: '+d['path'])
                elif kind=='export_error':self.exporting=False;messagebox.showerror('Export failed',d['text'])
                elif kind=='error':
                    self.pending=False;self.record_btn.config(state='normal')
                    if self.connection_pending:
                        self.connection_pending=False;self.connected=False
                        self.connect_btn.config(text='Connect',state='normal')
                        self.connection.config(text='Connection failed')
                        self.reading_status.config(text='CONNECTION ERROR',fg='#b45309')
                        self.footer.config(text='Connection error: '+d['text'][:160])
                    else:
                        messagebox.showerror('PMS Logger',d['text'])
        except queue.Empty:pass
        if self.sid:
            self.rec_label.config(text=f'{self.rec_count:,} samples  |  {self.rec_errors} errors')
        if self.latest and time.time()-self.latest['ts']>max(2,3*self.settings['interval']):self.reading_status.config(text='STALE  |  waiting for new reading',fg='#b45309')
        if self.page=='Live Monitor' and self.buffer and time.monotonic()-self.last_plot>.5:
            self.last_plot=time.monotonic(); rows=list(self.buffer); end=rows[-1]['ts']; seconds={'1 min':60,'5 min':300,'10 min':600,'15 min':900,'30 min':1800,'1 hour':3600,'Buffer data':1e20}[self.window.get()]
            rows=[r for r in rows if r['ts']>=end-seconds] if self.follow.get() else rows
            from matplotlib.ticker import FuncFormatter, MaxNLocator
            self.lax.xaxis.set_major_locator(MaxNLocator(nbins=5, min_n_ticks=2))
            self.line.set_data([r['ts'] for r in rows],[r['value'] if r['quality']=='OK' else math.nan for r in rows]);self.lax.set_ylabel('Pressure ('+self.settings['unit']+')');self.lax.yaxis.set_major_formatter(FuncFormatter(lambda p,pos:f'{from_psi(p,self.settings["unit"]):,.1f}'))
            self.lax.xaxis.set_major_formatter(FuncFormatter(lambda x,pos:stamp(x,self.settings['utc_offset'])[11:19]))
            self.lax.tick_params(axis='x',labelrotation=0)
            from datetime import datetime,timezone,timedelta
            date=datetime.fromtimestamp(end,timezone(timedelta(hours=self.settings['utc_offset']))).strftime('%d %b %Y')
            self.lax.set_xlabel(date+'  |  UTC'+f'{self.settings["utc_offset"]:+g}')
            if self.follow.get():
                self.lax.set_autoscaley_on(self.live_auto.get());self.lax.relim();self.lax.autoscale_view(scaley=self.live_auto.get());self.lax.set_xlim(max(rows[0]['ts'],end-seconds),max(end,rows[0]['ts']+1))
            self.lcanvas.draw_idle()
        self._check_connection_watchdog()
        self._check_modbus_timeout()
        self.update_enhancements()
        self._tick_after_id=self.after(80,self.tick)
    def _check_modbus_timeout(self):
        """Report missing Modbus replies even when the serial worker is blocked."""
        if self.settings['mode']!='Modbus RTU' or self.connection_timed_out:
            return
        if not self.connect_started or time.monotonic()-self.connect_started<5:
            return
        if self.latest and self.latest['quality']=='OK' and time.time()-self.latest['ts']<=max(2,3*self.settings['interval']):
            return
        self.connection_timed_out=True
        self.connection_pending=False
        self.reading_status.config(text='CONNECTION TIMEOUT  |  NO DATA',fg='#b45309')
        self.connection.config(text='Modbus RTU  |  '+(self.settings['port'] or 'No port')+'  |  timeout')
        self.connect_btn.config(text='Disconnect',state='normal')
        self.footer.config(text='No valid Modbus response within 5 seconds; check port and device')
        # Do not pretend a serial worker was stopped: it may still be blocked.
        # A late valid sample may recover the status normally.

    def _check_connection_watchdog(self):
        """Recover a stalled Modbus-to-Simulation switch without blocking Tk."""
        if not self.connection_pending or self.settings['mode']!='Simulation' or self.simulation_recovery_attempted:
            return
        if time.monotonic()-self.connect_started<2.5:
            return
        if self.sid or self.pending:
            return  # Never abandon a worker that may be saving a recording.
        self.simulation_recovery_attempted=True
        old=self.engine
        # A blocked serial read cannot be interrupted safely on every Windows driver.
        # Queue retirement, then run the independent simulator on a fresh worker.
        old.send('quit')
        self.retired_engines.append(old)
        self.engine=Engine(self.store)
        self.engine.start()
        self.connect_started=time.monotonic()
        self.footer.config(text='Serial worker unresponsive; restarting simulation worker')
        self.engine.send('connect',dict(self.settings),self.connection_generation)

    def _shutdown_trace(self,message):
        """Local diagnostic trail when a Windows close request appears stuck."""
        try:
            with (DATA/'shutdown.log').open('a',encoding='utf-8') as log:
                log.write(time.strftime('%Y-%m-%d %H:%M:%S')+'  '+message+'\n')
        except OSError:
            pass

    def _finish_close(self):
        """Independent shutdown poll; never relies on live-chart tick callbacks."""
        if not self.closing:return
        if not self.engine.is_alive():
            self._shutdown_trace('worker stopped; destroying window')
            if self._tick_after_id is not None:
                try:self.after_cancel(self._tick_after_id)
                except tk.TclError:pass
                self._tick_after_id=None
            self._shutdown_complete=True
            try:
                self.instance_lock.close()
            finally:
                self.destroy()
            return
        if time.monotonic()-self.close_started>8 and not self.shutdown_warning_shown:
            self.shutdown_warning_shown=True
            self._shutdown_trace('worker still alive after 8s; waiting for safe shutdown')
            self.footer.config(text='Device worker still stopping — see data/shutdown.log')
        # The worker is daemonized. A blocked Windows serial driver must not
        # prevent exit when no recording is being finalized. Never force exit
        # while the worker may still be writing an active recording.
        if time.monotonic()-self.close_started>10 and not self.sid and not self.pending:
            self._shutdown_trace('worker unresponsive; closing UI after grace period')
            self._shutdown_complete=True
            try:self.instance_lock.close()
            finally:self.destroy()
            return
        self.after(60,self._finish_close)

    def close(self):
        if self.closing:return
        self._shutdown_trace('close requested; recording='+str(bool(self.sid))
                             +'; pending='+str(bool(self.pending))
                             +'; export='+str(bool(self.exporting)))
        if self.exporting:
            messagebox.showinfo('Export running',
                'Please wait for the export to finish before closing.',parent=self)
            return
        if (self.sid or self.pending) and not messagebox.askyesno(
                'Stop and exit?','Stop recording, save and exit?',parent=self):
            self._shutdown_trace('close cancelled by operator')
            return
        try:
            if self.save_job:
                self.after_cancel(self.save_job)
                self.save_job=None
                if self.save_details() is False:
                    self._shutdown_trace('close blocked: metadata save failed')
                    return
        except Exception as exc:
            self._shutdown_trace('close blocked: metadata error '+type(exc).__name__)
            messagebox.showerror('Cannot close safely',
                'Recording details could not be saved. Please retry.\n'+str(exc),parent=self)
            return
        self.closing=True
        if self.sleep_prevention_active:
            try:ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)  # ES_CONTINUOUS
            except (AttributeError,OSError):pass
            self.sleep_prevention_active=False
        if self._tick_after_id is not None:
            try:self.after_cancel(self._tick_after_id)
            except tk.TclError:pass
            self._tick_after_id=None
        self.close_started=time.monotonic()
        self.shutdown_warning_shown=False
        self.footer.config(text='Saving and closing...')
        self._shutdown_trace('quit sent to acquisition worker')
        self.engine.send('quit')
        for old in self.retired_engines:
            if old.is_alive():old.send('quit')
        self.after(0,self._finish_close)

    def enhance(self):
        self.last_recording=None; self.enhanced_last=0; self.live_artists=[]
        self.bind('<Configure>', self.adapt_width, add='+')
        self.live_min=tk.StringVar(value='0');self.live_max=tk.StringVar(value=f'{from_psi(3000,self.settings["unit"]):.4f}');self.live_auto=tk.BooleanVar(value=True)
        self.live_labels=tk.BooleanVar(value=True)
        self.live_slider=TimeScrollbar(self.lcanvas.get_tk_widget().master,self.slide_live)
        self.live_slider.pack(after=self.lcanvas.get_tk_widget(),fill='x')
        self.live_events=ttk.Treeview(self.lcanvas.get_tk_widget().master,columns=('time','event'),show='headings',height=2)
        self.live_events.heading('time',text='Time');self.live_events.heading('event',text='Event');self.live_events.pack(after=self.live_slider,fill='x')
        self.live_events.insert('','end',iid='empty',values=('','No events yet'))
        self.events_expanded=False
        self.live_event_toggle=ttk.Button(self.lcanvas.get_tk_widget().master,
                                          text='Events (0)  ▸  Show event list',
                                          command=self.toggle_live_events)
        self.live_event_toggle.pack(after=self.live_events,fill='x')
        self.live_events.bind('<<TreeviewSelect>>',self.select_live_event)
        self.live_events.bind('<Double-1>',self.edit_live_event)
        self.lcanvas.mpl_connect('motion_notify_event',lambda e:self.hover(e,False))
        self.vcanvas.mpl_connect('motion_notify_event',lambda e:self.hover(e,True))
        self.ltip=None;self.vtip=None;self.hover_artists={}
        for canvas in (self.lcanvas,):
            widget=canvas.get_tk_widget()
            widget.pack_forget()
            # Bottom controls and navigator claim their space before the flexible plot.
            siblings = [self.live_events,self.live_event_toggle,self.live_slider] if canvas==self.lcanvas else [self.history_slider]
            for item in siblings:
                item.pack_forget()
                item.pack(side='bottom',fill='x')
            widget.pack(fill='both',expand=True)
        # Event list is opt-in; the graph receives the reclaimed vertical space.
        self.live_events.pack_forget()
        self.find_ports()

    def scroll_page(self,event):
        page=getattr(self,'page',None)
        if page not in ('Settings','About','Reporting'):return
        canvas={'Settings':self.settings_canvas,'About':self.about_canvas,'Reporting':self.reporting_canvas}[page]
        target=self.winfo_containing(event.x_root,event.y_root)
        current=target
        while current is not None and current!=canvas:
            if current==canvas.master:break
            current=current.master
        if current!=canvas:return
        if getattr(event,'num',None)==4:delta=-1
        elif getattr(event,'num',None)==5:delta=1
        else:
            wheel=getattr(event,'delta',0)
            if not wheel:return
            delta=-1 if wheel>0 else 1
        canvas.yview_scroll(delta,'units')
        return 'break'

    def adapt_width(self,event):
        if event.widget!=self:return
        compact=event.width<1120
        if compact==getattr(self,'compact',None):return
        self.compact=compact
        self.brand.config(font=(UI_FONT,14 if compact else 15,'bold'),
                          padx=6 if compact else 12)
        for button in self.nav_buttons.values():
            button.config(padx=6 if compact else 10)
        visible=str(self.details_panel) in self.live_pane.panes()
        if compact and visible:
            self.live_pane.forget(self.details_panel)
        elif not compact and self.details_user_visible and not visible:
            self.live_pane.add(self.details_panel,weight=1)
        # Settings actions replaced the former About panel. Keep both columns
        # on wide screens; stack them on narrow windows without hiding controls.
        self.settings_device.grid_configure(padx=(0,0) if compact else (0,8))
        self.settings_display.grid_configure(padx=(0,0) if compact else (0,8))
        self.settings_actions.grid_forget()
        if compact:
            self.settings_columns.columnconfigure(1,weight=0)
            self.settings_actions.grid(row=2,column=0,sticky='ew',pady=(12,0))
        else:
            self.settings_columns.columnconfigure(1,weight=2)
            self.settings_actions.grid(row=0,column=1,rowspan=2,
                                       sticky='nsew',padx=(8,0),pady=(0,10))

    def show_live_options(self):
        if getattr(self,'live_options',None) and self.live_options.winfo_exists():
            self.live_options.lift()
            return
        win=tk.Toplevel(self)
        win.title('Manual scale options')
        win.transient(self)
        win.resizable(False,False)
        self.live_options=win
        body=ttk.Frame(win,padding=14);body.pack(fill='both',expand=True)
        for row,(label,var) in enumerate((('Pressure min',self.live_min),('Pressure max',self.live_max))):
            ttk.Label(body,text=label+' ('+self.settings['unit']+')').grid(row=row,column=0,sticky='w',padx=(0,10),pady=5)
            ttk.Entry(body,textvariable=var,width=14).grid(row=row,column=1,sticky='ew',pady=5)
        ttk.Checkbutton(body,text='Show event labels',variable=self.live_labels,
                        command=self.paint_live_events).grid(row=2,column=0,columnspan=2,sticky='w',pady=(10,6))
        ttk.Button(body,text='Apply manual scale',style='Compact.TButton',
                   command=self.apply_live_scale).grid(row=3,column=0,columnspan=2,sticky='ew',pady=(8,3))
        ttk.Button(body,text='Close',style='Compact.TButton',command=win.destroy).grid(row=4,column=0,columnspan=2,sticky='ew')

    def select_live_scale(self):
        self.live_auto.set(self.scale_mode.get()=='Auto')
        self.toggle_live_auto_scale()

    def toggle_live_auto_scale(self):
        self.scale_mode.set('Auto' if self.live_auto.get() else 'Manual')
        self.lax.set_autoscaley_on(self.live_auto.get())
        if self.live_auto.get():
            self.lax.relim()
            self.lax.autoscale_view(scaley=True)
        else:
            try:
                lo,hi=to_psi(float(self.live_min.get()),self.settings['unit']),to_psi(float(self.live_max.get()),self.settings['unit'])
                if math.isfinite(lo) and math.isfinite(hi) and lo<hi:self.lax.set_ylim(lo,hi)
            except ValueError:pass
        self.lcanvas.draw_idle()

    def apply_live_scale(self):
        try:
            lo,hi=to_psi(float(self.live_min.get()),self.settings['unit']),to_psi(float(self.live_max.get()),self.settings['unit'])
            if not math.isfinite(lo) or not math.isfinite(hi) or lo>=hi:
                raise ValueError('Minimum must be less than maximum; use finite numbers.')
            self.live_auto.set(False)
            self.scale_mode.set('Manual')
            self.lax.set_ylim(lo,hi)
            self.lcanvas.draw_idle()
        except ValueError as exc:
            messagebox.showerror('Pressure scale',str(exc))

    def window_seconds(self,name):
        return {'1 min':60,'5 min':300,'10 min':600,'15 min':900,'30 min':1800,'1 hour':3600,'Buffer data':float('inf')}[name]

    def slide_live(self,value):
        if not self.buffer:return
        lo,hi=self.buffer[0]['ts'],self.buffer[-1]['ts']; width=min(self.window_seconds(self.window.get()),max(hi-lo,1))
        start=lo+max(0,hi-lo-width)*float(value)/100
        self.follow.set(False);self.lax.set_xlim(start,start+width)
        self.lcanvas.draw_idle()

    def slide_history(self,value):
        if not self.viewer_sid or not self.vrows:return
        duration=max((self.vrows[-1]['ts']-self.vsession['started'])/60,.01)
        width=min(duration,self.window_seconds(self.history_window.get())/60)
        start=max(0,duration-width)*float(value)/100
        self.view_vars['xmin'].set(str(start));self.view_vars['xmax'].set(str(start+width))
        self.vax.set_xlim(start,start+width)
        self.vcanvas.draw_idle()

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
            unit=self.settings['unit']
            text=f"Time: {stamp(row['ts'],self.settings['utc_offset'])[11:23]}\nPressure: {from_psi(y,unit):,.2f} {unit}\nQuality: {row['quality']}"
        if not near:
            marker,=ax.plot([x],[y],'o',color='#008b86',ms=5)
            guide=ax.axvline(x,color='#66798a',ls='--',lw=.7)
            horizontal=ax.axhline(y,color='#66798a',ls=':',lw=.6,alpha=.65)
            self.hover_artists[attr]=(marker,guide,horizontal)
        tip=ax.annotate(text,(x,y),xytext=(-12 if event.x>ax.bbox.xmax-160 else 12,-16 if event.y>ax.bbox.ymax-60 else 16),ha='right' if event.x>ax.bbox.xmax-160 else 'left',va='top' if event.y>ax.bbox.ymax-60 else 'bottom',textcoords='offset points',bbox=dict(boxstyle='round',fc='white',ec='#17334c'),fontsize=9)
        setattr(self,attr,tip);canvas.draw_idle()

    def recording_extrema(self,sid):
        with self.store.connect() as c:
            return c.execute("SELECT min(value),max(value) FROM samples WHERE session=? AND quality='OK'",(sid,)).fetchone()

    def update_enhancements(self):
        valid=not self.connection_pending and self.connected and self.latest and self.latest['quality']=='OK' and time.time()-self.latest['ts']<=max(2,3*self.settings['interval'])
        self.status_live.config(text=('SIMULATION MODE' if self.settings['mode']=='Simulation' else '● LIVE') if valid else ('CONNECTING...' if self.connection_pending else 'CONNECTION TIMEOUT' if self.connection_timed_out else 'DISCONNECTED / NO DATA'),bg=('#415875' if self.settings['mode']=='Simulation' else '#137a45') if valid else '#b55c00',fg='white',padx=8,pady=4)
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
                label.config(text='—' if value is None else f'{from_psi(value,self.settings["unit"]):,.2f} {self.settings["unit"]}')
            self.paint_live_events()
        if self.viewer_sid and self.page=='Viewer':
            self.update_viewer_summary()

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
        self.update_live_event_toggle()
        self.lcanvas.draw_idle()

    def toggle_live_events(self):
        self.events_expanded=not self.events_expanded
        if self.events_expanded:
            self.live_events.pack(side='bottom',fill='x',before=self.live_event_toggle)
        else:
            self.live_events.pack_forget()
        self.update_live_event_toggle()

    def update_live_event_toggle(self):
        count=0 if not self.last_recording else len(self.store.events(self.last_recording))
        arrow='▾  Hide event list' if self.events_expanded else '▸  Show event list'
        self.live_event_toggle.config(text=f'Events ({count})  {arrow}')

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
