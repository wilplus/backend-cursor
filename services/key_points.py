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

──────────────────────────────────────────────────────────────────────────────
NOT WIRED (founder 2026-08-07). Nothing calls this. `_tracked_changes_block`
used to, behind KEY_POINTS_ENABLED, and that flag is gone with the call site.

WHY, since the module is not broken: a cue sheet highlights each block's
verbatim OPENING PHRASE — by contract, exactly as specified — and on screen a
highlighted opening phrase is indistinguishable from an intervention. It was
read as "the system marked this and will not say why". The founder's call was
to replace it with real interventions from the manager engine and defer the
cue sheet until the E-2 full↔key-words toggle gives it a surface of its own,
where a milestone reads as navigation rather than as feedback.

Kept, with its tests, because the deferral is about WHERE it renders, not
about whether the derivation is right. Re-wiring it is one call in
`_tracked_changes_block` — but it needs the toggle first.
──────────────────────────────────────────────────────────────────────────────
"""
from __future__ import annotations

import re
from typing import Any

# A milestone is a *cue*, not a sentence — cap it so "Key Words / Concept" mode
# stays scannable. Cut at the first SENTENCE/clause end (a comma is within a
# clause, so it is NOT a break), else the last word boundary within the cap.
_CUE_MAX_CHARS = 48
_CLAUSE_BREAK = re.compile(r"[.;:—–]")

# ── Paragraph fallback (founder 2026-07-27) ──────────────────────────────
# One milestone per BLOCK is correct by contract and useless on screen for a
# DECKLESS project: blocks are keyed on slide index, so a deckless talk is one
# block, so the whole "Key words" view rendered as a single card. Below two
# blocks we cue per PARAGRAPH instead — same verbatim slice, same offsets.
_MIN_BLOCKS = 2
# A stray line ("So.", a dangling clause) is not a milestone.
_MIN_PARA_CHARS = 24
# A 60-slide talk must not return a 60-item wall; the cue sheet is a scannable
# set of milestones, not an outline of everything.
_MAX_CUES = 12
_PARA_SPLIT = re.compile(r"\n[ \t]*\n")


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


def _paragraph_spans(served_text: str) -> list:
    """[(start, end)] of every paragraph of ``served_text``, offsets absolute.
    Split on a blank line; the separator itself belongs to no paragraph. Pure."""
    spans, pos = [], 0
    for m in _PARA_SPLIT.finditer(served_text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(served_text)))
    return spans


def _paragraph_cues(served_text: str) -> list:
    """One milestone per PARAGRAPH — the deckless fallback. Same
    ``_opening_clause`` cutter and the same absolute offsets as the block
    path, so a cue is a verbatim, correctly-anchored slice either way.

    A cue whose slice does not come back byte-identical is DROPPED, never
    served: a mis-anchored milestone underlines the wrong words, which is
    worse than one milestone fewer. Pure."""
    out = []
    for s, e in _paragraph_spans(served_text):
        chunk = served_text[s:e]
        if len(chunk.strip()) < _MIN_PARA_CHARS:
            continue
        lead = len(chunk) - len(chunk.lstrip())
        start = s + lead
        cue = _opening_clause(chunk[lead:])
        if not cue:
            continue
        end = start + len(cue)
        if served_text[start:end] != cue:
            continue
        out.append({
            "block_key": None, "block_label": None,
            "text": cue, "start": start, "end": end,
        })
        if len(out) >= _MAX_CUES:
            break
    return out


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
    usable text are skipped. Pure; safe on junk input.

    PARAGRAPH FALLBACK (founder 2026-07-27): blocks are keyed on slide index,
    so a DECKLESS project is ONE block, so this returned exactly one cue and
    the student's "Key words" view rendered as a single card. When the block
    path yields fewer than two milestones and the served text is available, we
    cue per PARAGRAPH instead — same verbatim slice, same offsets, capped at
    _MAX_CUES. ``block_key``/``block_label`` are None on those entries, so the
    FE must not key its rendering on them.

    Order is DOCUMENT order, always. Nothing here ranks, scores or sorts a
    milestone by importance (AC-9 / the construct fence): it chooses a
    boundary and slices verbatim (L1). No LLM in this module."""
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
    if _st is not None and len(out) < _MIN_BLOCKS:
        fallback = _paragraph_cues(_st)
        if len(fallback) > len(out):
            return fallback
    return out
