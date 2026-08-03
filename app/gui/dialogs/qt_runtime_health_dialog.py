from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.services.qt_runtime_health_service import QtRuntimeHealthService


class QtRuntimeHealthDialog(QDialog):
    """Inspect and safely drain registered top-level Qt dialogs."""

    def __init__(
        self,
        service: QtRuntimeHealthService,
        parent: QWidget | None = None,
        *,
        export_dir: Path | None = None,
        open_path=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.export_dir = Path(export_dir or Path.cwd() / "reports" / "qt-runtime-health")
        self.open_path = open_path
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("qtRuntimeHealthDialog")
        self.setWindowTitle("UI runtime health")
        self.resize(980, 680)
        self.setMinimumSize(760, 520)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "UI runtime health",
            "Inspect dialog lifecycles, hidden top-level windows, deferred deletes and the global Qt thread pool.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Collecting Qt runtime state", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        section = DialogSection(
            "Registered dialogs",
            "All report dialogs use weak lifecycle tracking; hidden or finished windows can be drained without retaining Python references.",
        )
        self.table = QTableWidget(0, 7)
        self.table.setObjectName("qtRuntimeHealthTable")
        self.table.setHorizontalHeaderLabels(
            ["State", "Class", "Object", "Title", "Visible", "Modal", "Category"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        section.add_widget(self.table)
        self.workspace.add_body_widget(section)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)
        refresh = QPushButton("Refresh")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh)
        flush = QPushButton("Flush deferred deletes")
        flush.clicked.connect(self.flush_deferred)
        close_hidden = QPushButton("Close hidden dialogs")
        close_hidden.clicked.connect(self.close_hidden)
        export = QPushButton("Export snapshot")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_snapshot)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        for widget in (refresh, flush, close_hidden, export, close):
            self.workspace.add_footer_widget(widget)

    def refresh(self) -> None:
        snapshot = self.service.snapshot()
        tone = "warning" if snapshot.status == "attention" else "success"
        self.summary.update_status(
            f"{snapshot.registered_active} active · {snapshot.hidden_registered} hidden · {snapshot.active_thread_count} worker thread(s)",
            (
                f"Top-level widgets: {snapshot.top_level_widgets} · peak registered: {snapshot.peak_registered} · "
                f"created/finished/destroyed: {snapshot.created_total}/{snapshot.finished_total}/{snapshot.destroyed_total}"
            ),
            tone=tone,
        )
        self.table.setRowCount(len(snapshot.records))
        for row, record in enumerate(snapshot.records):
            values = [
                record.state.title(),
                record.class_name,
                record.object_name or "—",
                record.title or "—",
                "Yes" if record.visible else "No",
                "Yes" if record.modal else "No",
                record.category,
            ]
            for column, value in enumerate(values):
                self.table.setItem(row, column, QTableWidgetItem(str(value)))
        self.table.resizeColumnsToContents()
        self.status_label.setText(
            f"Qt platform: {snapshot.platform_name} · stale references: {snapshot.stale_reference_count}"
        )

    def flush_deferred(self) -> None:
        self.service.flush_deferred_deletes()
        self.refresh()
        self.status_label.setText("Deferred delete events flushed.")

    def close_hidden(self) -> None:
        count = self.service.close_hidden_dialogs()
        self.refresh()
        self.status_label.setText(f"Closed {count} hidden registered dialog(s).")

    def export_snapshot(self) -> Path:
        path = self.service.export_snapshot(self.export_dir)
        self.status_label.setText(f"Exported {path.name}")
        if callable(self.open_path):
            self.open_path(path.parent)
        return path
