from __future__ import annotations

from pathlib import Path

from app.bootstrap import create_application_context
from app.config.runtime import RuntimeConfig
from app.container import create_service_container
from app.gui.main import MainWindow
from app.gui.widgets.notification_center import NotificationCard, NotificationCenterWidget
from app.gui.widgets.professional_components import EmptyStateCard, InlineFeedbackBar


def _container(tmp_path: Path):
    return create_service_container(RuntimeConfig.from_root(tmp_path))


def _window(tmp_path: Path) -> MainWindow:
    container = _container(tmp_path)
    return MainWindow(create_application_context(container))


def test_phase29_empty_state_and_feedback_are_reusable(qt_app) -> None:
    calls: list[str] = []
    empty = EmptyStateCard("Nothing here", "Add an item to continue.", icon_name="general.info")
    button = empty.add_action("Add item", lambda: calls.append("add"), primary=True)
    feedback = InlineFeedbackBar()

    empty.show()
    feedback.show()
    qt_app.processEvents()
    button.click()
    feedback.show_message("Saved successfully.", tone="success")

    assert empty.objectName() == "professionalEmptyState"
    assert empty.title_label.text() == "Nothing here"
    assert button.objectName() == "professionalEmptyStatePrimary"
    assert calls == ["add"]
    assert feedback.property("tone") == "success"
    assert feedback.message_label.text() == "Saved successfully."


def test_phase29_notification_center_has_filters_empty_state_and_feedback(qt_app, tmp_path: Path) -> None:
    container = _container(tmp_path)
    widget = NotificationCenterWidget(container.notification_center_service)
    widget.show()
    qt_app.processEvents()

    assert widget.objectName() == "notificationCenter"
    assert widget.search.objectName() == "notificationSearch"
    assert widget.view_filter.count() == 2
    assert widget.content_stack.currentIndex() == 1
    assert widget.empty_state.title_label.text() == "No notifications"
    assert widget.feedback.objectName() == "notificationFeedback"
    widget.close()


def test_phase29_notification_cards_are_readable_and_filterable(qt_app, tmp_path: Path) -> None:
    container = _container(tmp_path)
    container.product_activity_service.notify("warning", "Quota warning", "Only 10% remains.")
    container.product_activity_service.notify("success", "Batch complete", "All files were generated.")
    widget = NotificationCenterWidget(container.notification_center_service)
    widget.show()
    qt_app.processEvents()

    assert widget.list_widget.count() == 2
    first_card = widget.list_widget.itemWidget(widget.list_widget.item(0))
    assert isinstance(first_card, NotificationCard)
    assert first_card.message_label.wordWrap() is True

    widget.severity.setCurrentText("Warning")
    qt_app.processEvents()
    assert widget.list_widget.count() == 1
    assert "Quota warning" in widget.list_widget.itemWidget(widget.list_widget.item(0)).title_label.text()
    widget.close()


def test_phase29_notification_actions_mark_read_and_emit_payload(qt_app, tmp_path: Path) -> None:
    container = _container(tmp_path)
    container.product_activity_service.notify(
        "error",
        "Generation incident",
        "A provider failure needs review.",
        action_label="Open Incident Center",
        action_payload="generation-incident-center",
    )
    widget = NotificationCenterWidget(container.notification_center_service)
    received: list[str] = []
    widget.action_requested.connect(received.append)
    widget.show()
    qt_app.processEvents()

    widget.list_widget.setCurrentRow(0)
    widget.open_selected_action()
    qt_app.processEvents()

    assert received == ["generation-incident-center"]
    assert container.notification_center_service.unread_count() == 0
    assert widget.feedback.property("tone") == "success"
    widget.close()


def test_phase29_mark_all_read_and_unread_filter(qt_app, tmp_path: Path) -> None:
    container = _container(tmp_path)
    for index in range(3):
        container.product_activity_service.notify("info", f"Notice {index}", "Message")
    widget = NotificationCenterWidget(container.notification_center_service)
    widget.show()
    qt_app.processEvents()

    widget.view_filter.setCurrentIndex(1)
    assert widget.list_widget.count() == 3
    widget.mark_all_read()
    qt_app.processEvents()

    assert container.notification_center_service.unread_count() == 0
    assert widget.content_stack.currentIndex() == 1
    assert widget.feedback.property("tone") == "success"
    widget.close()


def test_phase29_main_uses_shared_empty_state_and_dispatches_actions(qt_app, tmp_path: Path) -> None:
    window = _window(tmp_path)
    window.show()
    qt_app.processEvents()
    opened: list[str] = []
    window.open_generation_history = lambda: opened.append("history")

    assert isinstance(window.empty_state, EmptyStateCard)
    assert window.empty_add_source_button.objectName() == "professionalEmptyStatePrimary"
    assert window.notification_center.action_requested is not None
    assert window.handle_notification_action("generation-history") is True
    assert opened == ["history"]
    assert window.handle_notification_action("not-a-real-action") is False
    window.close()
