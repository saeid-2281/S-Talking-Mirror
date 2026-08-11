from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.models.domain import AppSettings, JobStatus, TTSJob
from app.models.provider_recovery import (
    ProviderRecoveryAssessment,
    ProviderRecoveryCandidate,
    ProviderRecoveryReceipt,
)
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.smart_provider_routing_service import SmartProviderRoutingService


class UserControlledProviderRecoveryService:
    """Plan cross-provider recovery without changing settings, jobs, or generation state.

    Phase 110 is deliberately review-only until the caller records explicit user
    approval. Assessment consumes only cached/configured routing evidence; it
    does not refresh catalogs, test provider connections, synthesize audio, switch a
    provider, reset failed jobs, or restart generation.
    """

    VERSION = 1

    def __init__(
        self,
        reports_dir: Path,
        smart_routing: SmartProviderRoutingService,
        providers: ProviderCatalogService,
    ) -> None:
        self.reports_dir = Path(reports_dir) / "provider-recovery"
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.smart_routing = smart_routing
        self.providers = providers

    def assess(
        self,
        *,
        settings: AppSettings,
        jobs: list[TTSJob],
        project_id: int | None,
        failure_message: str = "",
        current_profile=None,
        connection_status: str = "",
    ) -> ProviderRecoveryAssessment:
        failed = tuple(job for job in jobs if job.status == JobStatus.FAILED)
        pending = tuple(job for job in jobs if job.status == JobStatus.PENDING)
        scoped = (*failed, *pending)
        characters = sum(len(job.text) for job in scoped)
        largest_characters = max((len(job.text) for job in scoped), default=0)
        largest_bytes = max((len(job.text.encode("utf-8")) for job in scoped), default=0)
        current_provider = str(settings.provider or "mock").strip().casefold()
        current_name = self.providers.manifest_for(current_provider).display_name
        failure_summary = self._safe_text(failure_message)
        routing = self.smart_routing.analyze(
            settings=settings,
            scoped_jobs=len(scoped),
            scoped_characters=characters,
            project_id=project_id,
            current_profile=current_profile,
            connection_status=connection_status or failure_summary,
            preference="reliability",
            generation_active=False,
            largest_job_characters=largest_characters,
            largest_job_bytes=largest_bytes,
        )
        candidates: list[ProviderRecoveryCandidate] = []
        for route in routing.candidates:
            if route.provider_id in {current_provider, "mock"}:
                continue
            action_kind = (
                "offline_voice_review"
                if route.provider_id == "piper"
                else "catalog_review"
            )
            candidates.append(
                ProviderRecoveryCandidate(
                    provider_id=route.provider_id,
                    provider_name=route.provider_name,
                    rank=route.rank,
                    score=route.score,
                    ready=route.ready,
                    eligible=route.eligible,
                    locality=route.locality,
                    status=route.status,
                    detail=route.detail,
                    action_kind=action_kind,
                    profile_id=route.profile_id,
                    profile_name=route.profile_name,
                    recommended_voice_id=route.recommended_voice_id,
                    recommended_model_id=route.recommended_model_id,
                    language_state=route.language_state,
                    voice_state=route.voice_state,
                    model_state=route.model_state,
                    account_state=route.account_state,
                    request_limit_state=route.request_limit_state,
                    blockers=tuple(route.blockers),
                    warnings=tuple(route.warnings),
                )
            )
        candidates.sort(
            key=lambda item: (not item.actionable, item.rank, -item.score, item.provider_id)
        )
        recommended = next((item.provider_id for item in candidates if item.actionable), None)
        now = datetime.now(timezone.utc).isoformat()
        assessment_id = hashlib.sha256(
            json.dumps(
                {
                    "provider": current_provider,
                    "failed_rows": [job.row_number for job in failed],
                    "pending_rows": [job.row_number for job in pending],
                    "characters": characters,
                    "failure": failure_summary,
                    "created_at": now,
                },
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:24]
        return ProviderRecoveryAssessment(
            assessment_id=assessment_id,
            current_provider_id=current_provider,
            current_provider_name=current_name,
            failure_summary=failure_summary,
            failed_rows=tuple(job.row_number for job in failed),
            pending_rows=tuple(job.row_number for job in pending),
            scoped_jobs=len(scoped),
            scoped_characters=characters,
            recommended_provider_id=recommended,
            candidates=tuple(candidates),
            created_at=now,
        )

    def prepare_receipt(
        self,
        assessment: ProviderRecoveryAssessment,
        *,
        selected_settings: AppSettings,
        approved: bool,
    ) -> ProviderRecoveryReceipt:
        if not approved:
            raise ValueError(
                "Explicit user approval is required before preparing cross-provider recovery."
            )
        target = str(selected_settings.provider or "").strip().casefold()
        if not target or target == assessment.current_provider_id:
            raise ValueError(
                "Cross-provider recovery requires an explicitly selected alternate provider."
            )
        candidate = assessment.candidate_for(target)
        if candidate is None:
            raise ValueError(
                "Selected provider was not part of the reviewed recovery assessment."
            )
        if not candidate.actionable:
            raise ValueError("Selected recovery provider is blocked or not ready for this scope.")
        if target == "piper" and not str(selected_settings.piper_model_path or "").strip():
            raise ValueError("Piper recovery requires an explicitly selected local voice pack.")
        payload: dict[str, object] = {
            "version": self.VERSION,
            "receipt_id": uuid.uuid4().hex,
            "assessment_id": assessment.assessment_id,
            "from_provider_id": assessment.current_provider_id,
            "to_provider_id": target,
            "profile_id": selected_settings.active_api_profile_id,
            "voice_id": str(selected_settings.voice_id or ""),
            "model_id": str(selected_settings.model_id or ""),
            "language_code": selected_settings.language_code,
            "failed_rows": list(assessment.failed_rows),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "prepared",
            "user_approved": True,
            "generation_started": False,
            "policy": {
                "automatic_provider_switch": False,
                "automatic_generation_restart": False,
                "preflight_required": True,
                "explicit_start_required": True,
            },
            "metadata": {
                "candidate_rank": candidate.rank,
                "candidate_score": candidate.score,
                "action_kind": candidate.action_kind,
                "profile_name": candidate.profile_name,
                "piper_voice_pack": (
                    Path(selected_settings.piper_model_path).name
                    if selected_settings.piper_model_path
                    else None
                ),
            },
        }
        payload["checksum"] = self._checksum(payload)
        path = self.reports_dir / f"provider-recovery-{payload['receipt_id']}.json"
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
        return ProviderRecoveryReceipt(
            receipt_id=str(payload["receipt_id"]),
            assessment_id=assessment.assessment_id,
            from_provider_id=assessment.current_provider_id,
            to_provider_id=target,
            profile_id=selected_settings.active_api_profile_id,
            voice_id=str(selected_settings.voice_id or ""),
            model_id=str(selected_settings.model_id or ""),
            language_code=selected_settings.language_code,
            failed_rows=assessment.failed_rows,
            created_at=str(payload["created_at"]),
            checksum=str(payload["checksum"]),
            path=str(path),
            metadata=dict(payload["metadata"]),
        )

    def verify_receipt(self, receipt: ProviderRecoveryReceipt | Path | str) -> bool:
        path = Path(receipt.path) if isinstance(receipt, ProviderRecoveryReceipt) else Path(receipt)
        if not path.is_file():
            return False
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        return bool(
            isinstance(payload, dict)
            and payload.get("version") == self.VERSION
            and payload.get("checksum")
            and str(payload.get("checksum")) == self._checksum(payload)
            and payload.get("user_approved") is True
            and payload.get("generation_started") is False
        )

    @staticmethod
    def _checksum(payload: dict[str, object]) -> str:
        clean = {key: value for key, value in payload.items() if key != "checksum"}
        canonical = json.dumps(
            clean,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @staticmethod
    def _safe_text(value: str) -> str:
        text = " ".join(str(value or "").split())[:500]
        text = re.sub(
            r"(?i)bearer\s+[A-Za-z0-9._~+/-]+", "Bearer [REDACTED]", text
        )
        text = re.sub(
            r"(?i)(api[_ -]?key|token|secret)\s*[:=]\s*\S+",
            r"\1=[REDACTED]",
            text,
        )
        return text
