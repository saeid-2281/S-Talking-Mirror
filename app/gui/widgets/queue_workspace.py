from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtGui import QColor, QKeySequence, QPainter, QPalette, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMenu,
    QStyle,
    QStyleOptionViewItem,
    QStyledItemDelegate,
    QSizePolicy,
    QTableWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


from app.gui.design_system import density_metrics, normalize_density
from app.gui.widgets.queue_table_model import QueueDataRole

DEFAULT_QUEUE_COLUMNS = (
    "Source row",
    "Filename",
    "Source",
    "Worksheet",
    "Characters",
    "Status",
    "Provider",
    "Voice",
    "Model",
    "Duration",
    "Retry",
    "Output",
)


QUEUE_COLUMN_PRESETS: dict[str, tuple[int, ...]] = {
    "Compact": (1, 4, 5, 11),
    "Generation": (1, 4, 5, 6, 7, 9, 11),
    "Review": (0, 1, 2, 3, 4, 5, 10, 11),
    "All columns": tuple(range(len(DEFAULT_QUEUE_COLUMNS))),
}

QUEUE_COLUMN_WIDTHS: dict[str, dict[int, int]] = {
    "Compact": {1: 280, 4: 90, 5: 130, 11: 260},
    "Generation": {1: 240, 4: 90, 5: 150, 6: 120, 7: 160, 9: 90, 11: 220},
    "Review": {0: 86, 1: 240, 2: 140, 3: 110, 4: 90, 5: 130, 10: 72, 11: 220},
}


@dataclass(frozen=True)
class QueueSelectionStats:
    visible_jobs: int
    visible_characters: int
    selected_jobs: int
    selected_characters: int
    scope_label: str


class QueueScopeSummary(QFrame):
    """Compact, always-readable summary for the current queue view and scope."""

    clear_selection_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("queueScopeSummary")
        self.setMaximumHeight(38)
        self.setMinimumHeight(32)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(10)

        self.visible_label = QLabel("Visible: 0 jobs · 0 characters")
        self.visible_label.setObjectName("queueVisibleSummary")
        self.selected_label = QLabel("Selected: 0 jobs · 0 characters")
        self.selected_label.setObjectName("queueSelectedSummary")
        self.scope_label = QLabel("Scope: Entire queue")
        self.scope_label.setObjectName("queueActiveScope")

        layout.addWidget(self.visible_label)
        layout.addWidget(self._separator())
        layout.addWidget(self.selected_label)
        layout.addStretch(1)
        layout.addWidget(self.scope_label)

    @staticmethod
    def _separator() -> QFrame:
        separator = QFrame()
        separator.setObjectName("queueSummarySeparator")
        separator.setFrameShape(QFrame.VLine)
        separator.setFrameShadow(QFrame.Plain)
        return separator

    def update_stats(self, stats: QueueSelectionStats) -> None:
        self.visible_label.setText(
            f"Visible: {stats.visible_jobs:,} jobs · {stats.visible_characters:,} characters"
        )
        self.selected_label.setText(
            f"Selected: {stats.selected_jobs:,} jobs · {stats.selected_characters:,} characters"
        )
        self.scope_label.setText(f"Scope: {stats.scope_label}")
        self.selected_label.setProperty("active", bool(stats.selected_jobs))
        self.selected_label.style().unpolish(self.selected_label)
        self.selected_label.style().polish(self.selected_label)


class QueueStatusDelegate(QStyledItemDelegate):
    """Render queue status as a compact semantic badge.

    The delegate remains data-only: display text comes from the model and an
    optional progress value (0..100) can be supplied through UserRole + 2.
    """

    COLORS = {
        "pending": "#D97706",
        "running": "#2563EB",
        "completed": "#059669",
        "failed": "#DC2626",
        "skipped": "#64748B",
    }

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:  # noqa: ANN001
        status = str(index.data(Qt.DisplayRole) or "").casefold()
        if status not in self.COLORS:
            super().paint(painter, option, index)
            return

        prepared = QStyleOptionViewItem(option)
        self.initStyleOption(prepared, index)
        style = prepared.widget.style() if prepared.widget else None
        if style:
            style.drawPrimitive(QStyle.PE_PanelItemViewItem, prepared, painter, prepared.widget)

        progress = index.data(QueueDataRole.PROGRESS)
        if progress is None:
            progress = index.data(Qt.UserRole + 2)
        value = None
        label = prepared.text.title()
        if status == "running" and isinstance(progress, (int, float)):
            value = max(0.0, min(100.0, float(progress)))
            label = f"Running · {value:.0f}%"

        rect = option.rect.adjusted(8, 6, -8, -6)
        rect.setWidth(min(rect.width(), max(84, prepared.fontMetrics.horizontalAdvance(label) + 24)))
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor(self.COLORS[status])
        background = QColor(color)
        background.setAlpha(38 if not (option.state & QStyle.State_Selected) else 70)
        painter.setPen(Qt.NoPen)
        painter.setBrush(background)
        painter.drawRoundedRect(rect, 7, 7)

        if value is not None:
            fill_width = int(rect.width() * value / 100.0)
            if fill_width > 0:
                fill = rect.adjusted(0, 0, -(rect.width() - fill_width), 0)
                fill_color = QColor(color)
                fill_color.setAlpha(64)
                painter.setBrush(fill_color)
                painter.drawRoundedRect(fill, 7, 7)

        painter.setPen(color.lighter(145) if option.palette.color(QPalette.Base).lightness() < 128 else color.darker(115))
        painter.drawText(rect, Qt.AlignCenter, label)
        painter.restore()


class QueueColumnController:
    """Own queue column visibility and persist it without coupling MainWindow."""

    SETTINGS_KEY = "queue/visible-columns"
    HEADER_STATE_KEY = "queue/header-state"
    PRESET_KEY = "queue/column-preset"

    def __init__(self, table: QTableWidget, settings: QSettings | None = None) -> None:
        self.table = table
        self.settings = settings or QSettings()
        self.menu = QMenu(table)
        self._actions = []
        self.rebuild_menu()
        self.restore()
        header = self.table.horizontalHeader()
        header.sectionResized.connect(lambda *_: self.save_header_state())
        header.sectionMoved.connect(lambda *_: self.save_header_state())

    def _column_count(self) -> int:
        return int(self.table.model().columnCount()) if self.table.model() is not None else 0

    def rebuild_menu(self) -> None:
        self.menu.clear()
        self._actions.clear()
        for column in range(self._column_count()):
            item = self.table.horizontalHeaderItem(column) if hasattr(self.table,"horizontalHeaderItem") else None
            title = item.text() if item else self.table.model().headerData(column,Qt.Horizontal,Qt.DisplayRole)
            title = str(title) if title else f"Column {column + 1}"
            action = self.menu.addAction(title)
            action.setCheckable(True)
            action.setChecked(not self.table.isColumnHidden(column))
            action.toggled.connect(lambda visible, col=column: self.set_visible(col, visible))
            self._actions.append(action)
        self.menu.addSeparator()
        presets_menu = self.menu.addMenu("Column presets")
        active_preset = str(self.settings.value(self.PRESET_KEY, ""))
        for preset_name in QUEUE_COLUMN_PRESETS:
            preset_action = presets_menu.addAction(preset_name)
            preset_action.setCheckable(True)
            preset_action.setChecked(active_preset == preset_name)
            preset_action.triggered.connect(
                lambda _checked=False, name=preset_name: self.apply_preset(name)
            )
        self.menu.addSeparator()
        save_layout = self.menu.addAction("Save current column layout")
        save_layout.triggered.connect(self.save_header_state)
        restore_layout = self.menu.addAction("Restore saved column layout")
        restore_layout.triggered.connect(self.restore_header_state)
        self.menu.addSeparator()
        reset = self.menu.addAction("Restore default columns")
        reset.triggered.connect(self.restore_defaults)

    def set_visible(self, column: int, visible: bool) -> None:
        # Filename and Status are structural and must remain visible.
        if column in {1, 5} and not visible:
            self._actions[column].setChecked(True)
            return
        self.table.setColumnHidden(column, not visible)
        self.settings.remove(self.PRESET_KEY)
        self.save()

    def apply_preset(self, name: str) -> bool:
        """Apply a predictable task-oriented column layout.

        Presets change only presentation. Filename and Status remain visible,
        and the resulting layout is persisted through the same settings keys as
        manual customization.
        """
        columns = QUEUE_COLUMN_PRESETS.get(name)
        if columns is None:
            return False

        visible = set(columns)
        visible.update({1, 5})
        for column in range(self._column_count()):
            self.table.setColumnHidden(column, column not in visible)

        header = self.table.horizontalHeader()
        for logical in range(self._column_count()):
            visual = header.visualIndex(logical)
            if visual != logical:
                header.moveSection(visual, logical)

        for column, width in QUEUE_COLUMN_WIDTHS.get(name, {}).items():
            if column < self._column_count():
                self.table.setColumnWidth(column, width)

        self.settings.setValue(self.PRESET_KEY, name)
        self.save()
        self.rebuild_menu()
        return True

    def save(self) -> None:
        visible = [str(i) for i in range(self._column_count()) if not self.table.isColumnHidden(i)]
        self.settings.setValue(self.SETTINGS_KEY, ",".join(visible))
        self.save_header_state()

    def restore(self) -> None:
        """Restore visibility and header geometry independently.

        Header state may exist even when the user never saved a custom
        visibility set. Returning early in that case silently discarded saved
        widths and visual order, so each persisted component is restored on its
        own.
        """
        raw = self.settings.value(self.SETTINGS_KEY, "")
        if raw:
            visible = {int(value) for value in str(raw).split(",") if value.isdigit()}
            visible.update({1, 5})
            for column in range(self._column_count()):
                self.table.setColumnHidden(column, column not in visible)

        self.restore_header_state()
        self.rebuild_menu()

    def save_header_state(self) -> None:
        self.settings.setValue(self.HEADER_STATE_KEY, self.table.horizontalHeader().saveState())
        self.settings.sync()

    def restore_header_state(self) -> bool:
        state = self.settings.value(self.HEADER_STATE_KEY)
        if state is None:
            return False
        return bool(self.table.horizontalHeader().restoreState(state))

    def restore_defaults(self) -> None:
        for column in range(self._column_count()):
            self.table.setColumnHidden(column, False)
        self.settings.remove(self.SETTINGS_KEY)
        self.settings.remove(self.HEADER_STATE_KEY)
        self.settings.remove(self.PRESET_KEY)
        self.rebuild_menu()


class QueueWorkspace(QFrame):
    """Self-contained visual shell for the queue workspace.

    Business rules remain in controllers/services. This widget owns only queue
    presentation: title, range/command slots, scope summary, table and footer.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("queueWorkspace")

        # H9 Hotfix 5: isolate fixed queue chrome from the expanding work surface.
        #
        # H1-H4 proved that optional QWidgetItems could all be absent while the
        # heading/command geometry still contained 24-50 px of dead vertical space.
        # The root cause is that the same expanding QVBoxLayout owned both fixed
        # chrome and the stretchable body.  Qt may give fixed-height children
        # larger layout cells and center them inside those cells.  Keep the
        # historical ``root_layout`` API for queue chrome, but host it inside a
        # vertically Fixed widget.  The outer shell owns the stretchable body.
        self.shell_layout = QVBoxLayout(self)
        self.shell_layout.setContentsMargins(0, 0, 0, 0)
        self.shell_layout.setSpacing(6)

        self.chrome_host = QWidget(self)
        self.chrome_host.setObjectName("queueChromeHost")
        self.chrome_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.root_layout = QVBoxLayout(self.chrome_host)
        self.root_layout.setContentsMargins(0, 0, 0, 0)
        self.root_layout.setSpacing(6)
        root = self.root_layout

        self.heading = QFrame()
        self.heading.setObjectName("queueWorkspaceHeading")
        heading = self.heading
        heading_layout = QHBoxLayout(heading)
        heading_layout.setContentsMargins(10, 6, 8, 6)
        heading_layout.setSpacing(8)
        self.title_label = QLabel("Generation queue")
        self.title_label.setObjectName("queueWorkspaceTitle")
        self.subtitle_label = QLabel("Filter, order and generate the exact visible scope")
        self.subtitle_label.setObjectName("queueWorkspaceSubtitle")
        heading_layout.addWidget(self.title_label)
        heading_layout.addWidget(self.subtitle_label)
        heading_layout.addStretch(1)
        self.columns_button = QToolButton()
        self.columns_button.setObjectName("queueColumnsButton")
        self.columns_button.setText("Columns")
        self.columns_button.setToolTip("Choose visible queue columns")
        self.columns_button.setAccessibleName("Choose queue columns")
        self.columns_button.setPopupMode(QToolButton.InstantPopup)
        heading_layout.addWidget(self.columns_button)
        root.addWidget(heading)

        self.range_host = QFrame()
        self.range_host.setObjectName("queueRangeBar")
        self.range_layout = QHBoxLayout(self.range_host)
        self.range_layout.setContentsMargins(8, 4, 8, 4)
        self.range_layout.setSpacing(6)
        root.addWidget(self.range_host)

        self.command_host = QFrame()
        self.command_host.setObjectName("queueCommandBar")
        self.command_root_layout = QVBoxLayout(self.command_host)
        self.command_root_layout.setContentsMargins(8, 6, 8, 6)
        self.command_root_layout.setSpacing(6)
        self.command_layout = QHBoxLayout()
        self.command_layout.setContentsMargins(0, 0, 0, 0)
        self.command_layout.setSpacing(6)
        self.planning_host = QFrame()
        self.planning_host.setObjectName("queuePlanningRow")
        self.planning_layout = QHBoxLayout(self.planning_host)
        self.planning_layout.setContentsMargins(0, 0, 0, 0)
        self.planning_layout.setSpacing(6)
        self.action_layout = QHBoxLayout()
        self.action_layout.setContentsMargins(0, 0, 0, 0)
        self.action_layout.setSpacing(6)
        self.command_root_layout.addLayout(self.command_layout)
        self.command_root_layout.addLayout(self.action_layout)
        self.planning_host.hide()
        root.addWidget(self.command_host)

        self.summary = QueueScopeSummary()
        root.addWidget(self.summary)

        # The chrome host is fixed to its content; all spare desktop height is
        # donated to a real expanding body widget below. H6 Hotfix 2 proved the
        # chrome itself was internally compact while its *outer shell cell* could
        # still place the first chrome row roughly 70 px below the queue top on
        # the Windows Qt path. A concrete expanding body widget, explicit stretch
        # ownership and top alignment make that surplus allocation deterministic.
        self.shell_layout.addWidget(self.chrome_host, 0, Qt.AlignTop)

        self.body_host = QWidget(self)
        self.body_host.setObjectName("queueBodyHost")
        self.body_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.body_layout = QVBoxLayout(self.body_host)
        self.body_layout.setContentsMargins(0, 0, 0, 0)
        self.body_layout.setSpacing(4)
        self.shell_layout.addWidget(self.body_host, 1)

        self.footer = QLabel("No jobs loaded")
        self.footer.setObjectName("queueWorkspaceFooter")
        self.footer.setMinimumHeight(26)
        self.footer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.shell_layout.addWidget(self.footer, 0)
        self.shell_layout.setStretch(0, 0)
        self.shell_layout.setStretch(1, 1)
        self.shell_layout.setStretch(2, 0)
        self.shell_layout.setAlignment(self.chrome_host, Qt.AlignTop)

        self.column_controller: QueueColumnController | None = None
        self.bound_table = None
        self._responsive_mode = "wide"
        self._command_widgets: dict[str, QWidget] = {}
        self._range_summary: QWidget | None = None
        self._quota_summary: QWidget | None = None

    def chrome_content_height(self) -> int:
        """Return the bounded visible height of queue chrome.

        ``QBoxLayout.sizeHint()`` is not a safe authority after the chrome host
        has previously been fixed to a taller disclosure composition.  On the
        Windows Qt path it can retain that historical envelope even after
        Workflow/Batch/Range rows are structurally removed.  Measure the
        currently attached visible widget items instead and clamp every hint to
        the widget's explicit minimum/maximum height contract.
        """

        margins = self.root_layout.contentsMargins()
        heights: list[int] = []
        for index in range(self.root_layout.count()):
            item = self.root_layout.itemAt(index)
            widget = item.widget()
            if widget is None or widget.isHidden():
                continue
            hinted = widget.sizeHint().height()
            if hinted < 0:
                hinted = widget.minimumSizeHint().height()
            if hinted < 0:
                hinted = widget.height()
            bounded = max(widget.minimumHeight(), int(hinted))
            bounded = min(bounded, widget.maximumHeight())
            heights.append(max(0, bounded))

        spacing = max(0, self.root_layout.spacing())
        inter_item = spacing * max(0, len(heights) - 1)
        return max(0, margins.top() + margins.bottom() + sum(heights) + inter_item)

    def sync_chrome_height(self) -> int:
        """Lock queue chrome to the exact current bounded content height.

        The fixed host is deliberately released before measurement so a previous
        expanded disclosure cannot ratchet the next collapsed pass upward.  The
        final authority is :meth:`chrome_content_height`, not a historical Qt
        layout size hint.
        """

        self.chrome_host.setMinimumHeight(0)
        self.chrome_host.setMaximumHeight(16777215)
        self.root_layout.invalidate()
        self.root_layout.activate()
        height = self.chrome_content_height()
        self.chrome_host.setFixedHeight(height)
        self.chrome_host.updateGeometry()

        # Reassert shell ownership after every disclosure/density pass. A bare
        # child layout is intentionally avoided: on the frozen Windows Qt path
        # it allowed the zero-stretch chrome item to inherit surplus layout-cell
        # extent before the body. The body widget is the only expanding vertical
        # item and the chrome remains anchored to the shell top.
        self.shell_layout.setStretch(0, 0)
        self.shell_layout.setStretch(1, 1)
        self.shell_layout.setStretch(2, 0)
        self.shell_layout.setAlignment(self.chrome_host, Qt.AlignTop)
        self.body_host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.footer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.shell_layout.invalidate()
        self.shell_layout.activate()
        self.body_host.updateGeometry()
        self.updateGeometry()
        return height

    def set_compact_mode(self, compact: bool) -> None:
        """Prioritize the table on short desktop screens.

        The application already exposes the same queue counts in the global
        metrics strip. In Compact workspace mode, hiding the duplicate scope
        summary and footer gives the table enough vertical space at 1366×768
        without imposing an ineffective hard minimum height.
        """
        self.setProperty("compact", compact)
        self.subtitle_label.setVisible(not compact)
        self.summary.setVisible(not compact)
        self.footer.setVisible(not compact)
        self.heading.setMaximumHeight(36 if compact else 16777215)
        self.heading.setMinimumHeight(32 if compact else 0)
        self.root_layout.setSpacing(4 if compact else 6)
        self.shell_layout.setSpacing(4 if compact else 6)
        self.style().unpolish(self)
        self.style().polish(self)
        self.sync_chrome_height()

    def add_range_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.range_layout.addWidget(widget, stretch)

    def add_range_stretch(self, stretch: int = 1) -> None:
        self.range_layout.addStretch(stretch)

    def add_command_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.command_layout.addWidget(widget, stretch)

    def add_command_stretch(self, stretch: int = 1) -> None:
        self.command_layout.addStretch(stretch)

    def add_body_widget(self, widget: QWidget, stretch: int = 0) -> None:
        self.body_layout.addWidget(widget, stretch)

    def add_body_layout(self, layout) -> None:  # noqa: ANN001
        self.body_layout.addLayout(layout)

    def bind_table(self, table, settings: QSettings | None = None) -> None:  # noqa: ANN001
        self.bound_table = table
        self.column_controller = QueueColumnController(table, settings)
        self.columns_button.setMenu(self.column_controller.menu)

    def configure_range_summary(self, summary: QWidget, quota: QWidget) -> None:
        self._range_summary = summary
        self._quota_summary = quota

    def configure_command_center(self, **widgets: QWidget) -> None:
        """Register stable command widgets and enable breakpoint reflow.

        MainWindow retains ownership of every action and controller callback;
        the workspace only changes presentation and visibility.
        """

        self._command_widgets = dict(widgets)
        self.set_responsive_mode(self._responsive_mode, force=True)

    @staticmethod
    def _clear_layout(layout) -> None:  # noqa: ANN001
        while layout.count():
            item = layout.takeAt(0)
            if item is not None and item.spacerItem() is not None:
                del item

    def _add(self, layout, name: str, stretch: int = 0) -> None:  # noqa: ANN001
        widget = self._command_widgets.get(name)
        if widget is not None:
            layout.addWidget(widget, stretch)
            # Apply visibility after the widget has been inserted into its new
            # layout. This is more reliable on Windows/PySide6 when a widget was
            # explicitly hidden before being moved between command rows.
            widget.setVisible(True)

    def _command_visibility_matches(self, value: str) -> bool:
        """Return whether the current explicit visibility matches a breakpoint.

        Responsive mode can already be ``compact`` while a child was hidden by
        a previous layout pass or restored window state. Treating the mode value
        alone as authoritative made the method return early and left the More
        actions control hidden. ``isHidden`` is intentional here: unlike
        ``isVisible``, it does not depend on transient ancestor visibility while
        a window is being shown or tested offscreen.
        """

        if not self._command_widgets:
            return True
        planning_attached = self.command_root_layout.indexOf(self.planning_host) >= 0
        if planning_attached != (value == "compact"):
            return False
        expected = {
            "wide": {
                "filter_label", "search", "status", "source", "scope", "order",
                "use_sort", "action_label", "use_selection", "dry_run", "retry",
                "skip", "reset", "clear", "output",
            },
            "standard": {
                "filter_label", "search", "status", "source", "planning_label",
                "scope", "order", "use_sort", "action_label", "use_selection",
                "dry_run", "retry", "skip", "reset", "clear", "output",
            },
            "compact": {"search", "status", "source", "scope", "order", "dry_run", "retry", "more"},
        }[value]
        return all(widget.isHidden() == (name not in expected) for name, widget in self._command_widgets.items())

    def set_responsive_mode(self, mode: object, *, force: bool = False) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        if value not in {"compact", "standard", "wide"}:
            value = "standard"
        if not force and value == self._responsive_mode and self._command_visibility_matches(value):
            return
        self._responsive_mode = value
        self.setProperty("responsiveMode", value)
        self.subtitle_label.setVisible(value != "compact")
        if self._range_summary is not None:
            self._range_summary.setVisible(value != "compact")
        if self._quota_summary is not None:
            self._quota_summary.setVisible(True)

        if not self._command_widgets:
            self.style().unpolish(self)
            self.style().polish(self)
            return

        for widget in self._command_widgets.values():
            widget.setVisible(False)
        self._clear_layout(self.command_layout)
        self._clear_layout(self.planning_layout)
        self._clear_layout(self.action_layout)

        planning_attached = self.command_root_layout.indexOf(self.planning_host) >= 0
        if value == "compact" and not planning_attached:
            self.command_root_layout.insertWidget(1, self.planning_host)
            self.planning_host.show()
        elif value != "compact" and planning_attached:
            self.command_root_layout.removeWidget(self.planning_host)
            self.planning_host.hide()

        if value == "wide":
            for name, stretch in (
                ("filter_label", 0),
                ("search", 1),
                ("status", 0),
                ("source", 0),
                ("scope", 0),
                ("order", 0),
                ("use_sort", 0),
            ):
                self._add(self.command_layout, name, stretch)
            self.planning_layout.addStretch(1)
            for name in (
                "action_label",
                "use_selection",
                "dry_run",
                "retry",
                "skip",
                "reset",
                "clear",
                "output",
            ):
                self._add(self.action_layout, name)
            self.action_layout.addStretch(1)
        elif value == "standard":
            for name, stretch in (
                ("filter_label", 0),
                ("search", 1),
                ("status", 0),
                ("source", 0),
                ("planning_label", 0),
                ("scope", 0),
                ("order", 0),
                ("use_sort", 0),
            ):
                self._add(self.command_layout, name, stretch)
            for name in (
                "action_label",
                "use_selection",
                "dry_run",
                "retry",
                "skip",
                "reset",
                "clear",
                "output",
            ):
                self._add(self.action_layout, name)
            self.action_layout.addStretch(1)
        else:
            self._add(self.command_layout, "search", 1)
            self._add(self.command_layout, "status")
            self._add(self.planning_layout, "source", 1)
            self._add(self.planning_layout, "scope")
            self._add(self.planning_layout, "order")
            self._add(self.action_layout, "dry_run")
            self._add(self.action_layout, "retry")
            self._add(self.action_layout, "more")
            self.action_layout.addStretch(1)

        self.command_host.updateGeometry()
        self.style().unpolish(self)
        self.style().polish(self)

    def apply_density(self, density: object) -> None:
        metrics = density_metrics(density)
        compact = normalize_density(density).value == "compact"
        self.root_layout.setSpacing(4 if compact else 6)
        self.shell_layout.setSpacing(4 if compact else 6)
        self.heading.layout().setContentsMargins(
            8 if compact else 10,
            4 if compact else 6,
            8,
            4 if compact else 6,
        )
        self.range_layout.setContentsMargins(7 if compact else 8, 3 if compact else 4, 7 if compact else 8, 3 if compact else 4)
        self.command_root_layout.setContentsMargins(
            7 if compact else 8,
            5 if compact else 6,
            7 if compact else 8,
            5 if compact else 6,
        )
        self.command_root_layout.setSpacing(4 if compact else 6)
        self.command_layout.setSpacing(5 if compact else 6)
        self.action_layout.setSpacing(5 if compact else 6)
        self.summary.setMaximumHeight(34 if compact else 38)
        self.summary.setMinimumHeight(30 if compact else 32)
        self.footer.setMinimumHeight(22 if compact else 26)
        self.setProperty("density", normalize_density(density).value)
        self.style().unpolish(self)
        self.style().polish(self)

        # Reapply table metrics after repolishing. On Windows, Qt can restore the
        # header's style-derived default section size during polish(), which made
        # compact density visually remain at 32 px instead of the requested 30 px.
        table = self.bound_table
        if table is not None and hasattr(table, "verticalHeader"):
            vertical_header = table.verticalHeader()
            vertical_header.setMinimumSectionSize(max(24, metrics.row_height - 4))
            vertical_header.setDefaultSectionSize(metrics.row_height)
        self.sync_chrome_height()

    def update_footer(self, stats: QueueSelectionStats) -> None:
        selected = f" · {stats.selected_jobs:,} selected" if stats.selected_jobs else ""
        self.footer.setText(
            f"{stats.visible_jobs:,} visible jobs · {stats.visible_characters:,} characters{selected} · {stats.scope_label}"
        )


def configure_queue_table(table: QTableWidget) -> None:
    """Apply the shared professional data-grid behavior to the queue table."""

    table.setObjectName("queueTable")
    table.setAccessibleName("Generation queue")
    table.setAccessibleDescription("Jobs in the current generation scope. Use arrow keys to move and Space to select rows.")
    table.setMinimumHeight(180)
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setTextElideMode(Qt.ElideMiddle)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.setSelectionMode(QAbstractItemView.ExtendedSelection)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
    table.setSortingEnabled(False)  # MainWindow resolves stable, identity-safe sorting.
    table.verticalHeader().setVisible(False)
    table.verticalHeader().setDefaultSectionSize(32)
    table.verticalHeader().setMinimumSectionSize(28)

    header = table.horizontalHeader()
    header.setObjectName("queueHeader")
    header.setSectionsClickable(True)
    header.setHighlightSections(False)
    header.setSortIndicatorShown(True)
    header.setMinimumSectionSize(56)
    header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    header.setSectionsMovable(True)

    # Filename and output absorb available width; data columns remain compact.
    header.setSectionResizeMode(QHeaderView.Interactive)
    header.setSectionResizeMode(1, QHeaderView.Stretch)
    header.setSectionResizeMode(11, QHeaderView.Stretch)
    for column in (0, 4, 5, 9, 10):
        header.setSectionResizeMode(column, QHeaderView.ResizeToContents)

    table.setColumnWidth(2, 140)
    table.setColumnWidth(3, 110)
    table.setColumnWidth(6, 110)
    table.setColumnWidth(7, 150)
    table.setColumnWidth(8, 160)
    table.setItemDelegateForColumn(5, QueueStatusDelegate(table))

    # Standard desktop selection shortcuts.
    QShortcut(QKeySequence.SelectAll, table, activated=table.selectAll)
    QShortcut(QKeySequence("Escape"), table, activated=table.clearSelection)
