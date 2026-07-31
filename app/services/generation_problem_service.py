from __future__ import annotations

import csv
import hashlib
import json
import re
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app.models.generation_incident import (
    GenerationIncident,
    GenerationIncidentUpdate,
)
from app.models.generation_problem import (
    GenerationKnownProblem,
    GenerationProblemMatch,
    GenerationProblemSummary,
)
from app.models.product_events import ActivityEvent, NotificationRecord
from app.repositories.product_event_repository import ProductEventRepository


class GenerationProblemService:
    """Turn recurring incidents into known errors and tracked permanent fixes."""

    VALID_STATUSES = {
        "investigating",
        "known_error",
        "fix_planned",
        "monitoring",
        "closed",
    }
    ACTIVE_STATUSES = VALID_STATUSES - {"closed"}
    VALID_CATEGORIES = {
        "provider",
        "network",
        "configuration",
        "authentication",
        "quota",
        "data",
        "validation",
        "filesystem",
        "application",
        "unknown",
    }

    def __init__(
        self,
        repository: ProductEventRepository,
        *,
        now_factory: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self._now_factory = now_factory or (lambda: datetime.now(timezone.utc))

    def create_from_incidents(
        self,
        incident_ids: Iterable[str],
        *,
        title: str | None = None,
        actor: str | None = None,
    ) -> GenerationKnownProblem:
        incidents = self._incidents(incident_ids)
        if not incidents:
            raise ValueError("Select at least one existing incident.")
        project_ids = {incident.project_id for incident in incidents}
        if len(project_ids) != 1:
            raise ValueError("All incidents in a known problem must belong to one project.")
        linked_problem_ids = {
            incident.problem_id for incident in incidents if incident.problem_id
        }
        if len(linked_problem_ids) > 1:
            raise ValueError("Selected incidents belong to different known problems.")
        if linked_problem_ids:
            problem_id = next(iter(linked_problem_ids))
            for incident in incidents:
                if not incident.problem_id:
                    self.link_incident(
                        problem_id,
                        incident.incident_id,
                        match_reason="manual-grouping",
                        actor=actor,
                    )
            existing_link = self.get(problem_id)
            if existing_link is None:
                raise RuntimeError("Linked known problem could not be loaded.")
            return existing_link

        category = self._dominant_category(incidents)
        fingerprints = tuple(
            dict.fromkeys(
                incident.alert_fingerprint
                for incident in incidents
                if incident.alert_fingerprint.strip()
            )
        )
        key = self._problem_key(next(iter(project_ids)), category, fingerprints)
        existing = self.repository.find_known_problem_by_key(
            project_id=incidents[0].project_id,
            problem_key=key,
        )
        if existing is not None:
            for incident in incidents:
                self.link_incident(
                    existing.problem_id,
                    incident.incident_id,
                    match_reason="manual-grouping",
                    actor=actor,
                )
            refreshed = self.get(existing.problem_id)
            if refreshed is None:
                raise RuntimeError("Known problem disappeared after linking incidents.")
            return refreshed

        now = self._now().isoformat()
        incident_ids_tuple = tuple(incident.incident_id for incident in incidents)
        problem = GenerationKnownProblem(
            problem_id=uuid.uuid4().hex,
            project_id=incidents[0].project_id,
            problem_key=key,
            title=(title or self._default_title(category, incidents)).strip(),
            description=self._default_description(incidents),
            status="investigating",
            severity=self._highest_severity(incidents),
            root_cause_category=category,
            owner=self._dominant_owner(incidents),
            fingerprints=fingerprints,
            incident_ids=incident_ids_tuple,
            occurrence_count=sum(max(1, item.occurrence_count) for item in incidents),
            first_seen_at=min(item.created_at for item in incidents),
            last_seen_at=max(item.updated_at for item in incidents),
            created_at=now,
            updated_at=now,
        )
        self.repository.save_known_problem(problem)
        for incident in incidents:
            self._link(problem, incident, "manual-grouping", now)
        self._record_problem_event(
            problem,
            "Known problem created",
            f"Created from {len(incidents)} incident(s).",
            actor=actor,
            kind="problem_created",
        )
        return self.get(problem.problem_id) or problem

    def get(self, problem_id: str) -> GenerationKnownProblem | None:
        return self.repository.get_known_problem(problem_id)

    def list_problems(
        self,
        *,
        project_id: int | None = None,
        status: str | None = None,
        limit: int = 1000,
    ) -> list[GenerationKnownProblem]:
        return self.repository.list_known_problems(
            project_id=project_id,
            status=status,
            limit=limit,
        )

    def update_problem(
        self,
        problem: GenerationKnownProblem,
        *,
        actor: str | None = None,
    ) -> GenerationKnownProblem:
        current = self.get(problem.problem_id)
        if current is None:
            raise ValueError("Known problem does not exist.")
        status = problem.status.strip().lower()
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Unsupported problem status: {problem.status}")
        category = problem.root_cause_category.strip().lower() or "unknown"
        if category not in self.VALID_CATEGORIES:
            raise ValueError(f"Unsupported root-cause category: {category}")
        severity = problem.severity.strip().lower()
        if severity not in {"critical", "warning"}:
            raise ValueError(f"Unsupported problem severity: {problem.severity}")
        title = problem.title.strip()
        if not title:
            raise ValueError("Known problem title is required.")
        workaround = problem.workaround.strip()
        permanent_fix = problem.permanent_fix.strip()
        if status == "known_error" and not workaround:
            raise ValueError("Known Error status requires a documented workaround.")
        if status in {"monitoring", "closed"} and not permanent_fix:
            raise ValueError("Monitoring or Closed status requires a permanent fix.")
        monitoring_until = self._normalize_optional_datetime(problem.monitoring_until)
        now = self._now().isoformat()
        saved = replace(
            problem,
            title=title,
            description=problem.description.strip(),
            status=status,
            root_cause_category=category,
            severity=severity,
            workaround=workaround,
            permanent_fix=permanent_fix,
            owner=self._actor(problem.owner),
            monitoring_until=monitoring_until,
            updated_at=now,
            closed_at=now if status == "closed" else None,
        )
        self.repository.save_known_problem(saved)
        self.repository.update_problem_status_links(saved.problem_id, saved.status)
        if current.status != saved.status:
            self._record_problem_event(
                saved,
                "Known problem status changed",
                f"Status changed from {current.status} to {saved.status}.",
                actor=actor,
                kind="problem_status",
            )
        else:
            self._record_problem_event(
                saved,
                "Known problem updated",
                "Problem details, workaround, or permanent fix were updated.",
                actor=actor,
                kind="problem_updated",
            )
        return saved

    def set_status(
        self,
        problem_id: str,
        status: str,
        *,
        actor: str | None = None,
        monitoring_until: str | None = None,
    ) -> GenerationKnownProblem:
        problem = self.get(problem_id)
        if problem is None:
            raise ValueError("Known problem does not exist.")
        return self.update_problem(
            replace(problem, status=status, monitoring_until=monitoring_until),
            actor=actor,
        )

    def link_incident(
        self,
        problem_id: str,
        incident_id: str,
        *,
        match_reason: str = "manual",
        actor: str | None = None,
        notify: bool = False,
    ) -> GenerationKnownProblem:
        problem = self.get(problem_id)
        incident = self.repository.get_incident(incident_id)
        if problem is None:
            raise ValueError("Known problem does not exist.")
        if incident is None:
            raise ValueError("Incident does not exist.")
        if problem.project_id != incident.project_id:
            raise ValueError("Incident and known problem belong to different projects.")
        if incident.problem_id and incident.problem_id != problem_id:
            raise ValueError("Incident is already linked to a different known problem.")

        now = self._now().isoformat()
        reopened = problem.status == "closed"
        updated = replace(
            problem,
            status="investigating" if reopened else problem.status,
            closed_at=None if reopened else problem.closed_at,
            fingerprints=tuple(
                dict.fromkeys((*problem.fingerprints, incident.alert_fingerprint))
            ),
            incident_ids=tuple(dict.fromkeys((*problem.incident_ids, incident.incident_id))),
            occurrence_count=self._occurrence_count(
                tuple(dict.fromkeys((*problem.incident_ids, incident.incident_id)))
            ),
            first_seen_at=min(problem.first_seen_at, incident.created_at),
            last_seen_at=max(problem.last_seen_at, incident.updated_at),
            severity=self._higher_severity(problem.severity, incident.severity),
            updated_at=now,
        )
        self.repository.save_known_problem(updated)
        self._link(updated, incident, match_reason, now)
        message = (
            f"Closed problem reopened by incident {incident.incident_id}."
            if reopened
            else f"Incident {incident.incident_id} linked ({match_reason})."
        )
        self._record_problem_event(
            updated,
            "Known problem recurred" if notify or reopened else "Incident linked to problem",
            message,
            actor=actor,
            kind="problem_recurrence" if notify or reopened else "problem_link",
            incident=incident,
        )
        if notify or reopened:
            self.repository.add_notification(
                NotificationRecord(
                    notification_id=uuid.uuid4().hex,
                    severity="error" if incident.severity == "critical" else "warning",
                    title="Known problem recurred",
                    message=(
                        f"{updated.title}: incident {incident.incident_id} matched a known problem."
                        + (f" Workaround: {updated.workaround}" if updated.workaround else "")
                    ),
                    created_at=now,
                    action_label="Open Problem Center",
                    action_payload="generation-problem-center",
                )
            )
        return self.get(problem_id) or updated

    def match_incident(
        self,
        incident_id: str,
        *,
        auto_link: bool = True,
    ) -> GenerationProblemMatch | None:
        incident = self.repository.get_incident(incident_id)
        if incident is None:
            return None
        if incident.problem_id:
            if auto_link:
                self.link_incident(
                    incident.problem_id,
                    incident.incident_id,
                    match_reason="existing known problem recurrence",
                    notify=True,
                )
            return GenerationProblemMatch(
                problem_id=incident.problem_id,
                incident_id=incident.incident_id,
                score=100,
                reasons=("already linked",),
            )
        candidates = self.list_problems(project_id=incident.project_id)
        review = self.repository.get_incident_review(incident.incident_id)
        category = (
            review.root_cause_category
            if review is not None and review.root_cause_category != "unknown"
            else self._infer_category(incident)
        )
        matches: list[GenerationProblemMatch] = []
        for problem in candidates:
            if problem.status == "closed" and not problem.permanent_fix:
                continue
            score = 0
            reasons: list[str] = []
            if incident.alert_fingerprint in problem.fingerprints:
                score += 100
                reasons.append("exact error fingerprint")
            if category != "unknown" and category == problem.root_cause_category:
                score += 35
                reasons.append("same root-cause category")
            common = self._tokens(incident.title + " " + incident.summary) & self._tokens(
                problem.title + " " + problem.description
            )
            if common:
                score += min(20, len(common) * 4)
                reasons.append("shared incident terms")
            if score >= 60:
                matches.append(
                    GenerationProblemMatch(
                        problem_id=problem.problem_id,
                        incident_id=incident.incident_id,
                        score=score,
                        reasons=tuple(reasons),
                    )
                )
        if not matches:
            return None
        best = max(matches, key=lambda item: (item.score, item.problem_id))
        if auto_link and best.score >= 80:
            self.link_incident(
                best.problem_id,
                incident.incident_id,
                match_reason="; ".join(best.reasons),
                notify=True,
            )
        return best

    def link_action(self, action_id: str, problem_id: str | None) -> int:
        if problem_id is not None and self.get(problem_id) is None:
            raise ValueError("Known problem does not exist.")
        return self.repository.link_action_to_problem(action_id, problem_id)

    def list_actions(self, problem_id: str):
        return self.repository.list_incident_action_items(problem_id=problem_id)

    def summary(
        self,
        problems: Iterable[GenerationKnownProblem],
    ) -> GenerationProblemSummary:
        records = list(problems)
        statuses = Counter(item.status for item in records)
        categories = Counter(item.root_cause_category for item in records)
        return GenerationProblemSummary(
            total=len(records),
            investigating_count=statuses["investigating"],
            known_error_count=statuses["known_error"],
            fix_planned_count=statuses["fix_planned"],
            monitoring_count=statuses["monitoring"],
            closed_count=statuses["closed"],
            open_occurrences=sum(
                item.occurrence_count for item in records if item.status != "closed"
            ),
            linked_incidents=sum(len(item.incident_ids) for item in records),
            unassigned_count=sum(
                1 for item in records if item.status != "closed" and not item.owner
            ),
            by_category=dict(sorted(categories.items())),
        )

    def export(
        self,
        problems: Iterable[GenerationKnownProblem],
        directory: Path,
        *,
        project_name: str = "all-projects",
    ) -> tuple[Path, Path]:
        records = list(problems)
        directory.mkdir(parents=True, exist_ok=True)
        stamp = self._now().strftime("%Y%m%d-%H%M%S")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", project_name).strip("-") or "problems"
        json_path = directory / f"generation-known-problems-{safe_name}-{stamp}.json"
        csv_path = directory / f"generation-known-problems-{safe_name}-{stamp}.csv"
        payload = [self._payload(item) for item in records]
        json_path.write_text(
            json.dumps(
                {
                    "generated_at": self._now().isoformat(),
                    "project": project_name,
                    "summary": self.summary(records).__dict__,
                    "known_problems": payload,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        fieldnames = [
            "problem_id",
            "project_id",
            "problem_key",
            "status",
            "severity",
            "root_cause_category",
            "title",
            "description",
            "owner",
            "occurrence_count",
            "incident_count",
            "first_seen_at",
            "last_seen_at",
            "monitoring_until",
            "workaround",
            "permanent_fix",
            "fingerprints_json",
            "incident_ids_json",
            "corrective_actions_json",
            "created_at",
            "updated_at",
            "closed_at",
        ]
        with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for item in payload:
                writer.writerow(
                    {
                        key: (
                            json.dumps(value, ensure_ascii=False, sort_keys=True)
                            if isinstance(value, (list, dict))
                            else value
                        )
                        for key, value in item.items()
                        if key in fieldnames
                    }
                )
        return json_path, csv_path

    def _payload(self, problem: GenerationKnownProblem) -> dict[str, object]:
        actions = self.list_actions(problem.problem_id)
        return {
            "problem_id": problem.problem_id,
            "project_id": problem.project_id,
            "problem_key": problem.problem_key,
            "status": problem.status,
            "severity": problem.severity,
            "root_cause_category": problem.root_cause_category,
            "title": problem.title,
            "description": problem.description,
            "owner": problem.owner,
            "occurrence_count": problem.occurrence_count,
            "incident_count": len(problem.incident_ids),
            "first_seen_at": problem.first_seen_at,
            "last_seen_at": problem.last_seen_at,
            "monitoring_until": problem.monitoring_until,
            "workaround": problem.workaround,
            "permanent_fix": problem.permanent_fix,
            "fingerprints_json": list(problem.fingerprints),
            "incident_ids_json": list(problem.incident_ids),
            "corrective_actions_json": [
                {
                    "action_id": action.action_id,
                    "incident_id": action.incident_id,
                    "title": action.title,
                    "status": action.status,
                    "priority": action.priority,
                    "owner": action.owner,
                    "due_at": action.due_at,
                }
                for action in actions
            ],
            "created_at": problem.created_at,
            "updated_at": problem.updated_at,
            "closed_at": problem.closed_at,
        }

    def _link(
        self,
        problem: GenerationKnownProblem,
        incident: GenerationIncident,
        match_reason: str,
        linked_at: str,
    ) -> None:
        self.repository.link_problem_incident(
            problem.problem_id,
            incident.incident_id,
            problem_status=problem.status,
            match_reason=match_reason,
            linked_at=linked_at,
        )
        for action in self.repository.list_incident_action_items(
            incident_id=incident.incident_id
        ):
            if action.problem_id != problem.problem_id:
                self.repository.save_incident_action_item(
                    replace(action, problem_id=problem.problem_id)
                )

    def _record_problem_event(
        self,
        problem: GenerationKnownProblem,
        title: str,
        message: str,
        *,
        actor: str | None,
        kind: str,
        incident: GenerationIncident | None = None,
    ) -> None:
        now = self._now().isoformat()
        self.repository.add_activity(
            ActivityEvent(
                event_id=uuid.uuid4().hex,
                project_id=problem.project_id,
                category="generation-problem",
                title=title,
                message=message,
                created_at=now,
                metadata={
                    "problem_id": problem.problem_id,
                    "problem_status": problem.status,
                    "incident_id": incident.incident_id if incident else "",
                    "occurrence_count": problem.occurrence_count,
                },
            )
        )
        for incident_id in problem.incident_ids[-1:]:
            if self.repository.get_incident(incident_id) is None:
                continue
            self.repository.add_incident_update(
                GenerationIncidentUpdate(
                    update_id=uuid.uuid4().hex,
                    incident_id=incident_id,
                    kind=kind,
                    actor=self._actor(actor),
                    message=message,
                    created_at=now,
                    metadata={"problem_id": problem.problem_id, "status": problem.status},
                )
            )

    def _incidents(self, incident_ids: Iterable[str]) -> list[GenerationIncident]:
        ids = tuple(dict.fromkeys(str(value).strip() for value in incident_ids if str(value).strip()))
        return [
            incident
            for incident_id in ids
            if (incident := self.repository.get_incident(incident_id)) is not None
        ]

    def _occurrence_count(self, incident_ids: tuple[str, ...]) -> int:
        return sum(
            max(1, incident.occurrence_count)
            for incident_id in incident_ids
            if (incident := self.repository.get_incident(incident_id)) is not None
        )

    def _dominant_category(self, incidents: list[GenerationIncident]) -> str:
        categories: list[str] = []
        for incident in incidents:
            review = self.repository.get_incident_review(incident.incident_id)
            categories.append(
                review.root_cause_category
                if review is not None and review.root_cause_category != "unknown"
                else self._infer_category(incident)
            )
        counts = Counter(categories)
        return counts.most_common(1)[0][0] if counts else "unknown"

    @staticmethod
    def _infer_category(incident: GenerationIncident) -> str:
        text = " ".join(
            (incident.alert_fingerprint, incident.title, incident.summary)
        ).casefold()
        for category, tokens in (
            ("authentication", ("auth", "credential", "api key", "unauthorized")),
            ("quota", ("quota", "rate limit", "429", "billing")),
            ("network", ("network", "timeout", "connection", "dns")),
            ("filesystem", ("filesystem", "disk", "output", "permission", "path")),
            ("validation", ("validation", "invalid", "schema", "format")),
            ("configuration", ("configuration", "config", "profile", "setting")),
            ("data", ("csv", "input", "row", "data")),
            ("provider", ("provider", "server", "5xx", "service")),
            ("application", ("application", "exception", "crash", "bug")),
        ):
            if any(token in text for token in tokens):
                return category
        return "unknown"

    @staticmethod
    def _problem_key(
        project_id: int | None,
        category: str,
        fingerprints: tuple[str, ...],
    ) -> str:
        normalized = "|".join(
            (str(project_id or "global"), category, *sorted(fingerprints))
        )
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:24]

    @staticmethod
    def _default_title(category: str, incidents: list[GenerationIncident]) -> str:
        if len(incidents) == 1:
            return f"Known problem: {incidents[0].title}"
        return f"Known problem: {category.replace('_', ' ').title()} failures"

    @staticmethod
    def _default_description(incidents: list[GenerationIncident]) -> str:
        summaries = tuple(dict.fromkeys(item.summary for item in incidents if item.summary))
        return "\n".join(summaries[:5])

    @staticmethod
    def _highest_severity(incidents: list[GenerationIncident]) -> str:
        return "critical" if any(item.severity == "critical" for item in incidents) else "warning"

    @staticmethod
    def _higher_severity(current: str, incoming: str) -> str:
        return "critical" if "critical" in {current, incoming} else "warning"

    @staticmethod
    def _dominant_owner(incidents: list[GenerationIncident]) -> str | None:
        owners = [item.assigned_to for item in incidents if item.assigned_to]
        return Counter(owners).most_common(1)[0][0] if owners else None

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]{4,}", value.casefold())
            if token not in {"generation", "incident", "critical", "warning", "error"}
        }

    @classmethod
    def _normalize_optional_datetime(cls, value: str | None) -> str | None:
        text = (value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError as exc:
            raise ValueError("Monitoring deadline must be a valid ISO-8601 value.") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.isoformat()

    @staticmethod
    def _actor(value: str | None) -> str | None:
        return value.strip() if value and value.strip() else None

    def _now(self) -> datetime:
        value = self._now_factory()
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
