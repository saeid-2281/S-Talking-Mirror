# Text Source Readers — v0.20 Phase B

Text document parsing is now separated from `TextSourceService`.

## Architecture

- `TextSourceService`: orchestration, splitting, filenames and normalized CSV output.
- `TextReaderFactory`: extension-to-reader dispatch.
- `PlainTextReader`: TXT and TEXT.
- `MarkdownReader`: MD and MARKDOWN.
- `RtfReader`: RTF control words, paragraphs, tabs, hexadecimal escapes and Unicode escapes.
- `DocxReader`: WordprocessingML extraction from DOCX.
- `HtmlReader`: visible HTML text while excluding scripts and styles.
- `OdtReader`: paragraph and heading extraction from OpenDocument Text.
- `ClipboardReader`: manual/pasted text normalization.

## Supported document extensions

`.txt`, `.text`, `.md`, `.markdown`, `.rtf`, `.docx`, `.html`, `.htm`, `.odt`

CSV and Excel remain in the existing structured-source importer because they require explicit column and worksheet mapping. PDF and EPUB are intentionally not accepted yet; they require separate extraction and review rules rather than silently guessing document structure.

## RTF normalization

The RTF reader normalizes `\\par`, `\\pard`, `\\line`, `\\tab`, hexadecimal escapes and `\\uN` Unicode escapes. Leading whitespace introduced by RTF paragraph control words is removed per line, fixing outputs such as `First\n Second`.

## Compatibility

`app.services.text_source_service.TextSourceService` remains the public facade, so existing GUI and project-import code does not need to change.
