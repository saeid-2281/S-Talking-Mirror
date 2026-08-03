# Generation Launch Guard Policy Profiles & Templates — Phase 41

## Goal

Phase 41 turns project baseline guard settings into reusable, versioned policy profiles. Operators can apply consistent protection across projects, lock project policies against accidental edits, preserve an audit history, and record the active policy version inside each launch receipt.

## Built-in profiles

- **Strict production** — Enforce every protected category.
- **Balanced** — Warn and require acknowledgement for all categories.
- **Experimental** — Warn only for output policy, risk/cost, and integrity.
- **Provider migration** — Permit provider changes while protecting output, execution, scope, cost, and integrity.

Built-in profiles are read-only. The default profile is **Balanced** unless changed by the operator.

## Custom profiles

Custom profiles contain only:

- Profile ID and display name
- Description
- Guard mode
- Protected category names
- Created and updated timestamps

Profiles can be created, edited, deleted when unused, imported, exported, and selected as the default for projects without an explicit policy.

## Project policy governance

Each explicit project policy now stores:

- Applied profile ID and name
- Mode and protected categories
- Lock state
- Monotonic policy version
- Last operator
- Up to 100 immutable history entries

A locked policy rejects changes until an operator explicitly unlocks it. Applying a profile creates a new version rather than rewriting earlier history.

## Launch receipts

Schema 2 launch receipts now include a secret-free `guard_policy` object:

```json
{
  "profile_id": "strict-production",
  "version": 3,
  "locked": true
}
```

The policy metadata is covered by the existing receipt SHA-256 integrity digest.

## UI entry points

- **Reports → Guard Policy Profiles**
- Toolbar overflow → **Guard Policy Profiles**
- Command Palette → **Reports: Guard Policy Profiles**
- Launch Receipt Center → **Baseline guard policy** → **Manage profiles**

## Compatibility

- Existing Phase 38–40 project guard policies remain readable.
- Projects without an explicit policy inherit the current default profile without creating a policy record.
- No database migration is required; database schema remains version 22.
- API keys, credentials, source text, and receipt contents are never stored in profile or policy files.
