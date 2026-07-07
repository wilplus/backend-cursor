"""Per-slide transcript sync via the slide-click timeline (founder #6).

The Lab take viewer shows the FULL verbatim transcript per slide. Until now a
snippet was assigned WHOLE to the slide that was on screen when it STARTED, so
words spoken AFTER a mid-snippet slide click stayed under the OLD slide. With
word-level Whisper timestamps we can do it precisely: every WORD is bucketed to
the slide that was on screen when that word was spoken, so a snippet spanning a
click is split — the post-click words move to the new slide.

Pure + dependency-light (only slide_alignment). When there is no usable click
timeline (no slide_advances) or no words, ``split_words_by_slides`` returns [] so
the caller falls back to the legacy whole-snippet assignment.

Whisper word timestamps are SECONDS, absolute to the whole recording — the same
reference frame as a snippet's start_offset_ms — so a word's slide is just
``slide_index_for_offset(word.start * 1000, slide_advances)``.
"""
from __future__ import annotations

import os
from typing import Any


# ── Pause-snap (clock-offset robustness, flag-gated default OFF) ──────────
# The recorder warm-up makes Whisper word-times run slightly EARLIER than the
# UI tap-times, so the first word(s) after a slide tap can land on the PREVIOUS
# slide. When the speaker pauses as they tap (the common case), that offset sits
# inside the silence — so snapping each boundary into the nearest real speech
# pause recovers the true boundary WITHOUT knowing the offset and WITHOUT any
# capture change. Ships dark; flip SLIDE_PAUSE_SNAP_ENABLED=1 after observing a
# leak; instant rollback by flipping it off.

def _pause_snap_enabled() -> bool:
    return (os.getenv("SLIDE_PAUSE_SNAP_ENABLED") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _snap_boundaries_to_pauses(slide_advances: Any, words: Any, *,
                               window_ms: int, min_gap_ms: int) -> list:
    """Move each slide-change boundary to the NEAREST real speech pause within
    ``window_ms``, so a small audio-vs-UI clock offset lands in the silence the
    speaker leaves when they tap NEXT/BACK. Pure. Returns slide_advances
    unchanged (same ``{index, t_ms}`` shape) when there's no qualifying pause
    near a tap (speaker talked straight through) or when inputs are empty. Never
    reorders or collapses adjacent boundaries (clamps each snap strictly between
    the previous SNAPPED boundary and the next RAW boundary); the index of every
    entry is preserved; the first entry at t_ms<=0 (recording start) is never
    moved."""
    if not slide_advances or not words:
        return slide_advances

    # 1) Real pauses → snap-points (gap midpoints, ms). Only gaps bigger than
    #    normal speech rhythm count (a deliberate pause, not a breath).
    ws = sorted(
        (w for w in words if isinstance(w, dict)
         and isinstance(w.get("start"), (int, float))),
        key=lambda w: w.get("start") or 0.0,
    )
    gaps: list = []
    for i in range(len(ws) - 1):
        pe = ws[i].get("end")
        pe = float(pe) if isinstance(pe, (int, float)) else float(ws[i].get("start") or 0.0)
        ns = float(ws[i + 1].get("start") or 0.0)
        if (ns - pe) * 1000.0 >= min_gap_ms:
            gaps.append((pe + ns) / 2.0 * 1000.0)
    if not gaps:
        return slide_advances

    # 2) Boundaries in time order (t_ms is monotonic even with BACK nav).
    idxs = [i for i, a in enumerate(slide_advances)
            if isinstance(a, dict) and isinstance(a.get("t_ms"), (int, float))]
    idxs.sort(key=lambda i: slide_advances[i]["t_ms"])

    snapped: dict = {i: slide_advances[i]["t_ms"] for i in idxs}
    prev_snapped = None
    for pos, i in enumerate(idxs):
        t = slide_advances[i]["t_ms"]
        if t <= 0:                       # recording start — never snap
            prev_snapped = snapped[i]
            continue
        lo = prev_snapped if prev_snapped is not None else float("-inf")
        nxt = idxs[pos + 1] if pos + 1 < len(idxs) else None
        hi = slide_advances[nxt]["t_ms"] if nxt is not None else float("inf")
        best = None
        best_d = None
        for g in gaps:
            if g <= lo or g >= hi or abs(g - t) > window_ms:
                continue
            d = abs(g - t)
            if best_d is None or d < best_d:
                best, best_d = g, d
        snapped[i] = int(round(best)) if best is not None else t
        prev_snapped = snapped[i]

    # 3) Rebuild preserving original order + index; only t_ms changes.
    return [
        ({**a, "t_ms": snapped[i]} if (i in snapped and isinstance(a, dict)) else a)
        for i, a in enumerate(slide_advances)
    ]


def slice_words_for_window(words: Any, start_ms: int, end_ms: int) -> list:
    """The word-level analogue of slice_transcript_for_window: the words whose
    time span overlaps [start_ms, end_ms]. ``words`` = [{word, start, end}] in
    SECONDS (Whisper verbose_json). Pure; None-safe. Used to park each selected
    snippet's words at process time so the take viewer can split later."""
    if not words:
        return []
    s = start_ms / 1000.0
    e = end_ms / 1000.0
    out: list = []
    for w in words:
        if not isinstance(w, dict):
            continue
        ws = w.get("start")
        if not isinstance(ws, (int, float)):
            continue
        we = w.get("end")
        we = we if isinstance(we, (int, float)) else ws
        # Overlap test (same as the segment slicer): end after window start AND
        # start before window end.
        if we > s and ws < e:
            out.append({"word": w.get("word") or "", "start": ws, "end": we})
    return out


def split_words_by_slides(words: Any, slide_advances: Any, slides: Any) -> list:
    """Group a snippet's words into per-slide fragments by the click timeline.

    Returns an ordered list of
    ``{slide_index, transcript, start_offset_ms, duration_ms}`` — one entry per
    run of consecutive words that share a slide. A snippet whose words straddle a
    slide click yields TWO+ fragments (the split #6 is about).

    Returns ``[]`` when there is no usable timeline (no slide_advances) or no
    words/slides — the signal for the caller to fall back to the legacy
    whole-snippet assignment (which can't split, so it keeps everything on the
    start slide). A word before the first advance is clamped to the first slide;
    indices are clamped into range.
    """
    n = len(slides) if isinstance(slides, list) else 0
    if not words or n == 0 or not slide_advances:
        return []

    from services.slide_alignment import slide_index_for_offset

    ordered = sorted(
        (w for w in words if isinstance(w, dict)
         and isinstance(w.get("start"), (int, float))),
        key=lambda w: w.get("start") or 0.0,
    )

    groups: list = []
    cur: dict | None = None
    for w in ordered:
        token = (w.get("word") or "").strip()
        if not token:
            continue
        st = float(w.get("start") or 0.0)
        en = w.get("end")
        en = float(en) if isinstance(en, (int, float)) else st
        start_ms = int(st * 1000)
        end_ms = int(en * 1000)
        si = slide_index_for_offset(start_ms, slide_advances)
        si = 0 if not isinstance(si, int) else max(0, min(si, n - 1))
        if cur is None or cur["slide_index"] != si:
            if cur is not None:
                groups.append(cur)
            cur = {
                "slide_index": si, "tokens": [token],
                "start_offset_ms": start_ms, "end_ms": end_ms,
            }
        else:
            cur["tokens"].append(token)
            cur["end_ms"] = max(cur["end_ms"], end_ms)
    if cur is not None:
        groups.append(cur)

    return [
        {
            "slide_index": g["slide_index"],
            "transcript": " ".join(g["tokens"]).strip(),
            "start_offset_ms": g["start_offset_ms"],
            "duration_ms": max(0, g["end_ms"] - g["start_offset_ms"]),
        }
        for g in groups
    ]


def build_slide_transcripts(words_all: Any, slide_advances: Any,
                            slides: Any) -> list:
    """The COMPLETE per-slide transcript for the take viewer (founder Part A —
    "text under the slide = exactly 1:1 of what was said while that slide was on
    screen"). Unlike the per-snippet split, this buckets the WHOLE-recording word
    list so a slide whose speech wasn't in a salient snippet (typically the quiet
    first slide) still gets its words — fixing "the app doesn't catch the first
    slide / everything is shifted".

    Returns one entry PER DECK SLIDE (index 0..n-1, in order) —
    ``{index, transcript, start_offset_ms, duration_ms}`` — even when a slide had
    no speech (empty transcript is the truthful 1:1). Every word is bucketed to
    the slide on screen at its timestamp; a word before the first advance clamps
    to slide 0; a revisited slide collects all its words in time order. The span
    is [min word start, max word end] for that slide. Returns [] when there are
    no slides. Pure.
    """
    n = len(slides) if isinstance(slides, list) else 0
    if n == 0:
        return []

    # Pause-snap (flag-gated, default OFF) — absorb the recorder warm-up offset
    # by moving each slide boundary into the speaker's pause. No-op when off, or
    # when no qualifying pause is near a tap. Byte-identical to before when off.
    if words_all and slide_advances and _pause_snap_enabled():
        slide_advances = _snap_boundaries_to_pauses(
            slide_advances, words_all,
            window_ms=_env_int("SLIDE_PAUSE_SNAP_WINDOW_MS", 1200),
            min_gap_ms=_env_int("SLIDE_PAUSE_SNAP_MIN_GAP_MS", 200),
        )

    buckets: dict = {i: [] for i in range(n)}  # i -> [(start_ms, end_ms, token)]
    if words_all and slide_advances:
        from services.slide_alignment import slide_index_for_offset
        for w in words_all:
            if not isinstance(w, dict):
                continue
            st = w.get("start")
            if not isinstance(st, (int, float)):
                continue
            token = (w.get("word") or "").strip()
            if not token:
                continue
            en = w.get("end")
            en = float(en) if isinstance(en, (int, float)) else float(st)
            start_ms = int(float(st) * 1000)
            end_ms = int(en * 1000)
            si = slide_index_for_offset(start_ms, slide_advances)
            si = 0 if not isinstance(si, int) else max(0, min(si, n - 1))
            buckets[si].append((start_ms, end_ms, token))

    out: list = []
    for i in range(n):
        ws = sorted(buckets[i], key=lambda t: t[0])
        transcript = " ".join(t[2] for t in ws).strip()
        if ws:
            start_ms = ws[0][0]
            end_ms = max(t[1] for t in ws)
            duration_ms = max(0, end_ms - start_ms)
        else:
            start_ms = None
            duration_ms = None
        out.append({
            "index": i,
            "transcript": transcript,
            "start_offset_ms": start_ms,
            "duration_ms": duration_ms,
        })
    return out


# ── Deckless chunking (founder 2026-07-07) ─────────────────────────────────
# No deck → no click timeline to bucket by, so the whole-recording transcript
# (already persisted as a single slide_transcripts entry, see
# lab_recording.build_readout_from_session's DECKLESS fold) is exposed as one
# unbroken string today. Split it into fixed-size word chunks so the FE can
# lay it out as readable stacked paragraphs under one artificial "slide"
# (no next/prev — there's nothing to page between) instead of one wall of
# text. Word-count, not time — there's no tap timeline to chop by.

_DECKLESS_CHUNK_WORDS = 50


def chunk_transcript_by_words(text: Any, chunk_size: int = _DECKLESS_CHUNK_WORDS) -> list:
    """Split a flat transcript string into ~chunk_size-word groups, in order.

    Returns ``[{index, transcript}, ...]``; ``[]`` for blank/whitespace-only
    input. Pure.
    """
    words = (text or "").split()
    if not words:
        return []
    size = chunk_size if isinstance(chunk_size, int) and chunk_size > 0 else _DECKLESS_CHUNK_WORDS
    return [
        {"index": i // size, "transcript": " ".join(words[i:i + size])}
        for i in range(0, len(words), size)
    ]
