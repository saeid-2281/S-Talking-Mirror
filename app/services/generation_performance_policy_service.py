from __future__ import annotations

import hashlib
import re
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from app.models.generation_performance import (
    GenerationAlertDecision,
    GenerationPerformanceAnalysis,
    GenerationPerformanceBudget,
)
from app.repositories.product_event_repository import ProductEventRepository


class GenerationPerformancePolicyService:
    """Persist performance budgets and manage regression-alert lifecycle."""

    def __init__(
        self,
        repository: ProductEventRepository,
        *,
        default_budget: GenerationPerformanceBudget | None = None,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.default_budget = default_budget or GenerationPerformanceBudget()
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    def budget_for(self, project_id: int | None) -> GenerationPerformanceBudget:
        project_budget = self.repository.get_performance_budget(project_id)
        if project_budget is not None:
            return project_budget
        if project_id is not None:
            global_budget = self.repository.get_performance_budget(None)
            if global_budget is not None:
                return replace(global_budget, project_id=project_id)
        return replace(self.default_budget, project_id=project_id)

    def save_budget(self, budget: GenerationPerformanceBudget) -> GenerationPerformanceBudget:
        normalized = replace(
            budget,
            alert_cooldown_minutes=max(0, int(budget.alert_cooldown_minutes)),
            updated_at=self._now().isoformat(),
        )
        self.repository.save_performance_budget(normalized)
        return normalized

    def reset_budget(self, project_id: int | None) -> None:
        self.repository.delete_performance_budget(project_id)

    def silence(self, project_id: int | None, *, minutes: int) -> GenerationPerformanceBudget:
        budget = self.budget_for(project_id)
        silence_until = self._now() + timedelta(minutes=max(1, int(minutes)))
        return self.save_budget(replace(budget, silence_until=silence_until.isoformat()))

    def resume(self, project_id: int | None) -> GenerationPerformanceBudget:
        budget = self.budget_for(project_id)
        return self.save_budget(replace(budget, silence_until=None))

    def decide_and_persist(
        self,
        record,
        analysis: GenerationPerformanceAnalysis,
    ) -> GenerationAlertDecision:
        if analysis.severity not in {"warning", "critical"}:
            decision = GenerationAlertDecision(record.session_id, None, "none", False)
            self.repository.update_batch_alert(
                record.session_id,
                fingerprint=None,
                state="none",
                created_at=None,
            )
            return decision

        now = self._now()
        budget = self.budget_for(record.project_id)
        fingerprint = self.fingerprint(record, analysis)
        state = "open"
        notify = True
        reason = ""
        if not budget.enabled:
            state, notify, reason = "suppressed", False, "Performance alerts are disabled"
        elif self._is_future(budget.silence_until, now):
            state, notify, reason = "silenced", False, "Performance alerts are temporarily silenced"
        elif budget.alert_cooldown_minutes > 0:
            since = now - timedelta(minutes=budget.alert_cooldown_minutes)
            if self.repository.has_recent_emitted_alert(fingerprint, since.isoformat()):
                state, notify, reason = (
                    "suppressed",
                    False,
                    f"Duplicate alert inside {budget.alert_cooldown_minutes}-minute cooldown",
                )

        created_at = now.isoformat()
        self.repository.update_batch_alert(
            record.session_id,
            fingerprint=fingerprint,
            state=state,
            created_at=created_at,
        )
        return GenerationAlertDecision(
            session_id=record.session_id,
            fingerprint=fingerprint,
            state=state,
            notify=notify,
            reason=reason,
            created_at=created_at,
        )

    def attach_notification(self, session_id: str, notification_id: str) -> None:
        self.repository.attach_batch_alert_notification(session_id, notification_id)

    def acknowledge(self, session_ids: Iterable[str]) -> int:
        unique_ids = tuple(dict.fromkeys(str(value) for value in session_ids if value))
        if not unique_ids:
            return 0
        return self.repository.acknowledge_batch_alerts(unique_ids, self._now().isoformat())

    @staticmethod
    def fingerprint(record, analysis: GenerationPerformanceAnalysis) -> str:
        payload = "|".join(
            [
                str(record.project_id or "global"),
                record.provider,
                record.model,
                record.voice,
                record.scope,
                analysis.severity,
                *sorted(
                    GenerationPerformancePolicyService._reason_key(reason)
                    for reason in analysis.reasons
                ),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _reason_key(reason: str) -> str:
        normalized = re.sub(r"\d+(?:\.\d+)?%?", "#", reason.strip().casefold())
        return " ".join(normalized.split())

    def _now(self) -> datetime:
        value = self._now_factory()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)

    @staticmethod
    def _is_future(value: str | None, now: datetime) -> bool:
        if not value:
            return False
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return False
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed > now
