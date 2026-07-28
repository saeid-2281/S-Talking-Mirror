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

from app.gui.icons import action_icon, icon
from app.services.monitor_formatting import elide_middle


class MetricPill(QFrame):
    """Compact clickable queue metric used by the application shell."""

    clicked = Signal(str)

    def __init__(self, title: str) -> None:
        super().__init__()
        self.metric_key = ""
        self.filter_text = ""
        self.setObjectName("metricPill")
        self.setCursor(Qt.PointingHandCursor)
        self.setMaximumHeight(42)
        self.setMinimumHeight(34)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(7, 2, 7, 2)
        layout.setSpacing(4)

        self.icon_label = QLabel("")
        self.icon_label.setObjectName("metricIcon")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self.icon_label.setFixedWidth(18)

        self.value = QLabel("0")
        self.value.setObjectName("metricValue")
        self.value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.value.setMinimumWidth(0)
        self.value.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)

        caption = QLabel(title)
        caption.setObjectName("metricCaption")
        caption.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Preferred)

        layout.addWidget(self.icon_label)
        layout.addWidget(self.value, 1)
        layout.addWidget(caption)

    def configure(self, key: str, filter_text: str = "", icon_name: str = "general.info") -> None:
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

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton and self.filter_text:
            self.clicked.emit(self.filter_text)
            event.accept()
            return
        super().mousePressEvent(event)


class MetricsStrip(QFrame):
    """Owns all top-level queue metrics and their click behavior."""

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
        layout.setSpacing(2)
        self.cards: dict[str, MetricPill] = {}

        for key, title, filter_text, icon_name in self.METRICS:
            pill = MetricPill(title)
            pill.configure(key, filter_text, icon_name)
            pill.clicked.connect(metric_filter)
            self.cards[key] = pill
            layout.addWidget(pill)


class ProjectContextBar(QWidget):
    """Project identity plus source/output controls with stable public handles."""

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
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        self.context_label = QLabel(
            "Project: No project · Source: none · Output: output · "
            "Provider: Mock / Test Provider · Preflight: not checked"
        )
        self.context_label.setObjectName("projectContextBar")
        self.context_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.context_label)

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

        browse_csv = QPushButton("CSV")
        browse_csv.setIcon(icon("open"))
        browse_csv.setToolTip("Browse CSV")
        browse_output = QPushButton("Output")
        browse_output.setIcon(icon("folder"))
        browse_output.setToolTip("Choose output folder")
        self.reload_button = QPushButton("Reload")
        self.reload_button.setIcon(icon("refresh"))
        self.reload_button.setEnabled(False)

        browse_csv.clicked.connect(pick_csv)
        browse_output.clicked.connect(pick_output)
        self.reload_button.clicked.connect(reload_csv)
        self.csv.textChanged.connect(lambda _text: update_reload_state())
        self.output.textChanged.connect(lambda _text: update_source_output_strip())

        layout.addWidget(self.source_summary, 2)
        layout.addWidget(browse_csv)
        layout.addWidget(self.reload_button)
        layout.addSpacing(12)
        layout.addWidget(self.output_summary, 2)
        layout.addWidget(browse_output)
        root.addWidget(self.strip)


class ActivityCenter(QTabWidget):
    """Collapsible activity/output/error workspace independent from MainWindow."""

    COLLAPSED_MAX_HEIGHT = 34
    COLLAPSED_MIN_HEIGHT = 30

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("activityTabs")
        self.expanded_height = 150

        self.activity_log = QPlainTextEdit()
        self.activity_log.setReadOnly(True)
        self.output_log = QPlainTextEdit()
        self.output_log.setReadOnly(True)
        self.error_log = QPlainTextEdit()
        self.error_log.setReadOnly(True)

        self.addTab(self.activity_log, icon("report"), "Activity")
        self.addTab(self.output_log, icon("folder"), "Output")
        self.addTab(self.error_log, icon("warning"), "Errors")
        self.set_expanded(False)

    def set_expanded(self, expanded: bool) -> None:
        self.setMaximumHeight(self.expanded_height if expanded else self.COLLAPSED_MAX_HEIGHT)
        self.setMinimumHeight(96 if expanded else self.COLLAPSED_MIN_HEIGHT)


class GenerationStatusStrip(QFrame):
    """Primary generation controls and progress, kept outside MainWindow."""

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
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 0)

        self.start_button = QPushButton("Start")
        self.start_button.setIcon(icon("start"))
        self.preflight_button = QPushButton("Preflight: Not checked")
        self.pause_button = QPushButton("Pause")
        self.pause_button.setIcon(icon("pause"))
        self.stop_button = QPushButton("Stop")
        self.stop_button.setIcon(icon("stop"))
        self.pause_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumWidth(280)

        self.start_button.clicked.connect(start)
        self.pause_button.clicked.connect(pause)
        self.stop_button.clicked.connect(stop)
        self.preflight_button.clicked.connect(show_preflight)

        layout.addWidget(self.start_button)
        layout.addWidget(self.preflight_button)
        layout.addWidget(self.pause_button)
        layout.addWidget(self.stop_button)
        layout.addStretch()
        layout.addWidget(self.progress_bar)


class ApplicationShell(QWidget):
    """Top-level central widget. MainWindow orchestrates; the shell owns layout."""

    def __init__(self) -> None:
        super().__init__()
        self.root_layout = QVBoxLayout(self)
        self.root_layout.setContentsMargins(10, 8, 10, 8)
        self.root_layout.setSpacing(8)

    def add_header(self, context: QWidget, metrics: QWidget) -> None:
        self.root_layout.addWidget(context)
        self.root_layout.addWidget(metrics)

    def add_workspace(self, workspace: QWidget) -> None:
        self.root_layout.addWidget(workspace, 1)

    def add_footer(self, activity: QWidget, status: QWidget) -> None:
        self.root_layout.addWidget(activity)
        self.root_layout.addWidget(status)
