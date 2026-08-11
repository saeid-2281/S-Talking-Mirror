from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.config.runtime import RuntimeConfig
from app.models.first_run_onboarding import FirstRunOnboardingState, FirstRunOnboardingStep


class FirstRunOnboardingService:
    """Persistent, user-controlled first-run guidance for Roadmap 2 A2.

    Reading onboarding state is side-effect free. The service never switches a
    provider/account, refreshes a catalog, runs Preflight, starts/restarts
    generation, probes the network, or writes the database. State changes happen
    only after an explicit onboarding action such as marking a step reviewed,
    completing onboarding, or resetting progress.
    """

    DOCUMENT_SCHEMA_VERSION = 1
    ROADMAP = "S-Talking 1.x Product Experience"
    PHASE = "A2 — First-run / Onboarding Experience"
    STATE_FILENAME = "first-run-onboarding.json"

    _STEPS = (
        FirstRunOnboardingStep(
            "workspace_orientation",
            "Understand the production workflow",
            "Orient",
            "See the path from project/source preparation through provider selection, Preflight, generation and output review before changing anything.",
            "focus_workflow",
            "Show production workflow",
        ),
        FirstRunOnboardingStep(
            "provider_readiness",
            "Review provider account readiness",
            "Connect",
            "Open Provider Accounts to review credentials and readiness. Onboarding itself never creates, switches or verifies an account automatically.",
            "provider_accounts",
            "Open Provider Accounts",
        ),
        FirstRunOnboardingStep(
            "voice_model_choice",
            "Review voice and model choices",
            "Choose",
            "Use the unified catalog to inspect available voices/models and quality context. Selection remains an explicit user decision.",
            "voice_model_catalog",
            "Open Voice & Model Catalog",
        ),
        FirstRunOnboardingStep(
            "project_sources",
            "Create or continue a project",
            "Prepare",
            "Review project continuity and source preparation before anything enters the generation queue.",
            "project_continuity",
            "Open Project Continuity",
        ),
        FirstRunOnboardingStep(
            "preflight_approval",
            "Understand Preflight and launch approval",
            "Validate",
            "Preflight validates the resolved request and launch approval remains explicit. This step only brings the workflow into focus; it never runs Preflight or generation.",
            "focus_workflow",
            "Focus Preflight workflow",
        ),
        FirstRunOnboardingStep(
            "generation_output",
            "Understand generation and output review",
            "Finish",
            "Review live operations, progress and output playback. Generation still starts only from the existing explicit Generation controls.",
            "live_operations",
            "Show Live Operations",
        ),
    )

    def __init__(
        self,
        runtime: RuntimeConfig,
        *,
        state_path: Path | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.runtime = runtime
        self.state_path = Path(state_path or (runtime.data_dir / self.STATE_FILENAME))
        self._now_provider = now or (lambda: datetime.now(timezone.utc))

    @classmethod
    def safety_contract(cls) -> dict[str, object]:
        return {
            "read_state_is_side_effect_free": True,
            "automatic_provider_switch": False,
            "automatic_account_change": False,
            "automatic_catalog_refresh": False,
            "automatic_provider_probe": False,
            "automatic_preflight_run": False,
            "automatic_generation_start": False,
            "automatic_generation_restart": False,
            "automatic_cross_provider_failover": False,
            "automatic_database_write": False,
            "explicit_progress_writes_only": True,
        }

    @classmethod
    def steps(cls) -> tuple[FirstRunOnboardingStep, ...]:
        return cls._STEPS

    @classmethod
    def step_ids(cls) -> tuple[str, ...]:
        return tuple(step.step_id for step in cls._STEPS)

    def default_state(self) -> FirstRunOnboardingState:
        return FirstRunOnboardingState(document_schema_version=self.DOCUMENT_SCHEMA_VERSION)

    def load_state(self) -> FirstRunOnboardingState:
        """Read current progress without mutating the filesystem."""
        if not self.state_path.exists():
            return self.default_state()
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return self.default_state()
        if not isinstance(payload, dict):
            return self.default_state()
        if payload.get("document_schema_version") != self.DOCUMENT_SCHEMA_VERSION:
            return self.default_state()

        valid_ids = set(self.step_ids())
        raw_steps = payload.get("completed_steps", [])
        if not isinstance(raw_steps, list):
            raw_steps = []
        completed = tuple(
            step_id
            for step_id in self.step_ids()
            if step_id in raw_steps and step_id in valid_ids
        )
        first_run_completed = bool(payload.get("first_run_completed", False))
        if first_run_completed and not self.all_required_steps_complete(completed):
            first_run_completed = False
        last_step = str(payload.get("last_step", ""))
        if last_step not in valid_ids:
            last_step = ""
        return FirstRunOnboardingState(
            document_schema_version=self.DOCUMENT_SCHEMA_VERSION,
            completed_steps=completed,
            first_run_completed=first_run_completed,
            completed_at=str(payload.get("completed_at", "")) if first_run_completed else "",
            updated_at=str(payload.get("updated_at", "")),
            last_step=last_step,
        )

    def progress(self, state: FirstRunOnboardingState | None = None) -> tuple[int, int, int]:
        current = state or self.load_state()
        total = len(self._STEPS)
        completed = len(current.completed_steps)
        percent = round((completed / total) * 100) if total else 100
        return completed, total, percent

    def should_offer(self, state: FirstRunOnboardingState | None = None) -> bool:
        return not (state or self.load_state()).first_run_completed

    def all_required_steps_complete(self, completed_steps: tuple[str, ...] | list[str]) -> bool:
        completed = set(completed_steps)
        return all(not step.required or step.step_id in completed for step in self._STEPS)

    def mark_step_complete(self, step_id: str) -> FirstRunOnboardingState:
        self._require_step(step_id)
        current = self.load_state()
        completed = tuple(
            candidate
            for candidate in self.step_ids()
            if candidate in set(current.completed_steps) | {step_id}
        )
        state = FirstRunOnboardingState(
            document_schema_version=self.DOCUMENT_SCHEMA_VERSION,
            completed_steps=completed,
            first_run_completed=current.first_run_completed,
            completed_at=current.completed_at,
            updated_at=self._timestamp(),
            last_step=step_id,
        )
        self._write_state(state)
        return state

    def mark_step_incomplete(self, step_id: str) -> FirstRunOnboardingState:
        self._require_step(step_id)
        current = self.load_state()
        completed = tuple(item for item in current.completed_steps if item != step_id)
        state = FirstRunOnboardingState(
            document_schema_version=self.DOCUMENT_SCHEMA_VERSION,
            completed_steps=completed,
            first_run_completed=False,
            completed_at="",
            updated_at=self._timestamp(),
            last_step=step_id,
        )
        self._write_state(state)
        return state

    def complete_onboarding(self) -> FirstRunOnboardingState:
        current = self.load_state()
        if not self.all_required_steps_complete(current.completed_steps):
            raise ValueError("All required onboarding steps must be explicitly reviewed before completion.")
        timestamp = self._timestamp()
        state = FirstRunOnboardingState(
            document_schema_version=self.DOCUMENT_SCHEMA_VERSION,
            completed_steps=current.completed_steps,
            first_run_completed=True,
            completed_at=timestamp,
            updated_at=timestamp,
            last_step=current.last_step,
        )
        self._write_state(state)
        return state

    def reset_progress(self) -> FirstRunOnboardingState:
        state = FirstRunOnboardingState(
            document_schema_version=self.DOCUMENT_SCHEMA_VERSION,
            updated_at=self._timestamp(),
        )
        self._write_state(state)
        return state

    def _require_step(self, step_id: str) -> None:
        if step_id not in self.step_ids():
            raise ValueError(f"Unknown onboarding step: {step_id}")

    def _timestamp(self) -> str:
        return self._now_provider().astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def _write_state(self, state: FirstRunOnboardingState) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
        temp_path.write_text(
            json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(self.state_path)
