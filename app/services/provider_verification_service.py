from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from app.config.runtime import RuntimeConfig
from app.models.domain import AppSettings
from app.provider_factory import create_provider
from app.services.output_validation_service import OutputValidationService
from app.services.voice_service import VoiceCatalog, VoiceService

SECRET_VALUE = re.compile(r"(sk_[A-Za-z0-9_=-]+|xi-api-key[:=]\s*[^,\s]+|Bearer\s+[A-Za-z0-9._=-]+)", re.IGNORECASE)


@dataclass(frozen=True)
class ProviderVerificationCheck:
    name: str
    success: bool
    message: str
    request_id: str | None = None


@dataclass(frozen=True)
class ProviderVerificationReport:
    report_dir: Path
    json_path: Path
    markdown_path: Path
    html_path: Path
    success: bool
    checks: tuple[ProviderVerificationCheck, ...] = field(default_factory=tuple)


class ProviderVerificationService:
    """Runs safe live provider checks and writes redacted reports."""

    def __init__(
        self,
        runtime: RuntimeConfig,
        voice_service: VoiceService,
        *,
        provider_factory: Callable[[AppSettings], object] = create_provider,
    ) -> None:
        self.runtime = runtime
        self.voice_service = voice_service
        self.provider_factory = provider_factory

    def run_elevenlabs(
        self,
        settings: AppSettings,
        *,
        profile_name: str,
        sample_text: str,
        project_name: str = "default",
    ) -> ProviderVerificationReport:
        started = datetime.now(timezone.utc)
        report_dir = self._report_dir(project_name, started)
        checks: list[ProviderVerificationCheck] = []
        account: dict[str, object] = {}
        dictionary_capabilities: dict[str, bool] = {}
        preview: dict[str, object] = {}
        catalog: VoiceCatalog | None = None

        test_settings = settings.model_copy(update={"provider": "elevenlabs"})
        try:
            self.voice_service.invalidate_provider_cache(test_settings)
            # The cache was invalidated immediately above, so a normal refresh
            # is guaranteed to hit the provider. Avoid requiring every test fake
            # and third-party VoiceService implementation to accept the newer
            # ``force`` keyword.
            catalog = self.voice_service.refresh_catalog(test_settings)
            account = self._account_snapshot(catalog)
            checks.append(
                ProviderVerificationCheck(
                    "Account/catalog",
                    True,
                    f"{len(catalog.voices)} voice(s), {sum(1 for model in catalog.models if model.can_do_text_to_speech)} TTS model(s).",
                )
            )
        except Exception as exc:
            checks.append(ProviderVerificationCheck("Account/catalog", False, self._safe_text(str(exc))))

        provider = None
        try:
            provider = self.provider_factory(test_settings)
            dictionary_capabilities = {
                "list": callable(getattr(provider, "list_pronunciation_dictionaries", None)),
                "create_from_rules": callable(getattr(provider, "create_pronunciation_dictionary_from_rules", None)),
                "create_from_file": callable(getattr(provider, "create_pronunciation_dictionary_from_file", None)),
                "add_rules": callable(getattr(provider, "add_pronunciation_dictionary_rules", None)),
                "set_rules": callable(getattr(provider, "set_pronunciation_dictionary_rules", None)),
                "remove_rules": callable(getattr(provider, "remove_pronunciation_dictionary_rules", None)),
                "archive": callable(getattr(provider, "delete_pronunciation_dictionary", None)),
                "download_version": callable(getattr(provider, "download_pronunciation_dictionary_version", None)),
            }
            checks.append(
                ProviderVerificationCheck(
                    "Dictionary endpoint capability",
                    all(dictionary_capabilities.values()),
                    ", ".join(key for key, value in dictionary_capabilities.items() if value) or "No dictionary endpoints available.",
                )
            )
            preview_settings = self._preview_settings(test_settings, catalog)
            if preview_settings.voice_id and preview_settings.model_id:
                synthesize = getattr(provider, "synthesize_with_metadata", None)
                if not callable(synthesize):
                    raise RuntimeError("Provider does not expose preview metadata.")
                metadata = synthesize(sample_text, preview_settings)
                preview = {
                    "sample_characters": len(sample_text),
                    "voice_id": preview_settings.voice_id,
                    "model_id": preview_settings.model_id,
                    "request_id": metadata.get("request_id"),
                    "character_cost": metadata.get("character_cost"),
                    "audio_bytes": len(metadata.get("audio") or b""),
                }
                checks.append(
                    ProviderVerificationCheck(
                        "Minimal preview",
                        bool(metadata.get("audio")),
                        f"{len(metadata.get('audio') or b'')} audio byte(s).",
                        request_id=str(metadata.get("request_id") or "") or None,
                    )
                )
                self.voice_service.invalidate_provider_cache(test_settings)
            else:
                checks.append(ProviderVerificationCheck("Minimal preview", False, "No accessible voice/model was available."))
        except Exception as exc:
            checks.append(ProviderVerificationCheck("Minimal preview", False, self._safe_text(str(exc))))
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()

        finished = datetime.now(timezone.utc)
        payload = {
            "schema_version": 1,
            "started_at": started.isoformat(),
            "finished_at": finished.isoformat(),
            "provider": "elevenlabs",
            "profile_display_name": self._safe_text(profile_name),
            "safe_fingerprint": self._fingerprint(settings.api_key),
            "success": all(check.success for check in checks),
            "account": account,
            "voice_count": len(catalog.voices) if catalog else 0,
            "tts_model_count": sum(1 for model in catalog.models if model.can_do_text_to_speech) if catalog else 0,
            "dictionary_endpoint_capability": dictionary_capabilities,
            "preview": preview,
            "checks": [check.__dict__ for check in checks],
        }
        self._write_reports(report_dir, payload)
        return ProviderVerificationReport(
            report_dir=report_dir,
            json_path=report_dir / "verification.json",
            markdown_path=report_dir / "verification.md",
            html_path=report_dir / "verification.html",
            success=bool(payload["success"]),
            checks=tuple(checks),
        )

    def run_output_sample(
        self,
        settings: AppSettings,
        *,
        sample_text: str = "S Talking provider output verification.",
        project_name: str = "default",
    ) -> ProviderVerificationReport:
        started = datetime.now(timezone.utc)
        report_dir = self._report_dir(project_name, started)
        checks: list[ProviderVerificationCheck] = []
        provider = None
        output_path = report_dir / f"provider-sample{settings.file_extension if settings.provider not in {'mock', 'piper'} else '.wav'}"
        try:
            provider = self.provider_factory(settings)
            validation = provider.validate_configuration(settings)
            checks.append(ProviderVerificationCheck("Setup", validation.ok, self._safe_text(validation.message)))
            if not validation.ok:
                raise RuntimeError(validation.message)
            audio = provider.synthesize(sample_text, settings)
            result = OutputValidationService.finalize_atomic(output_path, audio)
            checks.append(ProviderVerificationCheck("Audio output", result.ok, result.message))
        except Exception as exc:
            checks.append(ProviderVerificationCheck("Audio output", False, self._safe_text(str(exc))))
        finally:
            close = getattr(provider, "close", None)
            if callable(close):
                close()
        payload = {
            "schema_version": 1,
            "started_at": started.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "provider": settings.provider,
            "success": all(check.success for check in checks),
            "output_path": str(output_path) if output_path.exists() else None,
            "checks": [check.__dict__ for check in checks],
        }
        self._write_reports(report_dir, payload)
        return ProviderVerificationReport(
            report_dir=report_dir,
            json_path=report_dir / "verification.json",
            markdown_path=report_dir / "verification.md",
            html_path=report_dir / "verification.html",
            success=bool(payload["success"]),
            checks=tuple(checks),
        )

    def _preview_settings(self, settings: AppSettings, catalog: VoiceCatalog | None) -> AppSettings:
        voice_id = settings.voice_id
        model_id = settings.model_id
        if catalog:
            if not voice_id and catalog.voices:
                voice_id = catalog.voices[0].voice_id
            if not model_id and catalog.models:
                model_id = catalog.models[0].model_id
        return settings.model_copy(update={"voice_id": voice_id, "model_id": model_id})

    def _report_dir(self, project_name: str, timestamp: datetime) -> Path:
        safe_project = re.sub(r"[^A-Za-z0-9_.-]+", "_", project_name).strip("._") or "default"
        report_dir = self.runtime.reports_dir / safe_project / "provider-verification" / timestamp.strftime("%Y%m%d-%H%M%S")
        report_dir.mkdir(parents=True, exist_ok=True)
        return report_dir

    @staticmethod
    def _account_snapshot(catalog: VoiceCatalog) -> dict[str, object]:
        if catalog.account is None:
            return {}
        return {
            "tier": catalog.account.tier,
            "status": catalog.account.status,
            "character_count": catalog.account.character_count,
            "character_limit": catalog.account.character_limit,
            "remaining_characters": catalog.account.remaining_characters,
            "refreshed_at": catalog.refreshed_at,
        }

    def _write_reports(self, report_dir: Path, payload: dict[str, object]) -> None:
        safe_payload = json.loads(self._safe_text(json.dumps(payload, ensure_ascii=False)))
        (report_dir / "verification.json").write_text(
            json.dumps(safe_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        checks = safe_payload.get("checks") if isinstance(safe_payload.get("checks"), list) else []
        lines = [
            "# Provider Verification",
            "",
            f"- Provider: {safe_payload.get('provider')}",
            f"- Profile: {safe_payload.get('profile_display_name')}",
            f"- Fingerprint: {safe_payload.get('safe_fingerprint')}",
            f"- Success: {safe_payload.get('success')}",
            "",
            "## Checks",
        ]
        for check in checks:
            if isinstance(check, dict):
                status = "PASS" if check.get("success") else "FAIL"
                lines.append(f"- {status}: {check.get('name')} - {check.get('message')}")
        markdown = "\n".join(lines) + "\n"
        (report_dir / "verification.md").write_text(markdown, encoding="utf-8")
        body = "".join(f"<li>{html.escape(line[2:])}</li>" for line in lines if line.startswith("- "))
        html_doc = f"<!doctype html><meta charset='utf-8'><title>Provider Verification</title><h1>Provider Verification</h1><ul>{body}</ul>"
        (report_dir / "verification.html").write_text(html_doc, encoding="utf-8")

    @staticmethod
    def _fingerprint(value: str) -> str:
        if not value:
            return "no-key"
        import hashlib

        return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _safe_text(value: str) -> str:
        return SECRET_VALUE.sub("[REDACTED]", value)
