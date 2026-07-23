from __future__ import annotations
import json,sys
from pathlib import Path
from PySide6.QtCore import Qt,QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import *
from app.bootstrap import ApplicationContext, create_application_context
from app.csv_loader import load_jobs
from app.gui.dialogs import NewProjectDialog,RecentProjectsDialog
from app.models.ui_state import SettingsViewData

COLORS={'pending':'#9CA3AF','running':'#F59E0B','completed':'#22C55E','skipped':'#60A5FA','failed':'#EF4444'}

class Card(QFrame):
    def __init__(self,title):
        super().__init__(); self.setObjectName('card'); lay=QVBoxLayout(self); self.value=QLabel('0'); self.value.setObjectName('cardValue'); cap=QLabel(title); cap.setObjectName('cardCaption'); lay.addWidget(self.value); lay.addWidget(cap)

class MainWindow(QMainWindow):
    def __init__(self, context: ApplicationContext):
        super().__init__(); self.setWindowTitle('S Talking — AI Audio Studio v0.3'); self.resize(1420,860)
        self.context=context; self.project_controller=context.project_controller; self.generation_controller=context.generation_controller; self.settings_controller=context.settings_controller; self.notifications=context.notification_service
        self.notifications.parent=self
        self.project_path=None
        self.autosave_timer=QTimer(self); self.autosave_timer.setInterval(30000); self.autosave_timer.timeout.connect(self.autosave); self.autosave_timer.start()
        self.build(); self.load_saved(); self.theme(); self.update_window_title()
    def build(self):
        self.build_project_menu()
        c=QWidget(); self.setCentralWidget(c); root=QVBoxLayout(c)
        head=QHBoxLayout(); brand=QVBoxLayout(); t=QLabel('S Talking'); t.setObjectName('title'); st=QLabel('Professional AI Audio Studio'); st.setObjectName('subtitle'); brand.addWidget(t); brand.addWidget(st); head.addLayout(brand); head.addStretch()
        for tx,fn in [('New',self.new_project),('Open project',self.open_project),('Save project',self.save_project)]: b=QPushButton(tx); b.clicked.connect(fn); head.addWidget(b)
        root.addLayout(head)
        cards=QHBoxLayout(); self.cards={}
        for k,tx in [('files','Files'),('chars','Characters'),('done','Completed'),('failed','Failed'),('eta','Estimated time')]: card=Card(tx); self.cards[k]=card; cards.addWidget(card)
        root.addLayout(cards)
        box=QGroupBox('Project sources'); g=QGridLayout(box); self.csv=QLineEdit(); self.out=QLineEdit(str(self.project_controller.default_output_path)); bc=QPushButton('Browse CSV'); bo=QPushButton('Output folder'); bl=QPushButton('Load CSV'); bc.clicked.connect(self.pick_csv); bo.clicked.connect(self.pick_out); bl.clicked.connect(self.load_csv); g.addWidget(QLabel('CSV file'),0,0); g.addWidget(self.csv,0,1); g.addWidget(bc,0,2); g.addWidget(bl,0,3); g.addWidget(QLabel('Output'),1,0); g.addWidget(self.out,1,1); g.addWidget(bo,1,2,1,2); root.addWidget(box)
        split=QSplitter(Qt.Horizontal); root.addWidget(split,1)
        sb=QGroupBox('Provider settings'); form=QFormLayout(sb); self.provider=QComboBox(); self.provider.addItems(['mock','piper','elevenlabs']); self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.voice=QLineEdit(); self.model=QLineEdit('eleven_multilingual_v2'); self.piper=QLineEdit(); pbtn=QPushButton('Browse'); pbtn.clicked.connect(self.pick_piper); prow=QWidget(); pl=QHBoxLayout(prow); pl.setContentsMargins(0,0,0,0); pl.addWidget(self.piper); pl.addWidget(pbtn)
        self.stability=self.slider(45); self.similarity=self.slider(75); self.style=self.slider(20); self.speed=QDoubleSpinBox(); self.speed.setRange(.7,1.2); self.speed.setValue(1); self.delay=QDoubleSpinBox(); self.delay.setRange(0,60); self.delay.setValue(.5); self.retries=QSpinBox(); self.retries.setRange(0,10); self.retries.setValue(4); self.boost=QCheckBox(); self.boost.setChecked(True); self.skip=QCheckBox(); self.skip.setChecked(True)
        for a,b in [('Provider',self.provider),('API key',self.key),('Voice ID',self.voice),('Model ID',self.model),('Piper model',prow),('Stability',self.stability),('Similarity',self.similarity),('Style',self.style),('Speed',self.speed),('Delay',self.delay),('Retries',self.retries),('Speaker boost',self.boost),('Skip existing',self.skip)]: form.addRow(a,b)
        split.addWidget(sb)
        mid=QWidget(); ml=QVBoxLayout(mid); self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['#','Filename','Text','Status','Time','Retry','Provider']); self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); self.table.itemSelectionChanged.connect(self.preview); ml.addWidget(self.table); split.addWidget(mid)
        pb=QGroupBox('Selected row'); pv=QVBoxLayout(pb); self.pname=QLabel('No row selected'); self.pname.setObjectName('previewTitle'); self.pmeta=QLabel(''); self.ptext=QPlainTextEdit(); self.ptext.setReadOnly(True); pv.addWidget(self.pname); pv.addWidget(self.pmeta); pv.addWidget(self.ptext); split.addWidget(pb); split.setSizes([330,760,330])
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumHeight(140); root.addWidget(self.log); self.bar=QProgressBar(); root.addWidget(self.bar)
        ctr=QHBoxLayout(); self.startb=QPushButton('Start'); self.pauseb=QPushButton('Pause'); self.stopb=QPushButton('Stop'); saveb=QPushButton('Save settings'); self.startb.clicked.connect(self.start); self.pauseb.clicked.connect(self.pause); self.stopb.clicked.connect(self.stop); saveb.clicked.connect(self.save_settings); ctr.addWidget(self.startb); ctr.addWidget(self.pauseb); ctr.addWidget(self.stopb); ctr.addStretch(); ctr.addWidget(saveb); root.addLayout(ctr)
        self.generation_controller.progress.connect(self.progress); self.generation_controller.log.connect(self.log.appendPlainText); self.generation_controller.finished.connect(self.finished); self.generation_controller.failed.connect(self.failed)
        self.provider.currentTextChanged.connect(self.provider_changed); self.provider_changed('mock')
        for w in [self.stability,self.similarity,self.style,self.speed,self.delay,self.retries,self.boost,self.skip]: w.valueChanged.connect(self.settings_changed) if hasattr(w,'valueChanged') else w.toggled.connect(self.settings_changed)
    def build_project_menu(self):
        self.project_menu=QMenu('Project',self); self.menuBar().addMenu(self.project_menu)
        for tx,fn in [('New Project',self.new_project),('Open Project',self.open_project),('Save',self.save_project),('Save As',self.save_project_as),('Recent Projects',self.recent_projects),('Close Project',self.close_project),('Exit',self.close)]: a=self.project_menu.addAction(tx); a.triggered.connect(fn)
    def update_window_title(self):
        s=self.project_controller.current_project
        name=s.name if s else 'AI Audio Studio v0.3'; dirty=' *' if s and s.dirty else ''
        self.setWindowTitle(f'S Talking — {name}{dirty}')
    def slider(self,v): s=QSlider(Qt.Horizontal); s.setRange(0,100); s.setValue(v); return s
    def provider_changed(self,n):
        for w in [self.key,self.voice,self.model]: w.setEnabled(n=='elevenlabs')
        self.piper.setEnabled(n=='piper'); self.dashboard()
        if hasattr(self,'project_controller') and not self.settings_controller.is_loading: self.project_controller.update_provider(n); self.update_window_title()
    def pick_csv(self):
        p,_=QFileDialog.getOpenFileName(self,'CSV','','CSV (*.csv)')
        if p: self.csv.setText(p); self.project_controller.update_csv_path(Path(p)); self.update_window_title(); self.load_csv()
    def pick_out(self):
        p=QFileDialog.getExistingDirectory(self,'Output')
        if p: self.out.setText(p); self.project_controller.update_output_path(Path(p)); self.update_window_title()
    def pick_piper(self):
        p,_=QFileDialog.getOpenFileName(self,'Piper model','','ONNX (*.onnx)')
        if p: self.piper.setText(p)
    def load_csv(self):
        try:
            if self.project_controller.current_project: self.project_controller.update_csv_path(Path(self.csv.text())); self.update_window_title()
            self.generation_controller.set_jobs(load_jobs(Path(self.csv.text()))); self.table.setRowCount(len(self.generation_controller.jobs))
            for r,j in enumerate(self.generation_controller.jobs):
                for c,v in enumerate([j.row_number,j.filename,j.text,'pending','—','0',self.provider.currentText()]): self.table.setItem(r,c,QTableWidgetItem(str(v)))
                self.paint(r,'pending')
            self.log.appendPlainText(f'Loaded {len(self.generation_controller.jobs):,} rows.'); self.dashboard()
        except Exception as e: self.notifications.error('CSV error',str(e))
    def settings_values(self): return SettingsViewData(provider=self.provider.currentText(),api_key=self.key.text(),voice_id=self.voice.text(),model_id=self.model.text() or 'eleven_multilingual_v2',piper_model_path=self.piper.text() or None,stability=self.stability.value()/100,similarity_boost=self.similarity.value()/100,style=self.style.value()/100,speed=self.speed.value(),delay_seconds=self.delay.value(),max_retries=self.retries.value(),use_speaker_boost=self.boost.isChecked(),skip_existing=self.skip.isChecked())
    def settings(self): return self.settings_controller.from_view_data(self.settings_values())
    def settings_changed(self):
        s=self.settings()
        if self.settings_controller.settings_changed(s): self.project_controller.update_settings(s); self.update_window_title()
    def save_settings(self): self.settings_controller.save_global_settings(self.settings()); self.log.appendPlainText('Settings saved.')
    def load_saved(self):
        s=self.settings_controller.load_global_settings()
        if s:
            with self.settings_controller.loading():
                self.provider.setCurrentText(s.provider); self.key.setText(s.api_key); self.voice.setText(s.voice_id); self.model.setText(s.model_id); self.piper.setText(s.piper_model_path or ''); self.delay.setValue(s.delay_seconds); self.retries.setValue(s.max_retries)
    def apply_project_state(self,s):
        with self.settings_controller.loading():
            self.apply_project_paths(s); self.apply_provider_settings(s); self.apply_project_metadata(s)
        self.refresh_project_title(); self.show_path_warnings()
    def apply_project_paths(self,s):
        self.project_path=s.project_file; self.csv.setText(str(s.csv_path or '')); self.out.setText(str(s.output_path or self.project_controller.default_output_path))
    def apply_provider_settings(self,s):
        self.provider.setCurrentText(s.provider); self.key.setText(s.settings.api_key); self.voice.setText(s.settings.voice_id); self.model.setText(s.settings.model_id); self.piper.setText(s.settings.piper_model_path or '')
    def apply_project_metadata(self,s):
        self.project_path=s.project_file
    def refresh_project_title(self): self.update_window_title()
    def show_path_warnings(self):
        v=self.project_controller.validate_current_paths()
        if v.has_missing_paths: self.notifications.warning('Project paths','\n'.join(v.messages()))
    def new_project(self):
        d=NewProjectDialog(self)
        if d.exec()!=QDialog.Accepted: return
        name,csv_path,out_path=d.values(); s=self.project_controller.new_project(name,csv_path,out_path,self.settings()); self.apply_project_state(s); self.generation_controller.clear_jobs(); self.table.setRowCount(0); self.dashboard(); self.log.appendPlainText('New project.')
    def save_project(self):
        try:
            s=self.project_controller.save_project(self.settings(),self.csv.text(),self.out.text())
            if s is None: return self.save_project_as()
            self.apply_project_state(s); self.log.appendPlainText(f'Project saved: {s.project_file}')
        except Exception as e: self.notifications.error('Project error',str(e))
    def save_project_as(self):
        p,_=QFileDialog.getSaveFileName(self,'Save project','','S Talking project (*.stproj)')
        if not p: return
        try:
            s=self.project_controller.save_project_as(Path(p),Path(p).stem,self.settings(),self.csv.text(),self.out.text()); self.apply_project_state(s); self.log.appendPlainText(f'Project saved: {s.project_file}')
        except Exception as e: self.notifications.error('Project error',str(e))
    def open_project(self):
        s,_=QFileDialog.getOpenFileName(self,'Open project','','S Talking project (*.stproj)')
        if not s:return
        try:
            p=self.project_controller.open_project(Path(s)); self.apply_project_state(p)
            if p.csv_path and p.csv_path.exists(): self.load_csv()
        except Exception as e: self.notifications.error('Project error',str(e))
    def recent_projects(self):
        d=RecentProjectsDialog(self.project_controller.list_recent_projects(),self)
        if d.exec()==QDialog.Accepted and d.selected_project and d.selected_project.project_file:
            try: self.apply_project_state(self.project_controller.open_project(Path(d.selected_project.project_file)))
            except Exception as e: self.notifications.error('Project error',str(e))
        elif d.removed_project_id: self.project_controller.remove_recent_project(d.removed_project_id)
    def close_project(self):
        self.project_controller.close_project(); self.project_path=None; self.csv.clear(); self.generation_controller.clear_jobs(); self.table.setRowCount(0); self.dashboard(); self.update_window_title(); self.log.appendPlainText('Project closed.')
    def autosave(self):
        try:
            if self.project_controller.autosave_if_needed(generation_active=self.generation_controller.is_active): self.log.appendPlainText('Project auto-saved.'); self.update_window_title()
        except Exception as e: self.log.appendPlainText(f'Auto-save failed: {e}')
    def start(self):
        if not self.generation_controller.has_jobs():self.load_csv()
        if not self.generation_controller.has_jobs():return
        s=self.settings(); project=self.project_controller.generation_context(self.out.text())
        if s.provider=='elevenlabs' and not self.notifications.confirmation('Plan warning','Selected voice may require a paid plan. Continue?'):return
        if self.generation_controller.start(self,s,project.output_path,project.project_key): self.startb.setEnabled(False)
    def pause(self):
        if not self.generation_controller.is_paused:
            if self.generation_controller.pause(): self.pauseb.setText('Resume')
        else:
            if self.generation_controller.resume(): self.pauseb.setText('Pause')
    def stop(self):
        self.generation_controller.stop()
    def progress(self,i,total,name,status,duration,retry,error):
        self.bar.setMaximum(total); self.bar.setValue(i); r=i-1
        if 0<=r<self.table.rowCount(): self.table.setItem(r,3,QTableWidgetItem(status)); self.table.setItem(r,4,QTableWidgetItem(f'{duration:.2f}s' if duration else '—')); self.table.setItem(r,5,QTableWidgetItem(str(retry))); self.paint(r,status)
        self.log.appendPlainText(f'[{i}/{total}] {status}: {name}'+(f' — {error}' if error else '')); self.dashboard()
    def finished(self,s): self.startb.setEnabled(True); self.pauseb.setText('Pause'); self.notifications.information('Finished',json.dumps(s,indent=2))
    def failed(self,e): self.startb.setEnabled(True); self.notifications.error('Error',e)
    def paint(self,r,status):
        it=self.table.item(r,3)
        if it: it.setForeground(QColor(COLORS.get(status,'#E5E7EB')))
    def preview(self):
        rows=self.table.selectionModel().selectedRows()
        if rows:
            j=self.generation_controller.jobs[rows[0].row()]; self.pname.setText(j.filename); self.pmeta.setText(f'Row {j.row_number} • {len(j.text):,} characters • {self.provider.currentText()}'); self.ptext.setPlainText(j.text)
    def dashboard(self):
        files=len(self.generation_controller.jobs); chars=sum(len(j.text) for j in self.generation_controller.jobs); done=failed=0
        for r in range(self.table.rowCount()):
            it=self.table.item(r,3); st=it.text() if it else 'pending'; done+=st=='completed'; failed+=st=='failed'
        eta=max(0,files-done)*(self.delay.value()+.35)/60 if files else 0
        self.cards['files'].value.setText(f'{files:,}'); self.cards['chars'].value.setText(f'{chars:,}'); self.cards['done'].value.setText(f'{done:,}'); self.cards['failed'].value.setText(f'{failed:,}'); self.cards['eta'].value.setText(f'{eta:.1f} min')
    def theme(self): self.setStyleSheet('''QWidget{background:#0B1220;color:#E5E7EB;font-size:13px;font-family:Segoe UI} QGroupBox{border:1px solid #263244;border-radius:9px;margin-top:12px;padding-top:12px;font-weight:600} QLineEdit,QComboBox,QSpinBox,QDoubleSpinBox,QPlainTextEdit,QTableWidget{background:#111827;border:1px solid #334155;border-radius:6px;padding:6px} QPushButton{background:#2563EB;border:0;border-radius:7px;padding:9px 14px;font-weight:600} QPushButton:hover{background:#1D4ED8} #title{font-size:31px;font-weight:800;color:#D1A23A} #subtitle{color:#94A3B8} #card{background:#111827;border:1px solid #263244;border-radius:10px} #cardValue{font-size:22px;font-weight:700} #cardCaption{color:#94A3B8} #previewTitle{font-size:17px;font-weight:700;color:#D1A23A} QHeaderView::section{background:#172033;color:#CBD5E1;border:0;padding:7px} QProgressBar::chunk{background:#14B8A6}''')

def main():
    app=QApplication(sys.argv); win=MainWindow(create_application_context()); win.show(); sys.exit(app.exec())
if __name__=='__main__':main()
