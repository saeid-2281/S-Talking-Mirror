from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.services.intelligent_tts_production_service import (
    IntelligentTTSProductionService,
    ProductionJobLike,
    ProductionManifest,
)


EXECUTION_BINDING_SCHEMA_VERSION = 1


class IntelligentTTSExecutionDrift(RuntimeError):
    """Raised when the launch-approved request changes before execution."""


@dataclass(frozen=True)
class IntelligentTTSExecutionBinding:
    schema_version: int
    manifest_digest: str
    authority_digest: str
    request_ids: tuple[str, ...]
    row_numbers: tuple[int, ...]
    provider: str
    profile_id: str | None
    voice_id: str
    model_id: str
    default_language: str
    output_root: str
    request_count: int
    character_count: int
    review_reasons: tuple[str, ...]
    cross_provider_failover: str = "disabled"
    automatic_execution: str = "disabled"
    language_override_policy: str = "explicit_mapping_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "manifest_digest": self.manifest_digest,
            "authority_digest": self.authority_digest,
            "request_ids": list(self.request_ids),
            "row_numbers": list(self.row_numbers),
            "provider": self.provider,
            "profile_id": self.profile_id,
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "default_language": self.default_language,
            "output_root": self.output_root,
            "request_count": self.request_count,
            "character_count": self.character_count,
            "review_reasons": list(self.review_reasons),
            "cross_provider_failover": self.cross_provider_failover,
            "automatic_execution": self.automatic_execution,
            "language_override_policy": self.language_override_policy,
        }


class IntelligentTTSExecutionService:
    """Bind the B1 manifest to the explicit Generation launch boundary.

    The service is deliberately incapable of starting Generation or selecting a
    provider.  It snapshots the exact queue/settings/output state immediately
    before the existing GenerationController call and can reject drift.  The
    caller retains all Preflight, confirmation, launch and generation authority.
    """

    def __init__(
        self,
        production_service: IntelligentTTSProductionService | None = None,
    ) -> None:
        self.production_service = production_service or IntelligentTTSProductionService()

    def prepare(
        self,
        jobs: Sequence[ProductionJobLike],
        settings: Any,
        output_dir: Path,
        *,
        job_language_overrides: Mapping[int, str] | None = None,
    ) -> IntelligentTTSExecutionBinding:
        manifest = self.production_service.compile_manifest(
            jobs,
            settings,
            Path(output_dir),
            job_language_overrides=job_language_overrides,
        )
        return self._binding_from_manifest(manifest)

    def verify_unchanged(
        self,
        binding: IntelligentTTSExecutionBinding,
        jobs: Sequence[ProductionJobLike],
        settings: Any,
        output_dir: Path,
        *,
        job_language_overrides: Mapping[int, str] | None = None,
    ) -> IntelligentTTSExecutionBinding:
        current = self.prepare(
            jobs,
            settings,
            Path(output_dir),
            job_language_overrides=job_language_overrides,
        )
        changed: list[str] = []
        if current.manifest_digest != binding.manifest_digest:
            changed.append("manifest")
        if current.authority_digest != binding.authority_digest:
            changed.append("authority")
        if current.request_ids != binding.request_ids:
            changed.append("requests")
        if current.row_numbers != binding.row_numbers:
            changed.append("queue_order")
        if current.output_root != binding.output_root:
            changed.append("output_root")
        if changed:
            raise IntelligentTTSExecutionDrift(
                "Intelligent TTS execution context changed: " + ", ".join(changed)
            )
        return current

    @staticmethod
    def _binding_from_manifest(
        manifest: ProductionManifest,
    ) -> IntelligentTTSExecutionBinding:
        return IntelligentTTSExecutionBinding(
            schema_version=EXECUTION_BINDING_SCHEMA_VERSION,
            manifest_digest=manifest.manifest_digest,
            authority_digest=manifest.authority.digest,
            request_ids=tuple(request.request_id for request in manifest.requests),
            row_numbers=tuple(request.row_number for request in manifest.requests),
            provider=manifest.authority.provider,
            profile_id=manifest.authority.profile_id,
            voice_id=manifest.authority.voice_id,
            model_id=manifest.authority.model_id,
            default_language=manifest.authority.default_language,
            output_root=manifest.output_root,
            request_count=len(manifest.requests),
            character_count=sum(request.character_count for request in manifest.requests),
            review_reasons=manifest.review_reasons,
        )
