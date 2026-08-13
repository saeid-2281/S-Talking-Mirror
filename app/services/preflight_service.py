from __future__ import annotations

import csv
import hashlib
import html
import json
import re
import tempfile
from dataclasses import asdict, is_dataclass
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.config.runtime import RuntimeConfig
from app.models.domain import AppSettings, JobStatus, TTSJob
from app.models.preflight_state import PreflightFix, PreflightIssue, PreflightState
from app.provider_factory import create_provider
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY
from app.repositories.voice_repository import VoiceRepository
from app.services.generation_planning_service import GenerationPlanningService
from app.services.language_assurance_service import LanguageAssuranceService
from app.services.monitor_formatting import format_duration
from app.services.pronunciation_assurance_service import PronunciationAssuranceService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.provider_readiness_service import ProviderReadinessService
from app.services.voice_service import VoiceService

if TYPE_CHECKING:
    from app.services.generation_cost_capacity_service import GenerationCostCapacityService

WINDOWS_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}
SECRET_VALUE = re.compile(r"(sk_[A-Za-z0-9_=-]+|Bearer\s+[A-Za-z0-9._=-]+)", re.IGNORECASE)
ELEVENLABS_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".pcm", ".ulaw", ".alaw"}


class PreflightService:
    def __init__(
        self,
        runtime: RuntimeConfig,
        voice_repository: VoiceRepository | None = None,
        voice_service: VoiceService | None = None,
        provider_readiness_service: ProviderReadinessService | None = None,
        cost_capacity_service: GenerationCostCapacityService | None = None,
        fallback_seconds_per_job: float = 3.0,
    ) -> None:
        self.runtime = runtime
        self.voice_repository = voice_repository
        self.voice_service = voice_service
        self.provider_readiness_service = provider_readiness_service or ProviderReadinessService()
        self.cost_capacity_service = cost_capacity_service
        self.planning_service = GenerationPlanningService(cost_capacity_service)
        self.language_assurance_service = LanguageAssuranceService()
        self.pronunciation_assurance_service = PronunciationAssuranceService()
        self.fallback_seconds_per_job = fallback_seconds_per_job
        self.latest: PreflightState | None = None
        self._cache_key: tuple[Any, ...] | None = None

    def invalidate(self) -> None:
        self.latest = None
        self._cache_key = None

    def current_state(
        self,
        *,
        jobs: list[TTSJob],
        settings: AppSettings,
        output_dir: Path,
        csv_path: Path | None = None,
        project_id: int | None = None,
    ) -> PreflightState | None:
        """Return the latest Preflight only when it still matches the resolved request.

        This method is intentionally side-effect free: it never refreshes provider
        state, rebuilds planning evidence, contacts the network, or mutates the
        cached Preflight result.
        """
        key = self._key(jobs, settings, output_dir, csv_path, project_id)
        if self.latest is None or self._cache_key != key:
            return None
        return self.latest

    def is_current(
        self,
        *,
        jobs: list[TTSJob],
        settings: AppSettings,
        output_dir: Path,
        csv_path: Path | None = None,
        project_id: int | None = None,
    ) -> bool:
        return (
            self.current_state(
                jobs=jobs,
                settings=settings,
                output_dir=output_dir,
                csv_path=csv_path,
                project_id=project_id,
            )
            is not None
        )

    def run(
        self,
        *,
        jobs: list[TTSJob],
        settings: AppSettings,
        output_dir: Path,
        csv_path: Path | None = None,
        project_name: str = "No project",
        project_id: int | None = None,
    ) -> PreflightState:
        key = self._key(jobs, settings, output_dir, csv_path, project_id)
        if self.latest is not None and self._cache_key == key:
            return self.latest
        issues: list[PreflightIssue] = []
        pending = [job for job in jobs if job.status == JobStatus.PENDING]
        extension = DEFAULT_PROVIDER_REGISTRY.output_extension(settings.provider, settings.file_extension)
        output_ready = self._validate_output_dir(output_dir, issues)
        provider_ready = self._validate_provider(settings, issues)
        provider_ready = self._validate_job_provider_overrides(jobs, settings, issues) and provider_ready
        language_assurance = self.language_assurance_service.assess_batch(jobs, settings)
        provider_ready = self._validate_language_assurance(language_assurance, issues) and provider_ready
        pronunciation_assurance = self.pronunciation_assurance_service.assess_batch(jobs, settings)
        provider_ready = self._validate_pronunciation_assurance(
            jobs,
            pronunciation_assurance,
            language_assurance.overall_level,
            issues,
        ) and provider_ready
        self._validate_pronunciation_dictionary(settings, issues)
        extension_ready = self._validate_extension(settings, issues)
        if csv_path and not csv_path.exists():
            self._issue(issues, "hard_error", None, str(csv_path), "CSV file is missing.", "Choose an existing CSV file.", "missing_csv")
        if not jobs:
            self._issue(issues, "hard_error", None, "", "No CSV rows are loaded.", "Load a CSV before starting generation.", "no_jobs")
        if jobs and not pending:
            failed_count = sum(1 for job in jobs if job.status == JobStatus.FAILED)
            action = f"Retry failed ({failed_count}) or reset the selected scope." if failed_count else "Select another range or reset completed/skipped jobs."
            self._issue(issues, "info", None, "", "No pending jobs in the selected scope.", action, "no_pending_jobs")

        output_names: list[tuple[str, TTSJob]] = []
        text_hashes: list[str] = []
        invalid_rows: list[int] = []
        empty_rows: list[int] = []
        long_rows: list[int] = []
        existing_outputs: list[str] = []
        max_chars = self._model_limit(settings)
        for job in jobs:
            output_path = job.output_path(output_dir, extension)
            output_names.append((output_path.name.casefold(), job))
            text_hashes.append(job.text.strip().casefold())
            if not job.text.strip():
                empty_rows.append(job.row_number)
                self._issue(issues, "hard_error", job.row_number, job.filename, "Text is empty.", "Enter text or remove this row.", "empty_text")
            if max_chars and len(job.text) > max_chars:
                long_rows.append(job.row_number)
                self._issue(issues, "hard_error", job.row_number, job.filename, f"Text exceeds model limit of {max_chars:,} characters.", "Shorten the text or choose another model.", "text_too_long")
            if self._invalid_filename(job.filename):
                invalid_rows.append(job.row_number)
                self._issue(issues, "hard_error", job.row_number, job.filename, "Filename is invalid on Windows.", "Sanitize the filename.", "invalid_filename")
            if self._path_traversal(job.filename):
                self._issue(issues, "hard_error", job.row_number, job.filename, "Filename escapes the output directory.", "Use a plain filename.", "path_traversal")
            extension_problem = self._filename_extension_problem(job.filename, settings)
            if extension_problem == "Filename extension is missing.":
                self._issue(issues, "warning", job.row_number, job.filename, extension_problem, "The provider default extension can be added.", "missing_extension")
            elif extension_problem:
                self._issue(issues, "hard_error", job.row_number, job.filename, extension_problem, "Use a supported audio filename extension.", "unsupported_extension")
            if len(str(output_path)) > 240:
                self._issue(issues, "hard_error", job.row_number, job.filename, "Output path is too long for Windows.", "Shorten the filename or output folder.", "path_too_long")
            if output_path.exists():
                existing_outputs.append(str(output_path))
                severity = "warning" if settings.skip_existing else "hard_error"
                action = "Mark as skipped before generation." if settings.skip_existing else "Enable Skip Existing, rename, or remove the file."
                self._issue(issues, severity, job.row_number, job.filename, "Output file already exists.", action, "existing_output")

        duplicate_names = {name for name, count in Counter(name for name, _job in output_names).items() if count > 1}
        duplicates = sorted(duplicate_names)
        for duplicate_name, job in output_names:
            if duplicate_name in duplicate_names:
                self._issue(issues, "hard_error", job.row_number, job.filename, "Duplicate output filename.", "Append suffixes to duplicate filenames.", "duplicate_filename")
        duplicate_text_rows = [
            job.row_number for job in jobs if text_hashes.count(job.text.strip().casefold()) > 1 and job.text.strip()
        ]
        for row in duplicate_text_rows:
            job = next(item for item in jobs if item.row_number == row)
            self._issue(issues, "warning", row, job.filename, "Duplicate text appears in the batch.", "Confirm this repeated text is intentional.", "duplicate_text")

        pending_characters = sum(len(job.text) for job in pending)
        quota_snapshot = self._validate_quota(settings, pending_characters, issues)
        warnings = sum(1 for issue in issues if issue.severity == "warning")
        blocking = sum(1 for issue in issues if issue.severity in {"hard_error", "overridable_error", "error"} and not (issue.overridable and issue.overridden))
        revision = hashlib.sha256(json.dumps(self._key(jobs, settings, output_dir, csv_path, project_id), default=str, sort_keys=True).encode("utf-8")).hexdigest()
        fallback_duration = len(pending) * self.fallback_seconds_per_job
        generation_plan = self.planning_service.build(
            project_id=project_id,
            provider=settings.provider,
            model=settings.model_id,
            files=len(pending),
            characters=pending_characters,
            provider_requests=len(pending),
            fallback_duration_seconds=fallback_duration,
            quota_snapshot=quota_snapshot,
            max_retries=settings.max_retries,
            delay_seconds=settings.delay_seconds,
        )
        estimated_cost = generation_plan.estimated_cost if generation_plan.cost_available else None
        pronunciation_decisions = {
            job.row_number: str(getattr(job, "pronunciation_override", None) or "").strip()
            for job in jobs
        }
        state = PreflightState(
            total_jobs=len(jobs),
            valid_jobs=max(0, len(jobs) - len({issue.row for issue in issues if issue.severity in {"hard_error", "error"} and issue.row})),
            blocking_errors=blocking,
            warnings=warnings,
            duplicate_filenames=duplicates,
            duplicate_texts=duplicate_text_rows,
            empty_texts=empty_rows,
            invalid_filenames=invalid_rows,
            excessively_long_texts=long_rows,
            existing_outputs=existing_outputs,
            estimated_characters=pending_characters,
            estimated_files=len(pending),
            estimated_duration_seconds=generation_plan.estimated_duration_seconds,
            estimated_provider_requests=len(pending),
            estimated_cost=estimated_cost,
            generation_plan=generation_plan,
            provider_ready=provider_ready,
            output_directory_ready=output_ready,
            can_start=blocking == 0 and bool(pending) and output_ready and provider_ready and extension_ready,
            quota_snapshot=quota_snapshot,
            issues=issues,
            revision=revision,
            account_fingerprint=hashlib.sha256((settings.api_key or "").encode("utf-8")).hexdigest()[:16],
            catalog_revision=str(quota_snapshot.get("catalog_revision", "")) if quota_snapshot else "",
            settings_revision=hashlib.sha256(settings.model_dump_json(exclude={"api_key"}).encode("utf-8")).hexdigest()[:16],
            language_lock_languages=language_assurance.languages,
            language_assurance_level=language_assurance.overall_level,
            language_assurance_summary=language_assurance.summary,
            pronunciation_risk_summary=pronunciation_assurance.summary,
            pronunciation_high_risk_rows=pronunciation_assurance.high_risk_rows,
            pronunciation_medium_risk_rows=pronunciation_assurance.medium_risk_rows,
            pronunciation_normalizable_rows=pronunciation_assurance.normalizable_rows,
            pronunciation_reviewed_rows=pronunciation_assurance.reviewed_rows,
            pronunciation_explicit_original_rows=pronunciation_assurance.explicit_original_rows,
            pronunciation_normalized_rows=pronunciation_assurance.normalized_rows,
            pronunciation_previews=tuple(
                {
                    "row": item.row,
                    "language": item.language,
                    "risk_level": item.risk_level,
                    "flags": list(item.flags),
                    "original_text": item.original_text,
                    "normalized_text": item.normalized_text,
                    "normalization_kind": item.normalization_kind,
                    "normalization_safe": item.normalization_safe,
                    "decision": pronunciation_decisions.get(int(item.row or 0), ""),
                }
                for item in pronunciation_assurance.assessments
                if item.risk_level in {"medium", "high"} or item.normalization_safe
            ),
        )
        self.latest = state
        self._cache_key = key
        return state

    def apply_safe_fixes(self, state: PreflightState, jobs: list[TTSJob], settings: AppSettings, output_dir: Path) -> int:
        output_dir.mkdir(parents=True, exist_ok=True)
        fixes = {fix.row: fix for fix in self.filename_fix_plan(state, jobs, settings, output_dir)}
        changed = 0
        for job in jobs:
            fix = fixes.get(job.row_number)
            if fix and job.filename != fix.new_filename:
                job.filename = fix.new_filename
                changed += 1
            output_path = job.output_path(output_dir, DEFAULT_PROVIDER_REGISTRY.output_extension(settings.provider, settings.file_extension))
            if settings.skip_existing and output_path.exists() and job.status == JobStatus.PENDING:
                job.status = JobStatus.SKIPPED
                job.generated_output_path = str(output_path)
                changed += 1
        self.invalidate()
        return changed

    def filename_fix_plan(
        self,
        state: PreflightState,
        jobs: list[TTSJob],
        settings: AppSettings,
        output_dir: Path,
    ) -> list[PreflightFix]:
        seen: dict[str, int] = {}
        extension = DEFAULT_PROVIDER_REGISTRY.output_extension(settings.provider, settings.file_extension)
        filename_issue_rows = {
            issue.row
            for issue in state.issues
            if issue.row is not None
            and issue.message
            in {
                "Filename is invalid on Windows.",
                "Filename escapes the output directory.",
                "Duplicate output filename.",
                "Filename extension is missing.",
                "Filename extension is unsupported.",
                "Output path is too long for Windows.",
            }
        }
        fixes: list[PreflightFix] = []
        for job in jobs:
            if self._looks_like_prose_filename(job.filename):
                continue
            safe = self._sanitize_filename(job.filename)
            stem_path = Path(safe)
            if not stem_path.suffix:
                stem_path = stem_path.with_suffix(extension)
            key = stem_path.name.casefold()
            seen[key] = seen.get(key, 0) + 1
            if seen[key] > 1:
                stem_path = stem_path.with_stem(f"{stem_path.stem}-{seen[key]}")
            if job.row_number in filename_issue_rows and stem_path.name != job.filename:
                reasons = [
                    issue.message
                    for issue in state.issues
                    if issue.row == job.row_number and issue.message in {
                        "Filename is invalid on Windows.",
                        "Filename escapes the output directory.",
                        "Duplicate output filename.",
                        "Filename extension is missing.",
                        "Filename extension is unsupported.",
                        "Output path is too long for Windows.",
                    }
                ]
                fixes.append(
                    PreflightFix(
                        row=job.row_number,
                        original_filename=job.filename,
                        new_filename=stem_path.name,
                        reason=", ".join(dict.fromkeys(reasons)) or "Filename fix",
                    )
                )
        return fixes

    def write_report(self, state: PreflightState, project_name: str = "No project") -> Path:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        report_dir = self.runtime.reports_dir / self._safe_name(project_name) / "preflight" / timestamp
        report_dir.mkdir(parents=True, exist_ok=True)
        payload = self._state_json(state)
        (report_dir / "preflight.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        (report_dir / "preflight.md").write_text(self.markdown(state), encoding="utf-8")
        (report_dir / "preflight.html").write_text(self.html(state), encoding="utf-8")
        with (report_dir / "issues.csv").open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["severity", "row", "filename", "message", "suggested_action", "code", "overridable", "overridden", "override_reason"])
            writer.writeheader()
            for issue in state.issues:
                writer.writerow(issue.__dict__)
        state.report_dir = report_dir
        return report_dir

    def markdown(self, state: PreflightState) -> str:
        lines = [
            "# S Talking Preflight Report",
            "",
            f"- Status: {state.status}",
            f"- Files: {state.estimated_files:,}",
            f"- Characters: {state.estimated_characters:,}",
            f"- Requests: {state.estimated_provider_requests:,}",
            f"- Estimated time: {format_duration(state.estimated_duration_seconds)}",
            (
                f"- Estimated cost: {state.estimated_cost:.4f}"
                if state.estimated_cost is not None
                else "- Estimated cost: Cost unavailable"
            ),
            f"- Existing outputs: {len(state.existing_outputs):,}",
        ]
        if state.generation_plan is not None:
            plan = state.generation_plan
            lines.extend(
                [
                    f"- Plan risk: {plan.risk_level.title()}",
                    f"- Throughput confidence: {plan.throughput_confidence.title()} ({plan.historical_session_count} historical sessions)",
                    f"- Quota remaining: {plan.quota_remaining:,}" if plan.quota_remaining is not None else "- Quota remaining: Unknown",
                    f"- Queue budget usage: {plan.budget_usage_percent:.1f}%" if plan.budget_usage_percent is not None else "- Queue budget usage: No limit",
                    "",
                    "## Planning scenarios",
                ]
            )
            lines.extend(
                f"- {scenario.label}: {scenario.characters:,} characters, {scenario.provider_requests:,} requests, {format_duration(scenario.estimated_duration_seconds)}, "
                + (f"{plan.currency} {scenario.estimated_cost:.4f}" if plan.cost_available else "Cost unavailable")
                for scenario in plan.scenarios
            )
        lines.extend(
            [
                "",
                "## Issues",
            ]
        )
        if state.issues:
            lines.extend(
                f"- {issue.severity.upper()} row {issue.row or '—'} `{issue.filename}`: {issue.message} Fix: {issue.suggested_action}"
                for issue in state.issues
            )
        else:
            lines.append("- None")
        return self._sanitize("\n".join(lines) + "\n")

    def html(self, state: PreflightState) -> str:
        rows = "".join(
            "<tr>"
            f"<td>{html.escape(issue.severity)}</td><td>{issue.row or ''}</td>"
            f"<td>{html.escape(issue.filename)}</td><td>{html.escape(issue.message)}</td>"
            f"<td>{html.escape(issue.suggested_action)}</td>"
            "</tr>"
            for issue in state.issues
        ) or "<tr><td colspan='5'>No issues</td></tr>"
        return self._sanitize(
            f"""<!doctype html>
<html lang="en"><meta charset="utf-8"><title>S Talking Preflight</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:2rem}}table{{border-collapse:collapse;width:100%}}td,th{{border-bottom:1px solid #ccc;padding:.45rem;text-align:left}}</style>
<h1>S Talking Preflight Report</h1>
<p>Status: <strong>{html.escape(state.status)}</strong></p>
{self._cost_html(state)}
{self._plan_html(state)}
<table><thead><tr><th>Severity</th><th>Row</th><th>Filename</th><th>Problem</th><th>Suggested fix</th></tr></thead><tbody>{rows}</tbody></table>
</html>
"""
        )


    @staticmethod
    def _plan_html(state: PreflightState) -> str:
        plan = state.generation_plan
        if plan is None:
            return ""
        scenario_rows = "".join(
            "<tr>"
            f"<td>{html.escape(item.label)}</td>"
            f"<td>{item.retry_reserve_percent}%</td>"
            f"<td>{item.characters:,}</td>"
            f"<td>{item.provider_requests:,}</td>"
            f"<td>{html.escape(format_duration(item.estimated_duration_seconds))}</td>"
            + (
                f"<td>{html.escape(plan.currency)} {item.estimated_cost:.4f}</td>"
                if plan.cost_available
                else "<td>Cost unavailable</td>"
            )
            + "</tr>"
            for item in plan.scenarios
        )
        reasons = " ".join(plan.reasons)
        return (
            f"<h2>Batch plan</h2><p>Risk: <strong>{html.escape(plan.risk_level.title())}</strong> · "
            f"Confidence: {html.escape(plan.throughput_confidence.title())} · "
            f"{html.escape(reasons)}</p>"
            "<table><thead><tr><th>Scenario</th><th>Retry reserve</th><th>Characters</th>"
            "<th>Requests</th><th>Time</th><th>Cost</th></tr></thead>"
            f"<tbody>{scenario_rows}</tbody></table>"
        )

    @staticmethod
    def _cost_html(state: PreflightState) -> str:
        if state.estimated_cost is None:
            return (
                f"<p>Files: {state.estimated_files:,} · "
                f"Characters: {state.estimated_characters:,} · "
                f"ETA: {format_duration(state.estimated_duration_seconds)} · "
                "Cost unavailable</p>"
            )
        return (
            f"<p>Files: {state.estimated_files:,} · "
            f"Characters: {state.estimated_characters:,} · "
            f"ETA: {format_duration(state.estimated_duration_seconds)} · "
            f"Estimated cost: {state.estimated_cost:.4f}</p>"
        )

    def _state_json(self, state: PreflightState) -> dict[str, Any]:
        data = {
            key: value
            for key, value in state.__dict__.items()
            if key not in {"issues", "report_dir"}
        }
        data["issues"] = [issue.__dict__ for issue in state.issues]
        data["report_dir"] = str(state.report_dir) if state.report_dir else None
        data["status"] = state.status
        return self._sanitize(data)

    def _validate_output_dir(self, output_dir: Path, issues: list[PreflightIssue]) -> bool:
        try:
            if not output_dir.exists():
                parent = output_dir.parent if output_dir.parent != output_dir else Path(".")
                if not parent.exists():
                    self._issue(issues, "hard_error", None, str(output_dir), "Output directory parent is missing.", "Choose an existing parent folder.", "output_parent_missing")
                    return False
                self._issue(issues, "warning", None, str(output_dir), "Output directory does not exist.", "Create the output directory before generation.", "output_missing")
                return True
            with tempfile.NamedTemporaryFile(dir=output_dir, delete=True):
                pass
            return True
        except Exception as exc:
            self._issue(issues, "hard_error", None, str(output_dir), f"Output directory is not writable: {exc}", "Choose or create a writable folder.", "output_unwritable")
            return False

    def _validate_provider(self, settings: AppSettings, issues: list[PreflightIssue]) -> bool:
        ready = True
        readiness = self.provider_readiness_service.readiness_for(settings.provider, settings)
        if readiness.blocks_generation:
            detail = readiness.reason
            if readiness.missing_requirements:
                detail = f"{detail} Missing: {', '.join(readiness.missing_requirements)}"
            self._issue(
                issues,
                "hard_error",
                None,
                settings.provider,
                f"{readiness.display_name} is {readiness.state}.",
                detail,
                "provider_not_production_ready",
            )
            ready = False
        catalog = ProviderCatalogService()
        capabilities = catalog.capabilities_for(settings.provider, settings)
        card = catalog.card_for(settings.provider, settings)
        if card.setup_state != "Ready":
            severity = "hard_error" if capabilities.requires_credential or capabilities.optional_dependency else "warning"
            self._issue(issues, severity, None, settings.provider, card.message, "Open Quick Setup or Provider accounts and complete setup.", "provider_setup_required")
            ready = severity != "hard_error"
        if capabilities.supported_output_formats and not DEFAULT_PROVIDER_REGISTRY.manifest_for(settings.provider).forced_file_extension:
            output_format = (settings.output_format or settings.file_extension.strip(".")).split("_", 1)[0]
            supported = {item.split("_", 1)[0].lower() for item in capabilities.supported_output_formats}
            if output_format.lower() not in supported and settings.file_extension.strip(".").lower() not in supported:
                self._issue(issues, "hard_error", None, settings.output_format, "Output format is not supported by the selected provider.", "Choose a provider-supported output format.", "provider_output_format_unsupported")
                ready = False
        if settings.provider == "elevenlabs":
            if not settings.api_key:
                self._issue(issues, "hard_error", None, "", "ElevenLabs API key is missing.", "Add an API key in provider settings.", "missing_api_key")
                ready = False
            if not settings.voice_id:
                self._issue(issues, "hard_error", None, "", "ElevenLabs voice is missing.", "Select a voice.", "missing_voice")
                ready = False
            if not settings.model_id:
                self._issue(issues, "hard_error", None, "", "ElevenLabs model is missing.", "Select a model.", "missing_model")
                ready = False
            if self.voice_repository and settings.voice_id:
                voice = self.voice_repository.get("elevenlabs", settings.voice_id)
                if voice is None:
                    self._issue(issues, "overridable_error", None, settings.voice_id, "Voice is not present in the cached catalog.", "Refresh the Voice Browser catalog or override remote validation for this run.", "voice_catalog_missing", overridable=True)
                else:
                    try:
                        metadata = json.loads(voice.metadata_json or "{}")
                    except json.JSONDecodeError:
                        metadata = {}
                    models = metadata.get("compatible_model_ids") or metadata.get("high_quality_base_model_ids") or []
                    if models and settings.model_id not in models:
                        self._issue(issues, "hard_error", None, settings.model_id, "Model is not available for the selected voice.", "Choose a compatible model from Voice Browser.", "model_voice_incompatible")
                        ready = False
                    language_codes = self._metadata_language_codes(metadata)
                    if settings.language_code and language_codes and settings.language_code.lower() not in language_codes:
                        self._issue(issues, "hard_error", None, settings.language_code, "Language code is not available for the selected voice/model metadata.", "Choose a compatible language or refresh Voice Browser metadata.", "language_model_incompatible")
                        ready = False
        elif settings.provider == "piper":
            if not settings.piper_model_path or not Path(settings.piper_model_path).is_file():
                self._issue(issues, "hard_error", None, settings.piper_model_path or "", "Piper model file is missing.", "Choose an existing .onnx model file.", "missing_piper_model")
                ready = False
        elif settings.provider in {"cartesia", "deepgram", "resemble", "murf"}:
            provider = None
            try:
                provider = create_provider(settings)
                validate = getattr(provider, "validate_synthesis_configuration", provider.validate_configuration)
                synthesis_validation = validate(settings)
            except Exception as exc:
                synthesis_validation = None
                self._issue(issues, "hard_error", None, settings.provider, str(exc), "Review provider account, voice, model, language and output settings.", "provider_synthesis_configuration_invalid")
                ready = False
            finally:
                close = getattr(provider, "close", None)
                if callable(close):
                    close()
            if synthesis_validation is not None and not synthesis_validation.ok:
                self._issue(issues, "hard_error", None, settings.provider, synthesis_validation.message, "Choose a compatible voice/model/language/output combination.", "provider_synthesis_configuration_invalid")
                ready = False
        return ready

    def _validate_job_provider_overrides(self, jobs: list[TTSJob], settings: AppSettings, issues: list[PreflightIssue]) -> bool:
        providers = {settings.provider}
        providers.update(job.provider_override for job in jobs if job.provider_override)
        if len(providers) > 1:
            self._issue(
                issues,
                "hard_error",
                None,
                ", ".join(sorted(providers)),
                "Mixed-provider batch execution is not enabled yet.",
                "Filter or edit the queue so all pending jobs use one provider.",
                "mixed_provider_batch_disabled",
            )
            return False
        return True

    def _validate_language_assurance(self, assurance, issues: list[PreflightIssue]) -> bool:
        ready = True
        for decision in assurance.decisions:
            row = decision.rows[0] if len(decision.rows) == 1 else None
            filename = decision.canonical_language or decision.requested_language
            if decision.blocking:
                self._issue(
                    issues,
                    "hard_error",
                    row,
                    filename,
                    decision.message,
                    decision.suggested_action,
                    decision.code,
                )
                ready = False
            elif decision.requires_acknowledgement:
                self._issue(
                    issues,
                    "warning",
                    row,
                    filename,
                    decision.message,
                    decision.suggested_action,
                    decision.code,
                )
        return ready

    def _validate_pronunciation_assurance(
        self,
        jobs: list[TTSJob],
        assurance,
        language_assurance_level: str,
        issues: list[PreflightIssue],
    ) -> bool:
        ready = True
        jobs_by_row = {job.row_number: job for job in jobs}
        unresolved_high: list[int] = []
        unresolved_medium: list[int] = []
        for assessment in assurance.assessments:
            if assessment.row is None:
                continue
            job = jobs_by_row.get(assessment.row)
            override = str(getattr(job, "pronunciation_override", None) or "").strip() if job else ""
            if override == "original":
                continue
            if override == "normalized":
                if not assessment.normalization_safe:
                    self._issue(
                        issues,
                        "hard_error",
                        assessment.row,
                        getattr(job, "filename", "") if job else "",
                        "Language-locked normalization was requested, but no safe normalized form is available for this text and selected language.",
                        "Keep the original text, use a pronunciation dictionary, or review the row in Language Probe.",
                        "pronunciation_normalization_unavailable",
                    )
                    ready = False
                continue
            if assessment.risk_level == "high":
                unresolved_high.append(assessment.row)
            elif assessment.risk_level == "medium":
                unresolved_medium.append(assessment.row)

        if unresolved_high or unresolved_medium:
            level_detail = (
                " Language Lock is best-effort for the selected provider/model, so short-text review is especially important."
                if language_assurance_level in {"best_effort", "none"}
                else ""
            )
            self._issue(
                issues,
                "warning",
                None,
                "pronunciation",
                f"Pronunciation review is recommended for {len(unresolved_high) + len(unresolved_medium)} job(s) "
                f"({len(unresolved_high)} high risk, {len(unresolved_medium)} medium risk).{level_detail}",
                "Open Pronunciation Review Workspace or select 1-3 rows for Language Probe. Record an explicit original/normalized decision only after review.",
                "pronunciation_review_required",
            )
        if len(assurance.languages) > 1:
            self._issue(
                issues,
                "info",
                None,
                ", ".join(assurance.languages),
                "The batch contains multiple explicit target languages from project/job language settings.",
                "Review Language Probe samples per target language. No content-based language detection or automatic language switching is performed.",
                "pronunciation_mixed_explicit_languages",
            )
        return ready

    def _validate_pronunciation_dictionary(self, settings: AppSettings, issues: list[PreflightIssue]) -> None:
        if settings.provider != "elevenlabs":
            return
        if settings.active_pronunciation_dictionary_id and not settings.pronunciation_dictionary_locators:
            self._issue(
                issues,
                "warning",
                None,
                settings.active_pronunciation_dictionary_id,
                "Pronunciation dictionary metadata is missing or stale.",
                "Open Pronunciation dictionaries and refresh or disable the dictionary.",
                "pronunciation_dictionary_missing",
            )

    def _validate_extension(self, settings: AppSettings, issues: list[PreflightIssue]) -> bool:
        if settings.provider == "elevenlabs" and settings.file_extension.lower() not in ELEVENLABS_EXTENSIONS:
            self._issue(issues, "hard_error", None, settings.file_extension, "Output extension is unsupported.", "Choose a supported audio extension.", "unsupported_output_extension")
            return False
        return True

    def _validate_quota(
        self,
        settings: AppSettings,
        characters: int,
        issues: list[PreflightIssue],
    ) -> dict[str, int | str | None] | None:
        if settings.provider != "elevenlabs":
            return None
        catalog = self.voice_service.cached_catalog(settings) if self.voice_service else None
        account = catalog.account if catalog else None
        if account and account.remaining_characters is not None:
            snapshot: dict[str, int | str | None] = {
                "tier": account.tier,
                "status": account.status,
                "used": account.character_count,
                "limit": account.character_limit,
                "remaining": account.remaining_characters,
                "catalog_revision": catalog.refreshed_at,
            }
            if characters > account.remaining_characters:
                shortfall = characters - account.remaining_characters
                self._issue(
                    issues,
                    "warning",
                    None,
                    "",
                    f"ElevenLabs quota shortfall. Required: {characters:,} characters. Available: {account.remaining_characters:,} characters. Shortfall: {shortfall:,} characters.",
                    "Continue anyway, select a smaller scope, auto-select jobs that fit quota, choose another account, or enable account failover.",
                    "insufficient_quota",
                )
            else:
                self._issue(issues, "warning", None, "", f"ElevenLabs quota snapshot: {account.character_count or 0:,} used, {account.remaining_characters:,} remaining.", "Refresh account data before starting if this is stale.", "quota_snapshot")
            return snapshot
        if characters > 0:
            self._issue(issues, "warning", None, "", "Quota unavailable.", "Test connection to refresh account data. You can continue, but the provider may stop when quota is exhausted.", "quota_unknown")
        return None

    def _model_limit(self, settings: AppSettings) -> int | None:
        if settings.provider == "mock":
            return 10_000
        if settings.provider == "piper":
            return 5_000
        if settings.provider == "openai":
            return 4_096
        return 5_000 if settings.provider in {"elevenlabs", "azure", "google", "aws_polly", "kokoro"} else None

    def _metadata_language_codes(self, metadata: dict[str, Any]) -> set[str]:
        codes: set[str] = set()
        for key in ("verified_languages", "languages"):
            values = metadata.get(key) or []
            if isinstance(values, dict):
                values = [values]
            for item in values:
                if isinstance(item, str):
                    codes.add(item.lower())
                elif isinstance(item, dict):
                    for field in ("language_id", "language_code", "code"):
                        value = item.get(field)
                        if isinstance(value, str) and value:
                            codes.add(value.lower())
        return codes

    def _invalid_filename(self, filename: str) -> bool:
        basename = Path(filename).name
        path = Path(basename)
        stem = path.stem.upper()
        return bool(
            WINDOWS_INVALID.search(basename)
            or stem in RESERVED_NAMES
            or basename.strip() != basename
            or basename.rstrip(".") != basename
            or not basename.strip()
        )

    def _filename_extension_problem(self, filename: str, settings: AppSettings) -> str | None:
        suffix = Path(filename).suffix.lower()
        if not suffix:
            return "Filename extension is missing."
        if settings.provider == "elevenlabs" and suffix not in ELEVENLABS_EXTENSIONS:
            return "Filename extension is unsupported."
        return None

    def _looks_like_prose_filename(self, filename: str) -> bool:
        basename = Path(filename).name.strip()
        if not Path(basename).suffix and (re.search(r"\s", basename) or basename.endswith((".", "!", "?", ":", ";", ","))):
            return True
        if len(basename) > 80:
            return True
        words = [part for part in re.split(r"\s+", basename) if part]
        if len(words) > 4:
            return True
        return False

    def _path_traversal(self, filename: str) -> bool:
        path = Path(filename)
        return path.is_absolute() or ".." in path.parts or len(path.parts) > 1

    def _sanitize_filename(self, filename: str) -> str:
        clean = WINDOWS_INVALID.sub("_", Path(filename).name.strip())
        clean = clean.replace("..", "_")
        if not clean or Path(clean).stem.upper() in RESERVED_NAMES:
            clean = "audio"
        return clean

    def _key(
        self,
        jobs: list[TTSJob],
        settings: AppSettings,
        output_dir: Path,
        csv_path: Path | None,
        project_id: int | None = None,
    ) -> tuple[Any, ...]:
        return (
            tuple(
                (
                    job.row_number,
                    job.filename,
                    job.text,
                    job.status.value,
                    job.language_override or "",
                    job.pronunciation_override or "",
                )
                for job in jobs
            ),
            settings.model_dump_json(exclude={"api_key"}),
            hashlib.sha256((settings.api_key or "").encode("utf-8")).hexdigest(),
            str(output_dir),
            str(csv_path or ""),
            project_id,
        )

    def _issue(
        self,
        issues: list[PreflightIssue],
        severity: str,
        row: int | None,
        filename: str,
        message: str,
        suggested_action: str,
        code: str = "",
        *,
        overridable: bool = False,
    ) -> None:
        issues.append(
            PreflightIssue(
                severity,
                row,
                self._sanitize(filename),
                self._sanitize(message),
                self._sanitize(suggested_action),
                code=code,
                overridable=overridable,
            )
        )

    def _sanitize(self, value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return self._sanitize(asdict(value))
        if isinstance(value, dict):
            return {key: self._sanitize(item) for key, item in value.items() if "api_key" not in str(key).lower()}
        if isinstance(value, (list, tuple)):
            return [self._sanitize(item) for item in value]
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, str):
            return SECRET_VALUE.sub("[REDACTED]", value)
        return value

    def _safe_name(self, value: str) -> str:
        return self._sanitize_filename(value).rstrip(". ") or "No project"
