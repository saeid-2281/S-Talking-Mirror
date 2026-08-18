"""Roadmap 2 A9 Soft Professional main-workspace modernization.

A9 is deliberately presentation-only.  It reorganizes the existing S-Talking
workspace and progressive disclosure without creating alternate generation,
preflight, provider-selection, routing, or source-mutation paths.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QLabel, QSizePolicy, QToolButton, QWidget

from app.gui.visual_design_system_v2 import ACTIVE_CONCEPT, COMPONENTS, palette_for


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
        self._apply_soft_professional_geometry()
        self.refresh_presentation()

    @staticmethod
    def _tune_layout(layout, margins: tuple[int, int, int, int], spacing: int) -> None:  # noqa: ANN001
        if layout is None:
            return
        layout.setContentsMargins(*margins)
        layout.setSpacing(spacing)

    def reapply_visual_geometry(self) -> None:
        """Restore A9.1 geometry after legacy density/layout passes."""

        self._apply_soft_professional_geometry()

    @staticmethod
    def _lock_vertical(widget: QWidget, height: int) -> None:
        """Keep toolbar-like rows from absorbing queue viewport height."""

        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        widget.setMinimumHeight(height)
        widget.setMaximumHeight(height)

    def _apply_soft_professional_geometry(self) -> None:
        """Apply the selected concept's compact vertical rhythm.

        B6H3 portable acceptance exposed a desktop-only layout defect: header and
        command frames used ``Preferred`` vertical policies, so QBoxLayout could
        donate spare height to them before the queue viewport.  The A8 concept
        uses fixed control bands and gives the remaining height to the working
        surface.  Keep that rule explicit here.
        """

        owner = self.owner
        shell = owner.application_shell
        control_height = COMPONENTS.control_compact_height
        command_rows = 3 if self._responsive_mode == "compact" else 2
        command_height = (command_rows * control_height) + ((command_rows - 1) * 4) + 8

        self._tune_layout(shell.root_layout, (10, 6, 10, 6), 6)
        self._tune_layout(owner.queue_workspace.layout(), (0, 0, 0, 0), 4)
        self._tune_layout(owner.queue_workspace.root_layout, (0, 0, 0, 0), 4)
        self._tune_layout(owner.queue_workspace.heading.layout(), (12, 5, 10, 5), 6)
        self._lock_vertical(owner.queue_workspace.heading, 46)
        owner.queue_workspace.title_label.setMaximumHeight(22)
        owner.queue_workspace.subtitle_label.setMaximumHeight(20)
        if hasattr(owner, "queue_focus_badge"):
            owner.queue_focus_badge.setMaximumHeight(min(control_height, 30))
            owner.queue_focus_badge.setAlignment(Qt.AlignCenter)

        # Command rows own only the height needed by their controls. Inner
        # layouts carry no duplicate vertical margins; the host owns that inset.
        self._tune_layout(owner.queue_workspace.command_root_layout, (8, 4, 8, 4), 4)
        self._tune_layout(owner.queue_workspace.command_layout, (0, 0, 0, 0), 6)
        self._tune_layout(owner.queue_workspace.action_layout, (0, 0, 0, 0), 6)
        self._tune_layout(owner.queue_workspace.planning_layout, (0, 0, 0, 0), 6)
        self._lock_vertical(owner.queue_workspace.command_host, command_height)
        self._tune_layout(owner.queue_workspace.range_layout, (8, 4, 8, 4), 6)
        self.sync_queue_disclosure_layout_from_widgets()
        self._tune_layout(owner.queue_workspace.body_layout, (0, 0, 0, 0), 4)
        owner.queue_workspace.summary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        owner.queue_workspace.summary.setMinimumHeight(30)
        owner.queue_workspace.summary.setMaximumHeight(32)
        owner.queue_workspace.sync_chrome_height()

        for name, widget in owner.queue_workspace._command_widgets.items():
            if name in {"filter_label", "planning_label", "action_label"}:
                continue
            widget.setMinimumHeight(control_height)
            widget.setMaximumHeight(control_height)

        for button in (
            owner.generation_status_strip.start_button,
            owner.generation_status_strip.preflight_button,
            owner.generation_status_strip.pause_button,
            owner.generation_status_strip.stop_button,
        ):
            button.setMinimumHeight(control_height)
            button.setMaximumHeight(control_height)
        owner.generation_status_strip.state_badge.setMinimumHeight(control_height)
        owner.generation_status_strip.state_badge.setMaximumHeight(control_height)
        owner.generation_status_strip.setMinimumHeight(COMPONENTS.generation_action_bar_height)
        owner.generation_status_strip.setMaximumHeight(COMPONENTS.generation_action_bar_height)
        self._tune_layout(owner.generation_status_strip.layout(), (8, 4, 8, 4), 6)

        self._tune_layout(owner.provider_panel.layout(), (8, 8, 8, 10), 8)
        self._tune_layout(owner.selected_row_panel.layout(), (10, 10, 10, 10), 8)
        owner.application_shell.setProperty("visualAlignment", "soft-professional")
        owner.queue_workspace.setProperty("visualAlignment", "soft-professional")
        owner.provider_panel.setProperty("visualAlignment", "soft-professional")
        owner.selected_row_panel.setProperty("visualAlignment", "soft-professional")

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
        """Apply disclosure visibility without fighting responsive compact state.

        GenerationJourneyWidget and QueueBatchOperationsWidget keep a persistent
        presentation request so a later MainWindow compact-overlay sync cannot
        accidentally reopen a disclosure that the A9 workspace modernizer closed.
        Other widgets retain the historical direct setVisible behavior.
        """

        if widget is None:
            return
        setter = getattr(widget, "set_presentation_visible", None)
        if callable(setter):
            setter(bool(visible))
        else:
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
        journey = getattr(self.owner, "generation_journey", None)
        self._set_visible(journey, expanded)
        batch = getattr(self.owner, "queue_batch_operations", None)
        self._sync_queue_disclosure_layout(
            workflow_visible=bool(expanded),
            batch_visible=bool(
                self._batch_expanded
                and batch is not None
                and not batch.isHidden()
            ),
        )
        self._sync_toggle(self.workflow_toggle, expanded)

    def _sync_batch_range_host_geometry(self, expanded: bool | None = None) -> None:
        """Give the optional range row layout authority only while it is open.

        H9 Hotfix 1/2 proved that hidden/zero-height state is not enough for
        optional queue chrome on the Windows Qt layout path.  Keep the range
        frame structural: no layout item while closed; exactly one compact row
        immediately before the command host while explicitly open.
        """

        queue = self.owner.queue_workspace
        host = queue.range_host
        root = queue.root_layout
        if expanded is None:
            expanded = self._batch_expanded and self._responsive_mode != "compact"
        expanded = bool(expanded)
        host.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        if expanded:
            command_index = root.indexOf(queue.command_host)
            if root.indexOf(host) < 0:
                root.insertWidget(max(1, command_index), host)
            height = COMPONENTS.control_compact_height + 8
            host.setMinimumHeight(height)
            host.setMaximumHeight(height)
            host.show()
        else:
            if root.indexOf(host) >= 0:
                root.removeWidget(host)
            host.setMinimumHeight(0)
            host.setMaximumHeight(0)
            host.hide()

        root.invalidate()
        queue.sync_chrome_height()

    def _sync_queue_disclosure_layout(
        self,
        *,
        workflow_visible: bool | None = None,
        batch_visible: bool | None = None,
    ) -> None:
        """Structurally compose optional queue chrome around the command band.

        Qt can retain layout-item extent for hidden presentation widgets across
        delayed polish/resize passes on the frozen Windows path.  Visibility is
        therefore not the layout authority.  Collapsed Workflow and Batch plan
        widgets are detached from ``queue.root_layout``; explicit disclosures are
        inserted contiguously immediately before the command host.
        """

        owner = self.owner
        queue = owner.queue_workspace
        root = queue.root_layout
        journey = getattr(owner, "generation_journey", None)
        batch = getattr(owner, "queue_batch_operations", None)

        if workflow_visible is None:
            workflow_visible = bool(
                self._workflow_expanded
                and journey is not None
                and not journey.isHidden()
            )
        if batch_visible is None:
            batch_visible = bool(
                self._batch_expanded
                and batch is not None
                and not batch.isHidden()
            )

        # Canonical composition authority: remove every optional queue row,
        # including a stale range row, before rebuilding the explicit order.
        # H9 H5 proved the fixed chrome host solved surplus cell growth, but a
        # surviving range QWidgetItem could still precede Batch and shift it to
        # index 2.  Logical disclosure state, not raw QWidget visibility, owns
        # whether a row may return.
        for widget in (journey, batch, queue.range_host):
            if widget is not None and root.indexOf(widget) >= 0:
                root.removeWidget(widget)

        if journey is not None:
            if workflow_visible:
                command_index = root.indexOf(queue.command_host)
                root.insertWidget(max(1, command_index), journey)
                journey.show()
            else:
                journey.hide()

        if batch is not None:
            if batch_visible:
                command_index = root.indexOf(queue.command_host)
                root.insertWidget(max(1, command_index), batch)
                batch.show()
            else:
                batch.hide()

        self._sync_batch_range_host_geometry(expanded=bool(batch_visible))
        root.invalidate()
        root.activate()
        queue.sync_chrome_height()

    def sync_queue_disclosure_layout_from_widgets(self) -> None:
        """Reconcile structural layout membership with current widget visibility."""

        owner = self.owner
        journey = getattr(owner, "generation_journey", None)
        batch = getattr(owner, "queue_batch_operations", None)
        self._sync_queue_disclosure_layout(
            workflow_visible=bool(
                self._workflow_expanded
                and journey is not None
                and not journey.isHidden()
            ),
            batch_visible=bool(
                self._batch_expanded
                and batch is not None
                and not batch.isHidden()
            ),
        )

    def reveal_batch_planning(self, expanded: bool = True) -> None:
        self._batch_expanded = bool(expanded)
        batch = getattr(self.owner, "queue_batch_operations", None)
        self._set_visible(batch, expanded)
        journey = getattr(self.owner, "generation_journey", None)
        self._sync_queue_disclosure_layout(
            workflow_visible=bool(
                self._workflow_expanded
                and journey is not None
                and not journey.isHidden()
            ),
            batch_visible=bool(expanded),
        )
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
        planning_label = command_widgets.get("planning_label")
        if planning_label is not None:
            if planning_label.isWindow() or planning_label.parentWidget() is None:
                planning_label.setParent(owner.queue_workspace.command_host)
            planning_label.hide()

        secondary_names = (
            "filter_label",
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
        self.sync_queue_disclosure_layout_from_widgets()
        self._apply_metric_priority()
        self._simplify_queue_commands()
        owner.project_context_widget.context_label.hide()
        owner.queue_workspace.footer.hide()
        self._apply_soft_professional_geometry()

    def refresh_presentation(self) -> None:
        owner = self.owner
        self.reveal_provider_insights(self._provider_insights_expanded)
        self.reveal_workflow(self._workflow_expanded)
        self.reveal_batch_planning(self._batch_expanded)
        owner.project_context_widget.context_label.hide()
        owner.queue_workspace.footer.hide()
        if hasattr(owner, "empty_state"):
            owner.empty_state.setMaximumWidth(680)
            owner.empty_state.setMinimumHeight(240)
            owner.empty_state.setMaximumHeight(360)
            owner.empty_state.setProperty("visualRole", "calm-empty-state")
        self._apply_metric_priority()
        self._simplify_queue_commands()
        self._apply_soft_professional_geometry()

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
    """Soft Professional A9/A9.1 styling layered after ThemeManager + A8 tokens.

    The root QMainWindow palette remains under ThemeManager authority.  This
    stylesheet aligns the real workspace with the A8 Soft Professional specimen
    through typography, spacing, quieter surfaces and action hierarchy only.
    """

    p = palette_for(is_dark=is_dark, concept_key=concept_key)
    return f"""
/* Roadmap 2 A9.1 — Soft Professional Visual Alignment */
QWidget#applicationShell {{
    background:{p.canvas}; color:{p.text_primary};
    font-family:"Segoe UI Variable", "Segoe UI", sans-serif; font-size:13px;
}}
QMenuBar {{
    background:{p.surface}; color:{p.text_secondary}; border-bottom:1px solid {p.border};
    padding:2px 8px; font-size:12px;
}}
QMenuBar::item {{ padding:5px 8px; border-radius:8px; }}
QMenuBar::item:selected {{ background:{p.surface_secondary}; color:{p.text_primary}; }}
QToolBar#mainToolbar {{
    background:{p.surface}; border:0; border-bottom:1px solid {p.border};
    padding:2px 8px; spacing:4px;
}}
QToolBar#mainToolbar QToolButton {{
    background:transparent; color:{p.text_secondary}; border:1px solid transparent;
    border-radius:8px; padding:5px 9px; font-size:12px; font-weight:500;
}}
QToolBar#mainToolbar QToolButton:hover {{
    background:{p.surface_secondary}; color:{p.text_primary}; border-color:{p.border};
}}
QToolButton#toolbarOverflowButton {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:8px; padding:5px 8px;
}}
QFrame#workspaceHero {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:14px;
}}
QFrame#projectContextStrip {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:12px;
}}
QLabel#compactSourceSummary, QLabel#compactOutputSummary {{ color:{p.text_secondary}; }}
QFrame#metricsStrip {{ background:transparent; border:0; }}
QFrame#metricPill, QFrame#metricCard, QFrame#card {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:12px;
}}
QFrame#metricPill:hover {{ background:{p.surface_secondary}; border-color:{p.border_strong}; }}
QLabel#metricValue, QLabel#cardValue {{ color:{p.text_primary}; font-size:13px; font-weight:700; }}
QLabel#metricCaption, QLabel#cardCaption {{ color:{p.text_muted}; font-size:10px; }}
QFrame#generationActionBar {{
    background:{p.surface_secondary}; border:0; border-radius:12px;
}}
QFrame#generationActionBar QPushButton {{
    min-height:30px; padding:0 11px; border-radius:8px;
    background:{p.surface}; color:{p.text_secondary}; border:1px solid {p.border};
}}
QFrame#generationActionBar QPushButton:hover {{
    color:{p.text_primary}; border-color:{p.border_strong}; background:{p.surface};
}}
QFrame#generationActionBar QPushButton#startGenerationButton,
QFrame#generationActionBar QPushButton[primary="true"] {{
    background:{p.primary}; color:{p.text_inverse}; border-color:{p.primary}; font-weight:700;
}}
QFrame#generationActionBar QPushButton#startGenerationButton:hover,
QFrame#generationActionBar QPushButton[primary="true"]:hover {{ background:{p.primary_hover}; }}
QFrame#generationProgressContext {{ background:transparent; border:0; }}
QWidget#queueWorkspace {{
    background:{p.surface}; color:{p.text_primary}; border:1px solid {p.border}; border-radius:14px;
}}
QFrame#queueWorkspaceHeading {{
    background:transparent; border:0; border-bottom:1px solid {p.border};
}}
QLabel#queueWorkspaceTitle {{
    color:{p.text_primary}; font-weight:700; font-size:14px; background:transparent; border:0;
}}
QLabel#queueWorkspaceSubtitle {{
    color:{p.text_muted}; font-size:11px; background:transparent; border:0;
}}
QLabel#queueFocusBadge {{
    color:{p.primary}; background:{p.primary_soft}; border:1px solid {p.border};
    border-radius:8px; padding:4px 8px; font-weight:600; font-size:11px;
}}
QToolButton#queueWorkflowDisclosure, QToolButton#queueBatchDisclosure,
QToolButton#providerInsightsDisclosure, QToolButton#queueColumnsButton {{
    background:{p.surface}; color:{p.text_secondary}; border:1px solid {p.border};
    border-radius:8px; padding:5px 8px; font-weight:600;
}}
QToolButton#queueWorkflowDisclosure:hover, QToolButton#queueBatchDisclosure:hover,
QToolButton#providerInsightsDisclosure:hover, QToolButton#queueColumnsButton:hover {{
    background:{p.surface_secondary}; color:{p.text_primary}; border-color:{p.border_strong};
}}
QFrame#queueCommandBar {{
    background:{p.surface_secondary}; border:0; border-radius:12px;
}}
QFrame#queueRangeBar {{
    background:{p.surface_secondary}; border:0; border-radius:12px;
}}
QFrame#queueScopeSummary {{
    background:transparent; border:0; border-top:1px solid {p.border}; border-radius:0;
}}
QLabel#queueCommandSectionLabel {{
    color:{p.text_muted}; font-size:10px; font-weight:700; background:transparent; border:0;
}}
QLineEdit#queueSearch, QComboBox#queueStatusFilter, QComboBox#queueSourceFilter,
QComboBox#queueScopeSelector, QComboBox#queueOrderSelector {{
    min-height:30px; background:{p.surface}; color:{p.text_primary};
    border:1px solid {p.border}; border-radius:8px; padding:0 9px;
}}
QLineEdit#queueSearch:focus, QComboBox#queueStatusFilter:focus, QComboBox#queueSourceFilter:focus,
QComboBox#queueScopeSelector:focus, QComboBox#queueOrderSelector:focus {{ border-color:{p.focus_ring}; }}
QPushButton#queuePrimaryAction {{
    min-height:30px; background:{p.primary_soft}; color:{p.primary};
    border:1px solid {p.border}; border-radius:8px; padding:0 10px; font-weight:700;
}}
QPushButton#queuePrimaryAction:hover {{ border-color:{p.primary}; background:{p.primary_soft}; }}
QPushButton#queueSecondaryAction, QToolButton#queueActionMenu, QToolButton#queueMoreActionsButton {{
    min-height:30px; color:{p.text_secondary}; background:{p.surface};
    border:1px solid {p.border}; border-radius:8px; padding:0 9px; font-weight:500;
}}
QPushButton#queueSecondaryAction:hover, QToolButton#queueActionMenu:hover,
QToolButton#queueMoreActionsButton:hover {{
    color:{p.text_primary}; background:{p.surface}; border-color:{p.border_strong};
}}
QFrame#providerPanelHeader {{
    background:transparent; border:0; border-bottom:1px solid {p.border};
}}
QFrame#providerPanel {{ background:{p.canvas}; border:0; }}
QFrame#providerSection, QFrame#collapsibleSection {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:12px;
}}
QToolButton#providerSectionHeader, QToolButton#sectionHeader {{
    min-height:30px; background:transparent; color:{p.text_primary}; border:0;
    border-radius:8px; padding:4px 7px; font-weight:650;
}}
QToolButton#providerSectionHeader:hover, QToolButton#sectionHeader:hover {{ background:{p.surface_secondary}; }}
QLabel#formLabel {{ color:{p.text_muted}; font-size:10px; font-weight:600; }}
QFrame#providerFieldRow QLineEdit, QFrame#providerFieldRow QComboBox,
QFrame#collapsibleSection QLineEdit, QFrame#collapsibleSection QComboBox,
QFrame#collapsibleSection QSpinBox, QFrame#collapsibleSection QDoubleSpinBox {{
    min-height:30px; background:{p.surface}; color:{p.text_primary}; border:1px solid {p.border};
    border-radius:8px; padding:0 8px;
}}
QTabWidget#leftWorkspaceTabs::pane, QTabWidget#rightInspectorTabs::pane {{
    background:{p.canvas}; border:0;
}}
QTabWidget#leftWorkspaceTabs QTabBar::tab, QTabWidget#rightInspectorTabs QTabBar::tab {{
    background:transparent; border:0; border-bottom:2px solid transparent;
    padding:8px 11px; color:{p.text_secondary}; font-size:12px; font-weight:600;
}}
QTabWidget#leftWorkspaceTabs QTabBar::tab:selected,
QTabWidget#rightInspectorTabs QTabBar::tab:selected {{
    color:{p.primary}; border-bottom-color:{p.primary};
}}
QFrame#selectedRowCard, QGroupBox#selectedRowCard {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:12px;
}}
QFrame#integratedDockTitle {{ background:transparent; border:0; }}
QFrame#emptyState, QWidget#emptyState {{
    background:{p.surface}; border:1px solid {p.border}; border-radius:14px;
}}
QFrame#emptyState QLabel, QWidget#emptyState QLabel {{
    background:transparent; border:0; color:{p.text_secondary};
}}
QFrame#emptyState QPushButton, QWidget#emptyState QPushButton {{
    min-height:34px; border-radius:8px; padding:0 11px;
}}
QFrame#emptyState QPushButton[primary="true"], QWidget#emptyState QPushButton[primary="true"] {{
    background:{p.primary}; color:{p.text_inverse}; border-color:{p.primary}; font-weight:700;
}}
QTableView#queueTable, QTableWidget#queueTable {{
    background:{p.surface}; alternate-background-color:{p.surface_secondary};
    border:0; gridline-color:{p.border}; selection-background-color:{p.primary_soft};
    selection-color:{p.text_primary};
}}
QTableView#queueTable QHeaderView::section, QTableWidget#queueTable QHeaderView::section {{
    background:{p.surface_secondary}; color:{p.text_secondary}; border:0;
    border-bottom:1px solid {p.border}; padding:7px 8px; font-weight:700;
}}
QTabWidget#activityTabs::pane {{ border:0; background:transparent; }}
QTabWidget#activityTabs QTabBar::tab {{
    background:transparent; border:0; border-top:2px solid transparent;
    padding:7px 12px; color:{p.text_muted};
}}
QTabWidget#activityTabs QTabBar::tab:selected {{ color:{p.primary}; border-top-color:{p.primary}; }}
QStatusBar {{ background:{p.surface}; color:{p.text_muted}; border-top:1px solid {p.border}; }}
""".strip()
