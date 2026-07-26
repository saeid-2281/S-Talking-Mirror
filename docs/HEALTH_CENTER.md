# Health Center and Smart Summary

The Health Center gives one current snapshot of S Talking without requiring a
terminal. Open it from **Developer Tools → Health Center** or click the health
indicator in the status bar.

## Health score

The score combines the latest compile, test, and Ruff result with repository
status, diagnostics availability, report availability, and runtime readiness.
The score is intended as a quick development signal, not as a substitute for
reviewing failed checks.

- **Ready**: the latest checks passed and core artifacts are available.
- **Needs attention**: a check or recommended artifact is missing.
- **Action required**: the latest automated checks failed.

## Copying information

- **Copy summary** creates a short plain-text status suitable for chat or issue
  descriptions.
- **Copy for ChatGPT** creates a structured Markdown report containing project,
  queue, checks, Git status, report paths, diagnostics paths, and warnings.
- **Copy detailed output** in the Run All Checks window preserves the complete
  compiler, pytest, and Ruff output.

## Task Center

Task Center reads Markdown task files from `docs/tasks/`. It can display the
current goal and acceptance criteria, copy the Codex prompt, update task status,
and open the source task file. Supported statuses are Draft, Ready, In Progress,
Review, and Done.
