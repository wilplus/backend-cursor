"""The history behind a Paragraph's bookmark (contract 16, founder 2026-09-25).

Clicking a bookmark never opens an empty screen: it shows how this Slide's
words changed Take by Take, which helper words were locked when, and which
practised passages were adopted into it (contract 29a). Every
Take rewrites the Slides it spoke (contract 8), so the history is read per
Slide from the version snapshots, each of which keeps its Slide map.

Words only — no score, rank or verdict (AC-9). A version whose snapshot has
no Slide map (written before 2026-09-25) is left out rather than guessed.

AN ACCEPTED CORRECTION IS ITS OWN ROW (founder 2026-10-05, N48.1; coach-panel
lock C11, "labelled 'Correction accepted'"). The snapshots are written only
when a Take is finalized, so an accepted rewrite never reached them and the
next Take's snapshot hid it. Its Paragraph revision is named
'accepted_rewrite' (0421); those revisions are merged among the Take rows by
time as rows of kind "accepted_correction", holding the Paragraph's words.
Revisions written before 0421 carry no name and are not guessed.
"""
from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Optional

_PARA = "\n\n"

TAKE = "take"
ACCEPTED_CORRECTION = "accepted_correction"


def _slide_paragraphs(version: Mapping, slide_index: int) -> Optional[list]:
    """This Slide's Paragraph texts in one version, or None if unprovable."""
    doc = version.get("document")
    text = version.get("text")
    if not isinstance(doc, Mapping) or not isinstance(text, str):
        return None
    paragraphs = doc.get("paragraphs")
    blocks = text.split(_PARA)
    if not isinstance(paragraphs, list) or len(paragraphs) != len(blocks):
        return None
    return [block for block, para in zip(blocks, paragraphs)
            if isinstance(para, Mapping)
            and para.get("slide_index") == slide_index]


def _take_index(version: Mapping) -> Optional[int]:
    """The Take whose words this version holds, when its snapshot says so —
    the answered bookmark labels each version "Take N" (Q21 A)."""
    doc = version.get("document")
    value = doc.get("take_index") if isinstance(doc, Mapping) else None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def slide_history(versions: Any, helper_log: Any, slide_index: int,
                  adoptions: Any = None) -> dict:
    """Versions where this Slide's words changed, and its helper-word sets.

    Consecutive versions with identical words collapse into the first: a Take
    that did not speak this Slide adds nothing to its history."""
    out_versions: list = []
    last: Optional[list] = None
    for row in versions or []:
        if not isinstance(row, Mapping):
            continue
        words = _slide_paragraphs(row, slide_index)
        if not words or words == last:
            continue
        out_versions.append({
            "kind": TAKE,
            "version": row.get("version"),
            "take_index": _take_index(row),
            "paragraphs": words,
            "at": row.get("created_at"),
        })
        last = words
    helper_words = [
        {"phrases": list(r.get("phrases") or []), "at": r.get("created_at")}
        for r in helper_log or [] if isinstance(r, Mapping)
    ]
    practice = [
        {"before": r.get("before_text"), "after": r.get("after_text"),
         "at": r.get("created_at")}
        for r in adoptions or [] if isinstance(r, Mapping)
    ]
    return {"slide_index": slide_index, "versions": out_versions,
            "helper_words": helper_words, "practice": practice}


def _when(value: Any) -> Optional[datetime]:
    """A row's time, or None when it cannot be read. A time without a zone
    is UTC, as the database writes it."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def with_accepted_corrections(versions: list, revisions: Any) -> list:
    """The Take rows with the Paragraph's accepted corrections merged in by
    time. Pure.

    Each correction goes before the first Take row written after it; Take
    rows keep their order. A correction with no words or no readable time is
    left out rather than placed by guess."""
    out = list(versions)
    for row in revisions or []:
        if not isinstance(row, Mapping):
            continue
        text = row.get("text")
        when = _when(row.get("created_at"))
        if not isinstance(text, str) or not text.strip() or when is None:
            continue
        at = len(out)
        for index, existing in enumerate(out):
            existing_when = _when(existing.get("at"))
            if existing_when is not None and existing_when > when:
                at = index
                break
        out.insert(at, {"kind": ACCEPTED_CORRECTION, "version": None,
                        "take_index": None, "paragraphs": [text],
                        "at": row.get("created_at")})
    return out


def history_for_part(database: Any, arc_id: str, user_id: str,
                     part_id: str) -> Optional[dict]:
    """The bookmark's history: resolve the Paragraph's Slide, then read.

    None when the Slide cannot be proven from the published document."""
    from services.slide_helper_words import slide_of_part

    slide = slide_of_part(
        database.get_ideal_text_document_core(arc_id, user_id), part_id)
    if slide is None:
        return None
    history = slide_history(
        database.list_ideal_text_versions(arc_id),
        database.list_slide_helper_words_log(arc_id, user_id, slide),
        slide,
        database.list_practice_adoptions(arc_id, user_id, slide))
    history["versions"] = with_accepted_corrections(
        history["versions"],
        database.list_accepted_rewrite_revisions(arc_id, user_id, part_id))
    return history


def _slide_clip(database: Any, session_id: str, slide_index: int,
                resolve_url: Any) -> Optional[dict]:
    """The Take's own audio for this Slide: from its first piece on the Slide
    to the end of its last, when they share one recording file; else the
    first piece alone. None when nothing on the Slide can play."""
    from services.transcript_document import _slide_corrections, _slide_of

    fixes = _slide_corrections(database, session_id)
    pieces = sorted(
        (s for s in database.get_snippets_by_session(session_id) or []
         if isinstance(s, Mapping) and _slide_of(s, fixes) == slide_index),
        key=lambda s: s.get("start_offset_ms") or 0)
    if not pieces:
        return None
    first, last = pieces[0], pieces[-1]
    url = resolve_url(first)
    if not url:
        return None
    start = int(first.get("start_offset_ms") or 0)
    duration = int(first.get("duration_ms") or 0)
    if len(pieces) > 1 and resolve_url(last) == url:
        duration = max(duration, int(last.get("start_offset_ms") or 0)
                       + int(last.get("duration_ms") or 0) - start)
    return {"snippet_audio_ref": url, "start_offset_ms": start,
            "duration_ms": duration,
            "snippet_ids": [str(s.get("id")) for s in pieces if s.get("id")]}


def _slide_answer(database: Any, session_id: str, user_id: str,
                  snippet_ids: list) -> Optional[str]:
    """The owner's own latest Confident Voice answer on this Slide's clips in
    that Take -- their self-report, shown back to them only. None when they
    did not answer there."""
    wanted = set(snippet_ids)
    answer = None
    for row in database.list_take_feedback_self_reports(
            session_id, user_id) or []:
        if (isinstance(row, Mapping)
                and row.get("feedback_family") == "confident_voice"
                and str(row.get("snippet_id") or "") in wanted
                and row.get("response")):
            answer = str(row["response"])
    return answer


def with_earlier_take_details(database: Any, arc_id: str, user_id: str,
                              history: dict, resolve_url: Any) -> dict:
    """Each version row gains its Take's recording for this Slide and the
    owner's answer on it (founder 2026-09-28, decision 5: the Earlier Takes
    rows carry an answer and a player, as the accepted Take stack shows).

    Best-effort per row: a Take whose audio or answer cannot be read keeps
    its words and simply shows no player or answer."""
    slide = history.get("slide_index")
    if not isinstance(slide, int):
        return history
    sessions = {
        row.get("take_index"): str(row.get("id"))
        for row in database.takes.get_arc_sessions(arc_id) or []
        if isinstance(row, Mapping) and row.get("id")
        and row.get("recording_kind") != "read"
        and not row.get("paired_session_id")
    }
    for version in history.get("versions") or []:
        if version.get("kind") == ACCEPTED_CORRECTION:
            continue  # a correction is no Take: no recording, no answer
        session_id = sessions.get(version.get("take_index"))
        if not session_id:
            continue
        version["take_session_id"] = session_id
        try:
            clip = _slide_clip(database, session_id, slide, resolve_url)
        except Exception:
            clip = None
        if clip is None:
            continue
        snippet_ids = clip.pop("snippet_ids")
        version["clip"] = clip
        try:
            version["answer"] = _slide_answer(
                database, session_id, user_id, snippet_ids)
        except Exception:
            version["answer"] = None
    return history


# ── Several Paragraphs at once (F5, founder 2026-10-08) ───────────────────

#: The reads a Paragraph's history makes that other Paragraphs of the same
#: document share. Each is made once per batch; everything else passes
#: through untouched.
_SHARED_READS = frozenset({
    "get_ideal_text_document_core", "list_ideal_text_versions",
    "list_slide_helper_words_log", "list_practice_adoptions",
    "list_accepted_rewrite_revisions", "get_snippet_slide_corrections",
    "get_snippets_by_session", "list_take_feedback_self_reports",
})

#: The most Paragraphs one request may name.
MAX_BATCH_PARTS = 200


def _key(name: str, args: tuple, kwargs: Mapping) -> tuple:
    return (name, args, tuple(sorted(kwargs.items())))


class _OnceTakes:
    """``database.takes`` with ``get_arc_sessions`` read once."""

    def __init__(self, takes: Any, memo: dict):
        self._takes = takes
        self._memo = memo

    def get_arc_sessions(self, *args: Any, **kwargs: Any) -> Any:
        key = _key("takes.get_arc_sessions", args, kwargs)
        if key not in self._memo:
            self._memo[key] = self._takes.get_arc_sessions(*args, **kwargs)
        return deepcopy(self._memo[key])

    def __getattr__(self, name: str) -> Any:
        return getattr(self._takes, name)


class BatchedHistoryReads:
    """The database as one document's Paragraph histories read it, with every
    shared read made once for the whole batch.

    NOT A SECOND IMPLEMENTATION. Each Paragraph is still assembled by
    `history_for_part` and `with_earlier_take_details`, exactly as the single
    endpoint assembles it; only the reads underneath are shared. Every value
    handed out is a copy, so one Paragraph's assembly can never change what
    the next one reads, and each body is the single endpoint's body.
    """

    def __init__(self, database: Any, arc_id: str, user_id: str,
                 arc_sessions: Any = None):
        self._database = database
        self._arc_id = arc_id
        self._user_id = user_id
        self._memo: dict = {}
        self.takes = _OnceTakes(database.takes, self._memo)
        if arc_sessions is not None:
            self._memo[_key("takes.get_arc_sessions", (arc_id,), {})] = \
                arc_sessions

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._database, name)
        if name not in _SHARED_READS:
            return attr

        def once(*args: Any, **kwargs: Any) -> Any:
            key = _key(name, args, kwargs)
            if key not in self._memo:
                self._memo[key] = attr(*args, **kwargs)
            return deepcopy(self._memo[key])

        return once

    def core(self) -> Any:
        """The published document core, as `history_for_part` reads it."""
        return self.get_ideal_text_document_core(self._arc_id, self._user_id)

    def _seed(self, name: str, args: tuple, value: Any) -> None:
        self._memo[_key(name, args, {})] = value

    def prefetch(self, part_ids: list) -> None:
        """Read the per-Slide and per-Paragraph rows for every named
        Paragraph in one read each. A batched read that fails seeds nothing,
        and the per-Slide or per-Paragraph read then runs as it always has."""
        from services.slide_helper_words import slide_of_part

        core = self.core()
        slide_by_part = {part_id: slide_of_part(core, part_id)
                         for part_id in part_ids}
        slides = sorted({s for s in slide_by_part.values() if s is not None})
        arc, user = self._arc_id, self._user_id
        if slides:
            for name, batched in (
                    ("list_slide_helper_words_log",
                     "list_slide_helper_words_log_for_slides"),
                    ("list_practice_adoptions",
                     "list_practice_adoptions_for_slides")):
                rows = getattr(self._database, batched)(arc, user, slides)
                if isinstance(rows, Mapping):
                    for slide in slides:
                        if slide in rows:
                            self._seed(name, (arc, user, slide), rows[slide])
        resolved = [p for p, s in slide_by_part.items() if s is not None]
        revisions = (self._database.list_accepted_rewrite_revisions_for_parts(
            arc, user, resolved) if resolved else None)
        if isinstance(revisions, Mapping):
            for part_id in resolved:
                rows = revisions.get(str(part_id).lower())
                if rows is not None:
                    self._seed("list_accepted_rewrite_revisions",
                               (arc, user, part_id), rows)


def requested_part_ids(raw: Any, core: Any) -> list:
    """The Paragraphs a batch asks for: ``?part_ids=a,b,c`` in the order
    given without repeats, else every Paragraph of the published core."""
    if isinstance(raw, str) and raw.strip():
        seen: list = []
        for part_id in (p.strip() for p in raw.split(",")):
            if part_id and part_id not in seen:
                seen.append(part_id)
        return seen[:MAX_BATCH_PARTS]
    payload = core.get("payload") if isinstance(core, Mapping) else None
    parts = payload.get("parts") if isinstance(payload, Mapping) else None
    return [str(p["id"]) for p in parts or []
            if isinstance(p, Mapping) and p.get("id")][:MAX_BATCH_PARTS]


def once_per_snippet(resolve_url: Any) -> Any:
    """``resolve_url`` asked once per snippet for the whole batch."""
    resolved: dict = {}

    def resolve(snippet: Any) -> Any:
        key = str(snippet.get("id")) if isinstance(snippet, Mapping) \
            and snippet.get("id") else None
        if key is None:
            return resolve_url(snippet)
        if key not in resolved:
            resolved[key] = resolve_url(snippet)
        return resolved[key]

    return resolve
