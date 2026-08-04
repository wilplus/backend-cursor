"""Prompts for master-document skeleton chunking (founder 2026-07-22).

Moved verbatim from services/master_document.py (registry extraction
2026-08-03). L1 FENCE in this text: the LLM returns piece INDEX
boundaries and labels ONLY — never transcript text.
"""
from __future__ import annotations

CHUNKING_SYSTEM = (
    "You segment a spoken-talk transcript into logical blocks. "
    "You NEVER rewrite, summarise or quote the text — you only "
    "return piece INDEX boundaries and a short label per "
    "block. Blocks must be contiguous, cover every piece "
    "exactly once, and stay in order. Output strict JSON: "
    '{"blocks": [{"start": int, "end": int, "label": str}]}'
)

FRAME_SHORT = (
    "Use exactly these four blocks in order: Hook, Context, "
    "Core Message, Closer."
)

FRAME_LONG = (
    "Chunk by natural topic shifts; label each block with a "
    "2-4 word neutral topic label."
)


def chunking_user(frame: str, numbered: str) -> str:
    return f"{frame}\n\nPieces:\n{numbered}"


REGISTER = {
    "master_document_chunking.system": CHUNKING_SYSTEM,
    "master_document_chunking.frame_short": FRAME_SHORT,
    "master_document_chunking.frame_long": FRAME_LONG,
    "master_document_chunking.user": chunking_user,
}
