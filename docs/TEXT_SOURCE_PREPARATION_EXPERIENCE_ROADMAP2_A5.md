# Roadmap 2 / Track A / A5 — Text / Source Preparation Experience

## Baseline

Official A4 + Hotfix 1 commit:

`97d0c9f89be06c4f9c4bce07b74ff2c8201b867e`

A4 certified Voice & Model Discovery while preserving explicit provider/account
authority, explicit Preflight, explicit generation start and schema contract 23.

## Product goal

A5 productizes journey 4 from the A1 UX baseline: **Text/source preparation**.

The existing Text Studio, Phase91 preparation funnel and Source Import Review remain the
single preparation path. A5 does not create a second queue or source-import architecture.

## Text Studio handoff visibility

Text Studio now keeps an explicit queue-handoff status visible below its metrics.

The status explains whether the handoff is:

- waiting for source rows;
- blocked by preparation issues;
- ready for Source Import Review.

When ready, the user is told that Source Import Review comes next, that a confirmed
import rebuilds the queue, that Preflight is invalidated rather than run, and that
generation is not started.

Duplicate-text warnings remain an explicit review decision and are not silently removed.

## Source Import Review safety

Source Import Review now receives the current queue size and source count from MainWindow
and presents an explicit queue-impact card.

The dialog explains:

- how many valid sources/jobs are available;
- whether the current queue is empty or will be rebuilt;
- how many valid selected sources/jobs will be imported;
- that Import selected requires an actual valid selection;
- that a confirmed import invalidates existing Preflight evidence;
- that Preflight does not run automatically;
- that generation does not start automatically.

`Import selected` can no longer accept an empty selection and accidentally hand off an
empty accepted set.

## Onboarding handoff

The existing `project_sources` onboarding step is preserved, but its action now opens
Text & Source Preparation directly instead of the more generic Project Continuity view.

The six-step onboarding structure remains unchanged.

## Authority boundary

A5 does not:

- change provider/account/voice/model;
- refresh provider catalogs;
- run Smart Routing;
- run Preflight;
- start or restart generation;
- introduce cross-provider failover;
- change queue ordering policy beyond the existing explicit source-import replacement;
- change database schema.

Database schema remains **23**.
