"""FORCED ALIGNMENT of a new take onto the known script (founder
2026-08-03) — deterministic word→block bucketing, no LLM.

The premise: from take 2 onward the speaker is re-reading a text we
ALREADY HOLD — the master document they just reviewed (often edited,
sometimes verbatim re-read). Mapping their new take onto the skeleton by
PIECE COUNT (_proportional_split) ignores that; mapping by CONTENT is
exact where it matters:

  * a speaker who spends longer on one section no longer bleeds into
    the neighboring block (the count split's failure mode);
  * departures from the script stay WITH their block's contiguous
    segment (the whole-segment contract: an accept never silently drops
    unmapped sentences — review findings #4/#27);
  * a take that abandoned the script entirely is detected (low
    coverage) and the caller falls back to the proportional split —
    alignment never fabricates a mapping it cannot support.

MECHANICS — anchor-and-fill alignment over normalized word tokens:
difflib's C-level matching blocks provide the exact-run ANCHORS; the
noisy regions between anchors (ASR misrecognitions, small rewordings)
are aligned with a real Needleman–Wunsch pass, bounded per gap. Matched
script words then VOTE each take piece into a block; assignments are
clamped monotone (reading order is monotone by construction) and
unvoted pieces inherit their neighbor's block, so the per-block
segments partition the take contiguously — exactly the shape
segment_take_for_blocks promises.

Decked takes are untouched (slide-exact mapping is already
deterministic truth). Flag: TAKE_ALIGNMENT_ENABLED (default OFF) —
flag off, the deckless lane keeps the proportional split byte-for-byte.

L1/L2/AC-9: pure mapping — no text is written or altered, judging is
unchanged, nothing here rides a user payload. Pure functions; the one
env read is the flag.
"""
from __future__ import annotations

import difflib
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_WORD_RE = re.compile(r"[\w']+", re.UNICODE)

# Below this fraction of matched script words the take is OFF-SCRIPT —
# the mapping is refused and the caller falls back (never fabricate).
_MIN_COVERAGE = 0.35
# A near-match (ASR variant: "kubernetes"/"kubernetis") shares this
# prefix and length class.
_NEAR_PREFIX = 4
_NEAR_MIN_LEN = 5
# One gap's NW table is bounded — a bigger gap keeps only its anchors.
_GAP_CELL_CAP = 40000
_MATCH, _NEAR, _MISMATCH, _GAP = 2, 1, -1, -1


def alignment_enabled() -> bool:
    return (os.getenv("TAKE_ALIGNMENT_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _tokens(text: Any) -> list:
    """Normalized word tokens — lowercase, punctuation stripped. The
    comparison space for all alignment (never shown anywhere)."""
    if not isinstance(text, str):
        return []
    return [w.lower() for w in _WORD_RE.findall(text)]


def _near(a: str, b: str) -> bool:
    """ASR-variant tolerance: same first-_NEAR_PREFIX letters on words
    long enough that the prefix is signal, not chance."""
    return (len(a) >= _NEAR_MIN_LEN and len(b) >= _NEAR_MIN_LEN
            and a[:_NEAR_PREFIX] == b[:_NEAR_PREFIX])


def _nw_gap(a: list, b: list) -> list:
    """Needleman–Wunsch over two SHORT token runs (the noisy region
    between two exact anchors). Returns matched (i, j) pairs — exact or
    near matches only, in order. Bounded by _GAP_CELL_CAP; an oversized
    gap yields no pairs (its anchors still bound the mapping). Pure."""
    n, m = len(a), len(b)
    if not n or not m or n * m > _GAP_CELL_CAP:
        return []
    score = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0] = i * _GAP
    for j in range(1, m + 1):
        score[0][j] = j * _GAP
    for i in range(1, n + 1):
        ai = a[i - 1]
        row = score[i]
        prev = score[i - 1]
        for j in range(1, m + 1):
            bj = b[j - 1]
            s = _MATCH if ai == bj else (_NEAR if _near(ai, bj)
                                         else _MISMATCH)
            row[j] = max(prev[j - 1] + s, prev[j] + _GAP,
                         row[j - 1] + _GAP)
    pairs = []
    i, j = n, m
    while i > 0 and j > 0:
        ai, bj = a[i - 1], b[j - 1]
        s = _MATCH if ai == bj else (_NEAR if _near(ai, bj)
                                     else _MISMATCH)
        if score[i][j] == score[i - 1][j - 1] + s:
            if s > 0:
                pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif score[i][j] == score[i - 1][j] + _GAP:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    return pairs


def align_words(take_words: list, script_words: list) -> list:
    """All matched (take_idx, script_idx) pairs, strictly monotone:
    difflib equal-run anchors + per-gap Needleman–Wunsch fill. Pure."""
    if not take_words or not script_words:
        return []
    sm = difflib.SequenceMatcher(None, take_words, script_words,
                                 autojunk=False)
    blocks = [b for b in sm.get_matching_blocks() if b.size > 0]
    pairs: list = []
    prev_a = prev_b = 0
    for blk in blocks + [difflib.Match(len(take_words),
                                       len(script_words), 0)]:
        gap_a = take_words[prev_a:blk.a]
        gap_b = script_words[prev_b:blk.b]
        if gap_a and gap_b:
            pairs.extend((prev_a + i, prev_b + j)
                         for i, j in _nw_gap(gap_a, gap_b))
        pairs.extend((blk.a + k, blk.b + k) for k in range(blk.size))
        prev_a, prev_b = blk.a + blk.size, blk.b + blk.size
    return pairs


def map_take_to_blocks(new_pieces: list, blocks: list) -> tuple:
    """The alignment mapping: ({block_key: [pieces]}, info) — the same
    contract as the proportional split (contiguous partition of ALL
    pieces, block order), boundaries placed by CONTENT. (None, info)
    when the take is off-script (coverage < _MIN_COVERAGE) or there is
    nothing to align — the caller falls back. Pure.

    info carries internal diagnostics only ({coverage, off_script,
    unvoted_pieces}) — logged, never surfaced (AC-9-neutral but
    unsurfaced regardless)."""
    targets = sorted(
        (r for r in (blocks or [])
         if r.get("active", True) and r.get("status") != "candidate"),
        key=lambda r: r.get("block_key") or 0)
    info = {"coverage": 0.0, "off_script": True, "unvoted_pieces": 0}
    if not targets or not new_pieces:
        return (None, info)

    # The SCRIPT: block texts concatenated in key order, with each
    # block's word range remembered.
    script_words: list = []
    block_ranges: list = []          # (start, end, block_key)
    for r in targets:
        words = []
        for p in (r.get("incumbent_pieces") or []):
            words.extend(_tokens(p.get("text")))
        if not words:
            continue
        block_ranges.append((len(script_words),
                             len(script_words) + len(words),
                             r.get("block_key")))
        script_words.extend(words)
    if not script_words:
        return (None, info)

    # The TAKE: piece texts concatenated, with each piece's word range.
    take_words: list = []
    piece_ranges: list = []          # (start, end)
    for p in new_pieces:
        words = _tokens(p.get("text"))
        piece_ranges.append((len(take_words),
                             len(take_words) + len(words)))
        take_words.extend(words)
    if not take_words:
        return (None, info)

    pairs = align_words(take_words, script_words)
    coverage = len(pairs) / max(len(take_words), len(script_words))
    info["coverage"] = round(coverage, 3)
    if coverage < _MIN_COVERAGE:
        return (None, info)
    info["off_script"] = False

    # VOTE: each matched script word puts its block behind the take
    # piece it landed in. Majority per piece; ties → the earlier block
    # (reading order).
    def _block_of(script_idx: int) -> Optional[int]:
        for s, e, key in block_ranges:
            if s <= script_idx < e:
                return key
        return None

    order = {key: pos for pos, (_, _, key) in enumerate(block_ranges)}
    votes: list = [dict() for _ in new_pieces]
    pi = 0
    for t_idx, s_idx in pairs:
        while pi < len(piece_ranges) and t_idx >= piece_ranges[pi][1]:
            pi += 1
        if pi >= len(piece_ranges) or t_idx < piece_ranges[pi][0]:
            # matched word sits in no piece (empty-piece edge) — skip
            continue
        key = _block_of(s_idx)
        if key is not None:
            votes[pi][key] = votes[pi].get(key, 0) + 1

    assigned: list = []
    for v in votes:
        if not v:
            assigned.append(None)
            continue
        best = max(v.items(), key=lambda kv: (kv[1], -order[kv[0]]))
        assigned.append(best[0])
    info["unvoted_pieces"] = sum(1 for a in assigned if a is None)

    # MONOTONE CLAMP + FILL: reading order never goes backward, and
    # every piece belongs somewhere (an off-script sentence rides with
    # the block it was said inside — the whole-segment contract).
    prev_pos = None
    positions: list = []
    for a in assigned:
        pos = order.get(a) if a is not None else None
        if pos is None:
            positions.append(prev_pos)      # inherit (leading fixed below)
        else:
            pos = pos if prev_pos is None else max(pos, prev_pos)
            positions.append(pos)
            prev_pos = pos
    first = next((p for p in positions if p is not None), None)
    if first is None:
        return (None, info)
    positions = [first if p is None else p for p in positions]

    keys = [block_ranges[p][2] for p in positions]
    mapping: dict = {}
    for piece, key in zip(new_pieces, keys):
        mapping.setdefault(key, []).append(piece)
    return (mapping, info)
