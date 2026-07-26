from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.database.connection import Database
from app.gui.dialogs.quick_setup_dialog import QuickSetupDialog
from app.gui.dialogs.source_import_review_dialog import SourceImportReviewDialog
from app.models.domain import AppSettings, TTSJob
from app.models.product_events import BatchSessionRecord
from app.repositories.product_event_repository import ProductEventRepository
from app.services.product_activity_service import ProductActivityService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.source_import_service import SourceImportService


@pytest.fixture
def qt_app():
    return QApplication.instance() or QApplication([])


def test_product_polish_migration_adds_history_tables(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.db")
    database.initialize()

    with database.connect() as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}

    assert {"notifications", "activity_timeline", "batch_sessions", "workspace_preferences"}.issubset(tables)
    assert 3 in versions


def test_product_event_repository_round_trips_notifications_activity_and_batches(tmp_path: Path) -> None:
    database = Database(tmp_path / "app.db")
    database.initialize()
    service = ProductActivityService(ProductEventRepository(database))

    notification = service.notify("info", "Imported", "Two sources imported.")
    activity = service.activity("import", "Source import", "Merged queue refreshed.", metadata={"sources": 2})
    service.record_batch(
        BatchSessionRecord(
            session_id="s1",
            project_id=None,
            scope="row_range",
            provider="mock",
            model="mock",
            voice="mock",
            total_jobs=2,
            completed_jobs=2,
            failed_jobs=0,
            skipped_jobs=0,
            character_count=10,
            report_path=None,
            output_path=None,
            result="completed",
            started_at="2026-01-01T00:00:00+00:00",
        )
    )

    repo = ProductEventRepository(database)
    assert repo.list_notifications()[0].notification_id == notification.notification_id
    assert repo.list_activity()[0].event_id == activity.event_id
    assert repo.list_batch_sessions()[0].session_id == "s1"


def test_provider_capability_cards_do_not_fabricate_claims() -> None:
    cards = {card.provider_id: card for card in ProviderCatalogService().cards(AppSettings(provider="mock"))}

    assert cards["mock"].setup_state == "Ready"
    assert "Local" in cards["mock"].badges
    assert "Cloud" in cards["openai"].badges
    assert cards["openai"].setup_state == "Setup required"
    assert "Setup required" in cards["azure"].badges


def test_source_import_review_dialog_imports_only_accepted_valid_sources(qt_app, tmp_path: Path) -> None:
    one = tmp_path / "one.csv"
    two = tmp_path / "two.csv"
    one.write_text("filename,text\none.wav,Hej\n", encoding="utf-8")
    two.write_text("filename,text\ntwo.wav,Hej igen\n", encoding="utf-8")
    service = SourceImportService()
    result = service.import_sources(service.create_sources([one, two]))
    dialog = SourceImportReviewDialog(result)
    dialog.table.selectRow(0)
    dialog.import_selected()

    selected = dialog.importable_results()

    assert dialog.result() == QDialog.Accepted
    assert [item.source.source_path for item in selected] == [one]


def test_generation_controller_source_filter_limits_visible_jobs(tmp_path: Path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    jobs = [
        TTSJob(row_number=1, filename="a.wav", text="a", source_id="s1", source_display_name="One"),
        TTSJob(row_number=2, filename="b.wav", text="b", source_id="s2", source_display_name="Two"),
    ]
    context.generation_controller.set_jobs(jobs, output_dir=tmp_path, settings=AppSettings(provider="mock"))

    context.generation_controller.set_source_filter("s2")

    assert [job.filename for job in context.generation_controller.visible_jobs()] == ["b.wav"]
    assert context.generation_controller.metrics().total == 1


def test_main_window_exposes_v017_shortcuts_and_empty_state(qt_app, tmp_path: Path) -> None:
    from app.gui.main import MainWindow

    window = MainWindow(create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path))))

    assert window.actions_by_name["New Project"].shortcut().toString() == "Ctrl+N"
    assert window.actions_by_name["Add source files"].shortcut().toString() == "Ctrl+Shift+O"
    assert window.actions_by_name["Command Palette"].shortcut().toString() == "Ctrl+K"
    assert window.empty_state.isVisible() or not window.generation_controller.has_jobs()
    assert window.source_filter.itemText(0) == "All sources"
    window.close()


def test_quick_setup_dialog_uses_provider_cards(qt_app) -> None:
    dialog = QuickSetupDialog(ProviderCatalogService(), AppSettings(provider="mock"))

    providers = [dialog.provider.itemData(index) for index in range(dialog.provider.count())]

    assert {"mock", "openai", "azure", "google", "aws_polly", "kokoro"}.issubset(set(providers))
    dialog.close()


def test_database_backup_created_for_each_missing_post_baseline_migration(tmp_path: Path) -> None:
    path = tmp_path / "db.sqlite"
    Database(path).initialize()
    with sqlite3.connect(path) as connection:
        connection.execute("DELETE FROM schema_migrations WHERE version IN (2, 3)")

    Database(path).initialize()

    assert (tmp_path / "db.sqlite.pre-v2.bak").exists()
    assert (tmp_path / "db.sqlite.pre-v3.bak").exists()
