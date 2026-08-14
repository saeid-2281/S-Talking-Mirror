# Roadmap 2 A7.4 — Pronunciation Decision Freshness, Revalidation & Safe Reuse

A7.4 makes pronunciation review evidence context-aware without introducing automatic language, provider, voice, model, dictionary, Preflight, generation, or routing changes.

## Contract

- Source text remains authoritative and is never rewritten by review or revalidation.
- User-selected project language and explicit per-job language overrides remain authoritative.
- New `original` / `normalized` review decisions are stored with a deterministic A7.4 pronunciation-context fingerprint.
- The fingerprint includes only pronunciation-critical inputs: job text, effective target language, provider, voice, model, active pronunciation dictionary id and dictionary locators.
- Unrelated settings such as speed, retry count, delay, output folder, theme, or UI state do not invalidate a review decision.
- Changing pronunciation-critical context marks versioned review evidence stale.
- Pre-A7.4 plain `original` / `normalized` decisions remain readable as legacy evidence and require explicit revalidation in freshness-aware workflows.
- Stale or legacy keep-original evidence is surfaced for review; source/provider text is still unchanged.
- Stale or legacy normalized evidence is a hard Preflight error and cannot be silently reused.
- `PronunciationService` refuses stale versioned normalized execution rather than falling back silently.
- Revalidation is an explicit selected-row action and preserves the user's original-vs-normalized intent.
- A normalized decision can be revalidated only when a safe language-locked normalized candidate still exists.
- Review decisions cannot be changed or revalidated while generation is active.
- No automatic Language Probe preview, Preflight, generation, Smart Routing apply, hidden failover, provider/account/voice/model/language switch, or content-based language detection is introduced.
- Database schema 23 remains unchanged.

## Review Workspace

The Pronunciation Review Workspace adds freshness visibility and a `Needs revalidation` filter. Rows show `Current`, `Stale`, `Legacy`, or no freshness evidence. `Revalidate selected decisions` emits an explicit request; it never performs synthesis, routing, Preflight, or generation.

## Safe reuse

A review decision can be reused when its pronunciation-critical fingerprint still matches. This allows stable reuse across operational changes that do not affect pronunciation while forcing re-review after changes that can affect spoken output.
