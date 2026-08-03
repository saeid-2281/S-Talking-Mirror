from __future__ import annotations

import hashlib
import json
import zipfile

import pytest
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QTableWidget

from app.gui.dialogs.generation_artifact_retention_dialog import (
    GenerationArtifactRetentionDialog,
)
from app.models.generation_artifact_retention import GenerationArtifactRetentionPolicy
from app.services.generation_artifact_retention_service import (
    GenerationArtifactRetentionService,
)


NOW = datetime(2026, 8, 3, 12, 0, tzinfo=timezone.utc)
OLD = "2024-01-01T12:00:00+00:00"
RECENT = "2026-08-01T12:00:00+00:00"


def _service(tmp_path: Path) -> GenerationArtifactRetentionService:
    return GenerationArtifactRetentionService(tmp_path, now_factory=lambda: NOW)


def _write_payload(path: Path, payload: dict[str, object], *, valid_integrity: bool = True) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = dict(payload)
    if valid_integrity:
        encoded = json.dumps(
            clean,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )
        clean["integrity"] = {
            "algorithm": "sha256",
            "digest": hashlib.sha256(encoded.encode("utf-8")).hexdigest(),
        }
    path.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _old_launch(root: Path, *, project: str = "Alpha", valid_integrity: bool = True) -> Path:
    folder = root / project / "launch-receipts" / "launch-old"
    path = _write_payload(
        folder / "generation-launch.json",
        {
            "schema_version": 2,
            "receipt_id": "launch-old",
            "created_at": OLD,
            "project_name": project,
        },
        valid_integrity=valid_integrity,
    )
    path.with_name("generation-launch.md").write_text("launch markdown", encoding="utf-8")
    return path


def _old_run(root: Path, *, status: str = "completed") -> Path:
    folder = root / "Alpha" / "runs" / "run-old"
    path = _write_payload(
        folder / "generation-execution.json",
        {
            "schema_version": 1,
            "run_id": "run-old",
            "status": status,
            "started_at": OLD,
            "project": {"name": "Alpha"},
        },
    )
    path.with_name("generation-execution.md").write_text("session", encoding="utf-8")
    path.with_name("generation-execution-receipt.json").write_text("{}", encoding="utf-8")
    path.with_name("generation-execution-receipt.md").write_text("receipt", encoding="utf-8")
    path.with_name("output-manifest.csv").write_text("filename\na.mp3\n", encoding="utf-8")
    return path


def test_policy_round_trip_is_project_scoped(tmp_path: Path) -> None:
    service = _service(tmp_path)
    saved = service.save_policy(
        GenerationArtifactRetentionPolicy(
            project_name="Alpha",
            launch_receipt_days=90,
            execution_run_days=120,
            archive_before_delete=False,
        )
    )
    loaded = service.get_policy("Alpha")
    other = service.get_policy("Beta")

    assert saved.updated_at == NOW.isoformat()
    assert loaded.launch_receipt_days == 90
    assert loaded.execution_run_days == 120
    assert loaded.archive_before_delete is False
    assert other.launch_receipt_days == 365


def test_preview_selects_stale_receipts_and_terminal_runs_only(tmp_path: Path) -> None:
    _old_launch(tmp_path)
    _old_run(tmp_path, status="completed")
    active = tmp_path / "Alpha" / "runs" / "run-active" / "generation-execution.json"
    _write_payload(
        active,
        {
            "run_id": "run-active",
            "status": "running",
            "started_at": OLD,
            "project": {"name": "Alpha"},
        },
    )
    recent = tmp_path / "Alpha" / "launch-receipts" / "launch-new" / "generation-launch.json"
    _write_payload(recent, {"receipt_id": "launch-new", "created_at": RECENT, "project_name": "Alpha"})

    preview = _service(tmp_path).preview(project_name="Alpha")
    types = {item.artifact_type for item in preview.candidates}
    ids = {item.identifier for item in preview.candidates}

    assert types == {"launch_receipt", "execution_run"}
    assert "launch-old" in ids
    assert "run-old" in ids
    assert "run-active" not in ids
    assert preview.actionable_count == 2


def test_integrity_mismatch_is_review_only_by_default(tmp_path: Path) -> None:
    path = _old_launch(tmp_path, valid_integrity=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["integrity"] = {"algorithm": "sha256", "digest": "wrong"}
    path.write_text(json.dumps(payload), encoding="utf-8")
    (tmp_path / "generation-launch-receipt-baselines.json").write_text(
        json.dumps(
            {
                "projects": {
                    "alpha": {
                        "project_name": "Alpha",
                        "receipt_id": "launch-old",
                        "receipt_path": str(path.relative_to(tmp_path)),
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    preview = _service(tmp_path).preview(project_name="Alpha")
    candidate = preview.candidates[0]

    assert candidate.integrity_status == "mismatch"
    assert candidate.action == "review"
    assert candidate.protected is True
    assert preview.actionable_count == 0


def test_orphan_companion_is_detected_after_grace_period(tmp_path: Path) -> None:
    orphan = tmp_path / "Alpha" / "runs" / "orphan-run" / "output-manifest.csv"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("filename\na.mp3\n", encoding="utf-8")
    old_epoch = datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()
    orphan.touch()
    import os

    os.utime(orphan, (old_epoch, old_epoch))
    policy = GenerationArtifactRetentionPolicy(project_name="Alpha", orphan_grace_days=7)

    preview = _service(tmp_path).preview(project_name="Alpha", policy=policy)

    assert preview.orphan_count == 1
    assert preview.candidates[0].artifact_type == "orphan"
    assert preview.candidates[0].path == orphan


def test_terminal_approval_and_budget_records_become_virtual_candidates(tmp_path: Path) -> None:
    (tmp_path / "generation-launch-guard-approvals.json").write_text(
        json.dumps(
            {
                "approvals": [
                    {
                        "approval_id": "guard-old",
                        "project_name": "Alpha",
                        "status": "consumed",
                        "created_at": OLD,
                    },
                    {
                        "approval_id": "guard-active",
                        "project_name": "Alpha",
                        "status": "approved",
                        "created_at": OLD,
                        "expires_at": "2027-01-01T00:00:00+00:00",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "generation-budget-guard.json").write_text(
        json.dumps(
            {
                "reservations": [
                    {
                        "reservation_id": "reservation-old",
                        "project_name": "Alpha",
                        "status": "settled",
                        "created_at": OLD,
                    }
                ],
                "approvals": [],
            }
        ),
        encoding="utf-8",
    )

    preview = _service(tmp_path).preview(project_name="Alpha")
    identifiers = {item.identifier for item in preview.candidates}

    assert identifiers == {"guard-old", "reservation-old"}
    assert all(item.virtual_record for item in preview.candidates)


def test_dry_run_records_audit_without_removing_files(tmp_path: Path) -> None:
    receipt = _old_launch(tmp_path)
    service = _service(tmp_path)
    preview = service.preview(project_name="Alpha")
    result = service.apply(preview, dry_run=True)

    assert result.status == "dry_run"
    assert receipt.is_file()
    assert result.deleted_count == 0
    assert service.list_runs()[0].run_id == result.run_id

    receipt.with_name("generation-launch.md").write_text("changed after preview", encoding="utf-8")
    with pytest.raises(ValueError, match="stale"):
        service.apply(preview)


def test_apply_creates_verified_archive_and_never_deletes_audio_output(tmp_path: Path) -> None:
    receipt = _old_launch(tmp_path)
    run = _old_run(tmp_path)
    output = tmp_path / "Alpha" / "generated-audio" / "lesson.mp3"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"audio-output-must-remain")
    service = _service(tmp_path)
    preview = service.preview(project_name="Alpha")
    result = service.apply(preview)

    assert result.status == "completed"
    assert result.archive_path is not None and result.archive_path.is_file()
    assert result.manifest_path is not None and result.manifest_path.is_file()
    assert service.verify_archive(result.archive_path, result.archive_sha256)[0] is True
    assert receipt.exists() is False
    assert run.exists() is False
    assert output.read_bytes() == b"audio-output-must-remain"
    with zipfile.ZipFile(result.archive_path) as archive:
        names = set(archive.namelist())
    assert "_retention_manifest.json" in names
    assert any(name.endswith("generation-launch.json") for name in names)


def test_export_is_secret_free_and_dialog_exposes_scroll_safe_tables(qt_app, tmp_path: Path) -> None:
    _old_launch(tmp_path)
    service = _service(tmp_path)
    preview = service.preview(project_name="Alpha")
    exported = service.export_preview(preview, tmp_path / "exports")
    combined = exported[0].read_text(encoding="utf-8") + exported[1].read_text(encoding="utf-8-sig")
    dialog = GenerationArtifactRetentionDialog(
        service,
        project_name="Alpha",
        export_dir=tmp_path / "exports",
    )

    assert "api_key" not in combined.casefold()
    assert "sk_" not in combined.casefold()
    assert dialog.objectName() == "generationArtifactRetentionDialog"
    assert dialog.minimumWidth() >= 820
    assert isinstance(dialog.candidate_table, QTableWidget)
    assert dialog.candidate_table.rowCount() == 1
    assert isinstance(dialog.run_table, QTableWidget)

    dialog.close()
    dialog.deleteLater()
    qt_app.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()
