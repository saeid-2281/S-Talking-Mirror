from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
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


class GenerationLaunchGuardApprovalRenewDialog(QDialog):
    """Collect operator details for a replacement approval version."""

    def __init__(
        self,
        approval: GenerationLaunchGuardApproval,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.approval = approval
        self.values: dict[str, object] | None = None
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationLaunchGuardApprovalRenewDialog")
        self.setWindowTitle("Renew exception approval")
        self.resize(620, 430)
        self.setMinimumSize(520, 380)
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        workspace = DialogWorkspace(
            "Renew exception approval",
            "Create a new immutable approval version while preserving the original audit record.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(workspace)
        summary = DialogStatusCard(
            self.approval.approval_id,
            f"{self.approval.project_name} · {self.approval.status.title()} · "
            f"{self.approval.used_count}/{self.approval.max_uses} uses",
            tone="warning",
        )
        workspace.add_body_widget(summary)
        section = DialogSection(
            "Replacement approval",
            "The launch fingerprint, baseline receipt and protected change set remain unchanged.",
        )
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(8)
        self.approved_by = QLineEdit(self.approval.approved_by)
        self.approved_by.setObjectName("guardApprovalRenewedBy")
        self.reason = QPlainTextEdit()
        self.reason.setObjectName("guardApprovalRenewReason")
        self.reason.setPlainText(f"Renewed approval for: {self.approval.reason}")
        self.reason.setMinimumHeight(90)
        self.duration = QComboBox()
        self.duration.setObjectName("guardApprovalRenewDuration")
        for label, minutes in (
            ("15 minutes", 15),
            ("1 hour", 60),
            ("4 hours", 240),
            ("24 hours", 1440),
        ):
            self.duration.addItem(label, minutes)
        self.duration.setCurrentIndex(1)
        self.max_uses = QSpinBox()
        self.max_uses.setObjectName("guardApprovalRenewMaxUses")
        self.max_uses.setRange(1, 10)
        self.max_uses.setValue(self.approval.max_uses)
        form.addRow("Approved by", self.approved_by)
        form.addRow("Reason", self.reason)
        form.addRow("Expires after", self.duration)
        form.addRow("Maximum uses", self.max_uses)
        section.add_layout(form)
        workspace.add_body_widget(section)
        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        workspace.add_footer_widget(self.status_label, 1)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        submit = QPushButton("Create renewed approval")
        submit.setObjectName("dialogPrimaryAction")
        submit.setIcon(action_icon("save"))
        submit.clicked.connect(self.submit)
        workspace.add_footer_widget(cancel)
        workspace.add_footer_widget(submit)

    def submit(self) -> bool:
        approved_by = self.approved_by.text().strip()
        reason = self.reason.toPlainText().strip()
        if not approved_by:
            self.status_label.setText("Approved by is required.")
            return False
        if len(reason) < 8:
            self.status_label.setText("Provide a renewal reason of at least 8 characters.")
            return False
        self.values = {
            "approved_by": approved_by,
            "reason": reason,
            "duration_minutes": int(self.duration.currentData() or 60),
            "max_uses": self.max_uses.value(),
        }
        self.accept()
        return True


class GenerationLaunchGuardApprovalDialog(QDialog):
    """Search, audit, renew and revoke launch guard exception approvals."""

    def __init__(
        self,
        service: GenerationLaunchReceiptService,
        project_name: str,
        parent: QWidget | None = None,
        *,
        confirmation: GenerationConfirmation | None = None,
        export_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.project_name = str(project_name or "").strip()
        self.confirmation = confirmation
        self.export_dir = Path(export_dir or service.reports_dir / "launch-approvals")
        self.all_approvals: list[GenerationLaunchGuardApproval] = []
        self.approvals: list[GenerationLaunchGuardApproval] = []
        self.created_approval: GenerationLaunchGuardApproval | None = None
        self.renew_dialogs: list[GenerationLaunchGuardApprovalRenewDialog] = []
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setObjectName("generationLaunchGuardApprovalDialog")
        self.setWindowTitle("Launch approval operations")
        self.resize(1180, 790)
        self.setMinimumSize(760, 540)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Launch approval operations",
            "Search exception approvals, inspect their audit trail, renew exact scopes and revoke active access.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)

        filters_section = DialogSection(
            "Find approvals",
            "Filter by project or lifecycle state. Search checks IDs, fingerprints, approvers, reasons and protected changes.",
        )
        filters = QGridLayout()
        filters.setContentsMargins(0, 0, 0, 0)
        filters.setHorizontalSpacing(8)
        filters.setVerticalSpacing(8)
        self.project_filter = QComboBox()
        self.project_filter.setObjectName("guardApprovalProjectFilter")
        self.project_filter.addItem("All projects", "")
        self.status_filter = QComboBox()
        self.status_filter.setObjectName("guardApprovalStatusFilter")
        self.status_filter.addItem("All states", "")
        for label, value in (
            ("Active", "approved"),
            ("Expired", "expired"),
            ("Consumed", "consumed"),
            ("Revoked", "revoked"),
        ):
            self.status_filter.addItem(label, value)
        self.search = QLineEdit()
        self.search.setObjectName("guardApprovalSearch")
        self.search.setPlaceholderText("Search approval, fingerprint, approver, reason or change…")
        self.search.setClearButtonEnabled(True)
        self.refresh_button = QPushButton("Refresh")
        self.refresh_button.setIcon(action_icon("general.refresh"))
        filters.addWidget(self.project_filter, 0, 0)
        filters.addWidget(self.status_filter, 0, 1)
        filters.addWidget(self.search, 1, 0, 1, 2)
        filters.addWidget(self.refresh_button, 1, 2)
        filters.setColumnStretch(1, 1)
        filters_section.add_layout(filters)
        self.workspace.add_body_widget(filters_section)

        self.summary_card = DialogStatusCard(
            "No approvals loaded",
            "Operational metrics update after filters are applied.",
            tone="info",
        )
        self.summary_card.setObjectName("generationLaunchGuardApprovalSummary")
        metrics = QHBoxLayout()
        metrics.setContentsMargins(0, 7, 0, 0)
        metrics.setSpacing(7)
        self.metric_values: dict[str, QLabel] = {}
        for key, caption in (
            ("total", "Approvals"),
            ("active", "Active"),
            ("expired", "Expired"),
            ("consumed", "Consumed"),
            ("revoked", "Revoked"),
        ):
            card = QFrame()
            card.setObjectName("historyMetricCard")
            layout = QVBoxLayout(card)
            layout.setContentsMargins(10, 7, 10, 7)
            layout.setSpacing(1)
            label = QLabel(caption)
            label.setObjectName("historyMetricCaption")
            value = QLabel("—")
            value.setObjectName("historyMetricValue")
            layout.addWidget(label)
            layout.addWidget(value)
            self.metric_values[key] = value
            metrics.addWidget(card, 1)
        self.summary_card.layout().addLayout(metrics)
        self.workspace.add_body_widget(self.summary_card)

        self.create_section = DialogSection(
            "Approve the blocked launch",
            "The approval is bound to one exact launch target and consumed only after a receipt is written successfully.",
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
            "Original approvals remain immutable. Renewal creates a linked replacement record instead of editing history.",
        )
        self.table = QTableWidget(0, 10)
        self.table.setObjectName("generationLaunchGuardApprovalTable")
        self.table.setHorizontalHeaderLabels(
            [
                "Status",
                "Project",
                "Created",
                "Expires",
                "Approved by",
                "Uses",
                "Launches",
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

        details_section = DialogSection(
            "Selected approval",
            "Review the exact scope, linked launch receipts and lifecycle events before taking action.",
        )
        self.details = QPlainTextEdit()
        self.details.setObjectName("generationLaunchGuardApprovalDetails")
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(120)
        self.details.setMaximumHeight(180)
        self.details.setPlaceholderText("Select an approval to inspect its audit trail.")
        details_section.add_widget(self.details)
        self.workspace.add_body_widget(details_section)

        tools = QGridLayout()
        tools.setContentsMargins(0, 0, 0, 0)
        tools.setHorizontalSpacing(8)
        tools.setVerticalSpacing(8)
        self.renew_button = QPushButton("Renew selected")
        self.revoke_button = QPushButton("Revoke selected")
        self.copy_button = QPushButton("Copy approval ID")
        self.export_button = QPushButton("Export filtered approvals")
        for index, (button, icon_name) in enumerate(
            (
                (self.renew_button, "save"),
                (self.revoke_button, "general.clear"),
                (self.copy_button, "general.copy"),
                (self.export_button, "save"),
            )
        ):
            button.setObjectName("historyToolAction")
            button.setIcon(action_icon(icon_name))
            button.setMinimumHeight(34)
            tools.addWidget(button, index // 2, index % 2)
        tools.setColumnStretch(0, 1)
        tools.setColumnStretch(1, 1)
        details_section.add_layout(tools)

        self.status_label = QLabel("Ready")
        self.status_label.setObjectName("historyStatusLabel")
        self.status_label.setWordWrap(True)
        self.workspace.add_footer_widget(self.status_label, 1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
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

        self.refresh_button.clicked.connect(self.refresh)
        self.project_filter.currentIndexChanged.connect(self.apply_filters)
        self.status_filter.currentIndexChanged.connect(self.apply_filters)
        self.search.textChanged.connect(self.apply_filters)
        self.table.itemSelectionChanged.connect(self.update_details)
        self.renew_button.clicked.connect(self.open_renew_dialog)
        self.revoke_button.clicked.connect(self.revoke_selected)
        self.copy_button.clicked.connect(self.copy_selected_id)
        self.export_button.clicked.connect(self.export_filtered)

    def refresh(self) -> None:
        self.all_approvals = self.service.list_guard_approvals(include_expired=True)
        selected_project = str(self.project_filter.currentData() or "")
        projects = sorted({item.project_name for item in self.all_approvals if item.project_name})
        if (
            self.project_name not in {"", "all-projects"}
            and self.project_name not in projects
        ):
            projects.append(self.project_name)
            projects.sort()
        self.project_filter.blockSignals(True)
        self.project_filter.clear()
        self.project_filter.addItem("All projects", "")
        for project in projects:
            self.project_filter.addItem(project, project)
        preferred = selected_project
        if not preferred and self.project_name not in {"", "all-projects"}:
            preferred = self.project_name
        index = self.project_filter.findData(preferred)
        self.project_filter.setCurrentIndex(max(0, index))
        self.project_filter.blockSignals(False)
        self.apply_filters()

    def apply_filters(self) -> None:
        project = str(self.project_filter.currentData() or "")
        status = str(self.status_filter.currentData() or "")
        key = self.search.text().strip().casefold()
        records = self.all_approvals
        if project:
            records = [item for item in records if item.project_name.casefold() == project.casefold()]
        if status:
            records = [item for item in records if item.status == status]
        if key:
            records = [
                item
                for item in records
                if key
                in " ".join(
                    (
                        item.approval_id,
                        item.project_name,
                        item.launch_fingerprint,
                        item.baseline_receipt_id,
                        item.approved_by,
                        item.reason,
                        item.status,
                        item.renewed_from_id,
                        " ".join(item.protected_change_keys),
                    )
                ).casefold()
            ]
        self.approvals = list(records)
        self._render_table()
        self._render_summary()
        self.update_details()

    def _render_table(self) -> None:
        self.table.setRowCount(len(self.approvals))
        for row, approval in enumerate(self.approvals):
            receipt_count = len(self.service.receipts_for_guard_approval(approval.approval_id))
            values = (
                approval.status.title(),
                approval.project_name,
                self._display_time(approval.created_at),
                self._display_time(approval.expires_at),
                approval.approved_by,
                f"{approval.used_count}/{approval.max_uses}",
                f"{receipt_count:,}",
                f"{len(approval.protected_change_keys):,}",
                approval.launch_fingerprint[:12],
                approval.approval_id,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                if column in {0, 5, 6, 7}:
                    item.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.table.horizontalHeader().setStretchLastSection(True)

    def _render_summary(self) -> None:
        summary = self.service.guard_approval_summary(self.approvals)
        self.metric_values["total"].setText(f"{summary.total_count:,}")
        self.metric_values["active"].setText(f"{summary.active_count:,}")
        self.metric_values["expired"].setText(f"{summary.expired_count:,}")
        self.metric_values["consumed"].setText(f"{summary.consumed_count:,}")
        self.metric_values["revoked"].setText(f"{summary.revoked_count:,}")
        tone = "warning" if summary.active_count else ("info" if summary.total_count else "info")
        self.summary_card.update_status(
            f"{summary.active_count:,} active approval(s)",
            f"{summary.total_count:,} filtered record(s) across {summary.project_count:,} project(s) · "
            f"{summary.used_count:,}/{summary.authorized_uses:,} authorized uses consumed.",
            tone=tone,
        )
        self.status_label.setText(f"Showing {summary.total_count:,} approval record(s).")

    def selected_approval(self) -> GenerationLaunchGuardApproval | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        row = rows[0].row()
        return self.approvals[row] if 0 <= row < len(self.approvals) else None

    def update_details(self) -> None:
        approval = self.selected_approval()
        if approval is None:
            self.details.clear()
            self._update_action_state()
            return
        receipts = self.service.receipts_for_guard_approval(approval.approval_id)
        receipt_ids = ", ".join(item.receipt_id for item in receipts if item.receipt_id) or "None"
        events = approval.audit_events
        event_lines = [
            f"- {event.action.title()} · {self._display_time(event.occurred_at)} · "
            f"{event.actor or 'system'}"
            + (f" · Receipt {event.receipt_id}" if event.receipt_id else "")
            for event in events
        ]
        self.details.setPlainText(
            "\n".join(
                (
                    f"Approval ID: {approval.approval_id}",
                    f"Project / status: {approval.project_name} / {approval.status}",
                    f"Approved by: {approval.approved_by}",
                    f"Created / expires: {approval.created_at} / {approval.expires_at}",
                    f"Uses: {approval.used_count}/{approval.max_uses} · Remaining: {approval.remaining_uses}",
                    f"Baseline receipt: {approval.baseline_receipt_id}",
                    f"Launch fingerprint: {approval.launch_fingerprint}",
                    f"Protected changes: {', '.join(approval.protected_change_keys)}",
                    f"Reason: {approval.reason}",
                    f"Renewed from: {approval.renewed_from_id or 'Original approval'}",
                    f"Linked launch receipts: {receipt_ids}",
                    "Audit events:",
                    *(event_lines or ["- No lifecycle events recorded (legacy approval record)."]),
                )
            )
        )
        self._update_action_state()

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
        self.status_label.setText(f"Exception {approval.approval_id} created.")
        self.refresh()
        return approval

    def renew_approval(
        self,
        approval: GenerationLaunchGuardApproval,
        *,
        approved_by: str,
        reason: str,
        duration_minutes: int = 60,
        max_uses: int | None = None,
    ) -> GenerationLaunchGuardApproval | None:
        try:
            renewed = self.service.renew_guard_approval(
                approval.approval_id,
                approved_by=approved_by,
                reason=reason,
                duration_minutes=duration_minutes,
                max_uses=max_uses,
            )
        except ValueError as exc:
            self.status_label.setText(str(exc))
            return None
        self.status_label.setText(
            f"Renewed approval {renewed.approval_id} created from {approval.approval_id}."
        )
        self.refresh()
        return renewed

    def open_renew_dialog(self) -> GenerationLaunchGuardApprovalRenewDialog | None:
        approval = self.selected_approval()
        if approval is None:
            self.status_label.setText("Select an approval to renew.")
            return None
        dialog = GenerationLaunchGuardApprovalRenewDialog(approval, self)
        self.renew_dialogs.append(dialog)
        dialog.finished.connect(self._renew_dialog_finished)
        dialog.show()
        return dialog

    def _renew_dialog_finished(self, result: int) -> None:
        dialog = self.sender()
        if not isinstance(dialog, GenerationLaunchGuardApprovalRenewDialog):
            return
        if result == QDialog.Accepted and dialog.values:
            self.renew_approval(dialog.approval, **dialog.values)
        if dialog in self.renew_dialogs:
            self.renew_dialogs.remove(dialog)

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

    def export_filtered(self) -> tuple[Path, Path] | None:
        if not self.approvals:
            self.status_label.setText("No filtered approvals are available to export.")
            return None
        project = str(self.project_filter.currentData() or "all-projects")
        paths = self.service.export_guard_approvals(
            self.approvals,
            self.export_dir,
            project_name=project,
        )
        self.status_label.setText(f"Exported {len(self.approvals):,} approval record(s).")
        return paths

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
        self.renew_button.setEnabled(selected is not None)
        self.copy_button.setEnabled(selected is not None)
        self.export_button.setEnabled(bool(self.approvals))

    @staticmethod
    def _display_time(value: str) -> str:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone().strftime("%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            return value or "—"
