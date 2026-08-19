from __future__ import annotations

import inspect
from pathlib import Path

from PySide6.QtCore import Qt

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.application_shell import ActivityCenter


def test_h11_progress_path_avoids_full_queue_rebuild() -> None:
    source = inspect.getsource(MainWindow.progress)
    assert "refresh_progress_row" in source
    assert "render_queue" not in source


def test_h11_incremental_refresh_preserves_filtered_or_status_order_semantics() -> None:
    source = inspect.getsource(MainWindow.refresh_progress_row)
    assert "self.queue_filter.currentText() != 'All'" in source
    assert "display_order" in source
    assert "self.render_queue()" in source
    assert "self.table.setItem" in source
    assert "self.paint" in source



def test_h11_full_queue_render_batches_widget_updates_and_reuses_settings() -> None:
    source = inspect.getsource(MainWindow.render_queue)
    assert "self.table.setUpdatesEnabled(False)" in source
    assert "self.table.blockSignals(True)" in source
    assert "settings=self.settings()" in source
    assert "output_path_for(j,output_dir,settings)" in source
    assert "self.table.setUpdatesEnabled(True)" in source


def test_h11_preserves_phase92_queue_batch_method_block() -> None:
    refresh_source = inspect.getsource(MainWindow.refresh_queue_batch_operations)
    lens_source = inspect.getsource(MainWindow.apply_queue_batch_lens)
    action_source = inspect.getsource(MainWindow.handle_queue_batch_action)
    focus_source = inspect.getsource(MainWindow.focus_queue_batch_operations)
    scope_source = inspect.getsource(MainWindow.update_queue_scope_summary)

    assert "queue_batch_service.snapshot" in refresh_source
    assert "queue_batch_service.lens_job_ids" in lens_source
    assert "'retry_failed':self.retry_failed" in action_source
    assert "focus_lens()" in focus_source
    assert "QueueSelectionStats" in scope_source


def test_h11_full_queue_render_preserves_phase92_summary_and_batch_refresh() -> None:
    source = inspect.getsource(MainWindow.render_queue)
    assert "self.update_queue_scope_summary(jobs)" in source
    assert "self.update_selection_scope_summary(jobs)" in source
    assert "self.refresh_queue_batch_operations(jobs)" in source

def test_h11_output_workspace_scrolls_instead_of_compressing_controls(qt_app, tmp_path: Path) -> None:
    services = create_service_container(RuntimeConfig.from_root(tmp_path))
    center = ActivityCenter()
    workspace = center.install_output_workspace(services.audio_player_service)

    assert workspace.scroll_area.widget() is workspace.scroll_content
    assert workspace.scroll_area.widgetResizable() is True
    assert workspace.scroll_area.horizontalScrollBarPolicy() == Qt.ScrollBarAlwaysOff
    assert workspace.scroll_content.minimumHeight() >= 520
    assert workspace.path_label.minimumWidth() == 0

    center.show_output_workspace()
    assert center.currentWidget() is workspace
    assert center.maximumHeight() >= 560
    center.close()


def test_h11_provider_account_migration_targets_real_portable_settings_root() -> None:
    source = Path("scripts/migrate_provider_accounts_to_portable.ps1").read_text(encoding="utf-8")
    assert 'S-Talking-Data\\settings' in source
    assert 'api-profiles.json' in source
    assert 'credentials' in source
    assert '*.cred' in source
    assert 'profile_id' in source
    assert 'Provider credential contents are never printed' in source


def test_h11_local_engine_migration_rebases_existing_launcher_and_settings() -> None:
    source = Path("scripts/migrate_local_engines_to_portable.ps1").read_text(encoding="utf-8")
    assert '$SourceData = Join-Path $SourcePortableRoot "S-Talking-Data"' in source
    assert 'Copy-Tree (Join-Path $SourceData "local-engines")' in source
    assert 'Copy-Tree (Join-Path $SourceData "offline-voices")' in source
    assert 'RUN-S-Talking-With-Local-Engines.cmd' in source
    assert '.Replace($SourcePortableRoot, $DestinationPortableRoot)' in source
    assert 'settings.json' in source

def test_h11_render_queue_preserves_model_view_adapter_path() -> None:
    source = inspect.getsource(MainWindow.render_queue)
    assert "self.queue_adapter.is_model_view" in source
    assert "self.queue_adapter.refresh_jobs(" in source
    assert "self.table.setRowCount(len(jobs))" in source
    assert "self.table.setUpdatesEnabled(False)" in source


def test_h11_incremental_progress_defers_model_view_to_adapter_render() -> None:
    source = inspect.getsource(MainWindow.refresh_progress_row)
    assert "self.queue_adapter.is_model_view" in source
    assert "self.render_queue(); return" in source


def test_h11_batch_snapshot_preserves_current_lens_contract() -> None:
    source = inspect.getsource(MainWindow.refresh_queue_batch_operations)
    assert "lens=str(self.queue_batch_operations.lens.currentData() or 'all')" in source


def test_h11_batch_lens_explicitly_preserves_generation_scope() -> None:
    source = inspect.getsource(MainWindow.apply_queue_batch_lens)
    assert "restore_selection(row_ids)" in source
    assert "selected_characters" in source
    assert "Generation scope is unchanged" in source
    assert "Preflight has NOT run" in source
    assert "set_generation_selection" not in source
    assert "invalidate_preflight" not in source
    assert "self.start(" not in source


def test_h11_batch_focus_reveals_a9_progressive_disclosure() -> None:
    source = inspect.getsource(MainWindow.focus_queue_batch_operations)
    assert "main_workspace_modernizer.reveal_batch_planning(True)" in source
    assert "queue_batch_operations.focus_lens()" in source

