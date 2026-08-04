"""Surface adapters — golden-case input → the real production function.

One adapter per eval-gated surface, keyed by the surface name (the
prefix of its prompt ids in prompts.lock.json AND the golden dataset
filename). Adapters call PRODUCTION code, never a re-implementation —
the whole point is that the shipped prompt + guards get graded.

Adapters must be read-only: no DB writes (call the pure/testable core,
not the dispatch/persist wrappers).
"""
from __future__ import annotations

import os
import sys
from typing import Any, Callable

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _say_it_stronger(inp: dict) -> Any:
    from services.say_it_stronger import generate_say_it_stronger
    return generate_say_it_stronger(
        inp.get("transcript") or "",
        inp.get("metrics"),
        inp.get("session_means"),
        inp.get("context"),
    )


def _best_presentation(inp: dict) -> Any:
    from services.best_presentation import _render_composition
    out = _render_composition(inp.get("picks") or [], inp.get("slides") or [])
    if out is None:
        return None
    return {str(k): v for k, v in out.items()}


def _slide_claims(inp: dict) -> Any:
    from services.slide_alignment import _llm_decompose
    slides = {int(k): v for k, v in (inp.get("slides") or {}).items()}
    out = _llm_decompose(slides)
    if out is None:
        return None
    return {str(k): v for k, v in out.items()}


def _slide_entailment(inp: dict) -> Any:
    from services.slide_alignment import _entail_batch
    return _entail_batch(inp.get("work") or [])


def _coach_comment_draft(inp: dict) -> Any:
    from services.coach_comment_drafter import generate_coach_note_draft
    return generate_coach_note_draft(
        inp.get("transcript") or "",
        inp.get("slide"),
        inp.get("metrics"),
        take_comparison=inp.get("take_comparison"),
        goal=inp.get("goal"),
    )


def _moment_suggestion(inp: dict) -> Any:
    from services.moment_suggestions import generate_moment_suggestion
    return generate_moment_suggestion(
        inp.get("kind") or "",
        inp.get("transcript") or "",
        audience=inp.get("audience"),
        strategic_context=inp.get("strategic_context"),
        context_document=inp.get("context_document"),
        trigger=inp.get("trigger"),
    )


def _structural_star(inp: dict) -> Any:
    from services.moment_suggestions import detect_structural_device
    return detect_structural_device(inp.get("transcript") or "")


ADAPTERS: dict[str, Callable[[dict], Any]] = {
    "say_it_stronger": _say_it_stronger,
    "best_presentation": _best_presentation,
    "slide_claims": _slide_claims,
    "slide_entailment": _slide_entailment,
    "coach_comment_draft": _coach_comment_draft,
    "moment_suggestion": _moment_suggestion,
    "structural_star": _structural_star,
}
