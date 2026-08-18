# Roadmap 2 / B6 Hotfix 3 / Hotfix 9 / Hotfix 6 / Hotfix 3 / Hotfix 1

## Inherited H5 body-host contract reconciliation

Hotfix 6 Hotfix 3 established the intended queue-shell ownership contract:

- `queueChromeHost` is fixed and top-aligned.
- `queueBodyHost` is the sole vertically expanding queue work-surface host.
- the collapsed queue chrome is physically contiguous.
- the original `launch -> summary <= 220px` acceptance envelope passes.

The H6H3 run passed its own shell-surplus tests, H6H2 bounded chrome-height tests,
the original H9 vertical-rhythm/typography contract, and H6 canonical composition.
It stopped only because the inherited H5 source-level regression still expected the
pre-H6H3 implementation detail `self.shell_layout.addLayout(self.body_layout, 1)`.

H6H3 intentionally replaced that raw layout insertion with a real expanding QWidget:
`queueBodyHost`, whose internal `body_layout` hosts the queue work surface. This
continuation updates only that inherited test contract to assert the new explicit body
host and its expanding size policy. No production/runtime source is changed.

Provider/routing/Preflight/Generation authority, credential semantics, portable-mode
semantics, Track A freezes, and database schema 23 remain outside the continuation.
