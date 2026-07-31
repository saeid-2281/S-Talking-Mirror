from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from app.models.generation_recovery import GenerationRecoverySnapshot


class GenerationRecoveryDialog(QDialog):
    RESUME_PENDING = 1
    RESUME_RETRY_FAILED = 2
    DISCARD = 3

    def __init__(
        self,
        snapshot: GenerationRecoverySnapshot,
        *,
        compatible: bool,
        incompatibility_reason: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.snapshot = snapshot
        self.choice = 0
        self.setWindowTitle("Recover interrupted generation")
        self.setModal(True)
        self.setMinimumWidth(520)

        root = QVBoxLayout(self)
        title = QLabel("An interrupted generation session was found.")
        title.setObjectName("dialogTitle")
        root.addWidget(title)

        description = QLabel(
            "Restore the saved queue and continue from the last safe checkpoint."
            if compatible
            else "This recovery snapshot does not match the current project or provider settings."
        )
        description.setWordWrap(True)
        root.addWidget(description)

        card = QFrame()
        card.setObjectName("recoverySummaryCard")
        form = QFormLayout(card)
        form.addRow("Saved", QLabel(self._saved_text(snapshot.saved_at)))
        form.addRow("Project", QLabel(snapshot.project_key or "—"))
        form.addRow("Provider", QLabel(snapshot.provider or "—"))
        form.addRow("API profile", QLabel(snapshot.profile_id or "Temporary key / no profile"))
        form.addRow("Model", QLabel(snapshot.model_id or "—"))
        form.addRow("Voice", QLabel(snapshot.voice_id or "—"))
        form.addRow("Output", QLabel(self._display_path(snapshot.output_dir)))
        form.addRow("Recoverable jobs", QLabel(f"{snapshot.resumable_jobs:,}"))
        form.addRow("Progress", QLabel(self._progress_text(snapshot)))
        root.addWidget(card)

        if not compatible:
            warning = QLabel(incompatibility_reason or "Open the matching project and restore its saved settings first.")
            warning.setObjectName("recoveryCompatibilityWarning")
            warning.setWordWrap(True)
            root.addWidget(warning)

        buttons = QDialogButtonBox()
        self.resume_button = QPushButton("Resume pending")
        self.retry_button = QPushButton("Resume + retry failed")
        self.discard_button = QPushButton("Discard snapshot")
        self.cancel_button = QPushButton("Not now")
        buttons.addButton(self.resume_button, QDialogButtonBox.AcceptRole)
        buttons.addButton(self.retry_button, QDialogButtonBox.AcceptRole)
        buttons.addButton(self.discard_button, QDialogButtonBox.DestructiveRole)
        buttons.addButton(self.cancel_button, QDialogButtonBox.RejectRole)
        self.resume_button.setEnabled(compatible and snapshot.resumable_jobs > 0)
        self.retry_button.setEnabled(compatible and snapshot.resumable_jobs > 0)
        self.resume_button.clicked.connect(lambda: self._finish(self.RESUME_PENDING))
        self.retry_button.clicked.connect(lambda: self._finish(self.RESUME_RETRY_FAILED))
        self.discard_button.clicked.connect(lambda: self._finish(self.DISCARD))
        self.cancel_button.clicked.connect(self.reject)
        root.addWidget(buttons)

    def _finish(self, choice: int) -> None:
        self.choice = choice
        self.accept()

    @staticmethod
    def _saved_text(value: str) -> str:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
        except ValueError:
            return value or "—"

    @staticmethod
    def _display_path(value: str) -> str:
        if not value:
            return "—"
        path = Path(value)
        return str(path) if len(str(path)) <= 72 else f"…{str(path)[-71:]}"

    @staticmethod
    def _progress_text(snapshot: GenerationRecoverySnapshot) -> str:
        session = snapshot.session
        completed = int(session.get("completed_jobs") or 0)
        total = int(session.get("total_jobs") or len(snapshot.jobs))
        percent = float(session.get("progress_percent") or 0.0)
        return f"{percent:.1f}% · {completed:,} of {total:,} completed"
