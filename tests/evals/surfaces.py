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
    from services.slide_selection import _render_composition
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
        speaker_focus=inp.get("speaker_focus"),
    )


def _verbal_read(inp: dict) -> Any:
    """The Take's verbal read (N326): which moments it flags, as one string
    of their ids, and its line for the Clearer version. No flag stays None,
    the read's own "nothing here"."""
    from services.inner_context import InnerContext
    from services.verbal_read import read
    notes = list(inp.get("notes") or [])
    inner = InnerContext(block="Their own notes, newest last:\n"
                         + "\n".join(f"- {n}" for n in notes), phrases=tuple(notes))
    moments = [{"snippet_id": f"m{i}", "slide": i - 1, "text": text}
               for i, text in enumerate(inp.get("moments") or [], start=1)]
    found = read(moments, dict(inp.get("outside") or {}), inner)
    if found is None:
        return None
    return {"flagged": ",".join(sorted(found.weights)), "focus": found.focus}


def _structural_star(inp: dict) -> Any:
    from services.moment_suggestions import detect_structural_device
    return detect_structural_device(inp.get("transcript") or "")


def _emphasis_phrase(inp: dict) -> Any:
    """Wrapped as {"quote": …} so the rubric can dot-path into it. NO pick
    stays None rather than {"quote": None}: "nothing stands out above the
    rest" is a real answer on this surface, and None is the shape
    `allow_none_output` speaks — a case that expects a pick still fails
    loudly, a flat passage passes."""
    from services.moment_suggestions import pick_emphasis_phrase
    phrase = pick_emphasis_phrase(inp.get("transcript") or "")
    return {"quote": phrase} if phrase else None


def _coach_answer(surface: str) -> Callable[[dict], Any]:
    """The coach's answer drafts (founder 2026-09-30, C2): the pure compose
    step, no database, so the shipped prompt gets graded as served."""
    def adapter(inp: dict) -> Any:
        from services.coach_request_drafts import compose_draft
        out = compose_draft(
            surface=surface, passage=inp.get("passage") or "",
            spotted=list(inp.get("spotted") or []),
            kind=str(inp.get("kind") or "error"), notes=inp.get("notes"))
        return None if out is None else out.get("text")
    return adapter


def _will_question(inp: dict) -> Any:
    """Will's calls. A row with an ``ask`` and its ``signed`` words is his
    lead-in (N89): ``lead_in`` ties the ask to the Take's ``facts`` and says
    the ask with a light touch, or the ask as written when it fails
    ``read_lead_in``. A row with a ``key`` and a ``question`` is the light
    touch (N86): ``vary`` says the signed question in slightly different
    words, or the signed words when the variation fails ``read_varied``.
    Every other row is the heard call (N82): who the talk is for and what it
    asks, kept only where the Take says it word for word (``read_heard``)."""
    from services.will_question import heard, lead_in, vary
    if inp.get("ask") and inp.get("signed"):
        # Will's lead-in to an ask after the Take (N89): his words around the
        # signed ask, or the ask as written when the lead-in fails its checks.
        said = lead_in(str(inp["ask"]), str(inp["signed"]), list(inp.get("facts") or []),
                       user_id=None, take=None, arc_id=None)
        return {"message": said or str(inp["signed"]), "led": said is not None}
    if inp.get("key") and inp.get("question"):
        said = vary(str(inp["key"]), str(inp["question"]), user_id=None, take=None, arc_id=None)
        return {"question": said or str(inp["question"]), "varied": said is not None}
    return heard(inp.get("title") or "", inp.get("transcript") or "",
                 user_id=None, take=None, arc_id=None)


def _question_kind(inp: dict) -> Any:
    """Will's mark on a question in a chat (N361 item 1): True when it asks
    about a product or a treatment, False when not, None when unclear."""
    from services.chats import asks_about_a_product_or_treatment
    return {"mark": asks_about_a_product_or_treatment(str(inp.get("words") or ""), user_id=None)}


def _walk_voice(inp: dict) -> Any:
    """Will's walk message (N560): the production writer and its check, on
    the row's context and step; None when the words fail ``check``."""
    from services.walk_voice import compose
    return compose(inp.get("context") or {}, inp.get("step") or {})


ADAPTERS: dict[str, Callable[[dict], Any]] = {
    "praise_line": _coach_answer("praise_line"),
    "clearer_version": _coach_answer("clearer_version"),
    "exercise_script": _coach_answer("exercise_script"),
    "say_it_stronger": _say_it_stronger,
    "best_presentation": _best_presentation,
    "slide_claims": _slide_claims,
    "slide_entailment": _slide_entailment,
    "coach_comment_draft": _coach_comment_draft,
    "moment_suggestion": _moment_suggestion,
    "verbal_read": _verbal_read,
    "structural_star": _structural_star,
    "emphasis_phrase": _emphasis_phrase,
    "will_question": _will_question,
    "question_kind": _question_kind,
    "walk_voice": _walk_voice,
}
