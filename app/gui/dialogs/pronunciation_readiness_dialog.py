from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.pronunciation_readiness import PronunciationProjectReadiness
from app.services.pronunciation_readiness_service import PronunciationReadinessService


class PronunciationReadinessDialog(QDialog):
    """Read-only project-level pronunciation coverage dashboard."""

    reviewWorkspaceRequested = Signal()

    FILTER_ALL = "All"

    def __init__(self, readiness: PronunciationProjectReadiness, parent=None) -> None:
        super().__init__(parent)
        self.readiness = readiness
        self.setWindowTitle("Pronunciation Coverage & Project Readiness")
        self.resize(1100, 700)

        root = QVBoxLayout(self)
        title = QLabel("Pronunciation Coverage & Project Readiness")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        subtitle = QLabel(
            "Read-only project coverage before Preflight. This dashboard never approves rows, changes pronunciation "
            "decisions, changes language/provider/voice/model/dictionary settings, runs Preflight, or starts generation."
        )
        subtitle.setObjectName("dialogSubtitle")
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        self.summary_label = QLabel()
        self.summary_label.setWordWrap(True)
        root.addWidget(self.summary_label)

        self.metrics_label = QLabel()
        self.metrics_label.setWordWrap(True)
        root.addWidget(self.metrics_label)

        controls = QHBoxLayout()
        controls.addWidget(QLabel("Category"))
        self.filter_combo = QComboBox()
        self.filter_combo.addItems([self.FILTER_ALL, *PronunciationReadinessService.CATEGORIES])
        self.filter_combo.currentTextChanged.connect(self.refresh_table)
        controls.addWidget(self.filter_combo)
        controls.addStretch(1)
        root.addLayout(controls)

        self.table = QTableWidget(0, 9)
        self.table.setHorizontalHeaderLabels(
            ["Row", "Category", "Risk", "Language", "Decision", "Freshness", "Signals", "Audit", "Reason"]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        for column, width in {0: 65, 1: 145, 2: 80, 3: 90, 4: 110, 5: 100, 6: 230, 7: 130}.items():
            self.table.setColumnWidth(column, width)
        root.addWidget(self.table, 1)

        actions = QHBoxLayout()
        self.review_button = QPushButton("Open Pronunciation Review Workspace")
        self.review_button.setToolTip("Open the explicit review workspace. No decision is applied from this dashboard.")
        self.review_button.clicked.connect(self.reviewWorkspaceRequested.emit)
        actions.addWidget(self.review_button)
        actions.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        actions.addWidget(close_button)
        root.addLayout(actions)

        self.refresh_readiness(readiness)

    def refresh_readiness(self, readiness: PronunciationProjectReadiness) -> None:
        self.readiness = readiness
        self.summary_label.setText(readiness.summary)
        self.metrics_label.setText(
            f"Total: {readiness.total_jobs:,} · pronunciation risk: {readiness.pronunciation_risk:,} · "
            f"reviewed current: {readiness.reviewed_current:,} · stale: {readiness.stale_decisions:,} · "
            f"unresolved: {readiness.unresolved:,} · normalized: {readiness.normalized:,} · "
            f"keep original: {readiness.keep_original:,} · audit events: {readiness.audit_event_count:,} "
            f"({readiness.audit_integrity})."
        )
        self.refresh_table()

    def refresh_table(self) -> None:
        selected = self.filter_combo.currentText() if hasattr(self, "filter_combo") else self.FILTER_ALL
        rows = [row for row in self.readiness.rows if selected == self.FILTER_ALL or row.category == selected]
        self.table.setRowCount(len(rows))
        category_rank = {
            PronunciationReadinessService.UNSAFE: 0,
            PronunciationReadinessService.STALE: 1,
            PronunciationReadinessService.NEEDS_REVIEW: 2,
            PronunciationReadinessService.READY: 3,
            PronunciationReadinessService.NO_ACTION: 4,
        }
        rows.sort(key=lambda row: (category_rank.get(row.category, 9), row.row_number))
        for table_row, row in enumerate(rows):
            audit = f"{row.audit_event_count} event(s)"
            if row.audit_note:
                audit = f"{audit} · {row.audit_note}"
            values = [
                str(row.row_number),
                row.category,
                row.risk_level.title(),
                row.language or "not set",
                row.decision_kind or "—",
                {"current": "Current", "stale": "Stale", "legacy": "Legacy", "none": "—"}.get(
                    row.freshness, row.freshness.title()
                ),
                ", ".join(row.flags) if row.flags else "plain prose",
                audit,
                row.reason,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.UserRole, row.row_number)
                self.table.setItem(table_row, column, item)
