"""willab beta — slide↔delivery alignment (UX Wave 4 Phase 2 / BE-S4).

Maps each snippet to the slide that was ON SCREEN when it was spoken, using the
user's tap timeline (slide_advances). Mechanical + deterministic:

  the slide for a snippet at time T = the advance with the greatest t_ms ≤ T
  (slide 0 is shown from t=0; back-navigation is real — a later advance can
  point at an earlier index, so ties resolve to the latest tap).

Falls back to best-match text overlap ONLY when there's no usable timeline
(e.g. a deck typed manually with no taps, or a legacy session). Never infers
slide-from-voice when timing exists.

Pure (stdlib only) — unit-tests without any deps.
"""
from __future__ import annotations

import re

_WORD = re.compile(r"[a-z0-9']+")


def slide_index_for_offset(start_offset_ms, slide_advances):
    """The on-screen slide index at start_offset_ms, or None when there's no
    usable timeline. Greatest t_ms ≤ offset wins; ties → the later tap."""
    if not slide_advances:
        return None
    t0 = start_offset_ms if isinstance(start_offset_ms, int) else 0
    chosen = None
    best_t = None
    for a in slide_advances:
        if not isinstance(a, dict):
            continue
        t = a.get("t_ms")
        idx = a.get("index")
        if not isinstance(t, int) or not isinstance(idx, int):
            continue
        # `t >= best_t` (not >) so a later equal-or-greater tap wins the tie,
        # honouring tap order = time order.
        if t <= t0 and (best_t is None or t >= best_t):
            best_t = t
            chosen = idx
    return chosen


def _tokens(text):
    return set(_WORD.findall((text or "").lower()))


def _best_match_index(transcript, slides):
    """Fallback: the slide whose title+body overlaps the transcript most.
    Returns None on no signal (so the caller omits `slide` rather than guess)."""
    toks = _tokens(transcript)
    if not toks or not slides:
        return None
    best_i, best_score = None, 0
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            continue
        overlap = len(toks & _tokens(f"{s.get('title', '')} {s.get('body', '')}"))
        if overlap > best_score:
            best_score = overlap
            best_i = i
    return best_i


def slide_for_snippet(snippet, slide_advances, slides):
    """Return {index, title, body} for the slide on screen during this snippet,
    or None. Timeline-first (exact); text-overlap fallback only when there's no
    usable timeline."""
    if not slides:
        return None
    idx = slide_index_for_offset(snippet.get("start_offset_ms"), slide_advances)
    if idx is None:
        idx = _best_match_index(snippet.get("transcript"), slides)
    if not isinstance(idx, int) or idx < 0 or idx >= len(slides):
        return None
    s = slides[idx]
    if not isinstance(s, dict):
        return None
    return {"index": idx, "title": s.get("title") or "", "body": s.get("body") or ""}
