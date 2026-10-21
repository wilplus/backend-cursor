"""Fresh links for the speaker's clips in the Lounge (founder lock
2026-10-12, moment and feedback chat): a walk step stores the moment's
signed link, which dies after six hours. On every read the link is
signed again from the moment's own recording, but only for a recording
that belongs to the reader. Best-effort: anything unreadable keeps the
stored link, and the player shows its existing "unavailable".

The coach's word for a Take, in the same read (founder 2026-10-19, N80):
a coach bubble plays a video only while it is the word's current one,
from a fresh link; a removed or replaced video is never served again (the
file stays stored). One "Later · from your coach" bubble per word: a
bubble left by an older version is left out of the page (it stays in the
table). Each coach bubble carries ``unseen``, the server's "new" for that
word. This part fails closed: when the word cannot be read, coach videos
are hidden for that read and the words still show.
"""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class _SessionSnippets:
    """The database, with ``get_snippets_by_session`` served from one batch
    read of every Take on the page (light columns only). Anything else, and
    any session the batch could not read, goes to the database as before."""

    def __init__(self, database: Any, rows_by_session: dict):
        self._database = database
        self._rows = rows_by_session

    def get_snippets_by_session(self, session_id: str, **kwargs: Any) -> list:
        rows = self._rows.get(str(session_id))
        if rows is None or kwargs:
            return self._database.get_snippets_by_session(session_id, **kwargs)
        return rows

    def __getattr__(self, name: str) -> Any:
        return getattr(self._database, name)


def with_page_snippets(messages: list, database: Any) -> Any:
    """Read the recordings of every Take on this page in one go (founder
    2026-10-14: the Lounge took seven seconds reading each Take's pieces
    with their word timings, once for moment clips and again for the whole
    Take). Falls back to the plain database when the batch read fails."""
    sids: set = set()
    for m in messages or []:
        meta = m.get("metadata")
        if not isinstance(meta, dict):
            continue
        if m.get("kind") == "walk_step" and meta.get("take_session_id"):
            sids.add(str(meta["take_session_id"]))
        elif m.get("kind") == "recording_summary" and meta.get("session_id"):
            sids.add(str(meta["session_id"]))
    reader = getattr(database, "get_snippet_audio_rows_by_sessions", None)
    if not sids or not callable(reader):
        return database
    rows = reader(sorted(sids))
    return _SessionSnippets(database, rows) if isinstance(rows, dict) else database


def refresh_walk_clips(messages: list, user_id: str, database: Any,
                       resolve: Callable[[dict], Optional[str]]) -> None:
    """Re-sign `metadata.clip.src` in place on the reader's walk steps."""
    wanted: dict = {}
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "walk_step" else None
        clip = meta.get("clip") if isinstance(meta, dict) else None
        sid = meta.get("take_session_id") if isinstance(meta, dict) else None
        if isinstance(clip, dict) and clip.get("snippet_id") and sid:
            wanted.setdefault(str(sid), []).append(clip)
    for sid, clips in wanted.items():
        try:
            rows = {str(r.get("id")): r
                    for r in database.get_snippets_by_session(sid) or []
                    if str(r.get("user_id") or "") == str(user_id)}
        except Exception:
            logger.warning("lounge clips: snippets unreadable for %s", sid,
                           exc_info=True)
            continue
        for clip in clips:
            row = rows.get(str(clip["snippet_id"]))
            try:
                url = resolve(row) if row else None
            except Exception:
                logger.warning("lounge clips: could not sign %s",
                               clip["snippet_id"], exc_info=True)
                url = None
            if url and row:
                clip["src"] = url
                clip["start_ms"] = row.get("start_offset_ms")
                clip["duration_ms"] = row.get("duration_ms")


def _practice_allowed(user_id: str, database: Any) -> bool:
    """The practice page's own gates: the purpose is on, and this person's
    "Personalised practice" choice says yes (routes/phase2_guard.py)."""
    from services.processing_authorization import (
        ProcessingAuthorizationService,
    )
    from services.processing_purposes import purpose_is_operational

    if not purpose_is_operational("personalized_exercise_recommendation"):
        return False
    service = ProcessingAuthorizationService(database)
    principal = service.user_acquisition_principal(str(user_id))
    if not principal:
        return not service.enforced
    return bool(service.choice_permitted(principal, "personalised_practice"))


def refresh_practice_clips(messages: list, user_id: str, database: Any,
                           resolve: Callable[[Any], Optional[str]]) -> None:
    """Re-sign a practise try's clip in place, from the reader's own
    practice, behind the same gates as the practice page. The gates (three
    reads) and the practice reads run side by side; a clip is signed only
    once the gates said yes."""
    from services.parallel import run_in_parallel

    wanted: dict = {}
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "walk_step" else None
        clip = meta.get("clip") if isinstance(meta, dict) else None
        if isinstance(clip, dict) and clip.get("practice_id") and clip.get("attempt_id"):
            wanted.setdefault(str(clip["practice_id"]), []).append(clip)
    if not wanted:
        return

    def gate() -> bool:
        try:
            return bool(_practice_allowed(user_id, database))
        except Exception:
            logger.warning("lounge clips: practice gates unreadable", exc_info=True)
            return False

    def attempts(pid: str) -> dict:
        try:
            if not database.get_confident_voice_practice(pid, str(user_id)):
                return {}
            return {str(r.get("id")): r
                    for r in database.list_confident_voice_practice_attempts(pid) or []}
        except Exception:
            logger.warning("lounge clips: practice %s unreadable", pid,
                           exc_info=True)
            return {}

    def reads() -> dict:
        return {pid: attempts(pid) for pid in wanted}

    allowed, rows_by_practice = run_in_parallel(gate, reads)
    if not allowed:
        return
    for pid, clips in wanted.items():
        rows = rows_by_practice.get(pid) or {}
        for clip in clips:
            row = rows.get(str(clip["attempt_id"]))
            url = resolve(row.get("audio_ref")) if row else None
            if url:
                clip["src"] = url


def _arc_sessions_by_id(arcs: list, database: Any) -> dict:
    """{arc_id: takes} for the page's projects: one batch read when the
    repository offers it, else one read per project as before."""
    reader = getattr(getattr(database, "takes", None), "get_arc_sessions_many", None)
    if callable(reader):
        try:
            rows = reader(arcs)
        except Exception:
            logger.warning("lounge cards: batch deck read failed", exc_info=True)
            rows = None
        if isinstance(rows, dict):
            return rows
    return {arc: database.takes.get_arc_sessions(arc) or [] for arc in arcs}


def attach_card_decks(messages: list, user_id: str, database: Any) -> None:
    """The Ideal Text card (a review's end, or a Take's Ideal Text bubble)
    shows its project's first slide: each card gets `metadata.deck.presentation_ref`, a fresh link to
    the reader's own project's deck (null for a deckless project, whose
    card shows the default deck). Unowned or unreadable: no `deck`. Every
    project on the page is read in one go (founder 2026-10-18: one read per
    project, one after another)."""
    from services.coach_video_storage import refreshed_media_url
    from services.ideal_text_read import _deck_identity
    from services.project_ownership import session_actor_id

    cards: dict = {}
    for m in messages or []:
        # A review's card, or a Take's Ideal Text bubble drawn as the same
        # small card (founder 2026-10-14, one card per Take).
        meta = m.get("metadata") if m.get("kind") in ("walk_step", "ideal_text") else None
        if not isinstance(meta, dict):
            continue
        if m.get("kind") == "walk_step" and meta.get("step") != "end":
            continue
        arc = str(meta.get("arc_id") or "")
        if arc:
            cards.setdefault(arc, []).append(meta)
    if not cards:
        return
    try:
        by_arc = _arc_sessions_by_id(sorted(cards), database)
    except Exception:
        logger.warning("lounge cards: decks unreadable", exc_info=True)
        return
    for arc, metas in cards.items():
        try:
            sessions = by_arc.get(arc) or []
            owned = any(session_actor_id(s) == str(user_id) for s in sessions)
            if not owned:
                continue
            ref = _deck_identity(sessions)[0]
            deck = {"presentation_ref": refreshed_media_url(ref) if ref else None}
        except Exception:
            logger.warning("lounge cards: deck unreadable for %s", arc, exc_info=True)
            continue
        for meta in metas:
            meta["deck"] = deck


def attach_take_audio(messages: list, user_id: str, database: Any,
                      resolve: Callable[[Any], Optional[str]]) -> None:
    """The "Your Recording" bubble plays the whole Take, as a moment's clip
    plays its part: each gets `metadata.audio.src`, a fresh link to the
    reader's own recording. Unowned or unreadable: no `audio`."""
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "recording_summary" else None
        sid = meta.get("session_id") if isinstance(meta, dict) else None
        if not sid:
            continue
        try:
            rows = [r for r in database.get_snippets_by_session(str(sid)) or []
                    if str(r.get("user_id") or "") == str(user_id)
                    and r.get("audio_segment_path")]
            url = resolve(rows[0]["audio_segment_path"]) if rows else None
        except Exception:
            logger.warning("lounge takes: audio unreadable for %s", sid,
                           exc_info=True)
            url = None
        if url and isinstance(meta, dict):
            meta["audio"] = {"src": url}


def _take_id(value: Any) -> Optional[str]:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _upload_take(key: Optional[str]) -> Optional[str]:
    """The Take a coach's upload was made on, from its key
    (``coach-feedback/<Take>/…``, store_session_video); None otherwise."""
    head, _, rest = str(key or "").partition("/")
    return _take_id(rest.partition("/")[0]) if head == "coach-feedback" else None


def _coach_bubbles(messages: list) -> list[tuple[dict, dict, tuple]]:
    """(message, metadata, the Takes its word may be of, surest first) for
    every coach bubble on the page: the "Later · from your coach" bubbles
    and the walk's copies of the coach's word, on a UUID-shaped Take.

    A "Later" bubble names its word's Take (the server writes it). A walk
    copy names the Take the walk reviewed, which is a later one when the
    walk showed an earlier Take's word (N48.3 Q11 A, until N77 retired
    it). So a copy's word is looked for first on the Take it names as ``coach_take_session_id``,
    then on the Take its video was uploaded on, then on its own Take."""
    out = []
    for m in messages or []:
        meta = m.get("metadata") if m.get("kind") == "walk_step" else None
        if not (isinstance(meta, dict) and meta.get("step") == "coachnote"
                and meta.get("author") == "coach"):
            continue
        take = _take_id(meta.get("take_session_id"))
        if not take:
            continue
        takes = [take] if meta.get("coach_update") else [
            _take_id(meta.get("coach_take_session_id")),
            _upload_take(_video_key(meta.get("video"))), take]
        out.append((m, meta, tuple(dict.fromkeys(t for t in takes if t))))
    return out


_SUPABASE_OBJECT = re.compile(r"^/storage/v1/object/(?:sign|public|authenticated)/[^/]+/(.+)$")


def _video_key(ref: Any) -> Optional[str]:
    """The stored object behind a video link, whatever shape it was written
    in (an s3:// ref, a bare key, a signed link, a Supabase storage link
    where R2 is not set up); None for no video."""
    if not isinstance(ref, str) or not ref.strip():
        return None
    from urllib.parse import unquote, urlsplit
    from services.coach_video_storage import media_key_from_ref
    try:
        key = media_key_from_ref(ref)
        found = None if key else _SUPABASE_OBJECT.match(urlsplit(ref.strip()).path or "")
    except Exception:  # noqa: BLE001 -- an unreadable ref is compared as written
        key, found = None, None
    return key or (unquote(found.group(1)) if found else ref.strip().split("?", 1)[0])


def _words(text: Any) -> Optional[str]:
    return " ".join(str(text or "").split()) or None


def _bubble_words(body: Any) -> Optional[str]:
    """The coach's words in a bubble: what follows its "Your coach" line."""
    return _words(str(body or "").partition("\n")[2])


def _coach_word_reads(user_id: str, takes: list, database: Any) -> tuple[dict, dict]:
    """({Take: its shared words}, {Take: seen_at}) for the reader's own
    Takes among these. Raises when a read fails."""
    from services.parallel import run_in_parallel
    owned = sorted(database.list_owned_take_ids(str(user_id), takes) or [])
    if not owned:
        return {}, {}
    words, seen = run_in_parallel(
        lambda: database.list_shared_coach_take_words(owned) or [],
        lambda: database.list_coach_take_word_seen(str(user_id), owned) or {})
    by_take: dict = {take: [] for take in owned}
    for word in words:
        take = _take_id(word.get("take_session_id")) if isinstance(word, dict) else None
        if take in by_take and word.get("shared_at"):
            by_take[take].append(word)
    return ({t: w for t, w in by_take.items() if w},
            {_take_id(t) or str(t): at for t, at in dict(seen).items()})


def refresh_coach_words(messages: list, user_id: str, database: Any) -> set:
    """The coach bubbles' videos, current-ness and "new" (N80). Returns the
    client ids of the bubbles to leave out of the page; the caller filters,
    after every group of the read is done.

    On a Take of the reader's that has a shared word: a bubble whose video
    is one of the word's current videos gets a freshly signed link; any
    other coach video is None (D2). Every coach bubble gets ``unseen``
    (D4, D7). A "Later · from your coach" bubble whose words or video no
    longer match a shared word is left out (D1). The walk's own copies are
    never left out. Each bubble is judged by its own word's Take (see
    ``_coach_bubbles``). A Take the reader does not own is left untouched.
    Fails closed: when a read fails, every coach video goes and nothing
    is left out or marked."""
    from services.coach_feedback_signal import newer_than_seen, word_changed_at
    from services.coach_video_storage import refreshed_media_url

    bubbles = _coach_bubbles(messages)
    if not bubbles:
        return set()
    try:
        words, seen = _coach_word_reads(
            user_id, sorted({t for _, _, takes in bubbles for t in takes}), database)
    except Exception:
        logger.warning("lounge coach words unreadable: coach videos hidden", exc_info=True)
        for _, meta, _ in bubbles:
            if meta.get("video"):
                meta["video"] = None
        return set()
    hidden: set = set()
    for message, meta, takes in bubbles:
        take = next((t for t in takes if t in words), None)
        if take is None:
            continue  # no shared word (an older publish's note): as stored
        shared = words[take]
        videos = {_video_key(w.get("video_ref")): w.get("video_ref") for w in shared}
        key = _video_key(meta.get("video"))
        versions = {(_words(w.get("text")), _video_key(w.get("video_ref"))) for w in shared}
        older = (meta.get("coach_update")
                 and (_bubble_words(message.get("body")), key) not in versions)
        if older and message.get("client_id"):
            hidden.add(str(message["client_id"]))
            continue
        if key is not None:
            meta["video"] = refreshed_media_url(videos[key]) if videos.get(key) else None
        meta["unseen"] = newer_than_seen(word_changed_at(shared), seen.get(take))
    return hidden


def enrich_page(page: dict, user_id: str, database: Any, *,
                resolve_snippet: Callable[[dict], Optional[str]],
                resolve_ref: Callable[[Any], Optional[str]],
                with_flags: bool) -> None:
    """Everything the Lounge read adds to a page of messages: fresh clip,
    practice, deck and recording links, the coach's word (N80), and (newest
    page only) the Ideal Text bubble's "new". The reads are independent, so
    they run side by side (founder 2026-10-18, "optimise the loading time")
    instead of one after another; the slowest one, not their sum, sets the
    wait.

    Thread safety: each group writes keys no other group touches. Walk
    clips carry a ``snippet_id`` and practise clips a ``practice_id`` (never
    both), decks write ``deck`` on cards, recordings write ``audio`` on
    readouts, the coach's word writes ``video`` and ``unseen`` on coach
    bubbles, and the flags are a return value. Clips and recordings share
    one read of the page's Takes, so they stay in one group, in order. The
    bubbles an older version of a word left are taken out of the page only
    after every group is done, since the others walk the same list.
    """
    from services.parallel import run_in_parallel
    from services.request_context import lap

    messages = page.get("messages") or []

    def recordings() -> None:
        with lap("takes"):
            clips_db = with_page_snippets(messages, database)
        with lap("clips"):
            refresh_walk_clips(messages, user_id, clips_db, resolve_snippet)
        with lap("audio"):
            attach_take_audio(messages, user_id, clips_db, resolve_ref)

    def practice() -> None:
        with lap("practice"):
            refresh_practice_clips(messages, user_id, database, resolve_ref)

    def decks() -> None:
        with lap("decks"):
            attach_card_decks(messages, user_id, database)

    def flags() -> Optional[dict]:
        if not with_flags:
            return None
        # The Ideal Text bubble's "new" (D-FW-5, walk lock flow 1): one
        # yes/no per project, never a count; {} when it cannot be read.
        from services.coach_feedback_signal import lounge_flags
        with lap("flags"):
            return lounge_flags(database, user_id)

    def coach_words() -> set:
        with lap("coach_words"):
            return refresh_coach_words(messages, user_id, database)

    _, _, _, fresh, older = run_in_parallel(recordings, practice, decks, flags,
                                            coach_words)
    if older:
        page["messages"] = [m for m in messages
                            if str(m.get("client_id") or "") not in older]
    if fresh is not None:
        page["new_coach_feedback"] = fresh
