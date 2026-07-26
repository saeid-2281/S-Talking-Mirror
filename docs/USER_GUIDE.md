# S Talking User Guide

## Projects

Create or open projects from the Project menu. A project stores the CSV path, output folder, provider, queue state, and generation settings. The app can restore the last project on startup; disable restore by deleting `cache/session-restore.json` or changing `auto_restore_enabled` to `false`.

## CSV Import And Repair

Load a CSV with named `filename` and `text` columns. S Talking diagnoses encoding, delimiter, malformed rows, duplicate filenames, and filename/text drift before queue creation.

If `input.repaired.csv` exists beside `input.csv`, the app offers to use it as the project CSV source. The original CSV is not overwritten.

Rejected rows can be repaired inside the Import Review dialog. Save repaired output as `input.repaired.csv`, then choose whether to replace the project CSV reference and reload.

## Mock Testing

Use provider `mock` for local dry runs and WAV generation. Mock does not need an API key and is the safest way to test queue, stop/resume, reports, and audio playback.

## ElevenLabs

Select provider `elevenlabs`, enter the API key, then use Test connection. The app shows connection state, tier/quota when available, voice/model availability, and cached catalog status. API keys are redacted from diagnostics and reports.

## Piper

Install Piper and select a local `.onnx` model. S Talking validates whether Piper and the model are available before generation and reports setup issues clearly.

## Preflight

Dry run checks CSV, output paths, filename safety, provider readiness, quota warnings, and existing output behavior. Blocked preflight prevents generation. Warning-only preflight can start after confirmation.

## Queue Recovery

Interrupted Running jobs are recovered to Pending on startup. Completed jobs are kept only when their output files still exist; missing output resets the affected job to Pending.

## Reports And Diagnostics

Generation reports are written under `reports/<project>/<timestamp>/`. Diagnostics bundles are exported from Developer Tools and redact token-like values.

## Backup And Restore

Back up `.stproj` files, repaired CSVs, and the `data` database folder. Do not back up API keys into shared locations.
