from __future__ import annotations

from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Callable

from app.models.generation_planning import BatchGenerationPlan, GenerationPlanScenario
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry


class GenerationPlanningService:
    """Build a deterministic decision snapshot before generation starts.

    The service deliberately contains no UI or persistence logic. It combines
    the pricing policy, historical throughput forecast, retry reserve and the
    latest provider quota snapshot into a small immutable plan.
    """

    def __init__(
        self,
        cost_capacity_service=None,
        *,
        now_factory: Callable[[], datetime] | None = None,
        registry: ProviderRegistry | None = None,
    ) -> None:
        self.cost_capacity_service = cost_capacity_service
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))
        self.registry = registry or DEFAULT_PROVIDER_REGISTRY

    def build(
        self,
        *,
        project_id: int | None,
        provider: str,
        model: str,
        files: int,
        characters: int,
        provider_requests: int,
        fallback_duration_seconds: float,
        quota_snapshot: dict[str, int | str | None] | None,
        max_retries: int,
        delay_seconds: float,
    ) -> BatchGenerationPlan:
        files = max(0, int(files))
        characters = max(0, int(characters))
        requests = max(0, int(provider_requests))
        provider_key = str(provider or "").strip().casefold()
        model_key = str(model or "").strip()

        estimated_cost = 0.0
        price_rate = 0.0
        currency = "USD"
        pricing_source = "unavailable"
        policy = None
        forecast = None
        if self.cost_capacity_service is not None:
            estimated_cost, price_rate, currency, pricing_source = self.cost_capacity_service.estimate_cost(
                project_id=project_id,
                provider=provider_key,
                model=model_key,
                characters=characters,
            )
            policy = self.cost_capacity_service.get_policy(project_id)
            forecast = self.cost_capacity_service.capacity_forecast(
                project_id=project_id,
                provider=provider_key,
                model=model_key,
                queued_jobs=files,
                queued_characters=characters,
            )

        base_duration = max(0.0, float(fallback_duration_seconds))
        confidence = "low"
        limiting_factor = "fallback"
        historical_sessions = 0
        completion_at = None
        if forecast is not None:
            base_duration = max(0.0, float(forecast.estimated_duration_seconds))
            confidence = str(forecast.confidence or "low")
            limiting_factor = str(forecast.limiting_factor or "fallback")
            historical_sessions = max(0, int(forecast.historical_session_count))

        # Provider delay is a real part of elapsed time and is not represented
        # in character/file throughput forecasts. Apply it once per gap, then
        # calculate completion from the final elapsed estimate.
        base_duration += max(0.0, float(delay_seconds)) * max(0, requests - 1)
        if files:
            completion_at = (self._aware_now() + timedelta(seconds=base_duration)).isoformat()

        quota_remaining = self._optional_int((quota_snapshot or {}).get("remaining"))
        quota_shortfall = max(0, characters - quota_remaining) if quota_remaining is not None else 0
        quota_usage = None
        if quota_remaining is not None:
            quota_usage = (characters / quota_remaining * 100.0) if quota_remaining > 0 else (100.0 if characters else 0.0)

        max_queue_cost = max(0.0, float(getattr(policy, "max_queue_cost", 0.0) or 0.0))
        budget_usage = (
            estimated_cost / max_queue_cost * 100.0
            if max_queue_cost > 0 and (price_rate > 0 or estimated_cost > 0)
            else None
        )

        expected_retry_percent = min(25, max(0, int(max_retries)) * 5)
        scenario_specs = (("base", "Base", 0), ("expected", "Expected retries", expected_retry_percent), ("stress", "Stress test", 25))
        scenarios = tuple(
            self._scenario(
                key=key,
                label=label,
                retry_percent=retry_percent,
                project_id=project_id,
                provider=provider_key,
                model=model_key,
                files=files,
                characters=characters,
                requests=requests,
                base_duration=base_duration,
                base_cost=estimated_cost,
            )
            for key, label, retry_percent in scenario_specs
        )

        reasons: list[str] = []
        risk = "low"
        if quota_shortfall > 0:
            risk = "high"
            reasons.append(f"Quota is short by {quota_shortfall:,} characters.")
        elif provider_key == "elevenlabs" and quota_remaining is None and characters:
            risk = "medium"
            reasons.append("Provider quota is unknown; refresh the account before starting.")
        elif quota_usage is not None and quota_usage >= 90:
            risk = "medium"
            reasons.append("This batch uses at least 90% of the currently available quota.")

        if max_queue_cost > 0 and estimated_cost > max_queue_cost:
            risk = "high"
            reasons.append(f"Estimated cost exceeds the queue budget limit of {currency} {max_queue_cost:.2f}.")
        elif budget_usage is not None and budget_usage >= 80 and risk != "high":
            risk = "medium"
            reasons.append("Estimated cost uses at least 80% of the queue budget limit.")

        if self.registry.manifest_for(provider_key).remote and price_rate <= 0:
            if risk == "low":
                risk = "medium"
            reasons.append("No pricing rate is configured, so cost is shown as unavailable.")
        if confidence == "low" and files:
            if risk == "low":
                risk = "medium"
            reasons.append("Time estimate has low confidence because there is little usable history.")
        if not reasons:
            reasons.append("Scope, quota, budget and timing checks are within configured limits.")

        return BatchGenerationPlan(
            provider=provider_key,
            model=model_key,
            files=files,
            characters=characters,
            provider_requests=requests,
            estimated_cost=max(0.0, float(estimated_cost)),
            currency=str(currency or "USD").upper(),
            price_per_million_characters=max(0.0, float(price_rate)),
            pricing_source=str(pricing_source or "unavailable"),
            estimated_duration_seconds=base_duration,
            estimated_completion_at=completion_at,
            throughput_confidence=confidence,
            limiting_factor=limiting_factor,
            historical_session_count=historical_sessions,
            quota_remaining=quota_remaining,
            quota_shortfall=quota_shortfall,
            quota_usage_percent=quota_usage,
            max_queue_cost=max_queue_cost,
            budget_usage_percent=budget_usage,
            risk_level=risk,
            reasons=tuple(reasons),
            scenarios=scenarios,
        )

    def _scenario(
        self,
        *,
        key: str,
        label: str,
        retry_percent: int,
        project_id: int | None,
        provider: str,
        model: str,
        files: int,
        characters: int,
        requests: int,
        base_duration: float,
        base_cost: float,
    ) -> GenerationPlanScenario:
        multiplier = 1.0 + max(0, retry_percent) / 100.0
        scenario_characters = round(characters * multiplier)
        scenario_requests = ceil(requests * multiplier)
        scenario_cost = base_cost * multiplier
        if self.cost_capacity_service is not None:
            scenario_cost, _rate, _currency, _source = self.cost_capacity_service.estimate_cost(
                project_id=project_id,
                provider=provider,
                model=model,
                characters=characters,
                retry_characters=max(0, scenario_characters - characters),
            )
        return GenerationPlanScenario(
            key=key,
            label=label,
            retry_reserve_percent=max(0, retry_percent),
            files=files,
            characters=scenario_characters,
            provider_requests=scenario_requests,
            estimated_cost=max(0.0, scenario_cost),
            estimated_duration_seconds=max(0.0, base_duration * multiplier),
        )

    def _aware_now(self) -> datetime:
        value = self._now_factory()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _optional_int(value: object) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return None
