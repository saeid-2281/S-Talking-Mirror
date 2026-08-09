from __future__ import annotations

import json
from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.application_shell import ActivityCenter
from app.gui.widgets.output_workspace import OutputPlaybackWorkspace
from app.models.domain import AppSettings, JobStatus, TTSJob
from app.services.audio_review_export_service import AudioReviewExportService


def _job(row: int, name: str, status: JobStatus, path: Path | None = None) -> TTSJob:
    return TTSJob(
        row_number=row,
        text=f"Text {row}",
        filename=name,
        status=status,
        generated_output_path=str(path) if path else None,
    )


def _path_for(job: TTSJob, output_dir: Path, settings: AppSettings) -> Path:
    if job.generated_output_path:
        return Path(job.generated_output_path)
    return job.output_path(output_dir, settings.file_extension)


def _inventory(tmp_path: Path):
    ready = tmp_path / "ready.mp3"
    ready.write_bytes(b"ready-audio")
    missing = tmp_path / "missing.mp3"
    failed = tmp_path / "failed.mp3"
    jobs = [
        _job(1, "ready", JobStatus.COMPLETED, ready),
        _job(2, "missing", JobStatus.COMPLETED, missing),
        _job(3, "failed", JobStatus.FAILED, failed),
        _job(4, "pending", JobStatus.PENDING, tmp_path / "pending.mp3"),
    ]
    service = AudioReviewExportService()
    summary = service.build_inventory(jobs, tmp_path, AppSettings(), _path_for)
    return service, summary, ready


def test_phase94_inventory_classifies_ready_missing_failed_and_pending(tmp_path: Path) -> None:
    _service, summary, _ready = _inventory(tmp_path)

    assert summary.total == 4
    assert summary.ready == 1
    assert summary.missing == 1
    assert summary.failed == 1
    assert summary.pending == 1
    assert [item.review_status for item in summary.items] == [
        "ready",
        "missing",
        "failed",
        "pending",
    ]


def test_phase94_inventory_preserves_queue_identity_and_order(tmp_path: Path) -> None:
    _service, summary, _ready = _inventory(tmp_path)

    assert [item.row_number for item in summary.items] == [1, 2, 3, 4]
    assert [item.filename for item in summary.items] == [
        "ready",
        "missing",
        "failed",
        "pending",
    ]


def test_phase94_flat_export_copies_ready_audio_and_verifies_sha256(tmp_path: Path) -> None:
    service, summary, ready = _inventory(tmp_path)
    destination = tmp_path / "export"

    receipt = service.export(summary.items, destination, preset="flat", output_root=tmp_path)

    assert len(receipt.copied) == 1
    exported = receipt.copied[0]
    assert exported.destination_path == destination / ready.name
    assert exported.destination_path.read_bytes() == ready.read_bytes()
    assert exported.sha256 == service.sha256(ready) == service.sha256(exported.destination_path)
    assert ready.read_bytes() == b"ready-audio"


def test_phase94_export_never_overwrites_collision(tmp_path: Path) -> None:
    service, summary, ready = _inventory(tmp_path)
    destination = tmp_path / "export"
    destination.mkdir()
    existing = destination / ready.name
    existing.write_bytes(b"keep-me")

    receipt = service.export(summary.items, destination, preset="flat", output_root=tmp_path)

    assert existing.read_bytes() == b"keep-me"
    assert receipt.collisions_resolved == 1
    assert receipt.copied[0].destination_path.name == "ready__2.mp3"


def test_phase94_preserve_folders_keeps_relative_output_structure(tmp_path: Path) -> None:
    service = AudioReviewExportService()
    output_root = tmp_path / "outputs"
    nested = output_root / "chapter-1" / "voice-a.wav"
    nested.parent.mkdir(parents=True)
    nested.write_bytes(b"wave")
    jobs = [_job(1, "voice-a", JobStatus.COMPLETED, nested)]
    summary = service.build_inventory(jobs, output_root, AppSettings(), _path_for)

    receipt = service.export(
        summary.items,
        tmp_path / "export",
        preset="preserve",
        output_root=output_root,
    )

    assert receipt.copied[0].destination_path == tmp_path / "export" / "chapter-1" / "voice-a.wav"


def test_phase94_export_skips_non_ready_items_without_touching_sources(tmp_path: Path) -> None:
    service, summary, ready = _inventory(tmp_path)
    before = ready.read_bytes()

    receipt = service.export(summary.items, tmp_path / "export", output_root=tmp_path)

    assert len(receipt.copied) == 1
    assert receipt.skipped_missing == 3
    assert ready.read_bytes() == before


def test_phase94_export_manifest_records_verified_copy_contract(tmp_path: Path) -> None:
    service, summary, _ready = _inventory(tmp_path)

    receipt = service.export(summary.items, tmp_path / "export", output_root=tmp_path)
    payload = json.loads(receipt.manifest_path.read_text(encoding="utf-8"))

    assert payload["schema"] == 1
    assert payload["operation"] == "audio_export_copy"
    assert payload["copied"] == 1
    assert payload["skipped_missing"] == 3
    assert len(payload["files"][0]["sha256"]) == 64


def test_phase94_output_workspace_exposes_review_navigation_and_export_controls(qt_app, tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    center = ActivityCenter()
    workspace = center.install_output_workspace(container.audio_player_service)

    assert isinstance(workspace, OutputPlaybackWorkspace)
    assert workspace.review_card.objectName() == "outputReviewCard"
    assert workspace.review_selector.objectName() == "outputReviewSelector"
    assert workspace.export_scope.objectName() == "outputExportScope"
    assert workspace.export_preset.objectName() == "outputExportPreset"
    assert workspace.export_ready_button.property("primary") is True
    center.close()


def test_phase94_workspace_refresh_lists_only_generated_review_rows(qt_app, tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    ready = tmp_path / "ready.wav"
    ready.write_bytes(b"wave")
    jobs = [
        _job(1, "ready", JobStatus.COMPLETED, ready),
        _job(2, "failed", JobStatus.FAILED, tmp_path / "failed.wav"),
        _job(3, "pending", JobStatus.PENDING, tmp_path / "pending.wav"),
    ]
    center = ActivityCenter()
    workspace = center.install_output_workspace(
        container.audio_player_service,
        jobs_provider=lambda: jobs,
        output_dir_provider=lambda: tmp_path,
        settings_provider=lambda: AppSettings(provider="piper"),
        output_path_for=_path_for,
    )

    summary = workspace.refresh_review()

    assert summary.ready == 1
    assert summary.failed == 1
    assert workspace.review_selector.count() == 2
    assert "Ready 1" in workspace.review_summary_label.text()
    assert "Failed 1" in workspace.review_summary_label.text()
    center.close()


def test_phase94_review_navigation_changes_output_context_without_autoplay(qt_app, tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    first = tmp_path / "first.wav"
    second = tmp_path / "second.wav"
    first.write_bytes(b"one")
    second.write_bytes(b"two")
    jobs = [
        _job(1, "first", JobStatus.COMPLETED, first),
        _job(2, "second", JobStatus.COMPLETED, second),
    ]
    center = ActivityCenter()
    workspace = center.install_output_workspace(
        container.audio_player_service,
        jobs_provider=lambda: jobs,
        output_dir_provider=lambda: tmp_path,
        settings_provider=lambda: AppSettings(provider="piper"),
        output_path_for=_path_for,
    )
    workspace.refresh_review()
    workspace.review_selector.setCurrentIndex(0)

    workspace.review_next()

    assert workspace.review_selector.currentIndex() == 1
    assert workspace.current_path == second
    assert workspace.service.playback_state != "playing"
    center.close()


def test_phase94_missing_review_item_is_visible_without_forcing_playback(qt_app, tmp_path: Path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    missing = tmp_path / "missing.wav"
    jobs = [_job(1, "missing", JobStatus.COMPLETED, missing)]
    center = ActivityCenter()
    workspace = center.install_output_workspace(
        container.audio_player_service,
        jobs_provider=lambda: jobs,
        output_dir_provider=lambda: tmp_path,
        settings_provider=lambda: AppSettings(provider="piper"),
        output_path_for=_path_for,
    )
    workspace.refresh_review()

    workspace._review_selection_changed(0)

    assert workspace.current_path == missing
    assert "Missing" in workspace.metadata_label.text()
    assert workspace.service.playback_state != "playing"
    center.close()


def test_phase94_main_wires_review_to_real_queue_and_exposes_shortcut(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))

    assert window.actions_by_name["Audio review & export"] is window.open_audio_review_action
    assert window.open_audio_review_action.shortcut().toString() == "Ctrl+Alt+A"
    assert callable(window.output_workspace.jobs_provider)
    assert callable(window.output_workspace.output_dir_provider)
    assert callable(window.output_workspace.settings_provider)
    assert window.output_workspace.output_path_for == window.generation_controller.output_path_for
    window.close()


def test_phase94_show_output_workspace_refreshes_review_before_handoff(qt_app, tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    window = MainWindow(create_application_context(create_service_container(runtime)))
    calls: list[str] = []
    original = window.output_workspace.refresh_review

    def refresh():
        calls.append("refresh")
        return original()

    window.output_workspace.refresh_review = refresh

    workspace = window.show_output_workspace()

    assert workspace is window.output_workspace
    assert calls == ["refresh"]
    window.close()


def test_phase94_source_contract_keeps_generation_and_playback_semantics_untouched() -> None:
    service_source = Path("app/services/audio_review_export_service.py").read_text(encoding="utf-8")
    main_source = Path("app/gui/main.py").read_text(encoding="utf-8")

    assert "shutil.copy2" in service_source
    assert "transcod" in service_source.lower()
    assert "overwrite" in service_source.lower()
    assert "generation_controller.output_path_for" in main_source
    assert "audio_player_service" in main_source
    assert "Ctrl+Alt+A" in main_source
