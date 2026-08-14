# Roadmap 2 A7.8 — Track A End-to-End Product Acceptance

A7.8 is the acceptance-only closure pass for the Track A product workflow. Production application source changed by A7.8: NO.

The goal is to prove that the already-implemented product experience works as one coherent user journey rather than as isolated phase features:

1. first run and resumable onboarding;
2. explicit provider/account setup;
3. explicit voice/model/language selection;
4. text/source preparation and queue planning;
5. pronunciation review, freshness, audit evidence, and project readiness;
6. explicit Preflight and launch review;
7. `Preflight Context == Launch Context == Generation Context`;
8. generation lifecycle including pause/resume/stop, failure/retry/recovery contracts;
9. audio/output review and export;
10. cloud and local provider contexts without hidden provider changes.

## Acceptance matrix

The committed `scripts/track-a-product-acceptance.ps1` harness executes eight independently evidenced lanes and writes JUnit XML plus a privacy-safe JSON summary beneath `artifacts/track-a-product-acceptance/`.

- First-run / provider / voice-model
- Text-source / queue / batch preparation
- Pronunciation / Preflight / launch assurance
- Generation lifecycle / pause-resume-stop / recovery
- Audio output / review / export
- Cloud-local provider matrix / Danish authority
- 4001-row / mixed-language acceptance
- QProcess / release compatibility

The 4001-row acceptance check validates deterministic request identity without mutating the source jobs. Mixed-language acceptance uses explicit per-job language overrides; it does not introduce content-based language detection.

## Authority freeze

A7.8 does not add workflow authority. It only executes and records acceptance evidence for existing behavior.

- User-selected provider/account/voice/model/language authority: PRESERVED
- Per-job explicit language override authority: PRESERVED
- Content-based language detection override: DISABLED
- Automatic provider/account/voice/model/language change: DISABLED
- Automatic Preflight: DISABLED
- Automatic generation: DISABLED
- Automatic Smart Routing apply: DISABLED
- Hidden cross-provider failover: NOT INTRODUCED
- Source text mutation: NOT INTRODUCED
- Database schema 23: PRESERVED

No live synthesis is required by the acceptance harness. Provider coverage is established through deterministic provider contracts and the existing provider regression suites; no credential or private source material is written into acceptance evidence.

## Evidence and failure semantics

Every acceptance lane is fail-closed. A lane with no required test files, a failing pytest invocation, malformed JUnit evidence, or a non-zero failure/error count blocks A7.8. The harness records only test metadata, paths, counts, durations, source commit identity, and status. It does not record API keys, raw source text, normalized source text, or raw credential values.

A7.8 is not allowed to silently rerun Preflight, start generation, alter routing, repair provider selection, or approve pronunciation decisions.

## Next fixed step

After A7.8 passes the focused acceptance matrix and the final Full Quality Gate, the next fixed Roadmap step is **A7.9 — Track A Certification & Freeze**. A7.9 is the certification/freeze phase and must not add new Track A features.
