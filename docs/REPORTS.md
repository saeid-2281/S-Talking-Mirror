# Reports

Every generation run creates a report under:

```text
reports/<project-name>/YYYY-MM-DD_HH-MM-SS/
```

The report directory contains:

- `summary.json`: machine-readable run metadata, counts, runtime versions, and
  non-secret settings.
- `summary.md`: concise human-readable technical summary suitable for sharing
  during troubleshooting.
- `report.html`: self-contained browser report with summary cards and failed
  jobs.
- `generation.log`: log events for the run.
- `jobs.csv`: every queued job with status, retry count, duration, character
  count, error, and output path.
- `failed.csv`: failed jobs only.
- `skipped.csv`: skipped jobs only.
- `diagnostics.json`: sanitized runtime/package diagnostics.

API keys, authorization headers, tokens, passwords, and common secret patterns
are redacted before report and diagnostic export.

The generation result panel is non-modal, so the main app can still be used or
closed while a report window is open.

## Diagnostics Bundles

Use the Reports menu, Developer Tools menu, or `S-Talking-Diagnostics.cmd` to
export:

```text
artifacts/diagnostics/S-Talking-Diagnostics-<timestamp>.zip
```

The ZIP contains report files and sanitized application logs.
