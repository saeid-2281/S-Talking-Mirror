# Phase 91 — Text / Source / Batch Preparation UX 2.0

Phase 91 starts the second product-value step of S-Talking 1.1. It keeps Text Studio as the single source-preparation workspace and adds a deterministic preparation funnel instead of creating another dialog.

## Preparation flow

Text Studio now exposes five live stages:

1. **Input** — manual text and selected document sections.
2. **Structure** — enabled chunks and oversize checks.
3. **Quality** — blocking filename/text issues and warnings.
4. **Batch** — selected, enabled and disabled row state.
5. **Queue** — readiness for the existing Source Import Review.

The primary action always reflects the next safe step: add source, safe prepare, review duplicates, review issues, or review/add to queue.

## Safe prepare contract

`Safe prepare enabled` is intentionally non-destructive with respect to content. It can:

- normalize accidental whitespace in enabled rows;
- split oversized enabled chunks with the existing Smart Split algorithm and configured character limit;
- preserve disabled rows exactly and keep them disabled;
- repair invalid enabled filenames and make enabled filenames unique deterministically.

It **does not delete duplicate text**. Duplicate removal remains an explicit user action in the existing Preparation Check tools.

## Queue safety

Phase 91 does not bypass source review or generation safety. Queue handoff remains:

`Text Studio → normalized CSV → Source Import Review → queue → Preflight → Start`

No provider routing, queue ordering, launch guard, billing, quota or generation semantics are changed.
