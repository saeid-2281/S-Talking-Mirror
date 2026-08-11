from __future__ import annotations

import hashlib
import re
import subprocess
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable, Mapping

import app
from app.config.runtime import RuntimeConfig
from app.models.danish_provider_benchmark import DanishProviderCertification
from app.models.provider_ga_certification import (
    ProviderGACertificationGate,
    ProviderGACertificationSnapshot,
    ProviderGACertificationSource,
)
from app.models.provider_plugin import PLUGIN_SDK_API_VERSION
from app.models.provider_recovery import ProviderRecoveryAssessment, ProviderRecoveryReceipt
from app.models.smart_provider_routing import SmartProviderRoutingState
from app.provider_registry import DEFAULT_PROVIDER_MANIFESTS, DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from app.release import SCHEMA_VERSION
from app.services.danish_provider_benchmark_service import DanishProviderBenchmarkService
from app.services.evidence_integrity import EvidenceIntegrityMixin
from app.services.final_production_certification_service import FinalProductionCertificationService
from app.services.provider_plugin_sdk_service import ProviderPluginSDKService


class ProviderGACertificationService(EvidenceIntegrityMixin):
    """Final machine-verifiable GA boundary for the Phase 98-111 provider track.

    The service adds provider-specific architecture evidence to the existing final
    production certification. It never publishes, tags, activates plugins, switches
    providers, refreshes catalogs, or starts generation. A successful attestation is
    GA evidence only; release promotion remains an explicit human action.
    """

    DOCUMENT_SCHEMA_VERSION = 1
    DEFAULT_MINIMUM_TEST_COUNT = FinalProductionCertificationService.DEFAULT_MINIMUM_TEST_COUNT
    EXPECTED_BUILTIN_PROVIDER_IDS = (
        "mock",
        "piper",
        "elevenlabs",
        "openai",
        "azure",
        "google",
        "aws_polly",
        "kokoro",
        "cartesia",
        "deepgram",
        "resemble",
        "murf",
    )
    CRITICAL_SOURCE_PATHS = (
        "app/release.py",
        "app/provider_registry.py",
        "app/provider_factory.py",
        "app/services/preflight_service.py",
        "app/services/generation_confirmation_service.py",
        "app/services/unified_preflight_decision_service.py",
        "app/services/provider_accounts_center_service.py",
        "app/services/unified_voice_model_catalog_service.py",
        "app/services/provider_cost_quota_limits_service.py",
        "app/services/smart_provider_routing_service.py",
        "app/services/danish_provider_benchmark_service.py",
        "app/services/user_controlled_provider_recovery_service.py",
        "app/services/provider_plugin_sdk_service.py",
        "app/plugin_sdk/__init__.py",
        "app/models/provider_ga_certification.py",
        "app/services/provider_ga_certification_service.py",
    )
    _COMMIT_RE = re.compile(r"^[0-9a-f]{7,40}$", re.IGNORECASE)
    _SECRET_RE = re.compile(
        r"(?i)(api[_-]?key\s*[:=]|authorization\s*[:=]|bearer\s+[A-Za-z0-9]|password\s*[:=]|passwd\s*[:=]|token\s*[:=]|private[_-]?key)"
    )
    _ABSOLUTE_PATH_RE = re.compile(
        r"(?i)(?:[A-Z]:[\\/]|/home/|/Users/|/tmp/|/var/tmp/|\\\\[^\\]+\\[^\\]+)"
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        final_production_certification_service: FinalProductionCertificationService,
        danish_provider_benchmark_service: DanishProviderBenchmarkService,
        provider_plugin_sdk_service: ProviderPluginSDKService,
        *,
        registry: ProviderRegistry | None = None,
        version: str | None = None,
        channel: str | None = None,
        schema_version: int | None = None,
        source_root: Path | None = None,
        now: Callable[[], datetime] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.final_production_certification_service = final_production_certification_service
        self.danish_provider_benchmark_service = danish_provider_benchmark_service
        self.provider_plugin_sdk_service = provider_plugin_sdk_service
        self.registry = registry or DEFAULT_PROVIDER_REGISTRY
        self.version = str(version or app.__version__)
        self.channel = str(channel or getattr(app, "__release_channel__", ""))
        self.schema_version = int(schema_version if schema_version is not None else SCHEMA_VERSION)
        self.source_root = Path(source_root or runtime.app_root)
        self.root = runtime.artifacts_dir / "provider-ga-certification"
        self.snapshots_dir = self.root / "snapshots"
        self.attestations_dir = self.root / "attestations"
        self.audit_packs_dir = self.root / "audit-packs"
        self.receipts_dir = self.root / "receipts"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._command_runner = command_runner or subprocess.run
        for folder in (
            self.root,
            self.snapshots_dir,
            self.attestations_dir,
            self.audit_packs_dir,
            self.receipts_dir,
        ):
            folder.mkdir(parents=True, exist_ok=True)

    @classmethod
    def _safety_contract(cls) -> dict[str, object]:
        return {
            "automatic_publish": False,
            "automatic_tag": False,
            "automatic_install": False,
            "automatic_update": False,
            "automatic_provider_switch": False,
            "automatic_generation_start": False,
            "automatic_plugin_loading": False,
            "automatic_catalog_refresh": False,
            "automatic_cross_provider_failover": False,
            "human_release_promotion_required": True,
        }

    def assess(
        self,
        *,
        source_commit: str = "",
        minimum_test_count: int | None = None,
    ) -> ProviderGACertificationSnapshot:
        commit = self._resolve_commit(source_commit)
        minimum_tests = max(
            1,
            int(
                self.DEFAULT_MINIMUM_TEST_COUNT
                if minimum_test_count is None
                else minimum_test_count
            ),
        )
        gates: list[ProviderGACertificationGate] = []
        sources: list[ProviderGACertificationSource] = []

        base = self.final_production_certification_service.assess(
            source_commit=commit,
            minimum_test_count=minimum_tests,
        )
        if base.blocker_count:
            base_status = "block"
            base_detail = (
                f"Base production certification has {base.blocker_count} blocker(s) "
                f"and {base.warning_count} warning(s)."
            )
        elif base.warning_count:
            base_status = "warn"
            base_detail = (
                f"Base production certification passed with {base.warning_count} supplemental warning(s)."
            )
        else:
            base_status = "pass"
            base_detail = "Base Phase 88 production certification gates pass for this source commit."
        gates.append(
            self._gate(
                "base_production_certification",
                "Base production certification",
                base_status,
                "blocker",
                base_detail,
                "Resolve base production certification blockers before GA promotion.",
            )
        )
        for source in base.sources:
            sources.append(
                ProviderGACertificationSource(
                    role=f"base:{source.role}",
                    label=source.label,
                    relative_path=source.relative_path,
                    sha256=source.sha256,
                    required=source.required,
                )
            )

        commit_ok = self._COMMIT_RE.fullmatch(commit) is not None
        gates.append(
            self._gate(
                "source_commit",
                "Immutable provider-track source commit",
                "pass" if commit_ok else "block",
                "blocker",
                f"Provider GA evidence is bound to source commit {commit or 'unknown'}.",
                "Commit the reviewed Phase 112 source before GA certification.",
            )
        )

        critical_ok, critical_detail = self._collect_critical_sources(sources)
        gates.append(
            self._gate(
                "critical_source_custody",
                "Critical provider-track source custody",
                "pass" if critical_ok else "block",
                "blocker",
                critical_detail,
                "Restore the reviewed provider-track source files before certification.",
            )
        )

        registered = self.registry.provider_ids()
        plugin_ids = set(self.registry.plugin_provider_ids())
        builtin_ids = tuple(item for item in registered if item not in plugin_ids)
        expected = self.EXPECTED_BUILTIN_PROVIDER_IDS
        registry_ok = builtin_ids == expected and len(set(registered)) == len(registered)
        gates.append(
            self._gate(
                "builtin_provider_registry",
                "Built-in provider registry contract",
                "pass" if registry_ok else "block",
                "blocker",
                (
                    f"All {len(expected)} built-in provider IDs are registered in the certified order."
                    if registry_ok
                    else f"Expected built-in providers {expected}; observed {builtin_ids}."
                ),
                "Restore the Phase 111 built-in registry before GA certification.",
            )
        )

        account_contract_ok, account_detail = self._provider_account_contract()
        gates.append(
            self._gate(
                "provider_account_surface",
                "Managed provider account surface",
                "pass" if account_contract_ok else "block",
                "blocker",
                account_detail,
                "Keep every credentialed cloud provider on the explicit Provider Accounts surface.",
            )
        )

        danish_gate, danish_pending = self._danish_governance_gate()
        gates.append(danish_gate)

        authority_ok = self._authority_defaults_are_safe()
        gates.append(
            self._gate(
                "selection_and_generation_authority",
                "User selection / Preflight / Generation authority",
                "pass" if authority_ok else "block",
                "blocker",
                (
                    "Routing, recovery and resume models preserve explicit user control and no automatic cross-provider failover."
                    if authority_ok
                    else "A provider-routing or recovery default permits automatic behavior and violates the authority contract."
                ),
                "Restore explicit user selection, Preflight and Generation authority defaults.",
            )
        )

        active_plugins = tuple(self.provider_plugin_sdk_service.active_plugins())
        plugin_ok = PLUGIN_SDK_API_VERSION == 1
        if not plugin_ok:
            plugin_status = "block"
            plugin_detail = f"Expected Plugin SDK API v1; observed {PLUGIN_SDK_API_VERSION}."
        elif active_plugins:
            plugin_status = "warn"
            plugin_detail = (
                f"Plugin SDK API v1 is valid, but {len(active_plugins)} session plugin(s) are active. "
                "Canonical GA evidence should be captured from a clean application session."
            )
        else:
            plugin_status = "pass"
            plugin_detail = "Plugin SDK API v1 is available with no automatically loaded session plugins."
        gates.append(
            self._gate(
                "plugin_sdk_boundary",
                "Provider Plugin SDK boundary",
                plugin_status,
                "blocker",
                plugin_detail,
                "Restart without session plugins before canonical GA evidence if needed.",
            )
        )

        manifest_contract_ok = self._manifest_contract_is_safe()
        gates.append(
            self._gate(
                "provider_manifest_contract",
                "Provider manifest / limits contract",
                "pass" if manifest_contract_ok else "block",
                "blocker",
                (
                    "Credential, locality and request-limit metadata remain explicit in the built-in manifests."
                    if manifest_contract_ok
                    else "One or more built-in manifests violate the GA provider metadata contract."
                ),
                "Restore explicit credential/locality/request-limit metadata before GA certification.",
            )
        )

        safety_ok = all(
            value is False
            for key, value in self._safety_contract().items()
            if key.startswith("automatic_")
        ) and self._safety_contract()["human_release_promotion_required"] is True
        gates.append(
            self._gate(
                "ga_safety_boundary",
                "GA evidence safety boundary",
                "pass" if safety_ok else "block",
                "blocker",
                "GA certification writes evidence only; publication, tags, installation and provider/generation actions remain manual.",
            )
        )

        blockers = sum(item.status == "block" for item in gates)
        warnings = sum(item.status == "warn" for item in gates)
        status = "blocked" if blockers else "ga_ready_with_warnings" if warnings else "ga_ready"
        summary = (
            f"Provider-track GA is blocked by {blockers} gate(s)."
            if blockers
            else f"Provider-track GA is machine-certified with {warnings} warning(s); human release promotion remains required."
            if warnings
            else "Provider-track GA machine certification passed; human release promotion remains required."
        )
        certification_seed = (
            f"{self.version}|{self.channel}|{self.schema_version}|{commit}|provider-ga-v1"
        )
        certification_id = hashlib.sha256(certification_seed.encode("utf-8")).hexdigest()[:20]
        return ProviderGACertificationSnapshot(
            certification_id=f"provider-ga-{certification_id}",
            generated_at=self._now_iso(),
            version=self.version,
            channel=self.channel,
            schema_version=self.schema_version,
            source_commit=commit,
            status=status,
            summary=summary,
            minimum_test_count=minimum_tests,
            observed_test_count=int(base.observed_test_count),
            builtin_provider_count=len(expected),
            plugin_sdk_api_version=PLUGIN_SDK_API_VERSION,
            danish_pending_count=danish_pending,
            active_plugin_count=len(active_plugins),
            gates=tuple(gates),
            sources=tuple(sources),
        )

    def export_snapshot(self, snapshot: ProviderGACertificationSnapshot) -> Path:
        payload = snapshot.to_dict()
        payload["document_schema_version"] = self.DOCUMENT_SCHEMA_VERSION
        payload["safety_contract"] = self._safety_contract()
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.snapshots_dir / f"{snapshot.certification_id}.json"
        self._write_json(path, payload)
        self._write_json(self.root / "latest-provider-ga-snapshot.json", payload)
        return path

    def create_attestation(self, snapshot: ProviderGACertificationSnapshot) -> dict[str, object]:
        if snapshot.blocker_count:
            return {
                "status": "blocked",
                "detail": "Provider GA attestation cannot be created while blocker gates remain.",
                "path": "",
            }
        snapshot_path = self.export_snapshot(snapshot)
        ok, detail = self.verify_snapshot(snapshot_path)
        if not ok:
            return {"status": "blocked", "detail": detail, "path": ""}
        payload: dict[str, object] = {
            "document_schema_version": self.DOCUMENT_SCHEMA_VERSION,
            "certification_id": snapshot.certification_id,
            "generated_at": self._now_iso(),
            "version": snapshot.version,
            "channel": snapshot.channel,
            "database_schema_version": snapshot.schema_version,
            "source_commit": snapshot.source_commit,
            "status": snapshot.status,
            "machine_certified": True,
            "human_release_promotion_required": True,
            "blocker_count": snapshot.blocker_count,
            "warning_count": snapshot.warning_count,
            "observed_test_count": snapshot.observed_test_count,
            "builtin_provider_count": snapshot.builtin_provider_count,
            "plugin_sdk_api_version": snapshot.plugin_sdk_api_version,
            "snapshot_relative_path": f"snapshots/{snapshot_path.name}",
            "snapshot_sha256": self._sha256(snapshot_path),
            "safety_contract": self._safety_contract(),
        }
        payload["attestation_sha256"] = self._payload_digest(payload)
        path = self.attestations_dir / f"{snapshot.certification_id}.json"
        self._write_json(path, payload)
        self._write_json(self.root / "latest-provider-ga-attestation.json", payload)
        pack_path, receipt_path = self._build_audit_pack(snapshot_path, path)
        ok, detail = self.verify_audit_pack(pack_path, receipt_path)
        if not ok:
            return {"status": "blocked", "detail": detail, "path": ""}
        return {
            "status": snapshot.status,
            "detail": "Provider GA machine attestation and audit pack verified.",
            "path": str(path),
            "snapshot_path": str(snapshot_path),
            "audit_pack_path": str(pack_path),
            "receipt_path": str(receipt_path),
        }

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if payload is None:
            return False, "Provider GA snapshot is missing or invalid JSON."
        digest = str(payload.get("snapshot_sha256") or "")
        source = dict(payload)
        source.pop("snapshot_sha256", None)
        if not digest or digest != self._payload_digest(source):
            return False, "Provider GA snapshot digest mismatch."
        if not self._verify_safety_contract(payload.get("safety_contract", {})):
            return False, "Provider GA snapshot safety contract mismatch."
        if self._contains_private_payload(payload):
            return False, "Provider GA snapshot contains private material."
        for item in payload.get("sources", []):
            if not isinstance(item, dict):
                return False, "Provider GA snapshot source entry is invalid."
            relative = str(item.get("relative_path") or "")
            expected_hash = str(item.get("sha256") or "")
            required = bool(item.get("required", True))
            if not self._safe_relative_path(relative):
                return False, "Provider GA snapshot contains an unsafe source path."
            source_path = self.source_root / relative
            if not source_path.is_file():
                if required:
                    return False, f"Provider GA source custody changed: {relative} is missing."
                continue
            if expected_hash and self._sha256(source_path) != expected_hash:
                return False, f"Provider GA source custody changed: {relative} digest mismatch."
        return True, "Provider GA snapshot verified."

    def verify_attestation(self, path: Path) -> tuple[bool, str]:
        payload = self._read_json(Path(path))
        if payload is None:
            return False, "Provider GA attestation is missing or invalid JSON."
        digest = str(payload.get("attestation_sha256") or "")
        source = dict(payload)
        source.pop("attestation_sha256", None)
        if not digest or digest != self._payload_digest(source):
            return False, "Provider GA attestation digest mismatch."
        if not self._verify_safety_contract(payload.get("safety_contract", {})):
            return False, "Provider GA attestation safety contract mismatch."
        if self._contains_private_payload(payload):
            return False, "Provider GA attestation contains private material."
        relative = str(payload.get("snapshot_relative_path") or "")
        if not self._safe_relative_path(relative):
            return False, "Provider GA attestation snapshot path is unsafe."
        snapshot_path = self.root / relative
        if not snapshot_path.is_file():
            return False, "Provider GA attestation snapshot is missing."
        if self._sha256(snapshot_path) != str(payload.get("snapshot_sha256") or ""):
            return False, "Provider GA attestation snapshot digest mismatch."
        return self.verify_snapshot(snapshot_path)

    def verify_audit_pack(self, pack_path: Path, receipt_path: Path) -> tuple[bool, str]:
        receipt = self._read_json(Path(receipt_path))
        if receipt is None:
            return False, "Provider GA audit receipt is missing or invalid."
        digest = str(receipt.get("receipt_sha256") or "")
        source = dict(receipt)
        source.pop("receipt_sha256", None)
        if not digest or digest != self._payload_digest(source):
            return False, "Provider GA audit receipt digest mismatch."
        if not self._verify_safety_contract(receipt.get("safety_contract", {})):
            return False, "Provider GA audit receipt safety contract mismatch."
        if self._contains_private_payload(receipt):
            return False, "Provider GA audit receipt contains private material."
        pack = Path(pack_path)
        if not pack.is_file() or self._sha256(pack) != str(receipt.get("zip_sha256") or ""):
            return False, "Provider GA audit pack digest mismatch."
        try:
            with zipfile.ZipFile(pack, "r") as archive:
                names = archive.namelist()
                if any(not self._safe_archive_name(name) for name in names):
                    return False, "Provider GA audit pack contains an unsafe archive name."
                expected = set(receipt.get("members", []))
                if set(names) != expected:
                    return False, "Provider GA audit pack member list mismatch."
        except (OSError, zipfile.BadZipFile):
            return False, "Provider GA audit pack is unreadable."
        return True, "Provider GA audit pack verified."

    def _collect_critical_sources(
        self,
        sources: list[ProviderGACertificationSource],
    ) -> tuple[bool, str]:
        missing: list[str] = []
        for relative in self.CRITICAL_SOURCE_PATHS:
            path = self.source_root / relative
            if not path.is_file():
                missing.append(relative)
                continue
            sources.append(
                ProviderGACertificationSource(
                    role="critical_source",
                    label=PurePosixPath(relative).name,
                    relative_path=relative,
                    sha256=self._sha256(path),
                    required=True,
                )
            )
        if missing:
            return False, f"Missing critical provider-track sources: {', '.join(missing)}"
        return True, f"Captured SHA-256 custody for {len(self.CRITICAL_SOURCE_PATHS)} critical provider-track source files."

    def _provider_account_contract(self) -> tuple[bool, str]:
        managed: list[str] = []
        invalid: list[str] = []
        for manifest in DEFAULT_PROVIDER_MANIFESTS:
            if manifest.locality != "cloud":
                continue
            if manifest.requires_credential:
                managed.append(manifest.provider_id)
                if not manifest.profile_management_ready:
                    invalid.append(manifest.provider_id)
        if invalid:
            return False, f"Credentialed cloud providers missing profile management: {', '.join(invalid)}"
        return True, f"All {len(managed)} credentialed cloud providers remain on the managed Provider Accounts surface."

    def _danish_governance_gate(self) -> tuple[ProviderGACertificationGate, int]:
        snapshot = self.danish_provider_benchmark_service.snapshot()
        by_id: Mapping[str, DanishProviderCertification] = {
            item.provider_id: item for item in snapshot.providers
        }
        violations: list[str] = []
        for provider_id in ("deepgram", "kokoro"):
            item = by_id.get(provider_id)
            if item is None or item.status != "not_certified":
                violations.append(f"{provider_id} must remain not_certified for Danish")
        mock = by_id.get("mock")
        if mock is None or mock.status != "not_applicable":
            violations.append("mock must remain not_applicable for Danish certification")
        murf = by_id.get("murf")
        if murf is not None and murf.documentation_state == "not_explicit" and murf.status == "certified":
            violations.append("murf cannot be fully certified while documentation remains not_explicit")
        pending = sum(item.status in {"pending", "conditional"} for item in snapshot.providers)
        if violations:
            return (
                self._gate(
                    "danish_certification_governance",
                    "Danish provider certification governance",
                    "block",
                    "blocker",
                    "; ".join(violations),
                    "Restore Phase 109 Danish certification governance before GA certification.",
                ),
                pending,
            )
        status = "warn" if pending else "pass"
        detail = (
            f"Danish certification guards are valid; {pending} provider route(s) remain pending/conditional human benchmark review."
            if pending
            else "Danish certification guards are valid and no provider route is pending human review."
        )
        return (
            self._gate(
                "danish_certification_governance",
                "Danish provider certification governance",
                status,
                "warning",
                detail,
                "Complete human benchmark evidence for pending Danish routes when production use requires them.",
            ),
            pending,
        )

    @staticmethod
    def _authority_defaults_are_safe() -> bool:
        routing_default = SmartProviderRoutingState.__dataclass_fields__["no_automatic_failover"].default
        recovery_switch = ProviderRecoveryAssessment.__dataclass_fields__["automatic_provider_switch"].default
        recovery_restart = ProviderRecoveryAssessment.__dataclass_fields__["automatic_generation_restart"].default
        receipt_start = ProviderRecoveryReceipt.__dataclass_fields__["generation_started"].default
        return (
            routing_default is True
            and recovery_switch is False
            and recovery_restart is False
            and receipt_start is False
        )

    @staticmethod
    def _manifest_contract_is_safe() -> bool:
        expected_limits = {
            "openai": (4096, "characters"),
            "google": (5000, "bytes"),
            "aws_polly": (3000, "billed_characters"),
            "murf": (3000, "characters"),
        }
        by_id = {item.provider_id: item for item in DEFAULT_PROVIDER_MANIFESTS}
        if tuple(by_id) != ProviderGACertificationService.EXPECTED_BUILTIN_PROVIDER_IDS:
            return False
        for provider_id, (limit, unit) in expected_limits.items():
            manifest = by_id[provider_id]
            if manifest.synthesis_request_limit != limit or manifest.synthesis_request_limit_unit != unit:
                return False
        return all(
            manifest.credential_mode == "none"
            for manifest in DEFAULT_PROVIDER_MANIFESTS
            if manifest.locality == "local"
        )

    def _build_audit_pack(self, snapshot_path: Path, attestation_path: Path) -> tuple[Path, Path]:
        pack_path = self.audit_packs_dir / f"{attestation_path.stem}.zip"
        members = [
            f"snapshots/{snapshot_path.name}",
            f"attestations/{attestation_path.name}",
        ]
        with zipfile.ZipFile(pack_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot_path, members[0])
            archive.write(attestation_path, members[1])
        receipt: dict[str, object] = {
            "document_schema_version": self.DOCUMENT_SCHEMA_VERSION,
            "generated_at": self._now_iso(),
            "zip_filename": pack_path.name,
            "zip_sha256": self._sha256(pack_path),
            "members": members,
            "safety_contract": self._safety_contract(),
        }
        receipt["receipt_sha256"] = self._payload_digest(receipt)
        receipt_path = self.receipts_dir / f"{attestation_path.stem}.json"
        self._write_json(receipt_path, receipt)
        self._write_json(self.root / "latest-provider-ga-receipt.json", receipt)
        return pack_path, receipt_path

    def _resolve_commit(self, source_commit: str) -> str:
        explicit = str(source_commit or "").strip()
        if explicit:
            return explicit
        try:
            result = self._command_runner(
                ["git", "rev-parse", "HEAD"],
                cwd=self.source_root,
                capture_output=True,
                text=True,
                check=False,
            )
        except (OSError, TypeError):
            return ""
        if int(getattr(result, "returncode", 1)) != 0:
            return ""
        return str(getattr(result, "stdout", "") or "").strip()

    @staticmethod
    def _safe_relative_path(value: str) -> bool:
        if not value or "\\" in value:
            return False
        pure = PurePosixPath(value)
        return not pure.is_absolute() and ".." not in pure.parts

    @staticmethod
    def _gate(
        code: str,
        label: str,
        status: str,
        severity: str,
        detail: str,
        action: str = "",
    ) -> ProviderGACertificationGate:
        return ProviderGACertificationGate(code, label, status, severity, detail, action)
