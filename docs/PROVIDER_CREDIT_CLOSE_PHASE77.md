# Phase 77 — Provider Credit Ledger Close & Financial Control

Phase 77 closes the financial-control loop created by the provider billing workflow.

It consumes verified Phase 76 settlement evidence and creates a privacy-safe,
tamper-evident accounting-period close record. The feature is evidence and
decision support only; it does not mutate invoices, ledgers, payments, credit
memos or provider accounts.

## Inputs

Each settlement source requires a matching Phase 76:

- settlement record;
- settlement attestation;
- closure pack;
- closure receipt.

The accounting period must use `YYYY-MM`. A close scope must contain one
currency only.

## Close gates

A clean close requires:

1. all selected source evidence to verify;
2. unique settlement identifiers;
3. a valid accounting period;
4. a single currency;
5. every dispute to have `outcome_status=settled`;
6. zero remaining settlement variance;
7. complete reviewed credit recovery;
8. independent human verification of the ledger export.

## Outputs

Phase 77 produces:

- provider credit close snapshot;
- provider credit close record;
- close attestation;
- audit pack;
- audit-pack receipt.

Every JSON document and ZIP manifest is SHA-256 protected. The audit receipt
also binds the ZIP filename, size and SHA-256.

## Safety contract

The Phase 77 evidence explicitly records that these operations are never
automatic:

- ledger change;
- invoice change;
- payment action;
- provider action;
- credit memo action;
- external accounting action;
- evidence upload.

Human acknowledgement is required before a close record is created.
