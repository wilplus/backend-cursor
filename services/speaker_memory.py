"""Speaker memory: Will learns about each speaker (WIL-74, founder 2026-10-20).

No model is retrained. Each speaker has one short private note (at most five
lines) that the AI rewrites from what happened, and Will reads it before it
chats and before it writes the summary after a Take. The note is plain text
in our own database, so it survives any change of AI provider.

    events (kept for good) ──► the note (≤ 5 lines) ──► Will's prompt
    speaker_memory_events      speaker_memory            chat + summary

Public API, the only way in or out (keep it that way):

  record(database, user_id, kind, payload, take_session_id, arc_id)
      An event happened. Stored, then the note is rewritten in the
      background (a "chat" event only now and then, see _rewrites_now).
      Never raises. Kinds:
        "answer"      an answer to "Did this help?" (helped, missing, skipped)
        "take"        a Take's outcome (practice, moved, helper_words)
        "transcript"  a spoken Take's transcript is final (opening, closing)
        "coach_word"  the speaker was SENT a coach's word: a Take word, its
                      video's transcript or a moment answer (source,
                      excerpt, edited). Never a draft
        "chat"        the speaker's own chat message (excerpt). Never Will's
                      reply, never an answer to "Did this help?"
  record_later(database, user_id, kind, payload, take_session_id, arc_id)
      The same, entirely off the caller's thread (the recording pipeline,
      the coach's save, the chat route). With no user_id, the Take's own
      speaker. The same event kept twice is kept once.
  forget(database, user_id, take_session_ids)
      A Take or project of theirs was erased: its events go (the ids given)
      and the note is written again from what remains. Never raises.
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
    rewrite carrying a digit is refused and the old note stays. The lines
    the model reads carry no digit either (_words_only), so a transcript
    with a number in it does not get every rewrite refused.
  - Every AI call goes through the processing-authorization path: in the
    protected scope of the Take the event came from, or, for a chat event,
    in the chat's own (the speaker's current ``ai_conversation`` authority,
    as routes.v2.processing_authorization.phase1_provider_route binds it).
    A line from a Take whose authorization is no longer in force never
    reaches the model, nor a chat line without current authority
    (_readable; fails closed). Nor does a line from a Take in a project
    the speaker erased or archived.
  - Both tables are purged with the account, and the events with their
    Take or project too (data_purge_registry); the note is written again
    after a Take or project is erased (forget).

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
KINDS = ("answer", "take", "transcript", "coach_word", "chat")
MAX_LINES = 5
MAX_CHARS = 800
#: How many recent events the AI reads for an update: the newest of the
#: Take, answer and coach kinds, and the newest chat messages beside them, so
#: a chatty week never pushes a Take out of the window. A rebuild reads
#: every event, chat capped at _REBUILD_CHAT.
_RECENT = 12
_RECENT_CHAT = 6
_REBUILD_CHAT = 40
_READ = 60
#: A chat message rewrites the note only when it is the speaker's first of
#: the day (UTC) or every _CHAT_EVERY-th that day (_rewrites_now).
_CHAT_EVERY = 10
#: How long a stored excerpt may be.
EXCERPT = 300
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
    "- Events may quote their own takes, what their coach sent them and what "
    "they wrote in the chat: keep what their coach told them to work on and "
    "what they keep asking about. Never copy their words.\n"
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


def _words_only(text: Any, limit: int = EXCERPT) -> str:
    """The text with every word that carries a digit or a percent sign
    dropped, flattened to one line and cut at a word boundary: what a line
    the model reads may quote. A number said in words stays words. Pure."""
    flat = " ".join(w for w in str(text or "").split() if not _DIGIT.search(w))
    flat = flat.replace('"', "'")
    if len(flat) > limit:
        flat = flat[:limit].rsplit(" ", 1)[0] + "…"
    return flat.strip()


_COACH = {"take_word": "Their coach wrote to them",
          "take_video": "Their coach told them in a video",
          "moment_answer": "Their coach answered one of their moments"}


def _event_line(event: dict) -> str:
    p = event.get("payload") or {}
    kind = event.get("kind")
    if kind == "answer":
        if p.get("skipped"):
            return "- Asked if the feedback helped: they skipped the follow-up."
        if p.get("missing"):
            missing = _words_only(p["missing"])
            return f"- Said what would help: \"{missing}\"" if missing else ""
        if p.get("helped") is True:
            return "- Said the feedback helped."
        if p.get("helped") is False:
            return "- Said the feedback did not really help."
        return ""
    if kind == "take":
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
        words = [_words_only(w, 60) for w in (p.get("helper_words") or [])
                 if isinstance(w, str)][:2]
        words = [w for w in words if w]
        if words:
            bits.append("chose helper words " + ", ".join(f'"{w}"' for w in words))
        return f"- A take: {'; '.join(bits)}." if bits else ""
    if kind == "transcript":
        opening, closing = _words_only(p.get("opening")), _words_only(p.get("closing"))
        if opening and closing:
            return f"- In a take they opened with \"{opening}\" and closed with \"{closing}\""
        return f"- In a take they said: \"{opening or closing}\"" if opening or closing else ""
    if kind == "coach_word":
        label, excerpt = _COACH.get(str(p.get("source") or "")), _words_only(p.get("excerpt"))
        if not label or not excerpt:
            return ""
        return f"- {label}{' (an edit)' if p.get('edited') else ''}: \"{excerpt}\""
    if kind == "chat":
        excerpt = _words_only(p.get("excerpt"))
        return f"- They wrote in the chat: \"{excerpt}\"" if excerpt else ""
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


def _chat_principal(database: Any, user_id: str, service: Any) -> Optional[str]:
    """The speaker's acquisition principal when it holds current
    ``ai_conversation`` authority (the chat's own rule,
    routes.v2.processing_authorization.phase1_provider_route), else None.
    Read only: nothing is created. Raises when the check cannot be made."""
    from services.processing_authorization import ProcessingAuthorizationError
    owner = database.get_owner_principal_for_user(str(user_id)) or {}
    principal = service.resolve_acquisition_principal(str(owner.get("id") or ""),
                                                      user_id=str(user_id))
    if not principal:
        return None
    try:
        service.require_current(principal, operation="ai_conversation")
    except ProcessingAuthorizationError as refusal:
        if refusal.status >= 500:
            raise
        return None
    return str(principal)


def _readable(database: Any, user_id: str, events: list[dict]) -> list[dict]:
    """The events whose lines may reach the model now (founder 2026-10-20,
    as in step 1). An event on a Take only when the Take is still this
    speaker's, in a project they have not erased or archived
    (services.speaker_lookup), and, while the gate enforces, its
    authorization is in force (``takes_in_force``); an event on no Take
    (chat) only while the speaker holds current chat authority. A check
    that cannot be made keeps its events out (fails closed)."""
    from services.processing_authorization import ProcessingAuthorizationService
    service = ProcessingAuthorizationService(database)
    takes = sorted({str(e["take_session_id"]) for e in events if e.get("take_session_id")})
    live: set[str] = set()
    if takes:
        try:
            from services.speaker_lookup import hidden_arcs, takes_in_force
            rows = [database.v2_get_session_by_id(t) or {} for t in takes]
            rows = [r for r in rows if r.get("id") and str(r.get("user_id") or "") == user_id]
            hidden = hidden_arcs(database, rows)
            rows = [r for r in rows if str(r.get("arc_id") or "") not in hidden]
            live = (takes_in_force(database, rows) if service.enforced
                    else {str(r["id"]) for r in rows})
        except Exception as error:  # noqa: BLE001 -- no Take line goes
            logger.warning("speaker memory: Takes unread user=%s: %s", user_id, error,
                           exc_info=True)
            live = set()
    chat_ok = not service.enforced
    if chat_ok is False and any(not e.get("take_session_id") for e in events):
        try:
            chat_ok = _chat_principal(database, user_id, service) is not None
        except Exception as error:  # noqa: BLE001 -- no chat line goes
            logger.warning("speaker memory: chat authority unread user=%s: %s", user_id,
                           error, exc_info=True)
    return [e for e in events
            if (str(e["take_session_id"]) in live if e.get("take_session_id") else chat_ok)]


def _under_authority(database: Any, user_id: str, take: Optional[str], write):
    """Run ``write`` inside a protected provider scope when the
    processing-authorization mode enforces: the Take's (as take_summary
    does), or with no Take the chat's own (the speaker's current
    ``ai_conversation`` authority, no Take coordinates, as
    phase1_provider_route). No authority, no call while enforced."""
    from services.processing_authorization import ProcessingAuthorizationService
    authorization = ProcessingAuthorizationService(database)
    if not authorization.enforced:
        return write()
    from services.authorized_provider import (
        AuthorizedProviderAdapter, ProviderCoordinates, protected_provider_scope)
    if take:
        session = database.v2_get_session_by_id(take) or {}
        principal = authorization.resolve_acquisition_principal(
            str(session.get("owner_principal_id") or ""),
            user_id=str(session.get("user_id") or "") or None)
    else:
        principal = _chat_principal(database, user_id, authorization)
    if not principal:
        return None
    adapter = AuthorizedProviderAdapter(
        database, ProviderCoordinates(principal, take or None, None), authorization=authorization)
    prefix = f"speaker-memory:{take or 'chat'}:{uuid.uuid4()}"
    with protected_provider_scope(adapter, idempotency_prefix=prefix):
        return write()


def _window(events: list[dict], *, other: Optional[int], chat: int) -> list[dict]:
    """The newest ``other`` events of the Take, answer and coach kinds (all
    of them when None) and the newest ``chat`` chat messages, oldest first.
    Pure."""
    chats = [i for i, e in enumerate(events) if e.get("kind") == "chat"]
    rest = [i for i, e in enumerate(events) if e.get("kind") != "chat"]
    keep = set(chats[-chat:] if chat else []) | set(rest if other is None else rest[-other:])
    return [e for i, e in enumerate(events) if i in keep]


def refresh(database: Any, user_id: str, take: Optional[str], *, from_scratch: bool = False) -> bool:
    """Rewrite the note from the old one and the recent events (or from
    every event when ``from_scratch``). Only the events that may reach the
    model now are read (_readable). True when a new note was saved."""
    events = database.list_speaker_memory_events(user_id, limit=None if from_scratch else _READ)
    events = (_window(events, other=None, chat=_REBUILD_CHAT) if from_scratch
              else _window(events, other=_RECENT, chat=_RECENT_CHAT))
    events = _readable(database, user_id, events)
    old = "" if from_scratch else note_for(database, user_id)
    note = _under_authority(database, user_id, take,
                            lambda: _write(old, events, user_id=user_id, take=take))
    if not note or note == old:
        return False
    from services.llm_config import SPEC_SPEAKER_MEMORY
    return bool(database.save_speaker_memory({
        "user_id": user_id, "note": note, "written_by": "ai",
        "model": getattr(SPEC_SPEAKER_MEMORY, "model", None), "updated_at": _now()}))


def _rewrites_now(database: Any, user_id: str, kind: str) -> bool:
    """Whether this event rewrites the note at once. Every kind does but
    "chat": a chat message is kept, and rewrites only as the speaker's first
    message of the day (UTC) or every _CHAT_EVERY-th that day, so the chat
    costs about one rewrite a day, not one per turn. A count that cannot be
    read rewrites nothing (the next event folds the message in)."""
    if kind != "chat":
        return True
    day = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    count = database.count_speaker_memory_events(user_id, kind="chat", since=day.isoformat())
    return isinstance(count, int) and (count == 1 or (count > 0 and count % _CHAT_EVERY == 0))


def _rewrite_later(database: Any, user_id: str, take: Optional[str], *,
                   from_scratch: bool = False) -> None:
    def run() -> None:
        try:
            refresh(database, user_id, take, from_scratch=from_scratch)
        except Exception as error:  # noqa: BLE001 -- the old note stays
            logger.warning("speaker memory: note not rewritten user=%s: %s", user_id, error,
                           exc_info=True)
    try:
        from services.parallel import start_scoped_thread
        start_scoped_thread(run, name="speaker-memory")
    except Exception as error:  # noqa: BLE001 -- the event is kept either way
        logger.warning("speaker memory: rewrite not started user=%s: %s", user_id, error,
                       exc_info=True)


def record(database: Any, user_id: Any, kind: str, payload: dict,
           take_session_id: Optional[str] = None, arc_id: Optional[str] = None) -> None:
    """An event happened: kept for good (with its Take and project, so it
    goes when they are erased), then the note is rewritten off the request
    when _rewrites_now says so. Never raises."""
    if not user_id or kind not in KINDS:
        return
    try:
        kept = database.insert_speaker_memory_event({
            "user_id": str(user_id), "kind": kind, "payload": payload or {},
            "take_session_id": str(take_session_id) if take_session_id else None,
            "arc_id": str(arc_id) if arc_id else None})
        if kept is False or not _rewrites_now(database, str(user_id), kind):
            return
    except Exception as error:  # noqa: BLE001 -- the speaker's flow never waits on memory
        logger.warning("speaker memory: event not kept user=%s: %s", user_id, error, exc_info=True)
        return
    _rewrite_later(database, str(user_id), take_session_id)


def _kept_before(database: Any, user_id: str, kind: str, payload: dict,
                 take: Optional[str]) -> bool:
    """The same event is among the speaker's recent ones already (a
    re-run of the pipeline, a coach saving the same sent word again)."""
    def same(p: Any) -> dict:
        return {k: v for k, v in (p or {}).items() if k != "edited"}
    recent = database.list_speaker_memory_events(user_id, limit=_READ) or []
    return any(e.get("kind") == kind and str(e.get("take_session_id") or "") == str(take or "")
               and (kind == "transcript" or same(e.get("payload")) == same(payload))
               for e in recent)


def record_later(database: Any, user_id: Any, kind: str, payload: dict,
                 take_session_id: Optional[str] = None, arc_id: Optional[str] = None) -> None:
    """``record``, entirely off the caller's thread: the recording pipeline,
    the coach's save and the chat route never wait on a database call for
    it. With no ``user_id`` the event is the Take's own speaker's; the
    Take's project is filled in when not given. An event already kept is
    not kept again. Never raises."""
    if kind not in KINDS or not (user_id or take_session_id):
        return

    def run() -> None:
        try:
            uid, arc = user_id, arc_id
            if take_session_id and (not uid or not arc):
                session = database.v2_get_session_by_id(str(take_session_id)) or {}
                if uid and str(session.get("user_id") or "") not in ("", str(uid)):
                    return  # not this speaker's Take: nothing is learned from it
                uid, arc = uid or session.get("user_id"), arc or session.get("arc_id")
            if not uid or _kept_before(database, str(uid), kind, payload, take_session_id):
                return
            record(database, uid, kind, payload, take_session_id, arc)
        except Exception as error:  # noqa: BLE001 -- the caller's flow never waits on memory
            logger.warning("speaker memory: event not kept kind=%s: %s", kind, error,
                           exc_info=True)
    try:
        from services.parallel import start_scoped_thread
        start_scoped_thread(run, name="speaker-memory-event")
    except Exception as error:  # noqa: BLE001
        logger.warning("speaker memory: event not started kind=%s: %s", kind, error,
                       exc_info=True)


def forget(database: Any, user_id: Any, take_session_ids: Any = ()) -> None:
    """A Take or a project of theirs was erased. The events of the Takes
    named go (the governed purge has already deleted them by Take and
    project, data_purge_registry), the note is emptied so nothing learned
    from them stays, and it is written again in the background from the
    events that remain. Never raises."""
    if not user_id:
        return
    uid = str(user_id)
    try:
        ids = [str(t) for t in (take_session_ids or ()) if t]
        if ids:
            database.delete_speaker_memory_events_for_takes(uid, ids)
        database.save_speaker_memory({"user_id": uid, "note": "", "written_by": "ai",
                                      "model": None, "updated_at": _now()})
    except Exception as error:  # noqa: BLE001 -- the erasure itself is done
        logger.warning("speaker memory: not forgotten user=%s: %s", uid, error, exc_info=True)
        return
    _rewrite_later(database, uid, None, from_scratch=True)


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
