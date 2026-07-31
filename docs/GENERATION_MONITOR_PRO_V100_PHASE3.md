# Generation Monitor Pro v1.0 — Phase 3

Adds the user-facing interrupted-session recovery workflow. A validated snapshot
is presented after session/project restore with provider identity, output,
progress, and recoverable job counts. Users can resume pending work, include
failed jobs in retry, discard the snapshot, or defer. Recovery refuses active
generation, confirms queue replacement, restores persisted jobs, records
activity/notifications, and runs normal preflight before continuing.
