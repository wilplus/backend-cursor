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
    """Per-page text from a PDF → one slide per page.

    Index-based iteration (NOT `for page in reader.pages`) — pypdf's _VirtualList
    is lazy and can bail silently mid-generator on a single malformed page,
    yielding fewer slides than the deck actually has (a 10-page deck coming back
    as 8). With explicit indexing, a bad page becomes one empty-slide + warning
    entry; the rest still come through.
    """
    try:
        from pypdf import PdfReader
    except ImportError as e:  # pragma: no cover
        raise DeckParseError(f"pdf parser unavailable: {e}")
    try:
        reader = PdfReader(BytesIO(file_bytes))
    except Exception as e:
        raise DeckParseError(f"could not open pdf: {e}")
    try:
        n_pages = len(reader.pages)
    except Exception as e:  # pragma: no cover - rare malformed root
        raise DeckParseError(f"could not count pdf pages: {e}")
    slides: list[dict] = []
    warnings: list[str] = []
    for i in range(n_pages):
        if len(slides) >= MAX_SLIDES:
            warnings.append(f"deck truncated to {MAX_SLIDES} slides")
            break
        # Isolate page access AND text extraction so neither can break the loop.
        try:
            page = reader.pages[i]
            text = (page.extract_text() or "").strip()
        except Exception as e:
            text = ""
            warnings.append(f"slide {i + 1}: extraction failed ({type(e).__name__})")
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        if not lines:
            slides.append({"title": "", "body": ""})
            warnings.append(f"slide {i + 1}: no extractable text (image-only?)")
            continue
        slides.append({
            "title": _clip(lines[0], _TITLE_CAP),
            "body": _clip("\n".join(lines[1:]), _BODY_CAP),
        })
    # Surface the PDF's real page count so any FE filter that drops empty slides
    # can spot a mismatch (e.g. 10 pages, 2 returned blank → FE knows 10 ≠ 8).
    if n_pages and len(slides) < n_pages:
        warnings.append(f"pdf has {n_pages} pages; returned {len(slides)} slides")
    return slides, warnings
