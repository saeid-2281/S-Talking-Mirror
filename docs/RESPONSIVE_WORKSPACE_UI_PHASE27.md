# Responsive Workspace UI — Phase 27

Phase 27 adds a breakpoint-aware presentation layer to the S-Talking desktop workspace without moving business logic out of existing controllers.

## Breakpoints

The resolver considers both the main-window size and the actual queue width:

- **Wide** — full command center, three-column source actions, text-and-icon toolbar.
- **Standard** — filters, planning controls and actions are separated into readable rows.
- **Compact** — essential queue controls remain visible; secondary actions move to the **More** menu; source actions use two columns; low-priority metric cards are hidden.

## Stability rules

- Existing public widget handles remain unchanged.
- Queue actions remain available at every breakpoint.
- Preflight detail is preserved in the tooltip when the compact label is used.
- User-resized docks are not continually reset; target widths are applied only when the resolved breakpoint changes.
- Existing workspace profiles, density settings, high-contrast mode and keyboard accessibility continue to work.

## Files

- `app/gui/responsive_workspace.py`
- `app/gui/main.py`
- `app/gui/theme.py`
- `app/gui/widgets/application_shell.py`
- `app/gui/widgets/queue_workspace.py`
- `app/gui/widgets/queue_details_pane.py`
- `tests/test_responsive_workspace_ui_phase27.py`
