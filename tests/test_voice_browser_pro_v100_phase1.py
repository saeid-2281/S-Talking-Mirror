from __future__ import annotations

from pathlib import Path

from app.database.connection import Database
from app.gui.widgets.voice_table_model import VoiceDataRole, VoiceTableModel
from app.gui.widgets.voice_table_view import VoiceTableView
from app.models.domain import AppSettings
from app.repositories.voice_repository import VoiceRepository
from app.services.voice_service import VoiceItem, VoiceService


def _voice(index: int, *, favorite: bool = False) -> VoiceItem:
    return VoiceItem(
        provider="elevenlabs",
        voice_id=f"voice-{index}",
        name=f"Voice {index:04d}",
        language="da" if index % 2 else "en",
        category="professional",
        description="Narration voice",
        labels={"accent": "danish", "gender": "female", "age": "adult"},
        is_favorite=favorite,
    )


def _service(tmp_path: Path) -> VoiceService:
    database = Database(tmp_path / "voices.db")
    database.initialize()
    return VoiceService(VoiceRepository(database), tmp_path / "previews")


def test_voice_table_model_exposes_identity_and_metadata() -> None:
    model = VoiceTableModel()
    item = _voice(1, favorite=True)
    model.set_items([item])

    assert model.rowCount() == 1
    assert model.columnCount() == 7
    assert model.index(0, 0).data() == "★"
    assert model.index(0, 1).data() == item.name
    assert model.index(0, 1).data(VoiceDataRole.VOICE_ID) == item.voice_id
    assert model.index(0, 1).data(VoiceDataRole.ITEM) == item
    assert model.row_for_voice_id(item.voice_id) == 0


def test_voice_table_model_handles_large_catalog_without_widget_items() -> None:
    model = VoiceTableModel()
    items = [_voice(index) for index in range(10_000)]
    model.set_items(items)

    assert model.rowCount() == 10_000
    assert model.row_for_voice_id("voice-9999") == 9999
    assert model.item_at(9999) == items[-1]


def test_voice_table_view_keeps_legacy_read_contract(qt_app) -> None:
    view = VoiceTableView()
    items = [_voice(1), _voice(2, favorite=True)]
    view.set_items(items, selected_id="voice-2")
    qt_app.processEvents()

    assert view.rowCount() == 2
    assert view.currentRow() == 1
    assert view.selected_item() == items[1]
    assert view.item(1, 0).text() == "★"
    assert view.item(1, 1).text() == "Voice 0002"


def test_voice_browser_uses_model_view_and_updates_result_count(qt_app, tmp_path: Path) -> None:
    from app.gui.voice_browser import VoiceBrowserDialog

    service = _service(tmp_path)
    for index in range(3):
        service.repository.upsert(
            provider="mock",
            voice_id=f"voice-{index}",
            name=f"Voice {index}",
            language="da",
            category="professional",
            metadata={"labels": {"accent": "danish"}},
        )
    item = service.list(provider="mock")[0]
    service.set_favorite(item, True)

    dialog = VoiceBrowserDialog(service=service, settings_provider=lambda: AppSettings(provider="mock"))
    dialog.apply_filters()
    qt_app.processEvents()

    assert isinstance(dialog.table, VoiceTableView)
    assert dialog.table.rowCount() == 3
    assert "3 voices" in dialog.results_label.text()
    assert "1 favorite" in dialog.results_label.text()
