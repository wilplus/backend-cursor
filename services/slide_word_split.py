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

from typing import Any


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
