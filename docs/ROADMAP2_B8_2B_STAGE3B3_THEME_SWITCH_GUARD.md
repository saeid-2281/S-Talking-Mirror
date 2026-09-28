# Roadmap 2 B8.2B Stage 3B-3 — Theme Switch Repaint Guard

## Evidence basis

The Stage 3B-3 attribution run isolated the live theme-switch stall to
`QApplication.setStyleSheet()`: the measured worst switch was 18,857.5 ms and
18,840.5 ms of that interval was inside application stylesheet installation.
Palette installation was 0.2 ms, icon refresh was at most 10.9 ms, and the
accessibility refresh was at most 5 ms.

## Change

Keep QApplication as the single theme authority and preserve the complete
Soft Professional Light/Dark/System stylesheet contract. During an actual
stylesheet change, temporarily disable updates on current top-level widgets,
install the new application palette and stylesheet, then restore updates in a
`finally` block and request one final repaint.

The same guard covers the comparatively rare full stylesheet rebuild caused by
high-contrast or enhanced-focus preference changes.

## Safety boundaries

- No provider/account/voice/model/language behavior changes.
- No queue, project, generation, database, billing or credential behavior changes.
- No B7 frozen-source changes.
- No removal or simplification of the certified A8/A11/A12 visual layers.
- QApplication remains the stylesheet authority.
- Update restoration is exception-safe and tolerates deleted Qt wrappers.

## Acceptance gate

Automated tests must pass first. The change is not runtime-certified until a
real Windows Light -> Dark -> System switch run demonstrates that the previous
~19 second stall is materially reduced without visual corruption.
