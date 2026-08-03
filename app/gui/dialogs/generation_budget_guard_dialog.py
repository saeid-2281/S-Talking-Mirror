from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.generation_budget_guard import GenerationBudgetGuardDecision
from app.services.generation_budget_guard_service import GenerationBudgetGuardService


class GenerationBudgetGuardDialog(QDialog):
    """Review reservations and create exact, time-bound budget exceptions."""

    def __init__(
        self,
        service: GenerationBudgetGuardService,
        project_name: str,
        parent: QWidget | None = None,
        *,
        decision: GenerationBudgetGuardDecision | None = None,
        export_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_name = str(project_name or "").strip()
        self.decision = decision
        self.export_dir = Path(export_dir or service.reports_dir / "budget-guard")
        self.created_approval = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationBudgetGuardDialog")
        self.setWindowTitle("Budget and quota guard")
        self.resize(1080, 760)
        self.setMinimumSize(780, 560)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Budget and quota guard",
            "Inspect active reservations, provider quota and time-bound exceptions before generation.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.summary = DialogStatusCard("Loading guard state", "", tone="info")
        self.workspace.add_body_widget(self.summary)

        if self.decision is not None and self.decision.status == "budget_blocked":
            section = DialogSection(
                "Approve this exact budget exception",
                "The approval is bound to the current decision fingerprint and cannot authorize another launch.",
            )
            form = QFormLayout()
            self.target = QLabel(
                f"{self.decision.currency} {self.decision.estimated_cost:.4f} · "
                f"{self.decision.required_characters:,} characters · {self.decision.fingerprint[:16]}"
            )
            self.target.setWordWrap(True)
            self.approved_by = QLineEdit()
            self.approved_by.setObjectName("budgetGuardApprovedBy")
            self.reason = QPlainTextEdit()
            self.reason.setObjectName("budgetGuardApprovalReason")
            self.reason.setMinimumHeight(80)
            self.duration = QComboBox()
            for label, minutes in (("15 minutes", 15), ("1 hour", 60), ("4 hours", 240), ("24 hours", 1440)):
                self.duration.addItem(label, minutes)
            self.duration.setCurrentIndex(1)
            self.max_uses = QSpinBox()
            self.max_uses.setRange(1, 10)
            self.max_uses.setValue(1)
            form.addRow("Launch", self.target)
            form.addRow("Approved by", self.approved_by)
            form.addRow("Reason", self.reason)
            form.addRow("Expires after", self.duration)
            form.addRow("Maximum uses", self.max_uses)
            section.add_layout(form)
            self.approve_button = QPushButton("Create budget exception")
            self.approve_button.setObjectName("dialogPrimaryAction")
            self.approve_button.setIcon(action_icon("save"))
            self.approve_button.clicked.connect(self.create_approval)
            section.add_widget(self.approve_button)
            self.workspace.add_body_widget(section)

        reservations = DialogSection(
            "Reservations",
            "Active reservations prevent concurrent runs from spending the same remaining budget or quota.",
        )
        self.reservation_table = QTableWidget(0, 7)
        self.reservation_table.setObjectName("budgetGuardReservationTable")
        self.reservation_table.setHorizontalHeaderLabels(
            ["Created", "Project", "Run", "Status", "Cost", "Characters", "Reservation ID"]
        )
        self.reservation_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.reservation_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        reservations.add_widget(self.reservation_table)
        self.workspace.add_body_widget(reservations)

        approvals = DialogSection(
            "Exception approvals",
            "Expired, consumed or revoked approvals cannot authorize a future launch.",
        )
        self.approval_table = QTableWidget(0, 6)
        self.approval_table.setObjectName("budgetGuardApprovalTable")
        self.approval_table.setHorizontalHeaderLabels(
            ["Created", "Project", "Status", "Approved by", "Uses", "Approval ID"]
        )
        self.approval_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.approval_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        approvals.add_widget(self.approval_table)
        self.workspace.add_body_widget(approvals)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.workspace.add_footer_widget(self.status_label, 1)
        refresh = QPushButton("Refresh")
        refresh.setIcon(action_icon("general.refresh"))
        refresh.clicked.connect(self.refresh)
        export = QPushButton("Export")
        export.setIcon(action_icon("save"))
        export.clicked.connect(self.export_records)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        self.workspace.add_footer_widget(refresh)
        self.workspace.add_footer_widget(export)
        self.workspace.add_footer_widget(close)

    def create_approval(self) -> bool:
        if self.decision is None:
            return False
        try:
            self.created_approval = self.service.create_approval(
                project_name=self.project_name,
                decision_fingerprint=self.decision.fingerprint,
                approved_by=self.approved_by.text().strip(),
                reason=self.reason.toPlainText().strip(),
                duration_minutes=int(self.duration.currentData() or 60),
                max_uses=self.max_uses.value(),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return False
        self.status_label.setText(f"Created approval {self.created_approval.approval_id}.")
        self.refresh()
        self.accept()
        return True

    def refresh(self) -> None:
        reservations = self.service.list_reservations(project_name=self.project_name or None)
        approvals = self.service.list_approvals(project_name=self.project_name or None)
        summary = self.service.summary(project_name=self.project_name or None)
        self.summary.update_status(
            f"{summary.active_reservations:,} active reservation(s)",
            f"{summary.currency} {summary.reserved_cost:.4f} reserved · "
            f"{summary.reserved_characters:,} characters · {summary.active_approvals:,} active approval(s)",
            tone="warning" if summary.active_reservations else "success",
        )
        self.reservation_table.setRowCount(len(reservations))
        for row, item in enumerate(reservations):
            values = (
                item.created_at,
                item.project_name,
                item.run_id,
                item.status.title(),
                f"{item.currency} {item.estimated_cost:.4f}",
                f"{item.reserved_characters:,}",
                item.reservation_id,
            )
            for column, value in enumerate(values):
                self.reservation_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.approval_table.setRowCount(len(approvals))
        for row, item in enumerate(approvals):
            values = (
                item.created_at,
                item.project_name,
                item.status.title(),
                item.approved_by,
                f"{item.used_count}/{item.max_uses}",
                item.approval_id,
            )
            for column, value in enumerate(values):
                self.approval_table.setItem(row, column, QTableWidgetItem(str(value)))
        self.reservation_table.resizeColumnsToContents()
        self.approval_table.resizeColumnsToContents()
        self.status_label.setText(
            f"Loaded {len(reservations):,} reservation(s) and {len(approvals):,} approval(s)."
        )

    def export_records(self):
        result = self.service.export(self.export_dir, project_name=self.project_name or None)
        self.status_label.setText(f"Exported {result.json_path.name} and {result.csv_path.name}.")
        return result
