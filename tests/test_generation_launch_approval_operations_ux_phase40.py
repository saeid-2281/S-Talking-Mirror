from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication, QDialog

from app.gui.dialogs.generation_launch_guard_approval_dialog import (
    GenerationLaunchGuardApprovalDialog,
    GenerationLaunchGuardApprovalRenewDialog,
)
from app.gui.dialogs.generation_launch_receipt_dialog import GenerationLaunchReceiptDialog
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


def _dispose_dialog(qt_app: QApplication, dialog: QDialog | None) -> None:
    if dialog is None:
        return
    dialog.close()
    QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
    qt_app.processEvents()


def _write_receipt(
    service: GenerationLaunchReceiptService,
    *,
    project_name: str,
    receipt_id: str,
    fingerprint: str,
    approval_id: str = "",
) -> Path:
    folder = service.reports_dir / project_name / "launches" / receipt_id
    folder.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "schema_version": 2,
        "receipt_id": receipt_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "project_name": project_name,
        "launch_fingerprint": fingerprint,
        "preflight_status": "Ready",
        "review_status": "ready",
        "acknowledged_codes": [],
        "required_acknowledgements": [],
        "guard_exception": (
            {
                "approval_id": approval_id,
                "candidate_fingerprint": fingerprint,
                "baseline_receipt_id": "baseline-receipt",
                "protected_change_keys": ["provider"],
            }
            if approval_id
            else None
        ),
        "scope": {
            "files": 1,
            "characters": 100,
            "provider_requests": 1,
            "existing_outputs": 0,
        },
        "settings": {
            "provider": "mock",
            "model_id": "model-a",
            "voice_id": "voice-a",
        },
        "output_directory": str(service.reports_dir / "output"),
        "generation_plan": {
            "risk_level": "low",
            "estimated_cost": 0.01,
            "currency": "USD",
        },
    }
    payload["integrity"] = {
        "algorithm": "sha256",
        "digest": service.canonical_digest(payload),
    }
    path = folder / service.RECEIPT_NAME
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    path.with_name(service.MARKDOWN_NAME).write_text("# Launch\n", encoding="utf-8")
    return path


def _setup(tmp_path: Path) -> tuple[GenerationLaunchReceiptService, str, str]:
    service = GenerationLaunchReceiptService(tmp_path / "reports")
    project = "Phase 40 Project"
    baseline_fingerprint = "a" * 64
    baseline_path = _write_receipt(
        service,
        project_name=project,
        receipt_id="baseline-receipt",
        fingerprint=baseline_fingerprint,
    )
    service.set_baseline(service.load(baseline_path))
    return service, project, baseline_fingerprint


def _approve(
    service: GenerationLaunchReceiptService,
    project: str,
    *,
    fingerprint: str = "b" * 64,
    approved_by: str = "Release operator",
    reason: str = "Approved controlled provider migration for this batch.",
    max_uses: int = 2,
):
    return service.create_guard_approval(
        project_name=project,
        launch_fingerprint=fingerprint,
        baseline_receipt_id="baseline-receipt",
        protected_change_keys=("provider",),
        reason=reason,
        approved_by=approved_by,
        duration_minutes=60,
        max_uses=max_uses,
    )


def test_phase40_summary_and_filters_cover_full_approval_lifecycle(tmp_path: Path) -> None:
    service, project, _ = _setup(tmp_path)
    active = _approve(service, project, fingerprint="b" * 64)
    consumed = _approve(service, project, fingerprint="c" * 64, max_uses=1)
    revoked = _approve(service, project, fingerprint="d" * 64)
    expired = _approve(service, project, fingerprint="e" * 64)
    assert service.consume_guard_approval(consumed.approval_id) is True
    assert service.revoke_guard_approval(revoked.approval_id) is True
    payload = service._read_guard_approval_index()
    for record in payload["approvals"]:
        if record["approval_id"] == expired.approval_id:
            record["expires_at"] = (
                datetime.now(timezone.utc) - timedelta(minutes=1)
            ).isoformat()
    service._write_guard_approval_index(payload)

    records = service.list_guard_approvals(project_name=project)
    summary = service.guard_approval_summary(records)

    assert summary.total_count == 4
    assert summary.active_count == 1
    assert summary.consumed_count == 1
    assert summary.revoked_count == 1
    assert summary.expired_count == 1
    assert service.list_guard_approvals(status="approved") == [
        next(item for item in records if item.approval_id == active.approval_id)
    ]
    assert len(service.list_guard_approvals(search="release operator")) == 4


def test_phase40_renewal_creates_linked_version_without_mutating_original(tmp_path: Path) -> None:
    service, project, _ = _setup(tmp_path)
    original = _approve(service, project)

    renewed = service.renew_guard_approval(
        original.approval_id,
        approved_by="Senior operator",
        reason="Renewed for the next controlled production window.",
        duration_minutes=240,
        max_uses=3,
    )
    records = service.list_guard_approvals(project_name=project)
    stored_original = next(item for item in records if item.approval_id == original.approval_id)

    assert renewed.approval_id != original.approval_id
    assert renewed.renewed_from_id == original.approval_id
    assert renewed.max_uses == 3
    assert renewed.audit_events[0].action == "renewed"
    assert stored_original.renewed_from_id == ""
    assert stored_original.max_uses == original.max_uses


def test_phase40_revoke_and_consume_append_audit_events_and_receipt_id(tmp_path: Path) -> None:
    service, project, _ = _setup(tmp_path)
    consumed = _approve(service, project, fingerprint="c" * 64, max_uses=1)
    revoked = _approve(service, project, fingerprint="d" * 64)

    assert service.consume_guard_approval(
        consumed.approval_id,
        receipt_id="launch-used-001",
    ) is True
    assert service.revoke_guard_approval(revoked.approval_id) is True
    records = service.list_guard_approvals(project_name=project)
    consumed_record = next(item for item in records if item.approval_id == consumed.approval_id)
    revoked_record = next(item for item in records if item.approval_id == revoked.approval_id)

    assert consumed_record.audit_events[-1].action == "consumed"
    assert consumed_record.audit_events[-1].receipt_id == "launch-used-001"
    assert consumed_record.last_used_at
    assert revoked_record.audit_events[-1].action == "revoked"
    assert revoked_record.revoked_at


def test_phase40_approval_usage_links_back_to_launch_receipts(tmp_path: Path) -> None:
    service, project, _ = _setup(tmp_path)
    approval = _approve(service, project, max_uses=3)
    _write_receipt(
        service,
        project_name=project,
        receipt_id="launch-with-approval",
        fingerprint="b" * 64,
        approval_id=approval.approval_id,
    )

    receipts = service.receipts_for_guard_approval(approval.approval_id)

    assert len(receipts) == 1
    assert receipts[0].receipt_id == "launch-with-approval"
    assert receipts[0].guard_approval_id == approval.approval_id


def test_phase40_approval_exports_are_filtered_and_secret_free(tmp_path: Path) -> None:
    service, project, _ = _setup(tmp_path)
    _approve(service, project, reason="Approved migration without credentials or source text.")
    records = service.list_guard_approvals(project_name=project)

    json_path, csv_path = service.export_guard_approvals(
        records,
        tmp_path / "exports",
        project_name=project,
    )
    exported = json_path.read_text(encoding="utf-8") + csv_path.read_text(
        encoding="utf-8-sig"
    )

    assert '"active_count": 1' in exported
    assert "renewed_from_id" in exported
    assert "api_key" not in exported
    assert "must-never-be-serialized" not in exported


def test_phase40_operations_center_filters_metrics_details_and_export(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    service, project, _ = _setup(tmp_path)
    approval = _approve(service, project)
    dialog = GenerationLaunchGuardApprovalDialog(
        service,
        "all-projects",
        export_dir=tmp_path / "exports",
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.objectName() == "generationLaunchGuardApprovalDialog"
    assert dialog.metric_values["total"].text() == "1"
    assert dialog.metric_values["active"].text() == "1"
    dialog.table.selectRow(0)
    qt_app.processEvents()
    assert approval.approval_id in dialog.details.toPlainText()
    assert "Audit events:" in dialog.details.toPlainText()
    dialog.status_filter.setCurrentIndex(dialog.status_filter.findData("revoked"))
    qt_app.processEvents()
    assert dialog.table.rowCount() == 0
    dialog.status_filter.setCurrentIndex(0)
    qt_app.processEvents()
    paths = dialog.export_filtered()
    assert paths is not None and all(path.exists() for path in paths)
    _dispose_dialog(qt_app, dialog)


def test_phase40_renew_dialog_and_operations_create_replacement(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    service, project, _ = _setup(tmp_path)
    approval = _approve(service, project)
    operations = GenerationLaunchGuardApprovalDialog(service, project)
    operations.show()
    qt_app.processEvents()
    operations.table.selectRow(0)
    renew = GenerationLaunchGuardApprovalRenewDialog(approval, operations)
    renew.show()
    qt_app.processEvents()
    renew.approved_by.setText("Senior operator")
    renew.reason.setPlainText("Renewed for the approved maintenance window.")
    assert renew.submit() is True
    replacement = operations.renew_approval(approval, **renew.values)

    assert replacement is not None
    assert replacement.renewed_from_id == approval.approval_id
    assert len(service.list_guard_approvals(project_name=project)) == 2
    _dispose_dialog(qt_app, renew)
    _dispose_dialog(qt_app, operations)


def test_phase40_receipt_center_opens_global_approval_operations(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    service, project, _ = _setup(tmp_path)
    _approve(service, project)
    dialog = GenerationLaunchReceiptDialog(
        service,
        project_name="all-projects",
        export_dir=tmp_path / "exports",
    )
    dialog.show()
    qt_app.processEvents()

    assert dialog.guard_approval_button.text() == "Approval operations"
    assert dialog.guard_approval_button.isEnabled() is True
    child = dialog.open_guard_approvals()
    qt_app.processEvents()

    assert child is not None
    assert child.project_name == "all-projects"
    assert child.table.rowCount() == 1
    _dispose_dialog(qt_app, child)
    _dispose_dialog(qt_app, dialog)
