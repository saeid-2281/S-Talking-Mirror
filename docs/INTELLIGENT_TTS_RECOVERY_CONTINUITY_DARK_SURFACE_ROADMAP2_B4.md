# Roadmap 2 B4 — Intelligent TTS Recovery Continuity & Dark Surface Polish

## Certified baseline

B4 starts from B3 commit:

`9ddf1b06d80c441699cb129ace88874cbc3f4cbe`

B1 production manifests, B2 execution bindings, B3 durable run ledgers and the B2 Dark Theme correction are frozen inputs.

## Recovery continuity

B3 made one run durable from approval through terminal outcome. B4 links an explicit Safe Resume child run back to the exact parent run ledger and the already-created resume receipt.

The child ledger receives a hash-chained `recovery_lineage` event containing parent run id, verified parent ledger path/digest/status when available, resume receipt id/path and an explicit continuity status. Missing or invalid historical parent evidence is surfaced; B4 never invents a parent digest or silently replaces damaged evidence.

## Restart visibility

At startup B4 scans the Intelligent TTS ledger evidence directory for verified non-terminal ledgers and records the count in the application log. This is visibility only. Existing recovery and Safe Resume remain user-controlled.

## Authority freeze

B4 does not change provider/account/voice/model/language, infer language from text, prepare or reorder recovery jobs, retry failed jobs, choose a recovery provider, run Preflight, start/restart Generation, apply Smart Routing, or introduce hidden cross-provider failover. Database schema 23 is unchanged.

## Dark Theme nested-surface polish

The real post-B2 screenshot still showed legacy blue/navy tones inside nested Provider and Selected Row cards/inputs even though the dock roots were already semantic.

B4 makes the final semantic layer authoritative for nested dock content:

- QFrame/QGroupBox card structures use `surface`;
- Provider/Inspector input controls use `surface_secondary`;
- object-name-independent runtime properties prevent extracted widgets from falling back to old navy rules;
- System / Light / Dark remain palette-driven;
- primary actions and status semantics are not recolored.

## Evidence

B4 machine evidence:

`artifacts/intelligent-tts-production/roadmap2-b4/`

Three-theme screenshot evidence is refreshed through the existing A12.1 certifier.

## Exit criteria

B4 closes only after 14 recovery-continuity tests, 8 nested Dark Theme tests, 15/15 B4 machine certification, B1-B3 regressions, Safe Resume/crash recovery regressions, Track A authority regressions, fresh System/Light/Dark screenshot evidence, historical QProcess regression, one Full Quality Gate, commit/push verification and a clean source Working Tree excluding local-only profiles.

Next: **Roadmap 2 B5**.

## Hotfix 1 — Preserve the certified B2 canvas hierarchy

The initial nested-surface pass treated every `QFrame` as a nested `surface`.
Because `QAbstractScrollArea` inherits from `QFrame`, the Provider page scroll
area and Generation Monitor scroll area were incorrectly changed from their
certified B2 `canvas` family to `surface`.

Hotfix 1 preserves the established hierarchy:

- every `QAbstractScrollArea` remains `canvas`;
- any widget already carrying `a121SurfaceFamily=canvas` remains authoritative;
- descendants are still processed independently, so nested cards stay
  `surface` and input controls stay `surface_secondary`;
- the two exact B2 regressions are now explicitly covered by B4 tests.

Recovery continuity and all provider/account/voice/model/language, Preflight,
Generation, Smart Routing and Database schema 23 authority are unchanged.
