from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from app.models.pronunciation_assurance import PronunciationAssessment


class LanguageProbeDialog(QDialog):
    """Manual 1-3 sample review for language-locked pronunciation evidence.

    This dialog never synthesizes audio and never changes provider, account,
    voice, model, or language. Preview requests only ask the host to preload the
    existing Voice Browser; the user must start playback explicitly there.
    """

    previewRequested = Signal(int, str)
    overrideRequested = Signal(int, str)

    def __init__(
        self,
        assessments: tuple[PronunciationAssessment, ...],
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not 1 <= len(assessments) <= 3:
            raise ValueError("Language Probe requires between 1 and 3 selected jobs.")
        self.assessments = assessments
        self.setWindowTitle("Language Probe · manual pronunciation review")
        self.resize(760, min(720, 260 + len(assessments) * 180))

        root = QVBoxLayout(self)
        title = QLabel("Language Probe")
        title.setObjectName("dialogTitle")
        root.addWidget(title)
        help_text = QLabel(
            "Review up to three samples using the already selected target language. "
            "No language detection, provider/model/voice switching, or automatic audio preview occurs here."
        )
        help_text.setWordWrap(True)
        help_text.setObjectName("dialogSubtitle")
        root.addWidget(help_text)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        for assessment in assessments:
            content_layout.addWidget(self._assessment_card(assessment))
        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)
        buttons.addWidget(close_button)
        root.addLayout(buttons)

    def _assessment_card(self, assessment: PronunciationAssessment) -> QFrame:
        card = QFrame()
        card.setObjectName("languageProbeCard")
        layout = QVBoxLayout(card)
        row_text = f"Row {assessment.row}" if assessment.row is not None else "Sample"
        heading = QLabel(
            f"{row_text} · Language {assessment.language or 'not set'} · "
            f"{assessment.risk_level.title()} risk"
        )
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)

        flags = ", ".join(assessment.flags) if assessment.flags else "plain prose"
        detail = QLabel(f"Risk signals: {flags}")
        detail.setWordWrap(True)
        layout.addWidget(detail)

        original = QLabel(f"Original: {assessment.original_text}")
        original.setWordWrap(True)
        original.setTextInteractionFlags(original.textInteractionFlags())
        layout.addWidget(original)

        if assessment.normalization_safe:
            normalized = QLabel(
                f"Language-locked normalized form ({assessment.normalization_kind}): "
                f"{assessment.normalized_text}"
            )
        else:
            normalized = QLabel("Language-locked normalized form: not safely available")
        normalized.setWordWrap(True)
        layout.addWidget(normalized)

        actions = QHBoxLayout()
        preview_original = QPushButton("Preview original")
        preview_original.clicked.connect(
            lambda _checked=False, item=assessment: self.previewRequested.emit(
                int(item.row or 0), item.original_text
            )
        )
        actions.addWidget(preview_original)

        if assessment.normalization_safe:
            preview_normalized = QPushButton("Preview normalized")
            preview_normalized.clicked.connect(
                lambda _checked=False, item=assessment: self.previewRequested.emit(
                    int(item.row or 0), item.normalized_text
                )
            )
            actions.addWidget(preview_normalized)
            apply_normalized = QPushButton("Use normalized for this job")
            apply_normalized.clicked.connect(
                lambda _checked=False, item=assessment: self.overrideRequested.emit(
                    int(item.row or 0), "normalized"
                )
            )
            actions.addWidget(apply_normalized)

        keep_original = QPushButton("Keep original")
        keep_original.clicked.connect(
            lambda _checked=False, item=assessment: self.overrideRequested.emit(
                int(item.row or 0), "original"
            )
        )
        actions.addWidget(keep_original)
        layout.addLayout(actions)
        return card
