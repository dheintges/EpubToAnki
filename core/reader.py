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
    """Extract text from an epub. Tries a direct OPF/spine parse first (works for
    epub2 and epub3, no NCX required, follows reading order, skips the nav page),
    then falls back to ebooklib."""
    errors = []
    try:
        return _extract_epub_manual(data)
    except Exception as exc:
        errors.append(f"manual parse: {exc}")
    try:
        return _extract_epub_ebooklib(data)
    except Exception as exc:
        errors.append(f"ebooklib: {exc}")
    raise ValueError(f"Could not parse epub ({'; '.join(errors)})")


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _extract_epub_manual(data: bytes) -> str:
    import urllib.parse
    import zipfile
    from xml.etree import ElementTree as ET

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        names = set(z.namelist())
        if "META-INF/container.xml" not in names:
            raise ValueError("not an epub zip (missing META-INF/container.xml)")
        container = ET.fromstring(z.read("META-INF/container.xml"))
        rootfile = next((el for el in container.iter() if _localname(el.tag) == "rootfile"), None)
        if rootfile is None:
            raise ValueError("container.xml has no rootfile")
        opf_path = rootfile.get("full-path")
        opf_dir = opf_path.rsplit("/", 1)[0] + "/" if "/" in opf_path else ""
        opf = ET.fromstring(z.read(opf_path))

        manifest = {}
        spine = []
        for el in opf.iter():
            name = _localname(el.tag)
            if name == "item" and el.get("id"):
                manifest[el.get("id")] = (el.get("href"), el.get("media-type") or "", el.get("properties") or "")
            elif name == "itemref":
                spine.append(el.get("idref"))
        if not spine:
            raise ValueError("opf has no spine")

        parts = []
        for idref in spine:
            item = manifest.get(idref)
            if not item:
                continue
            href, media_type, props = item
            if "nav" in props.split():
                continue
            if media_type not in ("application/xhtml+xml", "text/html"):
                continue
            path = urllib.parse.unquote(opf_dir + href)
            if path not in names:
                continue
            raw = z.read(path).decode("utf-8", errors="replace")
            parts.append(_html_to_text(raw))
        text = "\n".join(parts)
        if not text.strip():
            raise ValueError("spine contained no readable text")
        return text


def _extract_epub_ebooklib(data: bytes) -> str:
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
