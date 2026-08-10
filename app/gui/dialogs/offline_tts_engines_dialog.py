from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.models import AppSettings
from app.models.offline_tts_engine import OfflineEngineInventory, OfflineVoiceDescriptor
from app.services.offline_tts_engine_service import OfflineTTSEngineService


class OfflineTTSEnginesDialog(QDialog):
    def __init__(
        self,
        service: OfflineTTSEngineService,
        settings_provider: Callable[[], AppSettings],
        *,
        apply_piper_voice: Callable[[str], None] | None = None,
        generation_active: Callable[[], bool] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.settings_provider = settings_provider
        self.apply_piper_voice = apply_piper_voice
        self.generation_active = generation_active or (lambda: False)
        self.inventory = OfflineEngineInventory(())
        self.setWindowTitle("Offline TTS Engines")
        self.setObjectName("offlineTtsEnginesDialog")
        self.resize(980, 650)
        self.setMinimumSize(780, 520)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(10)

        header = QFrame()
        header.setObjectName("offlineTtsHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(12, 10, 12, 10)
        title_box = QVBoxLayout()
        title = QLabel("Offline TTS engines")
        title.setObjectName("dialogTitle")
        subtitle = QLabel(
            "Inspect local runtimes and voice assets without downloading, starting servers, or synthesizing audio."
        )
        subtitle.setWordWrap(True)
        subtitle.setObjectName("dialogSubtitle")
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_layout.addLayout(title_box, 1)
        self.summary_label = QLabel("Checking…")
        self.summary_label.setObjectName("summaryStrong")
        header_layout.addWidget(self.summary_label)
        root.addWidget(header)

        splitter = QSplitter(Qt.Vertical)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        engines_page = QWidget()
        engines_layout = QVBoxLayout(engines_page)
        engines_layout.setContentsMargins(0, 0, 0, 0)
        engines_layout.addWidget(QLabel("Engines"))
        self.engine_table = QTableWidget(0, 7)
        self.engine_table.setHorizontalHeaderLabels(
            ["Engine", "Provider", "Runtime", "Installed", "Configured", "State", "Voices"]
        )
        self.engine_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.engine_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.engine_table.verticalHeader().setVisible(False)
        self.engine_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.engine_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        self.engine_table.itemSelectionChanged.connect(self._engine_selection_changed)
        engines_layout.addWidget(self.engine_table, 1)
        self.engine_detail = QLabel()
        self.engine_detail.setWordWrap(True)
        self.engine_detail.setObjectName("summaryMuted")
        engines_layout.addWidget(self.engine_detail)
        runtime_actions = QHBoxLayout()
        runtime_actions.addStretch()
        self.warm_runtime_button = QPushButton("Warm Piper runtime")
        self.warm_runtime_button.clicked.connect(self.warm_piper_runtime)
        self.restart_runtime_button = QPushButton("Restart Piper runtime")
        self.restart_runtime_button.clicked.connect(self.restart_piper_runtime)
        runtime_actions.addWidget(self.warm_runtime_button)
        runtime_actions.addWidget(self.restart_runtime_button)
        engines_layout.addLayout(runtime_actions)
        splitter.addWidget(engines_page)

        voices_page = QWidget()
        voices_layout = QVBoxLayout(voices_page)
        voices_layout.setContentsMargins(0, 0, 0, 0)
        voice_header = QHBoxLayout()
        voice_header.addWidget(QLabel("Discovered voices"))
        voice_header.addStretch()
        self.use_voice_button = QPushButton("Use selected Piper voice")
        self.use_voice_button.clicked.connect(self.use_selected_voice)
        self.open_folder_button = QPushButton("Open model folder")
        self.open_folder_button.clicked.connect(self.open_selected_voice_folder)
        voice_header.addWidget(self.use_voice_button)
        voice_header.addWidget(self.open_folder_button)
        voices_layout.addLayout(voice_header)

        self.voice_table = QTableWidget(0, 7)
        self.voice_table.setHorizontalHeaderLabels(
            ["Selected", "Voice", "Language", "Sample rate", "Speakers", "Config", "Model path"]
        )
        self.voice_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.voice_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.voice_table.verticalHeader().setVisible(False)
        self.voice_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.voice_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.Stretch)
        self.voice_table.itemSelectionChanged.connect(self._voice_selection_changed)
        voices_layout.addWidget(self.voice_table, 1)
        splitter.addWidget(voices_page)
        splitter.setSizes([280, 300])

        note = QLabel(
            "Phase 97 uses an in-process Piper runtime with model reuse and Auto CPU/CUDA selection. "
            "Warm/restart actions never start generation; verified downloadable voice packs remain a separate distribution concern."
        )
        note.setWordWrap(True)
        note.setObjectName("summaryMuted")
        root.addWidget(note)

        footer = QHBoxLayout()
        self.refresh_button = QPushButton("Refresh inventory")
        self.refresh_button.clicked.connect(self.refresh)
        footer.addWidget(self.refresh_button)
        footer.addStretch()
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        footer.addWidget(buttons)
        root.addLayout(footer)

    def refresh(self) -> None:
        self.inventory = self.service.inventory(self.settings_provider())
        self.engine_table.setRowCount(len(self.inventory.engines))
        for row, engine in enumerate(self.inventory.engines):
            values = [
                engine.display_name,
                engine.provider_id,
                engine.runtime_mode,
                "Yes" if engine.installed else "No",
                "Yes" if engine.configured else "No",
                engine.state,
                str(len(engine.voices)),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.UserRole, engine.engine_id)
                self.engine_table.setItem(row, column, item)
        self.summary_label.setText(
            f"{self.inventory.ready_count} ready · {self.inventory.installed_count} installed"
        )
        if self.engine_table.rowCount():
            self.engine_table.selectRow(0)
        else:
            self._render_engine(None)

    def _engine_selection_changed(self) -> None:
        self._render_engine(self.selected_engine_id())

    def selected_engine_id(self) -> str | None:
        row = self.engine_table.currentRow()
        if row < 0:
            return None
        item = self.engine_table.item(row, 0)
        return str(item.data(Qt.UserRole)) if item is not None else None

    def _render_engine(self, engine_id: str | None) -> None:
        engine = self.inventory.engine(engine_id or "") if engine_id else None
        voices = engine.voices if engine else ()
        if engine is None:
            self.engine_detail.setText("Select an offline engine to inspect its runtime state.")
        else:
            issues = " · ".join(engine.issues) if engine.issues else "No blocking inventory issues."
            accelerators = ", ".join(engine.accelerators) or "—"
            runtime_detail = ""
            if engine.engine_id == "piper":
                loaded = "loaded" if engine.runtime_loaded else "cold"
                accelerator = (engine.resolved_accelerator or "cpu").upper()
                runtime_detail = (
                    f" In-process runtime: {loaded} · Auto→{accelerator} · "
                    f"loads {engine.runtime_load_count} · syntheses {engine.runtime_synthesis_count}."
                )
                if engine.runtime_fallback_reason:
                    runtime_detail += f" {engine.runtime_fallback_reason}."
                if engine.runtime_last_error:
                    runtime_detail += f" Last runtime error: {engine.runtime_last_error}."
            self.engine_detail.setText(
                f"{engine.summary} Runtime: {engine.runtime_mode}. Accelerators: {accelerators}."
                f"{runtime_detail} {issues}"
            )

        runtime_action_allowed = bool(
            engine
            and engine.engine_id == "piper"
            and engine.module_available
            and engine.configured
            and not self.generation_active()
        )
        self.warm_runtime_button.setEnabled(runtime_action_allowed)
        self.restart_runtime_button.setEnabled(
            bool(engine and engine.engine_id == "piper" and not self.generation_active())
        )

        self.voice_table.setRowCount(len(voices))
        for row, voice in enumerate(voices):
            values = [
                "✓" if voice.selected else "",
                voice.display_name,
                voice.language_code or "—",
                str(voice.sample_rate) if voice.sample_rate else "—",
                str(voice.speaker_count) if voice.speaker_count is not None else "—",
                "Present" if voice.config_present else "Missing",
                voice.model_path,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 1:
                    item.setData(Qt.UserRole, voice.model_path)
                self.voice_table.setItem(row, column, item)
        selected_row = next((index for index, voice in enumerate(voices) if voice.selected), -1)
        if selected_row >= 0:
            self.voice_table.selectRow(selected_row)
        elif voices:
            self.voice_table.selectRow(0)
        self._voice_selection_changed()

    def warm_piper_runtime(self) -> None:
        if self.generation_active():
            QMessageBox.warning(self, "Piper runtime", "Stop the active generation run before changing runtime state.")
            return
        try:
            health = self.service.warm_piper(self.settings_provider())
        except Exception as exc:
            QMessageBox.warning(self, "Piper runtime", str(exc))
            return
        self.refresh()
        self.summary_label.setText(
            f"Piper warm · {health.resolved_acceleration.upper()} · {health.load_count} model load(s)"
        )

    def restart_piper_runtime(self) -> None:
        if self.generation_active():
            QMessageBox.warning(self, "Piper runtime", "Stop the active generation run before changing runtime state.")
            return
        cleared = self.service.restart_piper(self.settings_provider())
        self.refresh()
        self.summary_label.setText(f"Piper runtime restarted · {cleared} cached model(s) cleared")

    def selected_voice(self) -> OfflineVoiceDescriptor | None:
        engine = self.inventory.engine(self.selected_engine_id() or "")
        if engine is None:
            return None
        row = self.voice_table.currentRow()
        if row < 0 or row >= len(engine.voices):
            return None
        return engine.voices[row]

    def _voice_selection_changed(self) -> None:
        voice = self.selected_voice()
        can_apply = bool(
            voice
            and voice.engine_id == "piper"
            and voice.config_present
            and self.apply_piper_voice is not None
            and not self.generation_active()
        )
        self.use_voice_button.setEnabled(can_apply)
        self.open_folder_button.setEnabled(bool(voice))

    def use_selected_voice(self) -> None:
        voice = self.selected_voice()
        if voice is None or voice.engine_id != "piper" or not voice.config_present:
            return
        if self.generation_active():
            QMessageBox.warning(
                self,
                "Generation is active",
                "Stop the current generation run before changing the offline voice.",
            )
            return
        if self.apply_piper_voice is None:
            return
        self.apply_piper_voice(voice.model_path)
        self.refresh()

    def open_selected_voice_folder(self) -> None:
        voice = self.selected_voice()
        if voice is None:
            return
        parent = Path(voice.model_path).parent
        if parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(parent)))
