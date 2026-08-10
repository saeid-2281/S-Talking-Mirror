from __future__ import annotations

from types import SimpleNamespace

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.dialogs.provider_account_editor_dialog import ProviderAccountEditorDialog
from app.gui.dialogs.provider_accounts_dialog import ProviderAccountsDialog
from app.models import AppSettings
from app.models.api_profile import ApiProfileStatus
from app.services.api_profile_service import ApiProfileService
from app.services.provider_accounts_center_service import ProviderAccountsCenterService
from app.services.provider_catalog_service import ProviderCatalogService
from app.services.secure_credentials import SecureCredentialStore


def _service(tmp_path) -> ApiProfileService:
    return ApiProfileService(
        tmp_path / "api-profiles.json",
        SecureCredentialStore(tmp_path / "credentials"),
    )


def test_phase105_managed_provider_inventory_is_registry_driven(tmp_path) -> None:
    profiles = _service(tmp_path)
    center = ProviderAccountsCenterService(profiles, ProviderCatalogService())

    assert center.managed_provider_ids() == (
        "elevenlabs",
        "openai",
        "azure",
        "google",
        "aws_polly",
        "cartesia",
        "deepgram",
        "resemble",
        "murf",
    )
    assert "mock" not in center.managed_provider_ids()
    assert "piper" not in center.managed_provider_ids()
    assert "kokoro" not in center.managed_provider_ids()


def test_phase105_cross_provider_summary_and_safe_inventory(tmp_path) -> None:
    profiles = _service(tmp_path)
    profiles.create_profile(
        "OpenAI Primary",
        provider="openai",
        api_key="sk_SECRET_OPENAI",
        active=True,
    )
    azure = profiles.create_profile(
        "Azure EU",
        provider="azure",
        api_key="azure-secret",
        active=True,
        metadata={"region": "northeurope"},
    )
    profiles.create_profile(
        "Google ADC",
        provider="google",
        active=True,
        metadata={"project_id": "tts-prod"},
    )
    azure.status = ApiProfileStatus.UNAVAILABLE
    azure.last_error = "network unavailable"
    profiles.update_profile(azure)

    center = ProviderAccountsCenterService(profiles, ProviderCatalogService())
    overview = center.overview()
    azure_summary = center.provider_summary("azure")
    inventory = center.safe_inventory_summary()

    assert overview.managed_provider_count == 9
    assert overview.configured_provider_count == 3
    assert overview.account_count == 3
    assert overview.active_provider_count == 3
    assert overview.attention_account_count >= 1
    assert azure_summary.attention_count == 1
    assert "OpenAI Primary" in inventory
    assert "Azure EU" in inventory
    assert "Google ADC" in inventory
    assert "sk_SECRET_OPENAI" not in inventory
    assert "azure-secret" not in inventory


def test_phase105_action_policy_distinguishes_saved_and_external_credentials(tmp_path) -> None:
    profiles = _service(tmp_path)
    openai = profiles.create_profile(
        "OpenAI",
        provider="openai",
        api_key="sk_TEST",
    )
    google = profiles.create_profile(
        "Google",
        provider="google",
        metadata={"project_id": "demo"},
    )
    center = ProviderAccountsCenterService(profiles, ProviderCatalogService())

    openai_policy = center.action_policy(openai)
    google_policy = center.action_policy(google)

    assert openai_policy.can_replace_secret is True
    assert openai_policy.can_use_temporary_secret is True
    assert google_policy.can_replace_secret is False
    assert google_policy.can_use_temporary_secret is False
    assert google_policy.can_edit_metadata is True


def test_phase105_move_profile_is_scoped_to_one_provider(tmp_path) -> None:
    profiles = _service(tmp_path)
    openai_a = profiles.create_profile("OpenAI A", provider="openai", api_key="a", priority=1)
    openai_b = profiles.create_profile("OpenAI B", provider="openai", api_key="b", priority=2)
    azure_a = profiles.create_profile(
        "Azure A",
        provider="azure",
        api_key="z",
        priority=40,
        metadata={"region": "northeurope"},
    )
    azure_b = profiles.create_profile(
        "Azure B",
        provider="azure",
        api_key="y",
        priority=50,
        metadata={"region": "westeurope"},
    )

    reordered = profiles.move_profile(openai_b.profile_id, -1)

    assert [item.profile_id for item in reordered] == [openai_b.profile_id, openai_a.profile_id]
    azure_after = profiles.list_profiles("azure")
    assert [(item.profile_id, item.priority) for item in azure_after] == [
        (azure_a.profile_id, 40),
        (azure_b.profile_id, 50),
    ]


def test_phase105_editor_is_provider_aware(qt_app, tmp_path) -> None:
    catalog = ProviderCatalogService()
    openai_editor = ProviderAccountEditorDialog(catalog.manifest_for("openai"))
    google_editor = ProviderAccountEditorDialog(catalog.manifest_for("google"))
    azure_editor = ProviderAccountEditorDialog(catalog.manifest_for("azure"))

    assert openai_editor.secret_edit is not None
    assert google_editor.secret_edit is None
    assert set(google_editor.metadata_edits) == {
        "credential_reference",
        "project_id",
        "api_endpoint",
    }
    assert set(azure_editor.metadata_edits) == {"region", "endpoint"}

    openai_editor.close()
    google_editor.close()
    azure_editor.close()


def test_phase105_dialog_exposes_all_provider_view_search_and_scoped_activation(qt_app, tmp_path) -> None:
    profiles = _service(tmp_path)
    openai = profiles.create_profile(
        "OpenAI Production",
        provider="openai",
        api_key="openai-key",
        active=True,
    )
    azure = profiles.create_profile(
        "Azure Europe",
        provider="azure",
        api_key="azure-key",
        active=False,
        metadata={"region": "northeurope"},
    )
    catalog = ProviderCatalogService()
    center = ProviderAccountsCenterService(profiles, catalog)
    voice = SimpleNamespace(catalog_store=None, invalidate_provider_cache=lambda *_args, **_kwargs: None)
    current_settings = AppSettings(provider="openai", api_key="temporary")
    dialog = ProviderAccountsDialog(
        profiles,
        voice,
        lambda: current_settings,
        provider_catalog_service=catalog,
        accounts_center_service=center,
    )
    dialog.show()
    qt_app.processEvents()

    all_index = dialog.provider.findData(None)
    assert all_index >= 0
    dialog.provider.setCurrentIndex(all_index)
    qt_app.processEvents()

    assert dialog.provider.currentText() == "All managed providers"
    assert dialog.table.rowCount() == 2
    assert dialog.tabs.isTabEnabled(1) is False
    assert dialog.center_accounts.text() == "Accounts: 2"
    assert dialog.move_up_button.isEnabled() is False
    assert dialog.move_down_button.isEnabled() is False

    dialog.account_search.setText("Azure")
    qt_app.processEvents()
    assert dialog.table.rowCount() == 1
    assert dialog.table.item(0, 1).text() == "Azure Europe"
    assert dialog.table.item(0, 2).text() == "Azure Speech"

    dialog.table.selectRow(0)
    dialog.set_active()
    assert profiles.get_profile(azure.profile_id).active is True
    assert profiles.get_profile(openai.profile_id).active is True
    assert current_settings.provider == "openai"

    dialog.close()


def test_phase105_dialog_disables_secret_actions_for_external_credentials(qt_app, tmp_path) -> None:
    profiles = _service(tmp_path)
    google = profiles.create_profile(
        "Google ADC",
        provider="google",
        active=True,
        metadata={"project_id": "tts"},
    )
    catalog = ProviderCatalogService()
    center = ProviderAccountsCenterService(profiles, catalog)
    voice = SimpleNamespace(catalog_store=None, invalidate_provider_cache=lambda *_args, **_kwargs: None)
    dialog = ProviderAccountsDialog(
        profiles,
        voice,
        lambda: AppSettings(provider="google"),
        provider_catalog_service=catalog,
        accounts_center_service=center,
    )
    dialog.show()
    qt_app.processEvents()
    dialog._select_profile_id(google.profile_id)
    qt_app.processEvents()

    assert dialog.more_actions["Replace key"].isEnabled() is False
    assert dialog.more_actions["Use temporary key"].isEnabled() is False
    assert dialog.more_actions["Provider settings"].isEnabled() is True
    dialog.close()


def test_phase105_context_exposes_shared_accounts_center(tmp_path) -> None:
    context = create_application_context(create_service_container(RuntimeConfig.from_root(tmp_path)))

    assert context.provider_accounts_center_service is context.container.provider_accounts_center_service
    assert context.provider_accounts_center_service.profiles is context.api_profile_service
    assert context.provider_accounts_center_service.catalog is context.provider_catalog_service


def test_phase105_does_not_change_database_schema(tmp_path) -> None:
    from app.database.connection import Database

    database = Database(tmp_path / "phase105-schema.db")
    database.initialize()
    assert database.applied_schema_versions()[-1] == 23
