"""Bounded, independently failing Ideal Text enrichment sections."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from contextvars import copy_context
from dataclasses import dataclass
from time import perf_counter
from typing import Any, Callable, Iterable, Mapping, Optional


#  HOW LONG A SECTION GETS, AND WHY THESE TWO NUMBERS DIFFER SO MUCH
#
#  FOUNDER, 2026-09-20: "no bookmarks" — on a document whose Manager work had
#  provably succeeded. The deck was drawing its reserved slots (the grey
#  circles it shows while feedback is still coming) on every paragraph, which
#  the frontend only does while the server is STILL answering `retryable`. It
#  answered that eight times across ninety seconds.
#
#  The focused retry had EIGHT seconds to do work that measurably takes twenty
#  to forty: when this same block was briefly computed inside `publish_for_arc`
#  (#580, reverted), production publication went from about a second to 22 and
#  42. That is the Manager over a six-paragraph document.
#
#  A reader given eight seconds to do forty seconds of work is detached every
#  single time — and `run_sections` cannot kill a running thread, so the work
#  then FINISHES and claims its feedback set with nobody listening. That is why
#  a claimed set existed at 15:54:36 for a take that showed nothing, and why a
#  three-paragraph document worked this morning while a six-paragraph one did
#  not. Nothing regressed; the document got longer.
#
#  THE COLD OPEN STAYS TIGHT. It is the first paint and it must not wait: a
#  section that cannot answer in two seconds reports `retryable` and the words
#  go on screen without it. Only the retry — which the client makes precisely
#  because the server asked to be asked again — gets room to finish.
#
#  Sixty would suit the Manager and not the proxy in front of us, so the retry
#  budget is deliberately short of that: past a normal request ceiling we would
#  be trading one silent failure for another. The real fix is to compute this
#  at the end of the pipeline, where no request is waiting on it (task #43).
COLD_OPEN_BUDGET_SECONDS = 2.0
FOCUSED_RETRY_BUDGET_SECONDS = 30.0

#: The sections whose work is measurably slower than the cold open allows, and
#: which therefore earn the long budget WHENEVER they are asked for — not only
#: on a retry (founder 2026-09-22: "can you do something to make loading of the
#: bookmarks faster? cause it is really long").
#:
#: THE SECOND ROUND TRIP WAS PURE WASTE. The budget used to be chosen by
#: whether the caller named any sections at all, so a first open asked for
#: everything, spent two seconds, gave up on the Manager, and only then asked
#: again with room to finish. The Manager measurably takes about four and a
#: half seconds, so the speaker paid two seconds of certain failure plus a
#: hop before the real work even started.
#:
#: Choosing by WHICH sections are asked for lets the page open two lanes at
#: once: the marks on their own with the long budget, and everything the page
#: renders around them on the tight one. Neither can hold the other up, which
#: the single-response shape could never express — one response has one
#: deadline.
SLOW_SECTIONS = frozenset({"document_layers"})


def budget_for(requested: Iterable[str]) -> float:
    """How long this request may spend, decided by what it asks for."""
    return (
        FOCUSED_RETRY_BUDGET_SECONDS
        if SLOW_SECTIONS & set(requested)
        else COLD_OPEN_BUDGET_SECONDS
    )


class SectionPending(Exception):
    """A reader that knows its answer is on its way but not yet here: the
    section goes out `pending`/`retryable` (ASK ME AGAIN), exactly as a reader
    that ran out of budget does, without the reader having to run out of it.
    `changes_block_for` raises it when the bake it is waiting for is still in
    flight at the request's deadline."""


@dataclass(frozen=True)
class EnrichmentSection:
    status: str
    data: Any = None
    retryable: bool = False

    def wire(self) -> dict[str, Any]:
        result: dict[str, Any] = {"status": self.status}
        if self.data is not None:
            result["data"] = self.data
        if self.retryable:
            result["retryable"] = True
        return result


def run_sections(
    readers: Mapping[str, Callable[[], Any]], *, timeout_seconds: float = 2.0,
) -> tuple[dict[str, dict[str, Any]], dict[str, float]]:
    """Run typed readers concurrently; one timeout/failure owns one section."""
    if not readers:
        return {}, {}
    started = perf_counter()
    sections: dict[str, dict[str, Any]] = {}
    timings: dict[str, float] = {}

    def timed(name: str, reader: Callable[[], Any]) -> Callable[[], Any]:
        # A section's lap is ITS OWN wall time, measured in its thread. The
        # collection loop below waits for the sections one after another, so
        # a wait measured there is only the part of a section that outlived
        # the ones collected before it (founder's stopwatch, 2026-10-18: six
        # concurrent sections read as a staircase that summed to the whole).
        def run() -> Any:
            section_started = perf_counter()
            try:
                return reader()
            finally:
                timings[name] = (perf_counter() - section_started) * 1000
        return run

    pool = ThreadPoolExecutor(max_workers=min(8, len(readers)),
                              thread_name_prefix="ideal-enrichment")
    try:
        # Each reader keeps the request's context (its own copy: one Context
        # cannot be entered by two threads), so the stopwatch counts the
        # sections' database calls and names their laps.
        futures = {name: pool.submit(copy_context().run, timed(name, reader))
                   for name, reader in readers.items()}
        for name, future in futures.items():
            remaining = max(0.001, timeout_seconds - (perf_counter() - started))
            try:
                data = future.result(timeout=remaining)
                sections[name] = EnrichmentSection("ready", data).wire()
            except TimeoutError:
                future.cancel()
                sections[name] = EnrichmentSection(
                    "pending", retryable=True).wire()
            except SectionPending:
                sections[name] = EnrichmentSection(
                    "pending", retryable=True).wire()
            except Exception:
                sections[name] = EnrichmentSection(
                    "failed", retryable=True).wire()
            # A section still running at the deadline has no lap of its own
            # yet; what it cost this response is the budget it was given.
            timings.setdefault(name, (perf_counter() - started) * 1000)
    finally:
        # A timed-out optional reader must not keep the HTTP response open.
        # Running calls cannot be killed by Python, but they are detached from
        # this response and their result is discarded.
        pool.shutdown(wait=False, cancel_futures=True)
    return sections, timings



# ── The enrichment request (GET /explore/arc/<arc_id>/ideal-text/enrichment)
#
# Moved out of ``routes.v2.explore_ideal_text`` unchanged (founder
# 2026-10-12). The route keeps the ownership gate, the timing headers and the
# two generation-fenced snapshot checks; this builds what sits between them.

ALLOWED_SECTIONS = frozenset({
    "feedback", "document_layers", "notes", "history", "journey",
    "entitlement", "learning",
})


#: The sections whose answer carries a presentation acknowledgement token (and
#: writes to get it): `learning` directly, `document_layers` through the
#: Manager's learning packets and feedback claims. A ready answer from either
#: must pass the post-read generation fence before it leaves the server.
FENCED_SECTIONS = frozenset({"learning", "document_layers"})


def requested_sections(raw: str) -> tuple[set, list]:
    """(the sections asked for, the unknown ones sorted). An empty ask is
    every section."""
    requested = (
        {value.strip() for value in raw.split(",") if value.strip()}
        if raw else set(ALLOWED_SECTIONS)
    )
    return requested, sorted(requested - ALLOWED_SECTIONS)


def stale_snapshot(current: Any, selected: Mapping[str, Any]) -> Any:
    """The 409 body when ``selected`` is no longer the current head, else
    None. The generation-fenced core read treats a head invalidated by a
    source mutation as stale immediately."""
    if current and str(current.get("id")) == str(selected.get("id")):
        return None
    return {
        "code": "SNAPSHOT_STALE",
        "current_document_snapshot_id": (
            str(current.get("id")) if current else None),
    }


@dataclass(frozen=True)
class EnrichmentDeps:
    """The route's helpers the sections bind to (looked up per request)."""

    optional_read: Callable
    explanations_map: Callable
    playback_map: Callable
    reference_map: Callable
    moments_entitled: Callable
    price_of: Callable


def _feedback_section(database, arc_id, seed, moments, take_ids, deps):
    from services.ideal_text_notebook import confidence_review_status_map
    from services.ideal_text_read import decorate_key_moments
    explanations = deps.optional_read(
        "moment_explanations", {}, lambda: deps.explanations_map(take_ids))
    playback = deps.optional_read(
        "moment_playback", {}, lambda: deps.playback_map(take_ids))
    review = deps.optional_read(
        "confidence_review_status", {},
        lambda: confidence_review_status_map(database, arc_id, moments))
    references = deps.optional_read(
        "moment_references", {},
        lambda: deps.reference_map([
            value.get("reference_post_slug")
            if isinstance(value, dict) else None
            for value in explanations.values()
        ]))
    return {
        "key_moments": decorate_key_moments(
            moments,
            suggestions_enabled=bool(seed.get("suggestions_enabled")),
            explanations=explanations, playback=playback,
            review_status=review, references=references,
        ),
        "explanations_available": bool(explanations),
    }


def _document_layers_section(database, arc_id, actor_id, snapshot_id, seed, core):
    prior = seed.get("prior_edit") if isinstance(seed, dict) else None
    result = {"prior_edit": prior}
    # The publish-boundary bake when it is provably the same answer, else
    # computed live — see `services.ideal_text_feedback_bake`.
    from services.ideal_text_feedback_bake import changes_block_for
    result.update(changes_block_for(database, arc_id, actor_id, snapshot_id, core))
    return result


def _learning_section(database, arc_id, actor_id, sessions, core):
    latest_id = str(core.get("latest_take_session_id") or "")
    latest = next((row for row in sessions
                   if str(row.get("id") or "") == latest_id), None)
    if not isinstance(latest, dict):
        return {"learning_exposure": None}
    from services.learning_exposures import prepare_ideal_text_presentation
    handle = prepare_ideal_text_presentation(
        database=database,
        owner_principal_id=str(latest.get("owner_principal_id") or ""),
        project_id=str(latest.get("project_id") or arc_id),
        take_id=latest_id, actor_id=actor_id,
        text=str(core.get("text") or ""), version=core.get("version"),
        take_count=core.get("take_count"), title=core.get("title"),
        parts=core.get("parts"), delivery_mode="canary",
    )
    return {"learning_exposure": handle}


def section_readers(database, *, arc_id: str, actor_id: str, sessions: list,
                    selected: Mapping[str, Any], snapshot_id: str,
                    deps: EnrichmentDeps,
                    coach_take: Optional[str] = None) -> dict[str, Callable[[], Any]]:
    """Every section's reader, bound to one immutable document snapshot.

    ``coach_take`` is the Take a coach's link names (``?take=``, founder
    2026-10-21, N77): the journey section then serves that Take's word, when
    it is one of the caller's own Takes of this project. Without it, the
    Take on screen's."""
    core = selected.get("payload") or {}
    seed = selected.get("enrichment_seed") or {}
    moments = seed.get("moments") if isinstance(seed, dict) else []
    moments = moments if isinstance(moments, list) else []
    take_ids = [moment.get("take_session_id") for moment in moments
                if isinstance(moment, dict)]
    take_count = int(core.get("take_count") or 0)

    def journey():
        from services.coach_message_read import journey_payload, word_take
        return journey_payload(database, actor_id, arc_id, take_count, sessions,
                               word_take(sessions, actor_id, coach_take,
                                         core.get("latest_take_session_id")))

    return {
        "feedback": lambda: _feedback_section(
            database, arc_id, seed, moments, take_ids, deps),
        "document_layers": lambda: _document_layers_section(
            database, arc_id, actor_id, snapshot_id, seed, core),
        "notes": lambda: {
            "notes_text": database.get_user_arc_ideal_notes(arc_id, actor_id)},
        "history": lambda: {
            "decision_history": database.list_intervention_decision_history(arc_id)},
        "journey": journey,
        "entitlement": lambda: {
            "moments_unlocked": deps.moments_entitled(arc_id),
            "price_tokens": deps.price_of("moment_explanation"),
        },
        "learning": lambda: _learning_section(database, arc_id, actor_id, sessions, core),
    }
