# Roadmap 2 B5 — Intelligent TTS Artifact Provenance & Output Integrity

## Certified baseline

B5 starts from B4 + Hotfix 2 commit:

`02246f2d521512d73b3abc2759f84db7086abe6f`

B1 manifests, B2 execution bindings, B3 run ledgers, B4 recovery lineage and the B4 Dark Theme hierarchy are frozen inputs.

## Purpose

B5 closes the remaining evidence gap between an approved request and the audio file that exists after Generation. Before Generation starts, an immutable artifact plan is persisted from the exact B2 binding. After the existing execution receipt is produced, B5 creates a privacy-safe artifact receipt.

For every B1 request it records request id, source row, filename/output path, source-text SHA-256, final job status, whether the output exists, output byte size and output SHA-256. Raw source text and credentials are never persisted.

## Integrity signals

B5 is observational only. It surfaces `missing_completed_output`, `empty_output`, `duplicate_planned_output`, `existing_output_for_noncompleted_job`, `nonterminal_status_after_completed_run`, `output_unreadable` and `unsafe_output_path`. Files outside the approved B2 output root are never opened or hashed.

B5 never deletes, renames, moves, repairs or regenerates an output. It does not retry a job or choose another provider.

## Evidence chain

The chain becomes:

`B1 Manifest → B2 Binding → B3/B4 Run Ledger → B5 Artifact Plan/Receipt → Execution Receipt/Report`

The B3/B4 final ledger event is extended with `artifact_receipt_path`, preserving one auditable chain from approved request identity through recovery lineage to final artifact evidence.

## Authority freeze

No automatic provider/account/voice/model/language switching, content language detection, Preflight, Generation start/restart, Smart Routing, retry, recovery or cross-provider failover is introduced. Database schema 23 is unchanged.

## Evidence location

Live plans and receipts: `<reports_dir>/intelligent-tts-artifacts/<project>/`. Machine certification: `artifacts/intelligent-tts-production/roadmap2-b5/`.

## Exit criteria

14 service tests, 8 integration tests, 15/15 machine certification, B1-B4 regressions, generation receipt/resume/budget regressions, visual/theme guards, Track A authority regression, QProcess regression and one Full Quality Gate.

Next: **Roadmap 2 B6**.
