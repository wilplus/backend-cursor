"""Act it: the founder acts a mistake, then labels its fixes (N708).

The founder picks the state (for now only "tense": high arousal, negative
valence), names the mistake (one of their names, or a new one), and records
it. The recording goes through the corpus import lane unchanged
(``services.training_import``): the same content gate, the corpus
registration the processing-authorization path requires, the transcription
and the measurements. Its import carries ``intake_context.acted``
(``{"state", "pattern"}``), which keeps it out of every coach queue and the
Corpus list (``training_import_setup.setup_complete``). Its labels are
ordinary Pattern Library rows (source ``corpus``), so Sniper, Rephrase and
AI Audio shape them as they shape any clip.

The founder's own voice is kept, as every corpus import's audio is; nothing
here plays it to a speaker. Odyssey reads of these clips come later.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.refusal import Refusal

logger = logging.getLogger(__name__)

#: The states one can act. Only one for now (founder, N708).
STATES = ("tense",)
LANGUAGES = ("pl", "en")
SPEAKER_LABEL = "Act it"
#: About 12 seconds of speech: one sentence, one clip.
MAX_AUDIO_BYTES = 3_000_000
#: The founder's acted recordings read per list.
LIST_LIMIT = 200


def acted_of(session: Any) -> Optional[dict]:
    """The acted marker of an import, or None."""
    ctx = session.get("intake_context") if isinstance(session, dict) else None
    acted = ctx.get("acted") if isinstance(ctx, dict) else None
    return acted if isinstance(acted, dict) else None


def _owned(session: Any, curator: str) -> bool:
    from services.corpus_coach_queue import is_corpus_import
    ctx = session.get("intake_context") if isinstance(session, dict) else {}
    return (is_corpus_import(session) and acted_of(session) is not None
            and str(session.get("user_id") or "") == str(curator)
            and not (ctx or {}).get("archived_at"))


def acted_clip(database: Any, curator: str, session_id: str, snippet_id: str) -> Optional[dict]:
    """A clip of the founder's own acted recording, or None."""
    try:
        snippet = database.get_snippet_by_id(str(snippet_id))
    except Exception:
        logger.warning("acted clip %s was not read", snippet_id, exc_info=True)
        return None
    if not isinstance(snippet, dict) or str(snippet.get("session_id") or "") != str(session_id):
        return None
    if not _owned(database.v2_get_session_by_id(str(session_id)), curator):
        return None
    if type(snippet.get("duration_ms")) is not int or snippet["duration_ms"] <= 0:
        return None
    return snippet


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit:
        raise Refusal("INVALID_ACTED", "Name the mistake.", 400)
    return value.strip()


def start(database: Any, curator: str, upload: Any, form: Any) -> tuple[dict, int]:
    """POST: one acted recording into the import lane; 202 while it is
    written out."""
    from services.training_import_request import start_training_import
    state = form.get("state")
    language = (form.get("language") or "").strip().lower()
    if state not in STATES or language not in LANGUAGES or upload is None:
        raise Refusal("INVALID_ACTED", "Choose the state and record the mistake.", 400)
    pattern = _text(form.get("pattern"), 100)
    return start_training_import(
        database, upload, {"speaker_label": SPEAKER_LABEL, "note": "Act it"},
        uploader_id=curator, topic=pattern, language=language,
        acted={"state": state, "pattern": pattern},
    )


def _clip(snippet: dict) -> Optional[dict]:
    from services.corpus_coach_queue import playback_body
    from services.speaking_patterns import clip_words
    if type(snippet.get("duration_ms")) is not int or snippet["duration_ms"] <= 0:
        return None
    playback = playback_body(snippet)
    return {
        "snippet_id": str(snippet["id"]),
        "words": clip_words(snippet),
        "duration_ms": snippet["duration_ms"],
        "start_offset_ms": snippet.get("start_offset_ms") or 0,
        "src": playback["url"] if playback else None,
    }


def listing(database: Any, curator: str) -> dict:
    """GET: the founder's acted recordings, newest first, with their clips
    once written out, and every mistake name they have used."""
    rows = database.takes.list_training_import_sessions(
        user_id=curator, limit=LIST_LIMIT, offset=0) or []
    recordings, names = [], []
    for row in rows:
        if not _owned(row, curator):
            continue
        acted = acted_of(row) or {}
        name = str(acted.get("pattern") or "")
        if name and name not in names:
            names.append(name)
        status = row.get("analysis_state") or "ready"
        clips = []
        if status == "ready":
            snippets = database.get_snippets_by_session(str(row["id"])) or []
            clips = [clip for clip in map(_clip, snippets) if clip]
        recordings.append({
            "session_id": str(row["id"]), "state": acted.get("state"), "pattern": name,
            "status": status, "created_at": row.get("created_at"), "clips": clips,
        })
    return {"recordings": recordings, "names": names, "states": list(STATES)}
