from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.config.runtime import RuntimeConfig
from app.models.product_ux_audit import (
    ProductUXAuditSnapshot,
    ProductUXBacklogItem,
    ProductUXEvidence,
    ProductUXJourney,
)


@dataclass(frozen=True)
class _EvidenceSpec:
    code: str
    label: str
    relative_path: str
    marker: str
    importance: str
    detail_present: str
    detail_missing: str
    action: str


@dataclass(frozen=True)
class _JourneySpec:
    journey_id: str
    label: str
    stage: str
    evidence: tuple[_EvidenceSpec, ...]


class ProductUXAuditService:
    """Read-only Product UX baseline for Roadmap 2 / Track A.

    Assessment reads reviewed local source only. It performs no network requests,
    provider probes, catalog refreshes, database writes, provider changes, or
    generation actions. Exporting a snapshot is an explicit user action.
    """

    DOCUMENT_SCHEMA_VERSION = 1
    ROADMAP = "S-Talking 1.x Product Experience"
    PHASE = "A1 — Full Product UX Audit & Workflow Baseline"

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        source_root: Path | None = None,
        now: Callable[[], datetime] | None = None,
        command_runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
    ) -> None:
        self.runtime = runtime
        self.source_root = Path(source_root or runtime.app_root)
        self.root = runtime.reports_dir / "product-ux-audit"
        self._now_provider = now or (lambda: datetime.now(timezone.utc))
        self._command_runner = command_runner or subprocess.run

    @classmethod
    def safety_contract(cls) -> dict[str, object]:
        return {
            "read_only_assessment": True,
            "automatic_provider_switch": False,
            "automatic_catalog_refresh": False,
            "automatic_generation_start": False,
            "automatic_generation_restart": False,
            "automatic_cross_provider_failover": False,
            "automatic_database_write": False,
            "automatic_network_probe": False,
            "explicit_snapshot_export_only": True,
        }

    @classmethod
    def journey_specs(cls) -> tuple[_JourneySpec, ...]:
        required = "required"
        opportunity = "opportunity"
        return (
            _JourneySpec(
                "first_run",
                "First run & orientation",
                "Start",
                (
                    _EvidenceSpec("quick_setup", "Quick Setup entry", "app/gui/main.py", "Help: Quick Setup", required, "Quick Setup is discoverable from the command palette.", "Quick Setup is not discoverable from the command palette.", "Expose one obvious first-run setup entry."),
                    _EvidenceSpec("session_continue", "Session continuation", "app/gui/main.py", "ProjectSessionWorkflowDialog", required, "Session/project continuation exists.", "No explicit session continuation surface was found.", "Keep continuation visible before asking users to rebuild context."),
                    _EvidenceSpec("first_run_state", "Persistent first-run state", "app/gui/main.py", "first_run_completed", opportunity, "A persistent first-run completion state exists.", "No explicit persistent first-run completion state is present in MainWindow.", "Add a resumable first-run onboarding state in A2."),
                ),
            ),
            _JourneySpec(
                "provider_setup",
                "Provider setup & account readiness",
                "Configure",
                (
                    _EvidenceSpec("provider_accounts", "Provider Accounts", "app/gui/main.py", "ProviderAccountsDialog", required, "Explicit Provider Accounts management is available.", "Provider Accounts management was not found.", "Restore explicit Provider Accounts management."),
                    _EvidenceSpec("quick_setup_provider", "Setup guidance", "app/gui/dialogs/quick_setup_dialog.py", "provider", required, "Quick Setup contains provider guidance.", "Quick Setup provider guidance is missing.", "Connect onboarding directly to provider readiness."),
                    _EvidenceSpec("setup_wizard", "Guided provider wizard", "app/gui/main.py", "ProviderSetupWizard", opportunity, "A dedicated provider setup wizard exists.", "Provider setup is distributed across existing tools rather than one guided wizard.", "Create a guided Provider Setup Wizard in A3."),
                ),
            ),
            _JourneySpec(
                "voice_discovery",
                "Voice & model discovery",
                "Choose",
                (
                    _EvidenceSpec("voice_browser", "Voice Browser", "app/gui/main.py", "VoiceBrowserDialog", required, "Voice browsing and preview are exposed.", "Voice Browser entry is missing.", "Restore voice browsing and preview."),
                    _EvidenceSpec("unified_catalog", "Unified catalog", "app/gui/main.py", "UnifiedVoiceModelCatalogDialog", required, "Unified Voice & Model Catalog is exposed.", "Unified Voice & Model Catalog entry is missing.", "Restore the unified catalog surface."),
                    _EvidenceSpec("quality_context", "Danish quality context", "app/gui/main.py", "DanishProviderBenchmarkDialog", opportunity, "Danish benchmark evidence is accessible.", "Danish quality evidence is not accessible from the main product surface.", "Bring quality evidence closer to voice selection in A4."),
                ),
            ),
            _JourneySpec(
                "text_preparation",
                "Text/source preparation",
                "Prepare",
                (
                    _EvidenceSpec("text_studio", "Text Studio", "app/gui/main.py", "TextStudioWorkspace", required, "Text Studio is integrated into the workspace.", "Text Studio workspace is missing.", "Restore the text preparation workspace."),
                    _EvidenceSpec("source_review", "Source import review", "app/gui/main.py", "SourceImportReviewDialog", required, "Source imports have an explicit review step.", "Source import review is missing.", "Keep source ingestion reviewable before queue entry."),
                    _EvidenceSpec("guided_next_step", "Guided next step", "app/gui/main.py", "Continue to Queue", opportunity, "Text preparation exposes a direct next-step cue.", "No explicit 'Continue to Queue' handoff marker is present.", "Make the Text Studio → Queue transition explicit in A5."),
                ),
            ),
            _JourneySpec(
                "queue_planning",
                "Queue planning & batch operations",
                "Plan",
                (
                    _EvidenceSpec("queue_workspace", "Queue workspace", "app/gui/main.py", "QueueWorkspace", required, "Queue workspace is integrated.", "Queue workspace is missing.", "Restore the queue workspace."),
                    _EvidenceSpec("batch_ops", "Batch operations", "app/gui/main.py", "QueueBatchOperationsWidget", required, "Batch operations are available.", "Batch operations are missing.", "Restore batch planning tools."),
                    _EvidenceSpec("queue_guidance", "Queue guidance", "app/gui/main.py", "queueEmptyState", opportunity, "Queue has a dedicated empty-state guidance marker.", "No dedicated queue empty-state guidance marker is visible in MainWindow source.", "Reduce first-use queue ambiguity in A5."),
                ),
            ),
            _JourneySpec(
                "preflight_approval",
                "Preflight & generation approval",
                "Approve",
                (
                    _EvidenceSpec("preflight", "Preflight", "app/gui/main.py", "PreflightDialog", required, "Preflight is a visible generation gate.", "Preflight UI gate is missing.", "Restore Preflight as the validation authority."),
                    _EvidenceSpec("launch_approval", "Launch approval", "app/gui/main.py", "GenerationLaunchDialog", required, "Generation launch requires an explicit review dialog.", "Explicit launch approval is missing.", "Restore explicit user launch approval."),
                    _EvidenceSpec("budget_guard", "Budget guard", "app/gui/main.py", "GenerationBudgetGuardDialog", opportunity, "Budget/cost guard is connected to generation approval.", "Budget guard is not visible in the launch flow.", "Keep cost implications legible at approval time."),
                ),
            ),
            _JourneySpec(
                "live_generation",
                "Live generation & progress",
                "Generate",
                (
                    _EvidenceSpec("live_ops", "Live operations", "app/gui/main.py", "GenerationLiveOperationsWidget", required, "Live generation operations are integrated.", "Live generation operations are missing.", "Restore live generation visibility."),
                    _EvidenceSpec("monitor", "Generation monitor", "app/gui/main.py", "Show/Hide Generation Monitor", required, "Generation Monitor is directly controllable.", "Generation Monitor control is missing.", "Keep live status visible and controllable."),
                    _EvidenceSpec("attention_handoff", "Attention handoff", "app/gui/main.py", "needs attention", opportunity, "Live flow contains an explicit attention handoff marker.", "No explicit user-facing 'needs attention' marker is present in MainWindow source.", "Consolidate actionable live errors in A6."),
                ),
            ),
            _JourneySpec(
                "recovery_resume",
                "Failure recovery & resume",
                "Recover",
                (
                    _EvidenceSpec("safe_resume", "Safe resume", "app/gui/main.py", "GenerationSafeResumeDialog", required, "Generation safe-resume is exposed.", "Safe-resume UI is missing.", "Restore safe resume."),
                    _EvidenceSpec("provider_recovery", "Multi-provider recovery", "app/gui/main.py", "UserControlledProviderRecoveryDialog", required, "User-controlled provider recovery is exposed.", "User-controlled provider recovery is missing.", "Preserve explicit recovery authority."),
                    _EvidenceSpec("recovery_center", "Unified recovery entry", "app/gui/main.py", "Recovery Center", opportunity, "A single Recovery Center entry exists.", "Recovery tools remain distributed across multiple surfaces.", "Unify failure/recovery UX in A6 without adding automatic failover."),
                ),
            ),
            _JourneySpec(
                "audio_review_export",
                "Audio review & export",
                "Finish",
                (
                    _EvidenceSpec("audio_player", "Audio playback", "app/gui/main.py", "audio_player_service", required, "Audio playback service is integrated.", "Audio playback integration is missing.", "Restore playback before export."),
                    _EvidenceSpec("output_folder", "Output access", "app/gui/main.py", "Open Output Folder", required, "Output folder access is exposed.", "Output folder access is missing.", "Keep finished artifacts easy to locate."),
                    _EvidenceSpec("review_handoff", "Review-to-export handoff", "app/gui/main.py", "Audio Review & Export", opportunity, "Audio review/export is represented as one user-facing concept.", "No direct 'Audio Review & Export' main-window marker is present.", "Tighten review/export handoff in a later Product Experience phase."),
                ),
            ),
            _JourneySpec(
                "settings_accessibility",
                "Settings, help & accessibility",
                "Support",
                (
                    _EvidenceSpec("preferences", "Interface preferences", "app/gui/main.py", "InterfacePreferencesDialog", required, "Interface Preferences are available.", "Interface Preferences are missing.", "Restore user-facing interface preferences."),
                    _EvidenceSpec("shortcuts", "Shortcut reference", "app/gui/main.py", "Shortcut Reference", required, "Shortcut Reference is available.", "Shortcut Reference is missing.", "Keep keyboard help discoverable."),
                    _EvidenceSpec("context_help", "Contextual help", "app/gui/main.py", "What's this?", opportunity, "Context-sensitive help markers exist.", "No contextual 'What's this?' help marker is present.", "Add contextual help progressively after A2/A3."),
                ),
            ),
        )

    def assess(self, *, source_commit: str = "") -> ProductUXAuditSnapshot:
        commit = str(source_commit or "").strip() or self._resolve_commit()
        journeys = tuple(self._assess_journey(spec) for spec in self.journey_specs())
        overall_score = round(sum(item.score for item in journeys) / max(1, len(journeys)))
        blocker_count = sum(item.required_gap_count for item in journeys)
        opportunity_count = sum(item.opportunity_count for item in journeys)
        if blocker_count:
            status = "structural_gaps"
        elif overall_score >= 90:
            status = "strong_baseline"
        elif overall_score >= 75:
            status = "baseline_ready"
        else:
            status = "friction_risk"
        backlog = self._build_backlog(journeys)
        summary = (
            f"{len(journeys)} core journeys audited; score {overall_score}/100; "
            f"{blocker_count} structural gap(s) and {opportunity_count} product-experience opportunity item(s)."
        )
        seed = f"{commit}|{overall_score}|{blocker_count}|{opportunity_count}|roadmap2-a1-v1"
        audit_id = "product-ux-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:20]
        return ProductUXAuditSnapshot(
            audit_id=audit_id,
            generated_at=self._now_iso(),
            source_commit=commit,
            roadmap=self.ROADMAP,
            phase=self.PHASE,
            overall_score=overall_score,
            status=status,
            summary=summary,
            journeys=journeys,
            backlog=backlog,
        )

    def export_snapshot(self, snapshot: ProductUXAuditSnapshot) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = snapshot.to_dict()
        payload["document_schema_version"] = self.DOCUMENT_SCHEMA_VERSION
        payload["safety_contract"] = self.safety_contract()
        payload["snapshot_sha256"] = self._payload_digest(payload)
        path = self.root / f"{snapshot.audit_id}.json"
        self._write_json(path, payload)
        self._write_json(self.root / "latest-product-ux-audit.json", payload)
        return path

    def verify_snapshot(self, path: Path) -> tuple[bool, str]:
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            return False, f"Unable to read Product UX audit snapshot: {exc}"
        expected = str(payload.pop("snapshot_sha256", ""))
        if not expected:
            return False, "Product UX audit snapshot digest is missing."
        actual = self._payload_digest(payload)
        if actual != expected:
            return False, "Product UX audit snapshot digest mismatch."
        if payload.get("safety_contract") != self.safety_contract():
            return False, "Product UX audit safety contract mismatch."
        return True, "Product UX audit snapshot verified."

    def _assess_journey(self, spec: _JourneySpec) -> ProductUXJourney:
        evidence: list[ProductUXEvidence] = []
        present_count = 0
        weighted_total = 0
        weighted_present = 0
        for item in spec.evidence:
            present = self._marker_present(item.relative_path, item.marker)
            weight = 2 if item.importance == "required" else 1
            weighted_total += weight
            if present:
                present_count += 1
                weighted_present += weight
            evidence.append(
                ProductUXEvidence(
                    code=item.code,
                    label=item.label,
                    status="present" if present else "missing",
                    importance=item.importance,
                    relative_path=item.relative_path,
                    detail=item.detail_present if present else item.detail_missing,
                    action="" if present else item.action,
                )
            )
        score = round((weighted_present / max(1, weighted_total)) * 100)
        required_missing = sum(
            item.status == "missing" and item.importance == "required" for item in evidence
        )
        opportunity_missing = sum(
            item.status == "missing" and item.importance == "opportunity" for item in evidence
        )
        if required_missing:
            status = "structural_gap"
        elif score >= 90:
            status = "ready"
        elif score >= 70:
            status = "needs_attention"
        else:
            status = "friction_risk"
        summary = (
            f"{present_count}/{len(evidence)} evidence signals present; "
            f"{required_missing} required gap(s), {opportunity_missing} opportunity item(s)."
        )
        return ProductUXJourney(
            journey_id=spec.journey_id,
            label=spec.label,
            stage=spec.stage,
            score=score,
            status=status,
            summary=summary,
            evidence=tuple(evidence),
        )

    @staticmethod
    def _build_backlog(journeys: tuple[ProductUXJourney, ...]) -> tuple[ProductUXBacklogItem, ...]:
        candidates: list[tuple[int, int, ProductUXBacklogItem]] = []
        order = 0
        for journey in journeys:
            for evidence in journey.evidence:
                if evidence.status != "missing":
                    continue
                priority = 1 if evidence.importance == "required" else 2
                candidates.append(
                    (
                        priority,
                        order,
                        ProductUXBacklogItem(
                            priority=priority,
                            journey_id=journey.journey_id,
                            journey_label=journey.label,
                            evidence_code=evidence.code,
                            title=evidence.label,
                            rationale=evidence.detail,
                            action=evidence.action,
                        ),
                    )
                )
                order += 1
        candidates.sort(key=lambda item: (item[0], item[1]))
        return tuple(item[2] for item in candidates)

    def _marker_present(self, relative_path: str, marker: str) -> bool:
        path = self.source_root / relative_path
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return False
        return marker in text

    def _resolve_commit(self) -> str:
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

    def _now_iso(self) -> str:
        value = self._now_provider()
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def _payload_digest(payload: dict[str, object]) -> str:
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _write_json(path: Path, payload: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
