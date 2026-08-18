# Roadmap 2 — B6 Hotfix 3 / Hotfix 10

## Frozen UX acceptance polish and range recovery

Manual review of the certified H9 TRUE Portable at commit
`5d3b448a02c2497997bb0b93a9d8c440fe0c21e2` exposed three user-visible issues
that static H9 certification did not cover:

1. 24px toolbar icons sat visually too close to the lower toolbar border instead
   of being optically centered.
2. The filled `Start generation` action read materially larger than adjacent
   generation controls despite sharing the same 34px height contract.
3. The historical row-range workflow was no longer discoverable.  H9 had made
   the range host structurally follow the Batch-plan disclosure, even though the
   underlying controller still supports both original source-row ranges and
   current displayed-order ranges.

Hotfix 10 is presentation/interaction recovery only.  It does not change
provider, account, voice, model, language, routing, Preflight or Generation
authority, and it does not change database schema 23.

### Toolbar

The main toolbar remains 42px high with 24px DPR-aware icons.  Its final Soft
Professional layer now fixes action widgets to a centered 32px control box with
balanced top/bottom toolbar inset, preventing the frozen Windows toolbar from
visually hugging its lower border.

### Primary generation action

The visible primary label is shortened to `Start` while the accessibility name
remains `Start generation`.  All launch controls remain exactly 34px high.

### Queue row / source row distinction

The model-view queue again shows its vertical row header.  These numbers are the
current displayed queue positions (1..N) and remain separate from the existing
`Source row` column, which preserves the source-file row identity.  This avoids
changing the stable queue-model column contract.

### Range recovery

A dedicated `Range` disclosure is restored in the queue heading.  It exposes the
existing `From` / `To` controls and the existing basis selector:

- `Original source row`
- `Current displayed order`

The range row remains structurally collapsed by default, so H9's compact
`<=220px` launch-to-summary envelope is preserved when range editing is not in
use.  Batch plan retains its historical behavior of surfacing the same range
row.  Compact responsive mode continues to hide optional disclosure chrome.
