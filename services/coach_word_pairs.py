"""The coach's own words as pair surfaces, C5-a (founder 2026-10-01; Phase 7
of the coach panel), dark behind ``Config.COACH_WORD_PAIRS_ENABLED``.

C5-a: "The coach's written words become preference surfaces like the other
three. The model drafts them, the draft sits in the field the coach edits
and is never shown to the speaker as drafted, and when the coach's final
differs, the (draft, final) pair is recorded under the C5 rule, never mixed
with other surfaces."

Two surfaces: ``coach_moment_line`` (the personal line on a moment, C1) and
``coach_take_word`` (the Take word, 35g-6). The Take word's video transcript
is saved as a second final (final_kind "transcript"), text only.

BLIND: a draft is requested only AFTER the coach judged every moment of the
Take (the Take word) or rated the moment (the line); the drafter's inputs
are the transcript and the coach's own text, never acoustics, never the
read; the draft states nothing about the read and carries no number.
Pre-fill returns for these two fields only (reversing 2026-07-14 for them).
TEXT ONLY: pairs are stored as text; nothing filters or rewrites the
coach's words.

THE DOORS (Privacy/Terms 3.5, signed by the founder 2026-10-08, decisions
log N68; legal/phase1-2026.1/22-…SIGNED, E2): the coach's own words are
training data under the SPEAKER's training yes, and the coach agreement
covers the coach's side. Doors 2, 3 and 4 know both surfaces
(feedback_pairs.DOOR_SURFACES), and each still opens for one only when its
switch is on and the founder named it in the door's config set. The
drafter keeps what its prompt was given (``draft_prompt`` on the row,
0459), the pair carries it, and a training example or a golden evaluation
rebuilds this module's prompt from it verbatim; a pair without it is never
released, judged or trained on. Door 3 needs the sealed golden set and 200
pairs. The ledger reports, per surface, the share of drafts sent unchanged.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

SURFACES = ("coach_moment_line", "coach_take_word")
LABEL = "Drafted from this Take · edit every word"
_MAX_PASSAGE = 1200
#: The prompt family a coach-word pair's ``prompt_context`` names; a pair
#: whose context does not name it was not drafted under this module's
#: prompts as kept, and is never an example or a reference.
PROMPT_FAMILY = "coach_word_drafts"


def word_pairs_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "COACH_WORD_PAIRS_ENABLED", False))


# ── drafting (text only) ──────────────────────────────────────────────────

def _every_moment_judged(database: Any, *, take_session_id: str, coach_id: str) -> bool:
    """The Take word's blind gate: this coach has rated every bookmarked
    moment of the Take."""
    bookmarked = database.list_bookmarked_snippet_ids(str(take_session_id)) or []
    if not bookmarked:
        return False
    ratings = database.get_own_state_ratings_for_session(str(take_session_id), str(coach_id)) or {}
    return all(str(s) in {str(k) for k in ratings} for s in bookmarked)


def passage_for(transcript: Any) -> str:
    """The transcript exactly as the prompt is given it: whitespace
    collapsed, cut at _MAX_PASSAGE characters, never ending on a space (so
    a kept passage collapses to itself and its prompt rebuilds verbatim)."""
    return " ".join(str(transcript or "").split())[:_MAX_PASSAGE].rstrip()


def prompt_snapshot(*, transcript: Any, coach_text: Optional[str]) -> dict:
    """What the draft's prompt was given, kept on the draft's row and then
    on its pair: {passage_text, prompt_context}."""
    return {"passage_text": passage_for(transcript),
            "prompt_context": {"prompt": PROMPT_FAMILY,
                               "coach_text": str(coach_text).strip() if coach_text else None}}


def prompt_from(surface: str, passage: Any, context: Any) -> Optional[tuple[str, str]]:
    """(system, user) for a coach-word surface, rebuilt verbatim from a kept
    snapshot; None when the surface is not one of these two, or the
    snapshot is missing, from another prompt family, or has no passage."""
    from services.prompts.coach_word_drafts import SYSTEM, user
    system = SYSTEM.get(str(surface or ""))
    text = " ".join(str(passage or "").split())
    if system is None or not text or not isinstance(context, dict):
        return None
    if context.get("prompt") != PROMPT_FAMILY or "coach_text" not in context:
        return None
    coach_text = context.get("coach_text")
    return system, user(surface=str(surface), transcript=text,
                        coach_text=str(coach_text) if coach_text else None)


def compose(*, surface: str, transcript: str, coach_text: Optional[str],
            user_id: Optional[str] = None) -> Optional[dict]:
    """The one model call, text only: the transcript and the coach's own
    words. {"text", "model_version"} or None."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_COACH_ANSWER_DRAFT
    from services.prompts.coach_word_drafts import SYSTEM, user
    system = SYSTEM.get(surface)
    passage = passage_for(transcript)
    if system is None or not passage:
        return None
    result = chat_complete(spec=SPEC_COACH_ANSWER_DRAFT, system=system,
                           user=user(surface=surface, transcript=passage, coach_text=coach_text),
                           surface=surface, user_id=user_id)
    text = str(getattr(result, "text", "") or "").strip()
    if not text:
        return None
    return {"text": text, "model_version": str(getattr(result, "model", "") or "")}


def draft_take_word(database: Any, *, take_session_id: str, coach_id: str,
                    body: Any) -> tuple[int, dict]:
    """POST .../word/draft: a draft of the Take word from the Take's
    transcript and the coach's notes, kept on the coach's word row."""
    if not word_pairs_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    if not _every_moment_judged(database, take_session_id=take_session_id, coach_id=coach_id):
        return 409, {"code": "JUDGE_EVERY_MOMENT_FIRST",
                     "error": "Judge every moment of this Take before a draft."}
    fields: dict = body if isinstance(body, dict) else {}
    transcript = " ".join(str(s.get("transcript") or "") for s in
                          (database.get_snippets_by_session(str(take_session_id)) or [])
                          if isinstance(s, dict))
    notes = str(fields.get("notes") or "").strip() or None
    draft = compose(surface="coach_take_word", transcript=transcript,
                    coach_text=notes, user_id=coach_id)
    if draft is None:
        return 503, {"code": "DRAFT_UNAVAILABLE", "error": "A draft could not be written right now."}
    database.set_coach_take_word_draft(take_session_id=str(take_session_id), coach_id=str(coach_id),
                                       text=draft["text"], model_version=draft["model_version"],
                                       prompt=prompt_snapshot(transcript=transcript, coach_text=notes))
    return 200, {"draft": {"surface": "coach_take_word", "text": draft["text"],
                           "model_version": draft["model_version"], "label": LABEL}}


def draft_moment_line(database: Any, *, request_row: Any, coach_id: str,
                      body: Any) -> tuple[int, dict]:
    """POST .../moment-line/draft: a draft of the personal line on a moment
    (an answer in words of kind note), after the coach's rating; kept on
    the request row under draft_surface coach_moment_line."""
    if not word_pairs_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    if not isinstance(request_row, dict) or not request_row.get("id"):
        return 404, {"code": "NOT_FOUND", "error": "No request for this moment."}
    from services.coach_request_drafts import changed_by_another_coach
    if changed_by_another_coach(request_row, coach_id):
        return 409, {"code": "ALREADY_RESOLVED",
                     "error": "This moment already has another coach's answer."}
    fields: dict = body if isinstance(body, dict) else {}
    snippet = database.get_snippet_by_id(str(request_row.get("snippet_id") or "")) or {}
    notes = str(fields.get("notes") or "").strip() or None
    transcript = str(snippet.get("transcript") or "")
    draft = compose(surface="coach_moment_line", transcript=transcript,
                    coach_text=notes, user_id=coach_id)
    if draft is None:
        return 503, {"code": "DRAFT_UNAVAILABLE", "error": "A draft could not be written right now."}
    database.set_exercise_coach_request_draft(request_id=str(request_row["id"]),
                                              surface="coach_moment_line", text=draft["text"],
                                              model_version=draft["model_version"],
                                              prompt=prompt_snapshot(transcript=transcript,
                                                                     coach_text=notes))
    return 200, {"draft": {"surface": "coach_moment_line", "text": draft["text"],
                           "model_version": draft["model_version"], "label": LABEL}}


# ── the pair on save ──────────────────────────────────────────────────────

def record_take_word_pair(database: Any, *, word_row: Any, coach_id: str,
                          final_text: Optional[str], final_kind: str = "final") -> Optional[dict]:
    """When a draft was shown and the coach's final differs, the pair under
    the C5 rule (feedback_pairs.record_pair; surface coach_take_word). A
    transcript of the word's video is a second final (final_kind
    "transcript"). Never in the save's way."""
    if not word_pairs_enabled() or not isinstance(word_row, dict):
        return None
    draft = word_row.get("draft_text")
    if not draft or not final_text:
        return None
    from services.feedback_pairs import record_pair
    take = str(word_row.get("take_session_id") or "")
    session = database.v2_get_session_by_id(take) or {}
    return record_pair(database, surface="coach_take_word", draft=draft, final=final_text,
                       coach_id=coach_id, model_version=word_row.get("draft_model_version"),
                       owner_user_id=session.get("user_id"), take_session_id=take,
                       take_word_id=str(word_row.get("id") or ""), final_kind=final_kind,
                       prompt_snapshot=word_row.get("draft_prompt"))


def record_moment_line_pair(database: Any, *, request_row: Any, coach_id: str,
                            final_text: Optional[str]) -> Optional[dict]:
    """The line's pair on a note answered in words (resolution note_written)."""
    if not word_pairs_enabled() or not isinstance(request_row, dict):
        return None
    if str(request_row.get("draft_surface") or "") != "coach_moment_line":
        return None
    draft = request_row.get("draft_text")
    if not draft or not final_text:
        return None
    from services.feedback_pairs import record_pair
    return record_pair(database, surface="coach_moment_line", draft=draft, final=final_text,
                       coach_id=coach_id, model_version=request_row.get("draft_model_version"),
                       owner_user_id=request_row.get("owner_user_id"),
                       take_session_id=request_row.get("take_session_id"),
                       snippet_id=request_row.get("snippet_id"),
                       request_id=str(request_row.get("id") or ""),
                       prompt_snapshot=request_row.get("draft_prompt"))


def _speaker_permit_adapter(database: Any, take_session_id: str) -> Any:
    """The provider door for the coach's Take-word video (PLF1, founder
    2026-10-05, N48.1).

    The video is the coach's, but it is about the speaker's Take and its
    transcript lands beside the speaker's words, so the permit is the
    SPEAKER's, exactly as ``speaker_provider_route`` binds the coach's text
    drafts: the Take's acquisition principal, ``require_current``, then a
    per-call permit. Coordinates are the Take and ``recording_id=None``: no
    recording of the speaker is sent, and naming one would claim it was.

    The operation is ``transcription`` (purpose ``transcription_feedback``),
    the one the RPC accepts for an OpenAI Whisper call. ``coach_review`` is
    reachable only through ``coach_delivery``, the willab_coach hand-off of
    a Take to a coach, which this is not.

    Raises ProcessingAuthorizationError when enforce mode refuses. Inert
    while the gate is off: no principal lookup, no permit, same code path.
    """
    from services.authorized_provider import AuthorizedProviderAdapter, ProviderCoordinates
    from services.processing_authorization import (
        ProcessingAuthorizationError, ProcessingAuthorizationService,
    )
    authorization = ProcessingAuthorizationService(database)
    principal_id = ""
    if authorization.enforced:
        session = database.v2_get_session_by_id(take_session_id) or {}
        principal_id = authorization.resolve_acquisition_principal(
            str(session.get("owner_principal_id") or ""),
            user_id=str(session.get("user_id") or "") or None)
        if not principal_id:
            raise ProcessingAuthorizationError(
                "PROCESSING_PRINCIPAL_UNRESOLVED",
                "The speaker of this Take could not be resolved.", 403)
        authorization.require_current(principal_id, operation="coach_draft")
    return AuthorizedProviderAdapter(
        database, ProviderCoordinates(principal_id, take_session_id or None, None),
        authorization=authorization)


def transcribe_take_word_video(database: Any, *, word_row: Any, coach_id: str) -> Optional[str]:
    """The word's video, transcribed (the coach video pipeline's own path:
    audio extracted, Whisper through the speaker's permit), saved as the
    second final. Best-effort, never raises; None when there is no video,
    it could not be read, or enforce mode refused the permit. A refusal
    costs only the transcript draft: the word and its video are already
    saved, and the coach types the words."""
    if not word_pairs_enabled() or not isinstance(word_row, dict) or not word_row.get("video_ref"):
        return None
    from services.processing_authorization import ProcessingAuthorizationError
    take = str(word_row.get("take_session_id") or "")
    try:
        from services.coach_video_storage import get_coach_object_bytes
        from services.ffmpeg_audio_extract import extract_audio_mp3_for_whisper
        ref = str(word_row["video_ref"])
        if not ref.startswith("s3://"):
            return None
        adapter = _speaker_permit_adapter(database, take)
        bucket, _, key = ref[len("s3://"):].partition("/")
        audio = extract_audio_mp3_for_whisper(get_coach_object_bytes(bucket, key), max_seconds=600)
        # usage_surface stays "whisper_take", the ledger label this call
        # always carried (the transcriber's default); relabelling is a
        # separate cost-report change.
        tr = adapter.transcribe_audio(audio, "take-word.mp3", usage_surface="whisper_take",
                                      usage_user_id=None, usage_session_id=take)
        text = (tr.get("text") or "").strip() if isinstance(tr, dict) else ""
        if not text:
            return None
        database.set_coach_take_word_transcript(take_session_id=take,
                                                coach_id=str(coach_id), transcript=text)
        record_take_word_pair(database, word_row=word_row, coach_id=coach_id,
                              final_text=text, final_kind="transcript")
        return text
    except ProcessingAuthorizationError as refused:
        _log.warning("take word transcript refused take=%s code=%s; the word is saved",
                     take, refused.code, exc_info=True)
        return None
    except Exception as e:  # noqa: BLE001 — the word is saved either way
        _log.warning("take word transcript failed take=%s: %s", take, e, exc_info=True)
        return None


def unchanged_share(rows: Any) -> dict:
    """Per surface: drafts sent unchanged over drafts shown. Pure;
    founder-only."""
    out: dict[str, dict] = {}
    for r in rows or []:
        if not isinstance(r, dict) or r.get("surface") not in SURFACES:
            continue
        entry = out.setdefault(str(r["surface"]), {"shown": 0, "unchanged": 0})
        entry["shown"] += 1
        if r.get("unchanged"):
            entry["unchanged"] += 1
    for entry in out.values():
        entry["share_unchanged"] = round(entry["unchanged"] / entry["shown"], 3) if entry["shown"] else None
    return out
