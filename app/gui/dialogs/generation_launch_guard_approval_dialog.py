from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
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
from app.models.generation_launch_receipt import GenerationLaunchGuardApproval
from app.services.generation_confirmation_service import GenerationConfirmation
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


class GenerationLaunchGuardApprovalDialog(QDialog):
    """Create and manage time-bound exceptions for exact launch fingerprints."""

    def __init__(
        self,
        service: GenerationLaunchReceiptService,
        project_name: str,
        parent: QWidget | None = None,
        *,
        confirmation: GenerationConfirmation | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_name = str(project_name or "").strip()
        self.confirmation = confirmation
        self.approvals: list[GenerationLaunchGuardApproval] = []
        self.created_approval: GenerationLaunchGuardApproval | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationLaunchGuardApprovalDialog")
        self.setWindowTitle("Baseline guard exception approvals")
        self.resize(980, 700)
        self.setMinimumSize(680, 500)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Baseline guard exception approvals",
            "Authorize one exact protected launch drift without weakening the project guard policy.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        self.summary_card = DialogStatusCard(
            "No active exception selected",
            "Approvals are bound to one project, baseline receipt, launch fingerprint and protected change set.",
            tone="info",
        )
        self.summary_card.setObjectName("generationLaunchGuardApprovalSummary")
        self.workspace.add_body_widget(self.summary_card)

        self.create_section = DialogSection(
            "Approve the blocked launch",
            "The approval is time-bound and will be consumed only after a launch receipt is written successfully.",
        )
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.target_label = QLabel()
        self.target_label.setObjectName("historySummaryText")
        self.target_label.setWordWrap(True)
        self.approved_by = QLineEdit()
        self.approved_by.setObjectName("guardApprovalApprovedBy")
        self.approved_by.setPlaceholderText("Operator or reviewer name")
        self.reason = QPlainTextEdit()
        self.reason.setObjectName("guardApprovalReason")
        self.reason.setPlaceholderText("Explain why this exact baseline drift is acceptable…")
        self.reason.setMinimumHeight(75)
        self.reason.setMaximumHeight(110)
        self.duration = QComboBox()
        self.duration.setObjectName("guardApprovalDuration")
        for label, minutes in (
            ("15 minutes", 15),
            ("1 hour", 60),
            ("4 hours", 240),
            ("24 hours", 1440),
        ):
            self.duration.addItem(label, minutes)
        self.duration.setCurrentIndex(1)
        self.max_uses = QSpinBox()
        self.max_uses.setObjectName("guardApprovalMaxUses")
        self.max_uses.setRange(1, 10)
        self.max_uses.setValue(1)
        form.addRow("Protected target", self.target_label)
        form.addRow("Approved by", self.approved_by)
        form.addRow("Reason", self.reason)
        form.addRow("Expires after", self.duration)
        form.addRow("Maximum uses", self.max_uses)
        self.create_section.add_layout(form)
        self.create_button = QPushButton("Create exception approval")
        self.create_button.setObjectName("dialogPrimaryAction")
        self.create_button.setIcon(action_icon("save"))
        self.create_button.clicked.connect(self.create_exception)
        self.create_section.add_widget(self.create_button)
        self.workspace.add_body_widget(self.create_section)

        archive = DialogSection(
            "Approval archive",
            "Expired, consumed and revoked records remain visible for audit but cannot authorize another launch.",
        )
        self.table = QTableWidget(0, 8)
        self.table.setObjectName("generationLaunchGuardApprovalTable")
        self.table.setHorizontalHeaderLabels(
            [
                "Status",
                "Created",
                "Expires",
                "Approved by",
                "Uses",
                "Changes",
                "Fingerprint",
                "Approval ID",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setMinimumHeight(260)
        self.table.horizontalHeader().setStretchLastSection(True)
        archive.add_widget(self.table, 1)
        self.workspace.add_body_widget(archive, 1)

        tools = QHBoxLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(action_icon("general.refresh"))
        self.revoke_button = QPushButton("Revoke selected")
        self.revoke_button.setIcon(action_icon("general.clear"))
        self.copy_button = QPushButton("Copy approval ID")
        self.copy_button.setIcon(action_icon("general.copy"))
        self.refresh_button.clicked.connect(self.refresh)
        self.revoke_button.clicked.connect(self.revoke_selected)
        self.copy_button.clicked.connect(self.copy_selected_id)
        tools.addWidget(self.refresh_button)
        tools.addWidget(self.revoke_button)
        tools.addWidget(self.copy_button)
        tools.addStretch(1)
        archive.add_layout(tools)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setWordWrap(True)
        self.workspace.add_footer_widget(self.status_label, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.accept)
        self.workspace.add_footer_widget(close_button)

        has_target = bool(
            self.confirmation is not None
            and self.confirmation.guard_candidate_fingerprint
            and self.confirmation.guard_baseline_receipt_id
            and self.confirmation.guard_change_keys
        )
        self.create_section.setVisible(has_target)
        if has_target and self.confirmation is not None:
            self.target_label.setText(
                f"Project: {self.project_name}\n"
                f"Baseline: {self.confirmation.guard_baseline_receipt_id}\n"
                f"Fingerprint: {self.confirmation.guard_candidate_fingerprint}\n"
                f"Protected changes: {', '.join(self.confirmation.guard_change_keys)}"
            )
        else:
            self.target_label.clear()

        self.table.itemSelectionChanged.connect(self._update_action_state)

    def refresh(self) -> None:
        self.approvals = self.service.list_guard_approvals(
            project_name=self.project_name or None,
            include_expired=True,
        )
        self.table.setRowCount(len(self.approvals))
        for row, approval in enumerate(self.approvals):
            values = (
                approval.status.title(),
                self._display_time(approval.created_at),
                self._display_time(approval.expires_at),
                approval.approved_by,
                f"{approval.used_count}/{approval.max_uses}",
                f"{len(approval.protected_change_keys):,}",
                approval.launch_fingerprint[:12],
                approval.approval_id,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column in {0, 4, 5}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        active = sum(item.status == "approved" for item in self.approvals)
        self.summary_card.update_status(
            f"{active:,} active exception approval(s)",
            f"{len(self.approvals):,} total approval record(s) for {self.project_name or 'all projects'}.",
            tone="warning" if active else "info",
        )
        self._update_action_state()

    def selected_approval(self) -> GenerationLaunchGuardApproval | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        row = rows[0].row()
        return self.approvals[row] if 0 <= row < len(self.approvals) else None

    def create_exception(self) -> GenerationLaunchGuardApproval | None:
        confirmation = self.confirmation
        if confirmation is None:
            return None
        try:
            approval = self.service.create_guard_approval(
                project_name=self.project_name,
                launch_fingerprint=confirmation.guard_candidate_fingerprint,
                baseline_receipt_id=confirmation.guard_baseline_receipt_id,
                protected_change_keys=confirmation.guard_change_keys,
                reason=self.reason.toPlainText(),
                approved_by=self.approved_by.text(),
                duration_minutes=int(self.duration.currentData() or 60),
                max_uses=self.max_uses.value(),
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None
        self.created_approval = approval
        self.status_label.setText(
            f"Exception {approval.approval_id} created. Re-run launch review to apply it."
        )
        self.refresh()
        return approval

    def revoke_selected(self) -> bool:
        approval = self.selected_approval()
        if approval is None:
            self.status_label.setText("Select an approval to revoke.")
            return False
        changed = self.service.revoke_guard_approval(approval.approval_id)
        self.status_label.setText(
            "Approval revoked." if changed else "The selected approval is already inactive."
        )
        self.refresh()
        return changed

    def copy_selected_id(self) -> None:
        approval = self.selected_approval()
        if approval is None:
            return
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(approval.approval_id)
        self.status_label.setText("Approval ID copied.")

    def _update_action_state(self) -> None:
        selected = self.selected_approval()
        self.revoke_button.setEnabled(selected is not None and selected.status == "approved")
        self.copy_button.setEnabled(selected is not None)

    @staticmethod
    def _display_time(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return value or "—"
