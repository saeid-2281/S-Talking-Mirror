from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic

import app
from app.config.runtime import RuntimeConfig
from app.models.dashboard_state import DashboardState
from app.models.health_state import HealthCheckState, HealthScoreItem, HealthState
from app.models.project_state import ProjectState
from app.services.diagnostics_service import DiagnosticsService
from app.services.git_service import GitService
from app.services.report_service import ReportService


class HealthService:
    """Build health snapshots and shareable Markdown summaries."""

    def __init__(
        self,
        runtime: RuntimeConfig,
        git_service: GitService,
        report_service: ReportService,
        diagnostics_service: DiagnosticsService,
    ) -> None:
        self.runtime = runtime
        self.git_service = git_service
        self.report_service = report_service
        self.diagnostics_service = diagnostics_service
        self._metadata_cache: tuple[float, object, HealthCheckState, Path | None, Path | None] | None = None

    def snapshot(
        self,
        *,
        project: ProjectState | None = None,
        dashboard: DashboardState | None = None,
    ) -> HealthState:
        current_dashboard = dashboard or DashboardState()
        git, check, report, diagnostics = self._metadata()
        packaged_runtime = self._is_packaged_runtime()
        development_available = not packaged_runtime
        warnings: list[str] = []
        recommendations: list[str] = []
        breakdown: list[HealthScoreItem] = []

        if packaged_runtime:
            breakdown.extend(self._runtime_breakdown(project=project, dashboard=current_dashboard, report=report, diagnostics=diagnostics))
        else:
            runtime_points = 10
            breakdown.append(HealthScoreItem("Runtime", runtime_points, 10, "passed", "Application services initialized."))

        if development_available:
            compile_points = 10 if check.compile_passed else 0
            breakdown.append(
                HealthScoreItem(
                    "Compile",
                    compile_points,
                    10,
                    "passed" if check.compile_passed else "warning",
                    "Passed" if check.compile_passed else "No successful compile result found.",
                )
            )

            test_points = 30 if check.success and check.tests_passed > 0 else 0
            breakdown.append(
                HealthScoreItem(
                    "Tests",
                    test_points,
                    30,
                    "passed" if test_points else "error" if check.available else "warning",
                    f"{check.tests_passed} tests passed" if check.tests_passed else "No passing test count found.",
                )
            )

            ruff_points = 15 if check.ruff_passed else 0
            breakdown.append(
                HealthScoreItem(
                    "Ruff",
                    ruff_points,
                    15,
                    "passed" if check.ruff_passed else "warning",
                    "Passed" if check.ruff_passed else "No successful Ruff result found.",
                )
            )
        else:
            breakdown.extend(
                [
                    HealthScoreItem("Compile", 0, 0, "not_applicable", "Development compile checks are not applicable in packaged runtime."),
                    HealthScoreItem("Tests", 0, 0, "not_applicable", "Pytest is a source-checkout tool and is not required in packaged runtime."),
                    HealthScoreItem("Ruff", 0, 0, "not_applicable", "Ruff is a source-checkout tool and is not required in packaged runtime."),
                ]
            )

        if packaged_runtime:
            git_points, git_status, git_detail = 0, "not_applicable", "Git status is not applicable in packaged runtime."
        else:
            if git.clean:
                git_points, git_status, git_detail = 15, "passed", "Working tree is clean."
            elif git.branch == "main":
                git_points, git_status, git_detail = 0, "error", f"main has {len(git.changed_files)} changed file(s)."
                warnings.append(git_detail)
                recommendations.append("Review or commit the pending changes before continuing on main.")
            else:
                git_points, git_status, git_detail = 10, "warning", f"Feature branch has {len(git.changed_files)} changed file(s)."
                warnings.append(git_detail)
                recommendations.append("Prepare a commit when the current feature is ready.")
        breakdown.append(HealthScoreItem("Git", git_points, 15, git_status, git_detail))

        if not packaged_runtime:
            diagnostics_points = 10 if diagnostics else 0
            breakdown.append(
                HealthScoreItem(
                    "Diagnostics",
                    diagnostics_points,
                    10,
                    "passed" if diagnostics else "warning",
                    str(diagnostics) if diagnostics else "No diagnostics bundle is available.",
                )
            )
            if not diagnostics:
                recommendations.append("Export a diagnostics bundle for easier troubleshooting.")

            report_points = 10 if report else 0
            report_status = "passed" if report else "warning" if current_dashboard.total_files else "neutral"
            report_detail = str(report) if report else "No generation report is available."
            breakdown.append(HealthScoreItem("Report", report_points, 10, report_status, report_detail))
            if current_dashboard.total_files and not report:
                recommendations.append("Run a Mock generation to create the first report for this queue.")

        if development_available:
            if not check.available:
                warnings.append("No development check result is available.")
                recommendations.insert(0, "Run all checks.")
            elif not check.success or not check.compile_passed or not check.ruff_passed:
                warnings.append("The latest development check needs attention.")
                recommendations.insert(0, "Run all checks and review the latest artifact output.")
            elif self._is_stale(check):
                warnings.append("The latest development check is older than three days.")
                recommendations.insert(0, "Run all checks to refresh project health.")
        else:
            recommendations.append("Use Runtime Health, Provider Output Verification, and diagnostics in packaged runtime.")

        score = max(0, min(100, sum(item.points for item in breakdown)))
        if development_available and check.available and not check.success:
            level, label = "error", "Checks failing"
        elif score >= 85:
            level, label = "healthy", "Ready"
        elif score >= 60:
            level, label = "warning", "Needs attention"
        else:
            level, label = "error", "Action required"

        if not recommendations:
            recommendations.append("No immediate action is required.")

        return HealthState(
            score=score,
            level=level,
            label=label,
            branch=git.branch,
            git_clean=git.clean,
            project_name=project.name if project else "No project",
            provider=project.provider if project else "—",
            queue_total=current_dashboard.total_files,
            queue_completed=current_dashboard.completed,
            queue_failed=current_dashboard.failed,
            latest_report=report,
            latest_diagnostics=diagnostics,
            check=check,
            breakdown=tuple(breakdown),
            recommendations=tuple(dict.fromkeys(recommendations)),
            warnings=tuple(warnings),
            runtime_domain="packaged" if packaged_runtime else "source",
            development_available=development_available,
            packaged_runtime=packaged_runtime,
        )

    def invalidate(self) -> None:
        """Discard cached repository/artifact metadata after an explicit action."""
        self._metadata_cache = None

    def _metadata(self):
        now = monotonic()
        if self._metadata_cache and now - self._metadata_cache[0] < 3.0:
            return self._metadata_cache[1:]
        metadata = (
            self.git_service.status(),
            self.latest_check(),
            self.report_service.latest_report_dir(),
            self._latest_diagnostics(),
        )
        self._metadata_cache = (now, *metadata)
        return metadata

    def latest_check(self) -> HealthCheckState:
        latest = self.runtime.artifacts_dir / "dev-check" / "latest"
        if not latest.exists():
            return HealthCheckState()
        result_path = latest / "result.json"
        if not result_path.exists():
            return HealthCheckState(
                summary="Development check status is unknown: result.json is missing.",
                artifact_directory=latest,
            )
        try:
            payload = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return HealthCheckState(
                summary="Development check status is unknown: result.json is malformed.",
                artifact_directory=latest,
            )

        steps = payload.get("steps") if isinstance(payload.get("steps"), dict) else {}
        compile_step = steps.get("compileall") if isinstance(steps.get("compileall"), dict) else {}
        pytest_step = steps.get("pytest") if isinstance(steps.get("pytest"), dict) else {}
        ruff_step = steps.get("ruff") if isinstance(steps.get("ruff"), dict) else {}
        success = bool(payload.get("success", False))
        tests_passed = int(pytest_step.get("passed") or 0)
        compile_passed = bool(compile_step.get("success", False))
        ruff_passed = bool(ruff_step.get("success", False))
        summary = str(payload.get("summary") or ("All checks passed" if success else "Latest checks need attention"))
        artifact = payload.get("artifact_directory")
        finished_at = self._parse_finished_at(payload, result_path)
        return HealthCheckState(
            available=True,
            success=success,
            tests_passed=tests_passed,
            compile_passed=compile_passed,
            ruff_passed=ruff_passed,
            summary=summary,
            artifact_directory=Path(artifact) if artifact else latest,
            finished_at=finished_at,
        )

    def markdown_summary(self, state: HealthState) -> str:
        check_icon = "✅" if state.check.success else "❌" if state.check.available else "⚪"
        git_icon = "✅" if state.git_clean else "⚠️"
        report = str(state.latest_report) if state.latest_report else "Not available"
        diagnostics = str(state.latest_diagnostics) if state.latest_diagnostics else "Not available"
        warning_lines = "\n".join(f"- {warning}" for warning in state.warnings) or "- None"
        recommendations = "\n".join(f"- {item}" for item in state.recommendations)
        breakdown = "\n".join(
            f"- {item.name}: **{item.points}/{item.maximum}** — {item.detail}" for item in state.breakdown
        )
        checked_at = state.check.finished_at.astimezone().isoformat(timespec="seconds") if state.check.finished_at else "Unknown"
        return (
            "# S Talking Health Report\n\n"
            f"Generated: {datetime.now().astimezone().isoformat(timespec='seconds')}\n\n"
            "## Overall\n\n"
            f"- Status: **{state.label}**\n"
            f"- Health score: **{state.score}/100**\n"
            f"- Application version: `{app.__version__}`\n\n"
            "## Score breakdown\n\n"
            f"{breakdown}\n\n"
            "## Project\n\n"
            f"- Name: {state.project_name}\n"
            f"- Provider: {state.provider}\n"
            f"- Queue: {state.queue_total} total, {state.queue_completed} completed, {state.queue_failed} failed\n\n"
            "## Development checks\n\n"
            f"- {check_icon} {state.check.summary}\n"
            f"- Tests passed: {state.check.tests_passed or 'Unknown'}\n"
            f"- Compile: {'Passed' if state.check.compile_passed else 'Unknown/failed'}\n"
            f"- Ruff: {'Passed' if state.check.ruff_passed else 'Unknown/failed'}\n"
            f"- Last checked: {checked_at}\n\n"
            "## Git\n\n"
            f"- Branch: `{state.branch}`\n"
            f"- {git_icon} Working tree: {'Clean' if state.git_clean else 'Has changes'}\n\n"
            "## Artifacts\n\n"
            f"- Latest report: `{report}`\n"
            f"- Latest diagnostics: `{diagnostics}`\n\n"
            "## Recommended next actions\n\n"
            f"{recommendations}\n\n"
            "## Warnings\n\n"
            f"{warning_lines}\n"
        )

    def compact_summary(self, state: HealthState) -> str:
        check = f"{state.check.tests_passed} tests passed" if state.check.success and state.check.tests_passed else state.check.summary
        next_action = state.recommendations[0] if state.recommendations else "No immediate action is required."
        return (
            f"S Talking — {state.label} ({state.score}/100)\n"
            f"Project: {state.project_name} | Provider: {state.provider}\n"
            f"Queue: {state.queue_total} total / {state.queue_completed} completed / {state.queue_failed} failed\n"
            f"Checks: {check}\n"
            f"Git: {state.branch} ({'clean' if state.git_clean else 'dirty'})\n"
            f"Next action: {next_action}\n"
            f"Report: {state.latest_report or 'none'}\n"
            f"Diagnostics: {state.latest_diagnostics or 'none'}"
        )

    def _latest_diagnostics(self) -> Path | None:
        if self.diagnostics_service.latest_bundle and self.diagnostics_service.latest_bundle.exists():
            return self.diagnostics_service.latest_bundle
        folder = self.runtime.artifacts_dir / "diagnostics"
        candidates = sorted(folder.glob("S-Talking-Diagnostics-*.zip"), key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0] if candidates else None

    def _runtime_breakdown(
        self,
        *,
        project: ProjectState | None,
        dashboard: DashboardState,
        report: Path | None,
        diagnostics: Path | None,
    ) -> list[HealthScoreItem]:
        items = [
            HealthScoreItem("Runtime initialization", 15, 15, "passed", "Application services initialized."),
            HealthScoreItem("Database and migrations", 15, 15, "passed", str(self.runtime.database_path)),
            HealthScoreItem("Writable data paths", 10, 10, "passed", str(self.runtime.data_dir)),
            HealthScoreItem(
                "Project/source integrity",
                15 if project else 12,
                15,
                "passed" if project else "neutral",
                project.name if project else "No project is open; this is allowed at startup.",
            ),
            HealthScoreItem("Provider readiness", 16, 20, "warning", "Run Provider Output Verification for the selected live provider."),
            HealthScoreItem("Multimedia/output validation", 10, 10, "passed", "Output validation service is available."),
            HealthScoreItem(
                "Diagnostics/report capability",
                10 if diagnostics or report else 8,
                10,
                "passed" if diagnostics or report else "neutral",
                str(diagnostics or report) if diagnostics or report else "Diagnostics and reports can be created when needed.",
            ),
            HealthScoreItem("Temporary-file recovery", 5, 5, "passed", "Startup recovery is available."),
        ]
        if dashboard.failed:
            items.append(HealthScoreItem("Last generation", 0, 0, "warning", f"{dashboard.failed} failed job(s) in current dashboard."))
        return items

    @staticmethod
    def _parse_finished_at(payload: dict, fallback: Path) -> datetime | None:
        raw = payload.get("finished_at") or payload.get("generated_at")
        if isinstance(raw, str):
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                pass
        try:
            return datetime.fromtimestamp(fallback.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None

    @staticmethod
    def _is_stale(check: HealthCheckState) -> bool:
        if not check.finished_at:
            return False
        now = datetime.now(tz=check.finished_at.tzinfo or timezone.utc)
        return (now - check.finished_at).total_seconds() > 3 * 24 * 60 * 60

    @staticmethod
    def _is_packaged_runtime() -> bool:
        return bool(getattr(sys, "frozen", False))
