# Workspace Layouts

S Talking v0.18 uses a compact production workspace inspired by the approved UI concept:

- Native menu bar with sectioned commands and shortcuts
- Compact project context line instead of a large permanent hero/header
- Compact metrics cards
- Provider settings on the left
- Queue as the dominant central workspace
- Selected row and Generation Monitor on the right
- Activity/report/status at the bottom

## Presets

The View menu contains `Workspace Layout` presets:

| Preset | Purpose |
| --- | --- |
| Compact | Narrow side panels, queue remains primary. |
| Standard | Balanced provider, queue, and selected-row panels. |
| Wide | Exposes source and monitor panels for large displays. |
| Focus Mode | Hides side panels and monitor so the queue dominates. |
| Restore Default Layout | Clears saved dock state and returns to Standard. |

Presets are saved with `QSettings` under `main_window/layout_preset`. Dock visibility and monitor width continue to persist through the existing layout state.

## Responsive Targets

The main window minimum is `1180x700`. Initial size is clamped to about 88% of the available screen and centered, with saved monitor widths clamped to the current window.

Manual validation targets:

- 1366x768
- 1920x1080
- 2560x1440
- 3840x2160

## Design Tokens

Theme tokens live in `app/gui/theme.py`:

- Primary, hover, pressed
- Success, warning, danger, info
- Surface, border, selected row
- Text hierarchy
- Dark, Light, and System theme selection

## Icon Source

The app uses the repository SVG path icon registry in `app/gui/icons.py`. The style is consistent stroke-based line icons generated at runtime as `QIcon` objects. Provider brand marks are not bundled unless licensing is explicit; provider identity falls back to neutral icons plus professional provider names.
