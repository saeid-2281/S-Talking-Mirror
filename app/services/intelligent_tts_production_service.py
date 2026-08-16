from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence


MANIFEST_SCHEMA_VERSION = 1
SHORT_UTTERANCE_REVIEW_CHARS = 20
LARGE_TEXT_REVIEW_CHARS = 5_000


class ProductionJobLike(Protocol):
    row_number: int
    filename: str
    text: str


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _optional_text(value: Any) -> str | None:
    normalized = _text(value).strip()
    return normalized or None


def _nonnegative_int(value: Any, default: int = 0) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return default


def _canonical_json(payload: Mapping[str, Any]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProductionAuthoritySnapshot:
    provider: str
    profile_id: str | None
    voice_id: str
    model_id: str
    default_language: str
    generation_scope: str | None
    execution_order: str | None
    max_retries: int
    cross_provider_failover: str = "disabled"
    automatic_selection: str = "disabled"

    @classmethod
    def from_settings(cls, settings: Any) -> "ProductionAuthoritySnapshot":
        return cls(
            provider=_text(getattr(settings, "provider", "")).strip(),
            profile_id=_optional_text(
                getattr(settings, "active_api_profile_id", None)
            ),
            voice_id=_text(getattr(settings, "voice_id", "")).strip(),
            model_id=_text(getattr(settings, "model_id", "")).strip(),
            default_language=_text(
                getattr(settings, "language_code", "")
            ).strip(),
            generation_scope=_optional_text(
                getattr(settings, "generation_scope", None)
            ),
            execution_order=_optional_text(
                getattr(settings, "execution_order", None)
            ),
            max_retries=_nonnegative_int(
                getattr(settings, "max_retries", 0)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "profile_id": self.profile_id,
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "default_language": self.default_language,
            "generation_scope": self.generation_scope,
            "execution_order": self.execution_order,
            "max_retries": self.max_retries,
            "cross_provider_failover": self.cross_provider_failover,
            "automatic_selection": self.automatic_selection,
        }

    @property
    def digest(self) -> str:
        return _digest(self.to_dict())


@dataclass(frozen=True)
class ProductionRequest:
    ordinal: int
    row_number: int
    filename: str
    text: str = field(repr=False, compare=False)
    text_sha256: str = ""
    character_count: int = 0
    output_path: str = ""
    configured_extension: str | None = None
    provider: str = ""
    profile_id: str | None = None
    voice_id: str = ""
    model_id: str = ""
    language_code: str = ""
    language_source: str = "settings"
    same_provider_retry_limit: int = 0
    cross_provider_failover: str = "disabled"
    request_signature: str = ""
    request_id: str = ""
    review_reasons: tuple[str, ...] = ()

    @property
    def requires_review(self) -> bool:
        return bool(self.review_reasons)

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ordinal": self.ordinal,
            "row_number": self.row_number,
            "filename": self.filename,
            "text_sha256": self.text_sha256,
            "character_count": self.character_count,
            "output_path": self.output_path,
            "configured_extension": self.configured_extension,
            "provider": self.provider,
            "profile_id": self.profile_id,
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "language_code": self.language_code,
            "language_source": self.language_source,
            "same_provider_retry_limit": self.same_provider_retry_limit,
            "cross_provider_failover": self.cross_provider_failover,
            "request_signature": self.request_signature,
            "request_id": self.request_id,
            "requires_review": self.requires_review,
            "review_reasons": list(self.review_reasons),
        }
        if include_text:
            payload["text"] = self.text
        return payload


@dataclass(frozen=True)
class ProductionBatch:
    batch_index: int
    start_ordinal: int
    end_ordinal: int
    row_numbers: tuple[int, ...]
    request_signature: str
    provider: str
    profile_id: str | None
    voice_id: str
    model_id: str
    language_code: str
    request_count: int
    character_count: int
    policy: str = "observational_contiguous_group_only"

    def to_dict(self) -> dict[str, Any]:
        return {
            "batch_index": self.batch_index,
            "start_ordinal": self.start_ordinal,
            "end_ordinal": self.end_ordinal,
            "row_numbers": list(self.row_numbers),
            "request_signature": self.request_signature,
            "provider": self.provider,
            "profile_id": self.profile_id,
            "voice_id": self.voice_id,
            "model_id": self.model_id,
            "language_code": self.language_code,
            "request_count": self.request_count,
            "character_count": self.character_count,
            "policy": self.policy,
        }


@dataclass(frozen=True)
class ProductionManifest:
    schema_version: int
    output_root: str
    authority: ProductionAuthoritySnapshot
    requests: tuple[ProductionRequest, ...]
    batches: tuple[ProductionBatch, ...]
    review_reasons: tuple[str, ...]
    manifest_digest: str

    @property
    def requires_review(self) -> bool:
        return bool(self.review_reasons)

    def to_dict(self, *, include_text: bool = False) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "output_root": self.output_root,
            "authority": self.authority.to_dict(),
            "authority_digest": self.authority.digest,
            "requests": [
                request.to_dict(include_text=include_text)
                for request in self.requests
            ],
            "batches": [batch.to_dict() for batch in self.batches],
            "requires_review": self.requires_review,
            "review_reasons": list(self.review_reasons),
            "manifest_digest": self.manifest_digest,
        }

    def to_json(self, *, include_text: bool = False) -> str:
        return json.dumps(
            self.to_dict(include_text=include_text),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )


class IntelligentTTSProductionService:
    """Compile immutable, authority-preserving TTS production manifests.

    B1 is deliberately advisory/planning-only. This service never creates a
    provider, runs Preflight, starts generation, applies Smart Routing, detects
    language from text, rewrites queue order, or mutates jobs/settings.
    """

    def compile_manifest(
        self,
        jobs: Sequence[ProductionJobLike],
        settings: Any,
        output_dir: Path,
        *,
        job_language_overrides: Mapping[int, str] | None = None,
    ) -> ProductionManifest:
        authority = ProductionAuthoritySnapshot.from_settings(settings)
        output_root = Path(output_dir)
        overrides = {
            int(row_number): _text(language).strip()
            for row_number, language in (job_language_overrides or {}).items()
            if _text(language).strip()
        }
        configured_extension = _optional_text(
            getattr(settings, "file_extension", None)
        )
        if configured_extension and not configured_extension.startswith("."):
            configured_extension = f".{configured_extension}"

        seen_outputs: dict[str, int] = {}
        requests: list[ProductionRequest] = []

        for ordinal, job in enumerate(jobs, start=1):
            row_number = _nonnegative_int(
                getattr(job, "row_number", ordinal),
                default=ordinal,
            )
            filename = _text(getattr(job, "filename", ""))
            text = _text(getattr(job, "text", ""))
            language_override = overrides.get(row_number)
            language = language_override or authority.default_language
            language_source = (
                "explicit_job_override"
                if language_override is not None
                else "settings"
            )
            reasons: list[str] = []

            if not authority.provider:
                reasons.append("missing_provider")
            if not authority.voice_id:
                reasons.append("missing_voice")
            if not authority.model_id:
                reasons.append("missing_model")
            if not language:
                reasons.append("missing_language")
            if not text.strip():
                reasons.append("empty_text")
            elif len(text) <= SHORT_UTTERANCE_REVIEW_CHARS:
                reasons.append("short_utterance")
            if len(text) > LARGE_TEXT_REVIEW_CHARS:
                reasons.append("large_text_review")

            filename_path = Path(filename)
            unsafe_filename = (
                not filename
                or filename_path.is_absolute()
                or filename_path.name != filename
                or filename in {".", ".."}
            )
            if unsafe_filename:
                reasons.append("unsafe_filename")

            output_path = output_root / filename
            collision_key = str(output_path).replace("\\", "/").casefold()
            previous_row = seen_outputs.get(collision_key)
            if previous_row is not None:
                reasons.append(f"duplicate_output_with_row:{previous_row}")
            else:
                seen_outputs[collision_key] = row_number

            signature_payload = {
                "provider": authority.provider,
                "profile_id": authority.profile_id,
                "voice_id": authority.voice_id,
                "model_id": authority.model_id,
                "language_code": language,
                "configured_extension": configured_extension,
                "same_provider_retry_limit": authority.max_retries,
                "cross_provider_failover": "disabled",
            }
            request_signature = _digest(signature_payload)
            text_sha256 = hashlib.sha256(text.encode("utf-8")).hexdigest()
            request_id = _digest(
                {
                    "ordinal": ordinal,
                    "row_number": row_number,
                    "filename": filename,
                    "text_sha256": text_sha256,
                    "request_signature": request_signature,
                }
            )

            requests.append(
                ProductionRequest(
                    ordinal=ordinal,
                    row_number=row_number,
                    filename=filename,
                    text=text,
                    text_sha256=text_sha256,
                    character_count=len(text),
                    output_path=str(output_path),
                    configured_extension=configured_extension,
                    provider=authority.provider,
                    profile_id=authority.profile_id,
                    voice_id=authority.voice_id,
                    model_id=authority.model_id,
                    language_code=language,
                    language_source=language_source,
                    same_provider_retry_limit=authority.max_retries,
                    cross_provider_failover="disabled",
                    request_signature=request_signature,
                    request_id=request_id,
                    review_reasons=tuple(reasons),
                )
            )

        batches = self._compile_observational_batches(requests)
        review_reasons = tuple(
            sorted(
                {
                    reason
                    for request in requests
                    for reason in request.review_reasons
                }
            )
        )
        digest_payload = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "output_root": str(output_root),
            "authority": authority.to_dict(),
            "requests": [
                request.to_dict(include_text=False)
                for request in requests
            ],
            "batches": [batch.to_dict() for batch in batches],
            "review_reasons": list(review_reasons),
        }
        return ProductionManifest(
            schema_version=MANIFEST_SCHEMA_VERSION,
            output_root=str(output_root),
            authority=authority,
            requests=tuple(requests),
            batches=tuple(batches),
            review_reasons=review_reasons,
            manifest_digest=_digest(digest_payload),
        )

    @staticmethod
    def _compile_observational_batches(
        requests: Sequence[ProductionRequest],
    ) -> list[ProductionBatch]:
        if not requests:
            return []

        groups: list[list[ProductionRequest]] = []
        current: list[ProductionRequest] = [requests[0]]
        for request in requests[1:]:
            if request.request_signature == current[-1].request_signature:
                current.append(request)
            else:
                groups.append(current)
                current = [request]
        groups.append(current)

        batches: list[ProductionBatch] = []
        for index, group in enumerate(groups, start=1):
            first = group[0]
            batches.append(
                ProductionBatch(
                    batch_index=index,
                    start_ordinal=first.ordinal,
                    end_ordinal=group[-1].ordinal,
                    row_numbers=tuple(item.row_number for item in group),
                    request_signature=first.request_signature,
                    provider=first.provider,
                    profile_id=first.profile_id,
                    voice_id=first.voice_id,
                    model_id=first.model_id,
                    language_code=first.language_code,
                    request_count=len(group),
                    character_count=sum(
                        item.character_count for item in group
                    ),
                )
            )
        return batches
