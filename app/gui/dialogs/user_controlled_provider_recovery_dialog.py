from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.models.provider_recovery import ProviderRecoveryAssessment, ProviderRecoveryCandidate


class UserControlledProviderRecoveryDialog(QDialog):
    """Review alternate routes without changing provider or restarting generation."""

    reviewProviderRequested = Signal(str, str)
    prepareProviderRequested = Signal(str, str)
    retryCurrentRequested = Signal()

    def __init__(self, assessment: ProviderRecoveryAssessment, parent=None) -> None:
        super().__init__(parent)
        self.assessment = assessment
        self.setWindowTitle("User-Controlled Multi-Provider Recovery")
        self.resize(980, 650)
        self._build_ui()
        self._render()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        title = QLabel("User-Controlled Multi-Provider Recovery")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        policy = QLabel(
            "S-Talking will not switch provider, retry failed jobs, refresh provider catalogs, "
            "or restart generation automatically. Review an alternate route, apply its account/voice/model "
            "explicitly, then prepare recovery and run preflight before starting generation yourself."
        )
        policy.setWordWrap(True)
        root.addWidget(policy)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        root.addWidget(self.summary)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Rank", "Provider", "State", "Score", "Language", "Account", "Evidence"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.detail = QLabel("Select an alternate provider to inspect recovery evidence.")
        self.detail.setWordWrap(True)
        root.addWidget(self.detail)

        actions = QHBoxLayout()
        self.review_button = QPushButton("Review selected alternate")
        self.prepare_button = QPushButton("Prepare selected route")
        self.retry_current_button = QPushButton("Retry current provider")
        actions.addWidget(self.review_button)
        actions.addWidget(self.prepare_button)
        actions.addWidget(self.retry_current_button)
        actions.addStretch(1)
        root.addLayout(actions)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

        self.table.itemSelectionChanged.connect(self._selection_changed)
        self.table.itemDoubleClicked.connect(lambda _item: self.review_selected())
        self.review_button.clicked.connect(self.review_selected)
        self.prepare_button.clicked.connect(self.prepare_selected)
        self.retry_current_button.clicked.connect(self.retryCurrentRequested.emit)

    def _render(self) -> None:
        self.summary.setText(
            f"Current provider: {self.assessment.current_provider_name} · "
            f"failed jobs: {len(self.assessment.failed_rows):,} · "
            f"pending jobs: {len(self.assessment.pending_rows):,} · "
            f"recovery scope: {self.assessment.scoped_jobs:,} jobs / "
            f"{self.assessment.scoped_characters:,} characters\n"
            f"Failure: {self.assessment.failure_summary or 'No failure detail supplied.'}"
        )
        self.table.setRowCount(len(self.assessment.candidates))
        for row, candidate in enumerate(self.assessment.candidates):
            state = "Ready" if candidate.actionable else "Blocked / review"
            values = (
                candidate.rank,
                candidate.provider_name,
                state,
                candidate.score,
                candidate.language_state,
                candidate.profile_name or candidate.account_state,
                candidate.evidence_text,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, candidate.provider_id)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        if self.assessment.recommended_provider_id:
            for row, candidate in enumerate(self.assessment.candidates):
                if candidate.provider_id == self.assessment.recommended_provider_id:
                    self.table.selectRow(row)
                    break
        self._selection_changed()

    def selected_candidate(self) -> ProviderRecoveryCandidate | None:
        row = self.table.currentRow()
        if row < 0 or row >= len(self.assessment.candidates):
            return None
        return self.assessment.candidates[row]

    def _selection_changed(self) -> None:
        candidate = self.selected_candidate()
        enabled = bool(candidate and candidate.actionable)
        self.review_button.setEnabled(enabled)
        self.prepare_button.setEnabled(enabled)
        if candidate is None:
            self.detail.setText("Select an alternate provider to inspect recovery evidence.")
            return
        blockers = "; ".join(candidate.blockers) or "none"
        warnings = "; ".join(candidate.warnings) or "none"
        action = (
            "Offline voice review"
            if candidate.action_kind == "offline_voice_review"
            else "Account / voice / model catalog review"
        )
        self.detail.setText(
            f"{candidate.provider_name} · {action}\n"
            f"{candidate.detail}\nBlockers: {blockers}\nWarnings: {warnings}"
        )

    def review_selected(self) -> None:
        candidate = self.selected_candidate()
        if candidate is None or not candidate.actionable:
            return
        self.reviewProviderRequested.emit(candidate.provider_id, self.assessment.assessment_id)

    def prepare_selected(self) -> None:
        candidate = self.selected_candidate()
        if candidate is None or not candidate.actionable:
            return
        self.prepareProviderRequested.emit(candidate.provider_id, self.assessment.assessment_id)
