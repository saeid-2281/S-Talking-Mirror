# Dialog & Settings UX — Phase 28

Phase 28 standardizes the application's most frequently used setup and review dialogs around a shared professional workspace.

## Shared dialog workspace

`DialogWorkspace` provides:

- a consistent title and supporting description;
- a vertically scrollable content area;
- a sticky action footer that remains visible at short window heights;
- reusable `DialogSection` cards for forms and tables;
- semantic `DialogStatusCard` summaries.

The shell intentionally avoids resize event filters, widget reparenting during paint/layout events, and breakpoint loops. This keeps it safe for PySide6 on Windows and compatible with high DPI and text scaling.

## Updated dialogs

### Interface & Accessibility

- settings and preview now scroll independently;
- Save, Cancel and Restore defaults stay pinned;
- long form rows wrap rather than clipping;
- minimum window size supports laptop displays.

### Quick Setup

- guided six-step workflow with progress indicator;
- persistent step rail and clear active/completed states;
- provider capability summary;
- pinned Back, Next, Finish and Cancel controls.

### New Project

- professional project-details form;
- clearer optional source and required output fields;
- visible validation state;
- Create Project stays pinned and disables when required data is missing.

### Source Import Review

- detailed mappings use horizontal scrolling instead of clipping;
- selected-source tools use a two-column grid;
- Import selected, Import all valid and Cancel stay pinned;
- source mapping uses the same scroll-safe form shell.

### Preflight

- readiness summary uses semantic status presentation;
- issues remain in a readable table;
- secondary tools are placed in the scrollable body;
- Start and Cancel stay pinned;
- filename-fix preview uses the same workspace.

## Compatibility

Public widget handles used by controllers and tests are preserved, including `provider`, `model`, `voice`, `language`, `stack`, `back`, `next`, `skip`, `finish`, `name`, `csv`, `output`, `summary`, `table`, `start_button`, `cancel_button`, `fix_button`, `override_button`, `export_button`, `copy_button`, and `open_output_button`.
