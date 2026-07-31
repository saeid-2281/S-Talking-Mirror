from __future__ import annotations

import csv
import hashlib
import json
import re
import statistics
import uuid
from collections import defaultdict
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable

from app.models.generation_cost_capacity import (
    GenerationCapacityForecast,
    GenerationCostBudgetPolicy,
    GenerationCostCapacityDashboard,
    GenerationCostCapacitySnapshot,
    GenerationPricingRate,
    GenerationProviderCostEfficiency,
    GenerationSessionCost,
)
from app.models.product_events import ActivityEvent, BatchSessionRecord, NotificationRecord
from app.repositories.job_repository import JobRepository
from app.repositories.product_event_repository import ProductEventRepository


class GenerationCostCapacityService:
    """Estimate generation cost, enforce budgets, and forecast queue capacity."""

    def __init__(
        self,
        repository: ProductEventRepository,
        job_repository: JobRepository | None = None,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.job_repository = job_repository
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def default_policy(project_id: int | None = None) -> GenerationCostBudgetPolicy:
        return GenerationCostBudgetPolicy(project_id=project_id)

    def get_policy(self, project_id: int | None) -> GenerationCostBudgetPolicy:
        if project_id is not None:
            project_policy = self.repository.get_cost_budget_policy(project_id)
            if project_policy is not None:
                return project_policy
        global_policy = self.repository.get_cost_budget_policy(None)
        if global_policy is not None:
            return replace(global_policy, project_id=project_id)
        return self.default_policy(project_id)

    def save_policy(
        self,
        policy: GenerationCostBudgetPolicy,
    ) -> GenerationCostBudgetPolicy:
        normalized = replace(
            policy,
            currency=self._currency(policy.currency),
            daily_budget=max(0.0, float(policy.daily_budget)),
            weekly_budget=max(0.0, float(policy.weekly_budget)),
            monthly_budget=max(0.0, float(policy.monthly_budget)),
            warning_percent=max(1.0, min(100.0, float(policy.warning_percent))),
            max_queue_cost=max(0.0, float(policy.max_queue_cost)),
            default_price_per_million_characters=max(
                0.0,
                float(policy.default_price_per_million_characters),
            ),
            alert_cooldown_minutes=max(0, int(policy.alert_cooldown_minutes)),
            updated_at=self._now().isoformat(),
        )
        self.repository.save_cost_budget_policy(normalized)
        return normalized

    def save_rate(self, rate: GenerationPricingRate) -> GenerationPricingRate:
        provider = rate.provider.strip().casefold()
        if not provider:
            raise ValueError("Provider is required.")
        model = (rate.model or "*").strip() or "*"
        current = self._now().isoformat()
        normalized = replace(
            rate,
            rate_id=rate.rate_id or uuid.uuid4().hex,
            provider=provider,
            model=model,
            price_per_million_characters=max(
                0.0,
                float(rate.price_per_million_characters),
            ),
            currency=self._currency(rate.currency),
            source=rate.source.strip() or "manual",
            effective_from=rate.effective_from or current,
            updated_at=current,
        )
        self.repository.save_pricing_rate(normalized)
        return normalized

    def delete_rate(self, rate_id: str) -> None:
        self.repository.delete_pricing_rate(rate_id)

    def list_rates(self, project_id: int | None) -> list[GenerationPricingRate]:
        return self.repository.list_pricing_rates(
            project_id=project_id,
            include_global=True,
        )

    def rate_for(
        self,
        *,
        project_id: int | None,
        provider: str,
        model: str,
    ) -> tuple[float, str, str]:
        provider_key = provider.strip().casefold()
        model_key = model.strip().casefold()
        rates = self.list_rates(project_id)
        candidates = (
            (project_id, provider_key, model_key),
            (project_id, provider_key, "*"),
            (None, provider_key, model_key),
            (None, provider_key, "*"),
        )
        for scope, candidate_provider, candidate_model in candidates:
            for rate in rates:
                if rate.project_id != scope:
                    continue
                if rate.provider.strip().casefold() != candidate_provider:
                    continue
                if rate.model.strip().casefold() != candidate_model:
                    continue
                return (
                    max(0.0, rate.price_per_million_characters),
                    rate.currency,
                    rate.source,
                )
        policy = self.get_policy(project_id)
        return (
            policy.default_price_per_million_characters,
            policy.currency,
            "policy-default",
        )

    def estimate_cost(
        self,
        *,
        project_id: int | None,
        provider: str,
        model: str,
        characters: int,
        retry_characters: int = 0,
    ) -> tuple[float, float, str, str]:
        rate, currency, source = self.rate_for(
            project_id=project_id,
            provider=provider,
            model=model,
        )
        policy = self.get_policy(project_id)
        billable = max(0, int(characters))
        if policy.bill_retry_characters:
            billable += max(0, int(retry_characters))
        return billable / 1_000_000.0 * rate, rate, currency, source

    def record_session(
        self,
        record: BatchSessionRecord,
    ) -> GenerationSessionCost:
        average_characters = (
            record.character_count / record.total_jobs if record.total_jobs > 0 else 0.0
        )
        retry_characters = max(0, round(average_characters * record.retry_events))
        estimated, rate, currency, source = self.estimate_cost(
            project_id=record.project_id,
            provider=record.provider,
            model=record.model,
            characters=record.character_count,
            retry_characters=retry_characters,
        )
        actual_cost = self._optional_number(
            record.monitor_metrics.get("actual_cost")
            or record.monitor_metrics.get("provider_cost")
            or record.monitor_metrics.get("cost")
        )
        actual_currency = str(
            record.monitor_metrics.get("cost_currency") or currency
        ).upper()
        policy = self.get_policy(record.project_id)
        billable = max(0, record.character_count)
        if policy.bill_retry_characters:
            billable += retry_characters
        cost = GenerationSessionCost(
            session_id=record.session_id,
            project_id=record.project_id,
            provider=record.provider,
            model=record.model,
            currency=actual_currency if actual_cost is not None else currency,
            character_count=max(0, record.character_count),
            retry_characters=retry_characters,
            billable_characters=billable,
            price_per_million_characters=rate,
            estimated_cost=max(0.0, estimated),
            actual_cost=actual_cost,
            cost_source="provider-actual" if actual_cost is not None else source,
            recorded_at=record.finished_at or record.started_at or self._now().isoformat(),
        )
        self.repository.save_session_cost(cost)
        return cost

    def capacity_forecast(
        self,
        *,
        project_id: int | None,
        provider: str,
        model: str,
        queued_jobs: int | None = None,
        queued_characters: int | None = None,
        now: datetime | None = None,
    ) -> GenerationCapacityForecast:
        current = self._aware(now or self._now())
        if queued_jobs is None or queued_characters is None:
            jobs, characters = self._queued_work(project_id)
            if queued_jobs is None:
                queued_jobs = jobs
            if queued_characters is None:
                queued_characters = characters
        queued_jobs = max(0, int(queued_jobs or 0))
        queued_characters = max(0, int(queued_characters or 0))
        sessions = [
            item
            for item in self.repository.list_batch_sessions(
                project_id=project_id,
                provider=provider or None,
                limit=500,
            )
            if (not model or item.model == model)
            and item.completed_jobs > 0
            and item.result not in {"failed", "cancelled"}
        ]
        character_rates = [
            item.characters_per_minute
            for item in sessions
            if item.characters_per_minute > 0
        ]
        file_rates = [
            item.files_per_minute for item in sessions if item.files_per_minute > 0
        ]
        characters_per_minute = self._median(character_rates)
        files_per_minute = self._median(file_rates)
        if queued_characters > 0 and characters_per_minute > 0:
            duration = queued_characters / characters_per_minute * 60.0
            limiting_factor = "characters"
        elif queued_jobs > 0 and files_per_minute > 0:
            duration = queued_jobs / files_per_minute * 60.0
            limiting_factor = "files"
        else:
            duration = queued_jobs * 3.0
            limiting_factor = "fallback"
        estimated_cost, _rate, currency, _source = self.estimate_cost(
            project_id=project_id,
            provider=provider,
            model=model,
            characters=queued_characters,
        )
        sample_count = len(sessions)
        confidence = "high" if sample_count >= 5 else "medium" if sample_count >= 2 else "low"
        completion = current + timedelta(seconds=duration) if queued_jobs else None
        return GenerationCapacityForecast(
            project_id=project_id,
            provider=provider,
            model=model,
            currency=currency,
            queued_jobs=queued_jobs,
            queued_characters=queued_characters,
            estimated_cost=estimated_cost,
            estimated_duration_seconds=max(0.0, duration),
            estimated_completion_at=completion.isoformat() if completion else None,
            files_per_minute=files_per_minute,
            characters_per_minute=characters_per_minute,
            historical_session_count=sample_count,
            confidence=confidence,
            limiting_factor=limiting_factor,
        )

    def dashboard(
        self,
        *,
        project_id: int | None = None,
        provider: str = "",
        model: str = "",
        now: datetime | None = None,
        history_limit: int = 60,
    ) -> GenerationCostCapacityDashboard:
        current = self._aware(now or self._now())
        policy = self.get_policy(project_id)
        self._backfill_costs(project_id)
        costs = self.repository.list_session_costs(project_id=project_id, limit=100000)
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=day_start.weekday())
        month_start = day_start.replace(day=1)
        period_start = min(day_start, week_start, month_start)
        day_costs = self._costs_between(costs, day_start, current)
        week_costs = self._costs_between(costs, week_start, current)
        month_costs = self._costs_between(costs, month_start, current)
        all_current = self._costs_between(costs, period_start, current)
        forecast = self.capacity_forecast(
            project_id=project_id,
            provider=provider,
            model=model,
            now=current,
        )
        provider_metrics = self._provider_metrics(project_id, costs)
        daily_spend = self._sum_cost(day_costs)
        weekly_spend = self._sum_cost(week_costs)
        monthly_spend = self._sum_cost(month_costs)
        total_cost = self._sum_cost(all_current)
        retry_cost = sum(
            item.retry_characters / 1_000_000.0 * item.price_per_million_characters
            for item in all_current
        )
        projected_monthly = self._project_monthly(monthly_spend, current)
        budget_usage = {
            "daily": self._usage(daily_spend, policy.daily_budget),
            "weekly": self._usage(weekly_spend, policy.weekly_budget),
            "monthly": self._usage(monthly_spend, policy.monthly_budget),
        }
        state, reasons, codes = self._budget_state(
            policy=policy,
            budget_usage=budget_usage,
            projected_monthly=projected_monthly,
            queue_cost=forecast.estimated_cost,
        )
        fingerprint = None
        if codes:
            raw = f"{project_id}:{','.join(sorted(codes))}:{policy.currency}"
            fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        snapshot = GenerationCostCapacitySnapshot(
            snapshot_id=uuid.uuid4().hex,
            project_id=project_id,
            period_start=period_start.isoformat(),
            period_end=current.isoformat(),
            created_at=current.isoformat(),
            currency=policy.currency,
            session_count=len(all_current),
            total_characters=sum(item.character_count for item in all_current),
            retry_characters=sum(item.retry_characters for item in all_current),
            total_cost=total_cost,
            retry_cost=retry_cost,
            daily_spend=daily_spend,
            weekly_spend=weekly_spend,
            monthly_spend=monthly_spend,
            daily_budget_usage_percent=budget_usage["daily"],
            weekly_budget_usage_percent=budget_usage["weekly"],
            monthly_budget_usage_percent=budget_usage["monthly"],
            projected_monthly_cost=projected_monthly,
            queue_forecast=forecast,
            provider_metrics=tuple(provider_metrics),
            state=state,
            reasons=tuple(reasons),
            alert_fingerprint=fingerprint,
        )
        return GenerationCostCapacityDashboard(
            policy=policy,
            snapshot=snapshot,
            rates=tuple(self.list_rates(project_id)),
            recent_costs=tuple(costs[:100]),
            history=tuple(
                self.repository.list_cost_capacity_snapshots(
                    project_id=project_id,
                    limit=history_limit,
                )
            ),
            budget_status={
                name: self._usage_status(value, policy.warning_percent)
                for name, value in budget_usage.items()
            },
        )

    def evaluate_and_persist(
        self,
        *,
        project_id: int | None = None,
        provider: str = "",
        model: str = "",
        now: datetime | None = None,
    ) -> GenerationCostCapacitySnapshot:
        dashboard = self.dashboard(
            project_id=project_id,
            provider=provider,
            model=model,
            now=now,
        )
        snapshot = dashboard.snapshot
        self.repository.add_cost_capacity_snapshot(snapshot)
        if snapshot.state not in {"warning", "critical"}:
            return snapshot
        if not snapshot.alert_fingerprint:
            return snapshot
        current = self._parse(snapshot.created_at)
        since = current - timedelta(minutes=dashboard.policy.alert_cooldown_minutes)
        if self.repository.has_recent_cost_alert(
            snapshot.alert_fingerprint,
            since.isoformat(),
        ):
            return snapshot
        title = (
            "Generation cost budget exceeded"
            if snapshot.state == "critical"
            else "Generation cost budget warning"
        )
        message = "; ".join(snapshot.reasons)
        notification = NotificationRecord(
            notification_id=uuid.uuid4().hex,
            severity="error" if snapshot.state == "critical" else "warning",
            title=title,
            message=message,
            created_at=snapshot.created_at,
            action_label="Open Cost & Capacity",
            action_payload="generation-cost-capacity",
        )
        self.repository.add_notification(notification)
        self.repository.attach_cost_snapshot_notification(
            snapshot.snapshot_id,
            notification.notification_id,
        )
        self.repository.add_activity(
            ActivityEvent(
                event_id=uuid.uuid4().hex,
                project_id=project_id,
                category="generation-cost-capacity",
                title=title,
                message=message,
                created_at=snapshot.created_at,
                metadata={
                    "snapshot_id": snapshot.snapshot_id,
                    "state": snapshot.state,
                    "daily_spend": snapshot.daily_spend,
                    "monthly_spend": snapshot.monthly_spend,
                    "projected_monthly_cost": snapshot.projected_monthly_cost,
                    "queue_cost": (
                        snapshot.queue_forecast.estimated_cost
                        if snapshot.queue_forecast is not None
                        else 0.0
                    ),
                    "alert_fingerprint": snapshot.alert_fingerprint,
                    "notification_id": notification.notification_id,
                },
            )
        )
        return replace(snapshot, alert_notification_id=notification.notification_id)

    @staticmethod
    def export(
        dashboard: GenerationCostCapacityDashboard,
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-")
        safe_name = safe_name or "cost-capacity"
        json_path = directory / f"generation-cost-capacity-{safe_name}-{stamp}.json"
        csv_path = directory / f"generation-cost-capacity-{safe_name}-{stamp}.csv"
        payload = {
            "created_at": datetime.now(timezone.utc).isoformat(),
            "project": project_name,
            "policy": asdict(dashboard.policy),
            "snapshot": asdict(dashboard.snapshot),
            "budget_status": dashboard.budget_status,
            "rates": [asdict(item) for item in dashboard.rates],
            "recent_costs": [asdict(item) for item in dashboard.recent_costs],
            "history": [asdict(item) for item in dashboard.history],
        }
        json_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        rows = [
            {
                **asdict(item),
                "effective_cost": item.effective_cost,
            }
            for item in dashboard.recent_costs
        ]
        fieldnames = [
            "session_id",
            "project_id",
            "provider",
            "model",
            "currency",
            "character_count",
            "retry_characters",
            "billable_characters",
            "price_per_million_characters",
            "estimated_cost",
            "actual_cost",
            "effective_cost",
            "cost_source",
            "recorded_at",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        return json_path, csv_path

    def _backfill_costs(self, project_id: int | None) -> None:
        sessions = self.repository.list_batch_sessions(
            project_id=project_id,
            limit=100000,
        )
        for session in sessions:
            if self.repository.get_session_cost(session.session_id) is None:
                self.record_session(session)

    def _provider_metrics(
        self,
        project_id: int | None,
        costs: Iterable[GenerationSessionCost],
    ) -> list[GenerationProviderCostEfficiency]:
        sessions = {
            item.session_id: item
            for item in self.repository.list_batch_sessions(
                project_id=project_id,
                limit=100000,
            )
        }
        grouped: dict[tuple[str, str], list[GenerationSessionCost]] = defaultdict(list)
        for cost in costs:
            grouped[(cost.provider, cost.model)].append(cost)
        result: list[GenerationProviderCostEfficiency] = []
        for (provider, model), items in grouped.items():
            related = [sessions[item.session_id] for item in items if item.session_id in sessions]
            total_jobs = sum(item.total_jobs for item in related)
            completed_jobs = sum(item.completed_jobs for item in related)
            total_characters = sum(item.character_count for item in items)
            total_cost = sum(item.effective_cost for item in items)
            retry_characters = sum(item.retry_characters for item in items)
            retry_cost = sum(
                item.retry_characters
                / 1_000_000.0
                * item.price_per_million_characters
                for item in items
            )
            file_rates = [item.files_per_minute for item in related if item.files_per_minute > 0]
            character_rates = [
                item.characters_per_minute
                for item in related
                if item.characters_per_minute > 0
            ]
            result.append(
                GenerationProviderCostEfficiency(
                    provider=provider,
                    model=model,
                    session_count=len(items),
                    total_jobs=total_jobs,
                    completed_jobs=completed_jobs,
                    total_characters=total_characters,
                    retry_characters=retry_characters,
                    total_cost=total_cost,
                    retry_cost=retry_cost,
                    cost_per_file=(total_cost / completed_jobs) if completed_jobs else 0.0,
                    cost_per_million_characters=(
                        total_cost / total_characters * 1_000_000.0
                        if total_characters
                        else 0.0
                    ),
                    average_files_per_minute=self._average(file_rates),
                    average_characters_per_minute=self._average(character_rates),
                    success_rate=self._rate(completed_jobs, total_jobs),
                )
            )
        return sorted(result, key=lambda item: (item.total_cost, item.provider, item.model))

    def _queued_work(self, project_id: int | None) -> tuple[int, int]:
        if self.job_repository is None or project_id is None:
            return 0, 0
        records = self.job_repository.list_by_project(project_id)
        queued = [item for item in records if item.status in {"pending", "running"}]
        return len(queued), sum(len(item.text or "") for item in queued)

    @staticmethod
    def _budget_state(
        *,
        policy: GenerationCostBudgetPolicy,
        budget_usage: dict[str, float],
        projected_monthly: float,
        queue_cost: float,
    ) -> tuple[str, list[str], list[str]]:
        if not policy.enabled:
            return "disabled", [], []
        reasons: list[str] = []
        codes: list[str] = []
        critical = False
        for name, spend in budget_usage.items():
            budget = getattr(policy, f"{name}_budget")
            if budget <= 0:
                continue
            if spend >= 100.0:
                critical = True
                codes.append(f"{name}_budget_exceeded")
                reasons.append(f"{name.title()} budget is {spend:.1f}% consumed.")
            elif spend >= policy.warning_percent:
                codes.append(f"{name}_budget_warning")
                reasons.append(f"{name.title()} budget is {spend:.1f}% consumed.")
        if policy.monthly_budget > 0 and projected_monthly > policy.monthly_budget:
            codes.append("monthly_projection")
            reasons.append(
                f"Projected monthly spend {projected_monthly:.2f} "
                f"{policy.currency} exceeds the {policy.monthly_budget:.2f} budget."
            )
        if policy.max_queue_cost > 0 and queue_cost > policy.max_queue_cost:
            critical = True
            codes.append("queue_cost")
            reasons.append(
                f"Queued work is estimated at {queue_cost:.2f} {policy.currency}, "
                f"above the {policy.max_queue_cost:.2f} limit."
            )
        if not codes:
            return "healthy", reasons, codes
        return ("critical" if critical else "warning"), reasons, codes

    @staticmethod
    def _usage_status(value: float, warning_percent: float) -> str:
        if value <= 0.0:
            return "not_configured"
        if value >= 100.0:
            return "exceeded"
        if value >= warning_percent:
            return "warning"
        return "healthy"

    @staticmethod
    def _costs_between(
        costs: Iterable[GenerationSessionCost],
        start: datetime,
        end: datetime,
    ) -> list[GenerationSessionCost]:
        return [
            item
            for item in costs
            if start <= GenerationCostCapacityService._parse(item.recorded_at) <= end
        ]

    @staticmethod
    def _project_monthly(monthly_spend: float, now: datetime) -> float:
        elapsed_days = now.day - 1 + (
            now.hour * 3600 + now.minute * 60 + now.second
        ) / 86400.0
        elapsed_days = max(1.0, elapsed_days)
        next_month = (now.replace(day=28) + timedelta(days=4)).replace(day=1)
        days_in_month = (next_month - now.replace(day=1)).days
        return monthly_spend / elapsed_days * days_in_month

    @staticmethod
    def _sum_cost(costs: Iterable[GenerationSessionCost]) -> float:
        return sum(item.effective_cost for item in costs)

    @staticmethod
    def _usage(spend: float, budget: float) -> float:
        return spend / budget * 100.0 if budget > 0 else 0.0

    @staticmethod
    def _rate(numerator: int | float, denominator: int | float) -> float:
        return numerator / denominator * 100.0 if denominator else 0.0

    @staticmethod
    def _average(values: Iterable[float]) -> float:
        prepared = list(values)
        return sum(prepared) / len(prepared) if prepared else 0.0

    @staticmethod
    def _median(values: Iterable[float]) -> float:
        prepared = list(values)
        return float(statistics.median(prepared)) if prepared else 0.0

    @staticmethod
    def _optional_number(value: object) -> float | None:
        if value is None or value == "":
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _currency(value: str) -> str:
        prepared = (value or "USD").strip().upper()
        return prepared[:8] or "USD"

    def _now(self) -> datetime:
        return self._aware(self._now_factory())

    @staticmethod
    def _aware(value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse(value: str) -> datetime:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return GenerationCostCapacityService._aware(parsed)
