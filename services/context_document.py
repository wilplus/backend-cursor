"""Context-document ingestion — X-1 (founder 2026-07-24).

A user uploads a supplementary document (a report, case metrics, Q&A) up to
~20 pages ALONGSIDE the deck; we extract its plain text and store it against
the arc so the assembly / feedback can reference the background.

L1 (the fence): this is BACKGROUND for the qualitative layer only — it must
NEVER become part of the verbatim ideal text. Its facts inform *feedback*
(why-lines, continuity), never new words served as the speaker's own. Parsing
is best-effort and never raises into the upload path.
"""
from __future__ import annotations

import logging
from io import BytesIO
from typing import Any

logger = logging.getLogger(__name__)

MAX_PAGES = 20
# ~20 dense pages of text; a hard cap keeps the downstream LLM budget bounded.
MAX_CHARS = 40000


def _looks_like_pdf(b: bytes, content_type: Any, filename: Any) -> bool:
    if isinstance(b, (bytes, bytearray)) and b[:5] == b"%PDF-":
        return True
    if content_type and "pdf" in str(content_type).lower():
        return True
    if filename and str(filename).lower().endswith(".pdf"):
        return True
    return False


def _pdf_text(b: bytes) -> tuple[str, int]:
    """(joined text over up to MAX_PAGES pages, TOTAL page count). Index-based
    + per-page isolation (a malformed page contributes nothing, never breaks
    the loop) — same hardening as services.deck_parser."""
    from pypdf import PdfReader        # lazy; ImportError → caller guards
    reader = PdfReader(BytesIO(b))
    n = len(reader.pages)
    parts: list = []
    for i in range(min(n, MAX_PAGES)):
        try:
            t = (reader.pages[i].extract_text() or "").strip()
        except Exception:
            t = ""
        if t:
            parts.append(t)
    return "\n\n".join(parts), n


def _looks_like_docx(b: bytes, content_type: Any, filename: Any) -> bool:
    """Extension / content-type first; the zip magic alone is NOT enough (a
    .pptx or .xlsx is also a zip), so the magic path additionally probes for
    the word/ part name inside the archive's early bytes."""
    if filename and str(filename).lower().endswith(".docx"):
        return True
    ct = str(content_type or "").lower()
    if "wordprocessingml" in ct or ct.endswith("/docx"):
        return True
    if isinstance(b, (bytes, bytearray)) and bytes(b[:4]) == b"PK\x03\x04":
        # The first local-file headers of a docx name its parts; word/ is the
        # document body's folder.
        return b"word/" in bytes(b[:4096])
    return False


def _docx_text(b: bytes) -> tuple[str, int]:
    """(joined paragraph text, 1). Same caps as PDF apply in the caller;
    python-docx (already in requirements for the strategy export) reads the
    zip in memory. A docx has no page count before layout, so pages is 1."""
    import docx                        # lazy; ImportError → caller guards
    document = docx.Document(BytesIO(b))
    parts: list = []
    for para in document.paragraphs:
        t = (para.text or "").strip()
        if t:
            parts.append(t)
    return "\n\n".join(parts), 1


def extract_context_text(file_bytes: Any, *, content_type: Any = None,
                         filename: Any = None) -> dict:
    """{text, pages, chars, truncated} — the extracted context, best-effort.

    PDF (magic/content-type/extension) → per-page text via pypdf, capped at
    MAX_PAGES; anything else → decoded as UTF-8 text/markdown. The text is
    capped at MAX_CHARS. Empty text on anything unparseable; NEVER raises."""
    out = {"text": "", "pages": 0, "chars": 0, "truncated": False}
    if not isinstance(file_bytes, (bytes, bytearray)) or not file_bytes:
        return out
    b = bytes(file_bytes)
    text, pages = "", 0
    try:
        if _looks_like_pdf(b, content_type, filename):
            try:
                text, pages = _pdf_text(b)
            except Exception as e:
                logger.warning("context_document: pdf parse failed: %s", e)
                return out
        elif _looks_like_docx(b, content_type, filename):
            # Added for the Life Panel setup upload (2026-07-30); shared here
            # because "extract plain text from an uploaded document, never
            # raise" is exactly this module's contract. Same caps as PDF.
            try:
                text, pages = _docx_text(b)
            except Exception as e:
                logger.warning("context_document: docx parse failed: %s", e)
                return out
        else:
            text = b.decode("utf-8", errors="replace")
            pages = 1
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("context_document: extract failed: %s", e)
        return out

    text = (text or "").strip()
    truncated = pages > MAX_PAGES
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rstrip()
        truncated = True
    return {"text": text, "pages": pages, "chars": len(text),
            "truncated": truncated}


# The upload allowlist for callers that gate on extension (the Life Panel
# setup upload). Kept next to the dispatcher so a new branch and its
# extension land in the same file.
SUPPORTED_UPLOAD_EXTENSIONS: tuple = (".pdf", ".docx", ".txt", ".md")


def extract_document_text(file_bytes: Any, *, content_type: Any = None,
                          filename: Any = None) -> dict:
    """Upload-facing name for the same dispatcher: PDF → pypdf, DOCX →
    python-docx, anything else → UTF-8 text/markdown. Same caps
    (MAX_PAGES / MAX_CHARS), same contract: best-effort, NEVER raises."""
    return extract_context_text(file_bytes, content_type=content_type,
                                filename=filename)
