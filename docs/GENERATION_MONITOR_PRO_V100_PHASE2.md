# Generation Monitor Pro v1.0 — Phase 2

Adds an atomic, checksummed recovery snapshot for interrupted generation runs.
Snapshots include provider/profile/model/voice identity, output path, monitor
session metrics, and every queue job. Running jobs are safely restored as
pending; failed jobs can optionally be reset for retry. Successful completion
discards the snapshot, while stopped/failed/closed runs remain recoverable.
