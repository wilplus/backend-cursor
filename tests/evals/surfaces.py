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
from types import SimpleNamespace
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
    """Will's walk message (N565): the production writer and its check, on
    the row's context and step; None when the words fail ``check``."""
    from services.walk_voice import compose
    return compose(inp.get("context") or {}, inp.get("step") or {})


def _project_chat(inp: dict) -> dict:
    """Answer in a synthetic project using the same scoped context and attachments."""
    from services import project_chat

    user_id, arc_id, take_id = "project-chat-eval", "eval-project", "eval-take"
    take = {
        "id": take_id, "user_id": user_id, "arc_id": arc_id,
        "take_index": 1, "status": "completed", "analysis_state": "ready",
        "results_published_at": "2026-11-23T12:00:00Z",
        "transcription_language": inp.get("language"),
        "intake_context": {"topic": inp.get("topic")},
    }
    snippets = [{
        "id": "opening", "session_id": take_id, "transcript": inp["transcript"],
        "metrics": {"vocal_cues": inp.get("vocal_cues", []), **(inp.get("metrics") or {})},
    }]
    for item in inp.get("feedback", []):
        if item["snippet_id"] != "opening":
            snippets.append({
                "id": item["snippet_id"], "session_id": take_id, "transcript": item["transcript_corrected"],
            })
    database = SimpleNamespace(
        client=None,
        get_arc_sessions=lambda arc: [take] if arc == arc_id else [],
        get_snippets_by_sessions=lambda ids: {take_id: snippets} if take_id in ids else {},
        get_coach_snippet_drafts=lambda sid: inp.get("feedback", []) if sid == take_id else [],
        get_project_lounge_messages_page=lambda *_args, **_kwargs: [],
        get_ideal_text_document_core=lambda arc, owner: {
            "source_take_session_id": take_id, "payload": {"text": inp["ideal_text"]},
        } if arc == arc_id and owner == user_id and inp.get("ideal_text") else None,
    )
    reply, _ = project_chat.answer(
        database, user_id, arc_id, inp["question"], take_session_id=take_id,
        review_focus=inp.get("focus", {"step": "feedback", "snippet_id": "opening"}),
    )
    metadata = reply["row_metadata"]
    output = {
        "answer": reply["answer"], "moment": (metadata.get("coach_moment") or {}).get("snippet_id"),
        "practise": bool((metadata.get("coach_moment") or {}).get("practise")),
        "destination": (metadata.get("review_destination") or {}).get("step"),
    }
    if inp.get("include_wording"):
        output["wording"] = metadata.get("coach_wording")
    return output


def _speaking_coach(inp: dict) -> str | dict | None:
    """Run the shipped coach over a synthetic Take and saved delivery cues."""
    from services.speaking_coach import answer, invalidate

    user_id = "speaking-coach-eval"
    arc_id = "eval-project"
    take_id = "eval-take"
    take = {
        "id": take_id,
        "user_id": user_id,
        "arc_id": arc_id,
        "take_index": 1,
        "status": "completed",
        "recording_kind": "spoken",
        "analysis_state": "ready",
        "created_at": "2026-01-02T00:00:00Z",
        "intake_context": {"topic": inp["project_title"]},
    }
    transcript = {
        "id": take_id,
        "user_id": user_id,
        "slide_transcripts": [{"index": 0, "transcript": inp["transcript"]}],
    }
    snippets = [{"session_id": take_id, **row} for row in inp.get("snippets", [])]
    if inp.get("vocal_cues"):
        snippets.append({
            "session_id": take_id,
            "transcript": inp["transcript"],
            "metrics": {"vocal_cues": inp["vocal_cues"]},
        })
    projects = {arc_id: [take]}
    transcripts = {take_id: transcript}
    if previous := inp.get("previous_recording"):
        earlier = {**take, "id": "earlier-take", "arc_id": "earlier-project",
                   "created_at": "2026-01-01T00:00:00Z",
                   "intake_context": {"topic": previous["project_title"]}}
        projects["earlier-project"] = [earlier]
        transcripts[earlier["id"]] = {
            "id": earlier["id"], "user_id": user_id,
            "slide_transcripts": [{"index": 0, "transcript": previous["transcript"]}],
        }
    takes = SimpleNamespace(
        list_user_arc_sessions=lambda owner: [row for rows in projects.values() for row in rows]
        if owner == user_id else [],
        get_arc_sessions_many=lambda arcs: {arc: projects[arc] for arc in arcs if arc in projects},
        get_slide_transcripts_many=lambda ids: {id_: transcripts[id_] for id_ in ids if id_ in transcripts},
    )
    database = SimpleNamespace(
        client=None, takes=takes,
        get_snippets_by_sessions=lambda ids: {take_id: snippets} if take_id in ids else {},
        list_active_diagnostic_exercises=lambda: inp.get("exercises", []),
    )
    # Paired cases keep the same Take and change its delivery evidence.
    invalidate(user_id)
    reply = answer(database, user_id, inp["question"], history=inp.get("history"),
                   app_config=SimpleNamespace(SPEAKING_COACH_ENABLED=True))
    if not reply:
        return None
    answer_text = reply[0]["answer"]
    if inp.get("include_wording"):
        meta = reply[0].get("row_metadata") or {}
        artifacts = ("coach_wording", "coach_moment", "chat_artifact", "review_destination")
        return {"answer": answer_text, "project_artifact": any(key in meta for key in artifacts)}
    return answer_text


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
    "project_chat": _project_chat,
    "speaking_coach": _speaking_coach,
}
