# v0.18.1 Visible UI Plan

This plan maps the current visible MainWindow regions to the v0.18.1 widget/layout implementation. It is intentionally focused on real PySide6 widgets, not only stylesheets or documentation.

## Current Problems

| Current region | Visible problem | v0.18.1 implementation |
| --- | --- | --- |
| Menu bar | Partly sectioned, but commands still feel flat and toolbar work is duplicated elsewhere. | Keep native menu bar, reuse shared `QAction` objects, add more separators/submenus, and attach the same actions to a real `QToolBar`. |
| Permanent in-workspace title/header | v0.18 removed the large title, but the workspace still has old stacked rows and classic Qt framing. | Keep title absent. Add a compact toolbar and bounded project context strip directly below the native menu. |
| Project sources path section | Large path row with permanent long path fields; consumes vertical space. | Replace with `project_context_frame`, a compact horizontal strip with elided source/output/provider/model/voice/preflight summary and source/output icon actions. Full paths move to tooltips. |
| Metric cards | Large boxed cards plus separate status counters create tall narrow boxes. | Replace both with one `metrics_strip` using lightweight `MetricPill` widgets and separators: Files, Characters, Pending, Running, Completed, Failed, Skipped, Quota, ETA. |
| Provider settings | Classic `QGroupBox` in the main splitter, cramped controls, clipped dropdown text. | Move provider form into `left_dock` tab `Provider`, using lightweight section headers and consistent combo minimum widths. Audio/Advanced sections are collapsible. |
| Project Sources | Separate dock can dominate layout and feels detached from provider setup. | Move source table into `left_dock` tab `Sources` with compact icon toolbar. Existing source table/actions remain functional. |
| Queue toolbar | Long chain of equally styled buttons. | Keep core filters visible; rare actions remain in grouped menu buttons and context menus. Toolbar sits inside `queue_workspace`. |
| Queue table | Queue is not always dominant because side widgets and empty panes consume space. | Make queue the central widget in `workspace_splitter`; use compact metrics and hide/collapse secondary panels in presets. |
| Selected Row | Classic `QGroupBox`, large empty text area when no row selected. | Move selected row content into `right_dock` tab `Selected Row`, compact empty state, active details, and resolved request summary. |
| Generation Monitor | Separate dock, can steal width and create old-layout feel. | Move monitor content into `right_dock` tab `Generation Monitor`; monitor remains scrollable vertically and uses existing responsive internals. |
| Bottom log/progress | Giant empty bottom panel. | Replace with `activity_splitter` containing a tabbed Activity/Output/Errors area, default collapsed to compact height. |
| Bottom buttons | Large standalone buttons duplicate toolbar/menu actions; Save defaults is visually too prominent. | Add compact `generation_action_bar` with Start/Pause/Stop/Preflight, progress, report/provider/health. Save defaults moves to Settings menu. |
| Workspace presets | Metadata existed but the visual difference was limited. | Presets now toggle left/right docks, monitor tab visibility, activity area height, and splitter sizes: Compact, Standard, Wide, Focus Mode, Reset Default. |
| Combo boxes | Profile/model/voice/provider fields can be clipped. | Shared minimum widths, popup widths, tooltips, and fixed-height connection status. |
| Official logo | Official asset existed after v0.18. | Keep master byte-for-byte unchanged; use derivatives only for icon/About/installer/report/empty state, never as a large permanent workspace logo. |

## Target Hierarchy

1. Native `QMenuBar`
2. `QToolBar` named `mainToolbar`
3. `project_context_frame`
4. `metrics_strip`
5. `workspace_splitter`
   - `left_dock` with `left_tabs`
     - Provider tab
     - Sources tab
   - central `queue_workspace`
   - `right_dock` with `right_tabs`
     - Selected Row tab
     - Generation Monitor tab
6. `activity_splitter` with `activity_tabs`
7. compact `generation_action_bar`
8. native status bar

## Acceptance Measurements

- Project strip: <= 56 px target height.
- Metrics strip: <= 72 px target height.
- Left dock default width: 270-320 px.
- Right dock default width: 290-340 px.
- Toolbar height: 38-42 logical px target.
- Queue remains the dominant visible central widget at 1366x768 and above.
