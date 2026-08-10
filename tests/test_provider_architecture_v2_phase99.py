from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.provider_factory import available_provider_ids
from app.provider_registry import DEFAULT_PROVIDER_REGISTRY, ProviderRegistry
from app.models.provider_manifest import ProviderManifest
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.provider_readiness_service import ProviderReadinessService


EXPECTED = ("mock", "piper", "elevenlabs", "openai", "azure", "google", "aws_polly", "kokoro")


def test_phase99_registry_covers_existing_provider_factory_in_stable_order() -> None:
    assert DEFAULT_PROVIDER_REGISTRY.provider_ids()[: len(EXPECTED)] == EXPECTED
    assert set(EXPECTED).issubset(available_provider_ids())
    catalog = ProviderCatalogService()
    assert catalog.provider_ids()[: len(EXPECTED)] == EXPECTED


def test_phase99_manifests_centralize_locality_credentials_dependencies_and_ui_policy() -> None:
    registry = DEFAULT_PROVIDER_REGISTRY
    assert registry.manifest_for("piper").locality == "local"
    assert registry.manifest_for("piper").controls.local_model_path is True
    assert registry.manifest_for("elevenlabs").controls.account_failover is True
    assert registry.manifest_for("openai").controls.api_key is True
    assert registry.manifest_for("azure").optional_dependency == "azure.cognitiveservices.speech"
    assert registry.manifest_for("google").optional_dependency == "google.cloud.texttospeech"
    assert registry.manifest_for("aws_polly").optional_dependency == "boto3"
    assert registry.manifest_for("kokoro").locality == "local"


def test_phase99_registry_rejects_duplicate_stable_ids() -> None:
    manifest = ProviderManifest(
        "sample",
        "Sample",
        locality="cloud",
        credential_mode="profile",
        setup_kind="optional_cloud",
    )
    try:
        ProviderRegistry((manifest, manifest))
    except ValueError as exc:
        assert "Duplicate provider manifest" in str(exc)
    else:  # pragma: no cover - defensive
        raise AssertionError("duplicate provider IDs must be rejected")


def test_phase99_unknown_future_adapter_gets_conservative_nonproduction_manifest() -> None:
    manifest = DEFAULT_PROVIDER_REGISTRY.manifest_for("future_cloud")
    assert manifest.provider_id == "future_cloud"
    assert manifest.locality == "cloud"
    assert manifest.requires_credential is True
    assert manifest.production_supported is False


def test_phase99_catalog_fallback_uses_manifest_instead_of_provider_id_sets(monkeypatch) -> None:
    catalog = ProviderCatalogService()

    def fail_create(_settings):
        raise RuntimeError("adapter unavailable")

    monkeypatch.setattr("app.services.provider_catalog_service.create_provider", fail_create)
    piper = catalog.capabilities_for("piper")
    azure = catalog.capabilities_for("azure")
    assert piper.remote is False
    assert piper.optional_dependency == "piper"
    assert azure.remote is True
    assert azure.requires_credential is True
    assert azure.optional_dependency == "azure.cognitiveservices.speech"


def test_phase99_readiness_consumes_registry_metadata() -> None:
    service = ProviderReadinessService()
    assert service.registry.manifest_for("mock").verified_locally is True
    assert service.registry.manifest_for("openai").retry_ready is True
    assert service.registry.manifest_for("kokoro").optional_dependency == "kokoro"


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase99_provider_workspace_is_populated_from_catalog_registry(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()
    actual = tuple(window.provider.itemText(index) for index in range(window.provider.count()))
    assert actual[: len(EXPECTED)] == EXPECTED


def test_phase99_existing_provider_control_contracts_are_preserved(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    window.provider.setCurrentText("mock")
    qt_app.processEvents()
    assert window.provider_field_rows["api_profile"].isHidden() is True
    assert window.provider_field_rows["piper"].isHidden() is True

    window.provider.setCurrentText("elevenlabs")
    qt_app.processEvents()
    assert window.provider_field_rows["api_profile"].isHidden() is False
    assert window.provider_field_rows["api_key"].isHidden() is False
    assert window.provider_field_rows["failover"].isHidden() is False

    window.provider.setCurrentText("piper")
    qt_app.processEvents()
    assert window.provider_field_rows["piper"].isHidden() is False
    assert window.provider_field_rows["api_profile"].isHidden() is True


def test_phase99_does_not_change_database_schema(tmp_path: Path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "phase99-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23
