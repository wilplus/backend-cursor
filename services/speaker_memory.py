"""Speaker memory: Will learns about each speaker (WIL-74, founder 2026-10-20).

No model is retrained. Each speaker has one short private note (at most five
lines) that the AI rewrites from what happened, and Will reads it before it
chats and before it writes the summary after a Take. The note is plain text
in our own database, so it survives any change of AI provider.

    events (kept for good) ──► the note (≤ 5 lines) ──► Will's prompt
    speaker_memory_events      speaker_memory            chat + summary

Public API, the only way in or out (keep it that way):

  record(database, user_id, kind, payload, take_session_id)
      An event happened. Stored, then the note is rewritten in the
      background. Never raises. Kinds:
        "answer"  an answer to "Did this help?" (helped, missing, skipped)
        "take"    a Take's outcome (practice, moved, helper_words)
  note_for(database, user_id) -> str
      The current note, '' when there is none. Never raises.
  prompt_block(note) -> str
      The note as a private block for Will's prompts, '' when empty.
  history_for(database, user_id, question) -> str
      The few pieces of the speaker's own history (their Takes' transcripts,
      what their coach sent them, their own earlier messages) that share the
      most words with the question, as a private block; '' when none. A
      simple lookup in services/speaker_lookup.py. Never raises.
  set_note(database, user_id, note)
      The founder corrects it by hand (admin). The AI keeps building on it.
  rebuild(database, user_id, take_session_id)
      Write the note from scratch from every stored event (after a model
      change, for example).

Rules:
  - Nobody but the founder ever sees the note. Will never quotes it and
    never repeats a speaker's own answer back to them.
  - No numbers, scores or verdicts in the note (CLAUDE.md, Never 1): a
    rewrite carrying a digit is refused and the old note stays.
  - Every AI call goes through the processing-authorization path, in the
    protected scope of the Take the event came from.
  - Both tables are purged with the account (data_purge_registry); a
    project purge takes the events on its Takes and leaves the note
    (data_purge_project_scope).

This is a permanent part of the app: tests/test_speaker_memory.py guards
that the events are recorded and that Will reads the note.
"""
from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SURFACE = "speaker_memory"
KINDS = ("answer", "take")
MAX_LINES = 5
MAX_CHARS = 800
#: How many recent events the AI reads for an update (rebuild reads all).
_RECENT = 12
_DIGIT = re.compile(r"\d|%")

_SYSTEM = (
    "You keep a private note about one person who is practising public "
    "speaking in an app. The note tells the app's coach-like chat what helps "
    "this person and what to ask or focus on next time. Rewrite the note "
    "from the old note and the new events.\n"
    "Rules:\n"
    "- At most five short lines, each starting with \"- \". Plain words.\n"
    "- Only what the events show: what helped, what they said would help, "
    "what they keep struggling with, what to ask about next. Never invent.\n"
    "- No numbers, scores, percentages or verdicts. No names.\n"
    "- Keep what still holds from the old note; drop what newer events "
    "contradict.\n"
    "- Write about them in the third person. Reply with the note only."
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def clean_note(text: Optional[str]) -> Optional[str]:
    """The AI's note made safe, or None when it must be refused (empty, or
    carrying a number). Pure."""
    lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
    lines = [ln if ln.startswith("- ") else f"- {ln.lstrip('-•* ').strip()}" for ln in lines]
    note = "\n".join(lines[:MAX_LINES])[:MAX_CHARS].strip()
    if not note or _DIGIT.search(note):
        return None
    return note


#: What each of Will's questions after a Take asked (``will_question``), for
#: the note's events.
_ASKED = {
    "pause": "whether they needed a breather",
    "not_used": "whether leaving out the line they practised was on purpose",
    "audience_check": "whether the talk is for who it sounded like",
    "audience": "who the talk is for",
    "goal": "what they want the audience to do or feel",
    "vision": "whether the talk takes them where they want to go",
    "most_you": "which part of the talk is most them",
    "why_matters": "why the talk matters to them",
    "changes": "what changes for them if the talk goes perfectly",
}


def _question_line(p: dict) -> str:
    asked = _ASKED.get(str(p.get("question")), "a question")
    if p.get("skipped"):
        return f"- Asked {asked}: they skipped it."
    said = str(p.get("said") or "")[:300]
    return f"- Asked {asked}: they said \"{said}\"." if said else ""


def _event_line(event: dict) -> str:
    p = event.get("payload") or {}
    if event.get("kind") == "answer" and p.get("question"):
        return _question_line(p)
    if event.get("kind") == "answer":
        if p.get("skipped"):
            return "- Asked if the feedback helped: they skipped the follow-up."
        if p.get("missing"):
            return f"- Said what would help: \"{str(p['missing'])[:300]}\""
        if p.get("helped") is True:
            return "- Said the feedback helped."
        if p.get("helped") is False:
            return "- Said the feedback did not really help."
        return ""
    if event.get("kind") == "take":
        bits = []
        if p.get("practice") == "better":
            bits.append("their practice landed")
        elif p.get("practice") == "not_yet":
            bits.append("their practice did not land yet")
        moved = {"rose": "voice sounded surer than the last take",
                 "held": "voice about as sure as the last take",
                 "dipped": "voice less sure than the last take"}.get(p.get("moved") or "")
        if moved:
            bits.append(moved)
        words = [w for w in (p.get("helper_words") or []) if isinstance(w, str)][:2]
        if words:
            bits.append("chose helper words " + ", ".join(f'"{w}"' for w in words))
        return f"- A take: {'; '.join(bits)}." if bits else ""
    return ""


def _write(old_note: str, events: list[dict], *, user_id: str, take: Optional[str]) -> Optional[str]:
    from services.llm import chat_complete
    from services.llm_config import SPEC_SPEAKER_MEMORY
    lines = [ln for ln in (_event_line(e) for e in events) if ln]
    if not lines:
        return None
    user = ("Old note:\n" + (old_note or "(none yet)") + "\n\nNew events, oldest first:\n"
            + "\n".join(lines))
    result = chat_complete(spec=SPEC_SPEAKER_MEMORY, system=_SYSTEM, user=user,
                           surface=_SURFACE, user_id=user_id, session_id=take)
    return clean_note(getattr(result, "text", None) if result else None)


def _under_authority(database: Any, take: Optional[str], write):
    """Run ``write`` inside the Take's protected provider scope when the
    processing-authorization mode enforces (as take_summary does). No Take,
    no call while enforced."""
    from services.processing_authorization import ProcessingAuthorizationService
    authorization = ProcessingAuthorizationService(database)
    if not authorization.enforced:
        return write()
    if not take:
        return None
    from services.authorized_provider import (
        AuthorizedProviderAdapter, ProviderCoordinates, protected_provider_scope)
    session = database.v2_get_session_by_id(take) or {}
    principal = authorization.resolve_acquisition_principal(
        str(session.get("owner_principal_id") or ""),
        user_id=str(session.get("user_id") or "") or None)
    if not principal:
        return None
    adapter = AuthorizedProviderAdapter(
        database, ProviderCoordinates(principal, take, None), authorization=authorization)
    with protected_provider_scope(adapter, idempotency_prefix=f"speaker-memory:{take}:{uuid.uuid4()}"):
        return write()


def refresh(database: Any, user_id: str, take: Optional[str], *, from_scratch: bool = False) -> bool:
    """Rewrite the note from the old one and the recent events (or from
    every event when ``from_scratch``). True when a new note was saved."""
    events = database.list_speaker_memory_events(user_id, limit=None if from_scratch else _RECENT)
    old = "" if from_scratch else note_for(database, user_id)
    note = _under_authority(database, take,
                            lambda: _write(old, events, user_id=user_id, take=take))
    if not note or note == old:
        return False
    from services.llm_config import SPEC_SPEAKER_MEMORY
    return bool(database.save_speaker_memory({
        "user_id": user_id, "note": note, "written_by": "ai",
        "model": getattr(SPEC_SPEAKER_MEMORY, "model", None), "updated_at": _now()}))


def record(database: Any, user_id: Any, kind: str, payload: dict,
           take_session_id: Optional[str] = None) -> None:
    """An event happened: kept for good, then the note is rewritten off the
    request. Never raises."""
    if not user_id or kind not in KINDS:
        return
    try:
        database.insert_speaker_memory_event({
            "user_id": str(user_id), "kind": kind, "payload": payload or {},
            "take_session_id": str(take_session_id) if take_session_id else None})
    except Exception as error:  # noqa: BLE001 -- the speaker's flow never waits on memory
        logger.warning("speaker memory: event not kept user=%s: %s", user_id, error, exc_info=True)
        return

    def run() -> None:
        try:
            refresh(database, str(user_id), take_session_id)
        except Exception as error:  # noqa: BLE001 -- the old note stays
            logger.warning("speaker memory: note not rewritten user=%s: %s", user_id, error,
                           exc_info=True)
    try:
        from services.parallel import start_scoped_thread
        start_scoped_thread(run, name="speaker-memory")
    except Exception as error:  # noqa: BLE001 -- the event is kept either way
        logger.warning("speaker memory: rewrite not started user=%s: %s", user_id, error,
                       exc_info=True)


def note_for(database: Any, user_id: Any) -> str:
    """The current note, '' when there is none. Never raises."""
    if not user_id:
        return ""
    try:
        return ((database.get_speaker_memory(str(user_id)) or {}).get("note") or "").strip()
    except Exception as error:  # noqa: BLE001 -- no note: Will answers as before
        logger.warning("speaker memory: note unread user=%s: %s", user_id, error, exc_info=True)
        return ""


def prompt_block(note: str) -> str:
    """The note as a private block for Will's prompts; '' when empty."""
    if not note:
        return ""
    return ("─── WHAT HELPS THIS SPEAKER (your private note; never quote it, never "
            "repeat their answers back, never mention that you keep it) ───\n"
            + note + "\nLet it shape what you ask and what you focus on.\n")


def history_for(database: Any, user_id: Any, question: str) -> str:
    """The speaker's own history most relevant to ``question``, as Will's
    private block (services.speaker_lookup); '' when nothing matches or a
    read fails. Never raises."""
    if not user_id:
        return ""
    try:
        from services.speaker_lookup import lookup, lookup_block
        return lookup_block(lookup(database, user_id, question))
    except Exception as error:  # noqa: BLE001 -- no block: Will answers as before
        logger.warning("speaker memory: history unread user=%s: %s", user_id, error,
                       exc_info=True)
        return ""


def set_note(database: Any, user_id: str, note: str) -> Optional[str]:
    """The founder's correction. Returns the saved note, or None when it is
    refused (a number, or too long once cleaned)."""
    cleaned = clean_note(note) if (note or "").strip() else ""
    if cleaned is None:
        return None
    ok = database.save_speaker_memory({"user_id": user_id, "note": cleaned,
                                       "written_by": "founder", "model": None,
                                       "updated_at": _now()})
    return cleaned if ok else None


def rebuild(database: Any, user_id: str, take_session_id: Optional[str] = None) -> bool:
    """The note written from scratch from every stored event."""
    return refresh(database, user_id, take_session_id, from_scratch=True)
