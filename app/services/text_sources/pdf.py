from __future__ import annotations

from pathlib import Path

from app.services.text_sources.base import TextDocumentReader
from app.services.text_sources.common import clean_text
from app.services.text_sources.document_structure import DocumentSection


class PdfReader(TextDocumentReader):
    """Extract text from PDF files when the optional pypdf dependency exists."""

    extensions = frozenset({".pdf"})

    def read(self, path: Path) -> str:
        return clean_text("\n\n".join(section.text for section in self.read_sections(path)))

    def read_sections(self, path: Path) -> list[DocumentSection]:
        try:
            from pypdf import PdfReader as _PdfReader
        except ImportError as exc:
            raise ValueError(
                "PDF import requires the optional 'pypdf' package. "
                "Install the PDF extra before importing PDF documents."
            ) from exc

        try:
            reader = _PdfReader(str(path))
            pages = [clean_text(page.extract_text() or "") for page in reader.pages]
        except Exception as exc:  # pypdf exposes several parser-specific errors.
            raise ValueError("The PDF file could not be read or contains no extractable text.") from exc

        sections = [
            DocumentSection(str(index), f"Page {index}", text, Path(path), index)
            for index, text in enumerate(pages, 1)
            if text
        ]
        if not sections:
            raise ValueError(
                "The PDF contains no extractable text. Scanned PDFs require OCR before import."
            )
        return sections
