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

import logging
import re

logger = logging.getLogger(__name__)

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


# ── BE-S5 — coach-only LLM compatibility commentary (spoken-vs-slide) ──────
# AC-9: REFERENCE FOR THE COACH ONLY. Never attached to a user surface; the
# human coach reads it and writes the insight. Only the coach-gated
# /v2/coach/sessions/<id>/slide-alignment route calls compute_slide_compatibility.

_COMPAT_MODEL = "gpt-4o-mini"

_COMPAT_SYSTEM = (
    "You are a presentation-coaching analyst. You receive a speaker's slides "
    "(the title + body each slide CLAIMED) and the transcript of what they "
    "actually SAID while each slide was on screen. For EACH slide judge whether "
    "the spoken delivery COVERED/REINFORCED the slide's claim (covered=true) or "
    "drifted from / omitted it (covered=false), with one short, concrete, "
    "constructive comment (<=400 chars) a human coach can act on. Then one "
    "overall comment on slide-vs-speech alignment. This is REFERENCE FOR THE "
    "COACH ONLY: plain language, no scores, no grades. If a slide had no spoken "
    "text, mark covered=false and say it wasn't addressed."
)

_COMPAT_SCHEMA = {
    "name": "slide_compatibility",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["per_slide", "overall_comment"],
        "properties": {
            "per_slide": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["slide_index", "covered", "comment"],
                    "properties": {
                        "slide_index": {"type": "integer"},
                        "covered": {"type": "boolean"},
                        "comment": {"type": "string", "maxLength": 400},
                    },
                },
            },
            "overall_comment": {"type": "string", "maxLength": 600},
        },
    },
    "strict": True,
}


def build_compat_input(readout):
    """Pure: from a readout (slides + snippets each carrying `slide`), group the
    spoken transcript by the slide it was said under → the per-slide payload the
    LLM scores. Returns [] when there's no deck / no spoken mapping."""
    if not isinstance(readout, dict):
        return []
    slides = readout.get("slides")
    if not slides:
        return []
    spoken: dict = {}
    for s in (readout.get("snippets") or []):
        sl = s.get("slide") if isinstance(s, dict) else None
        if isinstance(sl, dict) and isinstance(sl.get("index"), int):
            spoken.setdefault(sl["index"], []).append((s.get("transcript") or "").strip())
    if not spoken:
        return []
    out = []
    for i, sl in enumerate(slides):
        if not isinstance(sl, dict):
            continue
        said = " ".join(t for t in spoken.get(i, []) if t).strip()
        out.append({
            "slide_index": i,
            "title": sl.get("title") or "",
            "body": sl.get("body") or "",
            "spoken_while_shown": said[:1500],
        })
    return out


def compute_slide_compatibility(session_id):
    """COACH-REFERENCE ONLY (AC-9). LLM read of spoken-vs-slide →
    {per_slide:[{slide_index, covered, comment}], overall_comment} or None
    (no deck / no spoken mapping / LLM unavailable). Best-effort; never raises."""
    try:
        from services.lab_recording import build_readout_from_session
        readout = build_readout_from_session(session_id)
    except Exception as e:
        logger.warning("slide_compat: readout failed sid=%s err=%s", session_id, e)
        return None
    payload_slides = build_compat_input(readout)
    if not payload_slides:
        return None
    try:
        import json as _json
        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not getattr(service, "client", None):
            return None
        resp = service.client.chat.completions.create(
            model=_COMPAT_MODEL,
            messages=[
                {"role": "system", "content": _COMPAT_SYSTEM},
                {"role": "user", "content": _json.dumps({"slides": payload_slides})},
            ],
            temperature=0.3,
            max_tokens=1200,
            response_format={"type": "json_schema", "json_schema": _COMPAT_SCHEMA},
        )
        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            return None
        data = _json.loads(raw)
    except Exception as e:
        logger.warning("slide_compat: llm failed sid=%s err=%s", session_id, e)
        return None
    per = []
    for it in (data.get("per_slide") or []):
        if isinstance(it, dict) and isinstance(it.get("slide_index"), int):
            per.append({
                "slide_index": it["slide_index"],
                "covered": bool(it.get("covered")),
                "comment": (it.get("comment") or "")[:400],
            })
    return {"per_slide": per, "overall_comment": (data.get("overall_comment") or "")[:600]}
