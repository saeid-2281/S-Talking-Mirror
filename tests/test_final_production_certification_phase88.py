from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.final_production_certification_dialog import (
    FinalProductionCertificationDialog,
)
from app.services.final_production_certification_service import (
    FinalProductionCertificationService,
)


COMMIT = "61014db9b9ce6acdfc1d8d86ad36e6b7f990efeb"


class _FinalReleaseStub:
    def __init__(self, runtime: RuntimeConfig, *, valid: bool = True) -> None:
        self.runtime = runtime
        self.valid = valid

    def latest_release_dir(self) -> Path:
        return self.runtime.artifacts_dir / "final-release" / "latest"

    def verify_final_manifest(self, path: Path) -> tuple[bool, str]:
        return self.valid and path.is_file(), "final release manifest verified"

    def verify_update_feed(self, path: Path) -> tuple[bool, str]:
        return self.valid and path.is_file(), "stable update feed verified"


class _LifecycleStub:
    def __init__(self, runtime: RuntimeConfig, *, valid: bool = True) -> None:
        self.root = runtime.artifacts_dir / "release-lifecycle-validation"
        self.valid = valid

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        return self.valid and path.is_file(), "release lifecycle snapshot verified"


class _OperationalReadinessStub:
    def __init__(self, runtime: RuntimeConfig, *, valid: bool = True) -> None:
        self.root = runtime.artifacts_dir / "operational-readiness-certification"
        self.valid = valid

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        return self.valid and path.is_file(), "operational readiness attestation verified"


class _PersistenceStub:
    def __init__(self, *, valid: bool = True) -> None:
        self.valid = valid

    def verify_database(self) -> tuple[bool, str]:
        return self.valid, (
            "operational persistence verified"
            if self.valid
            else "operational persistence digest mismatch"
        )


def _runtime(tmp_path: Path) -> RuntimeConfig:
    runtime = RuntimeConfig.from_root(tmp_path / "project")
    runtime.ensure_directories()
    return runtime


def _runner(*, dirty: str = ""):
    def run(args, **_kwargs):
        if args[1:] == ["rev-parse", "HEAD"]:
            return SimpleNamespace(returncode=0, stdout=f"{COMMIT}\n", stderr="")
        if args[1:] == ["status", "--porcelain"]:
            return SimpleNamespace(returncode=0, stdout=dirty, stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")

    return run


def _write_release_check(runtime: RuntimeConfig, *, commit: str = COMMIT, passed: int = 1200) -> Path:
    path = runtime.artifacts_dir / "release-check" / "latest" / "result.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "success": True,
        "exit_code": 0,
        "application_version": "1.0.0",
        "release_channel": "stable",
        "source_commit": commit,
        "working_tree_clean": True,
        "steps": {"pytest": {"success": True, "exit_code": 0, "passed": passed}},
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _write_supplemental(runtime: RuntimeConfig) -> None:
    paths = (
        runtime.artifacts_dir / "final-release" / "latest" / "final-release-manifest.json",
        runtime.artifacts_dir / "update-channel" / "stable" / "latest.json",
        runtime.artifacts_dir
        / "release-lifecycle-validation"
        / "latest-release-lifecycle-validation.json",
        runtime.artifacts_dir
        / "operational-readiness-certification"
        / "latest-operational-readiness-attestation.json",
    )
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"status":"verified"}', encoding="utf-8")


def _service(
    tmp_path: Path,
    *,
    dirty: str = "",
    final_valid: bool = True,
    lifecycle_valid: bool = True,
    operational_valid: bool = True,
    persistence_valid: bool = True,
) -> tuple[FinalProductionCertificationService, RuntimeConfig]:
    runtime = _runtime(tmp_path)
    service = FinalProductionCertificationService(
        runtime,
        _FinalReleaseStub(runtime, valid=final_valid),
        _LifecycleStub(runtime, valid=lifecycle_valid),
        _OperationalReadinessStub(runtime, valid=operational_valid),
        _PersistenceStub(valid=persistence_valid),
        version="1.0.0",
        channel="stable",
        schema_version=23,
        command_runner=_runner(dirty=dirty),
    )
    return service, runtime


def test_phase88_clean_post_commit_release_check_certifies_source(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path)
    _write_release_check(runtime)
    _write_supplemental(runtime)
    snapshot = service.assess(minimum_test_count=1100)
    assert snapshot.status == "certified"
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0
    assert snapshot.observed_test_count == 1200
    assert snapshot.source_commit == COMMIT
    assert len(snapshot.sources) == 5


def test_phase88_release_check_must_match_commit_and_test_floor(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path)
    _write_release_check(runtime, commit="a" * 40, passed=1099)
    snapshot = service.assess(source_commit=COMMIT, minimum_test_count=1100)
    gate = next(item for item in snapshot.gates if item.code == "release_check")
    assert gate.status == "block"
    assert snapshot.status == "blocked"
    assert snapshot.observed_test_count == 1099


def test_phase88_only_approved_local_profiles_may_remain_dirty(tmp_path: Path) -> None:
    service, runtime = _service(
        tmp_path,
        dirty=" M api-profiles.json\n M workspace-profiles.json\n",
    )
    _write_release_check(runtime)
    snapshot = service.assess()
    assert next(item for item in snapshot.gates if item.code == "source_identity").status == "pass"

    blocked, runtime2 = _service(tmp_path / "other", dirty=" M app/gui/main.py\n")
    _write_release_check(runtime2)
    snapshot2 = blocked.assess()
    assert next(item for item in snapshot2.gates if item.code == "source_identity").status == "block"


def test_phase88_missing_supplemental_runtime_evidence_does_not_hide_core_gate(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path)
    _write_release_check(runtime)
    snapshot = service.assess()
    assert snapshot.status == "certified"
    assert snapshot.blocker_count == 0
    assert snapshot.observed_test_count == 1200
    assert len(snapshot.sources) == 1


def test_phase88_present_but_invalid_supplemental_evidence_warns(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path, final_valid=False)
    _write_release_check(runtime)
    _write_supplemental(runtime)
    snapshot = service.assess()
    assert snapshot.status == "certified_with_warnings"
    assert next(item for item in snapshot.gates if item.code == "final_manifest").status == "warn"


def test_phase88_persistence_integrity_is_mandatory(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path, persistence_valid=False)
    _write_release_check(runtime)
    snapshot = service.assess()
    gate = next(item for item in snapshot.gates if item.code == "persistence_integrity")
    assert gate.status == "block"
    assert snapshot.status == "blocked"


def test_phase88_attestation_requires_human_acknowledgement_and_verifies_pack(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path)
    _write_release_check(runtime)
    _write_supplemental(runtime)
    snapshot = service.assess()
    dry_run = service.create_certification(
        snapshot,
        reviewer="Release operator",
        statement="Reviewed final S-Talking 1.x production gates.",
        acknowledge=False,
    )
    assert dry_run["status"] == "dry_run"
    result = service.create_certification(
        snapshot,
        reviewer="Release operator",
        statement="Reviewed final S-Talking 1.x production gates.",
        acknowledge=True,
    )
    assert result["status"] == "certified"
    attestation = Path(str(result["path"]))
    pack = Path(str(result["audit_pack_path"]))
    receipt = Path(str(result["receipt_path"]))
    assert service.verify_attestation(attestation)[0]
    assert service.verify_audit_pack(pack, receipt)[0]


def test_phase88_source_custody_tampering_is_detected(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path)
    release_check = _write_release_check(runtime)
    snapshot_path = service.export_snapshot(service.assess())
    assert service.verify_snapshot(snapshot_path)[0]
    release_check.write_text("{}", encoding="utf-8")
    ok, detail = service.verify_snapshot(snapshot_path)
    assert not ok
    assert "custody changed" in detail


def test_phase88_private_reviewer_material_is_rejected(tmp_path: Path) -> None:
    service, runtime = _service(tmp_path)
    _write_release_check(runtime)
    snapshot = service.assess()
    result = service.create_certification(
        snapshot,
        reviewer=r"C:\\Users\\release\\operator",
        statement="Final review complete.",
        acknowledge=True,
    )
    assert result["status"] == "blocked"
    assert "private" in str(result["detail"]).casefold()


def test_phase88_gui_cli_navigation_and_safety_contract_are_exposed(
    qt_app,
    tmp_path: Path,
) -> None:
    service, runtime = _service(tmp_path)
    _write_release_check(runtime)
    dialog = FinalProductionCertificationDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "finalProductionCertificationDialog"
    assert dialog.table.rowCount() >= 8
    assert dialog.current_snapshot is not None
    assert dialog.current_snapshot.status == "certified"

    main_text = Path("app/gui/main.py").read_text(encoding="utf-8")
    frozen_text = Path("app/frozen_main.py").read_text(encoding="utf-8")
    workspace_text = Path(
        "app/gui/dialogs/operations_workspace_dialog.py"
    ).read_text(encoding="utf-8")
    assert "Final S-Talking 1.x Production Certification" in main_text
    assert "open_final_production_certification" in main_text
    assert "--final-production-certification" in frozen_text
    assert "final-production-certification" in workspace_text
    contract = service._safety_contract()
    assert contract["automatic_publish"] is False
    assert contract["automatic_install"] is False
    assert contract["automatic_restore"] is False
    assert contract["automatic_rollback"] is False
    assert contract["human_acknowledgement_required"] is True
    dialog.close()
