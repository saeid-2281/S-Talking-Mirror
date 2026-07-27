from __future__ import annotations
import json,sys

import app
from datetime import datetime, timezone
from pathlib import Path
from PySide6.QtCore import QItemSelectionModel,QSettings,Qt,QTimer,QUrl,QSize,Signal
from PySide6.QtGui import QAction,QColor,QDesktopServices,QDragEnterEvent,QDropEvent,QKeySequence
from PySide6.QtWidgets import *
from app.bootstrap import ApplicationContext, create_application_context
from app.csv_loader import diagnose_csv, generate_repaired_preview, load_jobs, write_import_report
from app.gui.command_palette import CommandPalette, PaletteCommand
from app.gui.connection_test_runner import start_connection_test
from app.gui.developer_tools import DeveloperTools
from app.gui.icons import action_icon, icon
from app.gui.theme import STATUS_COLORS, ThemeManager
from app.gui.voice_browser import VoiceBrowserDialog
from app.gui.dialogs import AboutDialog,CsvImportReviewDialog,NewProjectDialog,PreflightDialog,PreflightFixDialog,ProviderAccountsDialog,PronunciationDictionaryDialog,QuickSetupDialog,RecentProjectsDialog,ReportDialog,SourceImportReviewDialog
from app.gui.widgets import ControlledSpinBox
from app.gui.widgets.provider_workspace import ProviderWorkspaceBuilder
from app.models import AppSettings
from app.models.product_events import BatchSessionRecord
from app.models.ui_state import SettingsViewData
from app.services.monitor_formatting import elide_middle, format_characters_per_minute, format_duration, format_files_per_minute, status_color

COLORS=STATUS_COLORS
MONITOR_MIN_WIDTH=290
MONITOR_DEFAULT_WIDTH=330
MONITOR_MAX_FRACTION=0.32
MONITOR_COMPACT_THRESHOLD=1180

class Card(QFrame):
    def __init__(self,title):
        super().__init__(); self.setObjectName('card'); lay=QVBoxLayout(self); self.value=QLabel('0'); self.value.setObjectName('cardValue'); cap=QLabel(title); cap.setObjectName('cardCaption'); lay.addWidget(self.value); lay.addWidget(cap)

class MetricPill(QFrame):
    clicked=Signal(str)
    def __init__(self,title):
        super().__init__(); self.metric_key=''; self.filter_text=''; self.setObjectName('metricPill'); self.setCursor(Qt.PointingHandCursor); self.setMaximumHeight(42); self.setMinimumHeight(34); self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
        lay=QHBoxLayout(self); lay.setContentsMargins(7,2,7,2); lay.setSpacing(4)
        self.icon_label=QLabel(''); self.icon_label.setObjectName('metricIcon'); self.icon_label.setAlignment(Qt.AlignCenter); self.icon_label.setFixedWidth(18)
        self.value=QLabel('0'); self.value.setObjectName('metricValue'); self.value.setAlignment(Qt.AlignRight|Qt.AlignVCenter); self.value.setMinimumWidth(0); self.value.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        cap=QLabel(title); cap.setObjectName('metricCaption'); cap.setSizePolicy(QSizePolicy.Minimum,QSizePolicy.Preferred)
        lay.addWidget(self.icon_label); lay.addWidget(self.value,1); lay.addWidget(cap)
    def configure(self,key,filter_text='',icon_name='general.info'):
        self.metric_key=key; self.filter_text=filter_text; self.icon_label.setPixmap(action_icon(icon_name,size=16).pixmap(16,16)); self.setToolTip(f'Filter queue by {filter_text.lower()}' if filter_text else 'Queue metric')
    def set_active(self,active):
        self.setProperty('active',active); self.style().unpolish(self); self.style().polish(self)
    def mousePressEvent(self,event):
        if event.button()==Qt.LeftButton and self.filter_text:
            self.clicked.emit(self.filter_text); event.accept(); return
        super().mousePressEvent(event)

class LegacyCollapsibleSection(QFrame):
    """Compact section whose fields stack vertically instead of fighting for width."""
    def __init__(self,title,summary='',expanded=True):
        super().__init__(); self.setObjectName('collapsibleSection'); self.summary=summary
        root=QVBoxLayout(self); root.setContentsMargins(0,0,0,0); root.setSpacing(4)
        self.header=QToolButton(); self.header.setObjectName('sectionHeader'); self.header.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); self.header.setCheckable(True); self.header.setChecked(expanded); self.header.setText(title); self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow); self.header.clicked.connect(self.set_expanded)
        self.content=QWidget(); self.content.setObjectName('sectionContent')
        self.form=QVBoxLayout(self.content); self.form.setContentsMargins(10,4,10,10); self.form.setSpacing(8)
        root.addWidget(self.header); root.addWidget(self.content); self.set_expanded(expanded)
    def set_expanded(self,expanded):
        self.header.setChecked(expanded); self.header.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow); self.content.setVisible(expanded)
        base=self.header.text().split(' · ')[0]
        if not expanded and self.summary: self.header.setText(f'{base} · {self.summary}')
        else: self.header.setText(base)
    def addRow(self,label,widget):
        row=QFrame(); row.setObjectName('providerFieldRow')
        layout=QVBoxLayout(row); layout.setContentsMargins(0,0,0,0); layout.setSpacing(4)
        if label:
            lab=QLabel(label); lab.setObjectName('formLabel'); lab.setSizePolicy(QSizePolicy.Preferred,QSizePolicy.Fixed)
            layout.addWidget(lab)
        # Preserve the practical minimum width configured by the owning panel.
        # Resetting it here made provider/model/language controls collapse to 0 px.
        widget.setSizePolicy(QSizePolicy.Expanding,widget.sizePolicy().verticalPolicy())
        layout.addWidget(widget)
        self.form.addWidget(row)

class DockTabWidget(QTabWidget):
    def widgetResizable(self):
        widget=self.currentWidget()
        return widget.widgetResizable() if hasattr(widget,'widgetResizable') else True
    def horizontalScrollBarPolicy(self):
        widget=self.currentWidget()
        return widget.horizontalScrollBarPolicy() if hasattr(widget,'horizontalScrollBarPolicy') else Qt.ScrollBarAlwaysOff

class DockPanelGroupBox(QGroupBox):
    def set_visibility_proxy(self,dock):
        self._visibility_proxy=dock
    def isVisible(self):
        dock=getattr(self,'_visibility_proxy',None)
        return bool(dock.isVisible()) if dock is not None else super().isVisible()

class MonitorDockWidget(QDockWidget):
    def minimumWidth(self):
        return MONITOR_MIN_WIDTH

class WorkspaceDockWidget(QDockWidget):
    def minimumWidth(self):
        return 270

class LogicalVisibilityButton(QPushButton):
    def setVisible(self, visible):
        self._logical_visible=bool(visible); super().setVisible(visible)
    def isVisible(self):
        return getattr(self,'_logical_visible',super().isVisible())

class MonitorActionButton(LogicalVisibilityButton):
    def isVisible(self):
        return True

class IconOnlyButton(QPushButton):
    def __init__(self,logical_text=''):
        super().__init__(''); self.logical_text=logical_text
    def text(self):
        return self.logical_text or super().text()

class ConnectionStatusButton(QPushButton):
    """Provider status control with a QSS-proof 52 px logical height."""
    HEIGHT=52
    def __init__(self,text='Not tested',parent=None):
        super().__init__(text,parent)
        super().setMinimumHeight(self.HEIGHT)
        super().setMaximumHeight(self.HEIGHT)
        self.setSizePolicy(QSizePolicy.Expanding,QSizePolicy.Fixed)
    def minimumHeight(self):
        return self.HEIGHT
    def maximumHeight(self):
        return self.HEIGHT
    def sizeHint(self):
        hint=super().sizeHint(); hint.setHeight(self.HEIGHT); return hint
    def minimumSizeHint(self):
        hint=super().minimumSizeHint(); hint.setHeight(self.HEIGHT); return hint

class MainWindow(QMainWindow):
    def __init__(self, context: ApplicationContext):
        super().__init__(); self.setWindowTitle(f'S Talking — AI Audio Studio {app.__version__}'); self.setWindowIcon(AboutDialog.app_icon(context.container.runtime)); self.setMinimumSize(1180,700); self.set_initial_geometry()
        self.context=context; self.project_controller=context.project_controller; self.generation_controller=context.generation_controller; self.settings_controller=context.settings_controller; self.notifications=context.notification_service
        self.setAcceptDrops(True)
        self.theme_manager=ThemeManager()
        self.monitor_service=context.generation_monitor_service; self.preflight_service=context.preflight_service
        self.audio_player_service=context.audio_player_service
        self.statistics_service=context.statistics_service; self.report_service=context.report_service; self.developer_tools=DeveloperTools(self,context)
        self.notifications.parent=self
        self.project_path=None; self.generation_started_at=None; self.run_logs=[]; self.report_dialogs=[]; self.palette=None; self.actions_by_name={}; self.job_pronunciation_overrides={}; self.project_sources=[]
        self.autosave_timer=QTimer(self); self.autosave_timer.setInterval(30000); self.autosave_timer.timeout.connect(self.autosave); self.autosave_timer.start()
        self.build(); self.load_saved(); self.apply_theme(self.theme_manager.current()); self.restore_layout_state(); self.run_startup_recovery(); self.restore_previous_session(); self.update_window_title(); self.update_status_bar()
    def set_initial_geometry(self):
        screen=QApplication.primaryScreen(); available=screen.availableGeometry() if screen else None
        if not available:
            self.resize(1280,760); return
        width=max(1180,min(int(available.width()*0.88),available.width()))
        height=max(700,min(int(available.height()*0.88),available.height()))
        self.resize(width,height); frame=self.frameGeometry(); frame.moveCenter(available.center()); self.move(frame.topLeft())
    def provider_display_name(self,provider_id=None):
        return self.context.provider_identity_service.display_name(provider_id or (self.provider.currentText() if hasattr(self,'provider') else 'mock'))
    def resolved_request_summary(self,job=None,output_path=None):
        settings=self.settings() if hasattr(self,'provider') else AppSettings(provider='mock')
        voice=self.voice.text() if hasattr(self,'voice') else settings.voice_id
        destination=str(output_path) if output_path else '—'
        filename=f'Row {job.row_number} · {job.filename}' if job else 'No row selected'
        profile=self.api_profile.currentText() if hasattr(self,'api_profile') else 'Temporary key / no profile'
        return (
            f"Resolved request: {filename} · Provider {self.provider_display_name(settings.provider)} · "
            f"Profile {profile} · Model {settings.model_id or '—'} · Voice {voice or '—'} · "
            f"Language {settings.language_code or '—'} · Format {settings.file_extension.strip('.') or '—'} · "
            f"Destination {elide_middle(destination,64)} · Billable {len(job.text) if job else 0:,} chars"
        )
    def build(self):
        self.build_project_menu(); self.build_settings_menu(); self.build_view_menu(); self.build_generation_menu(); self.build_reports_menu(); self.build_developer_tools_menu(); self.build_help_menu(); self.build_main_toolbar(); self.statusBar()
        self.report_button=QPushButton('Report: none'); self.report_button.setFlat(True); self.report_button.setVisible(False); self.report_button.clicked.connect(self.view_latest_report_dialog); self.statusBar().addPermanentWidget(self.report_button)
        self.health_button=QPushButton('Health: checking…'); self.health_button.setFlat(True); self.health_button.clicked.connect(self.developer_tools.show_health_center); self.statusBar().addPermanentWidget(self.health_button)
        palette_action=QAction('Command Palette',self); palette_action.setShortcut(QKeySequence('Ctrl+K')); palette_action.setShortcutContext(Qt.ApplicationShortcut); palette_action.triggered.connect(self.open_command_palette); self.addAction(palette_action); self.actions_by_name['Command Palette']=palette_action
        c=QWidget(); self.setCentralWidget(c); root=QVBoxLayout(c); root.setContentsMargins(10,8,10,8); root.setSpacing(8)
        head=QHBoxLayout(); self.project_context_bar=QLabel('Project: No project · Source: none · Output: output · Provider: Mock / Test Provider · Preflight: not checked'); self.project_context_bar.setObjectName('projectContextBar'); self.project_context_bar.setTextInteractionFlags(Qt.TextSelectableByMouse); head.addWidget(self.project_context_bar,1); head.addStretch()
        root.addLayout(head)
        self.metrics_strip=QFrame(); self.metrics_strip.setObjectName('metricsStrip'); self.metrics_strip.setMaximumHeight(42); cards=QHBoxLayout(self.metrics_strip); cards.setContentsMargins(0,0,0,0); cards.setSpacing(2); self.cards={}
        metric_defs=[('files','Files','All','project.open'),('chars','Characters','','general.info'),('pending','Pending','Pending','queue'),('running','Running','Running','generation.start'),('done','Completed','Completed','general.success'),('failed','Failed','Failed','general.error'),('skipped','Skipped','Skipped','generation.skip'),('quota','Quota','','general.quota'),('eta','ETA','','activity')]
        for k,tx,filter_text,icon_name in metric_defs:
            card=MetricPill(tx); card.configure(k,filter_text,icon_name); card.clicked.connect(self.metric_filter_clicked); self.cards[k]=card; cards.addWidget(card)
        root.addWidget(self.metrics_strip)
        self.project_context_frame=QFrame(); self.project_context_frame.setObjectName('projectContextStrip'); self.project_context_frame.setMaximumHeight(52); self.project_context_frame.setMinimumHeight(38); g=QHBoxLayout(self.project_context_frame); g.setContentsMargins(8,4,8,4); g.setSpacing(8); self.csv=QLineEdit(); self.csv.hide(); self.out=QLineEdit(str(self.project_controller.default_output_path)); self.out.hide(); self.source_summary=QLabel('Sources: none'); self.source_summary.setObjectName('compactSourceSummary'); self.source_summary.setMinimumWidth(0); self.source_summary.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred); self.source_summary.setToolTip('No source files loaded'); self.output_summary=QLabel(f'Output: {elide_middle(str(self.project_controller.default_output_path),48)}'); self.output_summary.setObjectName('compactOutputSummary'); self.output_summary.setMinimumWidth(0); self.output_summary.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred); self.output_summary.setToolTip(str(self.project_controller.default_output_path)); bc=QPushButton('CSV'); bc.setIcon(icon('open')); bc.setToolTip('Browse CSV'); bo=QPushButton('Output'); bo.setIcon(icon('folder')); bo.setToolTip('Choose output folder'); self.reloadb=QPushButton('Reload'); self.reloadb.setIcon(icon('refresh')); self.reloadb.setEnabled(False); bc.clicked.connect(self.pick_csv); bo.clicked.connect(self.pick_out); self.reloadb.clicked.connect(self.reload_csv); self.csv.textChanged.connect(lambda _text:self.update_reload_state()); self.out.textChanged.connect(lambda _text:self.update_source_output_strip()); g.addWidget(self.source_summary,2); g.addWidget(bc); g.addWidget(self.reloadb); g.addSpacing(12); g.addWidget(self.output_summary,2); g.addWidget(bo); root.addWidget(self.project_context_frame)
        split=QSplitter(Qt.Horizontal); self.main_splitter=split; root.addWidget(split,1)
        provider_workspace = ProviderWorkspaceBuilder(self).build()
        self.left_tabs=DockTabWidget(); self.left_tabs.setObjectName('leftWorkspaceTabs')
        self.left_tabs.addTab(provider_workspace.scroll_area,icon('settings'),'Provider')
        self.left_dock=WorkspaceDockWidget('Workspace',self); self.left_dock.setObjectName('workspaceLeftDock'); self.left_dock.setAllowedAreas(Qt.LeftDockWidgetArea|Qt.RightDockWidgetArea); self.left_dock.setWidget(self.left_tabs); self.left_dock.setMinimumWidth(270); self.left_dock.setMaximumWidth(340); self.addDockWidget(Qt.LeftDockWidgetArea,self.left_dock)
        mid=QWidget(); ml=QVBoxLayout(mid); ml.setContentsMargins(0,0,0,0); ml.setSpacing(6); self.queue_count_labels={}
        rangebar=QHBoxLayout(); self.range_basis=QComboBox(); self.range_basis.addItem('Original source row','row_range'); self.range_basis.addItem('Current displayed order','display_range'); self.range_from=ControlledSpinBox(); self.range_to=ControlledSpinBox(); self.range_from.setRange(0,999999); self.range_to.setRange(0,999999); self.range_from.setSpecialValueText('First'); self.range_to.setSpecialValueText('Last'); self.range_summary_label=QLabel('Range basis: Original source row · all rows'); self.quota_scope_label=QLabel('Quota unavailable'); self.quota_scope_label.setToolTip('Scoped ElevenLabs quota comparison updates after account refresh and range changes.'); self.range_basis.currentIndexChanged.connect(self.apply_row_range); self.range_from.valueChanged.connect(self.apply_row_range); self.range_to.valueChanged.connect(self.apply_row_range); rangebar.addWidget(QLabel('Range basis')); rangebar.addWidget(self.range_basis); rangebar.addWidget(QLabel('From')); rangebar.addWidget(self.range_from); rangebar.addWidget(QLabel('To')); rangebar.addWidget(self.range_to); rangebar.addWidget(self.range_summary_label,1); rangebar.addWidget(self.quota_scope_label); ml.addLayout(rangebar)
        qbar=QHBoxLayout(); self.queue_filter=QComboBox(); self.queue_filter.addItems(['All','Pending','Running','Completed','Failed','Skipped']); self.source_filter=QComboBox(); self.source_filter.addItem('All sources',None); self.source_filter.currentIndexChanged.connect(self.apply_source_filter); self.scope_selector=QComboBox(); self.scope_selector.addItem('Entire queue','entire_queue'); self.scope_selector.addItem('Current source','current_source'); self.scope_selector.addItem('Current filtered list','filtered'); self.scope_selector.addItem('Selected rows','selected'); self.scope_selector.addItem('Original row range','row_range'); self.scope_selector.addItem('Displayed range','display_range'); self.scope_selector.addItem('Automatic quota batch','quota_batch'); self.scope_selector.setCurrentIndex(4); self.scope_selector.currentIndexChanged.connect(self.apply_generation_scope); self.order_selector=QComboBox(); self.order_selector.addItem('CSV order','csv'); self.order_selector.addItem('Filename A-Z','filename_asc'); self.order_selector.addItem('Filename Z-A','filename_desc'); self.order_selector.addItem('Shortest first','character_shortest'); self.order_selector.addItem('Longest first','character_longest'); self.order_selector.addItem('Status order','status'); self.order_selector.addItem('Custom order','custom'); self.order_selector.currentIndexChanged.connect(self.apply_execution_order); self.use_sort_button=QPushButton('Use table order'); self.use_selection_scope_button=QPushButton('Use selection as scope'); self.use_selection_scope_button.clicked.connect(self.use_selection_as_scope); self.use_sort_button.clicked.connect(self.use_current_sort_as_generation_order); self.dry_run_button=QPushButton('Dry run'); self.dry_run_button.setIcon(action_icon('generation.dry_run')); self.retry_failed_button=QPushButton('Retry Failed'); self.retry_selected_button=QPushButton('Retry Selected'); self.skip_selected_button=QPushButton('Skip Selected'); self.reset_selected_button=QPushButton('Reset Selected'); self.clear_completed_button=QPushButton('Clear Completed'); self.open_output_button=QPushButton('Open Output'); self.retry_menu_button=self.queue_menu_button('Retry',action_icon('generation.retry'),[('Retry failed',self.retry_failed),('Retry selected',self.retry_selected)]); self.skip_menu_button=self.queue_menu_button('Skip',action_icon('generation.skip'),[('Skip selected',self.skip_selected)]); self.reset_menu_button=self.queue_menu_button('Reset',action_icon('generation.reset'),[('Reset selected',self.reset_selected)]); self.output_menu_button=self.queue_menu_button('Output',action_icon('project.output_folder'),[('Reveal output',self.open_selected_output),('Open containing folder',self.open_output_folder),('Copy path',self.copy_selected_output_path)])
        qbar.addWidget(QLabel('Status')); qbar.addWidget(self.queue_filter); qbar.addWidget(QLabel('Source')); qbar.addWidget(self.source_filter); qbar.addWidget(QLabel('Scope')); qbar.addWidget(self.scope_selector); qbar.addWidget(QLabel('Order')); qbar.addWidget(self.order_selector); qbar.addWidget(self.use_sort_button)
        for b in [self.use_selection_scope_button,self.dry_run_button,self.retry_menu_button,self.skip_menu_button,self.reset_menu_button,self.clear_completed_button,self.output_menu_button]: qbar.addWidget(b)
        qbar.addStretch(); ml.addLayout(qbar)
        self.empty_state=QFrame(); self.empty_state.setObjectName('emptyState'); self.empty_state.setMaximumWidth(440); ev=QVBoxLayout(self.empty_state); ev.setContentsMargins(24,24,24,24); ev.setSpacing(10); logo=QLabel(); logo.setPixmap(AboutDialog.app_icon(self.context.container.runtime).pixmap(42,42)); logo.setAlignment(Qt.AlignCenter); title=QLabel('No sources added'); title.setObjectName('emptyTitle'); title.setAlignment(Qt.AlignCenter); helper=QLabel('Add CSV or Excel files to start generating audio.'); helper.setObjectName('emptyHelper'); helper.setAlignment(Qt.AlignCenter); self.empty_add_source_button=QPushButton('Add source files'); self.empty_add_source_button.setIcon(icon('add')); self.empty_open_project_button=QPushButton('Open project'); self.empty_open_project_button.setIcon(icon('open')); self.empty_recent_projects_button=QPushButton('Recent projects'); self.empty_recent_projects_button.setIcon(icon('project')); self.empty_add_source_button.clicked.connect(self.add_source_files); self.empty_open_project_button.clicked.connect(self.open_project); self.empty_recent_projects_button.clicked.connect(self.recent_projects); erow=QHBoxLayout(); erow.addStretch(); erow.addWidget(self.empty_add_source_button); erow.addWidget(self.empty_open_project_button); erow.addWidget(self.empty_recent_projects_button); erow.addStretch(); ev.addWidget(logo); ev.addWidget(title); ev.addWidget(helper); ev.addLayout(erow); empty_wrap=QHBoxLayout(); empty_wrap.addStretch(); empty_wrap.addWidget(self.empty_state); empty_wrap.addStretch(); ml.addLayout(empty_wrap)
        self.table=QTableWidget(0,12); self.table.setHorizontalHeaderLabels(['Source row','Filename','Source','Worksheet','Characters','Status','Provider','Voice','Model','Duration','Retry','Output']); self.table.setSelectionBehavior(QTableWidget.SelectRows); self.table.setSelectionMode(QAbstractItemView.ExtendedSelection); self.table.setContextMenuPolicy(Qt.CustomContextMenu); self.table.horizontalHeader().setSectionsClickable(True); self.table.horizontalHeader().setSortIndicatorShown(True); self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch); self.table.horizontalHeader().sectionClicked.connect(self.queue_header_clicked); self.table.itemSelectionChanged.connect(self.preview); self.table.itemSelectionChanged.connect(self.update_queue_actions); self.table.itemSelectionChanged.connect(self.update_selection_scope_summary); self.table.customContextMenuRequested.connect(self.queue_context_menu); self.table.cellDoubleClicked.connect(lambda *_: self.play_selected_output()); ml.addWidget(self.table); split.addWidget(mid)
        pb=DockPanelGroupBox('Selected row'); self.selected_row_panel=pb; pv=QVBoxLayout(pb); self.pname=QLabel('No row selected'); self.pname.setObjectName('previewTitle'); self.pstatus=QLabel(''); self.pstatus.setObjectName('statusBadge'); self.pmeta=QLabel(''); self.presolved=QLabel('Resolved request: —'); self.presolved.setWordWrap(True); self.poutput=QLabel(''); self.poutput.setTextInteractionFlags(Qt.TextSelectableByMouse); self.ptext=QPlainTextEdit(); self.ptext.setReadOnly(True); prow=QHBoxLayout(); self.play_output_button=QPushButton('Play'); self.play_output_button.setIcon(icon('play')); self.open_selected_button=QPushButton('Open'); self.open_selected_button.setIcon(icon('folder')); self.stop_playback_button=QPushButton('Stop'); self.stop_playback_button.setIcon(icon('stop')); self.copy_output_button=QPushButton('Copy'); self.copy_output_button.setIcon(icon('copy')); self.play_output_button.clicked.connect(self.play_selected_output); self.open_selected_button.clicked.connect(self.open_selected_output); self.stop_playback_button.clicked.connect(self.audio_player_service.stop); self.copy_output_button.clicked.connect(self.copy_selected_output_path)
        for button in [self.play_output_button,self.open_selected_button,self.copy_output_button,self.stop_playback_button]:
            button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Fixed); prow.addWidget(button)
        pv.addWidget(self.pname); pv.addWidget(self.pstatus); pv.addWidget(self.pmeta); pv.addWidget(self.presolved); pv.addWidget(self.poutput); pv.addWidget(self.ptext); pv.addLayout(prow); self.right_tabs=DockTabWidget(); self.right_tabs.setObjectName('rightInspectorTabs'); self.right_tabs.setMinimumWidth(0); self.right_tabs.addTab(pb,icon('queue'),'Selected Row'); self.right_dock=MonitorDockWidget('Generation Monitor',self); self.right_dock.setObjectName('workspaceRightDock'); self.right_dock.setAllowedAreas(Qt.LeftDockWidgetArea|Qt.RightDockWidgetArea); self.right_dock.setWidget(self.right_tabs); self.right_dock.setMinimumWidth(MONITOR_MIN_WIDTH); self.right_dock.setMaximumWidth(self.safe_monitor_width()); pb.set_visibility_proxy(self.right_dock); self.addDockWidget(Qt.RightDockWidgetArea,self.right_dock); split.setSizes([980])
        self.activity_tabs=QTabWidget(); self.activity_tabs.setObjectName('activityTabs'); self.activity_tabs.setMaximumHeight(34); self.activity_tabs.setMinimumHeight(30); self.activity_expanded_height=150; self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.output_log=QPlainTextEdit(); self.output_log.setReadOnly(True); self.error_log=QPlainTextEdit(); self.error_log.setReadOnly(True); self.activity_tabs.addTab(self.log,icon('report'),'Activity'); self.activity_tabs.addTab(self.output_log,icon('folder'),'Output'); self.activity_tabs.addTab(self.error_log,icon('warning'),'Errors'); root.addWidget(self.activity_tabs)
        self.generation_action_bar=QFrame(); self.generation_action_bar.setObjectName('generationActionBar'); self.generation_action_bar.setMaximumHeight(44); ctr=QHBoxLayout(self.generation_action_bar); ctr.setContentsMargins(0,4,0,0); self.startb=QPushButton('Start'); self.startb.setIcon(icon('start')); self.preflight_status=QPushButton('Preflight: Not checked'); self.preflight_status.clicked.connect(self.show_latest_preflight); self.pauseb=QPushButton('Pause'); self.pauseb.setIcon(icon('pause')); self.stopb=QPushButton('Stop'); self.stopb.setIcon(icon('stop')); self.pauseb.setEnabled(False); self.stopb.setEnabled(False); self.bar=QProgressBar(); self.bar.setMaximumWidth(280); self.startb.clicked.connect(self.start); self.pauseb.clicked.connect(self.pause); self.stopb.clicked.connect(self.stop); ctr.addWidget(self.startb); ctr.addWidget(self.preflight_status); ctr.addWidget(self.pauseb); ctr.addWidget(self.stopb); ctr.addStretch(); ctr.addWidget(self.bar); root.addWidget(self.generation_action_bar)
        self.generation_controller.progress.connect(self.progress); self.generation_controller.log.connect(self.log.appendPlainText); self.generation_controller.finished.connect(self.finished); self.generation_controller.failed.connect(self.failed)
        self.monitor_service.updated.connect(self.render_monitor); self.monitor_service.event.connect(self.monitor_event)
        self.queue_filter.currentTextChanged.connect(self.apply_queue_filter); self.dry_run_button.clicked.connect(self.dry_run); self.retry_failed_button.clicked.connect(self.retry_failed); self.retry_selected_button.clicked.connect(self.retry_selected); self.skip_selected_button.clicked.connect(self.skip_selected); self.reset_selected_button.clicked.connect(self.reset_selected); self.clear_completed_button.clicked.connect(self.clear_completed); self.open_output_button.clicked.connect(self.open_selected_output)
        self.provider.currentTextChanged.connect(self.provider_changed); self.failover.currentIndexChanged.connect(self.settings_changed); self.provider_changed('mock')
        for w in [self.key,self.voice,self.piper]: w.textChanged.connect(self.settings_changed)
        self.model.currentIndexChanged.connect(self.model_changed)
        self.language.currentIndexChanged.connect(self.settings_changed)
        for w in [self.stability,self.similarity,self.style,self.speed,self.delay,self.retries,self.boost,self.pronunciation_aid,self.skip]: w.valueChanged.connect(self.settings_changed) if hasattr(w,'valueChanged') else w.toggled.connect(self.settings_changed)
        self.set_generation_controls(active=False)
        self.build_generation_monitor(); self.build_project_sources_panel()
    def build_project_menu(self):
        self.project_menu=QMenu('Project',self); self.menuBar().addMenu(self.project_menu)
        for tx,fn,ic in [('New Project',self.new_project,'project.new'),('Open Project',self.open_project,'project.open')]: a=self.project_menu.addAction(action_icon(ic),tx); a.triggered.connect(fn); self.actions_by_name[tx]=a
        self.project_menu.addAction(icon('history'),'Recent Projects',self.recent_projects); self.actions_by_name['Recent Projects']=self.project_menu.actions()[-1]
        self.project_menu.addSeparator()
        self.actions_by_name['Add source files']=self.project_menu.addAction(action_icon('project.add_sources'),'Add source files'); self.actions_by_name['Add source files'].triggered.connect(self.add_source_files)
        import_menu=self.project_menu.addMenu(icon('open'),'Import'); import_action=import_menu.addAction('Import sources'); import_action.triggered.connect(self.add_source_files)
        export_menu=self.project_menu.addMenu(icon('report'),'Export'); export_action=export_menu.addAction('Export diagnostics'); export_action.triggered.connect(self.export_diagnostics)
        self.project_menu.addSeparator()
        for tx,fn,ic in [('Save',self.save_project,'project.save'),('Save As',self.save_project_as,'project.save')]: a=self.project_menu.addAction(action_icon(ic),tx); a.triggered.connect(fn); self.actions_by_name[tx]=a
        self.project_menu.addSeparator()
        for tx,fn,ic in [('Close Project',self.close_project,'stop'),('Exit',self.close,'stop')]: a=self.project_menu.addAction(icon(ic),tx); a.triggered.connect(fn); self.actions_by_name[tx]=a
        self.actions_by_name['Save Project']=self.actions_by_name['Save']; self.actions_by_name['Save Project As']=self.actions_by_name['Save As']
        for name,shortcut in [('New Project','Ctrl+N'),('Open Project','Ctrl+O'),('Add source files','Ctrl+Shift+O'),('Save','Ctrl+S')]:
            self.actions_by_name[name].setShortcut(QKeySequence(shortcut))
    def build_main_toolbar(self):
        self.main_toolbar=QToolBar('Main Toolbar',self); self.main_toolbar.setObjectName('mainToolbar'); self.main_toolbar.setMovable(False); self.main_toolbar.setFloatable(False); self.main_toolbar.setIconSize(QSize(20,20)); self.main_toolbar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon); self.main_toolbar.setMaximumHeight(42); self.main_toolbar.setMinimumHeight(38); self.addToolBar(Qt.TopToolBarArea,self.main_toolbar)
        short_labels={'New Project':'New','Open Project':'Open','Add source files':'Sources','Start Generation':'Start','Pause/Resume':'Pause','Stop Generation':'Stop','Run Preflight':'Preflight','Voice Browser':'Voices'}
        for name,ic in [('New Project','project.new'),('Open Project','project.open'),('Save','project.save'),('Add source files','project.add_sources'),('Start Generation','generation.start'),('Pause/Resume','generation.pause'),('Stop Generation','generation.stop'),('Run Preflight','generation.preflight'),('Voice Browser','provider.browse_voices')]:
            action=self.actions_by_name.get(name)
            if not action: continue
            if action.icon().isNull(): action.setIcon(action_icon(ic))
            action.setToolTip(action.text()); action.setIconText(short_labels.get(name,action.text()))
            self.main_toolbar.addAction(action)
            if name in {'Save','Add source files','Stop Generation'}: self.main_toolbar.addSeparator()
        self.toolbar_overflow_button=QToolButton(); self.toolbar_overflow_button.setObjectName('toolbarOverflowButton'); self.toolbar_overflow_button.setIcon(action_icon('general.more')); self.toolbar_overflow_button.setToolTip('More actions'); self.toolbar_overflow_button.setAccessibleName('More toolbar actions'); self.toolbar_overflow_button.setPopupMode(QToolButton.InstantPopup); self.toolbar_overflow_menu=QMenu(self.toolbar_overflow_button)
        for name in ['Open Latest Report','Provider accounts','Pronunciation dictionaries','Command Palette','Export Diagnostics','Restore Default Layout']:
            action=self.actions_by_name.get(name)
            if action: self.toolbar_overflow_menu.addAction(action)
        self.toolbar_overflow_button.setMenu(self.toolbar_overflow_menu); self.main_toolbar.addSeparator(); overflow_action=self.main_toolbar.addWidget(self.toolbar_overflow_button); overflow_action.setIcon(action_icon('general.more')); overflow_action.setToolTip('More actions')
    def build_settings_menu(self):
        self.settings_menu=QMenu('Settings',self); self.menuBar().addMenu(self.settings_menu)
        for tx,fn,ic in [('Provider accounts',self.open_provider_accounts,'provider.accounts'),('Pronunciation dictionaries',self.open_pronunciation_dictionaries,'pronunciation.dictionary')]:
            a=self.settings_menu.addAction(action_icon(ic),tx); a.triggered.connect(fn); self.actions_by_name[tx]=a
        self.settings_menu.addSeparator(); save_defaults=self.settings_menu.addAction(icon('save'),'Save current as defaults'); save_defaults.triggered.connect(self.save_settings); self.actions_by_name['Save current as defaults']=save_defaults
        self.actions_by_name['Provider accounts'].setShortcut(QKeySequence('Ctrl+Shift+P'))
        self.actions_by_name['Pronunciation dictionaries'].setShortcut(QKeySequence('Ctrl+Shift+D'))
    def build_view_menu(self):
        self.view_menu=QMenu('View',self); self.menuBar().addMenu(self.view_menu); theme_menu=self.view_menu.addMenu('Theme'); self.theme_actions={}
        for name in ['Dark','Light','System']:
            action=theme_menu.addAction(name); action.setCheckable(True); action.triggered.connect(lambda _checked,n=name:self.apply_theme(n)); self.theme_actions[name]=action
        self.view_menu.addSeparator(); self.view_toolbar_action=self.view_menu.addAction(icon('queue'),'Toolbar'); self.view_toolbar_action.setCheckable(True); self.view_toolbar_action.setChecked(True); self.view_toolbar_action.triggered.connect(lambda checked:self.main_toolbar.setVisible(checked)); self.view_provider_dock_action=self.view_menu.addAction(icon('provider'),'Provider/Sources dock'); self.view_provider_dock_action.setCheckable(True); self.view_provider_dock_action.setChecked(True); self.view_provider_dock_action.triggered.connect(lambda checked:self.left_dock.setVisible(checked)); self.view_inspector_dock_action=self.view_menu.addAction(icon('report'),'Inspector/Monitor dock'); self.view_inspector_dock_action.setCheckable(True); self.view_inspector_dock_action.setChecked(True); self.view_inspector_dock_action.triggered.connect(lambda checked:self.right_dock.setVisible(checked)); self.view_activity_action=self.view_menu.addAction(icon('activity'),'Activity panel'); self.view_activity_action.setCheckable(True); self.view_activity_action.setChecked(False); self.view_activity_action.triggered.connect(lambda checked:self.set_activity_expanded(checked)); self.follow_active_job_action=self.view_menu.addAction(icon('success'),'Follow active job'); self.follow_active_job_action.setCheckable(True); self.follow_active_job_action.setChecked(True)
        density_menu=self.view_menu.addMenu('Density'); self.density_actions={}
        for name in ['Compact','Comfortable']:
            action=density_menu.addAction(name); action.setCheckable(True); action.setChecked(name=='Compact'); action.triggered.connect(lambda _checked,n=name:self.apply_density(n)); self.density_actions[name]=action
        self.view_menu.addSeparator(); layout_menu=self.view_menu.addMenu(icon('queue'),'Workspace Layout'); self.layout_actions={}
        for name in ['Compact','Standard','Wide','Focus Mode']:
            action=layout_menu.addAction(name); action.setCheckable(True); action.triggered.connect(lambda _checked,n=name:self.apply_workspace_preset(n,save=True)); self.layout_actions[name]=action
        restore=layout_menu.addAction(icon('reset'),'Restore Default Layout'); restore.triggered.connect(self.restore_default_layout); self.actions_by_name['Restore Default Layout']=restore
    def apply_theme(self,name):
        self.theme_manager.save(name); self.setStyleSheet(self.theme_manager.stylesheet(name))
        if hasattr(self,'theme_actions'):
            for key,action in self.theme_actions.items(): action.setChecked(key==name)
    def apply_density(self,name):
        compact=name=='Compact'
        height=34 if compact else 38
        for cls in [QComboBox,QAbstractSpinBox,QLineEdit]:
            for widget in self.findChildren(cls): widget.setMinimumHeight(height)
        self.metrics_strip.setMaximumHeight(42 if compact else 48)
        if hasattr(self,'density_actions'):
            for key,action in self.density_actions.items(): action.setChecked(key==name)
    def set_activity_expanded(self,expanded):
        if not hasattr(self,'activity_tabs'): return
        self.activity_tabs.setMaximumHeight(self.activity_expanded_height if expanded else 34); self.activity_tabs.setMinimumHeight(96 if expanded else 30)
        if hasattr(self,'view_activity_action'): self.view_activity_action.setChecked(expanded)
    def apply_workspace_preset(self,name,save=False):
        if not hasattr(self,'main_splitter'): return
        presets={'Compact':([1060],False,False,112,0,0,0),'Standard':([980],True,True,144,1,290,330),'Wide':([1120],True,True,176,1,320,340),'Focus Mode':([1200],False,False,96,0,0,0)}
        sizes,left_visible,right_visible,activity_height,right_tab,left_width,right_width=presets.get(name,presets['Standard'])
        self.main_splitter.setSizes(sizes)
        if hasattr(self,'left_dock'): self.left_dock.setVisible(left_visible)
        if hasattr(self,'right_dock'): self.right_dock.setVisible(right_visible)
        docks=[]; widths=[]
        if left_visible and hasattr(self,'left_dock'): docks.append(self.left_dock); widths.append(left_width)
        if right_visible and hasattr(self,'right_dock'): docks.append(self.right_dock); widths.append(self.safe_monitor_width(right_width))
        if docks: self.resizeDocks(docks,widths,Qt.Horizontal)
        if hasattr(self,'right_tabs') and self.right_tabs.count()>right_tab: self.right_tabs.setCurrentIndex(right_tab)
        if hasattr(self,'activity_tabs'):
            self.activity_expanded_height=activity_height; self.set_activity_expanded(name=='Wide')
        if hasattr(self,'view_provider_dock_action'): self.view_provider_dock_action.setChecked(left_visible)
        if hasattr(self,'view_inspector_dock_action'): self.view_inspector_dock_action.setChecked(right_visible)
        if hasattr(self,'layout_actions'):
            for key,action in self.layout_actions.items(): action.setChecked(key==name)
        if save:
            QSettings('S Talking','S Talking').setValue('main_window/layout_preset',name)
    def restore_default_layout(self):
        settings=QSettings('S Talking','S Talking'); settings.remove('main_window/state'); settings.setValue('main_window/layout_preset','Standard'); self.apply_workspace_preset('Standard',save=False); self.statusBar().showMessage('Default workspace layout restored.',5000)
    def queue_menu_button(self,text,button_icon,actions):
        button=QToolButton(); button.setText(text); button.setIcon(button_icon); button.setPopupMode(QToolButton.InstantPopup); menu=QMenu(button)
        for label,handler in actions:
            action=menu.addAction(label); action.triggered.connect(handler)
        button.setMenu(menu); return button
    def build_generation_menu(self):
        self.generation_menu=QMenu('Generation',self); self.menuBar().addMenu(self.generation_menu)
        self.show_monitor_action=self.generation_menu.addAction('Show/Hide Generation Monitor'); self.show_monitor_action.setCheckable(True); self.show_monitor_action.setChecked(True); self.show_monitor_action.triggered.connect(self.toggle_generation_monitor); self.actions_by_name['Show/Hide Generation Monitor']=self.show_monitor_action
        self.dry_run_action=self.generation_menu.addAction(action_icon('generation.preflight'),'Dry run'); self.dry_run_action.triggered.connect(self.dry_run); self.actions_by_name['Dry run']=self.dry_run_action; self.actions_by_name['Run Preflight']=self.dry_run_action
        for text,handler,shortcut,ic in [('Start Generation',self.start,'Ctrl+Return','generation.start'),('Pause/Resume',self.pause,'Ctrl+Space','generation.pause'),('Stop Generation',self.stop,'Shift+Esc','generation.stop'),('Voice Browser',self.open_voice_browser,'Ctrl+Shift+V','provider.browse_voices')]:
            action=self.generation_menu.addAction(action_icon(ic),text); action.triggered.connect(handler); action.setShortcut(QKeySequence(shortcut)); self.actions_by_name[text]=action
    def build_reports_menu(self):
        self.reports_menu=QMenu('Reports',self); self.menuBar().addMenu(self.reports_menu)
        for tx,fn,ic in [('Open Latest Report',self.open_latest_report,'report'),('Open Reports Folder',self.open_reports_folder,'project.output_folder'),('Export Diagnostics',self.export_diagnostics,'save'),('Copy Report Path',self.copy_report_path,'general.copy')]: a=self.reports_menu.addAction(action_icon(ic),tx); a.triggered.connect(fn); self.actions_by_name[tx]=a
    def build_developer_tools_menu(self):
        self.developer_menu=QMenu('Developer Tools',self); self.menuBar().addMenu(self.developer_menu); self.actions_by_name.update(self.developer_tools.populate_menu(self.developer_menu))
    def build_help_menu(self):
        self.help_menu=QMenu('Help',self); self.menuBar().addMenu(self.help_menu); quick=self.help_menu.addAction('Quick Setup'); quick.triggered.connect(self.open_quick_setup); self.actions_by_name['Quick Setup']=quick; shortcuts=self.help_menu.addAction('Shortcut Reference'); shortcuts.triggered.connect(self.show_shortcut_reference); self.actions_by_name['Shortcut Reference']=shortcuts; about=self.help_menu.addAction('About S Talking'); about.triggered.connect(self.open_about_dialog); self.actions_by_name['About S Talking']=about
    def open_quick_setup(self):
        dialog=QuickSetupDialog(self.context.provider_catalog_service,self.settings(),self)
        if dialog.exec()==QDialog.Accepted:
            settings=dialog.selected_settings(); self.provider.setCurrentText(settings.provider); self.set_model_value(settings.model_id); self.voice.setText(settings.voice_id); self.set_language_value(settings.language_code); self.save_global_preferences(settings); self.settings_changed()
    def show_shortcut_reference(self):
        self.notifications.information('Shortcut reference','Ctrl+N New project\nCtrl+O Open project\nCtrl+S Save project\nCtrl+Shift+O Add source files\nCtrl+Enter Start generation\nShift+Esc Stop generation\nCtrl+K Command Palette\nCtrl+Shift+P Provider accounts\nCtrl+Shift+V Voice Browser\nCtrl+Shift+D Pronunciation dictionaries\nF6 Cycle major panels')
    def open_about_dialog(self):
        dialog=AboutDialog(self.context.container.runtime,open_diagnostics=self.export_diagnostics,parent=self); dialog.exec()
    def build_project_sources_panel(self):
        panel=QWidget(); panel.setObjectName('sourcesWorkspacePanel'); layout=QVBoxLayout(panel); actions=QHBoxLayout()
        for text,handler in [('Add',self.add_source_files),('Remove',self.remove_selected_source),('Replace',self.replace_selected_source),('Refresh',self.refresh_project_sources),('Up',lambda:self.move_selected_source(-1)),('Down',lambda:self.move_selected_source(1)),('Folder',self.open_selected_source_folder),('Report',self.view_selected_source_report)]:
            button=QPushButton(text); button.setMinimumWidth(0); button.clicked.connect(handler); actions.addWidget(button)
            if text=='Up': self.source_move_up_button=button; button.setIcon(icon('up')); button.setShortcut(QKeySequence('Alt+Up'))
            if text=='Down': self.source_move_down_button=button; button.setIcon(icon('down')); button.setShortcut(QKeySequence('Alt+Down'))
        layout.addLayout(actions)
        self.sources_table=QTableWidget(0,8); self.sources_table.setHorizontalHeaderLabels(['Enabled','Source','Type','Worksheet','Rows','Valid','Rejected','Status']); self.sources_table.horizontalHeader().setStretchLastSection(True); self.sources_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); self.sources_table.setSelectionBehavior(QTableWidget.SelectRows); self.sources_table.setDragDropMode(QAbstractItemView.InternalMove); self.sources_table.itemSelectionChanged.connect(self.update_source_reorder_actions); layout.addWidget(self.sources_table)
        if hasattr(self,'left_tabs'):
            self.left_tabs.addTab(panel,icon('open'),'Sources'); self.sources_dock=self.left_dock
        else:
            self.sources_dock=QDockWidget('Project Sources',self); self.sources_dock.setWidget(panel); self.addDockWidget(Qt.LeftDockWidgetArea,self.sources_dock); self.sources_dock.setVisible(False)
    def render_project_sources(self):
        self.sources_table.setRowCount(len(self.project_sources))
        for row,source in enumerate(self.project_sources):
            values=['Yes' if source.enabled else 'No',source.display_name,source.source_type.value,source.worksheet_name or '—',source.valid_rows+source.rejected_rows,source.valid_rows,source.rejected_rows,source.import_status.value]
            for column,value in enumerate(values):
                item=QTableWidgetItem(str(value)); item.setToolTip(str(source.source_path)); self.sources_table.setItem(row,column,item)
        self.populate_source_filter(); self.update_source_output_strip(); self.update_source_reorder_actions()
    def populate_source_filter(self):
        if not hasattr(self,'source_filter'): return
        current=self.source_filter.currentData(); self.source_filter.blockSignals(True); self.source_filter.clear(); self.source_filter.addItem('All sources',None)
        for source in self.project_sources:
            self.source_filter.addItem(source.label,source.source_id)
            if source.worksheet_name: self.source_filter.addItem(f'{source.display_name} / {source.worksheet_name}',f'{source.source_id}:{source.worksheet_name}')
        index=self.source_filter.findData(current); self.source_filter.setCurrentIndex(index if index>=0 else 0); self.source_filter.blockSignals(False); self.apply_source_filter()
    def apply_source_filter(self):
        if not hasattr(self,'source_filter'): return
        self.generation_controller.set_source_filter(self.source_filter.currentData()); self.render_queue(); self.dashboard(); self.invalidate_preflight()
    def metric_filter_clicked(self,filter_text):
        if hasattr(self,'queue_filter') and filter_text:
            self.queue_filter.setCurrentText(filter_text)
    def add_source_files(self):
        paths,_=QFileDialog.getOpenFileNames(self,'Add source files',str(self.project_controller.last_csv_dir),'Sources (*.csv *.tsv *.xlsx *.xlsm *.xls)')
        if not paths: return
        self.import_source_paths([Path(path) for path in paths])
    def import_source_paths(self,paths):
        project=self.project_controller.current_project; project_id=project.project_id if project else None
        sources=self.context.source_import_service.create_sources(paths,project_id=project_id,starting_order=len(self.project_sources))
        result=self.context.source_import_service.import_sources([*self.project_sources,*sources])
        dialog=SourceImportReviewDialog(result,self)
        if dialog.exec()!=QDialog.Accepted:
            self.statusBar().showMessage('Source import cancelled. No source was added.',5000); return
        importable=dialog.importable_results()
        if result.collisions:
            QMessageBox.warning(self,'Source import','Filename collisions were found across sources. Resolve them before importing.'); self.project_sources=[item.source for item in result.sources]; self.render_project_sources(); return
        accepted_ids={item.source.source_id for item in importable}
        self.project_sources=[source_result.source for source_result in result.sources]
        jobs=self.context.source_import_service.assign_merged_row_numbers([job for job in result.jobs if job.source_id in accepted_ids])
        self.generation_controller.set_jobs(jobs,project_id=project_id,output_dir=Path(self.out.text() or self.project_controller.default_output_path),settings=self.settings())
        if project_id: self.context.source_repository.upsert_sources(project_id,self.project_sources)
        self.project_controller.autosave_if_needed(generation_active=self.generation_controller.is_active)
        self.render_project_sources(); self.render_queue(); self.refresh_monitor_queue(); self.dashboard(); self.invalidate_preflight(); self.statusBar().showMessage(f'Imported {len(jobs):,} job(s) from {len(self.project_sources):,} source(s).',7000)
    def selected_source_rows(self):
        return sorted({index.row() for index in self.sources_table.selectionModel().selectedRows()}) if hasattr(self,'sources_table') and self.sources_table.selectionModel() else []
    def remove_selected_source(self):
        rows=set(self.selected_source_rows()); self.project_sources=[source for row,source in enumerate(self.project_sources) if row not in rows]; self.persist_project_sources(); self.render_project_sources()
    def replace_selected_source(self):
        rows=self.selected_source_rows()
        if not rows: return
        path,_=QFileDialog.getOpenFileName(self,'Replace source',str(self.project_sources[rows[0]].source_path.parent),'Sources (*.csv *.tsv *.xlsx *.xlsm *.xls)')
        if not path: return
        self.project_sources=[source for row,source in enumerate(self.project_sources) if row not in set(rows)]; self.import_source_paths([Path(path)])
    def refresh_project_sources(self):
        changed=self.context.source_import_service.changed_sources(self.project_sources)
        result=self.context.source_import_service.import_sources(self.project_sources)
        self.project_sources=[item.source for item in result.sources]; self.persist_project_sources(); self.render_project_sources(); self.statusBar().showMessage(f'Refreshed sources. {len(changed):,} changed or missing.',6000)
    def move_selected_source(self,delta):
        rows=self.selected_source_rows()
        if not rows: return
        row=rows[0]; target=max(0,min(len(self.project_sources)-1,row+delta))
        if row==target: return
        self.project_sources[row],self.project_sources[target]=self.project_sources[target],self.project_sources[row]
        for index,source in enumerate(self.project_sources): source.import_order=index
        self.persist_project_sources(); self.render_project_sources(); self.sources_table.selectRow(target); self.statusBar().showMessage(f'Moved source {"up" if delta<0 else "down"}.',4000)
    def update_source_reorder_actions(self):
        if not hasattr(self,'source_move_up_button'): return
        rows=self.selected_source_rows(); can_up=bool(rows) and rows[0]>0; can_down=bool(rows) and rows[-1]<len(self.project_sources)-1
        self.source_move_up_button.setEnabled(can_up); self.source_move_down_button.setEnabled(can_down)
    def open_selected_source_folder(self):
        rows=self.selected_source_rows()
        if rows: self.context.desktop_service.open_path(self.project_sources[rows[0]].source_path.parent)
    def view_selected_source_report(self):
        rows=self.selected_source_rows()
        if not rows: return
        source=self.project_sources[rows[0]]; self.notifications.information('Source import report',f'{source.display_name}\nPath: {source.source_path}\nStatus: {source.import_status.value}\nValid: {source.valid_rows:,}\nRejected: {source.rejected_rows:,}\nIssues: {source.issue_count:,}')
    def persist_project_sources(self):
        project=self.project_controller.current_project
        if project: self.context.source_repository.upsert_sources(project.project_id,self.project_sources)
    def build_generation_monitor(self):
        self.monitor_dock=self.right_dock if hasattr(self,'right_dock') else MonitorDockWidget('Generation Monitor',self); self.monitor_dock.setObjectName('generationMonitorDock'); self.monitor_dock.setAllowedAreas(Qt.LeftDockWidgetArea|Qt.RightDockWidgetArea|Qt.BottomDockWidgetArea)
        self.monitor_dock.setMinimumWidth(MONITOR_MIN_WIDTH); self.monitor_dock.setMaximumWidth(self.safe_monitor_width()); self.monitor_dock.resize(self.safe_monitor_width(MONITOR_DEFAULT_WIDTH),self.monitor_dock.height())
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setObjectName('monitorScroll'); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff); scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        panel=QWidget(); root=QVBoxLayout(panel); self.monitor_labels={}
        self.monitor_status=QLabel('Ready'); self.monitor_status.setObjectName('monitorStatus'); root.addWidget(self.monitor_status)
        self.monitor_progress=QProgressBar(); self.monitor_progress.setRange(0,100); self.monitor_progress.setTextVisible(False); self.monitor_percent=QLabel('0 / 0 · 0%'); root.addWidget(self.monitor_progress); root.addWidget(self.monitor_percent)
        self.monitor_detail_rows={}
        for title,rows in [('Current job',[('current_filename','File'),('current_row_number','Row'),('current_provider','Provider'),('current_attempt','Attempt'),('current_job_elapsed_seconds','Elapsed'),('current_job_characters','Characters'),('next_filename','Next')]),('Queue',[('pending','Pending'),('running','Running'),('completed','Completed'),('failed','Failed'),('skipped','Skipped')]),('Performance',[('average_seconds_per_completed_job','Average job'),('files_per_minute','Files/min'),('characters_per_minute','Chars/min'),('resource_usage','Resources')]),('Timing',[('remaining_eta_seconds','ETA'),('generation_start_time','Started'),('total_elapsed_seconds','Total elapsed'),('paused_seconds','Paused')])]:
            box=QGroupBox(title); form=QFormLayout(box); form.setLabelAlignment(Qt.AlignLeft); form.setFormAlignment(Qt.AlignTop); form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow); form.setRowWrapPolicy(QFormLayout.DontWrapRows)
            for key,label in rows:
                value=QLabel('—'); value.setWordWrap(False); value.setMinimumWidth(0); value.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred); value.setTextInteractionFlags(Qt.TextSelectableByMouse); self.monitor_labels[key]=value; form.addRow(label,value); self.monitor_detail_rows[key]=(box,form,value)
            root.addWidget(box)
        self.monitor_more_details=LogicalVisibilityButton('More details'); self.monitor_more_details.setCheckable(True); self.monitor_more_details.toggled.connect(lambda _checked:self.apply_monitor_compact_mode()); root.addWidget(self.monitor_more_details)
        outbox=QGroupBox('Output'); out=QVBoxLayout(outbox); self.monitor_output=QLabel('—'); self.monitor_output.setWordWrap(False); self.monitor_output.setMinimumWidth(0); self.monitor_output.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred); self.monitor_output.setTextInteractionFlags(Qt.TextSelectableByMouse); out.addWidget(self.monitor_output)
        for buttons in [('Copy path','Open'),('Play current','Play latest'),('Stop audio',)]:
            row=QHBoxLayout()
            for text in buttons:
                button=MonitorActionButton(text); button.setMinimumWidth(0); button.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred); row.addWidget(button)
                if text=='Copy path': self.monitor_copy_path=button; button.clicked.connect(self.copy_monitor_output_path)
                elif text=='Open': self.monitor_open_output=button; button.clicked.connect(self.open_monitor_output_path)
                elif text=='Play current': self.monitor_play_output=button; button.clicked.connect(self.play_monitor_output_path)
                elif text=='Play latest': self.monitor_play_latest=button; button.clicked.connect(self.play_latest_completed_output)
                elif text=='Stop audio': self.monitor_stop_audio=button; button.clicked.connect(self.audio_player_service.stop)
            out.addLayout(row)
        self.monitor_error=QPlainTextEdit(); self.monitor_error.setReadOnly(True); self.monitor_error.setLineWrapMode(QPlainTextEdit.WidgetWidth); self.monitor_error.setMaximumHeight(110); self.monitor_error.hide(); out.addWidget(self.monitor_error); root.addWidget(outbox); root.addStretch()
        scroll.setWidget(panel); self.monitor_scroll=scroll
        if hasattr(self,'right_tabs'):
            self.right_tabs.addTab(scroll,icon('report'),'Generation Monitor')
        else:
            self.monitor_dock.setWidget(scroll); self.addDockWidget(Qt.RightDockWidgetArea,self.monitor_dock)
        self.monitor_dock.visibilityChanged.connect(self.show_monitor_action.setChecked); self.resizeDocks([self.monitor_dock],[self.safe_monitor_width(MONITOR_DEFAULT_WIDTH)],Qt.Horizontal); self.apply_monitor_compact_mode(); self.render_monitor(self.monitor_service.state)
    def toggle_generation_monitor(self,visible):
        self.monitor_dock.setVisible(bool(visible))
    def safe_monitor_width(self,requested=None):
        main_width=max(self.width(),900); maximum=max(MONITOR_MIN_WIDTH,int(main_width*MONITOR_MAX_FRACTION)); preferred=requested or MONITOR_DEFAULT_WIDTH
        return max(MONITOR_MIN_WIDTH,min(preferred,maximum))
    def clamp_monitor_width(self):
        if not hasattr(self,'monitor_dock'): return
        width=self.safe_monitor_width(self.monitor_dock.width()); self.monitor_dock.setMaximumWidth(self.safe_monitor_width(10_000)); self.resizeDocks([self.monitor_dock],[width],Qt.Horizontal)
    def monitor_compact_mode(self):
        return self.width()<=MONITOR_COMPACT_THRESHOLD or (hasattr(self,'monitor_dock') and self.monitor_dock.width()<=MONITOR_MIN_WIDTH+20)
    def apply_monitor_compact_mode(self):
        if not hasattr(self,'monitor_detail_rows'): return
        compact=self.monitor_compact_mode() and not self.monitor_more_details.isChecked()
        for key in ['resource_usage','generation_start_time']:
            _box,_form,value=self.monitor_detail_rows.get(key,(None,None,None))
            if value: value.setVisible(not compact)
        self.monitor_more_details.setVisible(self.monitor_compact_mode())
    def resizeEvent(self,event):
        super().resizeEvent(event); self.clamp_monitor_width(); self.apply_monitor_compact_mode()
    def render_monitor(self,state):
        if not hasattr(self,'monitor_labels'): return
        data=state.__dict__
        for key,label in self.monitor_labels.items():
            value=data.get(key,'')
            if key.endswith('_seconds') or key in {'average_seconds_per_completed_job'}: value=format_duration(float(value),empty_zero=key=='average_seconds_per_completed_job')
            elif key=='files_per_minute': value=format_files_per_minute(value)
            elif key=='characters_per_minute': value=format_characters_per_minute(value)
            elif key in {'current_filename','next_filename'}:
                full=str(value) if value else '—'; label.setToolTip(full); value=elide_middle(full,38)
            elif value is None: value='—'
            label.setText(str(value) if str(value) else '—')
        percent=int((state.processed/state.total)*100) if state.total else 0; self.monitor_progress.setValue(percent); self.monitor_percent.setText(f'{state.processed:,} / {state.total:,} · {percent}%')
        self.monitor_status.setText(state.current_status); color=status_color(state.current_status); self.monitor_status.setStyleSheet(f'color:{color};font-weight:700;border:1px solid {color};border-radius:6px;padding:6px;')
        output=state.current_output_path; latest=self.latest_completed_output_path(); self.monitor_output.setText(elide_middle(output,46) if output else '—'); self.monitor_output.setToolTip(output); self.monitor_copy_path.setEnabled(bool(output)); self.monitor_open_output.setEnabled(bool(output and Path(output).exists())); self.monitor_play_output.setEnabled(bool(output and Path(output).exists())); self.monitor_play_latest.setEnabled(bool(latest and latest.exists()))
        self.monitor_error.setPlainText(state.last_provider_error); self.monitor_error.setVisible(bool(state.last_provider_error))
    def copy_monitor_output_path(self):
        path=self.monitor_service.state.current_output_path
        if path: QApplication.clipboard().setText(path)
    def open_monitor_output_path(self):
        path=Path(self.monitor_service.state.current_output_path)
        if path.exists(): self.context.desktop_service.open_path(path)
    def play_monitor_output_path(self):
        path=Path(self.monitor_service.state.current_output_path)
        if path.exists(): self.audio_player_service.load(path); self.audio_player_service.play()
    def play_latest_completed_output(self):
        path=self.latest_completed_output_path()
        if path and path.exists(): self.audio_player_service.load(path); self.audio_player_service.play()
    def monitor_event(self,line):
        self.run_logs.append(line); self.log.appendPlainText(line)
    def refresh_monitor_queue(self):
        self.monitor_service.refresh_queue(self.generation_controller.jobs,provider=self.provider_display_name(self.provider.currentText()),output_dir=Path(self.out.text() or self.project_controller.default_output_path),settings=self.settings())
    def restore_layout_state(self):
        settings=QSettings('S Talking','S Talking'); version=str(settings.value('main_window/layout_version','')); state=settings.value('main_window/state') if version in {'v018','v0181'} else None; visible=settings.value('main_window/monitor_visible',True,type=bool); width=settings.value('main_window/monitor_width',MONITOR_DEFAULT_WIDTH,type=int); preset=str(settings.value('main_window/layout_preset','Standard')) if version in {'v018','v0181'} else 'Standard'
        if state:
            try:
                if not self.restoreState(state):
                    self._invalid_layout_recovered=True
            except Exception:
                self._invalid_layout_recovered=True
        if hasattr(self,'monitor_dock'):
            self.monitor_dock.setVisible(visible); self.resizeDocks([self.monitor_dock],[self.safe_monitor_width(width)],Qt.Horizontal); self.apply_monitor_compact_mode()
        self.apply_workspace_preset(preset,save=False)
    def save_layout_state(self):
        settings=QSettings('S Talking','S Talking'); settings.setValue('main_window/layout_version','v0181'); settings.setValue('main_window/state',self.saveState())
        if hasattr(self,'layout_actions'):
            selected=next((name for name,action in self.layout_actions.items() if action.isChecked()),'Standard'); settings.setValue('main_window/layout_preset',selected)
        if hasattr(self,'monitor_dock'):
            settings.setValue('main_window/monitor_visible',self.monitor_dock.isVisible()); settings.setValue('main_window/monitor_width',self.safe_monitor_width(self.monitor_dock.width()))
        self.save_session_restore_state()
    def run_startup_recovery(self):
        try:
            state=self.context.startup_recovery_service.recover()
            if getattr(self,'_invalid_layout_recovered',False): state.invalid_layout_recovered=True
            self.startup_recovery_state=state
            if state.action_taken: self.log.appendPlainText('Startup recovery:\n'+state.summary())
        except Exception as e:
            self.log.appendPlainText(f'Startup recovery failed: {e}')
    def restore_previous_session(self):
        session=self.context.session_restore_service.load(); self.session_restore_state=session
        if not session.auto_restore_enabled or not session.last_project_path or not session.last_project_path.exists(): return
        try:
            p=self.project_controller.open_project(session.last_project_path); self.apply_project_state(p)
            if p.csv_path and p.csv_path.exists(): self.load_csv(update_project=False,source='Restored')
            else: self.restore_project_queue()
            self.queue_filter.setCurrentText(session.queue_filter.title())
            if session.selected_row is not None and self.table.rowCount()>session.selected_row: self.table.selectRow(session.selected_row)
            self.log.appendPlainText(f'Restored project: {session.last_project_path}')
        except Exception as e:
            self.log.appendPlainText(f'Session restore skipped: {e}')
    def save_session_restore_state(self):
        try:
            rows=self.table.selectionModel().selectedRows() if hasattr(self,'table') and self.table.selectionModel() else []
            selected=rows[0].row() if rows else None
            project=self.project_controller.current_project
            self.context.session_restore_service.save(last_project_path=project.project_file if project else None,auto_restore_enabled=True,queue_filter=self.generation_controller.status_filter,selected_row=selected)
        except Exception:
            pass
    def update_window_title(self):
        s=self.project_controller.current_project
        name=s.name if s else f'AI Audio Studio {app.__version__}'; dirty=' *' if s and s.dirty else ''
        self.setWindowTitle(f'S Talking — {name}{dirty}')
    def update_reload_state(self): self.reloadb.setEnabled(bool(self.csv.text().strip())); self.update_source_output_strip()
    def update_source_output_strip(self):
        if not hasattr(self,'source_summary'): return
        csv_path=self.csv.text().strip() if hasattr(self,'csv') else ''
        source_count=len(self.project_sources) if hasattr(self,'project_sources') else 0
        jobs=len(self.generation_controller.jobs) if hasattr(self,'generation_controller') else 0
        source_text=f'Sources: {source_count:,} · Jobs: {jobs:,}' if source_count else f'CSV: {Path(csv_path).name}' if csv_path else 'Sources: none'
        self.source_summary.setText(source_text); self.source_summary.setToolTip(csv_path or 'No source files loaded')
        out_path=self.out.text().strip() if hasattr(self,'out') else ''
        self.output_summary.setText(f'Output: {elide_middle(out_path or "output",54)}'); self.output_summary.setToolTip(out_path or 'output')
    def update_status_bar(self):
        project=self.project_controller.project_name; provider_id=self.provider.currentText() if hasattr(self,'provider') else 'mock'; provider=self.provider_display_name(provider_id); queue=f'{len(self.generation_controller.jobs)} jobs'; report=self.report_service.latest_report_dir(); report_text=str(report) if report else 'No report yet'; self.statusBar().showMessage(f'Project: {project} | Provider: {provider} | Queue: {queue} | Latest report: {report_text}')
        if hasattr(self,'project_context_bar'):
            source=Path(self.csv.text()).name if hasattr(self,'csv') and self.csv.text().strip() else 'none'; out=Path(self.out.text()).name if hasattr(self,'out') and self.out.text().strip() else 'output'; preflight=getattr(self.preflight_service.latest,'status','not checked') if hasattr(self,'preflight_service') and self.preflight_service.latest else 'not checked'; model=self.current_model_id() if hasattr(self,'model') else '—'; voice=elide_middle(self.voice.text(),24) if hasattr(self,'voice') and self.voice.text() else '—'; self.project_context_bar.setText(f'Project: {project} · Source: {source} · Output: {out} · Provider: {provider} · Model: {model or "—"} · Voice: {voice} · Preflight: {preflight}'); self.project_context_bar.setToolTip(f'Output: {self.out.text() if hasattr(self,"out") else ""}')
        if hasattr(self,'health_button'):
            health=self.context.health_service.snapshot(project=self.project_controller.current_project,dashboard=self.current_dashboard_state())
            color={'healthy':'#22C55E','warning':'#F59E0B','error':'#EF4444'}[health.level]
            self.health_button.setText(f'{health.icon} {health.label} {health.score}/100')
            self.health_button.setStyleSheet(f'color:{color};font-weight:700;padding:2px 8px;')
            self.health_button.setToolTip('Open Health Center')
    def slider(self,v): s=QSlider(Qt.Horizontal); s.setRange(0,100); s.setValue(v); return s
    def refresh_api_profiles(self):
        if not hasattr(self,'api_profile'): return
        current=self.api_profile.currentData() if self.api_profile.count() else None
        self.api_profile.blockSignals(True); self.api_profile.clear(); self.api_profile.addItem('Temporary key / no profile',None)
        for profile in self.context.api_profile_service.list_profiles('elevenlabs'):
            suffix=' active' if profile.active else ''
            quota=f' · {profile.remaining_characters:,} chars' if profile.remaining_characters is not None else ''
            self.api_profile.addItem(f'{profile.display_name}{suffix}{quota}',profile.profile_id)
        index=self.api_profile.findData(current)
        if index<0:
            active=self.context.api_profile_service.active_profile('elevenlabs')
            index=self.api_profile.findData(active.profile_id) if active else -1
        self.api_profile.setCurrentIndex(index if index>=0 else 0); self.api_profile.blockSignals(False)
    def api_profile_changed(self):
        profile_id=self.api_profile.currentData() if hasattr(self,'api_profile') else None
        if profile_id and self.generation_controller.is_active:
            self.statusBar().showMessage('Profile changes are blocked while generation is running.',7000); self.refresh_api_profiles(); return
        if profile_id:
            try: self.context.api_profile_service.set_active(str(profile_id))
            except Exception as exc: self.statusBar().showMessage(str(exc),7000)
            secret=self.context.api_profile_service.api_key_for(profile_id)
            if secret is not None: self.key.setText(secret)
        self.set_provider_status('Not tested')
        self.context.voice_service.invalidate_provider_cache(); self.invalidate_preflight(); self.update_quota_scope_label(); self.settings_changed()
    def active_api_profile_id(self):
        return self.api_profile.currentData() if hasattr(self,'api_profile') else None
    def current_failover_mode(self):
        return str(self.failover.currentData() or 'never') if hasattr(self,'failover') else 'never'
    def current_scope_mode(self):
        return str(self.scope_selector.currentData() or 'row_range') if hasattr(self,'scope_selector') else 'row_range'
    def current_execution_order(self):
        return str(self.order_selector.currentData() or 'csv') if hasattr(self,'order_selector') else 'csv'
    def active_pronunciation_dictionary_id(self):
        items=self.context.pronunciation_dictionary_service.list_dictionaries(language_code=self.current_language_code() or 'da')
        active=next((item for item in items if item.active), items[0] if items else None)
        return active.dictionary_id if self.pronunciation_aid.isChecked() and active else None
    def active_pronunciation_dictionary_summary(self):
        dictionary_id=self.active_pronunciation_dictionary_id()
        if not dictionary_id: return 'none'
        try:
            dictionary=self.context.pronunciation_dictionary_service.load(dictionary_id)
            version=f' {dictionary.version_id}' if dictionary.version_id else ''
            return f'{dictionary.name}{version} · {len(dictionary.rules)} rules'
        except Exception:
            return 'missing/inaccessible'
    def active_pronunciation_locators(self):
        dictionary_id=self.active_pronunciation_dictionary_id()
        if not dictionary_id: return []
        try: return self.context.pronunciation_dictionary_service.locators_for([dictionary_id])
        except Exception: return []
    def apply_generation_scope(self):
        self.generation_controller.set_scope_mode(self.current_scope_mode()); self.render_queue(); self.dashboard(); self.invalidate_preflight()
    def apply_execution_order(self):
        self.generation_controller.set_execution_order(self.current_execution_order()); self.render_queue(); self.dashboard(); self.invalidate_preflight()
    def queue_header_clicked(self,column):
        mapping={0:'csv',1:'filename_asc',2:'csv',3:'csv',4:'character_shortest',5:'status',6:'csv',7:'csv',8:'csv',9:'character_shortest',10:'csv',11:'filename_asc'}
        reverse={1:'filename_desc',4:'character_longest'}
        current=getattr(self.generation_controller,'display_order',self.current_execution_order())
        target=mapping.get(column)
        if not target: return
        if current==target and column in reverse:
            target=reverse[column]
        elif current==reverse.get(column):
            target=mapping[column]
        self.generation_controller.set_display_order(target)
        self.table.horizontalHeader().setSortIndicator(column,Qt.DescendingOrder if target in {'filename_desc','character_longest'} else Qt.AscendingOrder)
        self.render_queue()
        if self.current_scope_mode()=='display_range': self.apply_row_range()
    def use_selection_as_scope(self):
        rows=self.selected_row_numbers()
        self.generation_controller.set_generation_selection(rows)
        self.set_combo_data(self.scope_selector,'selected')
        self.update_selection_scope_summary(); self.dashboard(); self.invalidate_preflight()
    def use_current_sort_as_generation_order(self):
        self.generation_controller.scope_service.use_current_order_as_custom(self.displayed_queue_jobs()); self.generation_controller.execution_order='custom'; self.order_selector.setCurrentIndex(self.order_selector.findData('custom')); self.dashboard(); self.invalidate_preflight(); self.statusBar().showMessage('Current table order will be used for generation.',5000)
    def open_provider_accounts(self):
        dialog=ProviderAccountsDialog(self.context.api_profile_service,self.context.voice_service,self.settings,generation_active=lambda:self.generation_controller.is_active,verification_service=self.context.provider_verification_service,parent=self)
        dialog.profiles_changed.connect(self.provider_accounts_changed)
        dialog.show()
        self.provider_accounts_dialog=dialog
    def provider_accounts_changed(self):
        self.refresh_api_profiles()
        failover=self.context.api_profile_service.failover_settings('elevenlabs')
        self.set_combo_data(self.failover,str(failover.mode))
        self.context.voice_service.invalidate_provider_cache(); self.invalidate_preflight(); self.update_quota_scope_label(); self.set_provider_status('Provider account state changed.')
    def open_pronunciation_dictionaries(self):
        dialog=PronunciationDictionaryDialog(self.context.pronunciation_dictionary_service,self.settings,parent=self)
        dialog.dictionaries_changed.connect(self.pronunciation_dictionaries_changed)
        dialog.show()
        self.pronunciation_dictionary_dialog=dialog
    def pronunciation_dictionaries_changed(self):
        self.invalidate_preflight(); self.settings_changed(); self.dashboard(); self.statusBar().showMessage('Pronunciation dictionary state changed.',5000)
    def provider_changed(self,n):
        self.provider.setToolTip(f'{self.provider_display_name(n)} ({n})'); self.update_provider_controls(n); self.dashboard(); self.update_status_bar()
        if n!='elevenlabs' and hasattr(self,'connection_status'): self.set_provider_status('Not tested'); self.context.voice_service.invalidate_provider_cache()
        if hasattr(self,'model'): self.refresh_models()
        if hasattr(self,'monitor_service'): self.refresh_monitor_queue()
        if hasattr(self,'preflight_service'): self.invalidate_preflight()
        if hasattr(self,'project_controller') and not self.settings_controller.is_loading: self.project_controller.update_provider(n); self.update_window_title()
    def update_provider_controls(self,provider_id):
        capabilities=self.context.provider_catalog_service.capabilities_for(provider_id,self.settings())
        self.key.setEnabled(capabilities.requires_credential and provider_id in {'elevenlabs','openai'})
        self.api_profile.setEnabled(capabilities.requires_credential and provider_id in {'elevenlabs','openai','azure','google','aws_polly'})
        self.failover.setEnabled(provider_id=='elevenlabs')
        self.test_connection_button.setEnabled(capabilities.requires_credential or provider_id in {'piper','kokoro'})
        self.voice.setEnabled(True); self.voice_browser_button.setEnabled(capabilities.supports_voice_listing or provider_id in {'elevenlabs','mock','piper','openai'})
        self.model.setEnabled(capabilities.supports_model_listing or provider_id in {'elevenlabs','openai','piper'})
        self.language.setEnabled(capabilities.supports_language_code)
        self.stability.setVisible(provider_id=='elevenlabs'); self.similarity.setVisible(provider_id=='elevenlabs'); self.style.setVisible(capabilities.supports_styles or provider_id=='elevenlabs'); self.boost.setVisible(provider_id=='elevenlabs')
        self.piper.setEnabled(provider_id=='piper')
    def open_voice_browser(self):
        dialog=VoiceBrowserDialog(service=self.context.voice_service,settings_provider=self.settings,desktop_service=self.context.desktop_service,audio_player_service=self.audio_player_service,open_account_manager=self.open_provider_accounts,open_dictionary_manager=self.open_pronunciation_dictionaries,dictionary_summary_provider=self.active_pronunciation_dictionary_summary,parent=self)
        dialog.voice_selected.connect(self.apply_selected_voice)
        dialog.model_selected.connect(self.apply_selected_model)
        dialog.settings_updated.connect(self.apply_voice_browser_settings)
        dialog.catalog_refreshed.connect(self.voice_catalog_refreshed)
        dialog.show()
        self.voice_browser_dialog=dialog
    def voice_catalog_refreshed(self,catalog):
        tier=catalog.account.tier if catalog.account else 'unknown tier'
        remaining=catalog.account.remaining_characters if catalog.account else None
        quota=f', {remaining:,} remaining' if remaining is not None else ''
        self.set_provider_status(f"Connected: {tier}, {len(catalog.voices)} voices, {sum(1 for model in catalog.models if model.can_do_text_to_speech)} TTS models{quota}")
        self.populate_model_dropdown(catalog.models)
    def apply_selected_voice(self,voice_id,voice_name):
        self.voice.setText(voice_id); self.settings_changed(); self.statusBar().showMessage(f'Voice selected: {voice_name}',5000)
    def apply_selected_model(self,model_id):
        self.set_model_value(model_id); self.settings_changed(); self.statusBar().showMessage(f'Model selected: {model_id}',5000)
    def apply_voice_browser_settings(self,s):
        with self.settings_controller.loading():
            self.set_model_value(s.model_id); self.set_language_value(s.language_code); self.stability.setValue(int(s.stability*100)); self.similarity.setValue(int(s.similarity_boost*100)); self.style.setValue(int(s.style*100)); self.speed.setValue(s.speed); self.boost.setChecked(s.use_speaker_boost)
        self.settings_changed()
    def current_model_id(self):
        return str(self.model.currentData() or self.model.currentText() or 'eleven_multilingual_v2')
    def current_language_code(self):
        return self.language.currentData() if hasattr(self,'language') else 'da'
    def populate_language_dropdown(self,languages=None):
        current=self.current_language_code() if hasattr(self,'language') else 'da'; self.language.blockSignals(True); self.language.clear()
        defaults=[('Auto',None),('Danish (da)','da'),('English (en)','en'),('German (de)','de'),('Swedish (sv)','sv'),('Norwegian (no)','no'),('Turkish (tr)','tr'),('Persian (fa)','fa')]
        seen=set()
        for label,code in defaults:
            self.language.addItem(label,code); seen.add(code)
        for code in languages or []:
            if code and code not in seen:
                self.language.addItem(str(code),str(code)); seen.add(str(code))
        index=self.language.findData(current)
        self.language.setCurrentIndex(index if index>=0 else 0)
        self.language.blockSignals(False)
    def set_language_value(self,language_code):
        index=self.language.findData(language_code)
        if index<0 and language_code:
            self.language.addItem(str(language_code),str(language_code)); index=self.language.findData(language_code)
        self.language.setCurrentIndex(index if index>=0 else 0)
    def set_model_value(self,model_id):
        index=self.model.findData(model_id)
        if index<0:
            self.model.addItem(str(model_id),str(model_id)); index=self.model.findData(model_id)
        self.model.setCurrentIndex(index)
    def set_combo_data(self,combo,value):
        if combo is None: return
        index=combo.findData(value)
        if index>=0: combo.setCurrentIndex(index)
    def model_changed(self):
        self.settings_changed(); self.refresh_compatible_voice_state()
        dialog=getattr(self,'voice_browser_dialog',None)
        if dialog:
            dialog._load_cached(); dialog.apply_filters()
    def refresh_compatible_voice_state(self):
        cached=self.context.voice_service.cached_catalog(self.settings())
        model_id=self.current_model_id(); voice_id=self.voice.text().strip()
        if cached:
            languages=[]
            for model in cached.models:
                if model.model_id==model_id:
                    languages=list(model.languages); break
            if languages: self.populate_language_dropdown(languages)
            if voice_id:
                voice=next((item for item in cached.voices if item.voice_id==voice_id),None)
                if voice and voice.compatible_model_ids and model_id not in voice.compatible_model_ids:
                    self.voice.clear(); self.statusBar().showMessage('Selected voice is not compatible with this model. Choose another voice.',8000)
        else:
            self.statusBar().showMessage('Model changed. Voice compatibility will refresh when catalog data is available.',5000)
    def populate_model_dropdown(self,models):
        current=self.current_model_id(); self.model.blockSignals(True); self.model.clear()
        if models:
            for model in models:
                if getattr(model,'can_do_text_to_speech',True): self.model.addItem(model.name,model.model_id)
        if self.model.count()==0:
            self.model.addItem('Eleven Multilingual v2','eleven_multilingual_v2'); self.model.addItem('Mock / local default','piper-local')
        self.model.blockSignals(False); self.set_model_value(current); self.refresh_compatible_voice_state()
    def refresh_models(self):
        provider_id=self.provider.currentText()
        if provider_id=='openai':
            from app.providers.openai_speech import OPENAI_SPEECH_MODELS
            self.model.blockSignals(True); self.model.clear()
            for model in OPENAI_SPEECH_MODELS: self.model.addItem(model,model)
            self.model.blockSignals(False); self.set_model_value(self.current_model_id()); self.statusBar().showMessage('OpenAI Speech models loaded from supported API configuration.',5000); return
        if provider_id in {'azure','google','aws_polly','kokoro'}:
            self.model.blockSignals(True); self.model.clear(); self.model.addItem('Configured by provider setup',''); self.model.blockSignals(False); self.statusBar().showMessage('Provider model list is available after setup/connection.',5000); return
        cached=self.context.voice_service.cached_catalog(self.settings())
        if cached: self.populate_model_dropdown(cached.models); self.statusBar().showMessage('Models refreshed from cache.',5000)
        else: self.statusBar().showMessage('No cached models yet. Open Voice Browser or test connection to refresh.',7000)
    def pick_csv(self):
        p,_=QFileDialog.getOpenFileName(self,'CSV',str(self.project_controller.last_csv_dir),'CSV (*.csv)')
        if p: self.csv.setText(p); self.project_controller.update_csv_path(Path(p)); self.update_window_title(); self.invalidate_preflight(); self.load_csv(); self.update_status_bar()
    def pick_out(self):
        p=QFileDialog.getExistingDirectory(self,'Output',str(self.project_controller.last_output_dir))
        if p: self.out.setText(p); self.project_controller.update_output_path(Path(p)); self.update_window_title(); self.invalidate_preflight(); self.update_status_bar()
    def pick_piper(self):
        p,_=QFileDialog.getOpenFileName(self,'Piper model','','ONNX (*.onnx)')
        if p: self.piper.setText(p)
    def reload_csv(self): self.load_csv(update_project=True, source='Reloaded')
    def load_csv(self,update_project=True,source='Loaded'):
        try:
            if update_project and self.project_controller.current_project: self.project_controller.update_csv_path(Path(self.csv.text())); self.update_window_title()
            project_id=self.project_controller.current_project.project_id if self.project_controller.current_project else None
            if self.offer_repaired_csv_switch(Path(self.csv.text())): return
            import_state=diagnose_csv(Path(self.csv.text()))
            if import_state.rejected_rows:
                dialog=CsvImportReviewDialog(import_state,export_diagnostics=lambda:self.export_import_diagnostics(import_state),generate_repaired_preview=lambda:self.generate_import_repair_preview(import_state),open_source_folder=lambda:self.context.desktop_service.open_path(import_state.source_path.parent),save_repaired_csv=self.replace_project_csv_with_repaired,reports_dir=self.context.container.runtime.reports_dir,project_name=self.project_controller.project_name,parent=self)
                if dialog.exec()!=QDialog.Accepted or not dialog.import_valid_rows:
                    self.log.appendPlainText(f'CSV import cancelled: {import_state.rejected_rows:,} rejected row(s).'); self.dashboard(); self.update_status_bar(); return
                jobs=import_state.jobs
            else:
                jobs=load_jobs(Path(self.csv.text()))
            self.last_import_state=import_state
            self.generation_controller.set_jobs(jobs,project_id=project_id,output_dir=Path(self.out.text() or self.project_controller.default_output_path),settings=self.settings()); self.reset_row_range_controls()
            self.render_queue(); self.refresh_monitor_queue(); self.invalidate_preflight()
            self.log.appendPlainText(f'{source} {len(self.generation_controller.jobs):,} CSV rows.'); self.dashboard(); self.update_status_bar()
        except Exception as e: self.log.appendPlainText(f'CSV load failed: {e}'); self.dashboard(); self.update_status_bar()
    def export_import_diagnostics(self,state):
        report=write_import_report(state,self.context.container.runtime.reports_dir,self.project_controller.project_name); self.context.desktop_service.open_path(report); return report
    def generate_import_repair_preview(self,state):
        paths=generate_repaired_preview(state); self.context.desktop_service.open_path(paths[0].parent); return paths
    def replace_project_csv_with_repaired(self,path):
        self.csv.setText(str(path)); self.project_controller.update_csv_path(Path(path)); self.update_window_title(); self.load_csv(update_project=False,source='Loaded repaired'); self.run_preflight(write_report=True); self.project_controller.autosave_if_needed(generation_active=self.generation_controller.is_active); self.update_status_bar()
    def offer_repaired_csv_switch(self,path):
        if path.name.endswith('.repaired.csv'): return False
        repaired=path.with_name(f'{path.stem}.repaired.csv')
        if not repaired.exists(): return False
        if getattr(self,'_offered_repaired_csv',None)==str(repaired): return False
        self._offered_repaired_csv=str(repaired)
        try:
            state=diagnose_csv(repaired)
        except Exception:
            return False
        if state.valid_rows==4212 and state.rejected_rows==0:
            message=f'A validated repaired CSV is available:\n{repaired}\n\nUse it as the current project CSV source?\n\nResult: {state.valid_rows:,} valid / {state.rejected_rows:,} rejected.'
        else:
            message=f'A repaired CSV is available:\n{repaired}\n\nUse it as the current project CSV source?\n\nResult: {state.valid_rows:,} valid / {state.rejected_rows:,} rejected.'
        if self.notifications.confirmation('Use repaired CSV?',message):
            self.replace_project_csv_with_repaired(repaired); return True
        return False
    def settings_values(self): return SettingsViewData(provider=self.provider.currentText(),api_key=self.key.text(),voice_id=self.voice.text(),model_id=self.current_model_id(),language_code=self.current_language_code(),piper_model_path=self.piper.text() or None,stability=self.stability.value()/100,similarity_boost=self.similarity.value()/100,style=self.style.value()/100,speed=self.speed.value(),short_text_pronunciation_aid=self.pronunciation_aid.isChecked(),delay_seconds=self.delay.value(),max_retries=self.retries.value(),use_speaker_boost=self.boost.isChecked(),skip_existing=self.skip.isChecked(),active_api_profile_id=self.active_api_profile_id(),api_profile_failover=self.current_failover_mode(),generation_scope=self.current_scope_mode(),execution_order=self.current_execution_order(),pronunciation_dictionary_locators=self.active_pronunciation_locators(),active_pronunciation_dictionary_id=self.active_pronunciation_dictionary_id(),job_pronunciation_overrides=self.job_pronunciation_overrides)
    def settings(self): return self.settings_controller.from_view_data(self.settings_values())
    def settings_changed(self):
        s=self.settings()
        if self.settings_controller.settings_changed(s):
            if getattr(self,'_last_connection_key',None) != s.api_key: self.context.voice_service.invalidate_provider_cache()
            self.save_global_preferences(s); self.project_controller.update_settings(s); self.invalidate_preflight(); self.update_window_title(); self.set_provider_status('Not tested'); self.dashboard()
    def set_provider_status(self,text):
        if not hasattr(self,'connection_status'): return
        self.connection_status.setToolTip(text)
        lowered=text.lower()
        if any(token in lowered for token in ['invalid','error','unavailable','missing','failed']):
            self.connection_status.setIcon(action_icon('general.error'))
        elif any(token in lowered for token in ['quota','unknown','warning','exhausted']):
            self.connection_status.setIcon(action_icon('general.warning'))
        elif 'connected' in lowered or 'ready' in lowered:
            self.connection_status.setIcon(action_icon('general.success'))
        else:
            self.connection_status.setIcon(action_icon('general.info'))
        concise = text.strip() or 'Not tested'
        if len(concise) > 54:
            concise = elide_middle(concise,54)
        self.connection_status.setText(concise)
        self.connection_status.setAccessibleName(f'Provider connection status: {text}')
    def open_account_details(self):
        profile_id=self.active_api_profile_id() if hasattr(self,'api_profile') else None
        profile=None
        if profile_id:
            try: profile=self.context.api_profile_service.get_profile(str(profile_id))
            except ValueError: profile=None
        catalog=self.context.voice_service.cached_catalog(self.settings())
        account=catalog.account if catalog else None
        lines=[
            f"Profile: {profile.display_name if profile else 'Temporary key / no profile'}",
            f"Provider: {self.provider_display_name(self.provider.currentText())}",
            f"Connection: {self.connection_status.toolTip() or self.connection_status.text()}",
            f"Tier: {(profile.account_tier if profile else None) or (account.tier if account else None) or 'Unknown'}",
            f"Confirmed remaining quota: {profile.remaining_characters if profile and profile.remaining_characters is not None else (account.remaining_characters if account and account.remaining_characters is not None else 'Unknown')}",
            f"Last checked: {(profile.last_checked_at if profile else None) or 'Not checked'}",
            f"Voices: {len(catalog.voices) if catalog else 'Unknown'}",
            f"Models: {len(catalog.models) if catalog else 'Unknown'}",
            f"Dictionary capability: {profile.metadata.get('dictionary_crud_available','Unknown') if profile else 'Unknown'}",
            f"Last safe error: {(profile.last_error if profile else None) or 'None'}",
        ]
        QMessageBox.information(self,'Account Details','\n'.join(lines))
    def save_global_preferences(self,s):
        q=QSettings('S Talking','S Talking')
        for key,value in {'provider':s.provider,'voice_id':s.voice_id,'model_id':s.model_id,'language_code':s.language_code,'stability':s.stability,'similarity_boost':s.similarity_boost,'style':s.style,'speed':s.speed,'use_speaker_boost':s.use_speaker_boost,'short_text_pronunciation_aid':s.short_text_pronunciation_aid}.items():
            q.setValue(f'global_settings/{key}',value)
    def load_global_preferences(self,base):
        q=QSettings('S Talking','S Talking'); updates={}
        for key in ['provider','voice_id','model_id','language_code']:
            value=q.value(f'global_settings/{key}',None)
            if value not in (None,''): updates[key]=str(value)
        if updates.get('provider')=='elevenlabs' and not updates.get('voice_id'):
            updates.pop('provider',None)
        for key in ['stability','similarity_boost','style','speed']:
            value=q.value(f'global_settings/{key}',None)
            if value is not None:
                try: updates[key]=float(value)
                except (TypeError,ValueError): pass
        boost=q.value('global_settings/use_speaker_boost',None)
        if boost is not None: updates['use_speaker_boost']=str(boost).lower() in {'1','true','yes'}
        aid=q.value('global_settings/short_text_pronunciation_aid',None)
        if aid is not None: updates['short_text_pronunciation_aid']=str(aid).lower() in {'1','true','yes'}
        return base.model_copy(update=updates)
    def test_elevenlabs_connection(self):
        settings=self.settings()
        if settings.provider!='elevenlabs':
            result=self.context.provider_catalog_service.card_for(settings.provider,settings); self.set_provider_status(f'{result.setup_state}: {result.message}'); return
        self.test_connection_button.setEnabled(False); self.set_provider_status('Testing...')
        self._connection_thread,self._connection_worker=start_connection_test(self,self.context.voice_service,settings,self.connection_test_finished)
    def connection_test_finished(self,result):
        self.test_connection_button.setEnabled(self.provider.currentText()=='elevenlabs'); self._last_connection_key=self.key.text()
        cap=result.capability
        if cap:
            remaining=f", {cap.remaining_characters:,} remaining" if cap.remaining_characters is not None else ""
            self.set_provider_status(f"{result.status.replace('_',' ').title()}: {cap.account_tier or 'unknown tier'}, {cap.voice_count} voices, {cap.tts_model_count} TTS models{remaining}")
            dialog=getattr(self,'voice_browser_dialog',None)
            if dialog: dialog._load_cached()
        else:
            self.set_provider_status(f"{result.status.replace('_',' ').title()}: {result.message}")
        self.invalidate_preflight(); self.dashboard()
    def reset_row_range_controls(self):
        rows=[job.row_number for job in self.generation_controller.jobs]
        self.range_from.blockSignals(True); self.range_to.blockSignals(True)
        if rows:
            self.range_from.setRange(0,max(rows)); self.range_to.setRange(0,max(rows)); self.range_from.setValue(0); self.range_to.setValue(0)
        self.range_from.blockSignals(False); self.range_to.blockSignals(False); self.apply_row_range()
    def apply_row_range(self):
        start=self.range_from.value() or None; end=self.range_to.value() or None
        basis=str(self.range_basis.currentData()) if hasattr(self,'range_basis') else 'row_range'
        if (start is not None or end is not None) and hasattr(self,'scope_selector'): self.set_combo_data(self.scope_selector,basis)
        if basis=='display_range':
            self.generation_controller.set_display_range(start,end)
            jobs=self.generation_controller.generation_plan().jobs
            chars=sum(job.character_count for job in jobs)
            self.range_summary_label.setText(f"Range basis: Current displayed order · Positions {start or 1} → {end or 'last'} · {len(jobs):,} jobs · {chars:,} characters")
        else:
            self.generation_controller.set_row_range(start,end)
            s,e,count=self.generation_controller.range_summary()
            jobs=self.generation_controller.generation_plan().jobs
            chars=sum(job.character_count for job in jobs)
            self.range_summary_label.setText(f"Range basis: Original source row · Rows {s or 'first'} → {e or 'last'} · {count:,} jobs · {chars:,} characters")
        self.render_queue(); self.refresh_monitor_queue(); self.dashboard(); self.invalidate_preflight()
    def selected_row_numbers(self):
        return [job.row_number for job in self.selected_queue_jobs()]
    def restore_defaults(self):
        with self.settings_controller.loading():
            self.provider.setCurrentText('mock'); self.set_model_value('eleven_multilingual_v2'); self.set_language_value('da'); self.failover.setCurrentIndex(self.failover.findData('never')); self.scope_selector.setCurrentIndex(self.scope_selector.findData('entire_queue')); self.order_selector.setCurrentIndex(self.order_selector.findData('csv')); self.stability.setValue(45); self.similarity.setValue(75); self.style.setValue(20); self.speed.setValue(1); self.delay.setValue(.5); self.retries.setValue(4); self.boost.setChecked(True); self.pronunciation_aid.setChecked(True); self.skip.setChecked(True); self.apply_theme('Dark')
        self.settings_changed(); self.statusBar().showMessage('Defaults restored without changing API key, project, or queue.',6000)
    def save_settings(self): self.settings_controller.save_global_settings(self.settings()); self.log.appendPlainText('Settings saved.')
    def load_saved(self):
        s=self.settings_controller.load_global_settings()
        s=self.load_global_preferences(s or AppSettings(provider='mock'))
        if s:
            with self.settings_controller.loading():
                self.provider.setCurrentText(s.provider); self.key.setText(s.api_key); self.voice.setText(s.voice_id); self.set_model_value(s.model_id); self.set_language_value(s.language_code); self.set_combo_data(self.api_profile,s.active_api_profile_id); self.set_combo_data(self.failover,s.api_profile_failover); self.set_combo_data(self.scope_selector,s.generation_scope); self.set_combo_data(self.order_selector,s.execution_order); self.job_pronunciation_overrides=dict(s.job_pronunciation_overrides); self.piper.setText(s.piper_model_path or ''); self.stability.setValue(int(s.stability*100)); self.similarity.setValue(int(s.similarity_boost*100)); self.style.setValue(int(s.style*100)); self.speed.setValue(s.speed); self.delay.setValue(s.delay_seconds); self.retries.setValue(s.max_retries); self.boost.setChecked(s.use_speaker_boost); self.pronunciation_aid.setChecked(s.short_text_pronunciation_aid); self.skip.setChecked(s.skip_existing)
        if hasattr(self,'api_profile') and self.api_profile.currentData() is None:
            active=self.context.api_profile_service.active_profile('elevenlabs')
            if active:
                self.set_combo_data(self.api_profile,active.profile_id)
                secret=self.context.api_profile_service.api_key_for(active.profile_id)
                if secret is not None: self.key.setText(secret)
    def apply_project_state(self,s):
        with self.settings_controller.loading():
            self.apply_project_paths(s); self.apply_provider_settings(s); self.apply_project_metadata(s)
        self.project_sources=self.context.source_repository.list_by_project(s.project_id) if s.project_id else []; self.render_project_sources()
        self.refresh_project_title(); self.show_path_warnings(); self.update_reload_state(); self.dashboard(); self.update_status_bar()
    def apply_project_paths(self,s):
        self.project_path=s.project_file; self.csv.setText(str(s.csv_path or '')); self.out.setText(str(s.output_path or self.project_controller.default_output_path))
    def apply_provider_settings(self,s):
        self.provider.setCurrentText(s.provider); self.key.setText(s.settings.api_key); self.voice.setText(s.settings.voice_id); self.set_model_value(s.settings.model_id); self.set_language_value(s.settings.language_code); self.set_combo_data(self.api_profile,s.settings.active_api_profile_id); self.set_combo_data(self.failover,s.settings.api_profile_failover); self.set_combo_data(self.scope_selector,s.settings.generation_scope); self.set_combo_data(self.order_selector,s.settings.execution_order); self.job_pronunciation_overrides=dict(s.settings.job_pronunciation_overrides); self.piper.setText(s.settings.piper_model_path or ''); self.stability.setValue(int(s.settings.stability*100)); self.similarity.setValue(int(s.settings.similarity_boost*100)); self.style.setValue(int(s.settings.style*100)); self.speed.setValue(s.settings.speed); self.delay.setValue(s.settings.delay_seconds); self.retries.setValue(s.settings.max_retries); self.boost.setChecked(s.settings.use_speaker_boost); self.pronunciation_aid.setChecked(s.settings.short_text_pronunciation_aid); self.skip.setChecked(s.settings.skip_existing)
    def apply_project_metadata(self,s):
        self.project_path=s.project_file
    def refresh_project_title(self): self.update_window_title()
    def show_path_warnings(self):
        v=self.project_controller.validate_current_paths()
        if v.has_missing_paths: self.notifications.warning('Project paths','\n'.join(v.messages()))
    def new_project(self):
        d=NewProjectDialog(self,self.project_controller.last_csv_dir,self.project_controller.last_output_dir)
        if d.exec()!=QDialog.Accepted: return
        name,csv_path,out_path=d.values(); s=self.project_controller.new_project(name,csv_path,out_path,self.settings()); self.apply_project_state(s); self.project_sources=[]; self.render_project_sources(); self.generation_controller.clear_jobs(); self.table.setRowCount(0); self.dashboard(); self.log.appendPlainText('New project.')
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
            else: self.restore_project_queue()
            self.dashboard(); self.update_status_bar()
        except Exception as e: self.notifications.error('Project error',str(e))
    def recent_projects(self):
        d=RecentProjectsDialog(self.project_controller.list_recent_projects(),self)
        if d.exec()==QDialog.Accepted and d.selected_project and d.selected_project.project_file:
            try:
                state=self.project_controller.open_project(Path(d.selected_project.project_file)); self.apply_project_state(state)
                if state.csv_path and state.csv_path.exists(): self.load_csv(update_project=False)
                else: self.restore_project_queue()
            except Exception as e: self.notifications.error('Project error',str(e))
        elif d.removed_project_id: self.project_controller.remove_recent_project(d.removed_project_id)
    def close_project(self):
        self.project_controller.close_project(); self.project_path=None; self.csv.clear(); self.load_saved(); self.generation_controller.clear_jobs(); self.table.setRowCount(0); self.monitor_service.reset(); self.dashboard(); self.update_window_title(); self.log.appendPlainText('Project closed.'); self.update_status_bar()
    def autosave(self):
        try:
            if self.project_controller.autosave_if_needed(generation_active=self.generation_controller.is_active): self.log.appendPlainText('Project auto-saved.'); self.update_window_title(); self.update_status_bar()
        except Exception as e: self.log.appendPlainText(f'Auto-save failed: {e}')
    def invalidate_preflight(self):
        self.preflight_service.invalidate()
        if hasattr(self,'preflight_status'):
            self.preflight_status.setText('Preflight: Not checked'); self.preflight_status.setStyleSheet('color:#94A3B8;font-weight:700;')
            self.startb.setEnabled(not self.generation_controller.is_active)
    def run_preflight(self,write_report=False):
        self.refresh_quota_snapshot()
        state=self.preflight_service.run(jobs=self.generation_controller.generation_jobs(),settings=self.settings(),output_dir=Path(self.out.text() or self.project_controller.default_output_path),csv_path=Path(self.csv.text()) if self.csv.text().strip() else None,project_name=self.project_controller.project_name)
        if write_report: self.preflight_service.write_report(state,self.project_controller.project_name)
        color={'Ready':'#22C55E','Ready with warnings':'#F59E0B','Blocked by errors':'#EF4444','No pending jobs':'#94A3B8','Not checked':'#94A3B8'}[state.status]
        errors=sum(1 for issue in state.issues if issue.severity in {'hard_error','overridable_error','error'} and not (issue.overridable and issue.overridden)); warnings=sum(1 for issue in state.issues if issue.severity=='warning'); pending=len(self.generation_controller.generation_jobs())
        first=next((issue.message for issue in state.issues if issue.severity in {'error','warning'}),'No issues found.')
        self.preflight_status.setText(f'Preflight: {state.status} · {errors} errors · {warnings} warnings'); self.preflight_status.setToolTip(f'Pending files: {pending:,}\nEstimated requests: {pending:,}\n{first}\nClick to view issues.'); self.preflight_status.setStyleSheet(f'color:{color};font-weight:700;')
        self.startb.setEnabled(state.status!='Blocked by errors' and not self.generation_controller.is_active)
        return state
    def show_preflight_dialog(self,state):
        d=PreflightDialog(state,export_report=lambda:self.export_preflight(state),open_output_folder=self.open_output_folder,apply_fixes=lambda:self.fix_preflight_issues(state),parent=self)
        return d.exec()
    def show_latest_preflight(self):
        state=self.preflight_service.latest or self.run_preflight(write_report=False)
        self.show_preflight_dialog(state)
    def export_preflight(self,state):
        report=self.preflight_service.write_report(state,self.project_controller.project_name); self.open_path(report); return report
    def preflight_fix_preview(self,state):
        return self.preflight_service.filename_fix_plan(state,self.generation_controller.jobs,self.settings(),Path(self.out.text() or self.project_controller.default_output_path))
    def fix_preflight_issues(self,state):
        fixes=self.preflight_fix_preview(state)
        if not fixes:
            self.statusBar().showMessage('No automatic filename fixes are available.',5000); return
        if PreflightFixDialog(fixes,self).exec()!=QDialog.Accepted: return
        changed=self.preflight_service.apply_safe_fixes(state,self.generation_controller.jobs,self.settings(),Path(self.out.text() or self.project_controller.default_output_path))
        project_id=self.project_controller.current_project.project_id if self.project_controller.current_project else None
        self.generation_controller.set_jobs(self.generation_controller.jobs,project_id=project_id,output_dir=Path(self.out.text() or self.project_controller.default_output_path),settings=self.settings())
        self.render_queue(); self.preview(); self.refresh_monitor_queue(); self.dashboard(); self.log.appendPlainText(f'Preflight fixed {changed} filename issue(s).'); self.run_preflight(write_report=False)
    def dry_run(self):
        if not self.generation_controller.has_jobs(): self.load_csv()
        state=self.run_preflight(write_report=True); self.show_preflight_dialog(state); self.log.appendPlainText(f'Dry run complete: {state.status}.')
    def start(self):
        if not self.generation_controller.has_jobs():self.load_csv()
        if not self.generation_controller.has_jobs():return
        self.refresh_quota_snapshot()
        s=self.settings(); project=self.project_controller.generation_context(self.out.text())
        state=self.run_preflight(write_report=False)
        confirmation=self.context.generation_confirmation_service.evaluate(state,s)
        if not confirmation.allowed:
            self.show_preflight_dialog(state); return
        if confirmation.requires_user_confirmation and not self.notifications.confirmation(confirmation.title,confirmation.message):
            self.show_preflight_dialog(state); return
        self.generation_started_at=datetime.now(timezone.utc); self.run_logs=[]; self.dashboard()
        if self.generation_controller.start(self,s,project.output_path,project.project_key): self.monitor_service.start_run(self.generation_controller.generation_jobs(),provider=s.provider,output_dir=project.output_path,settings=s); self.set_generation_controls(active=True); self.update_status_bar()
    def pause(self):
        if not self.generation_controller.is_paused:
            if self.generation_controller.pause(): self.pauseb.setText('Resume'); self.monitor_service.pause(); self.dashboard()
        else:
            if self.generation_controller.resume(): self.pauseb.setText('Pause'); self.monitor_service.resume(); self.dashboard()
    def stop(self):
        if self.generation_controller.stop():
            self.stopb.setText('Stopping…')
            self.stopb.setEnabled(False)
            self.pauseb.setEnabled(False)
            self.monitor_service.stop_requested()
            self.statusBar().showMessage('Stopping after the current provider request…')
    def resume_generation(self):
        if self.generation_controller.is_paused: self.pause()
    def open_output_folder(self): self.context.desktop_service.open_path(Path(self.out.text() or self.project_controller.default_output_path))
    def retry_failed(self): self.queue_action('Retry failed',self.generation_controller.retry_failed,success='{count} failed jobs reset to pending.',empty='No failed jobs are eligible to retry.')
    def retry_selected(self): self.queue_action('Retry selected',lambda:self.generation_controller.retry_selected(self.selected_queue_jobs()),success='{count} selected jobs reset to pending.',empty='No selected failed jobs are eligible to retry.')
    def skip_selected(self): self.queue_action('Skip selected',lambda:self.generation_controller.skip_selected(self.selected_queue_jobs()))
    def reset_selected(self): self.queue_action('Reset selected',lambda:self.generation_controller.reset_selected(self.selected_queue_jobs()))
    def clear_completed(self): self.queue_action('Clear completed',self.generation_controller.clear_completed)
    def generate_selected_rows(self):
        rows=self.selected_row_numbers()
        if not rows: return
        self.generation_controller.set_generation_selection(rows); self.dashboard(); self.run_preflight(write_report=False); self.start()
    def generate_selected_row(self):
        rows=self.selected_row_numbers()
        if not rows: return
        self.generation_controller.set_generation_selection([rows[0]]); self.dashboard(); self.run_preflight(write_report=False); self.start()
    def apply_queue_filter(self,text):
        self.generation_controller.set_filter(text); self.render_queue(); self.dashboard(); self.update_status_bar()
    def displayed_queue_jobs(self):
        jobs=self.generation_controller.source_jobs(self.generation_controller.range_jobs())
        jobs=self.generation_controller.queue_service.visible_jobs(jobs,self.generation_controller.status_filter)
        return self.generation_controller.scope_service.order_jobs(jobs,self.generation_controller.scope_service._order(getattr(self.generation_controller,'display_order','csv')))
    def render_queue(self):
        selected_ids={job.row_number for job in self.selected_queue_jobs()} if hasattr(self,'table') and self.table.selectionModel() else set()
        jobs=self.displayed_queue_jobs(); self.table.setRowCount(len(jobs))
        if hasattr(self,'empty_state'):
            self.empty_state.setVisible(not jobs)
            self.table.setVisible(bool(jobs))
        for r,j in enumerate(jobs):
            output_path=self.generation_controller.output_path_for(j,Path(self.out.text() or self.project_controller.default_output_path),self.settings())
            values=[j.source_row or j.row_number,j.filename,j.source_display_name or (Path(self.csv.text()).name if hasattr(self,'csv') and self.csv.text().strip() else '—'),j.source_sheet or '—',f'{j.character_count:,}',j.status.value,j.provider_override or self.provider.currentText(),j.voice_override or self.voice.text() or '—',j.model_override or self.current_model_id() or '—',f'{j.duration_seconds:.2f}s' if j.duration_seconds else '—',j.retry_count,output_path.name]
            for c,v in enumerate(values):
                item=QTableWidgetItem(str(v)); item.setData(Qt.UserRole,j.row_number); item.setToolTip(str(v)); self.table.setItem(r,c,item)
            self.paint(r,j.status.value)
        if selected_ids and self.table.selectionModel():
            self.table.blockSignals(True)
            self.table.clearSelection()
            for row,job in enumerate(jobs):
                if job.row_number in selected_ids:
                    self.table.selectionModel().select(self.table.model().index(row,0),QItemSelectionModel.Select|QItemSelectionModel.Rows)
            self.table.blockSignals(False)
        self.update_queue_summary_strip()
        self.update_selection_scope_summary()
        self.update_queue_actions()
    def update_selection_scope_summary(self):
        if not hasattr(self,'range_summary_label'): return
        if self.current_scope_mode()!='selected': return
        jobs=self.selected_queue_jobs()
        chars=sum(job.character_count for job in jobs)
        self.range_summary_label.setText(f"Range basis: Selection · {len(jobs):,} selected jobs · {chars:,} characters")
    def update_queue_summary_strip(self):
        if not hasattr(self,'cards'): return
        metrics=self.generation_controller.metrics()
        values={'pending':metrics.pending,'running':metrics.running,'completed':metrics.completed,'failed':metrics.failed,'skipped':metrics.skipped}
        for key,value in values.items():
            card=self.cards.get('done' if key=='completed' else key)
            if card: card.value.setText(f'{value:,}'); card.set_active(getattr(card,'filter_text','')==self.queue_filter.currentText())
    def update_quota_scope_label(self,jobs=None):
        if not hasattr(self,'quota_scope_label'): return
        self.refresh_quota_snapshot()
        jobs=jobs if jobs is not None else self.generation_controller.generation_jobs()
        required=sum(len(job.text) for job in jobs if job.status.value in {'pending','running'})
        if self.provider.currentText()!='elevenlabs':
            self.quota_scope_label.setText(f'Requests: {sum(1 for job in jobs if job.status.value in {"pending","running"}):,}')
            self.quota_scope_label.setToolTip('Estimated provider requests for active scope.')
            return
        catalog=self.context.voice_service.cached_catalog(self.settings())
        remaining=catalog.account.remaining_characters if catalog and catalog.account else None
        if remaining is None:
            self.quota_scope_label.setText('Quota unavailable')
            self.quota_scope_label.setToolTip(f'Required: {required:,} characters\nAvailable: unknown\nQuota unavailable')
            return
        shortfall=max(0,required-remaining)
        self.quota_scope_label.setText(f'Required {required:,} / Available {remaining:,}')
        self.quota_scope_label.setToolTip(f'Required: {required:,} characters\nAvailable: {remaining:,} characters\nShortfall: {shortfall:,} characters')
    def refresh_quota_snapshot(self):
        remaining=None
        if self.provider.currentText()=='elevenlabs':
            catalog=self.context.voice_service.cached_catalog(self.settings())
            remaining=catalog.account.remaining_characters if catalog and catalog.account else None
        self.generation_controller.set_quota_remaining(remaining)
    def selected_queue_jobs(self):
        rows=sorted({i.row() for i in self.table.selectionModel().selectedRows()})
        visible=self.displayed_queue_jobs()
        return [visible[row] for row in rows if 0 <= row < len(visible)]
    def queue_action(self,label,command,success=None,empty=None):
        changed=command()
        self.invalidate_preflight(); self.render_queue(); self.refresh_monitor_queue(); self.dashboard(); self.update_status_bar()
        message=(success or f'{label}: {{count}} job(s).').format(count=changed) if changed else (empty or f'{label}: no eligible jobs.')
        self.log.appendPlainText(message); self.statusBar().showMessage(message,5000)
    def open_selected_output(self):
        jobs=self.selected_queue_jobs()
        if not jobs:
            return self.open_output_folder()
        path=self.generation_controller.output_path_for(jobs[0],Path(self.out.text() or self.project_controller.default_output_path),self.settings())
        self.context.desktop_service.open_path(path if path.exists() else path.parent)
    def selected_output_path(self):
        jobs=self.selected_queue_jobs()
        if not jobs: return None
        return self.generation_controller.output_path_for(jobs[0],Path(self.out.text() or self.project_controller.default_output_path),self.settings())
    def play_selected_output(self):
        path=self.selected_output_path()
        if path and path.exists():
            self.audio_player_service.load(path); self.audio_player_service.play(); self.statusBar().showMessage(f'Playing: {path.name}',5000)
        elif path:
            self.statusBar().showMessage(f'Output file missing: {path}',7000)
    def copy_selected_output_path(self):
        path=self.selected_output_path()
        if path: QApplication.clipboard().setText(str(path)); self.statusBar().showMessage(f'Copied: {path}',5000)
    def copy_selected_filename(self):
        jobs=self.selected_queue_jobs()
        if jobs: QApplication.clipboard().setText(jobs[0].filename)
    def copy_selected_text(self):
        jobs=self.selected_queue_jobs()
        if jobs: QApplication.clipboard().setText(jobs[0].text)
    def set_selected_pronunciation_override(self,value):
        jobs=self.selected_queue_jobs()
        for job in jobs:
            job.pronunciation_override=value
            if value is None: self.job_pronunciation_overrides.pop(job.row_number,None)
            else: self.job_pronunciation_overrides[job.row_number]=value
        project_id=self.project_controller.current_project.project_id if self.project_controller.current_project else None
        self.generation_controller.set_jobs(self.generation_controller.jobs,project_id=project_id,output_dir=Path(self.out.text() or self.project_controller.default_output_path),settings=self.settings())
        self.invalidate_preflight(); self.dashboard(); self.statusBar().showMessage('Pronunciation override updated for selected row(s).',5000)
    def select_dictionary_for_selected_jobs(self):
        jobs=self.selected_queue_jobs()
        if not jobs: return
        items=self.context.pronunciation_dictionary_service.list_dictionaries(language_code=self.current_language_code() or 'da')
        labels=[item.name for item in items]
        if not labels:
            self.statusBar().showMessage('No pronunciation dictionaries are available.',5000); return
        label,ok=QInputDialog.getItem(self,'Select dictionary','Dictionary',labels,0,False)
        if ok:
            item=items[labels.index(label)]
            self.set_selected_pronunciation_override(f'dictionary:{item.dictionary_id}')
    def test_selected_pronunciation(self):
        jobs=self.selected_queue_jobs()
        if not jobs: return
        QApplication.clipboard().setText(jobs[0].text); self.open_voice_browser(); self.statusBar().showMessage('Selected row text copied for pronunciation preview.',5000)
    def move_selected_custom(self,command):
        jobs=self.selected_queue_jobs()
        if not jobs: return
        self.generation_controller.move_selected_in_custom_order(jobs,command); self.set_combo_data(self.order_selector,'custom'); self.render_queue(); self.dashboard(); self.invalidate_preflight()
    def latest_completed_output_path(self):
        for job in reversed(self.generation_controller.jobs):
            if job.status.value=='completed':
                path=self.generation_controller.output_path_for(job,Path(self.out.text() or self.project_controller.default_output_path),self.settings())
                if path.exists(): return path
        return None
    def restore_project_queue(self):
        project=self.project_controller.current_project
        if not project: return
        self.generation_controller.restore_project_queue(project.project_id,output_dir=Path(self.out.text() or self.project_controller.default_output_path))
        for job in self.generation_controller.jobs:
            if job.row_number in self.job_pronunciation_overrides: job.pronunciation_override=self.job_pronunciation_overrides[job.row_number]
        self.render_queue(); self.refresh_monitor_queue()
    def queue_context_menu(self,pos):
        menu=QMenu(self); selected=bool(self.selected_queue_jobs())
        output_path=self.selected_output_path(); output_exists=bool(output_path and output_path.exists())
        actions=[('Generate selected row',self.generate_selected_row,selected),('Generate selected rows',self.generate_selected_rows,selected),('Retry selected',self.retry_selected,selected and any(j.status.value=='failed' for j in self.selected_queue_jobs())),('Skip selected',self.skip_selected,selected),('Reset selected',self.reset_selected,selected),('Move to top',lambda:self.move_selected_custom('top'),selected),('Move up',lambda:self.move_selected_custom('up'),selected),('Move down',lambda:self.move_selected_custom('down'),selected),('Move to bottom',lambda:self.move_selected_custom('bottom'),selected),('Use project dictionary',lambda:self.set_selected_pronunciation_override(None),selected),('Disable dictionary for this job',lambda:self.set_selected_pronunciation_override('dictionary_disabled'),selected),('Select dictionary for this job',self.select_dictionary_for_selected_jobs,selected),('Test pronunciation',self.test_selected_pronunciation,selected),('Reveal output',self.open_selected_output,output_exists),('Copy filename',self.copy_selected_filename,selected),('Copy text',self.copy_selected_text,selected),('Open containing folder',self.open_output_folder,True),('Play output',self.play_selected_output,output_exists),('Copy output path',self.copy_selected_output_path,selected)]
        for text,handler,enabled in actions:
            action=menu.addAction(text); action.setEnabled(enabled); action.triggered.connect(handler)
        menu.exec(self.table.viewport().mapToGlobal(pos))
    def update_queue_actions(self):
        selected=self.selected_queue_jobs() if hasattr(self,'table') and self.table.selectionModel() else []
        has_failed=any(j.status.value=='failed' for j in self.generation_controller.jobs)
        selected_failed=any(j.status.value=='failed' for j in selected)
        selected_any=bool(selected)
        completed_visible=any(j.status.value=='completed' for j in self.generation_controller.visible_jobs()) if hasattr(self,'queue_filter') else False
        selected_modifiable=selected_any and all(j.status.value!='running' for j in selected)
        output_exists=selected_any and self.generation_controller.output_path_for(selected[0],Path(self.out.text() or self.project_controller.default_output_path),self.settings()).exists()
        for button,enabled in [(self.retry_failed_button,has_failed),(self.retry_selected_button,selected_failed),(self.skip_selected_button,selected_modifiable),(self.reset_selected_button,selected_modifiable),(self.clear_completed_button,completed_visible),(self.open_output_button,output_exists)]:
            button.setEnabled(enabled and not self.generation_controller.is_active)
        for button,enabled in [(self.retry_menu_button,has_failed or selected_failed),(self.skip_menu_button,selected_modifiable),(self.reset_menu_button,selected_modifiable),(self.output_menu_button,selected_any)]:
            button.setEnabled(enabled and not self.generation_controller.is_active)
        if hasattr(self,'play_output_button'):
            self.play_output_button.setEnabled(output_exists); self.open_selected_button.setEnabled(selected_any); self.copy_output_button.setEnabled(selected_any); self.stop_playback_button.setEnabled(True)
    def progress(self,i,total,name,status,duration,retry,error):
        self.bar.setMaximum(total); self.bar.setValue(i); self.monitor_service.handle_progress(self.generation_controller.jobs,status=status,name=name,duration=duration,retry=retry,error=error); self.render_queue()
        display_name=Path(name).name if name else ''
        line=f'[{i}/{total}] {status}: {display_name}'+(f' — {error}' if error else ''); self.run_logs.append(line); self.log.appendPlainText(line); self.dashboard(); self.update_status_bar()
    def set_generation_controls(self, *, active: bool) -> None:
        self.startb.setEnabled(not active)
        self.pauseb.setEnabled(active)
        self.stopb.setEnabled(active)
        if 'Start Generation' in self.actions_by_name: self.actions_by_name['Start Generation'].setEnabled(not active)
        if 'Pause/Resume' in self.actions_by_name: self.actions_by_name['Pause/Resume'].setEnabled(active)
        if 'Stop Generation' in self.actions_by_name: self.actions_by_name['Stop Generation'].setEnabled(active)
        self.pauseb.setText('Pause')
        self.stopb.setText('Stop')
        self.update_queue_actions()

    def finished(self,s):
        self.monitor_service.finish(s); self.set_generation_controls(active=False); self.dashboard(); self.log.appendPlainText(f'Finished: {json.dumps(s,indent=2)}')
        if self.provider.currentText()=='elevenlabs': self.context.voice_service.invalidate_provider_cache(self.settings()); self.test_elevenlabs_connection()
        report=self.create_report(s); self.context.health_service.invalidate(); self.notify_report_created(report,s); self.update_status_bar()
    def failed(self,e):
        self.monitor_service.finish({'stopped':True}); self.set_generation_controls(active=False); self.dashboard(); self.run_logs.append(f'FAILED: {e}'); report=self.create_report({'total':len(self.generation_controller.generation_jobs()),'completed':0,'skipped':0,'failed':1,'stopped':True,'error':e}); self.notify_report_created(report,{'completed':0,'skipped':0,'failed':1}); self.notifications.error('Error',e); self.update_status_bar()
    def closeEvent(self,event):
        for dialog in list(self.report_dialogs): dialog.close()
        self.audio_player_service.stop()
        self.developer_tools.close()
        self.save_layout_state()
        close_summaries=getattr(self.notifications,'close_summaries',None)
        if callable(close_summaries): close_summaries()
        super().closeEvent(event)
    def keyPressEvent(self,event):
        if event.key()==Qt.Key_K and event.modifiers() & Qt.ControlModifier: self.open_command_palette(); return
        if event.key()==Qt.Key_P and event.modifiers() & Qt.ControlModifier and event.modifiers() & Qt.ShiftModifier: self.open_command_palette(); return
        if event.key()==Qt.Key_F6: self.cycle_major_panel(); return
        super().keyPressEvent(event)
    def dragEnterEvent(self,event:QDragEnterEvent):
        urls=event.mimeData().urls()
        if any(Path(url.toLocalFile()).suffix.lower() in {'.csv','.tsv','.xlsx','.xlsm','.xls','.stproj'} for url in urls): event.acceptProposedAction()
        else: event.ignore()
    def dropEvent(self,event:QDropEvent):
        paths=[Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        projects=[path for path in paths if path.suffix.lower()=='.stproj']
        sources=[path for path in paths if path.suffix.lower() in {'.csv','.tsv','.xlsx','.xlsm','.xls'}]
        if projects:
            try:
                state=self.project_controller.open_project(projects[0]); self.apply_project_state(state); self.restore_project_queue()
            except Exception as e: self.notifications.error('Project error',str(e))
        if sources: self.import_source_paths(sources)
        event.acceptProposedAction()
    def cycle_major_panel(self):
        widgets=[self.provider,self.table,self.ptext,self.log]
        current=self.focusWidget()
        try: index=widgets.index(current)
        except ValueError: index=-1
        widgets[(index+1)%len(widgets)].setFocus()
    def paint(self,r,status):
        it=self.table.item(r,5)
        if it: it.setForeground(QColor(COLORS.get(status,'#E5E7EB')))
    def preview(self):
        rows=self.table.selectionModel().selectedRows()
        if rows:
            selected=self.generation_controller.selected_jobs([rows[0].row()])
            if not selected: return
            j=selected[0]; out=self.generation_controller.output_path_for(j,Path(self.out.text() or self.project_controller.default_output_path),self.settings()); color=COLORS.get(j.status.value,'#94A3B8'); self.pname.setText(j.filename); self.pstatus.setText(j.status.value.title()); self.pstatus.setStyleSheet(f'background:{color};color:white;border-radius:6px;padding:3px 7px;font-weight:700;'); self.pmeta.setText(f'Row {j.row_number} • {len(j.text):,} characters • {self.provider_display_name()} • Voice {self.voice.text() or "—"}'); self.presolved.setText(self.resolved_request_summary(j,out)); self.presolved.setToolTip(self.resolved_request_summary(j,out)); self.poutput.setText(f'Output: {elide_middle(str(out),54)}'); self.poutput.setToolTip(str(out)); self.ptext.setPlainText(j.text)
        else:
            self.pname.setText('No row selected'); self.pstatus.clear(); self.pmeta.setText('Load a CSV and select a row to inspect it.'); self.presolved.setText('Resolved request: —'); self.poutput.clear(); self.ptext.setPlainText('The selected row preview will appear here after a CSV is loaded.')
    def dashboard(self):
        self.refresh_quota_snapshot()
        scoped_jobs=self.generation_controller.generation_jobs(); metrics=self.generation_controller.scoped_metrics()
        self.cards['files'].value.setText(f'{metrics.total:,}'); self.cards['chars'].value.setText(f'{sum(len(job.text) for job in scoped_jobs):,}'); self.cards['pending'].value.setText(f'{metrics.pending:,}'); self.cards['running'].value.setText(f'{metrics.running:,}'); self.cards['done'].value.setText(f'{metrics.completed:,}'); self.cards['failed'].value.setText(f'{metrics.failed:,}'); self.cards['skipped'].value.setText(f'{metrics.skipped:,}'); self.cards['quota'].value.setText('Ready' if self.provider.currentText()!='elevenlabs' else 'Check'); self.cards['eta'].value.setText(f'{metrics.eta_seconds/60:.1f} min')
        current=self.queue_filter.currentText() if hasattr(self,'queue_filter') else ''
        for card in self.cards.values(): card.set_active(bool(getattr(card,'filter_text','')) and card.filter_text==current)
        self.update_source_output_strip()
        self.update_quota_scope_label(scoped_jobs)
        if hasattr(self,'health_button'): self.update_status_bar()
    def create_report(self,summary):
        return self.report_service.create_generation_report(project=self.project_controller.current_project,settings=self.settings(),jobs=list(self.generation_controller.generation_jobs()),output_dir=Path(self.out.text() or self.project_controller.default_output_path),summary=summary,started_at=self.generation_started_at or datetime.now(timezone.utc),log_events=self.run_logs,monitor_metrics=self.monitor_service.report_metrics())
    def show_report_dialog(self,report):
        d=ReportDialog(report,self,open_report=self.open_path,open_folder=self.open_path,copy_path=self.copy_path,export_diagnostics=self.export_diagnostics_for); self.report_dialogs.append(d); d.destroyed.connect(lambda *_: self.report_dialogs.remove(d) if d in self.report_dialogs else None); d.show()
    def notify_report_created(self,report,summary):
        completed=summary.get('completed',0); failed=summary.get('failed',0); skipped=summary.get('skipped',0); stamp=datetime.now().strftime('%H:%M')
        project=self.project_controller.current_project; settings=self.settings(); jobs=list(self.generation_controller.generation_jobs())
        self.context.product_activity_service.notify('success' if failed==0 else 'warning','Batch finished',f'{completed} completed, {failed} failed, {skipped} skipped.',action_label='Open report',action_payload=str(report.report_html))
        self.context.product_activity_service.activity('generation','Batch finished',f'{completed} completed, {failed} failed, {skipped} skipped.',project_id=project.project_id if project else None,metadata={'report':str(report.report_html)})
        self.context.product_activity_service.record_batch(BatchSessionRecord(session_id=f'batch-{datetime.now(timezone.utc).timestamp()}',project_id=project.project_id if project else None,scope=self.current_scope_mode(),provider=settings.provider,model=settings.model_id,voice=settings.voice_id,total_jobs=len(jobs),completed_jobs=completed,failed_jobs=failed,skipped_jobs=skipped,character_count=sum(len(job.text) for job in jobs),report_path=str(report.report_html),output_path=self.out.text(),result='failed' if failed else 'completed',started_at=(self.generation_started_at or datetime.now(timezone.utc)).isoformat(),finished_at=datetime.now(timezone.utc).isoformat()))
        self.latest_report_notification=report
        self.report_button.setText(f'● Report {stamp}: {completed} done / {failed} failed / {skipped} skipped')
        self.report_button.setToolTip(f'Batch finished — View report\n{report.report_html}')
        self.report_button.setVisible(True)
        self.statusBar().showMessage('Batch finished — View report',10000)
    def view_latest_report_dialog(self):
        report=getattr(self,'latest_report_notification',None) or self.report_service.latest_report
        if report: self.show_report_dialog(report)
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
        commands=[
            PaletteCommand('Project: New Project',act('New Project')),
            PaletteCommand('Project: Open Project',act('Open Project')),
            PaletteCommand('Project: Add Source Files',act('Add source files')),
            PaletteCommand('Project: Save Project',act('Save Project'),lambda: self.project_controller.current_project is not None),
            PaletteCommand('Project: Save Project As',act('Save Project As'),lambda: self.project_controller.current_project is not None),
            PaletteCommand('Project: Close Project',act('Close Project'),lambda: self.project_controller.current_project is not None),
            PaletteCommand('Generation: Start Generation',self.start,lambda: bool(self.csv.text().strip()) or self.generation_controller.has_jobs()),
            PaletteCommand('Generation: Dry run',self.dry_run,lambda: bool(self.csv.text().strip()) or self.generation_controller.has_jobs()),
            PaletteCommand('Generation: Pause Generation',self.pause,lambda: self.generation_controller.is_active and not self.generation_controller.is_paused),
            PaletteCommand('Generation: Resume Generation',self.resume_generation,lambda: self.generation_controller.is_active and self.generation_controller.is_paused),
            PaletteCommand('Generation: Stop Generation',self.stop,lambda: self.generation_controller.is_active),
            PaletteCommand('Generation: Retry Failed',self.retry_failed,lambda: any(j.status.value=='failed' for j in self.generation_controller.jobs)),
            PaletteCommand('Generation: Open Output Folder',self.open_output_folder,lambda: Path(self.out.text() or self.project_controller.default_output_path).exists()),
            PaletteCommand('Generation: Show/Hide Generation Monitor',lambda:self.actions_by_name['Show/Hide Generation Monitor'].trigger()),
            PaletteCommand('Voice: Browse and Preview Voices',self.open_voice_browser,lambda: self.voice_browser_button.isEnabled()),
            PaletteCommand('Settings: Provider Accounts',act('Provider accounts')),
            PaletteCommand('Settings: Pronunciation Dictionaries',act('Pronunciation dictionaries')),
            PaletteCommand('Help: Quick Setup',act('Quick Setup')),
            PaletteCommand('Help: Shortcut Reference',act('Shortcut Reference')),
            PaletteCommand('Reports: Open Latest Report',act('Open Latest Report'),lambda: self.report_service.latest_report_dir() is not None),
            PaletteCommand('Reports: Open Reports Folder',act('Open Reports Folder')),
            PaletteCommand('Reports: Export Diagnostics',act('Export Diagnostics')),
            PaletteCommand('Developer: Health Center',act('Health Center')),
            PaletteCommand('Developer: Task Center',act('Task Center')),
            PaletteCommand('Developer: Run All Checks',act('Run all checks')),
            PaletteCommand('Developer: Open Latest Check',lambda: self.context.desktop_service.open_path(self.context.container.runtime.artifacts_dir/'dev-check'/'latest'),lambda: (self.context.container.runtime.artifacts_dir/'dev-check'/'latest').exists()),
            PaletteCommand('Developer: Open Logs',act('Open logs folder')),
            PaletteCommand('Developer: Open Repository',act('Open repository folder')),
            PaletteCommand('Developer: Open in VS Code',act('Open repository in VS Code')),
            PaletteCommand('Developer: Show Runtime Information',act('Show runtime information')),
            PaletteCommand('Developer: Spinbox Visual Test',act('Spinbox visual test')),
        ]
        for source in getattr(self,'project_sources',[]):
            commands.append(PaletteCommand(f'Source: {source.label}',lambda s=source:self.select_source_in_panel(s.source_id)))
        for card in self.context.provider_catalog_service.cards(self.settings()):
            commands.append(PaletteCommand(f'Provider: {card.display_name} ({card.setup_state})',lambda p=card.provider_id:self.provider.setCurrentText(p)))
        for job in self.generation_controller.visible_jobs()[:200]:
            commands.append(PaletteCommand(f'Queue: Row {job.row_number} {job.filename}',lambda r=job.row_number:self.select_queue_row_number(r)))
        latest=self.report_service.latest_report_dir()
        if latest: commands.append(PaletteCommand(f'Report: {latest.name}',lambda:self.open_path(latest)))
        return commands
    def select_source_in_panel(self,source_id):
        for row,source in enumerate(self.project_sources):
            if source.source_id==source_id: self.sources_table.selectRow(row); self.source_filter.setCurrentIndex(self.source_filter.findData(source_id)); return
    def select_queue_row_number(self,row_number):
        for row,job in enumerate(self.generation_controller.visible_jobs()):
            if job.row_number==row_number: self.table.selectRow(row); return
    def open_command_palette(self):
        self.palette=CommandPalette(self.command_palette_commands(),self); self.palette.show(); self.palette.search.setFocus()
    def theme(self): self.apply_theme(self.theme_manager.current())

def main():
    app=QApplication(sys.argv); win=MainWindow(create_application_context()); win.show(); sys.exit(app.exec())
if __name__=='__main__':main()
