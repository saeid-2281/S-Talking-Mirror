# Text Studio v0.23

Text Studio replaces the basic text-source dialog with a reviewed document-to-audio workflow.

## Sources

- Manual and clipboard text
- TXT and Markdown
- RTF, DOCX, HTML and ODT
- EPUB using the standard library
- PDF when the optional `documents` dependency (`pypdf`) is installed

Scanned PDFs are intentionally not sent through silent OCR. They report that OCR is required.

## Planning

The studio supports whole-document, paragraph, sentence, line and smart chunk strategies. A maximum character size can be applied to any strategy. The review table allows individual jobs to be enabled or disabled before import.

## Estimates

Character totals and approximate duration use a configurable characters-per-minute rate. Cost remains provider-neutral: the user may enter an optional price per one million characters.

## Safety

The existing normalized CSV import pipeline remains authoritative. Text Studio does not generate audio directly and does not bypass source diagnostics, Preflight, persistence or provenance.
