from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QAbstractItemView,
    QDialog,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from app.gui.icons import icon
from app.models.domain import AppSettings
from app.models.pronunciation_dictionary import PronunciationDictionary, PronunciationRule
from app.provider_factory import create_provider
from app.services.pronunciation_dictionary_service import PronunciationDictionaryService


class PronunciationDictionaryDialog(QDialog):
    dictionaries_changed = Signal()

    def __init__(
        self,
        service: PronunciationDictionaryService,
        settings_provider: Callable[[], AppSettings],
        *,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.service = service
        self.settings_provider = settings_provider
        self.undo_stack: list[list[PronunciationRule]] = []
        self.redo_stack: list[list[PronunciationRule]] = []
        self.setWindowTitle("Pronunciation Dictionaries")
        self.resize(1080, 660)
        self.setMinimumSize(940, 560)
        self._build()
        self.refresh()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        self.compatibility = QLabel("Select a dictionary to view compatibility.")
        self.compatibility.setWordWrap(True)
        top.addWidget(self.compatibility, 1)
        root.addLayout(top)

        splitter = QSplitter(Qt.Vertical)
        self.dictionary_table = QTableWidget(0, 9)
        self.dictionary_table.setHorizontalHeaderLabels([
            "Active",
            "Name",
            "Provider",
            "Language",
            "Model compatibility",
            "Dictionary ID",
            "Version",
            "Rule count",
            "Source",
        ])
        self.dictionary_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.dictionary_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.dictionary_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.dictionary_table.horizontalHeader().setStretchLastSection(True)
        self.dictionary_table.itemSelectionChanged.connect(self.selection_changed)
        splitter.addWidget(self.dictionary_table)

        self.rule_table = QTableWidget(0, 7)
        self.rule_table.setHorizontalHeaderLabels([
            "Grapheme/word",
            "Rule type",
            "Replacement or phoneme",
            "Alphabet",
            "Case sensitive",
            "Enabled",
            "Notes",
        ])
        self.rule_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.rule_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.rule_table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.rule_table.horizontalHeader().setStretchLastSection(True)
        splitter.addWidget(self.rule_table)
        splitter.setSizes([260, 280])
        root.addWidget(splitter, 1)

        actions = QGridLayout()
        items = [
            ("Refresh provider dictionaries", "refresh", self.refresh_remote),
            ("Sync selected", "refresh", self.sync_selected),
            ("Create dictionary", "new", self.create_dictionary),
            ("Import .pls", "open", self.import_pls),
            ("Export metadata", "save", self.export_metadata),
            ("Rename local alias", "settings", self.rename_dictionary),
            ("Delete / archive", "delete", self.delete_dictionary),
            ("Set active", "start", self.set_active),
            ("Disable for project", "stop", self.disable_current_project_dictionary),
            ("Test selected dictionary", "play", self.test_dictionary),
            ("Add rule", "new", self.add_rule),
            ("Edit rule", "settings", self.edit_rule),
            ("Delete rule", "delete", self.delete_rule),
            ("Duplicate rule", "copy", self.duplicate_rule),
            ("Import rules", "open", self.import_pls),
            ("Export .pls", "save", self.export_pls),
            ("Test rule with Preview", "play", self.test_rule),
            ("Undo", "refresh", self.undo),
            ("Redo", "refresh", self.redo),
        ]
        self.buttons: list[QPushButton] = []
        for index, (text, icon_name, handler) in enumerate(items):
            button = QPushButton(text)
            button.setIcon(icon(icon_name))
            button.clicked.connect(handler)
            actions.addWidget(button, index // 6, index % 6)
            self.buttons.append(button)
        root.addLayout(actions)

        bottom = QHBoxLayout()
        bottom.addStretch()
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        bottom.addWidget(close)
        root.addLayout(bottom)

    def refresh(self) -> None:
        summaries = self.service.list_dictionaries()
        self.dictionary_table.setRowCount(len(summaries))
        for row, summary in enumerate(summaries):
            values = [
                "Yes" if summary.active else "",
                summary.name,
                summary.provider,
                summary.language_code,
                summary.model_compatibility,
                summary.dictionary_id,
                summary.version_id or "—",
                summary.rule_count,
                summary.source,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setData(Qt.UserRole, summary.dictionary_id)
                item.setToolTip(str(value))
                self.dictionary_table.setItem(row, column, item)
        self.selection_changed()

    def selected_dictionary(self) -> PronunciationDictionary | None:
        row = self.dictionary_table.currentRow()
        if row < 0:
            return None
        item = self.dictionary_table.item(row, 0)
        if item is None:
            return None
        try:
            return self.service.load(str(item.data(Qt.UserRole)))
        except Exception:
            return None

    def selected_rule_index(self) -> int | None:
        row = self.rule_table.currentRow()
        return row if row >= 0 else None

    def selection_changed(self) -> None:
        dictionary = self.selected_dictionary()
        self.render_rules(dictionary)
        enabled = dictionary is not None
        for button in self.buttons[3:]:
            button.setEnabled(enabled)
        if dictionary is None:
            self.compatibility.setText("Select a dictionary to view compatibility.")
            return
        warning = self.service.alias_warning_for(dictionary)
        try:
            self.service.validate_rules(dictionary, model_id=self.settings_provider().model_id)
            compatibility = "Compatible with the selected model." if not warning else warning
        except ValueError as exc:
            compatibility = str(exc)
        self.compatibility.setText(
            f"Active dictionary: {dictionary.name} · {dictionary.language_code} · "
            f"{len(dictionary.rules)} rule(s)\n{compatibility}"
        )

    def render_rules(self, dictionary: PronunciationDictionary | None) -> None:
        rules = dictionary.rules if dictionary else []
        self.rule_table.setRowCount(len(rules))
        for row, rule in enumerate(rules):
            values = [
                rule.source,
                rule.rule_type,
                rule.replacement,
                rule.alphabet or "—",
                "Yes" if rule.case_sensitive else "No",
                "Yes" if rule.enabled else "No",
                rule.notes,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.rule_table.setItem(row, column, item)

    def refresh_remote(self) -> None:
        settings = self.settings_provider()
        if settings.provider != "elevenlabs" or not settings.api_key:
            QMessageBox.information(self, "Pronunciation dictionaries", "Enter an ElevenLabs API key before refreshing remote dictionaries.")
            return
        provider = create_provider(settings)
        try:
            self.service.refresh_remote_metadata(provider, provider_name=settings.provider)
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        self._changed()

    def sync_selected(self) -> None:
        dictionary = self.selected_dictionary()
        if not dictionary:
            return
        settings = self.settings_provider()
        if settings.provider != "elevenlabs" or not settings.api_key:
            QMessageBox.information(self, "Sync dictionary", "Enter an ElevenLabs API key before syncing remote dictionaries.")
            return
        provider = create_provider(settings)
        try:
            synced = self.service.sync_remote(provider, dictionary, model_id=settings.model_id)
        except Exception as exc:
            QMessageBox.warning(self, "Sync dictionary", str(exc))
            return
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        QMessageBox.information(self, "Sync dictionary", f"Synced '{synced.name}' at version {synced.version_id or 'unknown'}.")
        self._changed()

    def create_dictionary(self) -> None:
        name, ok = QInputDialog.getText(self, "Create dictionary", "Dictionary name")
        if ok:
            self.service.create(name, language_code=self.settings_provider().language_code or "da")
            self._changed()

    def import_pls(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import PLS", "", "PLS (*.pls *.xml)")
        if path:
            try:
                self.service.import_pls(Path(path))
                self._changed()
            except Exception as exc:
                QMessageBox.warning(self, "Import PLS", str(exc))

    def export_metadata(self) -> None:
        dictionary = self.selected_dictionary()
        if not dictionary:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export metadata", f"{dictionary.name}.json", "JSON (*.json)")
        if path:
            self.service.export_metadata(dictionary.dictionary_id, Path(path))

    def export_pls(self) -> None:
        dictionary = self.selected_dictionary()
        if not dictionary:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export PLS", f"{dictionary.name}.pls", "PLS (*.pls)")
        if path:
            self.service.export_pls(dictionary.dictionary_id, Path(path))

    def rename_dictionary(self) -> None:
        dictionary = self.selected_dictionary()
        if not dictionary:
            return
        name, ok = QInputDialog.getText(self, "Rename dictionary", "Name", text=dictionary.name)
        if ok:
            self.service.rename(dictionary.dictionary_id, name)
            self._changed()

    def delete_dictionary(self) -> None:
        dictionary = self.selected_dictionary()
        if not dictionary:
            return
        entered, ok = QInputDialog.getText(
            self,
            "Delete / archive dictionary",
            f"Type the dictionary name to confirm:\n{dictionary.name}",
        )
        if not ok or entered != dictionary.name:
            return
        if dictionary.source in {"Remote", "Synced", "Stale"}:
            settings = self.settings_provider()
            if settings.provider != "elevenlabs" or not settings.api_key:
                QMessageBox.warning(self, "Delete / archive dictionary", "Enter an ElevenLabs API key before archiving a remote dictionary.")
                return
            provider = create_provider(settings)
            try:
                delete = getattr(provider, "delete_pronunciation_dictionary", None)
                if not callable(delete):
                    raise RuntimeError("Provider does not support dictionary archiving.")
                delete(dictionary.dictionary_id)
            except Exception as exc:
                QMessageBox.warning(self, "Delete / archive dictionary", str(exc))
                return
            finally:
                close = getattr(provider, "close", None)
                if callable(close):
                    close()
        self.service.delete_metadata(dictionary.dictionary_id)
        self._changed()

    def set_active(self) -> None:
        dictionary = self.selected_dictionary()
        if dictionary:
            self.service.set_active(dictionary.dictionary_id, provider=dictionary.provider, language_code=dictionary.language_code)
            self._changed()

    def disable_current_project_dictionary(self) -> None:
        self.service.set_active(None, provider=self.settings_provider().provider, language_code=self.settings_provider().language_code)
        self._changed()

    def test_dictionary(self) -> None:
        dictionary = self.selected_dictionary()
        if dictionary:
            try:
                self.service.validate_rules(dictionary, model_id=self.settings_provider().model_id)
                QMessageBox.information(self, "Dictionary test", "Dictionary metadata and rules are valid for the selected settings.")
            except ValueError as exc:
                QMessageBox.warning(self, "Dictionary test", str(exc))

    def add_rule(self) -> None:
        dictionary = self.selected_dictionary()
        if not dictionary:
            return
        self._push_undo(dictionary)
        source, ok = QInputDialog.getText(self, "Add rule", "Grapheme/word")
        if not ok:
            return
        replacement, ok = QInputDialog.getText(self, "Add rule", "Replacement or phoneme")
        if ok:
            self.service.add_rule(dictionary.dictionary_id, PronunciationRule(source, replacement, "alias", dictionary.language_code))
            self._changed()

    def edit_rule(self) -> None:
        dictionary = self.selected_dictionary()
        index = self.selected_rule_index()
        if dictionary is None or index is None or index >= len(dictionary.rules):
            return
        self._push_undo(dictionary)
        rule = dictionary.rules[index]
        source, ok = QInputDialog.getText(self, "Edit rule", "Grapheme/word", text=rule.source)
        if not ok:
            return
        replacement, ok = QInputDialog.getText(self, "Edit rule", "Replacement or phoneme", text=rule.replacement)
        if ok:
            self.service.update_rule(
                dictionary.dictionary_id,
                index,
                PronunciationRule(
                    source=source,
                    replacement=replacement,
                    rule_type=rule.rule_type,
                    language_code=rule.language_code,
                    alphabet=rule.alphabet,
                    case_sensitive=rule.case_sensitive,
                    word_boundaries=rule.word_boundaries,
                    enabled=rule.enabled,
                    notes=rule.notes,
                ),
            )
            self._changed()

    def delete_rule(self) -> None:
        dictionary = self.selected_dictionary()
        index = self.selected_rule_index()
        if dictionary is not None and index is not None:
            self._push_undo(dictionary)
            self.service.delete_rule(dictionary.dictionary_id, index)
            self._changed()

    def duplicate_rule(self) -> None:
        dictionary = self.selected_dictionary()
        index = self.selected_rule_index()
        if dictionary is not None and index is not None:
            self._push_undo(dictionary)
            self.service.duplicate_rule(dictionary.dictionary_id, index)
            self._changed()

    def test_rule(self) -> None:
        dictionary = self.selected_dictionary()
        index = self.selected_rule_index()
        if dictionary is not None and index is not None and index < len(dictionary.rules):
            QApplication.clipboard().setText(dictionary.rules[index].source)
            QMessageBox.information(self, "Test rule", "Rule grapheme copied for Voice Browser preview testing.")

    def undo(self) -> None:
        dictionary = self.selected_dictionary()
        if not dictionary or not self.undo_stack:
            return
        self.redo_stack.append(list(dictionary.rules))
        dictionary.rules = self.undo_stack.pop()
        self.service.save(dictionary)
        self._changed()

    def redo(self) -> None:
        dictionary = self.selected_dictionary()
        if not dictionary or not self.redo_stack:
            return
        self.undo_stack.append(list(dictionary.rules))
        dictionary.rules = self.redo_stack.pop()
        self.service.save(dictionary)
        self._changed()

    def _push_undo(self, dictionary: PronunciationDictionary) -> None:
        self.undo_stack.append(list(dictionary.rules))
        self.redo_stack.clear()

    def _changed(self) -> None:
        self.refresh()
        self.dictionaries_changed.emit()
