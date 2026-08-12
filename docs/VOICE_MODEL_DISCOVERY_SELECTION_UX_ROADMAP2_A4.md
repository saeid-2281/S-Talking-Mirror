# Roadmap 2 / Track A / A4 — Voice & Model Discovery & Selection UX

Baseline: `e19819d6b858e2a45989af1c087a5428c37e4797`

A4 productizes journey 3 from the A1 UX baseline without creating a second catalog
or routing architecture. Phase106 remains the metadata source.

Opening Discovery is cached-first and side-effect free. Users can see the current
provider/account/voice/model/language, apply quick filters, inspect compatibility,
maximum text length and cost-factor metadata, and review exactly what a selection
would change before explicitly confirming it.

If an item belongs to a specific provider account, explicit approval applies that
exact profile ID rather than silently substituting another active account.

Discovery never automatically changes provider/account/voice/model, refreshes a
provider, tests credentials, runs Preflight, starts/restarts generation, applies
Smart Routing, or performs cross-provider failover.

Historical Phase106 public dialog attributes and the existing MainWindow catalog
action/shortcut remain compatible. Database schema remains 23.

Next: A5 — Text / Source Preparation Experience.
