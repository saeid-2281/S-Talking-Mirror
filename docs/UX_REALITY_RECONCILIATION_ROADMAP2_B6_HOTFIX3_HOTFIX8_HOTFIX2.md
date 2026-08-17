# Roadmap 2 B6 Hotfix 3 — Hotfix 8 Hotfix 2

## A12.1 runtime certifier reconciliation

Hotfix 8 deliberately keeps the historical `ThemeManager.tokens()` and
`ThemeManager.palette()` contracts while projecting the rendered Dark QSS onto
the selected Soft Professional surface family. Qt stylesheet polish therefore
makes the live `QWidget.palette()` window role equal the semantic Dark canvas
(`#121413`) even though the compatibility API still reports the historical
Dark window token (`#0B1220`).

The A12.1 runtime certifier still assumed those two layers had to be identical,
so it returned `FAILED` even after the Phase25/A11/A12.1 source-level contracts
were reconciled. This continuation updates only the certifier/test evidence
contract:

- historical ThemeManager/QPalette API remains unchanged;
- effective Dark rendering must resolve to the Soft Professional semantic canvas;
- Light remains historical QPalette-authoritative;
- System follows its effective resolved Light/Dark theme;
- three-theme screenshots and all workflow/provider/database authorities remain unchanged.

No production workflow, provider, routing, Preflight, Generation, credential,
portable, or database behavior is introduced by this continuation.
