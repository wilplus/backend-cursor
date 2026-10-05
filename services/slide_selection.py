"""The arc's spoken Takes, and the Take-count progress readers.

Renamed from ``services/best_presentation.py`` (audit Q-T4). Best
Presentation is retired (L1), and its builder is removed (founder 2026-10-05,
N48.3 Q13 A; contract 52): ``build_best_presentation``,
``_finalize_best_presentation``, the per-slide best-of selection
(``select_best_per_slide`` / ``select_best_deckless``), ``compose_presentation``
and the compose cache signature. The Ideal Text is the transcript of the Take
it is built from (services/ideal_text_block.assemble_transcript_document),
never a best-of pick across Takes. The ``best_presentation_cache`` table and
the edit tables stay (never auto-drop).

What stays:
  • spoken_arc_sessions — the arc's SPOKEN takes (reads excluded); live
    readers across the pipeline import it from here.
  • presentation_progress / TAKES_TARGET — the Take-count readiness reader.
  • _render_composition — reached by no live path. It stays only so the
    ``best_presentation`` prompt in services/prompts/prompts.lock.json keeps
    its golden eval (tests/evals/surfaces.py); removing it would mean
    removing a locked prompt, a separate change.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

TAKES_TARGET = 3


def spoken_arc_sessions(sessions: Any) -> list:
    """Only the SPOKEN takes of an arc (founder 2026-07-15 — reads are paired
    variants, coach-listening material): a read must never count toward the
    3-take readiness NOR compete as an ideal-text candidate. Rows without
    recording_kind (legacy / pre-migration) read as spoken. Pure."""
    return [
        s for s in (sessions or [])
        if isinstance(s, dict)
        and s.get("recording_kind") != "read"
        and not s.get("paired_session_id")
    ]


# ── Progress ────────────────────────────────────────────────────────────
def presentation_progress(takes_done: int) -> dict:
    td = takes_done if isinstance(takes_done, int) and takes_done >= 0 else 0
    return {
        "takes_done": td,
        "takes_target": TAKES_TARGET,
        # "we need N more takes to generate your best lines" (FE copy).
        "takes_remaining": max(0, TAKES_TARGET - td),
        "ready": td >= TAKES_TARGET,
    }


# ── Composition prompt (golden eval only) ───────────────────────────────
def _render_composition(picks_text: list, slides: list) -> Optional[dict]:
    """ONE constrained LLM pass. ``picks_text`` = [{slide_index, transcript}]
    (selected candidates, in slide order). Returns ``{slide_index: edited_text}`` or
    None on any failure (caller falls back to verbatim)."""
    if not picks_text:
        return {}
    try:
        import json as _json

        from services.llm import chat_complete
        from services.llm_config import SPEC_BEST_PRESENTATION
        # Prompt text lives in the registry (services/prompts/) — moved
        # verbatim 2026-08-03; hash-locked in prompts.lock.json.
        from services.prompts import best_presentation as _prompts
    except Exception as e:  # pragma: no cover - import guard
        from services.f1_observability import observe_f1_degrade
        observe_f1_degrade("polish_import_failed", exc=e)
        return None

    system = _prompts.system()
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
        from services.f1_observability import observe_f1_degrade
        observe_f1_degrade("polish_compose_failed", exc=e,
                           slides=len(picks_text))
        return None
    if not result:
        from services.f1_observability import observe_f1_degrade
        observe_f1_degrade("polish_empty_result", slides=len(picks_text))
        return None
    parsed = result.parsed
    if not isinstance(parsed, dict):
        try:
            parsed = _json.loads((result.text or "").strip())
        except Exception as e:
            from services.f1_observability import observe_f1_degrade
            observe_f1_degrade("polish_parse_failed", exc=e,
                               slides=len(picks_text))
            return None
    out = {}
    for row in (parsed.get("slides") if isinstance(parsed, dict) else []) or []:
        if isinstance(row, dict) and isinstance(row.get("slide_index"), int):
            t = str(row.get("text") or "").strip()
            if t:
                out[row["slide_index"]] = t
    return out
