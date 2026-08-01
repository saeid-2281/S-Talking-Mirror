from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHeaderView,
    QLabel,
    QTableWidget,
    QVBoxLayout,
)


class OrchestrationMetricCard(QFrame):
    """Compact dashboard metric with a semantic status property."""

    def __init__(self, title: str, value: str = "—", detail: str = "") -> None:
        super().__init__()
        self.setObjectName("orchestrationMetricCard")
        self.setProperty("status", "neutral")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 9, 12, 9)
        layout.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("orchestrationMetricTitle")
        self.value_label = QLabel(value)
        self.value_label.setObjectName("orchestrationMetricValue")
        self.detail_label = QLabel(detail)
        self.detail_label.setObjectName("orchestrationMetricDetail")
        self.detail_label.setWordWrap(True)
        layout.addWidget(self.title_label)
        layout.addWidget(self.value_label)
        layout.addWidget(self.detail_label)

    def update_metric(
        self,
        value: str,
        detail: str = "",
        *,
        status: str = "neutral",
    ) -> None:
        self.value_label.setText(value)
        self.detail_label.setText(detail)
        self.setProperty("status", status)
        self.style().unpolish(self)
        self.style().polish(self)


def configure_orchestration_table(table: QTableWidget) -> QTableWidget:
    table.setAlternatingRowColors(True)
    table.setEditTriggers(QAbstractItemView.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectRows)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
    table.horizontalHeader().setStretchLastSection(True)
    table.setSortingEnabled(False)
    table.setObjectName("orchestrationTable")
    return table


def apply_table_density(
    tables: Iterable[QTableWidget],
    density: str,
) -> None:
    row_height = 26 if density == "compact" else 34
    for table in tables:
        table.verticalHeader().setDefaultSectionSize(row_height)


def filter_table(
    table: QTableWidget,
    search_text: str,
    status_filter: str,
) -> int:
    query = search_text.strip().casefold()
    visible = 0
    for row in range(table.rowCount()):
        text = " ".join(
            table.item(row, column).text()
            for column in range(table.columnCount())
            if table.item(row, column) is not None
        ).casefold()
        matches_query = not query or query in text
        matches_status = _matches_status(text, status_filter)
        hidden = not (matches_query and matches_status)
        table.setRowHidden(row, hidden)
        if not hidden:
            visible += 1
    return visible


def _matches_status(text: str, status_filter: str) -> bool:
    if status_filter == "all":
        return True
    if status_filter == "attention":
        return any(
            token in text
            for token in (
                "open",
                "half_open",
                "warning",
                "at_risk",
                "missed",
                "failed",
                "exhausted",
                "rate_limited",
                "cooldown",
            )
        )
    if status_filter == "healthy":
        return any(token in text for token in ("closed", "success", "on_track", "healthy"))
    if status_filter == "failures":
        return any(token in text for token in ("failed", "failure", "exhausted", "switched"))
    if status_filter == "rate_limited":
        return any(token in text for token in ("rate_limited", "rate limit", "cooldown"))
    if status_filter == "at_risk":
        return any(token in text for token in ("watch", "at_risk", "missed"))
    return True


def set_status_cell(item: QLabel | object, status: str) -> None:
    if hasattr(item, "setProperty"):
        item.setProperty("status", status)
        style = item.style()
        style.unpolish(item)
        style.polish(item)
