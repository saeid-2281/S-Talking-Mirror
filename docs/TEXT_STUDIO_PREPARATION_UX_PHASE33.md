# Text Studio, Source Preparation & Batch Editing UX — Phase 33

Phase 33 turns Text Studio into a preparation workspace instead of a simple chunk editor.

## Preparation checks

Enabled jobs are checked for empty text, invalid or duplicate filenames, duplicate text, oversized chunks and accidental whitespace. Blocking filename/text issues prevent queue import, while warnings remain reviewable.

## Batch tools

Operators can normalize whitespace, remove duplicate enabled text, renumber filenames and perform case-sensitive or case-insensitive find/replace over selected or all jobs. Enabled/disabled state is preserved across transformations.

## Review workflow

The quality card exposes enabled jobs, character totals, blocking issues and warnings. `Issues only` combines with the existing search field, and row tooltips explain each issue without adding another table column.

## Navigation

`Ctrl+7` opens and focuses Text Studio. It is also included in the F6 workspace cycle.

## Compatibility

The existing three-column chunk table, session format, import signal and public widget handles remain compatible. Database schema remains version 22.
