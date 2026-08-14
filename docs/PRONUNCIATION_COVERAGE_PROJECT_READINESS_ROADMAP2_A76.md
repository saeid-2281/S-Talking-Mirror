# Roadmap 2 A7.6 — Pronunciation Coverage & Project Readiness

A7.6 adds a read-only project-level pronunciation readiness projection on top of the existing A7.2–A7.5 assurance, freshness, review, and audit evidence.

## Readiness categories

Every job in the current generation scope is assigned exactly one category:

- **Ready** — an explicit `original` or safe `normalized` decision is current for the pronunciation-critical context.
- **Needs review** — a medium/high pronunciation-risk row has no current explicit review decision.
- **Stale** — explicit review evidence is stale or legacy and requires revalidation.
- **Unsafe** — an explicit normalized decision exists but a safe language-locked normalized candidate is no longer available.
- **No action required** — no medium/high pronunciation risk requires an explicit decision.

The project summary exposes total jobs, pronunciation-risk rows, reviewed-current rows, stale decisions, unresolved rows, normalized decisions, keep-original decisions, and audit integrity/event counts.

## Authority boundary

The A7.6 dashboard is visibility only. It performs no bulk approval and does not mutate jobs or pronunciation decisions. It does not change provider, account, voice, model, dictionary, language, or per-job language override. It does not run Preflight, start/restart generation, apply Smart Routing, or introduce hidden cross-provider failover. Content-based language detection remains disabled. Preflight and Generation remain authoritative for launch/execution.

A7.5 audit integrity is surfaced as `EMPTY`, `VERIFIED`, or `FAILED`; an integrity failure is visible and never silently rewritten. The readiness layer itself has no generation authority.

Database schema 23 is unchanged.

Next fixed roadmap stage: **A7.7 — Launch Assurance Consolidation**.
