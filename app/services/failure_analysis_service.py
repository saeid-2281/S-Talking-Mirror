from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from app.exceptions import ProviderError
from app.models.domain import JobStatus, TTSJob
from app.models.retry_policy import (
    FailureAnalysis,
    FailureCategory,
    RetryBatchResult,
    RetryDecision,
    RetryHistoryEntry,
)


_TRANSIENT_CATEGORIES = {
    FailureCategory.NETWORK,
    FailureCategory.RATE_LIMIT,
    FailureCategory.SERVER,
}


class FailureAnalysisService:
    """Normalize provider failures into stable categories and fingerprints."""

    def analyze(self, error: Exception | str | None) -> FailureAnalysis:
        message = self._message(error)
        lower = message.casefold()
        code = self._code(error, lower)
        status = error.http_status if isinstance(error, ProviderError) else self._http_status(lower)
        category = self._category(code, status, lower, error)
        retryable = self._retryable(category, status, error, lower)
        permanent = not retryable and category != FailureCategory.CANCELLED
        fingerprint = self._fingerprint(category, code, message)
        return FailureAnalysis(
            category=category,
            error_code=code,
            fingerprint=fingerprint,
            retryable=retryable,
            permanent=permanent,
            message=message,
        )

    @staticmethod
    def apply(job: TTSJob, analysis: FailureAnalysis, *, attempt: int, max_retries: int) -> None:
        job.failure_category = analysis.category
        job.error_code = analysis.error_code
        job.error_fingerprint = analysis.fingerprint
        job.retryable = analysis.retryable
        job.retry_exhausted = max_retries >= 0 and attempt >= max_retries
        job.next_retry_at = None
        job.retry_history.append(
            RetryHistoryEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                event="failed",
                attempt=attempt,
                category=analysis.category,
                error_code=analysis.error_code,
                fingerprint=analysis.fingerprint,
                retryable=analysis.retryable,
                message=analysis.message[:500],
            )
        )

    @staticmethod
    def summary(jobs: Iterable[TTSJob]) -> dict[str, object]:
        failed = [job for job in jobs if job.status == JobStatus.FAILED]
        category_counts = Counter((job.failure_category or FailureCategory.UNKNOWN).value for job in failed)
        fingerprint_counts = Counter(job.error_fingerprint or "unclassified" for job in failed)
        return {
            "failed": len(failed),
            "retryable": sum(bool(job.retryable) and not job.retry_exhausted for job in failed),
            "permanent": sum(job.retryable is False for job in failed),
            "exhausted": sum(bool(job.retry_exhausted) for job in failed),
            "categories": dict(sorted(category_counts.items())),
            "fingerprints": dict(fingerprint_counts.most_common()),
        }

    @staticmethod
    def export_report(jobs: Iterable[TTSJob], directory: Path, *, project_name: str = "project") -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_project = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "project"
        json_path = directory / f"failure-report-{safe_project}-{stamp}.json"
        csv_path = directory / f"failure-report-{safe_project}-{stamp}.csv"
        failed = [job for job in jobs if job.status == JobStatus.FAILED]
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project": project_name,
            "summary": FailureAnalysisService.summary(failed),
            "jobs": [
                {
                    "row_number": job.row_number,
                    "filename": job.filename,
                    "category": (job.failure_category or FailureCategory.UNKNOWN).value,
                    "error_code": job.error_code,
                    "fingerprint": job.error_fingerprint,
                    "retryable": job.retryable,
                    "retry_exhausted": job.retry_exhausted,
                    "retry_count": job.retry_count,
                    "next_retry_at": job.next_retry_at,
                    "error": job.error,
                    "retry_history": [entry.model_dump(mode="json") for entry in job.retry_history],
                }
                for job in failed
            ],
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=[
                    "row_number",
                    "filename",
                    "category",
                    "error_code",
                    "fingerprint",
                    "retryable",
                    "retry_exhausted",
                    "retry_count",
                    "next_retry_at",
                    "error",
                ],
            )
            writer.writeheader()
            for job in failed:
                writer.writerow(
                    {
                        "row_number": job.row_number,
                        "filename": job.filename,
                        "category": (job.failure_category or FailureCategory.UNKNOWN).value,
                        "error_code": job.error_code or "",
                        "fingerprint": job.error_fingerprint or "",
                        "retryable": bool(job.retryable),
                        "retry_exhausted": bool(job.retry_exhausted),
                        "retry_count": job.retry_count,
                        "next_retry_at": job.next_retry_at or "",
                        "error": job.error or "",
                    }
                )
        return json_path, csv_path

    @staticmethod
    def _message(error: Exception | str | None) -> str:
        if error is None:
            return "Unknown generation failure."
        if isinstance(error, ProviderError):
            return error.user_message or str(error)
        return str(error) or "Unknown generation failure."

    @staticmethod
    def _code(error: Exception | str | None, lower: str) -> str:
        if isinstance(error, ProviderError) and error.provider_code:
            return str(error.provider_code).strip().lower()
        match = re.search(r"\bcode[=: ]+([a-z0-9_.-]+)", lower)
        if match:
            return match.group(1)
        if isinstance(error, TimeoutError):
            return "timeout"
        if isinstance(error, OSError):
            return "os_error"
        return "unknown"

    @staticmethod
    def _http_status(lower: str) -> int | None:
        match = re.search(r"\bstatus[=: ]+(\d{3})\b", lower)
        return int(match.group(1)) if match else None

    @staticmethod
    def _category(code: str, status: int | None, lower: str, error: Exception | str | None) -> FailureCategory:
        if code == "cancelled" or "cancelled by user" in lower:
            return FailureCategory.CANCELLED
        if status in {401, 403} or any(token in code for token in ("auth", "api_key", "permission")):
            return FailureCategory.AUTHENTICATION
        if status == 429 or any(token in code for token in ("rate", "throttl")) or "rate limit" in lower:
            return FailureCategory.RATE_LIMIT
        if status in {500, 502, 503, 504} or any(token in code for token in ("server", "unavailable", "empty_audio")):
            return FailureCategory.SERVER
        if status in {402} or any(token in code for token in ("quota", "credit", "billing")) or any(
            token in lower for token in ("quota exceeded", "insufficient credit", "billing")
        ):
            return FailureCategory.QUOTA
        if status in {400, 404, 409, 413, 415, 422} or any(
            token in code for token in ("invalid", "unsupported", "too_large", "validation")
        ):
            return FailureCategory.VALIDATION
        if isinstance(error, (ConnectionError, TimeoutError)) or any(
            token in lower for token in ("timeout", "timed out", "network", "connection reset", "temporarily unavailable")
        ):
            return FailureCategory.NETWORK
        if isinstance(error, OSError) or any(token in lower for token in ("permission denied", "disk full", "no space left", "read-only file")):
            return FailureCategory.FILESYSTEM
        return FailureCategory.UNKNOWN

    @staticmethod
    def _retryable(
        category: FailureCategory,
        status: int | None,
        error: Exception | str | None,
        lower: str,
    ) -> bool:
        if isinstance(error, ProviderError):
            return bool(error.retryable)
        if category in _TRANSIENT_CATEGORIES:
            return True
        if status in {408, 425, 429, 500, 502, 503, 504}:
            return True
        return any(token in lower for token in ("retryable=true", "temporarily", "try again", "timeout"))

    @staticmethod
    def _fingerprint(category: FailureCategory, code: str, message: str) -> str:
        normalized = message.casefold()
        normalized = re.sub(r"\b[0-9a-f]{8,}\b", "<id>", normalized)
        normalized = re.sub(r"\b\d+\b", "<n>", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()[:240]
        raw = f"{category.value}|{code}|{normalized}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]


class RetryPolicyService:
    """Select failed jobs for retry and assign deterministic backoff windows."""

    def __init__(self, *, base_delay_seconds: float = 2.0, maximum_delay_seconds: float = 300.0) -> None:
        self.base_delay_seconds = max(0.0, base_delay_seconds)
        self.maximum_delay_seconds = max(self.base_delay_seconds, maximum_delay_seconds)

    def decision(
        self,
        job: TTSJob,
        *,
        max_retries: int,
        transient_only: bool = False,
        category: FailureCategory | str | None = None,
        manual_override: bool = False,
        now: datetime | None = None,
    ) -> RetryDecision:
        if job.status == JobStatus.RUNNING:
            return RetryDecision(False, "active_job")
        if job.status != JobStatus.FAILED:
            return RetryDecision(False, "not_failed")
        requested_category = FailureCategory(category) if category else None
        actual_category = job.failure_category or FailureCategory.UNKNOWN
        if requested_category is not None and actual_category != requested_category:
            return RetryDecision(False, "category_mismatch")
        if not manual_override:
            if transient_only and actual_category not in _TRANSIENT_CATEGORIES:
                return RetryDecision(False, "not_transient")
            if job.retryable is False:
                return RetryDecision(False, "permanent_failure")
            if max_retries >= 0 and job.retry_count >= max_retries:
                return RetryDecision(False, "retry_limit")
        delay = 0.0 if manual_override else min(
            self.maximum_delay_seconds,
            self.base_delay_seconds * (2 ** max(0, job.retry_count - 1)),
        )
        timestamp = (now or datetime.now(timezone.utc)) + timedelta(seconds=delay)
        return RetryDecision(True, "manual_override" if manual_override else "scheduled", delay, timestamp.isoformat())

    def prepare(
        self,
        jobs: Iterable[TTSJob],
        *,
        max_retries: int,
        transient_only: bool = False,
        category: FailureCategory | str | None = None,
        manual_override: bool = False,
        now: datetime | None = None,
    ) -> RetryBatchResult:
        selected = list(jobs)
        blocked = Counter()
        categories = Counter()
        scheduled_rows: list[int] = []
        current_time = now or datetime.now(timezone.utc)
        for job in selected:
            decision = self.decision(
                job,
                max_retries=max_retries,
                transient_only=transient_only,
                category=category,
                manual_override=manual_override,
                now=current_time,
            )
            if not decision.eligible:
                blocked[decision.reason] += 1
                continue
            actual_category = job.failure_category or FailureCategory.UNKNOWN
            job.status = JobStatus.PENDING
            job.next_retry_at = decision.next_retry_at
            job.retry_exhausted = False
            job.retry_history.append(
                RetryHistoryEntry(
                    timestamp=current_time.isoformat(),
                    event="manual_override" if manual_override else "retry_scheduled",
                    attempt=job.retry_count + 1,
                    category=actual_category,
                    error_code=job.error_code,
                    fingerprint=job.error_fingerprint,
                    retryable=bool(job.retryable),
                    delay_seconds=decision.delay_seconds,
                    message=decision.reason,
                )
            )
            categories[actual_category.value] += 1
            scheduled_rows.append(job.row_number)
        return RetryBatchResult(
            requested=len(selected),
            scheduled=len(scheduled_rows),
            blocked=sum(blocked.values()),
            blocked_reasons=dict(sorted(blocked.items())),
            categories=dict(sorted(categories.items())),
            row_numbers=tuple(scheduled_rows),
        )
