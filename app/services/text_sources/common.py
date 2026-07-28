from __future__ import annotations

import re


def decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "utf-16", "cp1252", "latin-1"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("The text file encoding could not be detected.")


def clean_text(value: str, *, trim_each_line: bool = False) -> str:
    """Normalize document text without destroying intentional indentation.

    Line endings and trailing horizontal whitespace are normalized for every
    reader.  Boundary *blank lines* are removed, but leading whitespace on the
    first content line is preserved unless ``trim_each_line`` is requested.
    This distinction is important for pasted text and Markdown/code content.
    """
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "")
    if trim_each_line:
        lines = [line.strip() for line in value.splitlines()]
    else:
        lines = [line.rstrip() for line in value.splitlines()]

    # Remove only empty boundary lines.  ``str.strip()`` is intentionally not
    # used because it would remove meaningful indentation from the first line.
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()

    value = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", value)
