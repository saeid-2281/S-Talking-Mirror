from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QTabWidget,
    QToolButton,
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
    """Unified daily command strip plus high-value queue status chips.

    B7 keeps the historical ``MetricsStrip`` API so dashboards and plugins keep
    updating the same cards, but the visual role changes from a second row of
    metrics into the single daily command/status bar.  The native QMainWindow
    toolbar remains available as an action container and shortcut authority; its
    actions are surfaced here instead of being drawn a second time.
    """

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
    DAILY_METRICS = {"files", "running", "done", "failed"}

    def __init__(self, metric_filter: Callable[[str], None]) -> None:
        super().__init__()
        self.setObjectName("metricsStrip")
        self.setProperty("workspaceRole", "daily-command-strip")
        self.setMaximumHeight(42)
        self.setMinimumHeight(38)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        self.cards: dict[str, MetricPill] = {}
        self.action_buttons: dict[str, QToolButton] = {}
        self._status_badges: list[QWidget] = []

        self.command_host = QFrame(self)
        self.command_host.setObjectName("dailyCommandActions")
        self.command_layout = QHBoxLayout(self.command_host)
        self.command_layout.setContentsMargins(0, 0, 0, 0)
        self.command_layout.setSpacing(3)
        layout.addWidget(self.command_host, 0)

        self.status_host = QFrame(self)
        self.status_host.setObjectName("dailyCommandStatus")
        self.status_layout = QHBoxLayout(self.status_host)
        self.status_layout.setContentsMargins(0, 0, 0, 0)
        self.status_layout.setSpacing(4)
        layout.addWidget(self.status_host, 0)

        self.metric_host = QFrame(self)
        self.metric_host.setObjectName("dailyMetricHost")
        metric_layout = QHBoxLayout(self.metric_host)
        metric_layout.setContentsMargins(0, 0, 0, 0)
        metric_layout.setSpacing(4)
        layout.addWidget(self.metric_host, 1)

        for key, title, filter_text, icon_name in self.METRICS:
            pill = MetricPill(title)
            pill.configure(key, filter_text, icon_name)
            pill.clicked.connect(metric_filter)
            self.cards[key] = pill
            metric_layout.addWidget(pill)
            pill.setVisible(key in self.DAILY_METRICS)

        self.more_button = QToolButton(self.command_host)
        self.more_button.setObjectName("dailyCommandMore")
        self.more_button.setText("More")
        self.more_button.setIcon(action_icon("general.more", size=16))
        self.more_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.more_button.setPopupMode(QToolButton.InstantPopup)
        self.more_button.setAccessibleName("More workspace actions")
        self.more_menu = QMenu(self.more_button)
        self.more_button.setMenu(self.more_menu)
        self.more_button.hide()

    def bind_actions(self, primary_actions: list[object], more_actions: list[object]) -> None:
        """Surface existing QAction objects without creating alternate commands."""

        while self.command_layout.count():
            item = self.command_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not self.more_button:
                widget.deleteLater()
        self.action_buttons.clear()
        project_actions = [
            action for action in primary_actions
            if action is not None and str(action.text() or "") in {"New Project", "Open Project", "Save"}
        ]
        if project_actions:
            project_button = QToolButton(self.command_host)
            project_button.setObjectName("dailyProjectMenu")
            project_button.setText("Project")
            project_button.setIcon(action_icon("project.open", size=16))
            project_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            project_button.setPopupMode(QToolButton.InstantPopup)
            project_button.setAccessibleName("Project actions")
            project_menu = QMenu(project_button)
            for action in project_actions:
                project_menu.addAction(action)
                self.action_buttons[str(action.text() or "Action")] = project_button
            project_button.setMenu(project_menu)
            self.command_layout.addWidget(project_button)

        for action in primary_actions:
            if action is None:
                continue
            name = str(action.text() or "Action")
            if name in {"New Project", "Open Project", "Save"}:
                continue
            button = QToolButton(self.command_host)
            button.setDefaultAction(action)
            button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            button.setAutoRaise(False)
            button.setAccessibleName(name)
            if name == "Start Generation":
                button.setObjectName("dailyPrimaryStart")
                button.setText("Start")
            elif name == "Add source files":
                button.setObjectName("dailyAddSources")
                button.setText("Sources")
            else:
                button.setObjectName("dailyCommandAction")
            self.command_layout.addWidget(button)
            self.action_buttons[name] = button

        self.more_menu.clear()
        for action in more_actions:
            if action is not None:
                self.more_menu.addAction(action)
        self.more_button.setVisible(bool(self.more_menu.actions()))
        self.command_layout.addWidget(self.more_button)

    def attach_status_badges(self, *badges: QWidget) -> None:
        """Move the existing provider/model/preflight badges into this strip."""

        for badge in badges:
            if badge is None or badge in self._status_badges:
                continue
            badge.setParent(self.status_host)
            badge.setProperty("dailyStatus", True)
            self.status_layout.addWidget(badge)
            self._status_badges.append(badge)

    def apply_density(self, density: object) -> None:
        compact = normalize_density(density).value == "compact"
        self.layout().setSpacing(2 if compact else 4)
        self.command_layout.setSpacing(2 if compact else 3)
        self.status_layout.setSpacing(2 if compact else 4)
        for card in self.cards.values():
            card.layout().setContentsMargins(5 if compact else 6, 2, 5 if compact else 6, 2)
            card.setMinimumHeight(34 if compact else 36)
        for button in self.action_buttons.values():
            button.setMinimumHeight(32)
            button.setMaximumHeight(34)
        self.more_button.setMinimumHeight(32)
        self.more_button.setMaximumHeight(34)

    def set_metrics_visible(self, visible: bool) -> None:
        """Toggle optional queue metrics without hiding the daily command path."""

        self.metric_host.setVisible(bool(visible))

    def set_responsive_mode(self, mode: object) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        compact = value == "compact"
        wide = value == "wide"
        visible_metrics = {"files", "running", "failed"} if compact else self.DAILY_METRICS
        if wide:
            visible_metrics = self.DAILY_METRICS | {"eta"}
        for key, card in self.cards.items():
            card.setVisible(key in visible_metrics)
        # Keep the primary path visible; trim secondary project chrome first.
        seen_buttons: set[QToolButton] = set()
        for button in self.action_buttons.values():
            if button in seen_buttons:
                continue
            seen_buttons.add(button)
            button.show()
        for index, badge in enumerate(self._status_badges):
            if compact and index == 1:
                badge.hide()
            else:
                badge.show()
        self.setProperty("responsiveMode", value)
        self.style().unpolish(self)
        self.style().polish(self)


class ProjectContextBar(QWidget):
    """Single consolidated project/source/output identity surface for B7.

    The previous workspace rendered a large project hero and a second source /
    output strip immediately below it.  B7 keeps all public handles but nests the
    source/output controls inside the same card, eliminating one full-width band.
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
        root.setSpacing(0)

        self.hero = QFrame()
        self.hero.setObjectName("workspaceHero")
        hero_layout = QVBoxLayout(self.hero)
        hero_layout.setContentsMargins(14, 8, 14, 8)
        hero_layout.setSpacing(5)

        identity_row = QHBoxLayout()
        identity_row.setContentsMargins(0, 0, 0, 0)
        identity_row.setSpacing(10)
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
        self.context_label.hide()
        identity.addWidget(self.project_title)
        identity.addWidget(self.project_subtitle)
        identity.addWidget(self.context_label)
        identity_row.addLayout(identity, 1)

        self.badge_host = QFrame(self.hero)
        self.badge_host.setObjectName("workspaceContextBadges")
        badge_layout = QHBoxLayout(self.badge_host)
        badge_layout.setContentsMargins(0, 0, 0, 0)
        badge_layout.setSpacing(6)
        self.provider_badge = StatusBadge("Mock provider", "info")
        self.model_badge = StatusBadge("Model —", "neutral")
        self.preflight_badge = StatusBadge("Preflight not checked", "info")
        badge_layout.addWidget(self.provider_badge)
        badge_layout.addWidget(self.model_badge)
        badge_layout.addWidget(self.preflight_badge)
        identity_row.addWidget(self.badge_host, 0, Qt.AlignVCenter)
        hero_layout.addLayout(identity_row)

        self.strip = QFrame(self.hero)
        self.strip.setObjectName("projectContextStrip")
        self.strip.setProperty("embedded", True)
        self.strip.setMaximumHeight(44)
        self.strip.setMinimumHeight(34)
        layout = QHBoxLayout(self.strip)
        layout.setContentsMargins(0, 2, 0, 0)
        layout.setSpacing(7)

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
        layout.addSpacing(8)
        layout.addWidget(self.output_summary, 2)
        layout.addWidget(self.browse_output_button)
        hero_layout.addWidget(self.strip)
        root.addWidget(self.hero)

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
        model_label = model or "Default model"
        self.project_subtitle.setText(
            f"{source_label} · {provider or 'Provider not set'} · {voice_label} · {model_label}"
        )
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
        self.project_subtitle.setVisible(self._mode == "expanded")
        self.context_label.hide()
        self.strip.setVisible(self._mode != "hidden")

    def apply_density(self, density: object) -> None:
        metrics = density_metrics(density)
        compact = normalize_density(density).value == "compact"
        self.hero.layout().setContentsMargins(
            metrics.shell_margin,
            5 if compact else 7,
            metrics.shell_margin,
            5 if compact else 7,
        )
        self.hero.layout().setSpacing(3 if compact else 5)
        self.strip.layout().setSpacing(5 if compact else 7)
        self.strip.setMaximumHeight(38 if compact else 44)
        self.strip.setMinimumHeight(32 if compact else 34)

    def set_responsive_mode(self, mode: object) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        compact = value == "compact"
        self.project_subtitle.setVisible(not compact and self._mode == "expanded")
        self.reload_button.setVisible(not compact and self.reload_button.isEnabled())
        self.browse_csv_button.setText("Sources" if compact else "Add sources")
        self.browse_output_button.setText("Output")
        self.setProperty("responsiveMode", value)
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
        self.compact_output_mode = False
        self.compact_output_height = 260

        self.activity_log = QPlainTextEdit()
        self.activity_log.setReadOnly(True)
        self.output_log = QPlainTextEdit()
        self.output_log.setReadOnly(True)
        self.error_log = QPlainTextEdit()
        self.error_log.setReadOnly(True)
        # Long batches can emit tens of thousands of progress lines.  Keeping a
        # bounded visible history prevents QPlainTextEdit layout work from
        # starving the GUI thread while full run evidence remains in reports.
        for editor in (self.activity_log, self.output_log, self.error_log):
            editor.setMaximumBlockCount(2000)

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

    def set_compact_output_mode(self, enabled: bool, *, height: int = 260) -> None:
        self.compact_output_mode = bool(enabled)
        self.compact_output_height = max(210, min(340, int(height)))
        if self.compact_output_mode:
            self.expanded_height = min(self.expanded_height, self.compact_output_height)

    def show_output_workspace(self) -> None:
        if self.output_workspace is not None:
            self.setCurrentWidget(self.output_workspace)
        else:
            self.setCurrentIndex(1)
        if self.compact_output_mode:
            self.expanded_height = self.compact_output_height
        else:
            self.expanded_height = max(560, self.expanded_height)
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

        self.start_button = QPushButton("Start")
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
        self._minimal_daily_mode = False

    def set_minimal_daily_mode(self, enabled: bool = True) -> None:
        """Keep only run-time pause/stop/progress chrome in the secondary strip.

        Start and Preflight live in the B7 unified command strip.  The original
        buttons remain instantiated as stable API handles for controllers,
        shortcuts and historical integrations, but are not rendered twice.
        """

        self._minimal_daily_mode = bool(enabled)
        self.start_button.setVisible(not self._minimal_daily_mode)
        self.preflight_button.setVisible(not self._minimal_daily_mode)
        if self._minimal_daily_mode:
            self.state_badge.setVisible(True)
            self.pause_button.setVisible(self.pause_button.isEnabled())
            # Stop has a stable, always-visible home in daily mode.  It is
            # disabled while idle and enabled before generation starts, so the
            # user never has to hunt for the emergency control under load.
            self.stop_button.setVisible(True)
        else:
            self.pause_button.setVisible(True)
            self.stop_button.setVisible(True)

    def set_runtime_active(self, active: bool) -> None:
        if not self._minimal_daily_mode:
            return
        self.pause_button.setVisible(bool(active))
        self.stop_button.setVisible(True)
        self.progress_context.setVisible(True)

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
        self.start_button.setText("Start")
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


class ProjectPathNotice(QFrame):
    """Non-modal recovery banner for projects whose saved paths moved."""

    locate_source_requested = Signal()
    choose_output_requested = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("projectPathNotice")
        self.setProperty("tone", "warning")
        self._signature: tuple[str, ...] = ()
        self._dismissed_signature: tuple[str, ...] = ()

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        icon_label = QLabel()
        icon_label.setObjectName("projectPathNoticeIcon")
        icon_label.setPixmap(action_icon("general.warning", size=20).pixmap(20, 20))
        icon_label.setAlignment(Qt.AlignTop | Qt.AlignHCenter)
        layout.addWidget(icon_label)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)
        self.title = QLabel("Project needs attention")
        self.title.setObjectName("projectPathNoticeTitle")
        self.message = QLabel("")
        self.message.setObjectName("projectPathNoticeMessage")
        self.message.setWordWrap(True)
        self.message.setTextInteractionFlags(Qt.TextSelectableByMouse)
        text_column.addWidget(self.title)
        text_column.addWidget(self.message)
        layout.addLayout(text_column, 1)

        self.locate_source_button = QPushButton("Locate source")
        self.locate_source_button.setObjectName("projectPathNoticeAction")
        self.locate_source_button.clicked.connect(self.locate_source_requested.emit)
        self.choose_output_button = QPushButton("Choose output")
        self.choose_output_button.setObjectName("projectPathNoticeAction")
        self.choose_output_button.clicked.connect(self.choose_output_requested.emit)
        self.dismiss_button = QPushButton("Dismiss")
        self.dismiss_button.setObjectName("projectPathNoticeDismiss")
        self.dismiss_button.clicked.connect(self._dismiss)

        for button in (
            self.locate_source_button,
            self.choose_output_button,
            self.dismiss_button,
        ):
            button.setMinimumHeight(32)
            layout.addWidget(button)

        self.hide()

    def show_validation(
        self,
        messages: list[str] | tuple[str, ...],
        *,
        missing_csv: bool,
        missing_output: bool,
    ) -> None:
        signature = tuple(str(message).strip() for message in messages if str(message).strip())
        if not signature:
            self.clear()
            return
        if signature != self._signature:
            self._dismissed_signature = ()
        self._signature = signature
        self.message.setText(" · ".join(signature))
        self.locate_source_button.setVisible(bool(missing_csv))
        self.choose_output_button.setVisible(bool(missing_output))
        self.setAccessibleName("Project paths need attention")
        self.setAccessibleDescription(self.message.text())
        self.setVisible(signature != self._dismissed_signature)

    def clear(self) -> None:
        self._signature = ()
        self._dismissed_signature = ()
        self.message.clear()
        self.hide()

    def _dismiss(self) -> None:
        self._dismissed_signature = self._signature
        self.hide()
        self.dismissed.emit()


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
        self.notice: QWidget | None = None
        self.workspace: QWidget | None = None
        self.activity: QWidget | None = None
        self.status: QWidget | None = None

    def add_header(self, context: QWidget, metrics: QWidget) -> None:
        self.header_context = context
        self.header_metrics = metrics
        # B7 command/status strip is the single top-level entry point; the
        # consolidated project/source card follows it as context, not another toolbar.
        self.root_layout.addWidget(metrics)
        self.root_layout.addWidget(context)

    def add_notice(self, notice: QWidget) -> None:
        self.notice = notice
        self.root_layout.addWidget(notice)

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
        for widget in (self.header_context, self.header_metrics, self.notice, self.status):
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
            # B7 daily commands/status are no longer optional metric chrome.
            self.header_metrics.setVisible(True)
            metrics_handler = getattr(self.header_metrics, "set_metrics_visible", None)
            if callable(metrics_handler):
                metrics_handler(metrics_visible)

    def set_responsive_mode(self, mode: object) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        self.setProperty("responsiveMode", value)
        for widget in (self.header_context, self.header_metrics, self.notice, self.status):
            handler = getattr(widget, "set_responsive_mode", None)
            if callable(handler):
                handler(value)
        self.style().unpolish(self)
        self.style().polish(self)
