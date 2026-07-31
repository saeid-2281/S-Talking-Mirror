from __future__ import annotations

from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.services.workspace_profile_service import WorkspaceProfileService


def test_workspace_profiles_are_persistent_and_distinct(tmp_path) -> None:
    service = WorkspaceProfileService(tmp_path / "profiles.json")
    assert {"Compact", "Standard", "Wide", "Generation", "Review", "Debug", "Focus Mode"}.issubset(service.names())
    assert service.get("Generation").activity_visible is True
    assert service.get("Review").left_dock_visible is False
    service.select("Debug")
    assert WorkspaceProfileService(tmp_path / "profiles.json").last_profile == "Debug"


def test_notification_and_activity_centers_persist_and_prune(tmp_path) -> None:
    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    for index in range(30):
        container.product_activity_service.notify("info", f"Notice {index}", "message")
        container.product_activity_service.activity("generation", f"Event {index}", "message")
    assert len(container.notification_center_service.list()) == 30
    assert len(container.activity_timeline_service.list()) == 30
    first = container.notification_center_service.list()[0]
    container.notification_center_service.mark_read(first.notification_id)
    assert container.notification_center_service.unread_count() == 29
    container.notification_center_service.dismiss(first.notification_id)
    assert len(container.notification_center_service.list()) == 29


def test_main_window_exposes_independent_product_centers(qt_app, tmp_path) -> None:
    from app.bootstrap import create_application_context
    from app.gui.main import MainWindow

    container = create_service_container(RuntimeConfig.from_root(tmp_path))
    window = MainWindow(create_application_context(container))
    assert window.notification_center.objectName() == "notificationCenter"
    assert window.activity_timeline.objectName() == "activityTimeline"
    assert window.notification_dock.widget() is window.notification_center
    assert window.right_tabs.indexOf(window.notification_center) == -1
    assert window.activity_center.activity_workspace.indexOf(window.activity_timeline) >= 0
    assert [window.activity_center.tabText(i) for i in range(window.activity_center.count())] == [
        "Activity",
        "Output",
        "Errors",
    ]
    window.close()
