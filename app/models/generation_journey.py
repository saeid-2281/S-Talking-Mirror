from __future__ import annotations

from dataclasses import dataclass


READY_PREFLIGHT = {"Ready", "Ready with warnings"}


@dataclass(frozen=True)
class GenerationJourneyStep:
    code: str
    label: str
    status: str
    detail: str
    tone: str
    action_code: str
    complete: bool


@dataclass(frozen=True)
class GenerationJourneyState:
    headline: str
    summary: str
    steps: tuple[GenerationJourneyStep, ...]
    next_action_code: str
    next_action_label: str
    ready_to_start: bool
    generation_active: bool


def _provider_ready(state: str) -> bool:
    normalized = str(state or "").strip().casefold()
    return normalized in {"ready", "ready but unverified live", "connected"}


def build_generation_journey_state(
    *,
    total_jobs: int,
    total_characters: int,
    scoped_jobs: int,
    scoped_characters: int,
    provider_display: str,
    provider_state: str,
    provider_detail: str,
    model_label: str,
    voice_label: str,
    voice_required: bool,
    scope_label: str,
    preflight_status: str,
    preflight_errors: int = 0,
    preflight_warnings: int = 0,
    generation_active: bool = False,
) -> GenerationJourneyState:
    """Build the presentation-only Generation UX 2.0 journey state.

    Preflight remains authoritative. This helper only chooses the most useful
    next navigation action from already-known application state.
    """

    has_source = total_jobs > 0
    provider_ok = _provider_ready(provider_state)
    voice_ok = bool(str(voice_label or "").strip()) or not voice_required
    scope_ok = scoped_jobs > 0
    preflight_ready = preflight_status in READY_PREFLIGHT
    preflight_blocked = preflight_status == "Blocked by errors"

    source_step = GenerationJourneyStep(
        code="source",
        label="Source",
        status="Ready" if has_source else "Needed",
        detail=(
            f"{total_jobs:,} jobs · {total_characters:,} characters"
            if has_source
            else "Prepare text or add a source"
        ),
        tone="success" if has_source else "warning",
        action_code="prepare-source",
        complete=has_source,
    )

    provider_step = GenerationJourneyStep(
        code="provider",
        label="Provider",
        status="Ready" if provider_ok else "Review",
        detail=(
            f"{provider_display} · {model_label or 'model not selected'}"
            if provider_ok
            else (provider_detail or f"Review {provider_display} setup")
        ),
        tone="success" if provider_ok else "warning",
        action_code="provider",
        complete=provider_ok,
    )

    voice_step = GenerationJourneyStep(
        code="voice",
        label="Voice",
        status="Ready" if voice_ok else "Needed",
        detail=(
            voice_label or "Provider default voice"
            if voice_ok
            else "Choose a compatible voice"
        ),
        tone="success" if voice_ok else "warning",
        action_code="voice",
        complete=voice_ok,
    )

    scope_step = GenerationJourneyStep(
        code="scope",
        label="Scope",
        status="Ready" if scope_ok else "Empty",
        detail=(
            f"{scope_label} · {scoped_jobs:,} jobs · {scoped_characters:,} characters"
            if scope_ok
            else f"{scope_label} contains no jobs"
        ),
        tone="success" if scope_ok else "warning",
        action_code="scope",
        complete=scope_ok,
    )

    if preflight_ready:
        preflight_detail = (
            f"{preflight_errors} errors · {preflight_warnings} warnings"
            if preflight_warnings or preflight_errors
            else "No blocking issues"
        )
        preflight_tone = "warning" if preflight_warnings else "success"
        preflight_complete = True
    elif preflight_blocked:
        preflight_detail = f"{preflight_errors} blocking error(s) · review required"
        preflight_tone = "error"
        preflight_complete = False
    else:
        preflight_detail = "Run preflight after source, provider and scope are ready"
        preflight_tone = "info"
        preflight_complete = False

    preflight_step = GenerationJourneyStep(
        code="preflight",
        label="Preflight",
        status=preflight_status or "Not checked",
        detail=preflight_detail,
        tone=preflight_tone,
        action_code="preflight",
        complete=preflight_complete,
    )

    steps = (source_step, provider_step, voice_step, scope_step, preflight_step)
    ready_to_start = all(
        (has_source, provider_ok, voice_ok, scope_ok, preflight_ready)
    )

    if generation_active:
        headline = "Generation is running"
        summary = (
            f"{scoped_jobs:,} scoped jobs · {scoped_characters:,} characters · "
            "use the generation controls to pause or stop"
        )
        next_code = ""
        next_label = "Generation running"
    elif not has_source:
        headline = "Prepare your source"
        summary = "Start in Text Studio or add source files, then the journey will advance automatically."
        next_code = "prepare-source"
        next_label = "Prepare text"
    elif not provider_ok:
        headline = "Finish provider setup"
        summary = provider_detail or f"Review {provider_display} before generation."
        next_code = "provider"
        next_label = "Fix provider"
    elif not voice_ok:
        headline = "Choose a voice"
        summary = "Select a compatible voice for the active provider and model."
        next_code = "voice"
        next_label = "Choose voice"
    elif not scope_ok:
        headline = "Choose what to generate"
        summary = f"The current {scope_label.lower()} contains no eligible jobs."
        next_code = "scope"
        next_label = "Choose scope"
    elif not preflight_ready:
        headline = "Validate the batch"
        summary = (
            "Preflight found blocking issues."
            if preflight_blocked
            else "Run preflight to validate source, provider, quota, output and launch guards."
        )
        next_code = "preflight"
        next_label = "Review preflight" if preflight_blocked else "Run preflight"
    else:
        headline = "Ready to generate"
        summary = (
            f"{scoped_jobs:,} jobs · {scoped_characters:,} characters · "
            f"{provider_display} · {voice_label or 'provider default'}"
        )
        next_code = "start"
        next_label = "Review & start"

    return GenerationJourneyState(
        headline=headline,
        summary=summary,
        steps=steps,
        next_action_code=next_code,
        next_action_label=next_label,
        ready_to_start=ready_to_start,
        generation_active=generation_active,
    )
