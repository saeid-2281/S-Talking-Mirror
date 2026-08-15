# Roadmap 2 A9 — Main Workspace Modernization

## Product direction

A9 is the first structural application of the **Soft Professional** direction selected in A8.1. It does not replace the existing ThemeManager, controller/service boundaries, or Track A launch authority. Instead, it recomposes the current desktop workspace around the operator's primary job: prepare an explicit scope, review readiness, and launch generation deliberately.

## What changes visibly

- The existing Generation Status Strip moves from the bottom edge to the top of the working area, directly below project context and metrics. The same buttons, callbacks, state and progress widget are reused.
- Duplicate Start / Pause / Stop / Preflight toolbar widgets are visually removed. Their existing QActions remain available through menus, shortcuts and command surfaces.
- The Provider dock becomes a quieter setup sidebar. Provider Overview plus Provider & Account and Voice & Model stay directly available; Provider Intelligence and Smart Routing move behind one explicit **Provider insights** disclosure.
- Generation Workflow, Batch Planning and row-range controls remain fully available but are collapsed behind **Workflow** and **Batch plan** disclosures in the Queue header.
- The default Queue command center prioritizes Search, Status, Source, Scope, Order, Dry run and Retry. Secondary queue operations remain available from the existing **More** menu; no operation is removed.
- Redundant raw project-context text, low-priority Characters/Skipped metric pills and the duplicate queue footer are hidden from the normal workspace.
- Left/right docks use integrated tab headers and narrower Soft Professional proportions without changing public dock handles.
- The empty-state card receives more visual space so the next action is obvious when no source is loaded.

## Authority and behavior freeze

A9 is presentation-only. It does **not**:

- change provider/account/voice/model/language selections;
- run Preflight automatically;
- start or restart generation automatically;
- apply Smart Routing automatically;
- add hidden cross-provider failover;
- infer language from content;
- mutate source text;
- change database schema 23.

Progressive disclosure is user-driven. Command Palette/shortcut focus paths explicitly reveal a collapsed surface before focusing it, so discoverability is preserved without returning to the always-expanded legacy layout.

## Compatibility contracts retained

- Existing MainWindow public widget handles remain unchanged.
- The Queue Workspace still owns the same two-row standard/wide command-center layout and compact breakpoint behavior.
- Generation Journey and Queue Batch Operations keep their established positions in the Queue root layout; A9 changes only default visibility.
- ThemeManager remains the root QPalette authority. A9 does not target `QMainWindow` in its stylesheet.
- Compact/Comfortable density and historical queue row/toolbar/action-bar geometry remain authoritative.

## A10 handoff

A10 — Dialogs, Forms & Data-Dense UX should migrate high-use dialogs and forms to the same Soft Professional hierarchy, field grouping, progressive disclosure and semantic status language established here.
