from __future__ import annotations
import json,sys
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import Qt,QTimer,QUrl
from PySide6.QtGui import QAction,QColor,QDesktopServices,QKeySequence
from PySide6.QtWidgets import *
from app.bootstrap import ApplicationContext, create_application_context
from app.csv_loader import load_jobs
from app.gui.command_palette import CommandPalette, PaletteCommand
from app.gui.developer_tools import DeveloperTools
from app.gui.dialogs import NewProjectDialog,RecentProjectsDialog,ReportDialog
from app.gui.widgets import ControlledDoubleSpinBox, ControlledSpinBox
from app.models.ui_state import SettingsViewData

COLORS={'pending':'#9CA3AF','running':'#F59E0B','completed':'#22C55E','skipped':'#60A5FA','failed':'#EF4444'}

class Card(QFrame):
    def __init__(self,title):
        super().__init__(); self.setObjectName('card'); lay=QVBoxLayout(self); self.value=QLabel('0'); self.value.setObjectName('cardValue'); cap=QLabel(title); cap.setObjectName('cardCaption'); lay.addWidget(self.value); lay.addWidget(cap)

class MainWindow(QMainWindow):
    def __init__(self, context: ApplicationContext):
        super().__init__(); self.setWindowTitle('S Talking — AI Audio Studio v0.3'); self.resize(1420,860)
        self.context=context; self.project_controller=context.project_controller; self.generation_controller=context.generation_controller; self.settings_controller=context.settings_controller; self.notifications=context.notification_service
        self.statistics_service=context.statistics_service; self.report_service=context.report_service; self.developer_tools=DeveloperTools(self,context)
        self.notifications.parent=self
        self.project_path=None; self.generation_started_at=None; self.run_logs=[]; self.report_dialogs=[]; self.palette=None; self.actions_by_name={}
        self.autosave_timer=QTimer(self); self.autosave_timer.setInterval(30000); self.autosave_timer.timeout.connect(self.autosave); self.autosave_timer.start()
        self.build(); self.load_saved(); self.theme(); self.update_window_title(); self.update_status_bar()
    def build(self):
        self.build_project_menu(); self.build_reports_menu(); self.build_developer_tools_menu(); self.statusBar()
        palette_action=QAction('Command Palette',self); palette_action.setShortcut(QKeySequence('Ctrl+Shift+P')); palette_action.setShortcutContext(Qt.ApplicationShortcut); palette_action.triggered.connect(self.open_command_palette); self.addAction(palette_action); self.actions_by_name['Command Palette']=palette_action
        c=QWidget(); self.setCentralWidget(c); root=QVBoxLayout(c)
        head=QHBoxLayout(); brand=QVBoxLayout(); t=QLabel('S Talking'); t.setObjectName('title'); st=QLabel('Professional AI Audio Studio'); st.setObjectName('subtitle'); brand.addWidget(t); brand.addWidget(st); head.addLayout(brand); head.addStretch()
        for tx,fn in [('New',self.new_project),('Open project',self.open_project),('Save project',self.save_project)]: b=QPushButton(tx); b.clicked.connect(fn); head.addWidget(b)
        root.addLayout(head)
        cards=QHBoxLayout(); self.cards={}
        for k,tx in [('files','Files'),('chars','Characters'),('done','Completed'),('failed','Failed'),('eta','Estimated time')]: card=Card(tx); self.cards[k]=card; cards.addWidget(card)
        root.addLayout(cards)
        box=QGroupBox('Project sources'); g=QGridLayout(box); self.csv=QLineEdit(); self.out=QLineEdit(str(self.project_controller.default_output_path)); bc=QPushButton('Browse CSV'); bo=QPushButton('Output folder'); self.reloadb=QPushButton('Reload CSV'); self.reloadb.setEnabled(False); bc.clicked.connect(self.pick_csv); bo.clicked.connect(self.pick_out); self.reloadb.clicked.connect(self.reload_csv); self.csv.textChanged.connect(lambda _text:self.update_reload_state()); g.addWidget(QLabel('CSV file'),0,0); g.addWidget(self.csv,0,1); g.addWidget(bc,0,2); g.addWidget(self.reloadb,0,3); g.addWidget(QLabel('Output'),1,0); g.addWidget(self.out,1,1); g.addWidget(bo,1,2,1,2); root.addWidget(box)
        split=QSplitter(Qt.Horizontal); root.addWidget(split,1)
        sb=QGroupBox('Provider settings'); form=QFormLayout(sb); self.provider=QComboBox(); self.provider.addItems(['mock','piper','elevenlabs']); self.key=QLineEdit(); self.key.setEchoMode(QLineEdit.Password); self.voice=QLineEdit(); self.model=QLineEdit('eleven_multilingual_v2'); self.piper=QLineEdit(); pbtn=QPushButton('Browse'); pbtn.clicked.connect(self.pick_piper); prow=QWidget(); pl=QHBoxLayout(prow); pl.setContentsMargins(0,0,0,0); pl.addWidget(self.piper); pl.addWidget(pbtn)
        self.stability=self.slider(45); self.similarity=self.slider(75); self.style=self.slider(20); self.speed=ControlledDoubleSpinBox(); self.speed.setRange(.7,1.2); self.speed.setDecimals(2); self.speed.setSingleStep(.05); self.speed.setSuffix('×'); self.speed.setValue(1); self.speed.setToolTip('Type a value, use arrow buttons, or focus before using the mouse wheel.'); self.delay=ControlledDoubleSpinBox(); self.delay.setRange(0,60); self.delay.setDecimals(1); self.delay.setSingleStep(.1); self.delay.setSuffix(' s'); self.delay.setValue(.5); self.delay.setToolTip('Type seconds, use arrow buttons in 0.1 s steps, or focus before using the mouse wheel.'); self.retries=ControlledSpinBox(); self.retries.setRange(0,10); self.retries.setSingleStep(1); self.retries.setValue(4); self.retries.setToolTip('Type retries, use arrow buttons in steps of 1, or focus before using the mouse wheel.'); self.boost=QCheckBox(); self.boost.setChecked(True); self.skip=QCheckBox(); self.skip.setChecked(True)
        for a,b in [('Provider',self.provider),('API key',self.key),('Voice ID',self.voice),('Model ID',self.model),('Piper model',prow),('Stability',self.stability),('Similarity',self.similarity),('Style',self.style),('Speed',self.speed),('Delay',self.delay),('Retries',self.retries),('Speaker boost',self.boost),('Skip existing',self.skip)]: form.addRow(a,b)
        split.addWidget(sb)
        mid=QWidget(); ml=QVBoxLayout(mid); self.table=QTableWidget(0,7); self.table.setHorizontalHeaderLabels(['#','Filename','Text','Status','Time','Retry','Provider']); self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch); self.table.itemSelectionChanged.connect(self.preview); ml.addWidget(self.table); split.addWidget(mid)
        pb=QGroupBox('Selected row'); pv=QVBoxLayout(pb); self.pname=QLabel('No row selected'); self.pname.setObjectName('previewTitle'); self.pmeta=QLabel(''); self.ptext=QPlainTextEdit(); self.ptext.setReadOnly(True); pv.addWidget(self.pname); pv.addWidget(self.pmeta); pv.addWidget(self.ptext); split.addWidget(pb); split.setSizes([330,760,330])
        lower=QSplitter(Qt.Vertical); self.log=QPlainTextEdit(); self.log.setReadOnly(True); lower.addWidget(self.log); self.bar=QProgressBar(); lower.addWidget(self.bar); lower.setSizes([130,28]); root.addWidget(lower)
        ctr=QHBoxLayout(); self.startb=QPushButton('Start'); self.pauseb=QPushButton('Pause'); self.stopb=QPushButton('Stop'); saveb=QPushButton('Save as global defaults'); self.startb.clicked.connect(self.start); self.pauseb.clicked.connect(self.pause); self.stopb.clicked.connect(self.stop); saveb.clicked.connect(self.save_settings); ctr.addWidget(self.startb); ctr.addWidget(self.pauseb); ctr.addWidget(self.stopb); ctr.addStretch(); ctr.addWidget(saveb); root.addLayout(ctr)
        self.generation_controller.progress.connect(self.progress); self.generation_controller.log.connect(self.log.appendPlainText); self.generation_controller.finished.connect(self.finished); self.generation_controller.failed.connect(self.failed)
        self.provider.currentTextChanged.connect(self.provider_changed); self.provider_changed('mock')
        for w in [self.stability,self.similarity,self.style,self.speed,self.delay,self.retries,self.boost,self.skip]: w.valueChanged.connect(self.settings_changed) if hasattr(w,'valueChanged') else w.toggled.connect(self.settings_changed)
    def build_project_menu(self):
        self.project_menu=QMenu('Project',self); self.menuBar().addMenu(self.project_menu)
        for tx,fn in [('New Project',self.new_project),('Open Project',self.open_project),('Save',self.save_project),('Save As',self.save_project_as),('Recent Projects',self.recent_projects),('Close Project',self.close_project),('Exit',self.close)]: a=self.project_menu.addAction(tx); a.triggered.connect(fn); self.actions_by_name[tx]=a
        self.actions_by_name['Save Project']=self.actions_by_name['Save']; self.actions_by_name['Save Project As']=self.actions_by_name['Save As']
    def build_reports_menu(self):
        self.reports_menu=QMenu('Reports',self); self.menuBar().addMenu(self.reports_menu)
        for tx,fn in [('Open Latest Report',self.open_latest_report),('Open Reports Folder',self.open_reports_folder),('Export Diagnostics',self.export_diagnostics),('Copy Report Path',self.copy_report_path)]: a=self.reports_menu.addAction(tx); a.triggered.connect(fn); self.actions_by_name[tx]=a
    def build_developer_tools_menu(self):
        self.developer_menu=QMenu('Developer Tools',self); self.menuBar().addMenu(self.developer_menu); self.actions_by_name.update(self.developer_tools.populate_menu(self.developer_menu))
    def update_window_title(self):
        s=self.project_controller.current_project
        name=s.name if s else 'AI Audio Studio v0.3'; dirty=' *' if s and s.dirty else ''
        self.setWindowTitle(f'S Talking — {name}{dirty}')
    def update_reload_state(self): self.reloadb.setEnabled(bool(self.csv.text().strip()))
    def update_status_bar(self):
        project=self.project_controller.project_name; provider=self.provider.currentText() if hasattr(self,'provider') else 'mock'; queue=f'{len(self.generation_controller.jobs)} jobs'; report=self.report_service.latest_report_dir(); report_text=str(report) if report else 'No report yet'; self.statusBar().showMessage(f'Project: {project} | Provider: {provider} | Queue: {queue} | Latest report: {report_text}')
    def slider(self,v): s=QSlider(Qt.Horizontal); s.setRange(0,100); s.setValue(v); return s
    def provider_changed(self,n):
        for w in [self.key,self.voice,self.model]: w.setEnabled(n=='elevenlabs')
        self.piper.setEnabled(n=='piper'); self.dashboard(); self.update_status_bar()
        if hasattr(self,'project_controller') and not self.settings_controller.is_loading: self.project_controller.update_provider(n); self.update_window_title()
    def pick_csv(self):
        p,_=QFileDialog.getOpenFileName(self,'CSV',str(self.project_controller.last_csv_dir),'CSV (*.csv)')
        if p: self.csv.setText(p); self.project_controller.update_csv_path(Path(p)); self.update_window_title(); self.load_csv(); self.update_status_bar()
    def pick_out(self):
        p=QFileDialog.getExistingDirectory(self,'Output',str(self.project_controller.last_output_dir))
        if p: self.out.setText(p); self.project_controller.update_output_path(Path(p)); self.update_window_title(); self.update_status_bar()
    def pick_piper(self):
        p,_=QFileDialog.getOpenFileName(self,'Piper model','','ONNX (*.onnx)')
        if p: self.piper.setText(p)
    def reload_csv(self): self.load_csv(update_project=True, source='Reloaded')
    def load_csv(self,update_project=True,source='Loaded'):
        try:
            if update_project and self.project_controller.current_project: self.project_controller.update_csv_path(Path(self.csv.text())); self.update_window_title()
            self.generation_controller.set_jobs(load_jobs(Path(self.csv.text()))); self.table.setRowCount(len(self.generation_controller.jobs))
            for r,j in enumerate(self.generation_controller.jobs):
                for c,v in enumerate([j.row_number,j.filename,j.text,'pending','—','0',self.provider.currentText()]): self.table.setItem(r,c,QTableWidgetItem(str(v)))
                self.paint(r,'pending')
            self.log.appendPlainText(f'{source} {len(self.generation_controller.jobs):,} CSV rows.'); self.dashboard(); self.update_status_bar()
        except Exception as e: self.log.appendPlainText(f'CSV load failed: {e}'); self.dashboard(); self.update_status_bar()
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
                self.provider.setCurrentText(s.provider); self.key.setText(s.api_key); self.voice.setText(s.voice_id); self.model.setText(s.model_id); self.piper.setText(s.piper_model_path or ''); self.stability.setValue(int(s.stability*100)); self.similarity.setValue(int(s.similarity_boost*100)); self.style.setValue(int(s.style*100)); self.speed.setValue(s.speed); self.delay.setValue(s.delay_seconds); self.retries.setValue(s.max_retries); self.boost.setChecked(s.use_speaker_boost); self.skip.setChecked(s.skip_existing)
    def apply_project_state(self,s):
        with self.settings_controller.loading():
            self.apply_project_paths(s); self.apply_provider_settings(s); self.apply_project_metadata(s)
        self.refresh_project_title(); self.show_path_warnings(); self.update_reload_state(); self.dashboard(); self.update_status_bar()
    def apply_project_paths(self,s):
        self.project_path=s.project_file; self.csv.setText(str(s.csv_path or '')); self.out.setText(str(s.output_path or self.project_controller.default_output_path))
    def apply_provider_settings(self,s):
        self.provider.setCurrentText(s.provider); self.key.setText(s.settings.api_key); self.voice.setText(s.settings.voice_id); self.model.setText(s.settings.model_id); self.piper.setText(s.settings.piper_model_path or ''); self.stability.setValue(int(s.settings.stability*100)); self.similarity.setValue(int(s.settings.similarity_boost*100)); self.style.setValue(int(s.settings.style*100)); self.speed.setValue(s.settings.speed); self.delay.setValue(s.settings.delay_seconds); self.retries.setValue(s.settings.max_retries); self.boost.setChecked(s.settings.use_speaker_boost); self.skip.setChecked(s.settings.skip_existing)
    def apply_project_metadata(self,s):
        self.project_path=s.project_file
    def refresh_project_title(self): self.update_window_title()
    def show_path_warnings(self):
        v=self.project_controller.validate_current_paths()
        if v.has_missing_paths: self.notifications.warning('Project paths','\n'.join(v.messages()))
    def new_project(self):
        d=NewProjectDialog(self,self.project_controller.last_csv_dir,self.project_controller.last_output_dir)
        if d.exec()!=QDialog.Accepted: return
        name,csv_path,out_path=d.values(); s=self.project_controller.new_project(name,csv_path,out_path,self.settings()); self.apply_project_state(s); self.generation_controller.clear_jobs(); self.table.setRowCount(0); self.dashboard(); self.log.appendPlainText('New project.')
        if csv_path and csv_path.exists(): self.load_csv(update_project=False)
        self.dashboard(); self.update_status_bar()
    def save_project(self):
        try:
            s=self.project_controller.save_project(self.settings(),self.csv.text(),self.out.text())
            if s is None: return self.save_project_as()
            self.apply_project_state(s); self.log.appendPlainText(f'Project saved: {s.project_file}'); self.update_status_bar()
        except Exception as e: self.notifications.error('Project error',str(e))
    def save_project_as(self):
        p,_=QFileDialog.getSaveFileName(self,'Save project',str(self.project_controller.suggested_save_as_path()),'S Talking project (*.stproj)')
        if not p: return
        try:
            s=self.project_controller.save_project_as(Path(p),Path(p).stem,self.settings(),self.csv.text(),self.out.text()); self.apply_project_state(s); self.log.appendPlainText(f'Project saved: {s.project_file}'); self.update_status_bar()
        except Exception as e: self.notifications.error('Project error',str(e))
    def open_project(self):
        s,_=QFileDialog.getOpenFileName(self,'Open project','','S Talking project (*.stproj)')
        if not s:return
        try:
            p=self.project_controller.open_project(Path(s)); self.apply_project_state(p)
            if p.csv_path and p.csv_path.exists(): self.load_csv(update_project=False)
            self.dashboard(); self.update_status_bar()
        except Exception as e: self.notifications.error('Project error',str(e))
    def recent_projects(self):
        d=RecentProjectsDialog(self.project_controller.list_recent_projects(),self)
        if d.exec()==QDialog.Accepted and d.selected_project and d.selected_project.project_file:
            try: self.apply_project_state(self.project_controller.open_project(Path(d.selected_project.project_file)))
            except Exception as e: self.notifications.error('Project error',str(e))
        elif d.removed_project_id: self.project_controller.remove_recent_project(d.removed_project_id)
    def close_project(self):
        self.project_controller.close_project(); self.project_path=None; self.csv.clear(); self.generation_controller.clear_jobs(); self.table.setRowCount(0); self.dashboard(); self.update_window_title(); self.log.appendPlainText('Project closed.'); self.update_status_bar()
    def autosave(self):
        try:
            if self.project_controller.autosave_if_needed(generation_active=self.generation_controller.is_active): self.log.appendPlainText('Project auto-saved.'); self.update_window_title(); self.update_status_bar()
        except Exception as e: self.log.appendPlainText(f'Auto-save failed: {e}')
    def start(self):
        if not self.generation_controller.has_jobs():self.load_csv()
        if not self.generation_controller.has_jobs():return
        s=self.settings(); project=self.project_controller.generation_context(self.out.text())
        if s.provider=='elevenlabs' and not self.notifications.confirmation('Plan warning','Selected voice may require a paid plan. Continue?'):return
        self.generation_started_at=datetime.now(timezone.utc); self.run_logs=[]; self.dashboard()
        if self.generation_controller.start(self,s,project.output_path,project.project_key): self.startb.setEnabled(False); self.update_status_bar()
    def pause(self):
        if not self.generation_controller.is_paused:
            if self.generation_controller.pause(): self.pauseb.setText('Resume')
        else:
            if self.generation_controller.resume(): self.pauseb.setText('Pause')
    def stop(self):
        self.generation_controller.stop()
    def resume_generation(self):
        if self.generation_controller.is_paused: self.pause()
    def open_output_folder(self): self.context.desktop_service.open_path(Path(self.out.text() or self.project_controller.default_output_path))
    def retry_failed(self): self.log.appendPlainText('Retry Failed is not available in this workflow yet.')
    def progress(self,i,total,name,status,duration,retry,error):
        self.bar.setMaximum(total); self.bar.setValue(i); r=i-1
        if 0<=r<self.table.rowCount(): self.table.setItem(r,3,QTableWidgetItem(status)); self.table.setItem(r,4,QTableWidgetItem(f'{duration:.2f}s' if duration else '—')); self.table.setItem(r,5,QTableWidgetItem(str(retry))); self.paint(r,status)
        line=f'[{i}/{total}] {status}: {name}'+(f' — {error}' if error else ''); self.run_logs.append(line); self.log.appendPlainText(line); self.dashboard(); self.update_status_bar()
    def finished(self,s):
        self.startb.setEnabled(True); self.pauseb.setText('Pause'); self.dashboard(); self.log.appendPlainText(f'Finished: {json.dumps(s,indent=2)}')
        report=self.create_report(s); self.show_report_dialog(report); self.update_status_bar()
    def failed(self,e):
        self.startb.setEnabled(True); self.dashboard(); self.run_logs.append(f'FAILED: {e}'); report=self.create_report({'total':len(self.generation_controller.jobs),'completed':0,'skipped':0,'failed':1,'stopped':True,'error':e}); self.show_report_dialog(report); self.notifications.error('Error',e); self.update_status_bar()
    def closeEvent(self,event):
        for dialog in list(self.report_dialogs): dialog.close()
        self.developer_tools.close()
        close_summaries=getattr(self.notifications,'close_summaries',None)
        if callable(close_summaries): close_summaries()
        super().closeEvent(event)
    def keyPressEvent(self,event):
        if event.key()==Qt.Key_P and event.modifiers() & Qt.ControlModifier and event.modifiers() & Qt.ShiftModifier: self.open_command_palette(); return
        super().keyPressEvent(event)
    def paint(self,r,status):
        it=self.table.item(r,3)
        if it: it.setForeground(QColor(COLORS.get(status,'#E5E7EB')))
    def preview(self):
        rows=self.table.selectionModel().selectedRows()
        if rows:
            j=self.generation_controller.jobs[rows[0].row()]; self.pname.setText(j.filename); self.pmeta.setText(f'Row {j.row_number} • {len(j.text):,} characters • {self.provider.currentText()}'); self.ptext.setPlainText(j.text)
        else:
            self.pname.setText('No row selected'); self.pmeta.setText('Load a CSV and select a row to inspect it.'); self.ptext.setPlainText('The selected row preview will appear here after a CSV is loaded.')
    def dashboard(self):
        state=self.statistics_service.dashboard_for_jobs(self.generation_controller.jobs,project_key=self.project_controller.current_project.project_key if self.project_controller.current_project else None)
        self.cards['files'].value.setText(f'{state.total_files:,}'); self.cards['chars'].value.setText(f'{state.total_characters:,}'); self.cards['done'].value.setText(f'{state.completed:,}'); self.cards['failed'].value.setText(f'{state.failed:,}'); self.cards['eta'].value.setText(f'{state.estimated_minutes:.1f} min')
    def create_report(self,summary):
        return self.report_service.create_generation_report(project=self.project_controller.current_project,settings=self.settings(),jobs=list(self.generation_controller.jobs),output_dir=Path(self.out.text() or self.project_controller.default_output_path),summary=summary,started_at=self.generation_started_at or datetime.now(timezone.utc),log_events=self.run_logs)
    def show_report_dialog(self,report):
        d=ReportDialog(report,self,open_report=self.open_path,open_folder=self.open_path,copy_path=self.copy_path,export_diagnostics=self.export_diagnostics_for); self.report_dialogs.append(d); d.destroyed.connect(lambda *_: self.report_dialogs.remove(d) if d in self.report_dialogs else None); d.show()
    def open_path(self,path): QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))
    def open_latest_report(self):
        path=self.report_service.latest_report_dir()
        if path: self.open_path(path/'report.html')
    def open_reports_folder(self): self.open_path(self.context.container.runtime.reports_dir)
    def copy_path(self,path): QApplication.clipboard().setText(str(path)); self.statusBar().showMessage(f'Copied: {path}')
    def copy_report_path(self):
        path=self.report_service.latest_report_dir()
        if path: self.copy_path(path)
    def export_diagnostics_for(self,report_dir): bundle=self.context.diagnostics_service.export_bundle(project=self.project_controller.current_project,dashboard=self.current_dashboard_state(),queue_state={'active':self.generation_controller.is_active,'paused':self.generation_controller.is_paused}); self.open_path(bundle.parent); self.copy_path(bundle)
    def export_diagnostics(self): self.export_diagnostics_for(self.report_service.latest_report_dir())
    def current_dashboard_state(self): return self.statistics_service.dashboard_for_jobs(self.generation_controller.jobs,project_key=self.project_controller.current_project.project_key if self.project_controller.current_project else None)
    def command_palette_commands(self):
        def act(name): return lambda: self.actions_by_name[name].trigger()
        return [
            PaletteCommand('Project: New Project',act('New Project')),
            PaletteCommand('Project: Open Project',act('Open Project')),
            PaletteCommand('Project: Save Project',act('Save Project'),lambda: self.project_controller.current_project is not None),
            PaletteCommand('Project: Save Project As',act('Save Project As'),lambda: self.project_controller.current_project is not None),
            PaletteCommand('Project: Close Project',act('Close Project'),lambda: self.project_controller.current_project is not None),
            PaletteCommand('Generation: Start Generation',self.start,lambda: bool(self.csv.text().strip()) or self.generation_controller.has_jobs()),
            PaletteCommand('Generation: Pause Generation',self.pause,lambda: self.generation_controller.is_active and not self.generation_controller.is_paused),
            PaletteCommand('Generation: Resume Generation',self.resume_generation,lambda: self.generation_controller.is_active and self.generation_controller.is_paused),
            PaletteCommand('Generation: Stop Generation',self.stop,lambda: self.generation_controller.is_active),
            PaletteCommand('Generation: Retry Failed',self.retry_failed,lambda: False),
            PaletteCommand('Generation: Open Output Folder',self.open_output_folder,lambda: Path(self.out.text() or self.project_controller.default_output_path).exists()),
            PaletteCommand('Reports: Open Latest Report',act('Open Latest Report'),lambda: self.report_service.latest_report_dir() is not None),
            PaletteCommand('Reports: Open Reports Folder',act('Open Reports Folder')),
            PaletteCommand('Reports: Export Diagnostics',act('Export Diagnostics')),
            PaletteCommand('Developer: Run All Checks',act('Run all checks')),
            PaletteCommand('Developer: Open Latest Check',lambda: self.context.desktop_service.open_path(self.context.container.runtime.artifacts_dir/'dev-check'/'latest'),lambda: (self.context.container.runtime.artifacts_dir/'dev-check'/'latest').exists()),
            PaletteCommand('Developer: Open Logs',act('Open logs folder')),
            PaletteCommand('Developer: Open Repository',act('Open repository folder')),
            PaletteCommand('Developer: Open in VS Code',act('Open repository in VS Code')),
            PaletteCommand('Developer: Show Runtime Information',act('Show runtime information')),
            PaletteCommand('Developer: Spinbox Visual Test',act('Spinbox visual test')),
        ]
    def open_command_palette(self):
        self.palette=CommandPalette(self.command_palette_commands(),self); self.palette.show(); self.palette.search.setFocus()
    def theme(self): self.setStyleSheet('''QWidget{background:#0B1220;color:#E5E7EB;font-size:13px;font-family:Segoe UI} QGroupBox{border:1px solid #263244;border-radius:9px;margin-top:12px;padding-top:12px;font-weight:600} QLineEdit,QComboBox,QPlainTextEdit,QTableWidget{background:#111827;border:1px solid #334155;border-radius:6px;padding:6px} QAbstractSpinBox{background:#111827;border:1px solid #334155;border-radius:6px;padding:6px 30px 6px 6px;selection-background-color:#2563EB} QAbstractSpinBox:disabled{color:#64748B;background:#0F172A;border-color:#1F2937} QAbstractSpinBox::up-button{subcontrol-origin:border;subcontrol-position:top right;width:24px;border-left:1px solid #334155;border-bottom:1px solid #334155;border-top-right-radius:6px;background:#1F2937} QAbstractSpinBox::down-button{subcontrol-origin:border;subcontrol-position:bottom right;width:24px;border-left:1px solid #334155;border-bottom-right-radius:6px;background:#1F2937} QAbstractSpinBox::up-button:hover,QAbstractSpinBox::down-button:hover{background:#2563EB} QAbstractSpinBox::up-button:pressed,QAbstractSpinBox::down-button:pressed{background:#1D4ED8} QAbstractSpinBox::up-button:disabled,QAbstractSpinBox::down-button:disabled{background:#0F172A;border-color:#1F2937} QAbstractSpinBox::up-arrow,QAbstractSpinBox::down-arrow{width:8px;height:8px} QPushButton{background:#2563EB;border:0;border-radius:7px;padding:9px 14px;font-weight:600} QPushButton:hover{background:#1D4ED8} #title{font-size:31px;font-weight:800;color:#D1A23A} #subtitle{color:#94A3B8} #card{background:#111827;border:1px solid #263244;border-radius:10px} #cardValue{font-size:22px;font-weight:700} #cardCaption{color:#94A3B8} #previewTitle{font-size:17px;font-weight:700;color:#D1A23A} QHeaderView::section{background:#172033;color:#CBD5E1;border:0;padding:7px} QProgressBar::chunk{background:#14B8A6}''')

def main():
    app=QApplication(sys.argv); win=MainWindow(create_application_context()); win.show(); sys.exit(app.exec())
if __name__=='__main__':main()
