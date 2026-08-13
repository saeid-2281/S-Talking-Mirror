# Roadmap 2 A7.3 — Pronunciation Review Workspace & Explicit Batch Decisions

## Goal

A7.3 turns the A7.2 pronunciation-risk evidence into a scalable review workflow for large queues while preserving the authority contracts established by A7.1 and A7.2. The user-selected project language, or an explicit per-job language override, remains authoritative. Review never detects a replacement language and never changes provider, account, voice, model, language, source text, or generation state automatically.

## Explicit review semantics

A7.3 separates **reviewed** from **normalized**:

- `original` records that the user reviewed the row and explicitly chose to keep the original provider text;
- `normalized` records that the user reviewed the row and explicitly chose the safe language-locked normalized candidate;
- no override means the row remains unreviewed when A7.2 reports medium/high pronunciation risk.

The `original` decision does not mutate source text and preserves pronunciation-dictionary metadata. `normalized` remains valid only when A7.2 produced a safe candidate; unsafe normalized decisions still fail closed in Preflight.

## Pronunciation Review Workspace

The Generation menu, command palette, and queue context menu expose **Pronunciation Review Workspace**. It operates on the current explicit generation scope and provides:

- default **Needs review** filtering;
- High risk, Medium risk, Safe normalized candidate, Reviewed, and All review-candidate filters;
- search across row, filename, source text, language, risk signals, normalized candidate, and decision;
- visible source text and normalized candidate side by side;
- explicit multi-row **Use original**, **Use normalized**, and **Clear decision** actions;
- manual handoff of one to three selected rows to Language Probe.

Opening, filtering, searching, or selecting rows never changes any job. A decision is applied only after the user explicitly selects rows and presses a decision button. Normalized action is disabled unless every selected row has a safe language-locked candidate.

## Language Probe integration

A7.3 keeps A7.2 Language Probe manual. **Keep original** now records the explicit `original` review decision instead of merely clearing the override. Preview actions still only preload Voice Browser text; the user must press Preview manually.

## Preflight evidence

Preflight now records:

- unresolved high-risk rows;
- unresolved medium-risk rows;
- safe normalizable rows;
- reviewed rows;
- explicit-original rows;
- normalized rows;
- the per-row review decision in pronunciation preview evidence.

A medium/high-risk row with an explicit valid `original` or safe `normalized` decision is no longer reported as unreviewed. Changing or clearing a decision still changes the existing Preflight revision key, so old evidence becomes stale.

## Safety invariants

A7.3 does **not**:

- auto-select review rows;
- auto-apply original or normalized decisions;
- normalize unsafe rows;
- mutate source/job text;
- detect or replace target language;
- auto-run Language Probe audio;
- auto-run Voice Browser preview;
- auto-run Preflight;
- auto-start generation;
- auto-change provider, account, voice, model, or language;
- auto-apply Smart Routing;
- add hidden cross-provider failover;
- change database schema 23.

Review decisions are blocked while generation is active.
