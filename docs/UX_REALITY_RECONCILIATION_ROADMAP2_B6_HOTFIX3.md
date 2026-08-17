# Roadmap 2 / B6 Hotfix 3 — UX Reality Reconciliation & Soft Professional Shell Completion

## Why this hotfix exists

B6 Hotfix 2 passed automated Dark/three-theme certification, but manual runtime review
still found issues that automated checks did not represent faithfully:

- a missing CSV/output path could raise a modal warning before the main window became visible;
- Provider Accounts → Account details could compress and overlap at realistic desktop sizes;
- toolbar icons were rendered at a low logical/physical resolution on HiDPI displays;
- menu hover/focus borders could leave overlapping or apparently persistent highlights;
- the queue inspector and provider-account details still exposed broad legacy technical-blue/navy surfaces;
- offscreen screenshot certification could render every label as square glyphs while still reporting PASS;
- session restore and recovery work ran synchronously inside `MainWindow.__init__`, delaying first paint.

This hotfix is presentation/startup-recovery hardening only. It does **not** add automatic
provider/account/voice/model/language switching, automatic Preflight, generation, recovery,
Smart Routing, or cross-provider failover. Database schema 23 remains authoritative.

## Product changes

### 1. Non-blocking project path recovery

Saved projects with a moved/deleted CSV or output folder now open the application shell first.
Missing paths are shown in a non-modal `ProjectPathNotice` with explicit **Locate source**,
**Choose output**, and **Dismiss** actions. The warning is logged and shown in the status bar,
but it never blocks startup behind a `QMessageBox`.

Startup recovery/session restoration is deferred with a short `QTimer.singleShot(50, ...)` handoff, allowing
the first window event/paint to occur before restore work begins.

### 2. Provider Accounts responsive details pane

The Account details side is now a dedicated scrollable pane. Identity, quota, catalog and
metadata cards live inside the scroll area; the four account actions live in a separate 2×2
action grid below it. The details pane uses a 340–460 logical-pixel contract and the profile
table keeps the established 560px readability floor, preventing the previous collision at 900–1120px dialog widths.

### 3. HiDPI icon rendering

The icon registry remains SVG/vector-source based, but rasterization now occurs at the maximum
active screen device-pixel ratio and sets the resulting pixmap DPR. Toolbar logical icon size
is 24px within the established 38–42px toolbar height, keeping icon edges sharp on 125/150/200% Windows scaling.

### 4. Menu hover/focus geometry

Menu-bar and menu items reserve a transparent 1px border in their base state. Hover/pressed
states change color/border color without changing item geometry. This removes the border
growth/overlap that could make multiple menu headings look highlighted.

### 5. Soft Professional shell completion

The final stylesheet layer explicitly covers previously missed queue-inspector and
Provider Accounts surfaces. Large containers use Soft Professional `canvas`, `surface`,
and `surface_secondary` tokens. Primary actions and small semantic status accents remain
semantic; the hotfix does not intentionally remove the Soft Professional primary color.

### 6. Font-valid visual certification

`ensure_readable_runtime_font()` uses the normal Qt/system font database first. On Windows,
if an offscreen Qt process has no usable font database, it registers an installed Windows
system font from `%WINDIR%\Fonts` (for example Segoe UI) without bundling or redistributing
font files.

The new certifier refuses to pass if a readable family and Danish/Latin glyphs are unavailable.
It captures Dark main workspace, Dark Provider Accounts, Light main workspace, and System
main workspace.

Historical B6-H2 Dark, A12.1 three-theme, and A12 product-visual certifiers now also require a readable runtime font.

## Provider profile and credential locations

`api-profiles.json` is **metadata only**. Raw API keys are not stored in that JSON.

### Source-mode development

With the current development root `D:\Projects\S-Talking`:

- metadata: `D:\Projects\S-Talking\api-profiles.json`
- source-mode Windows credentials: `D:\Projects\S-Talking\credentials\*.cred`

Those `.cred` files are protected with Windows DPAPI.

### Frozen portable mode

When `portable.mode` is beside `S-Talking.exe`, the writable root is:

`<Portable>\S-Talking-Data`

Provider metadata is expected at:

`<Portable>\S-Talking-Data\settings\api-profiles.json`

The frozen Windows build uses **Windows Credential Manager** as the primary secret backend.
Its target is derived from the profile ID and is not stored in `api-profiles.json`.

For a one-time migration on the **same Windows account/machine**, legacy DPAPI `.cred` files
may be copied from:

`D:\Projects\S-Talking\credentials\`

to:

`<Portable>\S-Talking-Data\settings\credentials\`

On the first successful credential read, the frozen app migrates the secret into Windows
Credential Manager and securely deletes the legacy `.cred` file. A DPAPI file should not
be expected to decrypt on another Windows user/profile or another machine.

Portable packages must continue to exclude local profiles and credentials by default.

## Acceptance gates

1. compileall + Ruff
2. B6 Hotfix 3 dedicated tests
3. non-modal startup/path recovery regression
4. Provider Accounts layout regressions
5. B6-H2/B4/A12.1/A11 visual regressions
6. Track A provider/routing/language authority regressions
7. B5/B6 Intelligent TTS continuity
8. new font-valid runtime visual certification
9. Full Quality Gate exactly once
10. commit/push only after all gates pass
11. manual review of generated Dark/Provider Accounts screenshots before B7 freeze
