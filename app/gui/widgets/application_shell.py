from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.design_system import density_metrics, normalize_density, semantic_tone
from app.gui.icons import action_icon, icon
from app.gui.widgets.output_workspace import OutputPlaybackWorkspace
from app.services.monitor_formatting import elide_middle


class StatusBadge(QLabel):
    """Small semantic badge used across the professional workspace shell."""

    def __init__(self, text: str = "", tone: str = "neutral") -> None:
        super().__init__(text)
        self.setObjectName("workspaceStatusBadge")
        self.setAlignment(Qt.AlignCenter)
        self.setAccessibleName(text or "Status")
        self.set_tone(tone)

    def set_tone(self, tone: object) -> None:
        value = str(getattr(tone, "value", tone) or "neutral")
        self.setProperty("tone", value)
        self.style().unpolish(self)
        self.style().polish(self)

    def update_status(self, text: str, tone: object | None = None) -> None:
        self.setText(text)
        self.setAccessibleName(text or "Status")
        self.setAccessibleDescription(f"Status: {text}")
        self.set_tone(tone if tone is not None else semantic_tone(text))


class MetricPill(QFrame):
    """Compact clickable queue metric with semantic emphasis."""

    clicked = Signal(str)

    def __init__(self, title: str) -> None:
        super().__init__()
        self.metric_key = ""
        self.filter_text = ""
        self.setObjectName("metricPill")
        self.setProperty("tone", "neutral")
        self.setAccessibleName(f"{title}: 0")
        self.setCursor(Qt.PointingHandCursor)
        self.setMaximumHeight(42)
        self.setMinimumHeight(36)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 3, 8, 3)
        layout.setSpacing(6)

        self.icon_label = QLabel("")
        self.icon_label.setObjectName("metricIcon")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedWidth(18)

        text_layout = QVBoxLayout()
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(0)
        caption = QLabel(title)
        caption.setObjectName("metricCaption")
        caption.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)
        self.caption = caption
        self.value = QLabel("0")
        self.value.setObjectName("metricValue")
        self.value.setMinimumWidth(0)
        self.value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        text_layout.addWidget(caption)
        text_layout.addWidget(self.value)

        layout.addWidget(self.icon_label)
        layout.addLayout(text_layout, 1)

    def configure(
        self,
        key: str,
        filter_text: str = "",
        icon_name: str = "general.info",
    ) -> None:
        self.metric_key = key
        self.filter_text = filter_text
        self.icon_label.setPixmap(action_icon(icon_name, size=16).pixmap(16, 16))
        self.setToolTip(
            f"Filter queue by {filter_text.lower()}" if filter_text else "Queue metric"
        )

    def set_active(self, active: bool) -> None:
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def set_value(self, value: object, *, tone: object | None = None) -> None:
        self.value.setText(str(value))
        self.setAccessibleName(f"{self.caption.text()}: {value}")
        self.setAccessibleDescription(self.toolTip() or self.accessibleName())
        if tone is not None:
            semantic = semantic_tone(tone)
            self.setProperty("tone", semantic.value)
            self.style().unpolish(self)
            self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # noqa: ANN001
        if event.button() == Qt.LeftButton and self.filter_text:
            self.clicked.emit(self.filter_text)
            event.accept()
            return
        super().mousePressEvent(event)


class MetricsStrip(QFrame):
    """Own all top-level queue metrics and their click behavior."""

    METRICS = (
        ("files", "Files", "All", "project.open"),
        ("chars", "Characters", "", "general.info"),
        ("pending", "Pending", "Pending", "queue"),
        ("running", "Running", "Running", "generation.start"),
        ("done", "Completed", "Completed", "general.success"),
        ("failed", "Failed", "Failed", "general.error"),
        ("skipped", "Skipped", "Skipped", "generation.skip"),
        ("quota", "Quota", "", "general.quota"),
        ("eta", "ETA", "", "activity"),
    )

    def __init__(self, metric_filter: Callable[[str], None]) -> None:
        super().__init__()
        self.setObjectName("metricsStrip")
        self.setMaximumHeight(42)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.cards: dict[str, MetricPill] = {}

        for key, title, filter_text, icon_name in self.METRICS:
            pill = MetricPill(title)
            pill.configure(key, filter_text, icon_name)
            pill.clicked.connect(metric_filter)
            self.cards[key] = pill
            layout.addWidget(pill)

    def apply_density(self, density: object) -> None:
        compact = normalize_density(density).value == "compact"
        self.layout().setSpacing(2 if compact else 4)
        for card in self.cards.values():
            card.layout().setContentsMargins(6 if compact else 8, 2, 6 if compact else 8, 2)
            card.setMinimumHeight(34 if compact else 38)

    def set_responsive_mode(self, mode: object) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        compact = value == "compact"
        for key, card in self.cards.items():
            card.setVisible(not compact or key not in {"chars", "skipped", "quota"})
        self.setProperty("responsiveMode", value)
        self.style().unpolish(self)
        self.style().polish(self)


class ProjectContextBar(QWidget):
    """Project identity, readiness and source/output controls.

    Public handles from the legacy compact context bar are intentionally kept
    stable so controllers and plugins can migrate independently.
    """

    def __init__(
        self,
        default_output_path,
        *,
        pick_csv: Callable[[], None],
        pick_output: Callable[[], None],
        reload_csv: Callable[[], None],
        update_reload_state: Callable[[], None],
        update_source_output_strip: Callable[[], None],
    ) -> None:
        super().__init__()
        self.setObjectName("workspaceContext")
        self._mode = "expanded"
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.hero = QFrame()
        self.hero.setObjectName("workspaceHero")
        hero_layout = QHBoxLayout(self.hero)
        hero_layout.setContentsMargins(14, 9, 14, 9)
        hero_layout.setSpacing(12)

        identity = QVBoxLayout()
        identity.setContentsMargins(0, 0, 0, 0)
        identity.setSpacing(1)
        self.project_title = QLabel("No project")
        self.project_title.setObjectName("workspaceProjectTitle")
        self.project_subtitle = QLabel("Add sources or open a project to begin")
        self.project_subtitle.setObjectName("workspaceProjectSubtitle")
        self.context_label = QLabel(
            "Project: No project · Source: none · Output: output · "
            "Provider: Mock / Test Provider · Preflight: not checked"
        )
        self.context_label.setObjectName("projectContextBar")
        self.context_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        identity.addWidget(self.project_title)
        identity.addWidget(self.project_subtitle)
        identity.addWidget(self.context_label)
        hero_layout.addLayout(identity, 1)

        badge_layout = QHBoxLayout()
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.setSpacing(6)
        self.provider_badge = StatusBadge("Mock provider", "info")
        self.model_badge = StatusBadge("Model —", "neutral")
        self.preflight_badge = StatusBadge("Preflight not checked", "info")
        badge_layout.addWidget(self.provider_badge)
        badge_layout.addWidget(self.model_badge)
        badge_layout.addWidget(self.preflight_badge)
        hero_layout.addLayout(badge_layout)
        root.addWidget(self.hero)

        self.strip = QFrame()
        self.strip.setObjectName("projectContextStrip")
        self.strip.setMaximumHeight(52)
        self.strip.setMinimumHeight(38)
        layout = QHBoxLayout(self.strip)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        self.csv = QLineEdit()
        self.csv.hide()
        self.output = QLineEdit(str(default_output_path))
        self.output.hide()

        self.source_summary = QLabel("Sources: none")
        self.source_summary.setObjectName("compactSourceSummary")
        self.source_summary.setMinimumWidth(0)
        self.source_summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.source_summary.setToolTip("No source files loaded")

        output_text = elide_middle(str(default_output_path), 48)
        self.output_summary = QLabel(f"Output: {output_text}")
        self.output_summary.setObjectName("compactOutputSummary")
        self.output_summary.setMinimumWidth(0)
        self.output_summary.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.output_summary.setToolTip(str(default_output_path))

        self.browse_csv_button = QPushButton("Add sources")
        self.browse_csv_button.setObjectName("workspaceSecondaryAction")
        self.browse_csv_button.setIcon(icon("open"))
        self.browse_csv_button.setToolTip("Browse CSV, Excel or text sources")
        self.browse_csv_button.setAccessibleName("Add source files")
        self.browse_output_button = QPushButton("Output")
        self.browse_output_button.setObjectName("workspaceSecondaryAction")
        self.browse_output_button.setIcon(icon("folder"))
        self.browse_output_button.setToolTip("Choose output folder")
        self.browse_output_button.setAccessibleName("Choose output folder")
        self.reload_button = QPushButton("Reload")
        self.reload_button.setObjectName("workspaceSecondaryAction")
        self.reload_button.setIcon(icon("refresh"))
        self.reload_button.setEnabled(False)

        self.browse_csv_button.clicked.connect(pick_csv)
        self.browse_output_button.clicked.connect(pick_output)
        self.reload_button.clicked.connect(reload_csv)
        self.csv.textChanged.connect(lambda _text: update_reload_state())
        self.output.textChanged.connect(lambda _text: update_source_output_strip())

        layout.addWidget(self.source_summary, 2)
        layout.addWidget(self.browse_csv_button)
        layout.addWidget(self.reload_button)
        layout.addSpacing(12)
        layout.addWidget(self.output_summary, 2)
        layout.addWidget(self.browse_output_button)
        root.addWidget(self.strip)

    def update_context(
        self,
        *,
        project: str,
        source: str,
        output: str,
        provider: str,
        model: str,
        voice: str,
        preflight: str,
        output_path: str = "",
    ) -> None:
        safe_project = project or "No project"
        self.project_title.setText(safe_project)
        source_label = source if source and source != "none" else "No source loaded"
        voice_label = voice if voice and voice != "—" else "No voice selected"
        self.project_subtitle.setText(f"{source_label} · {voice_label}")
        self.context_label.setText(
            f"Project: {safe_project} · Source: {source or 'none'} · Output: {output or 'output'} · "
            f"Provider: {provider} · Model: {model or '—'} · Voice: {voice or '—'} · "
            f"Preflight: {preflight}"
        )
        self.context_label.setToolTip(f"Output: {output_path}")
        self.provider_badge.update_status(provider, "info")
        self.model_badge.update_status(f"Model {model or '—'}", "neutral")
        self.preflight_badge.update_status(f"Preflight {preflight}")

    def set_preflight_state(self, state: str) -> None:
        self.preflight_badge.update_status(f"Preflight {state}")

    def set_presentation_mode(self, mode: str) -> None:
        self._mode = mode if mode in {"expanded", "compact", "hidden"} else "expanded"
        self.setVisible(self._mode != "hidden")
        self.hero.setVisible(self._mode == "expanded")
        self.context_label.setVisible(self._mode == "expanded")
        self.strip.setVisible(self._mode != "hidden")

    def apply_density(self, density: object) -> None:
        metrics = density_metrics(density)
        self.hero.layout().setContentsMargins(
            metrics.panel_padding,
            7 if metrics.control_height <= 34 else 9,
            metrics.panel_padding,
            7 if metrics.control_height <= 34 else 9,
        )
        self.layout().setSpacing(metrics.section_gap)

    def set_responsive_mode(self, mode: object) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        self.setProperty("responsiveMode", value)
        compact = value == "compact"
        self.project_subtitle.setVisible(not compact)
        self.context_label.setVisible(self._mode == "expanded" and not compact)
        self.model_badge.setVisible(not compact)
        self.browse_csv_button.setText("Sources" if compact else "Add sources")
        self.browse_output_button.setText("Output")
        self.reload_button.setText("Reload")
        self.style().unpolish(self)
        self.style().polish(self)


class ActivityCenter(QTabWidget):
    """Collapsible activity/output/error workspace independent from MainWindow."""

    COLLAPSED_MAX_HEIGHT = 34
    COLLAPSED_MIN_HEIGHT = 30

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("activityTabs")
        self.expanded_height = 320

        self.activity_log = QPlainTextEdit()
        self.activity_log.setReadOnly(True)
        self.output_log = QPlainTextEdit()
        self.output_log.setReadOnly(True)
        self.error_log = QPlainTextEdit()
        self.error_log.setReadOnly(True)

        self.activity_workspace = QTabWidget()
        self.activity_workspace.setObjectName("activityWorkspace")
        self.activity_workspace.addTab(self.activity_log, icon("report"), "Log")

        self.addTab(self.activity_workspace, icon("report"), "Activity")
        self.addTab(self.output_log, icon("folder"), "Output")
        self.addTab(self.error_log, icon("warning"), "Errors")
        self.output_workspace: OutputPlaybackWorkspace | None = None
        self.set_expanded(False)

    def install_timeline(self, timeline: QWidget) -> None:
        if self.activity_workspace.indexOf(timeline) < 0:
            self.activity_workspace.insertTab(0, timeline, icon("activity"), "Timeline")
        self.activity_workspace.setCurrentWidget(timeline)

    def install_output_workspace(
        self,
        service,  # noqa: ANN001
        *,
        open_path=None,  # noqa: ANN001
        jobs_provider=None,  # noqa: ANN001
        output_dir_provider=None,  # noqa: ANN001
        settings_provider=None,  # noqa: ANN001
        output_path_for=None,  # noqa: ANN001
    ) -> OutputPlaybackWorkspace:
        """Upgrade the legacy Output tab while preserving ``output_log``.

        MainWindow and older integrations still append directly to output_log;
        the professional workspace simply reparents that same editor beneath a
        shared audio player and file-handoff controls.
        """

        if self.output_workspace is not None:
            return self.output_workspace
        index = self.indexOf(self.output_log)
        if index < 0:
            index = 1
        else:
            self.removeTab(index)
        workspace = OutputPlaybackWorkspace(
            service,
            self.output_log,
            open_path=open_path,
            jobs_provider=jobs_provider,
            output_dir_provider=output_dir_provider,
            settings_provider=settings_provider,
            output_path_for=output_path_for,
            parent=self,
        )
        self.output_workspace = workspace
        self.insertTab(index, workspace, icon("folder-output"), "Output")
        return workspace

    def show_output_workspace(self) -> None:
        if self.output_workspace is not None:
            self.setCurrentWidget(self.output_workspace)
        else:
            self.setCurrentIndex(1)
        self.expanded_height = max(400, self.expanded_height)
        self.set_expanded(True)

    def set_expanded(self, expanded: bool) -> None:
        self.setMaximumHeight(self.expanded_height if expanded else self.COLLAPSED_MAX_HEIGHT)
        self.setMinimumHeight(96 if expanded else self.COLLAPSED_MIN_HEIGHT)


class GenerationStatusStrip(QFrame):
    """Primary generation command dock with state and progress context."""

    stateChanged = Signal(str, str)

    def __init__(
        self,
        *,
        start: Callable[[], None],
        pause: Callable[[], None],
        stop: Callable[[], None],
        show_preflight: Callable[[], None],
    ) -> None:
        super().__init__()
        self.setObjectName("generationActionBar")
        self.setMaximumHeight(44)
        self.setMinimumHeight(40)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(7)

        self.state_badge = StatusBadge("Ready", "success")
        self.state_badge.setObjectName("generationStateBadge")
        layout.addWidget(self.state_badge)

        self.start_button = QPushButton("Start generation")
        self.start_button.setObjectName("generationPrimaryAction")
        self.start_button.setIcon(icon("start"))
        self.start_button.setAccessibleName("Start generation")
        self.start_button.setAccessibleDescription("Run preflight checks and start the current generation scope")
        self.preflight_button = QPushButton("Preflight: Not checked")
        self.preflight_button.setObjectName("generationPreflightAction")
        self.preflight_button.setAccessibleName("Open latest preflight report")
        self.preflight_button.setProperty("fullText", self.preflight_button.text())
        self.pause_button = QPushButton("Pause")
        self.pause_button.setIcon(icon("pause"))
        self.pause_button.setAccessibleName("Pause or resume generation")
        self.stop_button = QPushButton("Stop")
        self.stop_button.setObjectName("generationStopAction")
        self.stop_button.setIcon(icon("stop"))
        self.stop_button.setAccessibleName("Stop generation")
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        for button in (
            self.start_button,
            self.preflight_button,
            self.pause_button,
            self.stop_button,
        ):
            button.setMinimumHeight(30)
            button.setMaximumHeight(30)
            button.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        self.progress_context = QFrame()
        self.progress_context.setObjectName("generationProgressContext")
        progress_layout = QVBoxLayout(self.progress_context)
        progress_layout.setContentsMargins(8, 0, 8, 0)
        progress_layout.setSpacing(1)
        self.progress_label = QLabel("Queue is ready")
        self.progress_label.setObjectName("generationProgressLabel")
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(320)
        self.progress_bar.setMinimumWidth(180)
        self.progress_bar.setTextVisible(True)
        progress_layout.addWidget(self.progress_label)
        progress_layout.addWidget(self.progress_bar)

        self.start_button.clicked.connect(start)
        self.pause_button.clicked.connect(pause)
        self.stop_button.clicked.connect(stop)
        self.preflight_button.clicked.connect(show_preflight)

        layout.addWidget(self.start_button, 0, Qt.AlignVCenter)
        layout.addWidget(self.preflight_button, 0, Qt.AlignVCenter)
        layout.addWidget(self.pause_button, 0, Qt.AlignVCenter)
        layout.addWidget(self.stop_button, 0, Qt.AlignVCenter)
        layout.addStretch(1)
        layout.addWidget(self.progress_context)

    def set_generation_state(self, state: str, detail: str = "") -> None:
        self.state_badge.update_status(state)
        if detail:
            self.progress_label.setText(detail)
        self.stateChanged.emit(state, detail)

    def set_progress_detail(
        self,
        current: int,
        total: int,
        *,
        status: str = "",
        filename: str = "",
    ) -> None:
        self.progress_bar.setMaximum(max(0, total))
        self.progress_bar.setValue(max(0, current))
        progress = f"{current:,} of {total:,}" if total else "No queued jobs"
        display_status = status.replace("_", " ").title() if status else ""
        suffix = " · ".join(part for part in (display_status, filename) if part)
        self.progress_label.setText(f"{progress}{' · ' + suffix if suffix else ''}")
        if display_status:
            self.state_badge.update_status(display_status)
            self.stateChanged.emit(display_status, self.progress_label.text())

    def apply_density(self, density: object) -> None:
        metrics = density_metrics(density)
        compact = metrics.control_height <= 34
        # The command dock is a single application-shell row. Professional
        # hierarchy comes from semantic styling and layout, not excess height.
        self.setMaximumHeight(40 if compact else 44)
        self.setMinimumHeight(38 if compact else 40)
        self.layout().setContentsMargins(6 if compact else 8, 3, 6 if compact else 8, 3)
        self.layout().setSpacing(5 if compact else 7)

    def set_responsive_mode(self, mode: object) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        compact = value == "compact"
        self._responsive_mode = value
        self.setProperty("responsiveMode", value)
        self.start_button.setText("Start" if compact else "Start generation")
        if compact:
            self.progress_bar.setMinimumWidth(100)
            self.progress_bar.setMaximumWidth(190)
            self.progress_label.setVisible(False)
        else:
            self.progress_bar.setMinimumWidth(180)
            self.progress_bar.setMaximumWidth(320)
            self.progress_label.setVisible(True)
        self.refresh_preflight_label()
        self.style().unpolish(self)
        self.style().polish(self)

    def set_preflight_text(self, text: str) -> None:
        self.preflight_button.setProperty("fullText", str(text))
        self.refresh_preflight_label()

    def refresh_preflight_label(self) -> None:
        full_text = str(self.preflight_button.property("fullText") or "Preflight: Not checked")
        compact = getattr(self, "_responsive_mode", "standard") == "compact"
        self.preflight_button.setText("Preflight" if compact else full_text)
        self.preflight_button.setToolTip(full_text)


class ApplicationShell(QWidget):
    """Top-level central widget. MainWindow orchestrates; the shell owns layout."""

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("applicationShell")
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(10, 8, 10, 8)
        self.root_layout.setSpacing(8)
        self.header_context: QWidget | None = None
        self.header_metrics: QWidget | None = None
        self.workspace: QWidget | None = None
        self.activity: QWidget | None = None
        self.status: QWidget | None = None

    def add_header(self, context: QWidget, metrics: QWidget) -> None:
        self.header_context = context
        self.header_metrics = metrics
        self.root_layout.addWidget(context)
        self.root_layout.addWidget(metrics)

    def add_workspace(self, workspace: QWidget) -> None:
        self.workspace = workspace
        self.root_layout.addWidget(workspace, 1)

    def add_footer(self, activity: QWidget, status: QWidget) -> None:
        self.activity = activity
        self.status = status
        self.root_layout.addWidget(activity)
        self.root_layout.addWidget(status)

    def apply_density(self, density: object) -> None:
        metrics = density_metrics(density)
        compact = normalize_density(density).value == "compact"
        # Compact is the queue-first workspace. Keep horizontal breathing room,
        # but reclaim six vertical pixels for the queue viewport instead of
        # shrinking the Activity tabs or generation controls.
        vertical_margin = 3 if compact else metrics.shell_margin - 2
        self.root_layout.setContentsMargins(
            metrics.shell_margin,
            vertical_margin,
            metrics.shell_margin,
            vertical_margin,
        )
        self.root_layout.setSpacing(metrics.section_gap)
        for widget in (self.header_context, self.header_metrics, self.status):
            handler = getattr(widget, "apply_density", None)
            if callable(handler):
                handler(density)

    def set_header_mode(self, mode: str, *, metrics_visible: bool = True) -> None:
        handler = getattr(self.header_context, "set_presentation_mode", None)
        if callable(handler):
            handler(mode)
        elif self.header_context is not None:
            self.header_context.setVisible(mode != "hidden")
        if self.header_metrics is not None:
            self.header_metrics.setVisible(metrics_visible and mode != "hidden")

    def set_responsive_mode(self, mode: object) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        self.setProperty("responsiveMode", value)
        for widget in (self.header_context, self.header_metrics, self.status):
            handler = getattr(widget, "set_responsive_mode", None)
            if callable(handler):
                handler(value)
        self.style().unpolish(self)
        self.style().polish(self)
