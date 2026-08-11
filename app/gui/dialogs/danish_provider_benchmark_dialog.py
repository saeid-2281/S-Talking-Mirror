from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from app.gui.icons import action_icon
from app.gui.widgets.dialog_workspace import DialogSection, DialogStatusCard, DialogWorkspace
from app.models.danish_provider_benchmark import DanishBenchmarkRating
from app.services.danish_provider_benchmark_service import DanishProviderBenchmarkService


class DanishProviderBenchmarkDialog(QDialog):
    """Human-reviewed Danish provider benchmark/certification workspace."""

    openCatalogRequested = Signal(str)

    def __init__(
        self,
        service: DanishProviderBenchmarkService,
        parent: QWidget | None = None,
        *,
        open_path: Callable[[Path], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.open_path = open_path
        self._rating_widgets: dict[tuple[str, str], QSpinBox] = {}
        self.setObjectName("danishProviderBenchmarkDialog")
        self.setWindowTitle("Danish Provider Benchmark / Certification")
        self.resize(1500, 920)
        self.setMinimumSize(1080, 720)
        self._build()
        self.refresh_view()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        self.workspace = DialogWorkspace(
            "Danish Provider Benchmark / Certification",
            "Separate documented Danish support from human-reviewed voice/model quality certification. The workspace never synthesizes, switches provider, or spends credits automatically.",
            icon_name="report",
            parent=self,
        )
        root.addWidget(self.workspace)
        self.overall = DialogStatusCard("Loading Danish benchmark", "", tone="info")
        self.workspace.add_body_widget(self.overall)

        tabs = QTabWidget()
        tabs.addTab(self._provider_tab(), "Provider status")
        tabs.addTab(self._benchmark_tab(), "Benchmark selected provider")
        self.workspace.add_body_widget(tabs)

        buttons = QHBoxLayout()
        refresh = QPushButton(action_icon("general.refresh"), "Refresh")
        refresh.clicked.connect(self.refresh_view)
        buttons.addWidget(refresh)
        export = QPushButton(action_icon("save"), "Export fixed corpus")
        export.clicked.connect(self.export_corpus)
        buttons.addWidget(export)
        open_folder = QPushButton(action_icon("project.output_folder"), "Open evidence folder")
        open_folder.clicked.connect(lambda: self._open(self.service.root))
        buttons.addWidget(open_folder)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        buttons.addWidget(close)
        self.workspace.footer_layout.addLayout(buttons)

    def _provider_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        section = DialogSection(
            "Danish certification matrix",
            "Documented support is evidence only. Certified requires a verified human benchmark record for the selected voice/model.",
        )
        self.providers = QTableWidget(0, 7)
        self.providers.setHorizontalHeaderLabels(
            ["Provider", "Documentation", "Certification", "Score", "Cases", "Voice / model", "Evidence"]
        )
        self.providers.setEditTriggers(QTableWidget.NoEditTriggers)
        self.providers.setSelectionBehavior(QTableWidget.SelectRows)
        self.providers.setSelectionMode(QTableWidget.SingleSelection)
        self.providers.itemSelectionChanged.connect(self._provider_selection_changed)
        self.providers.horizontalHeader().setStretchLastSection(True)
        section.add_widget(self.providers)
        layout.addWidget(section)
        return page

    def _benchmark_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        identity = DialogSection(
            "Human review identity",
            "Use one provider, voice and model consistently across the fixed corpus. Scores are 1–5 and are saved as tamper-evident JSON evidence.",
        )
        form = QFormLayout()
        self.selected_provider = QLabel("Select a provider in the status tab")
        self.selected_provider.setTextInteractionFlags(Qt.TextSelectableByMouse)
        form.addRow("Provider", self.selected_provider)
        self.reviewer = QLineEdit()
        self.reviewer.setPlaceholderText("Reviewer name or role")
        form.addRow("Reviewer", self.reviewer)
        self.voice_id = QLineEdit()
        self.voice_id.setPlaceholderText("Voice ID used for all samples")
        form.addRow("Voice", self.voice_id)
        self.model_id = QLineEdit()
        self.model_id.setPlaceholderText("Model ID used for all samples")
        form.addRow("Model", self.model_id)
        identity.add_layout(form)
        layout.addWidget(identity)

        cases = DialogSection(
            "Fixed Danish corpus",
            "Generate/listen to these exact texts with the chosen provider settings, then rate intelligibility, pronunciation, prosody and stability.",
        )
        self.cases = QTableWidget(len(self.service.CORPUS), 8)
        self.cases.setHorizontalHeaderLabels(
            ["ID", "Category", "Text", "Critical", "Intelligibility", "Pronunciation", "Prosody", "Stability"]
        )
        self.cases.setEditTriggers(QTableWidget.NoEditTriggers)
        self.cases.horizontalHeader().setStretchLastSection(True)
        for row, case in enumerate(self.service.CORPUS):
            self.cases.setItem(row, 0, QTableWidgetItem(case.case_id))
            self.cases.setItem(row, 1, QTableWidgetItem(case.category))
            self.cases.setItem(row, 2, QTableWidgetItem(case.text))
            self.cases.setItem(row, 3, QTableWidgetItem("Yes" if case.critical else "No"))
            for column, metric in enumerate(("intelligibility", "pronunciation", "prosody", "stability"), start=4):
                spin = QSpinBox()
                spin.setRange(1, 5)
                spin.setValue(4)
                spin.setToolTip(case.guidance)
                self.cases.setCellWidget(row, column, spin)
                self._rating_widgets[(case.case_id, metric)] = spin
        self.cases.resizeColumnsToContents()
        cases.add_widget(self.cases)
        layout.addWidget(cases)

        actions = QHBoxLayout()
        catalog = QPushButton(action_icon("provider.browse_voices"), "Open Voice & Model Catalog")
        catalog.clicked.connect(self._open_catalog)
        actions.addWidget(catalog)
        certify = QPushButton(action_icon("success"), "Save human-reviewed certification")
        certify.clicked.connect(self.save_certification)
        actions.addWidget(certify)
        actions.addStretch(1)
        layout.addLayout(actions)
        return page

    def refresh_view(self) -> None:
        snapshot = self.service.snapshot()
        self.overall.update_status(
            "DANISH BENCHMARK",
            f"{snapshot.certified_count} certified · {snapshot.blocked_count} not certified · "
            f"{len(snapshot.providers)} providers · fixed corpus {len(snapshot.cases)} cases",
            tone="success" if snapshot.certified_count else "info",
        )
        self.providers.setRowCount(len(snapshot.providers))
        for row, item in enumerate(snapshot.providers):
            evidence = self.service.documentation_for(item.provider_id)
            values = (
                item.provider_name,
                evidence.label,
                item.status.replace("_", " ").title(),
                "—" if item.score is None else f"{item.score:.1f}",
                f"{item.case_count}/{item.minimum_cases}",
                " / ".join(value for value in (item.voice_id, item.model_id) if value) or "—",
                Path(item.evidence_path).name if item.evidence_path else evidence.source_label,
            )
            for column, value in enumerate(values):
                cell = QTableWidgetItem(str(value))
                cell.setData(Qt.UserRole, item.provider_id)
                self.providers.setItem(row, column, cell)
        self.providers.resizeColumnsToContents()
        if self.providers.rowCount() and self.providers.currentRow() < 0:
            self.providers.selectRow(0)

    def _selected_provider_id(self) -> str:
        row = self.providers.currentRow()
        if row < 0:
            return ""
        item = self.providers.item(row, 0)
        return str(item.data(Qt.UserRole) or "") if item else ""

    def _provider_selection_changed(self) -> None:
        provider_id = self._selected_provider_id()
        if not provider_id:
            return
        evidence = self.service.documentation_for(provider_id)
        manifest = self.service.registry.manifest_for(provider_id)
        self.selected_provider.setText(
            f"{manifest.display_name} ({provider_id}) · {evidence.label} · reviewed {evidence.checked_on}"
        )
        current = self.service.latest_certification(provider_id)
        if current.voice_id:
            self.voice_id.setText(current.voice_id)
        if current.model_id:
            self.model_id.setText(current.model_id)

    def _open_catalog(self) -> None:
        provider_id = self._selected_provider_id()
        if provider_id:
            self.openCatalogRequested.emit(provider_id)

    def save_certification(self) -> None:
        provider_id = self._selected_provider_id()
        if not provider_id:
            QMessageBox.warning(self, "No provider selected", "Select a provider first.")
            return
        ratings = []
        for case in self.service.CORPUS:
            ratings.append(
                DanishBenchmarkRating(
                    case.case_id,
                    self._rating_widgets[(case.case_id, "intelligibility")].value(),
                    self._rating_widgets[(case.case_id, "pronunciation")].value(),
                    self._rating_widgets[(case.case_id, "prosody")].value(),
                    self._rating_widgets[(case.case_id, "stability")].value(),
                )
            )
        try:
            result = self.service.save_evaluation(
                provider_id,
                ratings,
                reviewer=self.reviewer.text(),
                voice_id=self.voice_id.text(),
                model_id=self.model_id.text(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Certification not saved", str(exc))
            return
        self.refresh_view()
        QMessageBox.information(
            self,
            "Danish certification saved",
            f"{result.provider_name}: {result.status.replace('_', ' ').title()} · "
            f"score {result.score or 0:.1f}/100",
        )

    def export_corpus(self) -> None:
        path = self.service.export_corpus()
        QMessageBox.information(self, "Benchmark corpus exported", str(path))

    def _open(self, path: Path) -> None:
        if self.open_path is not None:
            self.open_path(Path(path))
