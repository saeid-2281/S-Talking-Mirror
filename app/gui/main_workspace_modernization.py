"""Roadmap 2 A9 Soft Professional main-workspace modernization.

A9 is deliberately presentation-only.  It reorganizes the existing S-Talking
workspace and progressive disclosure without creating alternate generation,
preflight, provider-selection, routing, or source-mutation paths.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QToolButton, QWidget

from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, palette_for


class MainWorkspaceModernizer:
    """Recompose the existing MainWindow surfaces around queue-first hierarchy.

    Every actionable widget continues to belong to MainWindow.  This class only
    reparents/reorders existing presentation surfaces, hides duplicated chrome,
    and adds disclosure controls for already-existing workspaces.
    """

    def __init__(self, owner) -> None:  # noqa: ANN001
        self.owner = owner
        self._provider_insights_expanded = False
        self._workflow_expanded = False
        self._batch_expanded = False
        self._responsive_mode = "standard"

    def install(self) -> None:
        self._move_generation_commands_above_workspace()
        self._integrate_docks()
        self._install_provider_disclosure()
        self._install_queue_disclosures()
        self._hide_duplicate_toolbar_generation_controls()
        self.refresh_presentation()

    def _move_generation_commands_above_workspace(self) -> None:
        shell = self.owner.application_shell
        status = self.owner.generation_status_strip
        workspace = shell.workspace
        if workspace is None:
            return
        layout = shell.root_layout
        layout.removeWidget(status)
        workspace_index = layout.indexOf(workspace)
        layout.insertWidget(max(0, workspace_index), status)
        status.setProperty("workspaceRole", "primary-command")
        status.setAccessibleDescription(
            "Primary launch controls for the current explicit queue scope."
        )

    @staticmethod
    def _blank_dock_title(dock) -> None:  # noqa: ANN001
        if dock.titleBarWidget() is not None:
            return
        title = QFrame(dock)
        title.setObjectName("integratedDockTitle")
        title.setFixedHeight(1)
        dock.setTitleBarWidget(title)

    def _integrate_docks(self) -> None:
        owner = self.owner
        self._blank_dock_title(owner.left_dock)
        self._blank_dock_title(owner.right_dock)
        owner.left_tabs.setDocumentMode(True)
        owner.right_tabs.setDocumentMode(True)
        owner.left_dock.setMinimumWidth(288)
        owner.left_dock.setMaximumWidth(300)
        owner.right_dock.setMinimumWidth(300)
        owner.right_dock.setMaximumWidth(328)

    def _install_provider_disclosure(self) -> None:
        owner = self.owner
        toggle = QToolButton(owner.provider_panel)
        toggle.setObjectName("providerInsightsDisclosure")
        toggle.setText("Provider insights")
        toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        toggle.setCheckable(True)
        toggle.setChecked(False)
        toggle.setArrowType(Qt.RightArrow)
        toggle.setToolTip("Show provider intelligence and smart-routing recommendations")
        toggle.setAccessibleName("Show provider insights")
        toggle.toggled.connect(self.reveal_provider_insights)
        owner.provider_panel.layout().insertWidget(2, toggle)
        owner.provider_insights_toggle = toggle

    def _queue_disclosure(self, text: str, object_name: str, handler) -> QToolButton:  # noqa: ANN001
        button = QToolButton(self.owner.queue_workspace.heading)
        button.setObjectName(object_name)
        button.setText(text)
        button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        button.setCheckable(True)
        button.setChecked(False)
        button.setArrowType(Qt.RightArrow)
        button.toggled.connect(handler)
        return button

    def _install_queue_disclosures(self) -> None:
        owner = self.owner
        heading_layout = owner.queue_workspace.heading.layout()
        self.workflow_toggle = self._queue_disclosure(
            "Workflow", "queueWorkflowDisclosure", self.reveal_workflow
        )
        self.workflow_toggle.setToolTip("Show source-to-launch readiness workflow")
        self.batch_toggle = self._queue_disclosure(
            "Batch plan", "queueBatchDisclosure", self.reveal_batch_planning
        )
        self.batch_toggle.setToolTip("Show batch planning and explicit row-range controls")
        self.focus_badge = QLabel("Queue focus", owner.queue_workspace.heading)
        self.focus_badge.setObjectName("queueFocusBadge")
        self.focus_badge.setAccessibleName("Queue-first workspace")
        insert_at = max(0, heading_layout.count() - 1)
        heading_layout.insertWidget(insert_at, self.focus_badge)
        heading_layout.insertWidget(insert_at + 1, self.workflow_toggle)
        heading_layout.insertWidget(insert_at + 2, self.batch_toggle)
        owner.queue_workflow_toggle = self.workflow_toggle
        owner.queue_batch_toggle = self.batch_toggle
        owner.queue_focus_badge = self.focus_badge

    def _hide_duplicate_toolbar_generation_controls(self) -> None:
        toolbar = self.owner.main_toolbar
        for name in ("Start Generation", "Pause/Resume", "Stop Generation", "Run Preflight"):
            action = self.owner.actions_by_name.get(name)
            if action is None:
                continue
            widget = toolbar.widgetForAction(action)
            if widget is not None:
                widget.hide()
        toolbar.setProperty("workspaceRole", "project-toolbar")

    @staticmethod
    def _set_visible(widget: QWidget | None, visible: bool) -> None:
        if widget is not None:
            widget.setVisible(bool(visible))

    def reveal_provider_insights(self, expanded: bool = True) -> None:
        self._provider_insights_expanded = bool(expanded)
        owner = self.owner
        self._set_visible(getattr(owner, "provider_intelligence", None), expanded)
        self._set_visible(getattr(owner, "smart_provider_routing", None), expanded)
        toggle = getattr(owner, "provider_insights_toggle", None)
        if toggle is not None:
            if toggle.isChecked() != bool(expanded):
                toggle.blockSignals(True)
                toggle.setChecked(bool(expanded))
                toggle.blockSignals(False)
            toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
            toggle.setAccessibleName("Hide provider insights" if expanded else "Show provider insights")

    def reveal_workflow(self, expanded: bool = True) -> None:
        self._workflow_expanded = bool(expanded)
        self._set_visible(getattr(self.owner, "generation_journey", None), expanded)
        self._sync_toggle(self.workflow_toggle, expanded)

    def reveal_batch_planning(self, expanded: bool = True) -> None:
        self._batch_expanded = bool(expanded)
        self._set_visible(getattr(self.owner, "queue_batch_operations", None), expanded)
        self._set_visible(getattr(self.owner.queue_workspace, "range_host", None), expanded)
        self._sync_toggle(self.batch_toggle, expanded)

    @staticmethod
    def _sync_toggle(toggle: QToolButton, expanded: bool) -> None:
        if toggle.isChecked() != bool(expanded):
            toggle.blockSignals(True)
            toggle.setChecked(bool(expanded))
            toggle.blockSignals(False)
        toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)

    def _ensure_more_action_in_row(self) -> None:
        owner = self.owner
        button = owner.queue_more_actions_button
        layout = owner.queue_workspace.action_layout
        if layout.indexOf(button) < 0:
            insert_at = max(0, layout.count() - 1)
            layout.insertWidget(insert_at, button)
        button.show()

    def _simplify_queue_commands(self) -> None:
        owner = self.owner
        command_widgets = owner.queue_workspace._command_widgets  # presentation registry
        secondary_names = (
            "filter_label",
            "planning_label",
            "action_label",
            "use_sort",
            "use_selection",
            "skip",
            "reset",
            "clear",
            "output",
        )
        show_full_operator_set = self._responsive_mode == "wide"
        for name in secondary_names:
            self._set_visible(command_widgets.get(name), show_full_operator_set)
        self._ensure_more_action_in_row()
        self._set_visible(owner.queue_more_actions_button, not show_full_operator_set)

    def _apply_metric_priority(self) -> None:
        cards = self.owner.cards
        for key, card in cards.items():
            if self._responsive_mode == "compact":
                card.setVisible(key not in {"chars", "skipped", "quota"})
            else:
                card.setVisible(key not in {"chars", "skipped"})

    def apply_responsive_mode(self, mode: object) -> None:
        value = str(getattr(mode, "value", mode) or "standard").casefold()
        if value not in {"compact", "standard", "wide"}:
            value = "standard"
        self._responsive_mode = value
        owner = self.owner
        compact = value == "compact"
        owner.left_dock.setMinimumWidth(280 if compact else 288)
        owner.left_dock.setMaximumWidth(300)
        owner.right_dock.setMinimumWidth(290 if compact else 300)
        owner.right_dock.setMaximumWidth(320 if compact else 328)
        self.workflow_toggle.setVisible(not compact)
        self.batch_toggle.setVisible(not compact)
        self.focus_badge.setVisible(not compact)
        if compact:
            self._set_visible(owner.generation_journey, False)
            self._set_visible(owner.queue_batch_operations, False)
            self._set_visible(owner.queue_workspace.range_host, False)
        else:
            self._set_visible(owner.generation_journey, self._workflow_expanded)
            self._set_visible(owner.queue_batch_operations, self._batch_expanded)
            self._set_visible(owner.queue_workspace.range_host, self._batch_expanded)
        self._apply_metric_priority()
        self._simplify_queue_commands()
        owner.project_context_widget.context_label.hide()
        owner.queue_workspace.footer.hide()

    def refresh_presentation(self) -> None:
        owner = self.owner
        self.reveal_provider_insights(self._provider_insights_expanded)
        self.reveal_workflow(self._workflow_expanded)
        self.reveal_batch_planning(self._batch_expanded)
        owner.project_context_widget.context_label.hide()
        owner.queue_workspace.footer.hide()
        if hasattr(owner, "empty_state"):
            owner.empty_state.setMaximumWidth(680)
            owner.empty_state.setMinimumHeight(220)
        self._apply_metric_priority()
        self._simplify_queue_commands()

    def refresh_generation_state(self, state) -> None:  # noqa: ANN001
        """Update only the tiny visual queue-focus summary from existing state."""

        scope = str(getattr(state, "scope_label", "") or "Queue")
        preflight = str(getattr(state, "preflight_status", "") or "Not checked")
        if bool(getattr(state, "generation_active", False)):
            label = "Generation active"
        elif preflight.casefold() in {"passed", "ready"}:
            label = "Ready to launch"
        else:
            label = scope
        self.focus_badge.setText(label)
        self.focus_badge.setToolTip(f"Scope: {scope} · Preflight: {preflight}")


def main_workspace_stylesheet(*, is_dark: bool, concept_key: str = ACTIVE_CONCEPT) -> str:
    """A9 structural styling layered after ThemeManager + A8 semantic tokens.

    QMainWindow is intentionally not targeted: ThemeManager remains the root
    QPalette authority certified by A8/A8.1.
    """

    p = palette_for(is_dark=is_dark, concept_key=concept_key)
    return f"""
/* Roadmap 2 A9 — Soft Professional Main Workspace */
QWidget#applicationShell {{ background:{p.canvas}; }}
QFrame#workspaceHero {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:10px;
}}
QFrame#projectContextStrip {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:8px;
}}
QFrame#generationActionBar {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:10px;
}}
QFrame#generationProgressContext {{ background:transparent; border:0; }}
QFrame#queueWorkspaceHeading {{
    background:{p.surface}; border:0; border-bottom:1px solid {p.border};
}}
QLabel#queueWorkspaceTitle {{ color:{p.text_primary}; font-weight:700; font-size:14px; }}
QLabel#queueWorkspaceSubtitle {{ color:{p.text_muted}; }}
QLabel#queueFocusBadge {{
    color:{p.primary}; background:{p.primary_soft}; border:1px solid {p.border};
    border-radius:7px; padding:4px 8px; font-weight:600;
}}
QToolButton#queueWorkflowDisclosure, QToolButton#queueBatchDisclosure,
QToolButton#providerInsightsDisclosure {{
    background:transparent; color:{p.text_secondary}; border:1px solid {p.border};
    border-radius:7px; padding:5px 8px; font-weight:600;
}}
QToolButton#queueWorkflowDisclosure:hover, QToolButton#queueBatchDisclosure:hover,
QToolButton#providerInsightsDisclosure:hover {{
    background:{p.surface_secondary}; color:{p.text_primary};
}}
QFrame#queueCommandBar, QFrame#queueScopeSummary {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:9px;
}}
QFrame#queueRangeBar {{
    background:{p.surface_secondary}; border:1px solid {p.border}; border-radius:8px;
}}
QFrame#providerPanelHeader {{
    background:transparent; border:0; border-bottom:1px solid {p.border};
}}
QFrame#providerPanel {{ background:{p.surface}; border:0; }}
QTabWidget#leftWorkspaceTabs::pane, QTabWidget#rightInspectorTabs::pane {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:9px;
}}
QTabWidget#leftWorkspaceTabs QTabBar::tab, QTabWidget#rightInspectorTabs QTabBar::tab {{
    background:transparent; border:0; border-bottom:2px solid transparent;
    padding:7px 10px; color:{p.text_secondary};
}}
QTabWidget#leftWorkspaceTabs QTabBar::tab:selected,
QTabWidget#rightInspectorTabs QTabBar::tab:selected {{
    color:{p.primary}; border-bottom-color:{p.primary};
}}
QFrame#integratedDockTitle {{ background:transparent; border:0; }}
QToolButton#queueMoreActionsButton {{
    color:{p.text_secondary}; background:{p.surface}; border:1px solid {p.border_strong};
    border-radius:7px; padding:5px 8px;
}}
QToolButton#queueMoreActionsButton:hover {{ background:{p.surface_secondary}; }}
""".strip()
