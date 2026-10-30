"""The walk quotes your notebook (founder 2026-10-29, N268; prototype
https://claude.ai/artifact/Jt2XrfdifpU2A41rbZed8D, version 2, placement B;
rules: frontend docs/flows/principles.md §1 R and
docs/flows/feedback-walk-and-chat.md C5).

On a corrected moment's Clearer version, while the speaker practises, the
walk asks for one quote (``ask``). Will (the model) reads the sentence they
said and the words they keep, and picks one that answers it, or none:

  * a kept 💪 strength, with the newest note it gathered (N2, N3);
  * the 🔭 vision line of Your why (Q1);
  * a # note that names what is theirs to control (O).

Only when the sentence doubted them, played the idea down or hedged. The
quote is their own words, copied word for word with its date; the line
above it is signed (``COPY``). At most one per Take (``walk_quotes``,
UNIQUE). The walk shows it under the praise line after a Good job, and says
so (``shown``): the first one shown carries "From your notebook. Only you
and Will see this." and "Not here" (the frontend's words). "Not here"
(``set_on(False)``) keeps the notebook out of every later walk until the
Life Panel's switch turns it back on.

Ring row ``walk_quotes``, ring 5, and only with the notebook kept. The
model call goes through ``services.llm`` like every provider call. Private:
the Life Panel's store (services/life_store.py), never read by a coach, the
coach's queue or the coach panel (N182, Never 2).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

FEATURE = "walk_quotes"
_SURFACE = "walk_quotes"
#: The signed words (N268). No new words without the founder's OK.
COPY = {
    "vision": "That's the voice of your 🔭 vision.",
    "yours": "You talked about the part that's yours. That's where your effort goes.",
}
_LOOKBACK = timedelta(days=60)
_MAX_SAID = 600
_MAX_NOTE = 600
_MAX_NOTES = 40

_PICK = """One speaker just practised a sentence from their talk. You get the
sentence as they first said it, and words they keep for themselves, each with
an id: their kept strengths (S1, S2, ...) with a note that shows each one,
their vision (V), and their own short notes (N1, N2, ...).

Pick at most one id whose words answer the sentence:
- S: the sentence doubts the speaker ("I'm not a numbers person", "I'm no
  expert") and the strength plainly shows the opposite;
- V: the sentence plays the idea down ("just a small project") and the vision
  shows what it is for;
- N: the sentence leans on something out of their hands ("it all depends on
  the supplier") and the note names something they did or will do about it.
Only when it clearly fits. A sentence that does none of these, or words that
only loosely relate: null. Never stretch.

Return JSON only: {"pick": "<id>" or null}."""


class WalkQuoteError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def available(database: Any, user_id: Any) -> bool:
    """The ring row on and the notebook kept. Fails closed."""
    from services import rings, voice_notebook
    if not user_id:
        return False
    try:
        return (rings.feature_is_on_for_user(FEATURE, user_id, database=database)
                and voice_notebook.consented(database, str(user_id)))
    except Exception as e:
        logger.warning("walk_quote: available failed user=%s: %s", user_id, e, exc_info=True)
        return False


def setting(database: Any, user_id: str) -> dict:
    """The Life Panel's switch: {available, on}."""
    from services import life_store
    if not available(database, user_id):
        return {"available": False, "on": False}
    return {"available": True,
            "on": not life_store.get_walk_quote_settings(str(user_id)).get("off")}


def set_on(database: Any, user_id: str, on: Any) -> dict:
    """"Not here" (False) or the Life Panel's switch."""
    from services import life_store
    if not available(database, user_id):
        raise WalkQuoteError("NOT_AVAILABLE", "Not available", 404)
    if not isinstance(on, bool):
        raise WalkQuoteError("BAD_CHOICE", "on must be true or false")
    if not life_store.save_walk_quote_settings(str(user_id), {
            "off": not on, "changed_at": datetime.now(timezone.utc).isoformat()}):
        raise WalkQuoteError("NOT_SAVED", "Could not save the setting", 503)
    return setting(database, user_id)


def _owned(database: Any, user_id: str, session_id: str) -> bool:
    try:
        session = database.v2_get_session_by_id(str(session_id))
    except Exception as e:
        logger.warning("walk_quote: session read failed id=%s: %s", session_id, e, exc_info=True)
        return False
    return bool(session) and str(session.get("user_id") or "") == str(user_id)


def _clip(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def _day(raw: Any) -> Optional[str]:
    text = str(raw or "")[:10]
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        return None


def _candidates(database: Any, user_id: str) -> dict[str, dict]:
    """{id: {kind, source_id, title, quote, said_on}}: only words they keep."""
    from services import life_store
    from services.voice_notebook import _crisis
    out: dict[str, dict] = {}
    notes_of: dict[str, dict] = {}
    for n in life_store.strength_notes(user_id):
        if _clip(n.get("body"), _MAX_NOTE):
            notes_of[str(n.get("strength_id"))] = n  # oldest first: the newest wins
    kept = [s for s in life_store.list_strengths(user_id) if s.get("status") == "kept"]
    for s in kept:
        note = notes_of.get(str(s.get("id")))
        if note and _clip(s.get("title"), 80):
            out[f"S{len([k for k in out if k.startswith('S')]) + 1}"] = {
                "kind": "strength", "source_id": str(s["id"]),
                "title": _clip(s.get("title"), 80),
                "quote": _clip(note.get("body"), _MAX_NOTE),
                "said_on": _day(note.get("noted_on"))}
    why = life_store.get_why(user_id)
    vision = _clip(why.get("vision"), _MAX_NOTE)
    if vision:
        out["V"] = {"kind": "vision", "source_id": None, "title": None,
                    "quote": vision, "said_on": None}
    since = (datetime.now(timezone.utc) - _LOOKBACK).date().isoformat()
    notes = database.list_voice_notes(user_id, limit=_MAX_NOTES) or []
    i = 0
    for n in notes:
        text = _clip(n.get("text_clean"), _MAX_NOTE).lstrip("#").strip()
        on = _day(n.get("created_at"))
        if not text or not on or on < since or _crisis(text):
            continue
        i += 1
        out[f"N{i}"] = {"kind": "yours", "source_id": str(n.get("id") or "") or None,
                        "title": None, "quote": text, "said_on": on}
    return out


def _model(user: str, user_id: str) -> dict:
    from services.llm import chat_complete
    from services.llm_config import SPEC_WALK_QUOTE
    result = chat_complete(spec=SPEC_WALK_QUOTE, system=_PICK, user=user,
                           surface=_SURFACE, user_id=str(user_id))
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else {}


def _line(row: dict) -> str:
    from services.strengths import COPY as STRENGTHS
    if row.get("kind") == "strength":
        return STRENGTHS["again"].format(title=row.get("title") or "")
    return COPY.get(str(row.get("kind")), "")


def _shown_quote(row: dict, first: bool) -> Optional[dict]:
    if not row or not row.get("quote") or not _line(row):
        return None
    return {"kind": row["kind"], "line": _line(row), "quote": row["quote"],
            "said_on": row.get("said_on"), "said": row.get("said"), "first": first}


def _first(user_id: str) -> bool:
    from services import life_store
    return not life_store.get_walk_quote_settings(user_id).get("first_shown_at")


def ask(database: Any, user_id: str, session_id: Any, said: Any) -> Optional[dict]:
    """The Take's one quote for the sentence it practises, or None. Asked
    while the speaker practises; the walk shows it after a Good job."""
    from services import life_store
    from services.voice_notebook import _crisis
    user_id = str(user_id)
    sentence = _clip(said, _MAX_SAID)
    if not sentence or not session_id or not setting(database, user_id)["on"]:
        return None
    if not _owned(database, user_id, str(session_id)):
        raise WalkQuoteError("NOT_FOUND", "Take not found", 404)
    kept = life_store.get_walk_quote(user_id, str(session_id))
    if kept:  # one per Take: the same sentence gets it again, another none
        return _shown_quote(kept, _first(user_id)) if kept.get("said") == sentence else None
    if _crisis(sentence):
        return None
    options = _candidates(database, user_id)
    if not options:
        return None
    lines = [f"SENTENCE: {sentence}"]
    for key, o in options.items():
        if o["kind"] == "strength":
            lines.append(f"{key}. strength \"{o['title']}\", shown by: {o['quote']}")
        elif o["kind"] == "vision":
            lines.append(f"{key}. vision: {o['quote']}")
        else:
            lines.append(f"{key}. ({o['said_on']}) {o['quote']}")
    pick = _model("\n".join(lines), user_id).get("pick")
    chosen = options.get(pick) if isinstance(pick, str) else None
    if not chosen:
        return None
    row = life_store.insert_walk_quote(user_id, str(session_id), {
        "said": sentence, **chosen}) or life_store.get_walk_quote(user_id, str(session_id))
    if not row or row.get("said") != sentence:
        return None
    return _shown_quote(row, _first(user_id))


def shown(database: Any, user_id: str, session_id: Any) -> dict:
    """The walk showed the Take's quote: kept, and the first one noted."""
    from services import life_store
    user_id = str(user_id)
    if not available(database, user_id) or not session_id:
        raise WalkQuoteError("NOT_AVAILABLE", "Not available", 404)
    if not life_store.get_walk_quote(user_id, str(session_id)):
        raise WalkQuoteError("NOT_FOUND", "No quote for this Take", 404)
    life_store.mark_walk_quote_shown(user_id, str(session_id))
    if _first(user_id):
        life_store.save_walk_quote_settings(user_id, {
            "first_shown_at": datetime.now(timezone.utc).isoformat()})
    return {"ok": True}


def replay(database: Any, user_id: str, session_id: Any) -> Optional[dict]:
    """A walk played again: the quote the walk already showed, as it was
    shown; nothing once the setting is off."""
    from services import life_store
    user_id = str(user_id)
    if not session_id or not setting(database, user_id)["on"]:
        return None
    row = life_store.get_walk_quote(user_id, str(session_id))
    return _shown_quote(row, False) if row.get("shown_at") else None
