from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import fmean
from typing import Iterable

from app.models.generation_estimate_actual import (
    GenerationEstimateActualProviderSummary,
    GenerationEstimateActualRun,
    GenerationEstimateActualSummary,
)
from app.models.generation_execution_receipt import GenerationExecutionReceipt
from app.models.generation_execution_session import GenerationExecutionSession
from app.models.generation_launch_receipt import GenerationLaunchReceipt
from app.services.generation_execution_receipt_service import GenerationExecutionReceiptService
from app.services.generation_execution_session_service import GenerationExecutionSessionService
from app.services.generation_launch_receipt_service import GenerationLaunchReceiptService


class GenerationEstimateActualService:
    """Compare launch estimates with completed execution evidence and suggest calibration."""

    SECRET_VALUE = re.compile(
        r"(sk[_-][A-Za-z0-9_=-]+|Bearer\s+[A-Za-z0-9._=-]+|(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;}]+)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        reports_dir: Path,
        *,
        launch_receipt_service: GenerationLaunchReceiptService | None = None,
        execution_receipt_service: GenerationExecutionReceiptService | None = None,
        execution_session_service: GenerationExecutionSessionService | None = None,
    ) -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.launch_receipt_service = launch_receipt_service or GenerationLaunchReceiptService(
            self.reports_dir
        )
        self.execution_receipt_service = (
            execution_receipt_service or GenerationExecutionReceiptService(self.reports_dir)
        )
        self.execution_session_service = (
            execution_session_service or GenerationExecutionSessionService(self.reports_dir)
        )

    def list_runs(
        self,
        *,
        project_name: str | None = None,
        provider: str | None = None,
        status: str | None = None,
        search: str = "",
        limit: int = 1000,
    ) -> list[GenerationEstimateActualRun]:
        project_key = str(project_name or "").strip().casefold()
        provider_key = str(provider or "").strip().casefold()
        status_key = str(status or "").strip().casefold()
        search_key = str(search or "").strip().casefold()
        result: list[GenerationEstimateActualRun] = []
        for receipt in self.execution_receipt_service.list_receipts(limit=max(limit * 2, 1000)):
            record = self.analyze_receipt(receipt)
            if project_key and record.project_name.casefold() != project_key:
                continue
            if provider_key and record.provider.casefold() != provider_key:
                continue
            if status_key and record.status.casefold() != status_key:
                continue
            if search_key and search_key not in self._search_text(record):
                continue
            result.append(record)
        result.sort(key=lambda item: (item.finished_at, item.run_id), reverse=True)
        return result[: max(0, int(limit))]

    def analyze_receipt(
        self,
        receipt: GenerationExecutionReceipt,
    ) -> GenerationEstimateActualRun:
        launch = self._load_launch(receipt.launch_receipt_path)
        session = self._load_session(receipt.execution_session_path)
        actual_characters, retry_characters, retry_events = self._actual_character_metrics(
            receipt,
            session,
        )
        actual_requests = self._actual_requests(receipt, session, retry_events)
        estimated_files = max(0, launch.files if launch is not None else receipt.planned_files)
        estimated_characters = max(
            0,
            launch.characters if launch is not None else receipt.planned_characters,
        )
        estimated_requests = max(
            0,
            launch.provider_requests if launch is not None else receipt.planned_requests,
        )
        estimated_duration = max(
            0.0,
            launch.estimated_duration_seconds if launch is not None else 0.0,
        )
        actual_duration = max(0.0, float(receipt.elapsed_seconds or 0.0))
        estimated_cost = max(0.0, float(launch.estimated_cost if launch is not None else 0.0))
        currency = str(launch.currency if launch is not None else "USD").upper()
        actual_cost, cost_source = self._derived_actual_cost(
            estimated_cost=estimated_cost,
            estimated_characters=estimated_characters,
            actual_characters=actual_characters,
            retry_characters=retry_characters,
        )
        actual_files = max(0, receipt.actual_outputs + receipt.skipped_outputs)
        file_accuracy = self._accuracy(estimated_files, actual_files)
        character_accuracy = self._accuracy(estimated_characters, actual_characters)
        request_accuracy = self._accuracy(estimated_requests, actual_requests)
        duration_accuracy = self._accuracy(estimated_duration, actual_duration)
        cost_accuracy = self._accuracy(estimated_cost, actual_cost)
        accuracy_score = self._accuracy_score(
            file_accuracy=file_accuracy,
            character_accuracy=character_accuracy,
            request_accuracy=request_accuracy,
            duration_accuracy=duration_accuracy if estimated_duration > 0 else None,
            cost_accuracy=cost_accuracy if estimated_cost > 0 else None,
        )
        success_denominator = max(1, receipt.planned_files)
        successful = max(0, receipt.created_outputs + receipt.overwritten_outputs + receipt.skipped_outputs)
        success_rate = min(100.0, successful / success_denominator * 100.0)
        attention: list[str] = []
        if receipt.integrity_status in {"mismatch", "unreadable"}:
            attention.append("Execution receipt integrity requires attention.")
        if launch is not None and launch.integrity_status in {"mismatch", "unreadable"}:
            attention.append("Launch receipt integrity requires attention.")
        if receipt.status in {"partial", "failed", "cancelled"}:
            attention.append(f"Run finished with {receipt.status} status.")
        if estimated_duration > 0 and actual_duration > estimated_duration * 1.25:
            attention.append("Actual duration exceeded the estimate by more than 25%.")
        if estimated_cost > 0 and actual_cost > estimated_cost * 1.15:
            attention.append("Derived actual cost exceeded the estimate by more than 15%.")
        if file_accuracy < 75.0 or character_accuracy < 75.0 or request_accuracy < 75.0:
            attention.append("One or more workload estimates were below 75% accuracy.")
        confidence = self._confidence(receipt, launch, session, estimated_duration, estimated_cost)
        return GenerationEstimateActualRun(
            run_id=receipt.run_id,
            project_name=receipt.project_name,
            status=receipt.status,
            provider=receipt.provider or (launch.provider if launch is not None else "unknown"),
            model_id=receipt.model_id or (launch.model_id if launch is not None else ""),
            voice_id=receipt.voice_id or (launch.voice_id if launch is not None else ""),
            currency=currency,
            launch_receipt_id=receipt.launch_receipt_id,
            launch_receipt_path=receipt.launch_receipt_path,
            execution_receipt_id=receipt.receipt_id,
            execution_receipt_path=str(receipt.path),
            execution_session_path=receipt.execution_session_path,
            finished_at=receipt.finished_at,
            estimated_files=estimated_files,
            actual_files=actual_files,
            file_variance=actual_files - estimated_files,
            file_accuracy_percent=file_accuracy,
            estimated_characters=estimated_characters,
            actual_characters=actual_characters,
            retry_characters=retry_characters,
            character_variance=actual_characters - estimated_characters,
            character_accuracy_percent=character_accuracy,
            estimated_requests=estimated_requests,
            actual_requests=actual_requests,
            request_variance=actual_requests - estimated_requests,
            request_accuracy_percent=request_accuracy,
            estimated_duration_seconds=estimated_duration,
            actual_duration_seconds=actual_duration,
            duration_variance_seconds=actual_duration - estimated_duration,
            duration_accuracy_percent=duration_accuracy,
            duration_multiplier=self._multiplier(estimated_duration, actual_duration),
            estimated_cost=estimated_cost,
            actual_cost=round(actual_cost, 8),
            cost_variance=round(actual_cost - estimated_cost, 8),
            cost_accuracy_percent=cost_accuracy,
            cost_multiplier=self._multiplier(estimated_cost, actual_cost),
            cost_source=cost_source,
            estimate_accuracy_score=accuracy_score,
            retry_events=retry_events,
            success_rate_percent=success_rate,
            confidence=confidence,
            integrity_status=receipt.integrity_status,
            attention_reasons=tuple(dict.fromkeys(attention)),
        )

    @staticmethod
    def summary(records: Iterable[GenerationEstimateActualRun]) -> GenerationEstimateActualSummary:
        items = list(records)
        return GenerationEstimateActualSummary(
            total_runs=len(items),
            completed_runs=sum(item.status == "completed" for item in items),
            partial_runs=sum(item.status == "partial" for item in items),
            failed_runs=sum(item.status == "failed" for item in items),
            cancelled_runs=sum(item.status == "cancelled" for item in items),
            project_count=len({item.project_name.casefold() for item in items if item.project_name}),
            provider_count=len({(item.provider.casefold(), item.model_id.casefold()) for item in items}),
            estimated_files=sum(item.estimated_files for item in items),
            actual_files=sum(item.actual_files for item in items),
            estimated_characters=sum(item.estimated_characters for item in items),
            actual_characters=sum(item.actual_characters for item in items),
            estimated_requests=sum(item.estimated_requests for item in items),
            actual_requests=sum(item.actual_requests for item in items),
            estimated_duration_seconds=sum(item.estimated_duration_seconds for item in items),
            actual_duration_seconds=sum(item.actual_duration_seconds for item in items),
            estimated_cost=sum(item.estimated_cost for item in items),
            actual_cost=sum(item.actual_cost for item in items),
            average_file_accuracy_percent=GenerationEstimateActualService._average(
                item.file_accuracy_percent for item in items
            ),
            average_character_accuracy_percent=GenerationEstimateActualService._average(
                item.character_accuracy_percent for item in items
            ),
            average_request_accuracy_percent=GenerationEstimateActualService._average(
                item.request_accuracy_percent for item in items
            ),
            average_duration_accuracy_percent=GenerationEstimateActualService._average(
                item.duration_accuracy_percent for item in items if item.estimated_duration_seconds > 0
            ),
            average_cost_accuracy_percent=GenerationEstimateActualService._average(
                item.cost_accuracy_percent for item in items if item.estimated_cost > 0
            ),
            average_accuracy_score=GenerationEstimateActualService._average(
                item.estimate_accuracy_score for item in items
            ),
            duration_overrun_count=sum(
                item.estimated_duration_seconds > 0
                and item.actual_duration_seconds > item.estimated_duration_seconds * 1.25
                for item in items
            ),
            cost_overrun_count=sum(
                item.estimated_cost > 0 and item.actual_cost > item.estimated_cost * 1.15
                for item in items
            ),
            high_variance_count=sum(item.requires_attention for item in items),
            total_retry_events=sum(item.retry_events for item in items),
        )

    @staticmethod
    def provider_summaries(
        records: Iterable[GenerationEstimateActualRun],
    ) -> list[GenerationEstimateActualProviderSummary]:
        grouped: dict[tuple[str, str, str, str], list[GenerationEstimateActualRun]] = {}
        for item in records:
            key = (item.provider, item.model_id, item.voice_id, item.currency)
            grouped.setdefault(key, []).append(item)
        result: list[GenerationEstimateActualProviderSummary] = []
        for (provider, model_id, voice_id, currency), items in grouped.items():
            durations = [item.duration_multiplier for item in items if item.duration_multiplier > 0]
            costs = [item.cost_multiplier for item in items if item.cost_multiplier > 0]
            actual_duration = sum(item.actual_duration_seconds for item in items)
            actual_characters = sum(item.actual_characters for item in items)
            duration_multiplier = GenerationEstimateActualService._average(durations, default=1.0)
            cost_multiplier = GenerationEstimateActualService._average(costs, default=1.0)
            recommendations = GenerationEstimateActualService._recommendations(
                duration_multiplier=duration_multiplier,
                cost_multiplier=cost_multiplier,
                success_rate=GenerationEstimateActualService._average(
                    item.success_rate_percent for item in items
                ),
                run_count=len(items),
            )
            result.append(
                GenerationEstimateActualProviderSummary(
                    provider=provider,
                    model_id=model_id,
                    voice_id=voice_id,
                    currency=currency,
                    run_count=len(items),
                    completed_run_count=sum(item.status == "completed" for item in items),
                    total_characters=actual_characters,
                    total_retry_events=sum(item.retry_events for item in items),
                    success_rate_percent=GenerationEstimateActualService._average(
                        item.success_rate_percent for item in items
                    ),
                    average_file_accuracy_percent=GenerationEstimateActualService._average(
                        item.file_accuracy_percent for item in items
                    ),
                    average_character_accuracy_percent=GenerationEstimateActualService._average(
                        item.character_accuracy_percent for item in items
                    ),
                    average_request_accuracy_percent=GenerationEstimateActualService._average(
                        item.request_accuracy_percent for item in items
                    ),
                    average_duration_accuracy_percent=GenerationEstimateActualService._average(
                        item.duration_accuracy_percent
                        for item in items
                        if item.estimated_duration_seconds > 0
                    ),
                    average_cost_accuracy_percent=GenerationEstimateActualService._average(
                        item.cost_accuracy_percent for item in items if item.estimated_cost > 0
                    ),
                    estimate_accuracy_score=GenerationEstimateActualService._average(
                        item.estimate_accuracy_score for item in items
                    ),
                    duration_multiplier=duration_multiplier,
                    cost_multiplier=cost_multiplier,
                    characters_per_minute=(actual_characters / actual_duration * 60.0)
                    if actual_duration > 0
                    else 0.0,
                    confidence=GenerationEstimateActualService._group_confidence(items),
                    recommendations=recommendations,
                )
            )
        result.sort(key=lambda item: (-item.run_count, item.provider.casefold(), item.model_id.casefold()))
        return result

    def export(
        self,
        records: Iterable[GenerationEstimateActualRun],
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path, Path]:
        items = list(records)
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe = self._safe_name(project_name)
        json_path = target / f"generation-estimate-actual-{safe}-{stamp}.json"
        csv_path = target / f"generation-estimate-actual-{safe}-{stamp}.csv"
        calibration_path = target / f"generation-estimate-calibration-{safe}-{stamp}.json"
        rows = [self._run_row(item) for item in items]
        providers = self.provider_summaries(items)
        json_path.write_text(
            json.dumps(
                {
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project": project_name,
                    "summary": asdict(self.summary(items)),
                    "provider_metrics": [asdict(item) for item in providers],
                    "runs": rows,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        fields = list(rows[0]) if rows else list(self._run_row(self._empty_run()))
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        calibration_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                    "project": project_name,
                    "note": "Calibration suggestions are advisory and are not applied automatically.",
                    "providers": [asdict(item) for item in providers],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        self._assert_secret_free(json_path, csv_path, calibration_path)
        return json_path, csv_path, calibration_path

    def _load_launch(self, path: str) -> GenerationLaunchReceipt | None:
        if not path or not Path(path).is_file():
            return None
        return self.launch_receipt_service.load(Path(path))

    def _load_session(self, path: str) -> GenerationExecutionSession | None:
        if not path or not Path(path).is_file():
            return None
        return self.execution_session_service.load(Path(path))

    @staticmethod
    def _actual_character_metrics(
        receipt: GenerationExecutionReceipt,
        session: GenerationExecutionSession | None,
    ) -> tuple[int, int, int]:
        if session is not None:
            attempted_jobs = [
                job for job in session.jobs if job.status in {"completed", "failed"}
            ]
            actual = sum(max(0, job.character_count) for job in attempted_jobs)
            retry_characters = sum(
                max(0, job.character_count) * max(0, job.retry_count)
                for job in attempted_jobs
            )
            return actual, retry_characters, max(0, session.retry_events)
        retries = sum(max(0, entry.retry_count) for entry in receipt.entries)
        return 0, 0, retries

    @staticmethod
    def _actual_requests(
        receipt: GenerationExecutionReceipt,
        session: GenerationExecutionSession | None,
        retry_events: int,
    ) -> int:
        if session is not None:
            attempted = max(0, session.completed_jobs + session.failed_jobs)
            return attempted + max(0, retry_events)
        attempted = sum(
            entry.job_status in {"completed", "failed"}
            for entry in receipt.entries
            if entry.disposition != "unexpected"
        )
        return attempted + max(0, retry_events)

    @staticmethod
    def _derived_actual_cost(
        *,
        estimated_cost: float,
        estimated_characters: int,
        actual_characters: int,
        retry_characters: int,
    ) -> tuple[float, str]:
        if estimated_cost <= 0 or estimated_characters <= 0:
            return 0.0, "unavailable"
        billable = max(0, actual_characters) + max(0, retry_characters)
        return round(estimated_cost / estimated_characters * billable, 8), "derived_from_launch_rate"

    @staticmethod
    def _accuracy(expected: float, actual: float) -> float:
        expected_value = max(0.0, float(expected or 0.0))
        actual_value = max(0.0, float(actual or 0.0))
        if expected_value <= 0:
            return 100.0 if actual_value <= 0 else 0.0
        error = abs(actual_value - expected_value) / expected_value
        return round(max(0.0, min(100.0, (1.0 - error) * 100.0)), 2)

    @staticmethod
    def _accuracy_score(
        *,
        file_accuracy: float,
        character_accuracy: float,
        request_accuracy: float,
        duration_accuracy: float | None,
        cost_accuracy: float | None,
    ) -> float:
        values = [file_accuracy, character_accuracy, request_accuracy]
        if duration_accuracy is not None:
            values.append(duration_accuracy)
        if cost_accuracy is not None:
            values.append(cost_accuracy)
        return GenerationEstimateActualService._average(values)

    @staticmethod
    def _multiplier(expected: float, actual: float) -> float:
        expected_value = max(0.0, float(expected or 0.0))
        if expected_value <= 0:
            return 0.0
        return round(max(0.0, float(actual or 0.0)) / expected_value, 4)

    @staticmethod
    def _average(values: Iterable[float], *, default: float = 0.0) -> float:
        numbers = [float(item) for item in values]
        return round(fmean(numbers), 2) if numbers else default

    @staticmethod
    def _confidence(
        receipt: GenerationExecutionReceipt,
        launch: GenerationLaunchReceipt | None,
        session: GenerationExecutionSession | None,
        estimated_duration: float,
        estimated_cost: float,
    ) -> str:
        if receipt.integrity_status in {"mismatch", "unreadable"}:
            return "low"
        if launch is None or session is None:
            return "low"
        if launch.integrity_status in {"mismatch", "unreadable"}:
            return "low"
        if estimated_duration > 0 and estimated_cost > 0:
            return "high"
        return "medium"

    @staticmethod
    def _group_confidence(items: list[GenerationEstimateActualRun]) -> str:
        if len(items) >= 5 and sum(item.confidence == "high" for item in items) >= 3:
            return "high"
        if len(items) >= 2 and any(item.confidence in {"high", "medium"} for item in items):
            return "medium"
        return "low"

    @staticmethod
    def _recommendations(
        *,
        duration_multiplier: float,
        cost_multiplier: float,
        success_rate: float,
        run_count: int,
    ) -> tuple[str, ...]:
        recommendations: list[str] = []
        if run_count < 3:
            recommendations.append("Collect at least three comparable runs before applying calibration.")
        if duration_multiplier > 1.15:
            recommendations.append(
                f"Increase ETA calibration by about {(duration_multiplier - 1.0) * 100.0:.0f}%."
            )
        elif 0 < duration_multiplier < 0.85:
            recommendations.append(
                f"Decrease ETA calibration by about {(1.0 - duration_multiplier) * 100.0:.0f}%."
            )
        if cost_multiplier > 1.10:
            recommendations.append(
                f"Increase cost calibration by about {(cost_multiplier - 1.0) * 100.0:.0f}%."
            )
        elif 0 < cost_multiplier < 0.90:
            recommendations.append(
                f"Decrease cost calibration by about {(1.0 - cost_multiplier) * 100.0:.0f}%."
            )
        if success_rate < 90.0:
            recommendations.append("Review provider reliability and retry policy before using this profile.")
        if not recommendations:
            recommendations.append("Current estimates are tracking actual execution within the target range.")
        return tuple(recommendations)

    @staticmethod
    def _search_text(record: GenerationEstimateActualRun) -> str:
        return " ".join(
            (
                record.run_id,
                record.project_name,
                record.status,
                record.provider,
                record.model_id,
                record.voice_id,
                record.launch_receipt_id,
                record.execution_receipt_id,
                record.confidence,
            )
        ).casefold()

    @staticmethod
    def _run_row(record: GenerationEstimateActualRun) -> dict[str, object]:
        return asdict(record)

    @staticmethod
    def _empty_run() -> GenerationEstimateActualRun:
        return GenerationEstimateActualRun("", "", "", "")

    @staticmethod
    def _safe_name(value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._") or "unknown"

    @classmethod
    def _assert_secret_free(cls, *paths: Path) -> None:
        for path in paths:
            text = path.read_text(encoding="utf-8-sig", errors="ignore")
            if cls.SECRET_VALUE.search(text):
                raise ValueError(f"Secret-like content detected in analytics export: {path.name}")
