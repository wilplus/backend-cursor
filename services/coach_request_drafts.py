"""One draft per coach request, by its kind (founder 2026-09-30, C2, C3;
build plan P2-2).

The coach opens a moment after their blind rating and may ask for a first
draft: a practice exercise for an error, one praise sentence for praise, a
clearer version of the passage for a rewrite. An ambiguity has no draft:
there the coach's own judgement is the whole answer. The draft is shown to
the coach only, stored on the request row so the final can be paired with
it (services.feedback_pairs), and never reaches the speaker as drafted.
Every draft is also kept, with what its prompt was given and the hash of
the exact text sent, in coach_draft_history (0480, N79;
services.coach_draft_history), and the row's ``draft_prompt`` names it.

The draft never blocks anything: a provider that does not answer returns
503 and the coach writes by hand, and the answer still resolves the request.
BLIND COACH: the route calls this only after the coach's own rating.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.prompts.coach_answer_drafts import (
    CLEARER_VERSION_SYSTEM, EXERCISE_SCRIPT_SYSTEM, PRAISE_LINE_SYSTEM, user,
)

_log = logging.getLogger(__name__)

#: Request kind → the surface its draft is written on. Ambiguity has none.
SURFACE_FOR_KIND = {
    "error": "exercise_script",
    "praise": "praise_line",
    "rewrite": "clearer_version",
}
_SYSTEM = {
    "exercise_script": EXERCISE_SCRIPT_SYSTEM,
    "praise_line": PRAISE_LINE_SYSTEM,
    "clearer_version": CLEARER_VERSION_SYSTEM,
}
_MAX_PASSAGE = 1200
#: The prompt family an answer draft's kept snapshot names
#: (services.prompts.coach_answer_drafts).
PROMPT_FAMILY = "coach_answer_drafts"


def surface_for(request: Any) -> Optional[str]:
    kind = str((request or {}).get("kind") or "error") if isinstance(request, dict) else ""
    return SURFACE_FOR_KIND.get(kind)


def compose_draft(*, surface: str, passage: str, spotted: list[str],
                  kind: str, notes: Optional[str] = None,
                  user_id: Optional[str] = None) -> Optional[dict]:
    """The one model call, pure of any database: ``{"text", "model_version"}``
    and the exact ``system``, ``user`` and ``passage`` it sent, or None when
    the provider gave nothing. The golden evals call this and read the
    text."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_COACH_ANSWER_DRAFT
    system = _SYSTEM.get(surface)
    passage = " ".join(str(passage or "").split())[:_MAX_PASSAGE]
    if system is None or not passage:
        return None
    sent = user(surface=surface, passage=passage, spotted=list(spotted or []),
                kind=kind, notes=notes)
    result = chat_complete(
        spec=SPEC_COACH_ANSWER_DRAFT, system=system, user=sent,
        surface=surface, user_id=user_id)
    text = str(getattr(result, "text", "") or "").strip()
    if not text:
        return None
    return {"text": text, "model_version": str(getattr(result, "model", "") or ""),
            "system": system, "user": sent, "passage": passage}


def _passage(database: Any, request: dict) -> str:
    snippet_id = str(request.get("snippet_id") or "")
    for row in database.get_snippets_by_session(str(request.get("take_session_id") or "")) or []:
        if isinstance(row, dict) and str(row.get("id")) == snippet_id:
            return str(row.get("transcript") or "").strip()
    return ""


def _spotted(database: Any, request: dict) -> list[str]:
    labels = {}
    if hasattr(database, "list_speaking_errors"):
        labels = {str(r.get("error_id")): str(r.get("label") or r.get("error_id"))
                  for r in database.list_speaking_errors() or [] if isinstance(r, dict)}
    return [labels.get(str(tag), str(tag)) for tag in request.get("observed_tags") or []]


def changed_by_another_coach(request: Any, coach_id: Any) -> bool:
    """0446 (Q-B12 A): a resolved request is open again to the coach who
    answered it (they may change their answer: a new draft, new words, a new
    video), and closed to everyone else. Pure."""
    if not isinstance(request, dict) or not request.get("resolution"):
        return False
    return str(request.get("resolved_by") or "") != str(coach_id or "")


def draft_for_request(database: Any, request: dict, body: Any, *,
                      coach_id: str) -> tuple[int, dict]:
    """POST .../exercise-request/draft: write the draft, keep it on the row,
    return it to the coach. A second call re-drafts and replaces it on the
    row; every draft stays in coach_draft_history with what its prompt was
    given (0480)."""
    if not isinstance(request, dict) or not request.get("id"):
        return 404, {"code": "NOT_FOUND", "error": "No request for this moment."}
    if changed_by_another_coach(request, coach_id):
        return 409, {"code": "ALREADY_RESOLVED",
                     "error": "This moment already has another coach's answer."}
    surface = surface_for(request)
    if surface is None:
        return 409, {"code": "NO_DRAFT_FOR_KIND",
                     "error": "An ambiguity has no draft; your judgement is the answer."}
    fields = body if isinstance(body, dict) else {}
    passage = _passage(database, request)
    if not passage:
        return 409, {"code": "NO_PASSAGE",
                     "error": "This moment has no transcript to draft from."}
    spotted = _spotted(database, request)
    kind = str(request.get("kind") or "error")
    notes = str(fields.get("notes") or "").strip() or None
    draft = compose_draft(surface=surface, passage=passage, spotted=spotted,
                          kind=kind, notes=notes, user_id=coach_id)
    if draft is None:
        return 503, {"code": "DRAFT_UNAVAILABLE",
                     "error": "A draft could not be written right now."}
    from services.coach_draft_history import keep, new_draft_id
    draft_id = new_draft_id()
    inputs = {"passage_text": draft["passage"], "kind": kind, "spotted": spotted,
              "spotted_tags": [str(t) for t in request.get("observed_tags") or []],
              "notes": notes}
    keeper = getattr(database, "set_exercise_coach_request_draft", None)
    stored = None
    if keeper is not None:
        try:
            stored = keeper(request_id=str(request["id"]), surface=surface,
                            text=draft["text"], model_version=draft["model_version"],
                            prompt=prompt_snapshot(inputs, draft_id=draft_id))
        except Exception as e:  # noqa: BLE001 -- the draft still shows
            _log.warning("coach request draft not kept id=%s: %s", request["id"], e,
                         exc_info=True)
    keep(database, draft_id=draft_id, surface=surface, prompt_family=PROMPT_FAMILY,
         coach_id=coach_id, draft=draft, inputs=inputs,
         take_session_id=request.get("take_session_id"),
         owner_user_id=request.get("owner_user_id"),
         snippet_id=request.get("snippet_id"), request_id=request["id"])
    return 200, {"draft": {"surface": surface, "text": draft["text"],
                           "model_version": draft["model_version"],
                           "kept": isinstance(stored, dict)}}


def prompt_snapshot(inputs: dict, *, draft_id: str) -> dict:
    """What an answer draft's prompt was given, kept on the request row
    (``draft_prompt``): {passage_text, prompt_context, draft_id}. Capture
    only: the answer surfaces' pairs still take their passage from the clip
    (services.feedback_pairs), and no reader rebuilds a prompt from it yet."""
    context = {key: inputs.get(key) for key in ("kind", "spotted", "spotted_tags", "notes")}
    return {"passage_text": inputs.get("passage_text"),
            "prompt_context": {"prompt": PROMPT_FAMILY, **context},
            "draft_id": str(draft_id)}


def draft_on(request: Any) -> Optional[dict]:
    """The draft a request row carries, for the coach's payload and the pair."""
    if not isinstance(request, dict) or not request.get("draft_text"):
        return None
    return {"surface": request.get("draft_surface"),
            "text": str(request.get("draft_text")),
            "model_version": request.get("draft_model_version"),
            "drafted_at": request.get("drafted_at")}
