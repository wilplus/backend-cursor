"""Presentation-mode cue sheet — E-1 "progressive shortening" v1
(founder 2026-07-24).

As a speaker gets fluent they want the ideal text to compress from the full
script to a CUE SHEET: the key phrase + starting point of each section, so it
reads as milestones to navigate, not a wall to recite. This module derives
that cue sheet deterministically from the master-document pieces.

L1 (the hard fence): every milestone's ``text`` is a VERBATIM prefix of the
block's own served words — this module only chooses a boundary, it never
rewrites. No LLM here; pure and deterministic. The served offsets
(``start``/``end``) point into the same served document the full text uses, so
the FE locates each milestone the same way it locates a tracked change.

This is the SHORTER view of the SAME text, never a summary and never a new
claim. The full-vs-cue toggle is the FE's (E-2); the BE just serves both.
"""
from __future__ import annotations

import re
from typing import Any

# A milestone is a *cue*, not a sentence — cap it so "Key Words / Concept" mode
# stays scannable. Cut at the first SENTENCE/clause end (a comma is within a
# clause, so it is NOT a break), else the last word boundary within the cap.
_CUE_MAX_CHARS = 48
_CLAUSE_BREAK = re.compile(r"[.;:—–]")


def _opening_clause(body: str) -> str:
    """The verbatim opening phrase of ``body`` (already left-stripped): up to
    the first sentence/clause end, else a word boundary within _CUE_MAX_CHARS,
    else the whole thing. Trailing whitespace trimmed (offset-safe — it only
    shortens the end). Pure."""
    if not isinstance(body, str) or not body:
        return ""
    m = _CLAUSE_BREAK.search(body)
    cut = m.start() if m else len(body)
    if cut > _CUE_MAX_CHARS:
        window = body[:_CUE_MAX_CHARS]
        sp = window.rfind(" ")
        cut = sp if sp > 0 else _CUE_MAX_CHARS
    return body[:cut].rstrip()


def build_key_points(pieces: Any, served_text: Any = None) -> list:
    """The cue sheet: ONE starting-point milestone per master-document block,
    in document order. Each entry:

        {block_key, block_label, text, start, end}

    where ``text`` is the block's verbatim opening phrase and start/end anchor
    it in the served document (start points at the first non-space character,
    so the FE can scroll/underline exactly like a tracked change).

    When ``served_text`` is given, the block source is sliced straight from it
    (``served_text[start:end]``) — L1-exact against the very document the FE
    renders, so the milestone can never drift from the served words even if a
    piece's own ``text`` is a stale pre-relocation copy. Otherwise the piece's
    ``text`` is used (the pure/testable path). Pieces with no block or no
    usable text are skipped. Pure; safe on junk input."""
    if not isinstance(pieces, list):
        return []
    _st = served_text if isinstance(served_text, str) else None
    blocks: dict = {}
    order: list = []
    for p in pieces:
        if not isinstance(p, dict):
            continue
        bk = p.get("block_key")
        if bk not in blocks:
            blocks[bk] = []
            order.append(bk)
        blocks[bk].append(p)

    out: list = []
    for bk in order:
        first = sorted(blocks[bk], key=lambda p: p.get("start") or 0)[0]
        s0, e0 = first.get("start"), first.get("end")
        if _st is not None and isinstance(s0, int) and isinstance(e0, int) \
                and 0 <= s0 < e0 <= len(_st):
            raw, base = _st[s0:e0], s0        # L1-exact against served text
        else:
            raw = first.get("text")
            base = s0 if isinstance(s0, int) else 0
        if not isinstance(raw, str) or not raw.strip():
            continue
        lead = len(raw) - len(raw.lstrip())           # keep offsets exact
        start = base + lead
        cue = _opening_clause(raw[lead:])
        if not cue:
            continue
        out.append({
            "block_key": bk,
            "block_label": first.get("block_label"),
            "text": cue,
            "start": start,
            "end": start + len(cue),
        })
    return out
