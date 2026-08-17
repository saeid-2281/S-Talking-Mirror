# Roadmap 2 B6 — Intelligent TTS Production Operations Intelligence

## Certified baseline

B6 starts from the successful B5 commit:

`134789743b749f68e2016ffc651d0a131bbf86e7`

B1 production manifests, B2 execution bindings, B3 run ledgers, B4 recovery
lineage, B5 artifact provenance and the B4 Dark Theme hierarchy are frozen
inputs.

## Purpose

B1–B5 make an Intelligent TTS run traceable from approved request to the final
audio artifact. B6 turns that evidence into production-operations intelligence
without taking execution authority.

For each terminal run B6 records a privacy-safe operations snapshot with:

- request / completed / failed / skipped counts;
- completion rate;
- elapsed time;
- retry event count;
- files per minute;
- characters per minute;
- verified artifact count;
- artifact integrity issue count and status;
- execution-receipt id;
- resume / parent-run provenance;
- provider/profile/voice/model/default-language identity from the frozen B2
  binding;
- a health classification: `healthy`, `warning`, or `attention`.

## Project rollup

B6 also derives a project-level rollup over verified run snapshots:

- total / completed / failed / cancelled runs;
- total requests and outcomes;
- weighted completion rate;
- verified files and artifact issues;
- resume-run count;
- total retries;
- average elapsed time and throughput;
- healthy / warning / attention run counts;
- invalid/tampered operations evidence count;
- latest run/result.

The rollup is observational and may be regenerated from the underlying run
snapshots.

## Evidence integrity

Run snapshots and project rollups have deterministic SHA-256 digests. A modified
snapshot or rollup fails verification.

A terminal run snapshot is immutable. Repeating finalization for the same
run/evidence returns the existing snapshot; conflicting evidence for the same
run is rejected.

## Privacy

B6 does not store:

- raw source text;
- API keys or credentials;
- arbitrary queue payloads;
- audio file contents.

It reuses privacy-safe identifiers and numeric metrics already available in the
B1–B5 evidence chain.

## Authority freeze

B6 does not:

- start or restart Generation;
- run Preflight;
- retry jobs;
- recover/resume jobs automatically;
- select or switch provider/account/voice/model/language;
- infer language from text;
- apply Smart Routing;
- reorder the queue;
- delete, rename, replace or regenerate output files;
- migrate Database schema 23.

## MainWindow integration

Terminal finalization order is:

1. existing execution session / receipt;
2. B5 artifact receipt;
3. B6 operations snapshot and project rollup;
4. B3/B4/B5 run-ledger final event.

The run ledger receives the B6 operations snapshot path so the evidence chain is
navigable end-to-end.

## Visual freeze

B6 does not modify the B4 Soft Professional theme implementation. B4 nested
surface, B2 canvas and System / Light / Dark regressions remain focused guards.

## Evidence location

Machine certification:

`artifacts/intelligent-tts-production/roadmap2-b6/`

Runtime operations evidence:

`<reports_dir>/intelligent-tts-operations/<project>/`

## Exit criteria

B6 closes only after:

- 14 operations-intelligence service tests;
- 8 MainWindow integration tests;
- 15/15 machine certification;
- B1–B5 Intelligent TTS regressions;
- execution receipt / Safe Resume / budget regressions;
- B4 Dark Theme and historical visual regressions;
- Track A provider/routing/language authority regressions;
- historical QProcess regression;
- one Full Quality Gate;
- commit/push verification;
- clean source Working Tree excluding local-only profile files.

Next: **Roadmap 2 B7 — Track B End-to-End Acceptance, Certification & Freeze**.
