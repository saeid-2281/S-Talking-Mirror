# Phase 76 — Billing Dispute Resolution & Settlement Verification

Phase 76 extends verified Phase 75 provider billing reconciliation evidence into a human-controlled dispute and settlement workflow.

## Scope

The workflow verifies a complete Phase 75 evidence set:

- billing reconciliation result;
- billing reconciliation attestation;
- dispute-readiness pack;
- pack receipt.

A dispute case can only be recorded for a reconciliation result whose outcome is `withheld`. The recorded claim cannot exceed the verified reconciliation variance.

## Settlement evidence

A human reviewer records the provider response, approved credit, applied credit, remaining variance and the reviewed ledger state. The outcome is one of:

- `settled` — the complete requested credit is applied and no variance remains;
- `partially_settled` — some credit is applied but follow-up remains;
- `rejected` — the provider response is reviewed but no credit is approved;
- `withheld` — required response or ledger evidence is incomplete or inconsistent.

Each record is protected by SHA-256 and linked to immutable source evidence. A closure pack and receipt provide portable verification.

## Safety contract

Phase 76 never performs any of the following automatically:

- submit a provider dispute;
- request a refund;
- send email;
- upload evidence;
- change a billing ledger;
- execute a provider action;
- make a release decision.

The GUI, CLI and PowerShell entry points only create or verify local evidence after explicit human acknowledgement.

## CLI

Create a readiness snapshot:

```powershell
.\S-Talking.exe --billing-dispute-resolution-snapshot
```

Verify a case:

```powershell
.\S-Talking.exe --verify-billing-dispute-case <case.json>
```

Verify a closure pack:

```powershell
.\S-Talking.exe `
  --verify-billing-closure-pack <closure-pack.zip> `
  --billing-closure-receipt <receipt.json>
```
