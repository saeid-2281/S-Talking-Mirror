# Roadmap 2 B6 Hotfix 3 / Hotfix 9 / A9.1 Hotfix 2

## Purpose

Reconcile the remaining historical A9.1 launch-strip spacing assertion with the
already-certified Hotfix 9 vertical-rhythm authority.

The previous A9.1 continuation correctly adopted the H9 queue-heading geometry
(`12 / 5 / 10 / 5` margins and `6px` heading spacing), but one inherited
assertion still required `GenerationStatusStrip.layout().spacing() == 8`.
Runtime evidence from the failed continuation shows the H9 production geometry
is `6px`, while the H9 vertical-rhythm, bounded-chrome, shell-surplus,
progressive-disclosure, and canonical-composition gates already pass.

## Scope

This continuation is **test-contract only**. No production/runtime source is
changed.

- Keep the H9 `<=220px` launch-to-summary envelope unchanged.
- Keep the 46px queue-heading authority unchanged.
- Keep Queue command spacing at 6px.
- Accept the H9 primary launch-strip spacing authority of 6px instead of the
  pre-H9 A9.1 literal 8px.
- Preserve Provider, routing, Preflight, Generation, credential, portable, and
  database authority.
- Preserve Phase89/Phase92 progressive-disclosure behavior.
- Preserve System / Light / Dark certification and H8 pixel-color thresholds.

## Acceptance

The continuation must first pass A9/A9.1 historical compatibility, then rerun
all H9 geometry regressions, Phase89/92 compatibility, three-theme and pixel
certification, Track A/B6 authority smoke, the QProcess regression, and finally
one Full Quality Gate. Commit/push and a fresh TRUE Portable are allowed only
after every gate passes.
