from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path

from app.services.text_sources.base import TextDocumentReader
from app.services.text_sources.common import clean_text, decode_text

_BLOCK_TAGS = {
    "article", "aside", "blockquote", "br", "div", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
    "header", "li", "main", "nav", "p", "section", "table", "tr",
}
_IGNORED_TAGS = {"script", "style", "noscript", "svg"}


class _PlainHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:  # noqa: ANN001
        del attrs
        tag = tag.lower()
        if tag in _IGNORED_TAGS:
            self._ignored_depth += 1
        elif self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
        elif self._ignored_depth == 0 and tag in _BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self.parts.append(data)


class HtmlReader(TextDocumentReader):
    extensions = frozenset({".html", ".htm"})

    def read(self, path: Path) -> str:
        parser = _PlainHtmlParser()
        parser.feed(decode_text(path.read_bytes()))
        parser.close()
        return clean_text("".join(parser.parts), trim_each_line=True)
