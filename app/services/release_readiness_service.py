from __future__ import annotations

import importlib.util
import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

import app
from app.config.runtime import RuntimeConfig
from app.csv_loader import diagnose_csv
from app.database.connection import Database
from app.models import AppSettings, ProviderStatusState, ReleaseReadinessState, TTSJob
from app.release import RELEASE_CHANNEL, build_metadata
from app.services.diagnostics_service import DiagnosticsService
from app.services.git_service import GitService
from app.services.preflight_service import PreflightService
from app.services.report_service import ReportService
from app.services.voice_service import VoiceService


class ReleaseReadinessService:
    def __init__(
        self,
        runtime: RuntimeConfig,
        database: Database,
        git_service: GitService,
        report_service: ReportService,
        diagnostics_service: DiagnosticsService,
        preflight_service: PreflightService,
        voice_service: VoiceService,
    ) -> None:
        self.runtime = runtime
        self.database = database
        self.git_service = git_service
        self.report_service = report_service
        self.diagnostics_service = diagnostics_service
        self.preflight_service = preflight_service
        self.voice_service = voice_service

    def snapshot(
        self,
        *,
        csv_path: Path | None = None,
        jobs: list[TTSJob] | None = None,
        settings: AppSettings | None = None,
        output_dir: Path | None = None,
        preflight_status: str | None = None,
    ) -> ReleaseReadinessState:
        check = self._latest_check()
        csv_status, valid, rejected = self._csv_status(csv_path)
        database_status, migration_status = self._database_status()
        provider = self.provider_status(settings or AppSettings(provider="mock"))
        git = self.git_service.status()
        return ReleaseReadinessState(
            version=app.__version__,
            release_channel=RELEASE_CHANNEL,
            branch=git.branch,
            dirty=not git.clean,
            compile_status="passed" if check.get("steps", {}).get("compileall", {}).get("success") else "unknown",
            test_count=int(check.get("steps", {}).get("pytest", {}).get("passed") or 0),
            ruff_status="passed" if check.get("steps", {}).get("ruff", {}).get("success") else "unknown",
            database_status=database_status,
            migration_status=migration_status,
            csv_source_status=csv_status,
            valid_rows=valid,
            rejected_rows=rejected,
            preflight_status=preflight_status or self._preflight_status(jobs or [], settings, output_dir, csv_path),
            provider_status=provider,
            latest_report=self.report_service.latest_report_dir(),
            latest_diagnostics=self.diagnostics_service.latest_bundle,
            temporary_file_status=self._temporary_file_status(),
            secret_redaction_status=self.secret_redaction_status(),
            artifact_folder=self.runtime.artifacts_dir / "release-check" / "latest",
        )

    def provider_status(self, settings: AppSettings) -> ProviderStatusState:
        if settings.provider == "elevenlabs":
            cached = self.voice_service.cached_catalog(settings)
            if cached:
                remaining = cached.account.remaining_characters if cached.account else None
                tier = cached.account.tier if cached.account else "unknown"
                voice_ids = {voice.voice_id for voice in cached.voices}
                model_ids = {model.model_id for model in cached.models if model.can_do_text_to_speech}
                return ProviderStatusState(
                    provider=settings.provider,
                    connection_state="cached",
                    account_tier=tier,
                    remaining_quota=remaining,
                    selected_voice=settings.voice_id,
                    selected_model=settings.model_id,
                    model_availability="available" if settings.model_id in model_ids else "unknown",
                    voice_accessibility="available" if settings.voice_id in voice_ids else "unknown",
                    last_catalog_refresh="cached",
                )
            return ProviderStatusState(
                provider=settings.provider,
                connection_state="not tested",
                selected_voice=settings.voice_id,
                selected_model=settings.model_id,
            )
        if settings.provider == "piper":
            model = Path(settings.piper_model_path or "")
            try:
                python_api = importlib.util.find_spec("piper") is not None
            except (ImportError, ModuleNotFoundError, ValueError):
                python_api = False
            available = python_api or bool(shutil.which("piper"))
            model_ok = bool(
                settings.piper_model_path
                and model.is_file()
                and Path(f"{model}.json").is_file()
            )
            return ProviderStatusState(
                provider="piper",
                connection_state="ready" if available and model_ok else "setup needed",
                selected_voice=str(model) if settings.piper_model_path else "",
                selected_model="piper-local" if model_ok else "",
                model_availability="available" if model_ok else "missing model",
                voice_accessibility="local" if model_ok else "missing",
            )
        return ProviderStatusState(
            provider=settings.provider,
            connection_state="ready",
            selected_voice=settings.voice_id or "mock",
            selected_model=settings.model_id,
            model_availability="available",
            voice_accessibility="available",
        )

    def export(self, state: ReleaseReadinessState) -> Path:
        folder = self.runtime.artifacts_dir / "release-readiness"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "release-readiness.json"
        payload = {
            "build_metadata": build_metadata(),
            "state": self._jsonable(state),
        }
        path.write_text(json.dumps(self.report_service.sanitize(payload), indent=2, ensure_ascii=False), encoding="utf-8")
        return path

    def copy_summary_text(self, state: ReleaseReadinessState) -> str:
        return (
            f"S Talking {state.version} ({state.release_channel})\n"
            f"Git: {state.branch} ({'dirty' if state.dirty else 'clean'})\n"
            f"Checks: compile={state.compile_status}, tests={state.test_count}, ruff={state.ruff_status}\n"
            f"CSV: {state.valid_rows} valid / {state.rejected_rows} rejected\n"
            f"Preflight: {state.preflight_status}\n"
            f"Provider: {state.provider_status.provider} / {state.provider_status.connection_state}\n"
            f"Ready: {'yes' if state.ready else 'needs attention'}"
        )

    def secret_redaction_status(self) -> str:
        sample = "api_key=sk_test_secret Bearer abc.def token"
        redacted = self.report_service.sanitize_text(sample)
        return "passed" if "sk_test_secret" not in redacted and "Bearer abc.def" not in redacted else "failed"

    def create_portable_zip(self) -> Path:
        dist = self.runtime.artifacts_dir / "package" / f"S-Talking-{app.__version__}-portable"
        if dist.exists():
            shutil.rmtree(dist)
        dist.mkdir(parents=True, exist_ok=True)
        excluded_names = {
            ".git",
            ".venv",
            ".pytest-tmp",
            ".pytest_cache",
            ".ruff_cache",
            ".mypy_cache",
            "artifacts",
            "reports",
            "output",
            "outputs",
            "logs",
            "cache",
            "data",
            "credentials",
            "__pycache__",
            "settings.json",
            "api-profiles.json",
            "workspace-profiles.json",
        }
        for path in self.runtime.app_root.iterdir():
            if path.name in excluded_names:
                continue
            target = dist / path.name
            if path.is_dir():
                shutil.copytree(path, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo", ".ruff_cache", ".pytest_cache", ".mypy_cache", "*.egg-info", "*.db", "*.sqlite", "*.sqlite3", "*.mp3", "*.wav"))
            else:
                shutil.copy2(path, target)
        (dist / "RUN-S-TALKING.bat").write_text("@echo off\r\npy -m app.gui.main\r\n", encoding="utf-8")
        zip_path = dist.parent / f"{dist.name}.zip"
        if zip_path.exists():
            zip_path.unlink()
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as archive:
            for path in dist.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(dist.parent))
        return zip_path

    def _latest_check(self) -> dict[str, Any]:
        for root in [self.runtime.artifacts_dir / "release-check" / "latest", self.runtime.artifacts_dir / "dev-check" / "latest"]:
            path = root / "result.json"
            if path.exists():
                try:
                    return json.loads(path.read_text(encoding="utf-8-sig"))
                except Exception:
                    return {}
        return {}

    def _csv_status(self, csv_path: Path | None) -> tuple[str, int, int]:
        if not csv_path:
            return "no CSV selected", 0, 0
        if not csv_path.exists():
            return "missing", 0, 0
        try:
            state = diagnose_csv(csv_path)
        except Exception as exc:
            return f"error: {exc}", 0, 0
        return "ready" if state.rejected_rows == 0 else "needs repair", state.valid_rows, state.rejected_rows

    def _database_status(self) -> tuple[str, str]:
        try:
            self.database.initialize()
            applied = self.database.applied_schema_versions()
            expected = self.database.expected_schema_version
            migration_ok = applied == tuple(range(1, expected + 1))
            integrity_ok = self.database.quick_check() == "ok"
            foreign_keys_ok = not self.database.foreign_key_violations()
            return (
                "passed" if integrity_ok and foreign_keys_ok else "failed",
                "passed" if migration_ok else "failed",
            )
        except Exception:
            return "failed", "failed"

    def _preflight_status(
        self,
        jobs: list[TTSJob],
        settings: AppSettings | None,
        output_dir: Path | None,
        csv_path: Path | None,
    ) -> str:
        if not jobs or not settings:
            return "not checked"
        try:
            state = self.preflight_service.run(
                jobs=jobs,
                settings=settings,
                output_dir=output_dir or self.runtime.default_output_dir,
                csv_path=csv_path,
                project_name="Release readiness",
            )
        except Exception as exc:
            return f"error: {exc}"
        return state.status

    def _temporary_file_status(self) -> str:
        candidates = list(self.runtime.default_output_dir.glob("*.tmp")) + list(self.runtime.default_output_dir.glob("*.partial"))
        return "passed" if not candidates else f"{len(candidates)} stale temp file(s)"

    def _jsonable(self, value: Any) -> Any:
        if hasattr(value, "__dict__"):
            return {key: self._jsonable(item) for key, item in value.__dict__.items()}
        if isinstance(value, Path):
            return str(value)
        return value
