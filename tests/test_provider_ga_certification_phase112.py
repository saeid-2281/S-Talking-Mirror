from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from app.config.runtime import RuntimeConfig
from app.gui.dialogs.provider_ga_certification_dialog import ProviderGACertificationDialog
from app.models.danish_provider_benchmark import DanishProviderCertification
from app.models.provider_manifest import ProviderControlPolicy, ProviderManifest
from app.models.provider_plugin import PLUGIN_SDK_API_VERSION
from app.models.provider_recovery import ProviderRecoveryAssessment, ProviderRecoveryReceipt
from app.models.smart_provider_routing import SmartProviderRoutingState
from app.provider_registry import ProviderRegistry
from app.release import SCHEMA_VERSION
from app.services.provider_ga_certification_service import ProviderGACertificationService


COMMIT = "59f916148609b99ac200440034cb5c1b108e9290"


class _FinalCertificationStub:
    def __init__(self, *, blockers: int = 0, warnings: int = 0, tests: int = 1400) -> None:
        self.blockers = blockers
        self.warnings = warnings
        self.tests = tests

    def assess(self, **_kwargs):
        return SimpleNamespace(
            blocker_count=self.blockers,
            warning_count=self.warnings,
            observed_test_count=self.tests,
            status="blocked" if self.blockers else "certified_with_warnings" if self.warnings else "certified",
            sources=(),
        )


class _PluginStub:
    def __init__(self, active=()) -> None:
        self._active = tuple(active)

    def active_plugins(self):
        return self._active


class _DanishStub:
    def __init__(self, providers) -> None:
        self.providers = tuple(providers)

    def snapshot(self):
        return SimpleNamespace(providers=self.providers)


def _cert(provider_id: str, status: str, documentation: str = "documented") -> DanishProviderCertification:
    return DanishProviderCertification(
        provider_id=provider_id,
        provider_name=provider_id.replace("_", " ").title(),
        status=status,
        documentation_state=documentation,
        score=None,
        case_count=0,
        minimum_cases=10,
    )


def _safe_danish(*, pending: bool = False, murf_status: str = "not_certified"):
    status = "pending" if pending else "certified"
    return (
        _cert("mock", "not_applicable", "test_only"),
        _cert("piper", status, "runtime_dependent"),
        _cert("elevenlabs", status),
        _cert("openai", status),
        _cert("azure", status),
        _cert("google", status),
        _cert("aws_polly", status),
        _cert("kokoro", "not_certified", "unsupported"),
        _cert("cartesia", status),
        _cert("deepgram", "not_certified", "unsupported"),
        _cert("resemble", status),
        _cert("murf", murf_status, "not_explicit"),
    )


def _runner(args, **_kwargs):
    if args == ["git", "rev-parse", "HEAD"]:
        return SimpleNamespace(returncode=0, stdout=f"{COMMIT}\n", stderr="")
    return SimpleNamespace(returncode=1, stdout="", stderr="unsupported")


def _prepare_sources(root: Path) -> None:
    for index, relative in enumerate(ProviderGACertificationService.CRITICAL_SOURCE_PATHS):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"phase112-source-{index}\n", encoding="utf-8")


def _service(
    tmp_path: Path,
    *,
    blockers: int = 0,
    warnings: int = 0,
    tests: int = 1400,
    danish=None,
    active_plugins=(),
    prepare_sources: bool = True,
):
    source_root = tmp_path / "project"
    source_root.mkdir(parents=True, exist_ok=True)
    runtime = RuntimeConfig.from_root(source_root)
    runtime.ensure_directories()
    if prepare_sources:
        _prepare_sources(source_root)
    service = ProviderGACertificationService(
        runtime,
        _FinalCertificationStub(blockers=blockers, warnings=warnings, tests=tests),
        _DanishStub(danish or _safe_danish()),
        _PluginStub(active_plugins),
        registry=ProviderRegistry(),
        version="1.0.0",
        channel="stable",
        schema_version=23,
        source_root=source_root,
        command_runner=_runner,
    )
    return service, runtime, source_root


def test_phase112_does_not_change_database_schema() -> None:
    assert SCHEMA_VERSION == 23


def test_phase112_builtin_provider_contract_is_exact() -> None:
    registry = ProviderRegistry()
    assert registry.provider_ids() == ProviderGACertificationService.EXPECTED_BUILTIN_PROVIDER_IDS
    assert len(registry.provider_ids()) == 12


def test_phase112_clean_provider_track_is_ga_ready(tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path)
    snapshot = service.assess(source_commit=COMMIT)
    assert snapshot.status == "ga_ready"
    assert snapshot.blocker_count == 0
    assert snapshot.warning_count == 0
    assert snapshot.builtin_provider_count == 12
    assert snapshot.observed_test_count == 1400


def test_phase112_base_production_blocker_blocks_ga(tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path, blockers=1)
    snapshot = service.assess(source_commit=COMMIT)
    assert snapshot.status == "blocked"
    gate = next(item for item in snapshot.gates if item.code == "base_production_certification")
    assert gate.status == "block"


def test_phase112_base_production_warning_is_preserved(tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path, warnings=2)
    snapshot = service.assess(source_commit=COMMIT)
    assert snapshot.status == "ga_ready_with_warnings"
    assert snapshot.warning_count >= 1


def test_phase112_missing_critical_source_blocks_ga(tmp_path: Path) -> None:
    service, _runtime, root = _service(tmp_path)
    (root / ProviderGACertificationService.CRITICAL_SOURCE_PATHS[0]).unlink()
    snapshot = service.assess(source_commit=COMMIT)
    gate = next(item for item in snapshot.gates if item.code == "critical_source_custody")
    assert gate.status == "block"
    assert snapshot.status == "blocked"


def test_phase112_pending_danish_benchmarks_warn_without_bypassing_guards(tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path, danish=_safe_danish(pending=True))
    snapshot = service.assess(source_commit=COMMIT)
    gate = next(item for item in snapshot.gates if item.code == "danish_certification_governance")
    assert gate.status == "warn"
    assert snapshot.danish_pending_count > 0
    assert snapshot.status == "ga_ready_with_warnings"


def test_phase112_unsupported_danish_route_cannot_become_certified(tmp_path: Path) -> None:
    providers = list(_safe_danish())
    providers[9] = _cert("deepgram", "certified", "unsupported")
    service, _runtime, _root = _service(tmp_path, danish=providers)
    snapshot = service.assess(source_commit=COMMIT)
    gate = next(item for item in snapshot.gates if item.code == "danish_certification_governance")
    assert gate.status == "block"


def test_phase112_murf_not_explicit_documentation_cannot_be_fully_certified(tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path, danish=_safe_danish(murf_status="certified"))
    snapshot = service.assess(source_commit=COMMIT)
    gate = next(item for item in snapshot.gates if item.code == "danish_certification_governance")
    assert gate.status == "block"


def test_phase112_active_session_plugin_is_warning_not_builtin_mutation(tmp_path: Path) -> None:
    active = SimpleNamespace(provider_id="example_plugin")
    service, _runtime, _root = _service(tmp_path, active_plugins=(active,))
    snapshot = service.assess(source_commit=COMMIT)
    gate = next(item for item in snapshot.gates if item.code == "plugin_sdk_boundary")
    assert gate.status == "warn"
    assert snapshot.active_plugin_count == 1
    assert snapshot.builtin_provider_count == 12


def test_phase112_plugin_sdk_api_v1_is_certification_contract() -> None:
    assert PLUGIN_SDK_API_VERSION == 1


def test_phase112_authority_defaults_preserve_user_control() -> None:
    assert SmartProviderRoutingState.__dataclass_fields__["no_automatic_failover"].default is True
    assert ProviderRecoveryAssessment.__dataclass_fields__["automatic_provider_switch"].default is False
    assert ProviderRecoveryAssessment.__dataclass_fields__["automatic_generation_restart"].default is False
    assert ProviderRecoveryReceipt.__dataclass_fields__["generation_started"].default is False
    assert ProviderGACertificationService._authority_defaults_are_safe()


def test_phase112_request_limit_manifest_contract_remains_certified() -> None:
    assert ProviderGACertificationService._manifest_contract_is_safe()


def test_phase112_plugin_manifest_cannot_replace_builtin_registry(tmp_path: Path) -> None:
    registry = ProviderRegistry()
    duplicate = ProviderManifest(
        "openai",
        "Replacement",
        locality="cloud",
        credential_mode="profile",
        setup_kind="optional_cloud",
        controls=ProviderControlPolicy(api_profile=True),
    )
    try:
        registry.register_plugin_manifest(duplicate)
    except ValueError as exc:
        assert "already registered" in str(exc)
    else:
        raise AssertionError("built-in provider override must be rejected")


def test_phase112_snapshot_is_tamper_evident(tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path)
    path = service.export_snapshot(service.assess(source_commit=COMMIT))
    assert service.verify_snapshot(path)[0]
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["status"] = "blocked"
    path.write_text(json.dumps(payload), encoding="utf-8")
    ok, detail = service.verify_snapshot(path)
    assert not ok
    assert "digest" in detail.lower()


def test_phase112_critical_source_tampering_invalidates_snapshot(tmp_path: Path) -> None:
    service, _runtime, root = _service(tmp_path)
    path = service.export_snapshot(service.assess(source_commit=COMMIT))
    target = root / ProviderGACertificationService.CRITICAL_SOURCE_PATHS[2]
    target.write_text("tampered\n", encoding="utf-8")
    ok, detail = service.verify_snapshot(path)
    assert not ok
    assert "custody changed" in detail.lower()


def test_phase112_attestation_and_audit_pack_verify(tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path)
    result = service.create_attestation(service.assess(source_commit=COMMIT))
    assert result["status"] == "ga_ready"
    assert service.verify_attestation(Path(str(result["path"])))[0]
    assert service.verify_audit_pack(
        Path(str(result["audit_pack_path"])),
        Path(str(result["receipt_path"])),
    )[0]


def test_phase112_attestation_does_not_authorize_automatic_release_actions(tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path)
    result = service.create_attestation(service.assess(source_commit=COMMIT))
    payload = json.loads(Path(str(result["path"])).read_text(encoding="utf-8"))
    contract = payload["safety_contract"]
    assert contract["automatic_publish"] is False
    assert contract["automatic_tag"] is False
    assert contract["automatic_provider_switch"] is False
    assert contract["automatic_generation_start"] is False
    assert contract["automatic_plugin_loading"] is False
    assert contract["automatic_cross_provider_failover"] is False
    assert payload["human_release_promotion_required"] is True


def test_phase112_commit_can_be_resolved_without_guessing(tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path)
    snapshot = service.assess()
    assert snapshot.source_commit == COMMIT


def test_phase112_gui_navigation_and_ga_contract_are_exposed(qt_app, tmp_path: Path) -> None:
    service, _runtime, _root = _service(tmp_path)
    dialog = ProviderGACertificationDialog(service)
    dialog.show()
    qt_app.processEvents()
    assert dialog.objectName() == "providerGACertificationDialog"
    assert dialog.table.rowCount() >= 8
    assert dialog.current_snapshot is not None
    main_text = Path("app/gui/main.py").read_text(encoding="utf-8")
    assert "Provider Track Production Certification / GA" in main_text
    assert "open_provider_ga_certification" in main_text
    service_text = Path("app/services/provider_ga_certification_service.py").read_text(encoding="utf-8")
    assert "automatic_cross_provider_failover" in service_text
    assert "human_release_promotion_required" in service_text
    dialog.close()
