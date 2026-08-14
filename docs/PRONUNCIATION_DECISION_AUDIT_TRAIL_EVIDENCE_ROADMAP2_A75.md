# Roadmap 2 A7.5 — Pronunciation Decision Audit Trail & Evidence

## Objective

A7.5 makes explicit pronunciation review decisions traceable without changing the authority model established by A7–A7.4. The audit trail is evidence only. It cannot select or change a provider, account, voice, model, language, routing plan, Preflight result, or generation action.

## Recorded explicit actions

The audit trail records only user-driven pronunciation decision lifecycle events:

- `decision_set` for explicit `original` or `normalized` review decisions.
- `decision_cleared` when a previously reviewed decision is removed or replaced by a non-review pronunciation override.
- `decision_revalidated` when the user explicitly revalidates the same `original`/`normalized` intent under the current A7.4 pronunciation-critical context.

Review Workspace and Language Probe decisions share the same centralized recording path. Dictionary/project pronunciation overrides do not become review decisions, but replacing an existing reviewed decision records a clear event so the history has no silent gap.

## Privacy-safe evidence contract

Persisted audit events intentionally exclude:

- raw source text;
- raw normalized candidate text;
- API keys, credentials, or account secrets;
- raw voice IDs;
- raw model IDs;
- raw pronunciation dictionary IDs/locators;
- raw project identifiers in the audit filename or event payload.

Evidence keeps only the minimum fields required for traceability: row number, UTC timestamp, action, decision kind, previous decision kind, A7.4 context fingerprint, effective language, provider ID, hashed voice/model/dictionary references, risk level, normalization kind/safety, freshness at record time, and audit-chain hashes.

## Append-only hash chain

Project audit events are stored as JSON Lines under the selected output directory:

`.s-talking/pronunciation-audit/project-<project-ref>.jsonl`

Each event contains `previous_event_hash` and `event_hash`. The service verifies the complete chain before appending or exporting evidence. A corrupted/tampered chain is reported as an integrity failure and is never silently extended.

The logical history is append-only: earlier events are never edited or deleted by A7.5.

## Decision recording safety

A user decision is applied through the existing centralized pronunciation override path. If audit evidence cannot be recorded, the in-memory pronunciation decision is rolled back and the user receives an explicit error. This prevents a normal UI decision from appearing successfully applied while silently missing A7.5 evidence.

Revalidation keeps the A7.4 intent unchanged and remains blocked while generation is active. Unsafe normalized candidates remain non-revalidatable.

## Review Workspace evidence

The Pronunciation Review Workspace shows:

- project audit event count and verified-chain status;
- decision-set, revalidation, and clear counts;
- per-row event count;
- most recent audit action/time;
- a current-context note derived without storing raw text.

A stale reason can identify safe context dimensions such as effective language/provider/voice/model/dictionary changes. If every other pronunciation-critical dimension matches but the A7.4 fingerprint changed, the report identifies source text as the changed context without persisting that text.

## Explicit evidence export

`Export audit evidence` is a user-triggered action. It creates a privacy-safe Markdown report in the output directory. Export does not open Voice Browser, run Preflight, synthesize audio, start generation, apply Smart Routing, or mutate pronunciation decisions.

## Preserved authority boundaries

A7.5 preserves all established constraints:

- source text is not mutated;
- user-selected target language remains authoritative;
- per-job language overrides remain explicit;
- no content-based language detection override;
- no automatic provider/account/voice/model/language changes;
- no automatic Preflight;
- no automatic generation or restart;
- no automatic Smart Routing apply;
- no hidden cross-provider failover;
- Database schema 23 is unchanged.

## Next fixed roadmap objective

After successful A7.5 certification, continue directly to:

**Roadmap 2 A7.6 — Pronunciation Coverage & Project Readiness**
