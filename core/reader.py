from __future__ import annotations

import html as htmllib
import io
import re
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".md", ".log", ".csv"}
SUPPORTED_SUFFIXES = TEXT_SUFFIXES | {".epub", ".pdf"}


def extract_text(data: bytes, suffix: str) -> str:
    suffix = suffix.lower()
    if suffix in TEXT_SUFFIXES:
        return data.decode("utf-8", errors="replace")
    if suffix == ".epub":
        return _extract_epub(data)
    if suffix == ".pdf":
        return _extract_pdf(data)
    raise ValueError(f"Unsupported file format: {suffix or '(none)'}. Supported: {sorted(SUPPORTED_SUFFIXES)}")


def extract_text_from_path(path: str | Path) -> str:
    path = Path(path)
    return extract_text(path.read_bytes(), path.suffix)


def _extract_epub(data: bytes) -> str:
    import ebooklib
    from ebooklib import epub

    book = epub.read_epub(io.BytesIO(data))
    parts = []
    for item in book.get_items_of_type(ebooklib.ITEM_DOCUMENT):
        raw = item.get_content().decode("utf-8", errors="replace")
        parts.append(_html_to_text(raw))
    return "\n".join(parts)


def _html_to_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?is)<!--.*?-->", " ", html)
    html = re.sub(r"(?s)<[^>]+>", " ", html)
    return htmllib.unescape(html)


def _extract_pdf(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages:
        pages.append(page.extract_text() or "")
    return "\n".join(pages)
