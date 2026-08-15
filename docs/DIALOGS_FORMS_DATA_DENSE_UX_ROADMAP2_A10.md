# S-Talking Roadmap 2 — A10 Dialogs, Forms & Data-Dense UX

## Status

A10 modernizes the product-wide dialog and form layer on top of the certified Soft Professional A9.1 workspace. It is intentionally presentation-only: existing dialog controllers, signals, validation, persistence, provider selection, Preflight authority, generation authority, routing authority, and database behavior remain unchanged.

## Product scope

A10 covers the existing dialog families used by the live application, including provider/account setup, provider setup wizard, voice/model catalog, provider cost/quota limits, Preflight and Preflight fixes, pronunciation review/dictionaries, source import review, CSV import review, recent projects, and interface preferences.

Data-dense surfaces receive the same visual grammar across tables, trees, lists, catalogs, review grids, and evidence views.

## Soft Professional dialog contract

- Dialog canvas uses the active Soft Professional semantic palette.
- Root dialog layouts gain consistent calm margins and spacing only when the existing layout is still using compact/default margins.
- `QFormLayout` keeps its existing row structure while receiving readable horizontal/vertical rhythm, left-aligned labels, and growing fields.
- Input controls receive a common semantic role and density-aware minimum height.
- Multiline editors, group sections, tabs, scroll areas, and button boxes receive consistent semantic roles for QSS styling.
- Tables, trees, and lists receive consistent Soft Professional surfaces, alternate rows, selection treatment, and headers without changing editing or selection authority.
- Dialog button boxes use a quiet secondary action surface while the existing default button remains the visual primary action.
- Native system file/font dialogs are intentionally excluded from custom modernization.

## Runtime integration

`DialogFormModernizer` is installed once per `MainWindow` and observes existing Qt dialogs when they are shown. It does not replace dialog classes or create alternate workflows.

The A10 stylesheet is appended after ThemeManager, Visual Design System 2.0, and A9 workspace overlays. ThemeManager remains the root QApplication palette authority. A10 never targets `QMainWindow`.

Density changes are forwarded to the dialog modernizer so open form controls remain aligned with Compact/Comfortable density settings.

## Authority boundaries

A10 does not:

- run Preflight;
- start, pause, stop, or restart generation;
- change provider/account/voice/model/language selections;
- apply Smart Routing recommendations;
- introduce hidden cross-provider failover;
- mutate source text;
- migrate or modify database schema 23.

## Certification handoff

A10 dedicated tests verify actual runtime Qt dialogs, form layouts, controls, button boxes, data-dense views, tabs, multiline controls, density refresh, native-system-dialog exclusion, product dialog inventory, theme integration, and presentation-only boundaries.

After A10 certification, Roadmap 2 proceeds to **A11 — Theme, Dark Mode & Visual Accessibility**.
