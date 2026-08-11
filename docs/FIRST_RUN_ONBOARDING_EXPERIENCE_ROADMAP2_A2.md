# Roadmap 2 / Track A / Phase A2 — First-run / Onboarding Experience

## Purpose

A2 turns the A1 first-run gap into a visible, resumable Getting Started experience. It guides a new user through the existing production workflow without silently making production decisions for them.

## Six-step onboarding path

1. Understand the production workflow.
2. Review Provider Accounts readiness.
3. Review voice/model choices in the unified catalog.
4. Create or continue a project and prepare sources.
5. Understand Preflight and explicit launch approval.
6. Understand live generation and output review.

The onboarding UI exposes explicit handoffs into existing product tools. Opening a handoff never marks a step complete; the user explicitly marks each step reviewed.

## Persistence

Progress is stored outside the database in `first-run-onboarding.json` under the runtime data directory. Reading state is side-effect free. Missing, malformed or schema-incompatible state safely resolves to an incomplete default state without an automatic write.

Completion requires all required steps to have been explicitly reviewed. Resetting onboarding affects only the onboarding checklist.

## Product integration

- Help → **Getting Started / First-run Onboarding** is always available.
- The command palette exposes the same action.
- While onboarding is incomplete, a compact **Getting Started · x/6** status-bar entry remains visible.
- Completion hides the status entry but does not remove the Help action, so the guide remains revisitable.
- No blocking modal is automatically launched on application startup.

## Safety / authority contract

A2 does not:

- switch provider, account, voice or model;
- refresh provider catalogs;
- probe provider/network readiness automatically;
- run Preflight;
- start or restart generation;
- perform hidden cross-provider failover;
- modify database schema or write onboarding state to the database.

Smart Routing remains recommendation-only. Preflight validates. The user decides. Generation Engine executes.

Database schema remains **23**.

## A1 baseline closure

A1 identified the missing persistent `first_run_completed` state as a first-run opportunity. A2 supplies that explicit persistent state and keeps the Product UX Audit evidence contract intact.

## Next

**Roadmap 2 A3 — Provider Setup Wizard** will deepen the provider setup path without transferring provider/account selection authority away from the user.
