from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from app.models.generation_budget_guard import (
    GenerationBudgetGuardApproval,
    GenerationBudgetGuardDecision,
    GenerationBudgetGuardExport,
    GenerationBudgetReservation,
    GenerationBudgetGuardSummary,
)
from app.services.generation_cost_capacity_service import GenerationCostCapacityService


class GenerationBudgetGuardService:
    """Enforce cost budgets and provider quota with auditable reservations."""

    INDEX_NAME = "generation-budget-guard.json"
    SCHEMA_VERSION = 1
    SECRET_VALUE = re.compile(
        r"(sk[_-][A-Za-z0-9_=-]+|Bearer\s+[A-Za-z0-9._=-]+|(?:api[_-]?key|token|secret|password)\s*[:=]\s*['\"]?[^'\"\s,;}]+)",
        re.IGNORECASE,
    )

    def __init__(
        self,
        reports_dir: Path,
        cost_capacity_service: GenerationCostCapacityService,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)
        self.cost_capacity_service = cost_capacity_service
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    @property
    def index_path(self) -> Path:
        return self.reports_dir / self.INDEX_NAME

    def evaluate(
        self,
        *,
        project_id: int | None,
        project_name: str,
        provider: str,
        model_id: str,
        estimated_cost: float,
        currency: str,
        required_characters: int,
        quota_remaining: int | None,
        launch_fingerprint: str,
    ) -> GenerationBudgetGuardDecision:
        now = self._now()
        self._expire_records(now)
        dashboard = self.cost_capacity_service.dashboard(
            project_id=project_id,
            provider=provider,
            model=model_id,
            now=now,
        )
        policy = dashboard.policy
        snapshot = dashboard.snapshot
        reservations = self.list_reservations(project_name=project_name, status="active")
        reserved_cost = sum(
            item.estimated_cost
            for item in reservations
            if item.currency.upper() == str(currency or policy.currency).upper()
            and item.launch_fingerprint != launch_fingerprint
        )
        reserved_characters = sum(
            item.reserved_characters
            for item in reservations
            if item.provider.casefold() == str(provider or "").casefold()
            and item.launch_fingerprint != launch_fingerprint
        )
        normalized_cost = max(0.0, float(estimated_cost or 0.0))
        normalized_chars = max(0, int(required_characters or 0))
        normalized_currency = str(currency or policy.currency or "USD").upper()
        daily = max(0.0, float(snapshot.daily_spend)) + reserved_cost + normalized_cost
        weekly = max(0.0, float(snapshot.weekly_spend)) + reserved_cost + normalized_cost
        monthly = max(0.0, float(snapshot.monthly_spend)) + reserved_cost + normalized_cost
        effective_quota = None if quota_remaining is None else max(0, int(quota_remaining))
        quota_shortfall = (
            max(0, normalized_chars + reserved_characters - effective_quota)
            if effective_quota is not None
            else 0
        )
        hard_codes: list[str] = []
        warning_codes: list[str] = []
        reasons: list[str] = []

        if effective_quota is None:
            warning_codes.append("quota_unknown")
            reasons.append("Provider quota is unknown; refresh the provider account before a large run.")
        elif quota_shortfall > 0:
            hard_codes.append("quota_shortfall")
            reasons.append(
                f"Required and reserved work exceeds provider quota by {quota_shortfall:,} characters."
            )

        currency_mismatch = normalized_currency != str(policy.currency or "USD").upper()
        if currency_mismatch and normalized_cost > 0:
            warning_codes.append("budget_currency_mismatch")
            reasons.append(
                f"Launch estimate uses {normalized_currency}, while the configured budget uses {policy.currency}."
            )

        if policy.enabled and not currency_mismatch:
            self._check_budget(
                "daily",
                daily,
                policy.daily_budget,
                policy.warning_percent,
                hard_codes,
                warning_codes,
                reasons,
                normalized_currency,
            )
            self._check_budget(
                "weekly",
                weekly,
                policy.weekly_budget,
                policy.warning_percent,
                hard_codes,
                warning_codes,
                reasons,
                normalized_currency,
            )
            self._check_budget(
                "monthly",
                monthly,
                policy.monthly_budget,
                policy.warning_percent,
                hard_codes,
                warning_codes,
                reasons,
                normalized_currency,
            )
            if policy.max_queue_cost > 0 and normalized_cost > policy.max_queue_cost:
                hard_codes.append("max_queue_cost")
                reasons.append(
                    f"Launch cost {normalized_currency} {normalized_cost:.4f} exceeds the per-run limit "
                    f"of {policy.max_queue_cost:.4f}."
                )

        fingerprint = self._fingerprint(
            project_id=project_id,
            project_name=project_name,
            provider=provider,
            model_id=model_id,
            launch_fingerprint=launch_fingerprint,
            estimated_cost=normalized_cost,
            currency=normalized_currency,
            required_characters=normalized_chars,
            quota_remaining=effective_quota,
            hard_codes=hard_codes,
            warning_codes=warning_codes,
            policy_updated_at=policy.updated_at,
        )
        approval = self.matching_approval(project_name, fingerprint)
        quota_blocked = "quota_shortfall" in hard_codes
        budget_hard_codes = tuple(code for code in hard_codes if code != "quota_shortfall")

        if not policy.enabled and not hard_codes and not warning_codes:
            status = "disabled"
            allowed = True
            summary = "Budget policy is disabled and provider quota is sufficient."
            acknowledgement = False
        elif quota_blocked:
            status = "quota_blocked"
            allowed = False
            summary = "Provider quota cannot cover the planned and reserved characters."
            acknowledgement = False
        elif budget_hard_codes and approval is None:
            status = "budget_blocked"
            allowed = False
            summary = "Configured cost limits block this launch."
            acknowledgement = False
        elif budget_hard_codes and approval is not None:
            status = "approved_exception"
            allowed = True
            summary = "A time-bound budget exception permits this exact launch."
            acknowledgement = True
        elif warning_codes:
            status = "warning"
            allowed = True
            summary = "Budget or quota conditions require explicit acknowledgement."
            acknowledgement = True
        else:
            status = "ready"
            allowed = True
            summary = "Budget and provider quota are ready for this launch."
            acknowledgement = False

        return GenerationBudgetGuardDecision(
            status=status,
            allowed=allowed,
            summary=summary,
            fingerprint=fingerprint,
            project_id=project_id,
            project_name=str(project_name or ""),
            provider=str(provider or ""),
            model_id=str(model_id or ""),
            currency=normalized_currency,
            estimated_cost=normalized_cost,
            active_reserved_cost=round(reserved_cost, 8),
            projected_daily_spend=round(daily, 8),
            projected_weekly_spend=round(weekly, 8),
            projected_monthly_spend=round(monthly, 8),
            daily_budget=max(0.0, float(policy.daily_budget)),
            weekly_budget=max(0.0, float(policy.weekly_budget)),
            monthly_budget=max(0.0, float(policy.monthly_budget)),
            max_queue_cost=max(0.0, float(policy.max_queue_cost)),
            warning_percent=max(1.0, min(100.0, float(policy.warning_percent))),
            required_characters=normalized_chars,
            active_reserved_characters=reserved_characters,
            quota_remaining=effective_quota,
            quota_shortfall=quota_shortfall,
            reasons=tuple(dict.fromkeys(reasons)),
            hard_limit_codes=tuple(dict.fromkeys(hard_codes)),
            warning_codes=tuple(dict.fromkeys(warning_codes)),
            approval_id=approval.approval_id if approval is not None else "",
            requires_acknowledgement=acknowledgement,
        )

    def create_approval(
        self,
        *,
        project_name: str,
        decision_fingerprint: str,
        approved_by: str,
        reason: str,
        duration_minutes: int = 60,
        max_uses: int = 1,
    ) -> GenerationBudgetGuardApproval:
        project = str(project_name or "").strip()
        fingerprint = str(decision_fingerprint or "").strip()
        actor = self._sanitize(approved_by).strip()
        explanation = self._sanitize(reason).strip()
        if not project or not fingerprint:
            raise ValueError("Project and budget decision fingerprint are required.")
        if not actor:
            raise ValueError("Approved by is required.")
        if len(explanation) < 8:
            raise ValueError("Provide a budget exception reason of at least 8 characters.")
        now = self._now()
        approval = GenerationBudgetGuardApproval(
            approval_id=f"budget-approval-{uuid.uuid4().hex}",
            project_name=project,
            decision_fingerprint=fingerprint,
            reason=explanation,
            approved_by=actor,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=max(1, int(duration_minutes)))).isoformat(),
            max_uses=max(1, min(10, int(max_uses))),
            status="approved",
        )
        payload = self._read_index()
        approvals = payload.setdefault("approvals", [])
        if not isinstance(approvals, list):
            approvals = []
            payload["approvals"] = approvals
        approvals.append(asdict(approval))
        payload["updated_at"] = now.isoformat()
        self._write_index(payload)
        return approval

    def matching_approval(
        self,
        project_name: str,
        decision_fingerprint: str,
    ) -> GenerationBudgetGuardApproval | None:
        now = self._now()
        for approval in self.list_approvals(project_name=project_name, status="approved"):
            if approval.decision_fingerprint != decision_fingerprint:
                continue
            if self._parse(approval.expires_at) <= now:
                continue
            if approval.used_count >= approval.max_uses:
                continue
            return approval
        return None

    def consume_approval(self, approval_id: str, *, receipt_id: str = "") -> GenerationBudgetGuardApproval:
        payload = self._read_index()
        approvals = payload.get("approvals")
        if not isinstance(approvals, list):
            raise ValueError("Budget approval archive is empty.")
        now = self._now()
        for index, item in enumerate(approvals):
            if not isinstance(item, dict) or str(item.get("approval_id")) != str(approval_id):
                continue
            approval = self._approval_from_dict(item, now)
            if not approval.active or self._parse(approval.expires_at) <= now:
                raise ValueError("Budget exception approval is not active.")
            used = approval.used_count + 1
            status = "consumed" if used >= approval.max_uses else "approved"
            updated = replace(approval, used_count=used, status=status)
            record = asdict(updated)
            record["last_receipt_id"] = self._sanitize(receipt_id)
            approvals[index] = record
            payload["updated_at"] = now.isoformat()
            self._write_index(payload)
            return updated
        raise ValueError("Budget exception approval was not found.")

    def revoke_approval(self, approval_id: str) -> GenerationBudgetGuardApproval:
        payload = self._read_index()
        approvals = payload.get("approvals")
        if not isinstance(approvals, list):
            raise ValueError("Budget approval archive is empty.")
        now = self._now()
        for index, item in enumerate(approvals):
            if not isinstance(item, dict) or str(item.get("approval_id")) != str(approval_id):
                continue
            approval = self._approval_from_dict(item, now)
            updated = replace(approval, status="revoked", revoked_at=now.isoformat())
            approvals[index] = asdict(updated)
            payload["updated_at"] = now.isoformat()
            self._write_index(payload)
            return updated
        raise ValueError("Budget exception approval was not found.")

    def reserve(
        self,
        decision: GenerationBudgetGuardDecision,
        *,
        run_id: str,
        launch_fingerprint: str,
        receipt_id: str = "",
        expires_minutes: int = 1440,
    ) -> GenerationBudgetReservation:
        if not decision.allowed:
            raise ValueError("A blocked budget decision cannot be reserved.")
        existing = next(
            (
                item
                for item in self.list_reservations(status="active")
                if item.run_id == run_id or (
                    item.launch_fingerprint == launch_fingerprint
                    and item.project_name.casefold() == decision.project_name.casefold()
                )
            ),
            None,
        )
        if existing is not None:
            return existing
        now = self._now()
        reservation = GenerationBudgetReservation(
            reservation_id=f"budget-reservation-{uuid.uuid4().hex}",
            project_id=decision.project_id,
            project_name=decision.project_name,
            run_id=str(run_id or ""),
            launch_fingerprint=str(launch_fingerprint or ""),
            provider=decision.provider,
            model_id=decision.model_id,
            currency=decision.currency,
            estimated_cost=decision.estimated_cost,
            reserved_characters=decision.required_characters,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(minutes=max(1, int(expires_minutes)))).isoformat(),
            receipt_id=self._sanitize(receipt_id),
        )
        payload = self._read_index()
        reservations = payload.setdefault("reservations", [])
        if not isinstance(reservations, list):
            reservations = []
            payload["reservations"] = reservations
        reservations.append(asdict(reservation))
        payload["updated_at"] = now.isoformat()
        self._write_index(payload)
        return reservation

    def attach_receipt(self, reservation_id: str, receipt_id: str) -> GenerationBudgetReservation:
        return self._update_reservation(
            reservation_id,
            lambda item: replace(item, receipt_id=self._sanitize(receipt_id)),
        )

    def release_reservation(
        self,
        reservation_id: str,
        *,
        reason: str = "released",
    ) -> GenerationBudgetReservation:
        now = self._now()
        return self._update_reservation(
            reservation_id,
            lambda item: replace(
                item,
                status="released",
                released_at=now.isoformat(),
                release_reason=self._sanitize(reason),
            ),
        )

    def settle_reservation(
        self,
        reservation_id: str,
        *,
        actual_cost: float | None,
        execution_receipt_id: str = "",
    ) -> GenerationBudgetReservation:
        now = self._now()
        value = None if actual_cost is None else max(0.0, float(actual_cost))
        return self._update_reservation(
            reservation_id,
            lambda item: replace(
                item,
                status="settled",
                actual_cost=value,
                execution_receipt_id=self._sanitize(execution_receipt_id),
                released_at=now.isoformat(),
                release_reason="run_finalized",
            ),
        )

    def list_reservations(
        self,
        *,
        project_name: str | None = None,
        status: str | None = None,
    ) -> list[GenerationBudgetReservation]:
        now = self._now()
        payload = self._read_index()
        records = payload.get("reservations")
        project_key = str(project_name or "").strip().casefold()
        status_key = str(status or "").strip().casefold()
        result: list[GenerationBudgetReservation] = []
        for item in records if isinstance(records, list) else []:
            if not isinstance(item, dict):
                continue
            reservation = self._reservation_from_dict(item, now)
            if project_key and reservation.project_name.casefold() != project_key:
                continue
            if status_key and reservation.status.casefold() != status_key:
                continue
            result.append(reservation)
        result.sort(key=lambda item: (item.created_at, item.reservation_id), reverse=True)
        return result

    def list_approvals(
        self,
        *,
        project_name: str | None = None,
        status: str | None = None,
    ) -> list[GenerationBudgetGuardApproval]:
        now = self._now()
        payload = self._read_index()
        records = payload.get("approvals")
        project_key = str(project_name or "").strip().casefold()
        status_key = str(status or "").strip().casefold()
        result: list[GenerationBudgetGuardApproval] = []
        for item in records if isinstance(records, list) else []:
            if not isinstance(item, dict):
                continue
            approval = self._approval_from_dict(item, now)
            if project_key and approval.project_name.casefold() != project_key:
                continue
            if status_key and approval.status.casefold() != status_key:
                continue
            result.append(approval)
        result.sort(key=lambda item: (item.created_at, item.approval_id), reverse=True)
        return result

    def summary(self, *, project_name: str | None = None) -> GenerationBudgetGuardSummary:
        reservations = self.list_reservations(project_name=project_name)
        approvals = self.list_approvals(project_name=project_name)
        active = [item for item in reservations if item.status == "active"]
        currency = next((item.currency for item in active), "USD")
        return GenerationBudgetGuardSummary(
            total_reservations=len(reservations),
            active_reservations=sum(item.status == "active" for item in reservations),
            settled_reservations=sum(item.status == "settled" for item in reservations),
            released_reservations=sum(item.status in {"released", "expired"} for item in reservations),
            total_approvals=len(approvals),
            active_approvals=sum(item.status == "approved" for item in approvals),
            reserved_cost=sum(item.estimated_cost for item in active),
            reserved_characters=sum(item.reserved_characters for item in active),
            currency=currency,
        )

    def export(
        self,
        directory: Path,
        *,
        project_name: str | None = None,
    ) -> GenerationBudgetGuardExport:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        safe_project = re.sub(r"[^A-Za-z0-9._-]+", "-", str(project_name or "all-projects")).strip("-") or "all-projects"
        json_path = directory / f"generation-budget-guard-{safe_project}-{stamp}.json"
        csv_path = directory / f"generation-budget-reservations-{safe_project}-{stamp}.csv"
        reservations = self.list_reservations(project_name=project_name)
        approvals = self.list_approvals(project_name=project_name)
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "created_at": self._now().isoformat(),
            "project_name": project_name or "all-projects",
            "summary": asdict(self.summary(project_name=project_name)),
            "reservations": [asdict(item) for item in reservations],
            "approvals": [asdict(item) for item in approvals],
        }
        json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        fields = list(GenerationBudgetReservation.__dataclass_fields__)
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(asdict(item) for item in reservations)
        return GenerationBudgetGuardExport(json_path=json_path, csv_path=csv_path)

    def _update_reservation(self, reservation_id: str, updater) -> GenerationBudgetReservation:
        payload = self._read_index()
        records = payload.get("reservations")
        if not isinstance(records, list):
            raise ValueError("Budget reservation archive is empty.")
        now = self._now()
        for index, item in enumerate(records):
            if not isinstance(item, dict) or str(item.get("reservation_id")) != str(reservation_id):
                continue
            reservation = self._reservation_from_dict(item, now)
            updated = updater(reservation)
            records[index] = asdict(updated)
            payload["updated_at"] = now.isoformat()
            self._write_index(payload)
            return updated
        raise ValueError("Budget reservation was not found.")

    def _expire_records(self, now: datetime) -> None:
        payload = self._read_index()
        changed = False
        reservations = payload.get("reservations")
        if isinstance(reservations, list):
            for index, item in enumerate(reservations):
                if not isinstance(item, dict):
                    continue
                reservation = self._reservation_from_dict(item, now)
                if reservation.status == "active" and self._parse(reservation.expires_at) <= now:
                    reservations[index] = asdict(
                        replace(
                            reservation,
                            status="expired",
                            released_at=now.isoformat(),
                            release_reason="reservation_expired",
                        )
                    )
                    changed = True
        approvals = payload.get("approvals")
        if isinstance(approvals, list):
            for index, item in enumerate(approvals):
                if not isinstance(item, dict):
                    continue
                approval = self._approval_from_dict(item, now)
                if approval.status == "approved" and self._parse(approval.expires_at) <= now:
                    approvals[index] = asdict(replace(approval, status="expired"))
                    changed = True
        if changed:
            payload["updated_at"] = now.isoformat()
            self._write_index(payload)

    @staticmethod
    def _check_budget(
        name: str,
        projected: float,
        budget: float,
        warning_percent: float,
        hard_codes: list[str],
        warning_codes: list[str],
        reasons: list[str],
        currency: str,
    ) -> None:
        limit = max(0.0, float(budget or 0.0))
        if limit <= 0:
            return
        usage = projected / limit * 100.0
        if projected > limit + 1e-9:
            hard_codes.append(f"{name}_budget_exceeded")
            reasons.append(
                f"Projected {name} spend is {currency} {projected:.4f}, above the {limit:.4f} limit."
            )
        elif usage >= max(1.0, min(100.0, float(warning_percent))):
            warning_codes.append(f"{name}_budget_warning")
            reasons.append(f"Projected {name} budget usage is {usage:.1f}%.")

    def _read_index(self) -> dict[str, object]:
        if not self.index_path.exists():
            return {
                "schema_version": self.SCHEMA_VERSION,
                "updated_at": "",
                "reservations": [],
                "approvals": [],
            }
        try:
            payload = json.loads(self.index_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                payload.setdefault("reservations", [])
                payload.setdefault("approvals", [])
                return payload
        except (OSError, ValueError, TypeError):
            pass
        return {
            "schema_version": self.SCHEMA_VERSION,
            "updated_at": "",
            "reservations": [],
            "approvals": [],
        }

    def _write_index(self, payload: dict[str, object]) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload["schema_version"] = self.SCHEMA_VERSION
        encoded = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{self.index_path.name}.",
            suffix=".tmp",
            dir=str(self.index_path.parent),
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.index_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _reservation_from_dict(
        self,
        item: dict[str, object],
        now: datetime,
    ) -> GenerationBudgetReservation:
        status = str(item.get("status") or "active").casefold()
        expires_at = str(item.get("expires_at") or now.isoformat())
        if status == "active" and self._parse(expires_at) <= now:
            status = "expired"
        return GenerationBudgetReservation(
            reservation_id=str(item.get("reservation_id") or ""),
            project_id=self._optional_integer(item.get("project_id")),
            project_name=str(item.get("project_name") or ""),
            run_id=str(item.get("run_id") or ""),
            launch_fingerprint=str(item.get("launch_fingerprint") or ""),
            provider=str(item.get("provider") or ""),
            model_id=str(item.get("model_id") or ""),
            currency=str(item.get("currency") or "USD").upper(),
            estimated_cost=max(0.0, self._number(item.get("estimated_cost"))),
            reserved_characters=max(0, self._integer(item.get("reserved_characters"))),
            created_at=str(item.get("created_at") or ""),
            expires_at=expires_at,
            status=status,
            receipt_id=str(item.get("receipt_id") or ""),
            execution_receipt_id=str(item.get("execution_receipt_id") or ""),
            actual_cost=self._optional_number(item.get("actual_cost")),
            released_at=str(item.get("released_at") or ""),
            release_reason=str(item.get("release_reason") or ""),
        )

    def _approval_from_dict(
        self,
        item: dict[str, object],
        now: datetime,
    ) -> GenerationBudgetGuardApproval:
        status = str(item.get("status") or "approved").casefold()
        expires_at = str(item.get("expires_at") or now.isoformat())
        used = max(0, self._integer(item.get("used_count")))
        maximum = max(1, self._integer(item.get("max_uses"), 1))
        if status == "approved" and self._parse(expires_at) <= now:
            status = "expired"
        elif status == "approved" and used >= maximum:
            status = "consumed"
        return GenerationBudgetGuardApproval(
            approval_id=str(item.get("approval_id") or ""),
            project_name=str(item.get("project_name") or ""),
            decision_fingerprint=str(item.get("decision_fingerprint") or ""),
            reason=str(item.get("reason") or ""),
            approved_by=str(item.get("approved_by") or ""),
            created_at=str(item.get("created_at") or ""),
            expires_at=expires_at,
            max_uses=maximum,
            used_count=used,
            status=status,
            revoked_at=str(item.get("revoked_at") or ""),
        )

    @classmethod
    def _fingerprint(cls, **values: object) -> str:
        encoded = json.dumps(values, sort_keys=True, default=str, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @classmethod
    def _sanitize(cls, value: object) -> str:
        return cls.SECRET_VALUE.sub("[REDACTED]", str(value or ""))[:2000]

    def _now(self) -> datetime:
        value = self._now_factory()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    @staticmethod
    def _parse(value: str) -> datetime:
        try:
            parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        except ValueError:
            return datetime.min.replace(tzinfo=timezone.utc)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)

    @staticmethod
    def _integer(value: object, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _optional_integer(value: object) -> int | None:
        if value in {None, ""}:
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _number(value: object) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _optional_number(value: object) -> float | None:
        if value in {None, ""}:
            return None
        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return None
