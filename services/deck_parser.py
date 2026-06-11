"""willab beta — slide-deck parser (UX Wave 4 §S) — PDF-only.

A deck is uploaded as PDF; we extract per-slide {title, body} text (first line
→ title, rest → body, best-effort with warnings) and serve the PDF itself (the
FE renders pages with PDF.js).

PowerPoint is NOT converted server-side — users export to PDF. The PPTX→PDF
path needed headless LibreOffice, which did not provision reliably on the
platform (apt didn't land `soffice`; the Nix package was too heavy a build), so
it was dropped to keep the build lean and the feature reliable. `.pptx` uploads
return a clear "export to PDF" message.

pypdf is lazy-imported so the route layer imports this module without it.
"""
from __future__ import annotations

import logging
import os
from io import BytesIO

logger = logging.getLogger(__name__)

MAX_SLIDES = 60
_TITLE_CAP = 200
_BODY_CAP = 2000

SUPPORTED_EXTS = (".pdf",)


class DeckParseError(Exception):
    """Unsupported type / unparseable file. The route maps it to 415/422."""


def _ext(filename: str) -> str:
    return (os.path.splitext(filename or "")[1] or "").lower()


def _clip(s, n: int) -> str:
    return (s or "").strip()[:n]


def extract_deck(file_bytes: bytes, filename: str) -> dict:
    """→ {slides: [{title, body}], source: "pdf", warnings: [str],
         pdf_bytes: bytes}. Raises DeckParseError on non-PDF / unparseable."""
    ext = _ext(filename)
    if ext == ".pptx":
        raise DeckParseError(
            "PowerPoint isn't supported yet — export your slides to PDF and "
            "upload the PDF."
        )
    if ext != ".pdf":
        raise DeckParseError(f"unsupported file type: {ext or 'unknown'}")
    slides, warnings = _extract_pdf_text(file_bytes)
    return {"slides": slides, "source": "pdf", "warnings": warnings,
            "pdf_bytes": file_bytes}


def _extract_pdf_text(file_bytes: bytes):
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise DeckParseError(f"pdf parser unavailable: {e}")
    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception as e:
        raise DeckParseError(f"could not open pdf: {e}")
    slides: list[dict] = []
    warnings: list[str] = []
    for i, page in enumerate(reader.pages):
        if len(slides) >= MAX_SLIDES:
            warnings.append(f"deck truncated to {MAX_SLIDES} slides")
            break
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            slides.append({"title": "", "body": ""})
            warnings.append(f"slide {i + 1}: no extractable text (image-only?)")
            continue
        slides.append({
            "title": _clip(lines[0], _TITLE_CAP),
            "body": _clip("\n".join(lines[1:]), _BODY_CAP),
        })
    return slides, warnings
