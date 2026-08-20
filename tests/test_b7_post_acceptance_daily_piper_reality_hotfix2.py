from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.config.settings import load_settings
from app.container import create_service_container
from app.gui.main import MainWindow
from app.models import AppSettings
from app.providers.piper import PiperProvider
from app.providers.piper_installation import managed_piper_executable_candidates
from app.services.offline_tts_engine_service import OfflineTTSEngineService
from app.services.workspace_profile_service import WorkspaceProfileService


ROOT = Path(__file__).resolve().parents[1]
MAIN = ROOT / "app" / "gui" / "main.py"
FROZEN_MAIN = ROOT / "app" / "frozen_main.py"
LOCAL_MIGRATION = ROOT / "scripts" / "migrate_local_engines_to_portable.ps1"


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    return MainWindow(create_application_context(create_service_container(runtime)))


def _portable_managed_piper(runtime: RuntimeConfig) -> tuple[Path, Path]:
    executable = runtime.data_dir.parent / "local-engines" / "piper" / ".venv" / "Scripts" / "piper.exe"
    executable.parent.mkdir(parents=True, exist_ok=True)
    executable.write_bytes(b"stub-piper")

    model = (
        runtime.data_dir.parent
        / "offline-voices"
        / "piper"
        / "da_DK-talesyntese-medium"
        / "da_DK-talesyntese-medium.onnx"
    )
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(b"onnx-model")
    Path(f"{model}.json").write_text(
        json.dumps(
            {
                "dataset": "talesyntese",
                "language": {"code": "da_DK"},
                "audio": {"sample_rate": 22050},
                "num_speakers": 1,
            }
        ),
        encoding="utf-8",
    )
    return executable, model


class _NoPythonPiperRuntime:
    @staticmethod
    def api_available() -> bool:
        return False


def test_b7_h2_empty_queue_expands_above_bottom_pinned_accordion(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.resize(1600, 900)
    window.show()
    window.render_queue()
    qt_app.processEvents()

    queue = window.queue_workspace
    body = queue.body_layout
    empty_index = body.indexOf(window.empty_state_host)
    table_index = body.indexOf(window.table)
    accordion_index = body.indexOf(window.queue_tools_accordion)

    assert empty_index >= 0
    assert table_index >= 0
    assert accordion_index > table_index
    assert body.stretch(empty_index) == 1
    assert body.stretch(table_index) == 1
    assert body.itemAt(accordion_index).alignment() & Qt.AlignBottom
    assert window.empty_state_host.isVisible()
    assert window.table.isHidden()
    assert queue.body_host.rect().bottom() - window.queue_tools_accordion.geometry().bottom() <= 8
    window.close()


def test_b7_h2_start_blocks_on_real_safety_issue_before_launch_assurance() -> None:
    source = MAIN.read_text(encoding="utf-8")
    start = source.split("def start(self):", 1)[1].split("def pause", 1)[0]

    safety_state = start.index("state=self.run_preflight(write_report=False)")
    blocked = start.index("if not state.can_start:", safety_state)
    blocker_surface = start.index("self.block_generation_on_safety_state(state)", blocked)
    first_launch_assurance = start.index("launch_assurance_service.verify_launch(")
    confirmation = start.index("generation_confirmation_service.evaluate")

    assert safety_state < blocked < blocker_surface < first_launch_assurance < confirmation
    blocker = source.split("def block_generation_on_safety_state", 1)[1].split(
        "def show_preflight_dialog", 1
    )[0]
    assert "Generation blocked" in blocker
    assert "suggested_action" in blocker
    assert "Run Preflight explicitly" not in blocker


def test_b7_h2_context_change_routes_to_start_not_mandatory_explicit_preflight() -> None:
    source = MAIN.read_text(encoding="utf-8")
    block = source.split("def reject_launch_context_change", 1)[1].split(
        "def current_preflight_state", 1
    )[0]
    assert "Press Start again to refresh the no-audio safety validation" in block
    assert "Start Generation" in block
    assert "Run Preflight explicitly again" not in block
    assert "run_preflight(" not in block
    assert "generation_controller.start(" not in block


def test_b7_h2_offline_inventory_finds_migrated_piper_without_path_launcher(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    executable, model = _portable_managed_piper(runtime)
    service = OfflineTTSEngineService(
        runtime,
        module_finder=lambda _name: None,
        executable_finder=lambda _name: None,
    )

    snapshot = service.snapshot(
        "piper",
        AppSettings(provider="piper", piper_model_path=str(model)),
    )

    assert snapshot.installed is True
    assert snapshot.module_available is False
    assert snapshot.runtime_mode == "legacy-cli"
    assert Path(snapshot.executable_path or "").resolve() == executable.resolve()
    assert snapshot.ready is True
    assert any(Path(voice.model_path).resolve() == model.resolve() for voice in snapshot.voices)


def test_b7_h2_piper_provider_uses_same_managed_executable_without_path_mutation(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    runtime.ensure_directories()
    executable, model = _portable_managed_piper(runtime)

    provider = PiperProvider(
        AppSettings(provider="piper", piper_model_path=str(model)),
        runtime=_NoPythonPiperRuntime(),
        runtime_config=runtime,
        executable_finder=lambda _name: None,
    )

    assert provider.runtime_mode == "legacy-cli"
    assert Path(provider.exe or "").resolve() == executable.resolve()
    assert provider.validate_configuration(provider.settings).ok is True


def test_b7_h2_managed_executable_contract_matches_portable_migration_root(tmp_path: Path) -> None:
    runtime = RuntimeConfig.from_root(tmp_path)
    expected = runtime.data_dir.parent / "local-engines" / "piper" / ".venv" / "Scripts" / "piper.exe"
    assert managed_piper_executable_candidates(runtime)[0] == expected

    migration = LOCAL_MIGRATION.read_text(encoding="utf-8")
    assert 'local-engines\\piper\\.venv\\Scripts\\piper.exe' in migration
    assert "--local-engines-runtime-verify" in migration
    assert "--local-engines-require-piper" in migration
    assert "LOCAL_ENGINES_RUNTIME_VERIFY=PASS" in migration


def test_b7_h2_migrated_json_state_is_bom_compatible_and_rewritten_without_bom(tmp_path: Path) -> None:
    settings_path = tmp_path / "settings.json"
    settings_path.write_text(json.dumps({"provider": "mock"}), encoding="utf-8-sig")
    assert load_settings(settings_path).provider == "mock"

    workspace_path = tmp_path / "workspace-profiles.json"
    workspace_path.write_text(json.dumps({"last_profile": "Compact"}), encoding="utf-8-sig")
    assert WorkspaceProfileService(workspace_path).last_profile == "Compact"

    migration = LOCAL_MIGRATION.read_text(encoding="utf-8")
    assert migration.count("[System.Text.UTF8Encoding]::new($false)") >= 2


def test_b7_h2_frozen_verifier_proves_product_level_piper_discovery_without_synthesis() -> None:
    source = FROZEN_MAIN.read_text(encoding="utf-8")
    handler = source.split("def _handle_local_engines_runtime_verify", 1)[1].split(
        "def _handle_provider_accounts_runtime_verify", 1
    )[0]
    assert "OfflineTTSEngineService(runtime)" in handler
    assert "PiperProvider(" in handler
    assert "LOCAL_ENGINES_PIPER_INSTALLED" in handler
    assert "LOCAL_ENGINES_PIPER_EXECUTABLE_PRESENT" in handler
    assert "LOCAL_ENGINES_PIPER_VOICE_COUNT" in handler
    assert "LOCAL_ENGINES_PIPER_PROVIDER_RESOLUTION" in handler
    assert "LOCAL_ENGINES_RUNTIME_VERIFY" in handler
    assert ".synthesize(" not in handler
    assert ".warm(" not in handler
    assert ".import_" not in handler
