# Troubleshooting

## CSV Shows Rejected Rows

Open the Import Review dialog, inspect issue codes, repair rejected rows, save `input.repaired.csv`, and switch the project CSV reference after confirmation.

## Health Center Looks Stale

Use Developer Tools > Run all checks or Developer Tools > Release readiness. Health reads authoritative `result.json` artifacts.

## Generation Stops Midway

Restart the app and reopen the project. Running jobs are recovered to Pending, and completed jobs are validated against existing output files.

## ElevenLabs Fails

Use Test connection. Invalid keys, quota issues, inaccessible voices, missing models, and network errors are normalized into user-facing messages.

## Piper Missing

Check that `piper` is on PATH and that the selected model file exists. Use Mock to verify the rest of the workflow while setting up Piper.

## Diagnostics

Export diagnostics from Developer Tools. API keys and token-like values are redacted.
