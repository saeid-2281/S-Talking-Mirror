from __future__ import annotations

import csv
import json
import math
import re
import uuid
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.models.api_profile import ApiProfile, ApiProfileFailoverMode
from app.models.domain import AppSettings, TTSJob
from app.models.generation_orchestration import (
    GenerationAdaptiveRoutingPolicy,
    GenerationExecutionPlan,
    GenerationFailoverEvent,
    GenerationOrchestrationPolicy,
    GenerationRoutingDecision,
    GenerationSchedulerEvent,
    GenerationSchedulingPolicy,
    ProviderCircuitSnapshot,
    ProviderCircuitStatus,
    ProviderExecutionCandidate,
    ProviderRoutingMetric,
    ProviderThrottleSnapshot,
    RoutingMode,
    SchedulingMode,
)
from app.models.product_events import ActivityEvent, NotificationRecord
from app.models.retry_policy import FailureAnalysis, FailureCategory
from app.repositories.generation_orchestration_repository import (
    GenerationOrchestrationRepository,
)
from app.services.activity_timeline_service import ActivityTimelineService
from app.services.api_profile_service import ApiProfileService
from app.services.notification_center_service import NotificationCenterService


_FAILOVER_CATEGORIES = {
    FailureCategory.NETWORK,
    FailureCategory.RATE_LIMIT,
    FailureCategory.SERVER,
    FailureCategory.AUTHENTICATION,
    FailureCategory.QUOTA,
}
_FAILURE_OUTCOMES = {"switched", "exhausted", "failed"}
_SUCCESS_OUTCOMES = {"success", "completed"}


class GenerationOrchestrationService:
    """Build executable provider plans and persist routing/failover telemetry."""

    def __init__(
        self,
        repository: GenerationOrchestrationRepository,
        api_profiles: ApiProfileService,
        notification_service: NotificationCenterService | None = None,
        activity_service: ActivityTimelineService | None = None,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.api_profiles = api_profiles
        self.notification_service = notification_service
        self.activity_service = activity_service
        self._now = now_factory or (lambda: datetime.now(timezone.utc))

    def default_policy(self, project_id: int | None) -> GenerationOrchestrationPolicy:
        return GenerationOrchestrationPolicy(
            policy_key="global" if project_id is None else f"project:{project_id}",
            project_id=project_id,
            updated_at=self._now().isoformat(),
        )

    def get_policy(self, project_id: int | None) -> GenerationOrchestrationPolicy:
        return self.repository.get_effective_policy(project_id) or self.default_policy(project_id)

    def save_policy(self, policy: GenerationOrchestrationPolicy) -> GenerationOrchestrationPolicy:
        normalized = replace(
            policy,
            policy_key="global" if policy.project_id is None else f"project:{policy.project_id}",
            failure_threshold=max(1, min(100, int(policy.failure_threshold))),
            circuit_cooldown_seconds=max(0, min(86400, int(policy.circuit_cooldown_seconds))),
            max_switches_per_run=max(0, min(20, int(policy.max_switches_per_run))),
            updated_at=self._now().isoformat(),
        )
        return self.repository.save_policy(normalized)

    def default_routing_policy(
        self,
        project_id: int | None,
    ) -> GenerationAdaptiveRoutingPolicy:
        return GenerationAdaptiveRoutingPolicy(
            policy_key="global" if project_id is None else f"project:{project_id}",
            project_id=project_id,
            updated_at=self._now().isoformat(),
        )

    def get_routing_policy(
        self,
        project_id: int | None,
    ) -> GenerationAdaptiveRoutingPolicy:
        return (
            self.repository.get_effective_routing_policy(project_id)
            or self.default_routing_policy(project_id)
        )

    def save_routing_policy(
        self,
        policy: GenerationAdaptiveRoutingPolicy,
    ) -> GenerationAdaptiveRoutingPolicy:
        try:
            mode = RoutingMode(str(policy.mode))
        except ValueError:
            mode = RoutingMode.PRIORITY
        weights = [
            max(0.0, float(policy.health_weight)),
            max(0.0, float(policy.capacity_weight)),
            max(0.0, float(policy.latency_weight)),
            max(0.0, float(policy.priority_weight)),
        ]
        total = sum(weights)
        if total <= 0:
            weights = [0.45, 0.30, 0.15, 0.10]
            total = 1.0
        normalized = replace(
            policy,
            policy_key="global" if policy.project_id is None else f"project:{policy.project_id}",
            mode=mode,
            health_weight=weights[0] / total,
            capacity_weight=weights[1] / total,
            latency_weight=weights[2] / total,
            priority_weight=weights[3] / total,
            minimum_quota_reserve=max(0, int(policy.minimum_quota_reserve)),
            max_profile_share_percent=max(1, min(100, int(policy.max_profile_share_percent))),
            sample_window=max(5, min(1000, int(policy.sample_window))),
            updated_at=self._now().isoformat(),
        )
        return self.repository.save_routing_policy(normalized)

    def default_scheduling_policy(
        self,
        project_id: int | None,
    ) -> GenerationSchedulingPolicy:
        return GenerationSchedulingPolicy(
            policy_key="global" if project_id is None else f"project:{project_id}",
            project_id=project_id,
            updated_at=self._now().isoformat(),
        )

    def get_scheduling_policy(
        self,
        project_id: int | None,
    ) -> GenerationSchedulingPolicy:
        return (
            self.repository.get_effective_scheduling_policy(project_id)
            or self.default_scheduling_policy(project_id)
        )

    def save_scheduling_policy(
        self,
        policy: GenerationSchedulingPolicy,
    ) -> GenerationSchedulingPolicy:
        try:
            mode = SchedulingMode(str(policy.mode))
        except ValueError:
            mode = SchedulingMode.ADAPTIVE
        minimum = max(1, min(32, int(policy.minimum_concurrency)))
        maximum = max(minimum, min(32, int(policy.maximum_concurrency)))
        initial = max(minimum, min(maximum, int(policy.initial_concurrency)))
        normalized = replace(
            policy,
            policy_key="global" if policy.project_id is None else f"project:{policy.project_id}",
            mode=mode,
            minimum_concurrency=minimum,
            initial_concurrency=initial,
            maximum_concurrency=maximum,
            per_profile_concurrency=max(1, min(maximum, int(policy.per_profile_concurrency))),
            success_window=max(1, min(1000, int(policy.success_window))),
            error_window=max(1, min(1000, int(policy.error_window))),
            increase_step=max(1, min(16, int(policy.increase_step))),
            decrease_factor=max(0.1, min(1.0, float(policy.decrease_factor))),
            rate_limit_cooldown_seconds=max(0, min(86400, int(policy.rate_limit_cooldown_seconds))),
            updated_at=self._now().isoformat(),
        )
        return self.repository.save_scheduling_policy(normalized)

    def build_plan(
        self,
        *,
        project_id: int | None,
        settings: AppSettings,
        jobs: list[TTSJob] | None = None,
    ) -> GenerationExecutionPlan:
        now = self._now()
        policy = self.get_policy(project_id)
        routing_policy = self.get_routing_policy(project_id)
        scheduling_policy = self.get_scheduling_policy(project_id)
        profile_failover = self.api_profiles.failover_settings(settings.provider)
        try:
            mode = ApiProfileFailoverMode(str(settings.api_profile_failover or profile_failover.mode))
        except ValueError:
            mode = ApiProfileFailoverMode.NEVER
        auto_requested = bool(
            policy.enabled
            and policy.auto_failover
            and mode == ApiProfileFailoverMode.AUTO
        )
        adaptive_requested = bool(
            auto_requested
            and routing_policy.enabled
            and routing_policy.mode != RoutingMode.PRIORITY
        )

        profiles = self.api_profiles.ordered_failover_profiles(settings.provider)
        by_id = {profile.profile_id: profile for profile in profiles}
        primary_profile = by_id.get(settings.active_api_profile_id or "")
        if primary_profile is None:
            primary_profile = next((profile for profile in profiles if profile.active), None)

        if primary_profile is not None and primary_profile.has_saved_key:
            primary_candidate = self._candidate(
                project_id,
                self.api_profiles.apply_profile_key(settings, primary_profile.profile_id),
                primary_profile.profile_id,
                primary_profile.display_name,
                primary_profile.priority,
                now,
                profile=primary_profile,
                routing_policy=routing_policy,
            )
        else:
            primary_candidate = self._candidate(
                project_id,
                settings,
                settings.active_api_profile_id,
                "Temporary key" if settings.api_key else "Current provider settings",
                0,
                now,
                routing_policy=routing_policy,
            )

        candidates: list[ProviderExecutionCandidate] = []
        excluded: list[dict[str, str]] = []
        if primary_candidate.circuit_status == ProviderCircuitStatus.OPEN and auto_requested:
            excluded.append({"profile": primary_candidate.profile_name, "reason": "circuit open"})
        elif self._below_quota_reserve(primary_candidate, routing_policy, adaptive_requested):
            excluded.append({"profile": primary_candidate.profile_name, "reason": "quota reserve"})
        else:
            candidates.append(primary_candidate)

        primary_id = primary_candidate.profile_id
        for profile in profiles:
            if profile.profile_id == primary_id:
                continue
            if not profile.enabled:
                excluded.append({"profile": profile.display_name, "reason": "disabled"})
                continue
            if not profile.has_saved_key:
                excluded.append({"profile": profile.display_name, "reason": "no saved credential"})
                continue
            if not profile.is_usable:
                excluded.append({"profile": profile.display_name, "reason": str(profile.status)})
                continue
            candidate = self._candidate(
                project_id,
                self.api_profiles.apply_profile_key(settings, profile.profile_id),
                profile.profile_id,
                profile.display_name,
                profile.priority,
                now,
                profile=profile,
                routing_policy=routing_policy,
            )
            if candidate.circuit_status == ProviderCircuitStatus.OPEN and auto_requested:
                excluded.append({"profile": profile.display_name, "reason": "circuit open"})
                continue
            if self._below_quota_reserve(candidate, routing_policy, adaptive_requested):
                excluded.append({"profile": profile.display_name, "reason": "quota reserve"})
                continue
            candidates.append(candidate)

        if adaptive_requested:
            candidates.sort(key=lambda item: (-item.routing_score, item.priority, item.profile_name))

        max_switches = min(
            max(0, settings.api_profile_failover_max_switches),
            max(0, profile_failover.max_switches_per_run),
            max(0, policy.max_switches_per_run),
        )
        blocked_reason = None
        if auto_requested and not candidates:
            if any(item.get("reason") == "quota reserve" for item in excluded):
                blocked_reason = (
                    "All configured provider accounts are unavailable, have open circuits, "
                    "or are below the quota reserve."
                )
            else:
                blocked_reason = "All configured provider accounts have open circuits or are unavailable."
        enabled = bool(auto_requested and max_switches > 0 and len(candidates) > 1)
        routing_enabled = bool(adaptive_requested and len(candidates) > 1)
        preview_count = len(jobs) if jobs is not None else min(20, max(1, len(candidates) * 4))
        routing_sequence = self._routing_sequence(
            candidates,
            preview_count,
            routing_policy.max_profile_share_percent,
        ) if routing_enabled else ()
        distribution = self._distribution(candidates, routing_sequence, preview_count)
        return GenerationExecutionPlan(
            project_id=project_id,
            provider=settings.provider,
            mode=str(mode),
            enabled=enabled,
            max_switches=max_switches,
            failure_threshold=policy.failure_threshold,
            circuit_cooldown_seconds=policy.circuit_cooldown_seconds,
            sticky_successful_profile=policy.sticky_successful_profile,
            candidates=tuple(candidates),
            excluded=tuple(excluded),
            blocked_reason=blocked_reason,
            routing_enabled=routing_enabled,
            routing_mode=routing_policy.mode,
            max_profile_share_percent=routing_policy.max_profile_share_percent,
            routing_sequence=routing_sequence,
            predicted_distribution=distribution,
            scheduling_enabled=bool(
                scheduling_policy.enabled
                and jobs is not None
                and len(jobs) > 1
            ),
            scheduling_mode=scheduling_policy.mode,
            minimum_concurrency=scheduling_policy.minimum_concurrency,
            initial_concurrency=min(
                scheduling_policy.maximum_concurrency,
                max(scheduling_policy.minimum_concurrency, scheduling_policy.initial_concurrency),
            ),
            maximum_concurrency=scheduling_policy.maximum_concurrency,
            per_profile_concurrency=scheduling_policy.per_profile_concurrency,
            success_window=scheduling_policy.success_window,
            error_window=scheduling_policy.error_window,
            increase_step=scheduling_policy.increase_step,
            decrease_factor=scheduling_policy.decrease_factor,
            rate_limit_cooldown_seconds=scheduling_policy.rate_limit_cooldown_seconds,
        )

    def should_failover(self, analysis: FailureAnalysis) -> bool:
        return analysis.category in _FAILOVER_CATEGORIES

    def record_worker_event(self, payload: dict[str, object]) -> GenerationFailoverEvent:
        now = self._now()
        event = GenerationFailoverEvent(
            event_id=str(payload.get("event_id") or uuid.uuid4().hex),
            project_id=self._optional_int(payload.get("project_id")),
            job_row_number=self._optional_int(payload.get("job_row_number")),
            filename=str(payload.get("filename") or ""),
            provider=str(payload.get("provider") or "unknown"),
            from_profile_id=self._optional_str(payload.get("from_profile_id")),
            from_profile_name=str(payload.get("from_profile_name") or "Current provider"),
            to_profile_id=self._optional_str(payload.get("to_profile_id")),
            to_profile_name=self._optional_str(payload.get("to_profile_name")),
            failure_category=str(payload.get("failure_category") or "unknown"),
            error_code=str(payload.get("error_code") or "unknown"),
            outcome=str(payload.get("outcome") or "unknown"),
            switch_number=max(0, self._optional_int(payload.get("switch_number")) or 0),
            consecutive_failures=max(0, self._optional_int(payload.get("consecutive_failures")) or 0),
            circuit_opened=bool(payload.get("circuit_opened", False)),
            created_at=str(payload.get("created_at") or now.isoformat()),
            metadata=dict(payload.get("metadata") or {}),
        )
        self.repository.add_event(event)
        if event.outcome == "routed":
            self._record_decision(event)
            self._update_metric(event)
            return event
        if event.outcome in _SUCCESS_OUTCOMES or event.outcome in _FAILURE_OUTCOMES:
            self._update_metric(event)
            self._update_circuit(event, now)
        self._publish(event)
        return event

    def record_scheduler_event(
        self,
        payload: dict[str, object],
    ) -> GenerationSchedulerEvent:
        now = self._now()
        project_id = self._optional_int(payload.get("project_id"))
        provider = str(payload.get("provider") or "unknown")
        profile_id = self._optional_str(payload.get("profile_id"))
        profile_name = str(payload.get("profile_name") or "Current provider")
        event_type = str(payload.get("event_type") or "scheduler_update")
        from_concurrency = max(1, self._optional_int(payload.get("from_concurrency")) or 1)
        to_concurrency = max(1, self._optional_int(payload.get("to_concurrency")) or 1)
        created_at = str(payload.get("created_at") or now.isoformat())
        metadata = {
            key: value
            for key, value in dict(payload.get("metadata") or {}).items()
            if key not in {"api_key", "credential", "secret"}
        }
        event = GenerationSchedulerEvent(
            event_id=str(payload.get("event_id") or uuid.uuid4().hex),
            project_id=project_id,
            provider=provider,
            profile_id=profile_id,
            profile_name=profile_name,
            event_type=event_type,
            from_concurrency=from_concurrency,
            to_concurrency=to_concurrency,
            pending_jobs=max(0, self._optional_int(payload.get("pending_jobs")) or 0),
            active_jobs=max(0, self._optional_int(payload.get("active_jobs")) or 0),
            reason=str(payload.get("reason") or ""),
            created_at=created_at,
            metadata=metadata,
        )
        self.repository.add_scheduler_event(event)
        if event_type == "scheduler_started":
            return event
        existing = self.repository.get_throttle_state(
            project_id=project_id,
            provider=provider,
            profile_id=profile_id,
        )
        policy = self.get_scheduling_policy(project_id)
        recent_rate_limits = existing.recent_rate_limits if existing else 0
        cooldown_until = existing.cooldown_until if existing else None
        last_rate_limit_at = existing.last_rate_limit_at if existing else None
        last_recovered_at = existing.last_recovered_at if existing else None
        if event_type == "rate_limited":
            recent_rate_limits += 1
            cooldown_until = str(
                metadata.get("cooldown_until")
                or (now + timedelta(seconds=policy.rate_limit_cooldown_seconds)).isoformat()
            )
            last_rate_limit_at = created_at
        elif event_type in {"recovered", "concurrency_increased"}:
            recent_rate_limits = max(0, recent_rate_limits - 1)
            cooldown_until = None
            last_recovered_at = created_at
        elif event_type == "backpressure" and metadata.get("cooldown_until"):
            cooldown_until = str(metadata["cooldown_until"])
        snapshot = ProviderThrottleSnapshot(
            throttle_key=self.repository.throttle_key(project_id, provider, profile_id),
            project_id=project_id,
            provider=provider,
            profile_id=profile_id,
            profile_name=profile_name,
            current_concurrency=to_concurrency,
            recent_rate_limits=recent_rate_limits,
            cooldown_until=cooldown_until,
            last_rate_limit_at=last_rate_limit_at,
            last_recovered_at=last_recovered_at,
            updated_at=created_at,
        )
        self.repository.save_throttle_state(snapshot)
        if self.activity_service is not None and event_type != "scheduler_started":
            self.activity_service.record(
                ActivityEvent(
                    event_id=f"scheduler-{event.event_id}",
                    project_id=project_id,
                    category="generation_scheduler",
                    title="Generation scheduler adjusted",
                    message=(
                        f"{profile_name}: concurrency {from_concurrency} → {to_concurrency} "
                        f"({event.reason or event_type})."
                    ),
                    created_at=created_at,
                    metadata={
                        "provider": provider,
                        "profile_id": profile_id,
                        "event_type": event_type,
                    },
                )
            )
        return event

    def reset_circuit(
        self,
        *,
        project_id: int | None,
        provider: str,
        profile_id: str | None,
        profile_name: str = "",
    ) -> ProviderCircuitSnapshot:
        now = self._now().isoformat()
        snapshot = ProviderCircuitSnapshot(
            state_key=self.repository.state_key(project_id, provider, profile_id),
            project_id=project_id,
            provider=provider,
            profile_id=profile_id,
            profile_name=profile_name,
            status=ProviderCircuitStatus.CLOSED,
            updated_at=now,
        )
        return self.repository.save_circuit(snapshot)

    def export_report(
        self,
        directory: Path,
        *,
        project_id: int | None = None,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        directory.mkdir(parents=True, exist_ok=True)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "project"
        json_path = directory / f"orchestration-{safe}-{stamp}.json"
        csv_path = directory / f"orchestration-{safe}-{stamp}.csv"
        policy = self.get_policy(project_id)
        routing_policy = self.get_routing_policy(project_id)
        scheduling_policy = self.get_scheduling_policy(project_id)
        throttle_states = self.repository.list_throttle_states(project_id=project_id)
        scheduler_events = self.repository.list_scheduler_events(project_id=project_id)
        circuits = self.repository.list_circuits(project_id=project_id)
        metrics = self.repository.list_routing_metrics(project_id=project_id)
        decisions = self.repository.list_decisions(project_id=project_id)
        events = self.repository.list_events(project_id=project_id)
        payload = {
            "created_at": self._now().isoformat(),
            "project": project_name,
            "policy": policy.__dict__,
            "routing_policy": self._jsonable(routing_policy.__dict__),
            "scheduling_policy": self._jsonable(scheduling_policy.__dict__),
            "throttle_states": [self._jsonable(item.__dict__) for item in throttle_states],
            "scheduler_events": [self._jsonable(item.__dict__) for item in scheduler_events],
            "circuits": [self._jsonable(item.__dict__) for item in circuits],
            "routing_metrics": [self._jsonable(item.__dict__) for item in metrics],
            "routing_decisions": [self._jsonable(item.__dict__) for item in decisions],
            "events": [self._jsonable(item.__dict__) for item in events],
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        fields = [
            "record_type",
            "created_at",
            "filename",
            "provider",
            "from_profile_name",
            "to_profile_name",
            "failure_category",
            "error_code",
            "outcome",
            "switch_number",
            "consecutive_failures",
            "circuit_opened",
            "routing_mode",
            "routing_score",
            "routing_weight",
            "characters",
            "attempts",
            "successes",
            "failures",
            "health_score",
            "ewma_latency_seconds",
            "event_type",
            "from_concurrency",
            "to_concurrency",
            "pending_jobs",
            "active_jobs",
            "reason",
            "cooldown_until",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for event in events:
                writer.writerow(
                    {
                        "record_type": "provider_event",
                        "created_at": event.created_at,
                        "filename": event.filename,
                        "provider": event.provider,
                        "from_profile_name": event.from_profile_name,
                        "to_profile_name": event.to_profile_name,
                        "failure_category": event.failure_category,
                        "error_code": event.error_code,
                        "outcome": event.outcome,
                        "switch_number": event.switch_number,
                        "consecutive_failures": event.consecutive_failures,
                        "circuit_opened": event.circuit_opened,
                    }
                )
            for decision in decisions:
                writer.writerow(
                    {
                        "record_type": "routing_decision",
                        "created_at": decision.created_at,
                        "filename": decision.filename,
                        "provider": decision.provider,
                        "from_profile_name": decision.profile_name,
                        "routing_mode": str(decision.routing_mode),
                        "routing_score": decision.routing_score,
                        "routing_weight": decision.routing_weight,
                        "characters": decision.estimated_characters,
                    }
                )
            for event in scheduler_events:
                writer.writerow(
                    {
                        "record_type": "scheduler_event",
                        "created_at": event.created_at,
                        "provider": event.provider,
                        "from_profile_name": event.profile_name,
                        "event_type": event.event_type,
                        "from_concurrency": event.from_concurrency,
                        "to_concurrency": event.to_concurrency,
                        "pending_jobs": event.pending_jobs,
                        "active_jobs": event.active_jobs,
                        "reason": event.reason,
                    }
                )
            for state in throttle_states:
                writer.writerow(
                    {
                        "record_type": "throttle_state",
                        "created_at": state.updated_at,
                        "provider": state.provider,
                        "from_profile_name": state.profile_name,
                        "to_concurrency": state.current_concurrency,
                        "failures": state.recent_rate_limits,
                        "cooldown_until": state.cooldown_until,
                    }
                )
            for metric in metrics:
                writer.writerow(
                    {
                        "record_type": "routing_metric",
                        "created_at": metric.updated_at,
                        "provider": metric.provider,
                        "from_profile_name": metric.profile_name,
                        "attempts": metric.attempts,
                        "successes": metric.successes,
                        "failures": metric.failures,
                        "health_score": metric.health_score,
                        "ewma_latency_seconds": metric.ewma_latency_seconds,
                        "characters": metric.total_characters,
                    }
                )
        return json_path, csv_path

    def _candidate(
        self,
        project_id: int | None,
        settings: AppSettings,
        profile_id: str | None,
        profile_name: str,
        priority: int,
        now: datetime,
        *,
        profile: ApiProfile | None = None,
        routing_policy: GenerationAdaptiveRoutingPolicy,
    ) -> ProviderExecutionCandidate:
        circuit = self.repository.get_circuit(
            project_id=project_id,
            provider=settings.provider,
            profile_id=profile_id,
        )
        metric = self.repository.get_routing_metric(
            project_id=project_id,
            provider=settings.provider,
            profile_id=profile_id,
        )
        status = ProviderCircuitStatus.CLOSED
        failures = 0
        retry_after = None
        if circuit is not None:
            status = circuit.status
            failures = circuit.consecutive_failures
            retry_after = circuit.retry_after
            if status == ProviderCircuitStatus.OPEN and retry_after:
                retry_at = self._parse_time(retry_after)
                if retry_at is not None and retry_at <= now:
                    status = ProviderCircuitStatus.HALF_OPEN
        remaining = profile.remaining_characters if profile is not None else None
        limit = profile.character_limit if profile is not None else None
        capacity_ratio = None
        if remaining is not None and limit and limit > 0:
            capacity_ratio = max(0.0, min(1.0, remaining / limit))
        success_rate = metric.success_rate if metric is not None else 0.85
        latency = metric.ewma_latency_seconds if metric is not None else None
        score, weight = self._routing_score(
            routing_policy,
            priority=priority,
            circuit_status=status,
            capacity_ratio=capacity_ratio,
            success_rate=success_rate,
            latency=latency,
            profile=profile,
        )
        return ProviderExecutionCandidate(
            candidate_id=f"{settings.provider}:{profile_id or 'temporary'}",
            provider=settings.provider,
            profile_id=profile_id,
            profile_name=profile_name,
            settings=settings,
            priority=priority,
            circuit_status=status,
            consecutive_failures=failures,
            retry_after=retry_after,
            remaining_characters=remaining,
            character_limit=limit,
            capacity_ratio=capacity_ratio,
            historical_success_rate=success_rate,
            ewma_latency_seconds=latency,
            routing_score=score,
            routing_weight=weight,
        )

    @staticmethod
    def _below_quota_reserve(
        candidate: ProviderExecutionCandidate,
        policy: GenerationAdaptiveRoutingPolicy,
        adaptive_requested: bool,
    ) -> bool:
        return bool(
            adaptive_requested
            and candidate.remaining_characters is not None
            and candidate.remaining_characters < policy.minimum_quota_reserve
        )

    @staticmethod
    def _routing_score(
        policy: GenerationAdaptiveRoutingPolicy,
        *,
        priority: int,
        circuit_status: ProviderCircuitStatus,
        capacity_ratio: float | None,
        success_rate: float,
        latency: float | None,
        profile: ApiProfile | None,
    ) -> tuple[float, int]:
        if policy.mode == RoutingMode.WEIGHTED:
            raw = None if profile is None else profile.metadata.get("routing_weight")
            try:
                weight = max(1, min(100, int(raw))) if raw is not None else max(1, 101 - priority)
            except (TypeError, ValueError):
                weight = max(1, 101 - priority)
            return float(weight), weight
        health = max(0.0, min(1.0, success_rate))
        capacity = 0.5 if capacity_ratio is None else capacity_ratio
        latency_score = 0.5 if latency is None else 1.0 / (1.0 + max(0.0, latency))
        priority_score = 1.0 / (1.0 + max(0, priority) / 10.0)
        score = 100.0 * (
            policy.health_weight * health
            + policy.capacity_weight * capacity
            + policy.latency_weight * latency_score
            + policy.priority_weight * priority_score
        )
        if circuit_status == ProviderCircuitStatus.HALF_OPEN:
            score *= 0.25
        score = max(1.0, min(100.0, score))
        return round(score, 3), max(1, int(round(score)))

    @staticmethod
    def _routing_sequence(
        candidates: list[ProviderExecutionCandidate],
        job_count: int,
        max_share_percent: int,
    ) -> tuple[str, ...]:
        if job_count <= 0 or not candidates:
            return ()
        if len(candidates) == 1:
            return tuple(candidates[0].candidate_id for _ in range(job_count))
        minimum_viable = math.ceil(job_count / len(candidates))
        requested_cap = math.ceil(job_count * max_share_percent / 100.0)
        cap = max(minimum_viable, requested_cap)
        current = {item.candidate_id: 0.0 for item in candidates}
        counts = {item.candidate_id: 0 for item in candidates}
        weights = {item.candidate_id: max(1, item.routing_weight) for item in candidates}
        total_weight = sum(weights.values())
        sequence: list[str] = []
        for _ in range(job_count):
            eligible = [item for item in candidates if counts[item.candidate_id] < cap]
            if not eligible:
                eligible = list(candidates)
            for item in eligible:
                current[item.candidate_id] += weights[item.candidate_id]
            selected = max(
                eligible,
                key=lambda item: (
                    current[item.candidate_id],
                    -counts[item.candidate_id],
                    -item.priority,
                    item.profile_name,
                ),
            )
            sequence.append(selected.candidate_id)
            counts[selected.candidate_id] += 1
            current[selected.candidate_id] -= total_weight
        return tuple(sequence)

    @staticmethod
    def _distribution(
        candidates: list[ProviderExecutionCandidate],
        sequence: tuple[str, ...],
        job_count: int,
    ) -> tuple[dict[str, object], ...]:
        counts = {item.candidate_id: sequence.count(item.candidate_id) for item in candidates}
        return tuple(
            {
                "candidate_id": item.candidate_id,
                "profile_id": item.profile_id,
                "profile_name": item.profile_name,
                "jobs": counts[item.candidate_id],
                "share_percent": round(
                    100.0 * counts[item.candidate_id] / job_count,
                    1,
                ) if job_count else 0.0,
                "routing_score": item.routing_score,
                "routing_weight": item.routing_weight,
            }
            for item in candidates
        )

    def _record_decision(self, event: GenerationFailoverEvent) -> None:
        metadata = event.metadata
        try:
            mode = RoutingMode(str(metadata.get("routing_mode") or "priority"))
        except ValueError:
            mode = RoutingMode.PRIORITY
        decision = GenerationRoutingDecision(
            decision_id=str(metadata.get("decision_id") or event.event_id),
            project_id=event.project_id,
            job_row_number=event.job_row_number,
            filename=event.filename,
            provider=event.provider,
            profile_id=event.from_profile_id,
            profile_name=event.from_profile_name,
            routing_mode=mode,
            routing_score=self._optional_float(metadata.get("routing_score")) or 0.0,
            routing_weight=max(1, self._optional_int(metadata.get("routing_weight")) or 1),
            estimated_characters=max(0, self._optional_int(metadata.get("characters")) or 0),
            reason=str(metadata.get("reason") or "scheduled routing"),
            created_at=event.created_at,
            metadata={
                key: value
                for key, value in metadata.items()
                if key not in {"api_key", "credential", "secret"}
            },
        )
        self.repository.add_decision(decision)

    def _update_metric(self, event: GenerationFailoverEvent) -> None:
        existing = self.repository.get_routing_metric(
            project_id=event.project_id,
            provider=event.provider,
            profile_id=event.from_profile_id,
        )
        metric = existing or ProviderRoutingMetric(
            metric_key=self.repository.metric_key(
                event.project_id,
                event.provider,
                event.from_profile_id,
            ),
            project_id=event.project_id,
            provider=event.provider,
            profile_id=event.from_profile_id,
            profile_name=event.from_profile_name,
            updated_at=event.created_at,
        )
        if event.outcome == "routed":
            self.repository.save_routing_metric(
                replace(metric, last_selected_at=event.created_at, updated_at=event.created_at)
            )
            return
        latency = max(0.0, self._optional_float(event.metadata.get("duration_seconds")) or 0.0)
        characters = max(0, self._optional_int(event.metadata.get("characters")) or 0)
        success = event.outcome in _SUCCESS_OUTCOMES
        attempts = metric.attempts + 1
        successes = metric.successes + int(success)
        failures = metric.failures + int(not success)
        routing_policy = self.get_routing_policy(event.project_id)
        alpha = 2.0 / (routing_policy.sample_window + 1.0)
        ewma = latency if metric.ewma_latency_seconds is None else (
            alpha * latency + (1.0 - alpha) * metric.ewma_latency_seconds
        )
        success_rate = successes / attempts
        latency_factor = 1.0 / (1.0 + ewma)
        health = max(0.0, min(100.0, 100.0 * (0.80 * success_rate + 0.20 * latency_factor)))
        self.repository.save_routing_metric(
            replace(
                metric,
                attempts=attempts,
                successes=successes,
                failures=failures,
                total_latency_seconds=metric.total_latency_seconds + latency,
                total_characters=metric.total_characters + characters,
                ewma_latency_seconds=ewma,
                health_score=health,
                last_selected_at=event.created_at,
                last_success_at=event.created_at if success else metric.last_success_at,
                last_failure_at=event.created_at if not success else metric.last_failure_at,
                updated_at=event.created_at,
            )
        )

    def _update_circuit(self, event: GenerationFailoverEvent, now: datetime) -> None:
        profile_id = event.from_profile_id
        existing = self.repository.get_circuit(
            project_id=event.project_id,
            provider=event.provider,
            profile_id=profile_id,
        )
        if event.outcome in _SUCCESS_OUTCOMES:
            snapshot = ProviderCircuitSnapshot(
                state_key=self.repository.state_key(event.project_id, event.provider, profile_id),
                project_id=event.project_id,
                provider=event.provider,
                profile_id=profile_id,
                profile_name=event.from_profile_name,
                status=ProviderCircuitStatus.CLOSED,
                consecutive_failures=0,
                last_success_at=event.created_at,
                updated_at=event.created_at,
            )
        else:
            policy = self.get_policy(event.project_id)
            failures = max(event.consecutive_failures, (existing.consecutive_failures if existing else 0) + 1)
            opened = event.circuit_opened or failures >= policy.failure_threshold
            retry_after = (
                now + timedelta(seconds=policy.circuit_cooldown_seconds)
            ).isoformat() if opened else None
            snapshot = ProviderCircuitSnapshot(
                state_key=self.repository.state_key(event.project_id, event.provider, profile_id),
                project_id=event.project_id,
                provider=event.provider,
                profile_id=profile_id,
                profile_name=event.from_profile_name,
                status=ProviderCircuitStatus.OPEN if opened else ProviderCircuitStatus.CLOSED,
                consecutive_failures=failures,
                opened_at=event.created_at if opened else (existing.opened_at if existing else None),
                retry_after=retry_after,
                last_failure_category=event.failure_category,
                last_failure_code=event.error_code,
                last_failure_at=event.created_at,
                last_success_at=existing.last_success_at if existing else None,
                updated_at=event.created_at,
            )
        self.repository.save_circuit(snapshot)

    def _publish(self, event: GenerationFailoverEvent) -> None:
        if event.outcome in _SUCCESS_OUTCOMES:
            return
        if self.activity_service is not None:
            target = f" → {event.to_profile_name}" if event.to_profile_name else ""
            self.activity_service.record(
                ActivityEvent(
                    event_id=f"orchestration-{event.event_id}",
                    project_id=event.project_id,
                    category="generation_orchestration",
                    title="Provider failover" if event.outcome == "switched" else "Provider circuit update",
                    message=(
                        f"{event.filename}: {event.from_profile_name}{target} "
                        f"({event.failure_category}/{event.error_code}, {event.outcome})."
                    ),
                    created_at=event.created_at,
                    metadata={
                        "provider": event.provider,
                        "from_profile_id": event.from_profile_id,
                        "to_profile_id": event.to_profile_id,
                        "circuit_opened": event.circuit_opened,
                    },
                )
            )
        if event.circuit_opened and self.notification_service is not None:
            policy = self.get_policy(event.project_id)
            if policy.notify_on_circuit_open:
                self.notification_service.publish(
                    NotificationRecord(
                        notification_id=f"provider-circuit-{event.event_id}",
                        severity="warning",
                        title="Provider account circuit opened",
                        message=(
                            f"{event.from_profile_name} was temporarily removed from routing "
                            f"after {event.consecutive_failures} eligible failure(s)."
                        ),
                        created_at=event.created_at,
                        action_label="Open orchestration",
                        action_payload="generation-orchestration",
                    )
                )

    @staticmethod
    def _parse_time(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    @staticmethod
    def _optional_int(value: object) -> int | None:
        try:
            return int(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_float(value: object) -> float | None:
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _optional_str(value: object) -> str | None:
        return str(value) if value not in (None, "") else None

    @staticmethod
    def _jsonable(value: dict[str, object]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in value.items():
            result[key] = str(item) if isinstance(item, (ProviderCircuitStatus, RoutingMode)) else item
        return result
