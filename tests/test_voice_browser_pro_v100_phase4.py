from __future__ import annotations

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.voice_browser import VoiceBrowserDialog
from app.models.domain import AppSettings
from app.models.provider_catalog_sync import CatalogDiagnostics, CatalogSyncResult
from app.services.voice_service import AccountUsage, VoiceCatalog, VoiceItem, VoiceModelItem


def _catalog() -> VoiceCatalog:
    return VoiceCatalog(
        voices=(VoiceItem("mock", "voice-1", "Voice", "da", None, "", {}, False),),
        models=(VoiceModelItem("model-1", "Model", ("da",), True),),
        account=AccountUsage("creator", "active", 100, 1000),
        refreshed_at="2026-07-29T10:00:00+00:00",
    )


def test_catalog_diagnostics_describes_live_catalog(tmp_path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    settings = AppSettings(provider="mock", active_api_profile_id="profile-a")
    diagnostics = context.voice_service.catalog_diagnostics(settings, catalog=_catalog(), latency_ms=123)

    assert diagnostics.state == "Live"
    assert diagnostics.voice_count == 1
    assert diagnostics.model_count == 1
    assert diagnostics.remaining_characters == 900
    assert diagnostics.latency_ms == 123


def test_voice_browser_catalog_sync_controls_and_diagnostics(qt_app, tmp_path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    settings = AppSettings(provider="mock", active_api_profile_id="profile-a")
    dialog = VoiceBrowserDialog(service=context.voice_service, settings_provider=lambda: settings)

    assert dialog.cancel_catalog_button.text() == "Cancel sync"
    assert dialog.catalog_diagnostics_button.text() == "Diagnostics"
    assert dialog.catalog_state_label.text().startswith("Catalog:")

    dialog._catalog_loaded(1, CatalogSyncResult(_catalog(), 77, CatalogDiagnostics.now_iso()))
    assert "77 ms" in dialog.catalog_state_label.text()
    assert dialog.table.rowCount() == 1


def test_cancelled_catalog_result_is_ignored(qt_app, tmp_path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))
    settings = AppSettings(provider="mock", active_api_profile_id="profile-a")
    dialog = VoiceBrowserDialog(service=context.voice_service, settings_provider=lambda: settings)
    dialog._catalog_request_id = 4
    dialog._cancelled_catalog_requests.add(4)

    dialog._catalog_loaded(4, CatalogSyncResult(_catalog(), 10, CatalogDiagnostics.now_iso()))

    assert dialog.catalog is None
    assert dialog.table.rowCount() == 0
