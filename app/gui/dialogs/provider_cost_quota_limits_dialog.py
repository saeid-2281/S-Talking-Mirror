from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models import AppSettings
from app.models.provider_cost_quota_limits import ProviderCostQuotaLimitRow
from app.services.provider_cost_quota_limits_service import ProviderCostQuotaLimitsService


class ProviderCostQuotaLimitsDialog(QDialog):
    """Cached/configured provider economics and request-limit intelligence."""

    def __init__(
        self,
        service: ProviderCostQuotaLimitsService,
        settings_provider: Callable[[], AppSettings],
        *,
        project_id: int | None,
        scoped_characters: int,
        open_cost_capacity: Callable[[], object] | None = None,
        open_accounts: Callable[[], object] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.settings_provider = settings_provider
        self.project_id = project_id
        self.scoped_characters = max(0, int(scoped_characters))
        self.open_cost_capacity = open_cost_capacity
        self.open_accounts = open_accounts
        self.snapshot_data = None
        self.setWindowTitle("Provider Cost / Quota / Limits Intelligence")
        self.resize(1120, 660)

        root = QVBoxLayout(self)
        title = QLabel("Provider Cost / Quota / Limits Intelligence")
        title.setStyleSheet("font-size:18px;font-weight:700;")
        root.addWidget(title)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        filters = QHBoxLayout()
        self.provider = QComboBox()
        self.provider.addItem("All providers", None)
        for provider_id in self.service.providers.provider_ids():
            manifest = self.service.providers.manifest_for(provider_id)
            self.provider.addItem(manifest.display_name, provider_id)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search provider, account, model, source, status…")
        self.attention_only = QCheckBox("Attention only")
        self.refresh_button = QPushButton("Refresh view")
        filters.addWidget(self.provider)
        filters.addWidget(self.search, 1)
        filters.addWidget(self.attention_only)
        filters.addWidget(self.refresh_button)
        root.addLayout(filters)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Provider", "Account", "Model", "Cost", "Quota", "Request limit", "State"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.details = QLabel("Select a provider row for source details.")
        self.details.setWordWrap(True)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.details)

        buttons = QHBoxLayout()
        cost_button = QPushButton("Cost & Capacity…")
        accounts_button = QPushButton("Provider Accounts…")
        close_button = QPushButton("Close")
        cost_button.setEnabled(self.open_cost_capacity is not None)
        accounts_button.setEnabled(self.open_accounts is not None)
        buttons.addWidget(cost_button)
        buttons.addWidget(accounts_button)
        buttons.addStretch(1)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

        self.provider.currentIndexChanged.connect(self._render)
        self.search.textChanged.connect(self._render)
        self.attention_only.toggled.connect(self._render)
        self.refresh_button.clicked.connect(self.refresh_snapshot)
        self.table.itemSelectionChanged.connect(self._show_selected)
        cost_button.clicked.connect(lambda: self.open_cost_capacity and self.open_cost_capacity())
        accounts_button.clicked.connect(lambda: self.open_accounts and self.open_accounts())
        close_button.clicked.connect(self.close)
        self.refresh_snapshot()

    def refresh_snapshot(self) -> None:
        self.snapshot_data = self.service.snapshot(
            self.settings_provider(),
            project_id=self.project_id,
            scoped_characters=self.scoped_characters,
        )
        snapshot = self.snapshot_data
        self.summary.setText(
            f"Scope: {snapshot.scoped_characters:,} characters · "
            f"Providers: {snapshot.provider_count} · "
            f"Known cost: {snapshot.configured_cost_count} · "
            f"Confirmed quota: {snapshot.confirmed_quota_count} · "
            f"Known request limits: {snapshot.known_limit_count} · "
            f"Attention: {snapshot.attention_count}. "
            "This view is cached/configured-only and does not call billing/admin APIs."
        )
        self._render()

    def _render(self) -> None:
        if self.snapshot_data is None:
            return
        rows = self.service.filtered_rows(
            self.snapshot_data,
            query=self.search.text(),
            provider_id=self.provider.currentData(),
            attention_only=self.attention_only.isChecked(),
        )
        self.table.setRowCount(len(rows))
        for row_index, row in enumerate(rows):
            values = (
                row.provider_name,
                row.profile_name or "—",
                row.model_id or "—",
                self._cost_text(row),
                self._quota_text(row),
                self._limit_text(row),
                row.state.replace("_", " ").title(),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, row)
                self.table.setItem(row_index, column, item)
        self.table.resizeColumnsToContents()
        if rows:
            self.table.selectRow(0)
        else:
            self.details.setText("No providers match the current filters.")

    def _show_selected(self) -> None:
        row_index = self.table.currentRow()
        if row_index < 0:
            return
        item = self.table.item(row_index, 0)
        row = item.data(Qt.UserRole) if item else None
        if not isinstance(row, ProviderCostQuotaLimitRow):
            return
        self.details.setText(
            f"{row.provider_name} [{row.provider_id}] · {row.summary}\n"
            f"Cost source: {row.cost.source} — {row.cost.message}\n"
            f"Quota source: {row.quota.source} — {row.quota.message}\n"
            f"Limit source: {row.request_limit.source} — {row.request_limit.message}"
        )

    @staticmethod
    def _cost_text(row: ProviderCostQuotaLimitRow) -> str:
        cost = row.cost
        if cost.estimated_cost is None:
            return "Unknown"
        if cost.currency is None:
            return "No provider fee"
        rate = cost.rate_per_million_characters or 0.0
        return f"{cost.currency} {cost.estimated_cost:.4f} · {rate:.2f}/1M"

    @staticmethod
    def _quota_text(row: ProviderCostQuotaLimitRow) -> str:
        quota = row.quota
        if quota.state == "not_applicable":
            return "Local / N/A"
        if quota.remaining is None:
            return "Unknown"
        suffix = f" / {quota.limit:,}" if quota.limit is not None else ""
        if quota.shortfall:
            return f"{quota.remaining:,}{suffix} · short {quota.shortfall:,}"
        return f"{quota.remaining:,}{suffix} remaining"

    @staticmethod
    def _limit_text(row: ProviderCostQuotaLimitRow) -> str:
        limit = row.request_limit
        if limit.state == "not_applicable":
            return "Local / N/A"
        if limit.value is None:
            return "Unknown"
        return f"{limit.value:,} {limit.unit}"
