from __future__ import annotations

import json
from dataclasses import replace

from app.database.connection import Database
from app.models.generation_orchestration import (
    GenerationAdaptiveRoutingPolicy,
    GenerationFailoverEvent,
    GenerationOrchestrationPolicy,
    GenerationRoutingDecision,
    GenerationSchedulerEvent,
    GenerationSchedulingPolicy,
    ProviderCircuitSnapshot,
    ProviderCircuitStatus,
    ProviderRoutingMetric,
    ProviderThrottleSnapshot,
    RoutingMode,
    SchedulingMode,
)


class GenerationOrchestrationRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def save_policy(self, policy: GenerationOrchestrationPolicy) -> GenerationOrchestrationPolicy:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_orchestration_policies(
                    policy_key, project_id, enabled, auto_failover,
                    failure_threshold, circuit_cooldown_seconds,
                    max_switches_per_run, sticky_successful_profile,
                    notify_on_circuit_open, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    enabled = excluded.enabled,
                    auto_failover = excluded.auto_failover,
                    failure_threshold = excluded.failure_threshold,
                    circuit_cooldown_seconds = excluded.circuit_cooldown_seconds,
                    max_switches_per_run = excluded.max_switches_per_run,
                    sticky_successful_profile = excluded.sticky_successful_profile,
                    notify_on_circuit_open = excluded.notify_on_circuit_open,
                    updated_at = excluded.updated_at
                """,
                (
                    policy.policy_key,
                    policy.project_id,
                    int(policy.enabled),
                    int(policy.auto_failover),
                    policy.failure_threshold,
                    policy.circuit_cooldown_seconds,
                    policy.max_switches_per_run,
                    int(policy.sticky_successful_profile),
                    int(policy.notify_on_circuit_open),
                    policy.updated_at,
                ),
            )
        return policy

    def get_policy(self, project_id: int | None) -> GenerationOrchestrationPolicy | None:
        key = "global" if project_id is None else f"project:{project_id}"
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_orchestration_policies WHERE policy_key = ?",
                (key,),
            ).fetchone()
        return self._policy(row) if row is not None else None

    def get_effective_policy(self, project_id: int | None) -> GenerationOrchestrationPolicy | None:
        exact = self.get_policy(project_id)
        if exact is not None or project_id is None:
            return exact
        global_policy = self.get_policy(None)
        if global_policy is None:
            return None
        return replace(global_policy, policy_key=f"project:{project_id}", project_id=project_id)

    def save_routing_policy(
        self,
        policy: GenerationAdaptiveRoutingPolicy,
    ) -> GenerationAdaptiveRoutingPolicy:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_adaptive_routing_policies(
                    policy_key, project_id, enabled, mode, health_weight,
                    capacity_weight, latency_weight, priority_weight,
                    minimum_quota_reserve, max_profile_share_percent,
                    sample_window, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    enabled = excluded.enabled,
                    mode = excluded.mode,
                    health_weight = excluded.health_weight,
                    capacity_weight = excluded.capacity_weight,
                    latency_weight = excluded.latency_weight,
                    priority_weight = excluded.priority_weight,
                    minimum_quota_reserve = excluded.minimum_quota_reserve,
                    max_profile_share_percent = excluded.max_profile_share_percent,
                    sample_window = excluded.sample_window,
                    updated_at = excluded.updated_at
                """,
                (
                    policy.policy_key,
                    policy.project_id,
                    int(policy.enabled),
                    str(policy.mode),
                    policy.health_weight,
                    policy.capacity_weight,
                    policy.latency_weight,
                    policy.priority_weight,
                    policy.minimum_quota_reserve,
                    policy.max_profile_share_percent,
                    policy.sample_window,
                    policy.updated_at,
                ),
            )
        return policy

    def get_routing_policy(
        self,
        project_id: int | None,
    ) -> GenerationAdaptiveRoutingPolicy | None:
        key = "global" if project_id is None else f"project:{project_id}"
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_adaptive_routing_policies WHERE policy_key = ?",
                (key,),
            ).fetchone()
        return self._routing_policy(row) if row is not None else None

    def get_effective_routing_policy(
        self,
        project_id: int | None,
    ) -> GenerationAdaptiveRoutingPolicy | None:
        exact = self.get_routing_policy(project_id)
        if exact is not None or project_id is None:
            return exact
        global_policy = self.get_routing_policy(None)
        if global_policy is None:
            return None
        return replace(global_policy, policy_key=f"project:{project_id}", project_id=project_id)

    def save_circuit(self, snapshot: ProviderCircuitSnapshot) -> ProviderCircuitSnapshot:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_provider_circuit_states(
                    state_key, project_id, provider, profile_id, profile_name,
                    status, consecutive_failures, opened_at, retry_after,
                    last_failure_category, last_failure_code, last_failure_at,
                    last_success_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(state_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    provider = excluded.provider,
                    profile_id = excluded.profile_id,
                    profile_name = excluded.profile_name,
                    status = excluded.status,
                    consecutive_failures = excluded.consecutive_failures,
                    opened_at = excluded.opened_at,
                    retry_after = excluded.retry_after,
                    last_failure_category = excluded.last_failure_category,
                    last_failure_code = excluded.last_failure_code,
                    last_failure_at = excluded.last_failure_at,
                    last_success_at = excluded.last_success_at,
                    updated_at = excluded.updated_at
                """,
                (
                    snapshot.state_key,
                    snapshot.project_id,
                    snapshot.provider,
                    snapshot.profile_id,
                    snapshot.profile_name,
                    str(snapshot.status),
                    snapshot.consecutive_failures,
                    snapshot.opened_at,
                    snapshot.retry_after,
                    snapshot.last_failure_category,
                    snapshot.last_failure_code,
                    snapshot.last_failure_at,
                    snapshot.last_success_at,
                    snapshot.updated_at,
                ),
            )
        return snapshot

    def get_circuit(
        self,
        *,
        project_id: int | None,
        provider: str,
        profile_id: str | None,
    ) -> ProviderCircuitSnapshot | None:
        key = self.state_key(project_id, provider, profile_id)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_provider_circuit_states WHERE state_key = ?",
                (key,),
            ).fetchone()
        return self._circuit(row) if row is not None else None

    def list_circuits(
        self,
        *,
        project_id: int | None = None,
        provider: str | None = None,
    ) -> list[ProviderCircuitSnapshot]:
        clauses: list[str] = []
        params: list[object] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_provider_circuit_states {where} "
                "ORDER BY provider, profile_name",
                tuple(params),
            ).fetchall()
        return [self._circuit(row) for row in rows]

    def save_routing_metric(self, metric: ProviderRoutingMetric) -> ProviderRoutingMetric:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_provider_routing_metrics(
                    metric_key, project_id, provider, profile_id, profile_name,
                    attempts, successes, failures, total_latency_seconds,
                    total_characters, ewma_latency_seconds, health_score,
                    last_selected_at, last_success_at, last_failure_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(metric_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    provider = excluded.provider,
                    profile_id = excluded.profile_id,
                    profile_name = excluded.profile_name,
                    attempts = excluded.attempts,
                    successes = excluded.successes,
                    failures = excluded.failures,
                    total_latency_seconds = excluded.total_latency_seconds,
                    total_characters = excluded.total_characters,
                    ewma_latency_seconds = excluded.ewma_latency_seconds,
                    health_score = excluded.health_score,
                    last_selected_at = excluded.last_selected_at,
                    last_success_at = excluded.last_success_at,
                    last_failure_at = excluded.last_failure_at,
                    updated_at = excluded.updated_at
                """,
                (
                    metric.metric_key,
                    metric.project_id,
                    metric.provider,
                    metric.profile_id,
                    metric.profile_name,
                    metric.attempts,
                    metric.successes,
                    metric.failures,
                    metric.total_latency_seconds,
                    metric.total_characters,
                    metric.ewma_latency_seconds,
                    metric.health_score,
                    metric.last_selected_at,
                    metric.last_success_at,
                    metric.last_failure_at,
                    metric.updated_at,
                ),
            )
        return metric

    def get_routing_metric(
        self,
        *,
        project_id: int | None,
        provider: str,
        profile_id: str | None,
    ) -> ProviderRoutingMetric | None:
        key = self.metric_key(project_id, provider, profile_id)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_provider_routing_metrics WHERE metric_key = ?",
                (key,),
            ).fetchone()
        return self._routing_metric(row) if row is not None else None

    def list_routing_metrics(
        self,
        *,
        project_id: int | None = None,
        provider: str | None = None,
    ) -> list[ProviderRoutingMetric]:
        clauses: list[str] = []
        params: list[object] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_provider_routing_metrics {where} "
                "ORDER BY health_score DESC, profile_name",
                tuple(params),
            ).fetchall()
        return [self._routing_metric(row) for row in rows]

    def add_decision(self, decision: GenerationRoutingDecision) -> GenerationRoutingDecision:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO generation_routing_decisions(
                    decision_id, project_id, job_row_number, filename, provider,
                    profile_id, profile_name, routing_mode, routing_score,
                    routing_weight, estimated_characters, reason, created_at,
                    metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision.decision_id,
                    decision.project_id,
                    decision.job_row_number,
                    decision.filename,
                    decision.provider,
                    decision.profile_id,
                    decision.profile_name,
                    str(decision.routing_mode),
                    decision.routing_score,
                    decision.routing_weight,
                    decision.estimated_characters,
                    decision.reason,
                    decision.created_at,
                    json.dumps(decision.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
        return decision

    def list_decisions(
        self,
        *,
        project_id: int | None = None,
        limit: int = 500,
    ) -> list[GenerationRoutingDecision]:
        where = "WHERE project_id = ?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (project_id, max(1, limit)) if project_id is not None else (max(1, limit),)
        )
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_routing_decisions {where} "
                "ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._decision(row) for row in rows]

    def add_event(self, event: GenerationFailoverEvent) -> GenerationFailoverEvent:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO generation_failover_events(
                    event_id, project_id, job_row_number, filename, provider,
                    from_profile_id, from_profile_name, to_profile_id,
                    to_profile_name, failure_category, error_code, outcome,
                    switch_number, consecutive_failures, circuit_opened,
                    created_at, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.project_id,
                    event.job_row_number,
                    event.filename,
                    event.provider,
                    event.from_profile_id,
                    event.from_profile_name,
                    event.to_profile_id,
                    event.to_profile_name,
                    event.failure_category,
                    event.error_code,
                    event.outcome,
                    event.switch_number,
                    event.consecutive_failures,
                    int(event.circuit_opened),
                    event.created_at,
                    json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
        return event

    def list_events(
        self,
        *,
        project_id: int | None = None,
        limit: int = 500,
    ) -> list[GenerationFailoverEvent]:
        where = "WHERE project_id = ?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (project_id, max(1, limit)) if project_id is not None else (max(1, limit),)
        )
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_failover_events {where} "
                "ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._event(row) for row in rows]

    def save_scheduling_policy(
        self,
        policy: GenerationSchedulingPolicy,
    ) -> GenerationSchedulingPolicy:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_scheduling_policies(
                    policy_key, project_id, enabled, mode, minimum_concurrency,
                    initial_concurrency, maximum_concurrency, per_profile_concurrency,
                    success_window, error_window, increase_step, decrease_factor,
                    rate_limit_cooldown_seconds, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(policy_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    enabled = excluded.enabled,
                    mode = excluded.mode,
                    minimum_concurrency = excluded.minimum_concurrency,
                    initial_concurrency = excluded.initial_concurrency,
                    maximum_concurrency = excluded.maximum_concurrency,
                    per_profile_concurrency = excluded.per_profile_concurrency,
                    success_window = excluded.success_window,
                    error_window = excluded.error_window,
                    increase_step = excluded.increase_step,
                    decrease_factor = excluded.decrease_factor,
                    rate_limit_cooldown_seconds = excluded.rate_limit_cooldown_seconds,
                    updated_at = excluded.updated_at
                """,
                (
                    policy.policy_key,
                    policy.project_id,
                    int(policy.enabled),
                    str(policy.mode),
                    policy.minimum_concurrency,
                    policy.initial_concurrency,
                    policy.maximum_concurrency,
                    policy.per_profile_concurrency,
                    policy.success_window,
                    policy.error_window,
                    policy.increase_step,
                    policy.decrease_factor,
                    policy.rate_limit_cooldown_seconds,
                    policy.updated_at,
                ),
            )
        return policy

    def get_scheduling_policy(
        self,
        project_id: int | None,
    ) -> GenerationSchedulingPolicy | None:
        key = "global" if project_id is None else f"project:{project_id}"
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_scheduling_policies WHERE policy_key = ?",
                (key,),
            ).fetchone()
        return self._scheduling_policy(row) if row is not None else None

    def get_effective_scheduling_policy(
        self,
        project_id: int | None,
    ) -> GenerationSchedulingPolicy | None:
        exact = self.get_scheduling_policy(project_id)
        if exact is not None or project_id is None:
            return exact
        global_policy = self.get_scheduling_policy(None)
        if global_policy is None:
            return None
        return replace(global_policy, policy_key=f"project:{project_id}", project_id=project_id)

    def save_throttle_state(
        self,
        snapshot: ProviderThrottleSnapshot,
    ) -> ProviderThrottleSnapshot:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO generation_provider_throttle_states(
                    throttle_key, project_id, provider, profile_id, profile_name,
                    current_concurrency, recent_rate_limits, cooldown_until,
                    last_rate_limit_at, last_recovered_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(throttle_key) DO UPDATE SET
                    project_id = excluded.project_id,
                    provider = excluded.provider,
                    profile_id = excluded.profile_id,
                    profile_name = excluded.profile_name,
                    current_concurrency = excluded.current_concurrency,
                    recent_rate_limits = excluded.recent_rate_limits,
                    cooldown_until = excluded.cooldown_until,
                    last_rate_limit_at = excluded.last_rate_limit_at,
                    last_recovered_at = excluded.last_recovered_at,
                    updated_at = excluded.updated_at
                """,
                (
                    snapshot.throttle_key,
                    snapshot.project_id,
                    snapshot.provider,
                    snapshot.profile_id,
                    snapshot.profile_name,
                    snapshot.current_concurrency,
                    snapshot.recent_rate_limits,
                    snapshot.cooldown_until,
                    snapshot.last_rate_limit_at,
                    snapshot.last_recovered_at,
                    snapshot.updated_at,
                ),
            )
        return snapshot

    def get_throttle_state(
        self,
        *,
        project_id: int | None,
        provider: str,
        profile_id: str | None,
    ) -> ProviderThrottleSnapshot | None:
        key = self.throttle_key(project_id, provider, profile_id)
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM generation_provider_throttle_states WHERE throttle_key = ?",
                (key,),
            ).fetchone()
        return self._throttle_state(row) if row is not None else None

    def list_throttle_states(
        self,
        *,
        project_id: int | None = None,
        provider: str | None = None,
    ) -> list[ProviderThrottleSnapshot]:
        clauses: list[str] = []
        params: list[object] = []
        if project_id is not None:
            clauses.append("project_id = ?")
            params.append(project_id)
        if provider:
            clauses.append("provider = ?")
            params.append(provider)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_provider_throttle_states {where} "
                "ORDER BY provider, profile_name",
                tuple(params),
            ).fetchall()
        return [self._throttle_state(row) for row in rows]

    def add_scheduler_event(
        self,
        event: GenerationSchedulerEvent,
    ) -> GenerationSchedulerEvent:
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO generation_scheduler_events(
                    event_id, project_id, provider, profile_id, profile_name,
                    event_type, from_concurrency, to_concurrency, pending_jobs,
                    active_jobs, reason, created_at, metadata_json
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.project_id,
                    event.provider,
                    event.profile_id,
                    event.profile_name,
                    event.event_type,
                    event.from_concurrency,
                    event.to_concurrency,
                    event.pending_jobs,
                    event.active_jobs,
                    event.reason,
                    event.created_at,
                    json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
        return event

    def list_scheduler_events(
        self,
        *,
        project_id: int | None = None,
        limit: int = 500,
    ) -> list[GenerationSchedulerEvent]:
        where = "WHERE project_id = ?" if project_id is not None else ""
        params: tuple[object, ...] = (
            (project_id, max(1, limit)) if project_id is not None else (max(1, limit),)
        )
        with self.database.connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM generation_scheduler_events {where} "
                "ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._scheduler_event(row) for row in rows]

    @staticmethod
    def state_key(project_id: int | None, provider: str, profile_id: str | None) -> str:
        project = "global" if project_id is None else str(project_id)
        profile = profile_id or "temporary"
        return f"{project}:{provider}:{profile}"

    @staticmethod
    def metric_key(project_id: int | None, provider: str, profile_id: str | None) -> str:
        return GenerationOrchestrationRepository.state_key(project_id, provider, profile_id)

    @staticmethod
    def throttle_key(project_id: int | None, provider: str, profile_id: str | None) -> str:
        return GenerationOrchestrationRepository.state_key(project_id, provider, profile_id)


    @staticmethod
    def _scheduling_policy(row) -> GenerationSchedulingPolicy:
        try:
            mode = SchedulingMode(str(row["mode"]))
        except ValueError:
            mode = SchedulingMode.ADAPTIVE
        return GenerationSchedulingPolicy(
            policy_key=str(row["policy_key"]),
            project_id=row["project_id"],
            enabled=bool(row["enabled"]),
            mode=mode,
            minimum_concurrency=max(1, int(row["minimum_concurrency"])),
            initial_concurrency=max(1, int(row["initial_concurrency"])),
            maximum_concurrency=max(1, int(row["maximum_concurrency"])),
            per_profile_concurrency=max(1, int(row["per_profile_concurrency"])),
            success_window=max(1, int(row["success_window"])),
            error_window=max(1, int(row["error_window"])),
            increase_step=max(1, int(row["increase_step"])),
            decrease_factor=max(0.1, min(1.0, float(row["decrease_factor"]))),
            rate_limit_cooldown_seconds=max(0, int(row["rate_limit_cooldown_seconds"])),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _throttle_state(row) -> ProviderThrottleSnapshot:
        return ProviderThrottleSnapshot(
            throttle_key=str(row["throttle_key"]),
            project_id=row["project_id"],
            provider=str(row["provider"]),
            profile_id=row["profile_id"],
            profile_name=str(row["profile_name"] or ""),
            current_concurrency=max(1, int(row["current_concurrency"])),
            recent_rate_limits=max(0, int(row["recent_rate_limits"])),
            cooldown_until=row["cooldown_until"],
            last_rate_limit_at=row["last_rate_limit_at"],
            last_recovered_at=row["last_recovered_at"],
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _scheduler_event(row) -> GenerationSchedulerEvent:
        return GenerationSchedulerEvent(
            event_id=str(row["event_id"]),
            project_id=row["project_id"],
            provider=str(row["provider"]),
            profile_id=row["profile_id"],
            profile_name=str(row["profile_name"] or ""),
            event_type=str(row["event_type"]),
            from_concurrency=max(1, int(row["from_concurrency"])),
            to_concurrency=max(1, int(row["to_concurrency"])),
            pending_jobs=max(0, int(row["pending_jobs"])),
            active_jobs=max(0, int(row["active_jobs"])),
            reason=str(row["reason"] or ""),
            created_at=str(row["created_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _policy(row) -> GenerationOrchestrationPolicy:
        return GenerationOrchestrationPolicy(
            policy_key=str(row["policy_key"]),
            project_id=row["project_id"],
            enabled=bool(row["enabled"]),
            auto_failover=bool(row["auto_failover"]),
            failure_threshold=max(1, int(row["failure_threshold"])),
            circuit_cooldown_seconds=max(0, int(row["circuit_cooldown_seconds"])),
            max_switches_per_run=max(0, int(row["max_switches_per_run"])),
            sticky_successful_profile=bool(row["sticky_successful_profile"]),
            notify_on_circuit_open=bool(row["notify_on_circuit_open"]),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _routing_policy(row) -> GenerationAdaptiveRoutingPolicy:
        try:
            mode = RoutingMode(str(row["mode"]))
        except ValueError:
            mode = RoutingMode.PRIORITY
        return GenerationAdaptiveRoutingPolicy(
            policy_key=str(row["policy_key"]),
            project_id=row["project_id"],
            enabled=bool(row["enabled"]),
            mode=mode,
            health_weight=float(row["health_weight"]),
            capacity_weight=float(row["capacity_weight"]),
            latency_weight=float(row["latency_weight"]),
            priority_weight=float(row["priority_weight"]),
            minimum_quota_reserve=max(0, int(row["minimum_quota_reserve"])),
            max_profile_share_percent=max(1, int(row["max_profile_share_percent"])),
            sample_window=max(1, int(row["sample_window"])),
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _circuit(row) -> ProviderCircuitSnapshot:
        try:
            status = ProviderCircuitStatus(str(row["status"]))
        except ValueError:
            status = ProviderCircuitStatus.CLOSED
        return ProviderCircuitSnapshot(
            state_key=str(row["state_key"]),
            project_id=row["project_id"],
            provider=str(row["provider"]),
            profile_id=row["profile_id"],
            profile_name=str(row["profile_name"] or ""),
            status=status,
            consecutive_failures=max(0, int(row["consecutive_failures"])),
            opened_at=row["opened_at"],
            retry_after=row["retry_after"],
            last_failure_category=row["last_failure_category"],
            last_failure_code=row["last_failure_code"],
            last_failure_at=row["last_failure_at"],
            last_success_at=row["last_success_at"],
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _routing_metric(row) -> ProviderRoutingMetric:
        return ProviderRoutingMetric(
            metric_key=str(row["metric_key"]),
            project_id=row["project_id"],
            provider=str(row["provider"]),
            profile_id=row["profile_id"],
            profile_name=str(row["profile_name"] or ""),
            attempts=max(0, int(row["attempts"])),
            successes=max(0, int(row["successes"])),
            failures=max(0, int(row["failures"])),
            total_latency_seconds=max(0.0, float(row["total_latency_seconds"])),
            total_characters=max(0, int(row["total_characters"])),
            ewma_latency_seconds=(
                None
                if row["ewma_latency_seconds"] is None
                else max(0.0, float(row["ewma_latency_seconds"]))
            ),
            health_score=max(0.0, min(100.0, float(row["health_score"]))),
            last_selected_at=row["last_selected_at"],
            last_success_at=row["last_success_at"],
            last_failure_at=row["last_failure_at"],
            updated_at=str(row["updated_at"]),
        )

    @staticmethod
    def _decision(row) -> GenerationRoutingDecision:
        try:
            mode = RoutingMode(str(row["routing_mode"]))
        except ValueError:
            mode = RoutingMode.PRIORITY
        return GenerationRoutingDecision(
            decision_id=str(row["decision_id"]),
            project_id=row["project_id"],
            job_row_number=row["job_row_number"],
            filename=str(row["filename"] or ""),
            provider=str(row["provider"]),
            profile_id=row["profile_id"],
            profile_name=str(row["profile_name"] or ""),
            routing_mode=mode,
            routing_score=float(row["routing_score"]),
            routing_weight=max(1, int(row["routing_weight"])),
            estimated_characters=max(0, int(row["estimated_characters"])),
            reason=str(row["reason"] or ""),
            created_at=str(row["created_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    @staticmethod
    def _event(row) -> GenerationFailoverEvent:
        return GenerationFailoverEvent(
            event_id=str(row["event_id"]),
            project_id=row["project_id"],
            job_row_number=row["job_row_number"],
            filename=str(row["filename"] or ""),
            provider=str(row["provider"]),
            from_profile_id=row["from_profile_id"],
            from_profile_name=str(row["from_profile_name"] or ""),
            to_profile_id=row["to_profile_id"],
            to_profile_name=row["to_profile_name"],
            failure_category=str(row["failure_category"]),
            error_code=str(row["error_code"]),
            outcome=str(row["outcome"]),
            switch_number=max(0, int(row["switch_number"])),
            consecutive_failures=max(0, int(row["consecutive_failures"])),
            circuit_opened=bool(row["circuit_opened"]),
            created_at=str(row["created_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )
