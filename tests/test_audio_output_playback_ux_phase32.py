from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.application_shell import ActivityCenter
from app.gui.widgets.audio_player import AudioPlayerWidget
from app.gui.widgets.output_workspace import OutputPlaybackWorkspace, format_file_size


def _window(tmp_path: Path) -> MainWindow:
    runtime = RuntimeConfig.from_root(tmp_path)
    return MainWindow(create_application_context(create_service_container(runtime)))


def test_phase32_file_size_formatting_is_compact_and_predictable() -> None:
    assert format_file_size(0) == "0 B"
    assert format_file_size(1023) == "1,023 B"
    assert format_file_size(1024) == "1.0 KB"
    assert format_file_size(5 * 1024 * 1024) == "5.0 MB"


def test_phase32_activity_center_upgrades_output_tab_without_changing_contract(qt_app, tmp_path: Path) -> None:
    services = create_service_container(RuntimeConfig.from_root(tmp_path))
    center = ActivityCenter()
    legacy_log = center.output_log

    workspace = center.install_output_workspace(services.audio_player_service)

    assert isinstance(workspace, OutputPlaybackWorkspace)
    assert workspace.output_log is legacy_log
    assert center.output_workspace is workspace
    assert [center.tabText(index) for index in range(center.count())] == [
        "Activity",
        "Output",
        "Errors",
    ]
    assert center.widget(1) is workspace
    center.close()


def test_phase32_output_workspace_exposes_professional_player_and_file_actions(qt_app, tmp_path: Path) -> None:
    services = create_service_container(RuntimeConfig.from_root(tmp_path))
    center = ActivityCenter()
    workspace = center.install_output_workspace(services.audio_player_service)

    assert workspace.objectName() == "outputPlaybackWorkspace"
    assert isinstance(workspace.player, AudioPlayerWidget)
    assert workspace.header.objectName() == "outputWorkspaceHeader"
    assert workspace.player_card.objectName() == "outputPlayerCard"
    assert workspace.file_card.objectName() == "outputFileCard"
    assert workspace.open_file_button.objectName() == "outputFileAction"
    assert workspace.copy_info_button.minimumHeight() >= 32
    center.close()


def test_phase32_output_context_shows_file_metadata_without_starting_playback(qt_app, tmp_path: Path) -> None:
    services = create_service_container(RuntimeConfig.from_root(tmp_path))
    center = ActivityCenter()
    workspace = center.install_output_workspace(services.audio_player_service)
    path = tmp_path / "sample.mp3"
    path.write_bytes(b"a" * 2048)

    workspace.set_output_context(path)

    assert workspace.current_path == path
    assert workspace.path_label.toolTip() == str(path)
    assert "MP3" in workspace.metadata_label.text()
    assert "2.0 KB" in workspace.metadata_label.text()
    assert workspace.open_file_button.isEnabled() is True
    center.close()


def test_phase32_audio_player_uses_professional_transport_components(qt_app, tmp_path: Path) -> None:
    services = create_service_container(RuntimeConfig.from_root(tmp_path))
    player = AudioPlayerWidget(services.audio_player_service)

    assert player.objectName() == "audioPlayerWidget"
    assert player.filename.objectName() == "audioPlayerFilename"
    assert player.status.objectName() == "audioPlayerStatus"
    assert player.play_pause.objectName() == "audioPrimaryAction"
    assert player.seek_slider.objectName() == "audioSeekSlider"
    assert player.volume_slider.objectName() == "audioVolumeSlider"
    player.close()


def test_phase32_main_window_installs_output_workspace_and_preserves_log_alias(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    assert isinstance(window.output_workspace, OutputPlaybackWorkspace)
    assert window.output_workspace.output_log is window.output_log
    assert window.activity_tabs.widget(1) is window.output_workspace
    assert window.actions_by_name["Output playback"] is window.open_output_workspace_action
    assert window.open_output_workspace_action.shortcut().toString() == "Ctrl+6"
    window.close()


def test_phase32_show_output_workspace_expands_and_focuses_output_tab(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()

    result = window.show_output_workspace()

    assert result is window.output_workspace
    assert window.activity_tabs.currentWidget() is window.output_workspace
    assert window.activity_tabs.maximumHeight() >= 300
    assert window.view_activity_action.isChecked() is True
    window.close()
