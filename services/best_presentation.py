"""Best-Presentation composition (willab Prompt D §4) — REPLACES the audit.

After the explore arc's 3 (optional 4th) takes, this assembles the user's
strongest version of the talk: for EACH slide, their best-rated CHALLENGE
delivery of that slide across takes, lightly stitched into continuous "ideal
presentation" text, with threat→challenge breakthrough markers.

Pieces:
  • select_best_per_slide — PURE: filter to challenge, rank with the combined
    power_score (challenge-threat terms ON), keep the best per slide.
  • compose_presentation — ONE constrained LLM pass that MOSTLY keeps the user's
    words and changes only a few per slide for continuity + slide-accuracy; on
    any failure it falls back to the snippet VERBATIM (the §9-safe degradation).
  • build_best_presentation — orchestration: pulls the arc's takes, resolves
    direction (coach blind label → shadow), detects breakthroughs per take,
    builds candidates, selects, composes, returns the payload.

FENCES (§0/§7): user sees ONLY challenge moments (threat informs ranking +
marks where the breakthrough started, never shown); the composed text is
grounded — no invented content, empty slide stays blank; scores are internal
(AC-9), never serialized.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

TAKES_TARGET = 3


# ── Selection (pure) ────────────────────────────────────────────────────
def select_best_per_slide(candidates: Any) -> dict:
    """candidates = list of per-snippet dicts: {slide_index, snippet_id,
    transcript, audio_ref, take_index, direction, breakthrough, activation,
    slide_stickiness, tag}. Returns ``{slide_index: winning_candidate}`` — the
    highest combined-score CHALLENGE snippet per slide (others dropped)."""
    from services.challenge_threat import is_challenge
    from services.power_phrase_ranking import power_score

    best: dict = {}
    for c in candidates if isinstance(candidates, list) else []:
        if not isinstance(c, dict):
            continue
        if not is_challenge(c.get("direction")):
            continue  # surfacing filter — challenge only
        si = c.get("slide_index")
        if not isinstance(si, int) or si < 0:
            continue
        score = power_score(
            activation=c.get("activation"),
            slide_stickiness=c.get("slide_stickiness"),
            tag=c.get("tag"),
            direction=c.get("direction"),
            breakthrough=bool(c.get("breakthrough")),
        )
        cur = best.get(si)
        if cur is None or score > cur["_score"]:
            best[si] = {**c, "_score": score}
    return best


# ── Composition (LLM, light edits, verbatim fallback) ───────────────────
def _render_composition(picks_text: list, slides: list) -> Optional[dict]:
    """ONE constrained LLM pass. ``picks_text`` = [{slide_index, transcript}]
    (challenge picks, in slide order). Returns ``{slide_index: edited_text}`` or
    None on any failure (caller falls back to verbatim)."""
    if not picks_text:
        return {}
    try:
        import json as _json

        from services.llm import chat_complete
        from services.llm_config import SPEC_BEST_PRESENTATION
        from services.will_voice import with_voice_rules
    except Exception as e:  # pragma: no cover - import guard
        logger.warning("best_presentation: llm import failed: %s", e)
        return None

    system = with_voice_rules("\n".join(f"- {r}" for r in [
        "You assemble a speaker's STRONGEST version of their talk from lines "
        "they actually said. For each slide you get the slide's title/body and "
        "the user's best spoken line for it.",
        "Return that line MOSTLY VERBATIM. You may change only a FEW words per "
        "slide — just enough for continuity with the neighbouring slides and "
        "accuracy to this slide's point.",
        "NEVER add new claims, facts, numbers, or sentences the user didn't say. "
        "Keep the user's voice. If a line is already clean, return it unchanged.",
        "Render in the SAME language the user spoke in.",
        'Output strict JSON: {"slides": [{"slide_index": int, "text": str}]} '
        "with one entry per input slide.",
    ]))
    payload = {
        "slides": [
            {
                "slide_index": p["slide_index"],
                "slide_title": (slides[p["slide_index"]].get("title")
                                if 0 <= p["slide_index"] < len(slides)
                                and isinstance(slides[p["slide_index"]], dict)
                                else ""),
                "slide_body": (slides[p["slide_index"]].get("body")
                               if 0 <= p["slide_index"] < len(slides)
                               and isinstance(slides[p["slide_index"]], dict)
                               else ""),
                "spoken_line": p["transcript"],
            }
            for p in picks_text
        ]
    }
    schema = {
        "name": "best_presentation",
        "schema": {
            "type": "object", "additionalProperties": False,
            "required": ["slides"],
            "properties": {"slides": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["slide_index", "text"],
                "properties": {
                    "slide_index": {"type": "integer"},
                    "text": {"type": "string", "maxLength": 1200},
                },
            }}},
        },
        "strict": True,
    }
    try:
        result = chat_complete(
            spec=SPEC_BEST_PRESENTATION, system=system,
            user=_json.dumps(payload, ensure_ascii=False),
            surface="best_presentation",
            response_format_override={"type": "json_schema", "json_schema": schema},
        )
    except Exception as e:
        logger.warning("best_presentation: compose call failed: %s", e)
        return None
    if not result:
        return None
    parsed = result.parsed
    if not isinstance(parsed, dict):
        try:
            parsed = _json.loads((result.text or "").strip())
        except Exception:
            return None
    out = {}
    for row in (parsed.get("slides") if isinstance(parsed, dict) else []) or []:
        if isinstance(row, dict) and isinstance(row.get("slide_index"), int):
            t = str(row.get("text") or "").strip()
            if t:
                out[row["slide_index"]] = t
    return out


def compose_presentation(picks: dict, slides: list) -> list:
    """``picks`` = {slide_index: winning_candidate}. Returns the per-slide
    payload list (slide order), each
    {index, title, text, audio_ref, take_index, breakthrough}. The text is the
    lightly-edited line, or the snippet VERBATIM if the LLM didn't return one.
    A slide with no challenge pick is included with empty text (never invented).
    """
    slides = slides if isinstance(slides, list) else []
    n = max([len(slides)] + [si + 1 for si in picks], default=0)

    picks_text = [
        {"slide_index": si, "transcript": picks[si].get("transcript") or ""}
        for si in sorted(picks)
        if (picks[si].get("transcript") or "").strip()
    ]
    edited = _render_composition(picks_text, slides) or {}

    out = []
    for i in range(n):
        slide = slides[i] if i < len(slides) and isinstance(slides[i], dict) else {}
        pick = picks.get(i)
        if pick:
            verbatim = pick.get("transcript") or ""
            out.append({
                "index": i,
                "title": slide.get("title") or "",
                "text": edited.get(i) or verbatim,  # light-edit, else verbatim
                "audio_ref": pick.get("audio_ref"),
                "take_index": pick.get("take_index"),
                "breakthrough": bool(pick.get("breakthrough")),
            })
        else:
            out.append({
                "index": i, "title": slide.get("title") or "",
                "text": "", "audio_ref": None,
                "take_index": None, "breakthrough": False,
            })
    return out


# ── Progress ────────────────────────────────────────────────────────────
def presentation_progress(takes_done: int) -> dict:
    td = takes_done if isinstance(takes_done, int) and takes_done >= 0 else 0
    return {
        "takes_done": td,
        "takes_target": TAKES_TARGET,
        "ready": td >= TAKES_TARGET,
    }


# ── Orchestration (DB + shadow model) ───────────────────────────────────
def _resolve_take_directions(snippets: list, coach_labels: dict) -> list:
    """Attach a resolved ``direction`` to each snippet (coach blind label →
    shadow prediction). Returns the snippets with a 'direction' key added."""
    from services.challenge_threat import resolve_direction
    try:
        from services.learning_serve import predict_direction
    except Exception:
        predict_direction = None  # type: ignore
    out = []
    for s in snippets or []:
        if not isinstance(s, dict):
            continue
        coach = coach_labels.get(str(s.get("id")))
        shadow = None
        if predict_direction and isinstance(s.get("metrics"), dict):
            try:
                pred = predict_direction(s.get("metrics"))
                shadow = (pred or {}).get("label")
            except Exception:
                shadow = None
        out.append({**s, "direction": resolve_direction(coach, shadow)})
    return out


def build_best_presentation(arc_id: Optional[str], *, database=None) -> dict:
    """Assemble the best-presentation payload for an arc. Best-effort; returns
    a progress-only payload (ready=False) when there's nothing to compose."""
    from services.slide_alignment import slide_index_for_offset
    db = database if database is not None else _default_db()

    sessions = db.get_arc_sessions(arc_id) if arc_id else []
    progress = presentation_progress(len(sessions))

    candidates = []
    canonical_slides: list = []
    for sess in sessions:
        sid = sess.get("id")
        ctx = sess.get("intake_context") if isinstance(sess.get("intake_context"), dict) else {}
        slides = ctx.get("slides") or []
        advances = ctx.get("slide_advances")
        if slides and len(slides) >= len(canonical_slides):
            canonical_slides = slides  # most-complete deck wins
        take_index = sess.get("take_index")
        snippets = db.get_snippets_by_session(sid) if sid else []
        coach_labels = {
            str(r.get("snippet_id")): r.get("value")
            for r in (db.get_training_labels(sid) or [])
        }
        directed = _resolve_take_directions(snippets, coach_labels)
        from services.challenge_threat import detect_breakthroughs
        breakthroughs = detect_breakthroughs([
            {"id": s.get("id"), "start_offset_ms": s.get("start_offset_ms"),
             "direction": s.get("direction")}
            for s in directed
        ])
        for s in directed:
            metrics = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
            stick = metrics.get("slide_stickiness")
            if isinstance(stick, dict):
                stick = stick.get("composite")
            candidates.append({
                "slide_index": slide_index_for_offset(s.get("start_offset_ms"), advances),
                "snippet_id": s.get("id"),
                "transcript": s.get("transcript") or s.get("transcript_excerpt") or "",
                "audio_ref": s.get("audio_ref") or s.get("storage_path"),
                "take_index": take_index,
                "direction": s.get("direction"),
                "breakthrough": s.get("id") in breakthroughs,
                "activation": metrics.get("overall_score"),
                "slide_stickiness": stick,
                "tag": None,  # coach 'strong'/'to_work_on' lives in drafts; not here
            })

    picks = select_best_per_slide(candidates)
    slides_payload = compose_presentation(picks, canonical_slides)
    return {
        "ready": progress["ready"],
        "progress": progress,
        "slides": slides_payload,
    }


def _default_db():
    from services.db import db as _db
    return _db
