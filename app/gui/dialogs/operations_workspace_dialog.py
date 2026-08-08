from __future__ import annotations

from dataclasses import dataclass
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.operations_command_center import OperationsCommandSnapshot
from app.services.operations_command_center_service import OperationsCommandCenterService


@dataclass(frozen=True, slots=True)
class OperationsWorkspaceTool:
    code: str
    title: str
    description: str
    group: str
    icon_name: str = "report"


OPERATIONS_WORKSPACE_TOOLS: tuple[OperationsWorkspaceTool, ...] = (
    OperationsWorkspaceTool(
        "operations-command-center",
        "Production Operations Command Center",
        "Read-only health summary across incidents, SLO, capacity, recovery, providers, billing and assurance.",
        "Overview",
        "health",
    ),
    OperationsWorkspaceTool(
        "operational-persistence",
        "Operational Persistence & Evidence Store",
        "Index verified operational evidence in the secondary SQLite persistence layer.",
        "Evidence & Certification",
    ),
    OperationsWorkspaceTool(
        "evidence-refresh",
        "Evidence & Certification Refresh",
        "Review evidence freshness and create a read-only certification refresh.",
        "Evidence & Certification",
    ),
    OperationsWorkspaceTool(
        "operational-readiness",
        "Operational Readiness Final Certification",
        "Review final readiness gates and human certification evidence.",
        "Evidence & Certification",
    ),
    OperationsWorkspaceTool(
        "post-ga-maintenance",
        "Post-GA Maintenance",
        "Review stable-release maintenance evidence and operational freshness.",
        "Reliability",
        "health",
    ),
    OperationsWorkspaceTool(
        "service-level-objectives",
        "Service-Level Objectives & Error Budget",
        "Inspect SLO observations, error budget and release-safety decisions.",
        "Reliability",
        "health",
    ),
    OperationsWorkspaceTool(
        "capacity-readiness",
        "Capacity Forecast & Degradation Readiness",
        "Review saturation headroom, forecasts and release-capacity decisions.",
        "Reliability",
        "health",
    ),
    OperationsWorkspaceTool(
        "reliability-assurance",
        "Reliability Assurance & Audit Pack",
        "Review assurance decisions, exceptions and the audit evidence chain.",
        "Reliability",
    ),
    OperationsWorkspaceTool(
        "assurance-renewal",
        "Assurance Renewal & Follow-up",
        "Track assurance expiry, follow-up exceptions and renewal decisions.",
        "Reliability",
        "health",
    ),
    OperationsWorkspaceTool(
        "incident-support",
        "Production Incident Support",
        "Create privacy-safe support evidence for production incidents.",
        "Incidents",
        "warning",
    ),
    OperationsWorkspaceTool(
        "incident-triage",
        "Incident Triage & Remediation",
        "Validate support evidence, severity, priority and remediation readiness.",
        "Incidents",
        "warning",
    ),
    OperationsWorkspaceTool(
        "incident-resolution",
        "Incident Resolution & Closure",
        "Record verified resolution, closure and knowledge capture.",
        "Incidents",
        "health",
    ),
    OperationsWorkspaceTool(
        "incident-prevention",
        "Incident Prevention & Recurrence",
        "Aggregate recurrence patterns and preventive-action evidence.",
        "Incidents",
        "health",
    ),
    OperationsWorkspaceTool(
        "prevention-effectiveness",
        "Prevention Effectiveness & Risk",
        "Review preventive-action effectiveness and residual risk.",
        "Incidents",
        "health",
    ),
    OperationsWorkspaceTool(
        "service-continuity",
        "Service Continuity & Recovery Drill",
        "Review backup freshness, RTO/RPO targets and recovery-drill evidence.",
        "Recovery",
        "health",
    ),
    OperationsWorkspaceTool(
        "degradation-readiness",
        "Controlled Degradation Drill & Recovery",
        "Review controlled degradation scenarios and recovery validation.",
        "Recovery",
        "health",
    ),
    OperationsWorkspaceTool(
        "recovery-replay",
        "Recovery Replay Integrity & Duplicate Prevention",
        "Validate recovery replay, duplicate prevention and billing safety.",
        "Recovery",
        "health",
    ),
    OperationsWorkspaceTool(
        "provider-governance",
        "Provider Performance Governance",
        "Review provider reliability, cost, billing integrity and governance recommendations.",
        "Providers & Billing",
        "health",
    ),
    OperationsWorkspaceTool(
        "billing-reconciliation",
        "Provider Billing Reconciliation & Dispute Readiness",
        "Reconcile provider invoices against verified internal requests and usage.",
        "Providers & Billing",
    ),
    OperationsWorkspaceTool(
        "billing-dispute-resolution",
        "Billing Dispute Resolution & Settlement",
        "Verify provider dispute responses, credits and remaining variance.",
        "Providers & Billing",
    ),
    OperationsWorkspaceTool(
        "provider-credit-close",
        "Provider Credit Ledger Close & Financial Control",
        "Close verified provider credits into an auditable financial period.",
        "Providers & Billing",
    ),
    OperationsWorkspaceTool(
        "financial-audit",
        "Financial Audit & Cost Integrity",
        "Audit invoice, internal ledger, settlement credit and residual variance integrity.",
        "Providers & Billing",
    ),
    OperationsWorkspaceTool(
        "security-supply-chain",
        "Security & Supply Chain",
        "Review security hardening, dependencies and release-supply-chain evidence.",
        "Release & Security",
        "health",
    ),
    OperationsWorkspaceTool(
        "performance-stability",
        "Performance & Stability",
        "Review long-run runtime stability and performance evidence.",
        "Release & Security",
        "health",
    ),
    OperationsWorkspaceTool(
        "production-release",
        "Production Release Certification",
        "Review production release-readiness certification evidence.",
        "Release & Security",
        "health",
    ),
    OperationsWorkspaceTool(
        "stable-release",
        "Stable Release Promotion",
        "Review stable-channel promotion evidence and immutable release receipts.",
        "Release & Security",
        "health",
    ),
    OperationsWorkspaceTool(
        "final-production-certification",
        "Final S-Talking 1.x Production Certification",
        "Bind the committed stable source, post-commit release check and verified operational evidence into the final 1.x certification.",
        "Release & Security",
        "success",
    ),
    OperationsWorkspaceTool(
        "release-lifecycle",
        "Release Lifecycle E2E Validation",
        "Validate final release, stable update delivery, migration and recovery as one guarded chain.",
        "Release & Security",
        "history",
    ),
    OperationsWorkspaceTool(
        "upgrade-recovery",
        "Upgrade & Recovery",
        "Validate upgrade, backup, migration and acknowledged recovery behavior.",
        "Release & Security",
        "history",
    ),
)


class OperationsWorkspaceDialog(QDialog):
    """Unified navigation shell for operational and governance workspaces."""

    openRequested = Signal(str)

    GROUP_ORDER = (
        "Overview",
        "Reliability",
        "Incidents",
        "Recovery",
        "Providers & Billing",
        "Evidence & Certification",
        "Release & Security",
    )

    def __init__(
        self,
        service: OperationsCommandCenterService,
        parent: QWidget | None = None,
        *,
        project_id: int | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_id = project_id
        self.current_snapshot: OperationsCommandSnapshot | None = None
        self.tool_widgets: dict[str, QFrame] = {}
        self.tool_status_labels: dict[str, QLabel] = {}
        self.group_pages: dict[str, QWidget] = {}
        self.group_items: dict[str, QListWidgetItem] = {}
        self._domain_signature: tuple[tuple[object, ...], ...] | None = None
        self._tool_status_cache: dict[str, str] = {}
        self.setObjectName("operationsWorkspaceDialog")
        self.setWindowTitle("Operations workspace")
        self.resize(1480, 920)
        self.setMinimumSize(1080, 720)
        self._build()
        self.refresh()

    @classmethod
    def tools_for_group(cls, group: str) -> tuple[OperationsWorkspaceTool, ...]:
        return tuple(tool for tool in OPERATIONS_WORKSPACE_TOOLS if tool.group == group)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Operations workspace",
            "A single navigation surface for production operations, reliability, incidents, recovery, provider governance, billing and audit evidence. Specialist workspaces remain available without crowding the Reports menu.",
            icon_name="health",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.overall = DialogStatusCard(
            "Loading operational status",
            "Verified command-center evidence is being summarized.",
            tone="info",
        )
        self.workspace.add_body_widget(self.overall)

        controls = QFrame(self)
        controls.setObjectName("operationsWorkspaceControls")
        controls_layout = QHBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)
        self.search = QLineEdit()
        self.search.setObjectName("operationsWorkspaceSearch")
        self.search.setPlaceholderText("Filter operational tools…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Filter operational tools")
        self.search.textChanged.connect(self._apply_filter)
        controls_layout.addWidget(self.search, 1)
        refresh = QPushButton(action_icon("general.refresh"), "Refresh status")
        refresh.clicked.connect(self.refresh)
        controls_layout.addWidget(refresh)
        self.workspace.add_body_widget(controls)

        content = QFrame(self)
        content.setObjectName("operationsWorkspaceContent")
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(12)

        self.navigation = QListWidget()
        self.navigation.setObjectName("operationsWorkspaceNavigation")
        self.navigation.setMaximumWidth(260)
        self.navigation.setMinimumWidth(210)
        self.navigation.setAccessibleName("Operations workspace sections")
        self.navigation.currentRowChanged.connect(self.pages_set_current_index)
        content_layout.addWidget(self.navigation)

        self.pages = QStackedWidget()
        self.pages.setObjectName("operationsWorkspacePages")
        content_layout.addWidget(self.pages, 1)

        for group in self.GROUP_ORDER:
            item = QListWidgetItem(group)
            self.navigation.addItem(item)
            self.group_items[group] = item
            page = self._build_overview_page() if group == "Overview" else self._build_group_page(group)
            self.group_pages[group] = page
            self.pages.addWidget(page)

        self.navigation.setCurrentRow(0)
        self.workspace.add_body_widget(content, 1)

        footer = QHBoxLayout()
        command_center = QPushButton(action_icon("health"), "Open command center")
        command_center.clicked.connect(
            lambda: self.openRequested.emit("operations-command-center")
        )
        footer.addWidget(command_center)
        footer.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        footer.addWidget(close_button)
        self.workspace.footer_layout.addLayout(footer)

    def pages_set_current_index(self, index: int) -> None:
        if 0 <= index < self.pages.count():
            self.pages.setCurrentIndex(index)

    def _build_overview_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        counters = QFrame()
        counter_layout = QGridLayout(counters)
        counter_layout.setContentsMargins(0, 0, 0, 0)
        self.healthy_label = QLabel("Healthy 0")
        self.warning_label = QLabel("Warning 0")
        self.critical_label = QLabel("Critical 0")
        self.unknown_label = QLabel("Unknown 0")
        for column, label in enumerate(
            (self.healthy_label, self.warning_label, self.critical_label, self.unknown_label)
        ):
            label.setObjectName("operationsWorkspaceCounter")
            counter_layout.addWidget(label, 0, column)
        layout.addWidget(counters)

        section = DialogSection(
            "Operational health",
            "The latest verified command-center evidence. Open a specialist workspace when a domain needs attention.",
        )
        self.domain_table = QTableWidget(0, 5)
        self.domain_table.setHorizontalHeaderLabels(
            ["Domain", "Status", "Metric", "Summary", "Open"]
        )
        self.domain_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.domain_table.setAlternatingRowColors(True)
        self.domain_table.horizontalHeader().setStretchLastSection(True)
        section.add_widget(self.domain_table)
        layout.addWidget(section)

        help_section = DialogSection(
            "How this workspace is organized",
            "Use the left navigation to move between operational disciplines. The unified workspace only navigates and summarizes; it does not execute deploy, provider, billing or recovery changes.",
        )
        layout.addWidget(help_section)
        layout.addStretch(1)
        return page

    def _build_group_page(self, group: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        section = DialogSection(
            group,
            "Open the specialist workspace you need; verified evidence and existing workflows remain authoritative.",
        )
        for tool in self.tools_for_group(group):
            card = self._build_tool_card(tool)
            section.add_widget(card)
        layout.addWidget(section)
        layout.addStretch(1)
        return page

    def _build_tool_card(self, tool: OperationsWorkspaceTool) -> QFrame:
        card = QFrame()
        card.setObjectName("operationsWorkspaceToolCard")
        card.setProperty("toolCode", tool.code)
        layout = QHBoxLayout(card)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(3)
        title = QLabel(tool.title)
        title.setObjectName("operationsWorkspaceToolTitle")
        description = QLabel(tool.description)
        description.setObjectName("operationsWorkspaceToolDescription")
        description.setWordWrap(True)
        text_layout.addWidget(title)
        text_layout.addWidget(description)
        layout.addWidget(text_box, 1)

        status = QLabel("Available")
        status.setObjectName("operationsWorkspaceToolStatus")
        status.setAlignment(Qt.AlignCenter)
        status.setMinimumWidth(92)
        layout.addWidget(status)

        button = QPushButton(action_icon(tool.icon_name), "Open")
        button.setAccessibleName(f"Open {tool.title}")
        button.clicked.connect(lambda _checked=False, code=tool.code: self.openRequested.emit(code))
        layout.addWidget(button)

        self.tool_widgets[tool.code] = card
        self.tool_status_labels[tool.code] = status
        return card

    def refresh(self) -> None:
        snapshot = self.service.snapshot(project_id=self.project_id)
        self.current_snapshot = snapshot
        tone = (
            "danger"
            if snapshot.overall_status == "critical"
            else "warning"
            if snapshot.overall_status == "attention"
            else "success"
        )
        self.overall.update_status(
            snapshot.overall_status.upper(),
            snapshot.status_summary,
            tone=tone,
        )
        self.healthy_label.setText(f"Healthy {snapshot.healthy_count}")
        self.warning_label.setText(f"Warning {snapshot.warning_count}")
        self.critical_label.setText(f"Critical {snapshot.critical_count}")
        self.unknown_label.setText(f"Unknown {snapshot.unknown_count}")
        self._fill_domains(snapshot)
        self._update_tool_status(snapshot)

    def _fill_domains(self, snapshot: OperationsCommandSnapshot) -> None:
        signature = tuple(
            (
                domain.code,
                domain.label,
                domain.status,
                domain.metric,
                domain.headline,
                domain.detail,
                domain.action_code,
            )
            for domain in snapshot.domains
        )
        if signature == self._domain_signature:
            return
        self._domain_signature = signature
        self.domain_table.setRowCount(len(snapshot.domains))
        for row, domain in enumerate(snapshot.domains):
            for column, value in enumerate(
                (domain.label, domain.status, domain.metric, domain.headline)
            ):
                item = QTableWidgetItem(str(value))
                item.setToolTip(domain.detail if column in {2, 3} else str(value))
                self.domain_table.setItem(row, column, item)
            button = QPushButton("Open")
            button.setEnabled(bool(domain.action_code))
            button.clicked.connect(
                lambda _checked=False, code=domain.action_code: self.openRequested.emit(code)
            )
            self.domain_table.setCellWidget(row, 4, button)
        self.domain_table.resizeColumnsToContents()

    def _update_tool_status(self, snapshot: OperationsCommandSnapshot) -> None:
        status_by_code = {domain.action_code: domain.status for domain in snapshot.domains}
        for code, label in self.tool_status_labels.items():
            status = status_by_code.get(code, "available")
            if self._tool_status_cache.get(code) == status:
                continue
            self._tool_status_cache[code] = status
            label.setText(status.replace("_", " ").title())
            label.setProperty("status", status)
            label.style().unpolish(label)
            label.style().polish(label)

    def _apply_filter(self, query: str) -> None:
        needle = query.strip().casefold()
        visible_by_group: dict[str, int] = {group: 0 for group in self.GROUP_ORDER}
        for tool in OPERATIONS_WORKSPACE_TOOLS:
            card = self.tool_widgets.get(tool.code)
            if card is None:
                continue
            haystack = f"{tool.title} {tool.description} {tool.group}".casefold()
            visible = not needle or needle in haystack
            card.setVisible(visible)
            if visible:
                visible_by_group[tool.group] = visible_by_group.get(tool.group, 0) + 1

        for group, item in self.group_items.items():
            if group == "Overview":
                item.setHidden(bool(needle))
            else:
                item.setHidden(bool(needle) and visible_by_group.get(group, 0) == 0)

        if needle:
            preferred_group = self._matching_group_for_filter(needle)
            if preferred_group is not None:
                self.navigation.setCurrentItem(self.group_items[preferred_group])
            else:
                self._select_first_visible_group()

    def _matching_group_for_filter(self, needle: str) -> str | None:
        for group in self.GROUP_ORDER:
            item = self.group_items[group]
            if item.isHidden():
                continue
            if needle in group.casefold():
                return group
        return None

    def _select_first_visible_group(self) -> None:
        for row in range(self.navigation.count()):
            item = self.navigation.item(row)
            if not item.isHidden():
                self.navigation.setCurrentRow(row)
                return

    @staticmethod
    def tool_codes() -> tuple[str, ...]:
        return tuple(tool.code for tool in OPERATIONS_WORKSPACE_TOOLS)

    @staticmethod
    def grouped_tool_counts() -> dict[str, int]:
        result: dict[str, int] = {}
        for tool in OPERATIONS_WORKSPACE_TOOLS:
            result[tool.group] = result.get(tool.group, 0) + 1
        return result
