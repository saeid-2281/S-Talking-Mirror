# Text Sources — v0.20

S Talking can now create normal queue jobs from pasted text and common text documents.

## Entry points

- **Project → Add text source…**
- Keyboard shortcut: **Ctrl+Shift+T**
- **Enter text** in the empty-project workspace

## Supported input

- Manual typed or pasted text
- `.txt`
- `.md` / `.markdown`
- `.rtf`
- `.docx`

## Splitting

A source can become one audio file or be split by paragraph, non-empty line, or sentence. The dialog previews generated filenames, row counts and total characters before import.

## Architecture

Text inputs are converted to a normalized UTF-8 CSV snapshot under the runtime data directory and then passed through the existing source-import pipeline. This preserves diagnostics, project persistence, source provenance, Preflight, queue ordering and reporting without maintaining a parallel generation path.
