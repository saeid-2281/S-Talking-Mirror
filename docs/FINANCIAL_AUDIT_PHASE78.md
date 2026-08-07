# Phase 78 — Financial Audit & Cost Integrity

Phase 78 completes the provider-billing financial-control chain.

It consumes verified Phase 75 billing reconciliation evidence together with
Phase 77 provider-credit close evidence and proves that final provider charges
agree with the reviewed internal ledger after dispute credits are applied.

## Integrity equation

For every provider invoice in the selected accounting period:

`final net invoice = Phase 75 net invoice - Phase 77 settled credit`

The final net invoice must agree with the reviewed internal ledger within the
human-selected residual tolerance.

## Audit gates

A clean financial audit requires:

1. verified Phase 75 reconciliation result, attestation, dispute pack and receipt;
2. verified Phase 77 close, attestation, audit pack and receipt when a variance
   required settlement;
3. one reconciliation record per provider invoice;
4. no settlement identifier applied more than once;
5. one currency per audit scope;
6. complete invoice-to-settlement coverage;
7. final residual variance within tolerance.

## Outputs

Phase 78 produces:

- financial audit snapshot;
- financial audit record;
- financial audit attestation;
- audit pack;
- audit-pack receipt.

JSON documents, ZIP entries and receipts are SHA-256 protected.

## Safety contract

The feature is evidence and decision support only. It never automatically:

- changes a ledger;
- changes an invoice;
- initiates a payment;
- applies a credit;
- changes a provider account;
- exports to an external accounting system;
- uploads financial evidence.

Human acknowledgement is required before an audit record is created.
