"""Compute the Manager's block at the write boundary, not on the read.

FOUNDER, 2026-09-20: "it's unacceptable that we open the ideal text after the
processing and there are no bookmarks. There need to be bookmarks right away
the moment we see it. Otherwise, that makes no sense because people will
quit."

The bookmarks were never stored. ``document_layers`` ran the whole ~20-stage
Manager pipeline on every GET, so they were COMPUTED when the document opened
rather than read, and no client retry budget can make a computation instant.

This module runs that same computation once, as its own queued job at the end
of the analysis run, and stores the result against the immutable snapshot it
was computed over. The read then serves it.

WHERE IT RUNS IS THE WHOLE DESIGN, and getting it wrong is what broke
production once already. It is not on the publish (#580: seven callers,
including Take 1 document creation, paid a 20-40s Manager run) and it is not
on the wait screen (that only moves the delay). It is after the run returns,
on the queue, where the only thing it can make slower is itself.

THREE THINGS IT DELIBERATELY IS NOT.

It is not a second implementation. It calls the exact function the route
calls, so there is one Manager and one arbitration; only the moment changes.
A parallel "fast path" that could disagree with the real one is how a product
ends up with two answers and no way to tell which is true.

It is not required. Every failure here returns quietly and the next reader
computes live, which is what every reader did before this existed. A bake
must never be able to fail a publish or delay the loop.

It is not a document cache. The words, their order and Ideal Text itself are
untouched (L1); the Manager still arbitrates (L2); no provenance moves (L3).
"""
from __future__ import annotations

import logging
from typing import Any, Mapping

logger = logging.getLogger(__name__)

BAKE_TASK_PATH = "services.ideal_text_feedback_bake.run_pending_bake"


def _bake_enabled() -> bool:
    """Is the publish-boundary bake switched on?

    A named predicate, like `_living_transcript_enabled` and
    `_suggestions_enabled` next door, rather than a `Config()` read at the
    call site. That is not style: other modules reload `config`, so a late
    `from config import Config` can resolve to a different class object than
    the one a caller or a test is holding — which is exactly how this failed
    in the full suite while passing on its own.
    """
    from config import Config
    return bool(Config().IDEAL_TEXT_FEEDBACK_BAKE_ENABLED)


def _snapshot_id_of(result: Any) -> str:
    """The published snapshot's id, or "" when the shape is not one."""
    if not isinstance(result, Mapping):
        return ""
    value = result.get("id") or result.get("snapshot_id")
    return str(value) if value else ""


def changes_block_for(
    database: Any, arc_id: str, actor_id: str, document_snapshot_id: str,
    core: Mapping[str, Any],
) -> dict:
    """The feedback block for one open document: stored if it can be, else live.

    HERE RATHER THAN IN THE ROUTE, and not only because the route fence said
    so. `v2_explore_get_ideal_text_enrichment` is grandfathered at 172 lines
    and five database calls precisely because a read endpoint that keeps
    growing a branch at a time is how the cold open became slow enough to need
    this fix. The decision is one sentence — serve the bake when it is provably
    the same answer, otherwise compute — and it belongs next to the writer that
    makes the bake, where the two can be read together.

    A MISS IS NEVER A FAILURE. `read_ideal_text_feedback_bake` returns None for
    an absent function, an absent row, a different snapshot, or any write to
    the mutable feedback surface since the bake was made. Every one of those
    falls through to the live computation, which is what every reader did
    before this existed, so the fast path can only be taken when it is safe.
    """
    # THE FLAG GATES THE READ TOO, and leaving it off the read was the defect
    # that kept the regression alive after #584 (founder: "No bookmarks",
    # after the bake was already switched off).
    #
    # #583 stopped new empty blocks being stored and #584 stopped the bake
    # running at all — but a row written in the window between #580 and those
    # fixes is still sitting in the table, and this function was still
    # serving it. Turning a writer off does nothing about what it already
    # wrote. A switch that silences the cause and keeps serving its damage is
    # not a switch.
    #
    # So when the bake is off, the stored answer does not exist as far as
    # this read is concerned: it computes live, which is what every reader
    # did before #580. That also makes the flag a true rollback rather than
    # a half one, and means a poisoned row cannot outlive the feature.
    baked = (
        database.read_ideal_text_feedback_bake(
            str(arc_id), str(actor_id), str(document_snapshot_id or ""))
        if _bake_enabled() else None
    )
    if isinstance(baked, dict) and baked:
        return baked
    from routes.v2.explore_ideal_text import _tracked_changes_block
    return _tracked_changes_block(
        str(arc_id), str(core.get("text") or ""), str(actor_id),
        str(core.get("latest_take_session_id") or ""),
        review_version=core.get("version"))


def enqueue_bake(arc_id: Any, actor_id: Any, recording_kind: Any) -> bool:
    """Ask for one bake, off the critical path. Never raises, never waits.

    THE WHOLE POINT OF #43 IS THIS FUNCTION'S RETURN BEING INSTANT. The bake
    computes the Manager over the whole document, which measurably takes 20 to
    40 seconds; the only safe way to spend that is where nothing is waiting.
    A queued job is the one placement that is true of. The two alternatives
    were both worse:

    * inside the run, synchronously — honest, but it adds those seconds to the
      wait screen, so the speaker waits either way and we have moved the delay
      rather than removed it;
    * a detached thread — which is precisely the bug #586 fixed. Work with
      nobody listening finishes anyway and its side effects land unobserved.

    A false return is not a failure. No broker (dev, tests, a Redis outage)
    means no bake, and every reader computes live exactly as it did before any
    of this existed.

    EVERY CONDITION LIVES HERE rather than at the call site, including the
    spoken-take one, which the worker knows and this module does not. The
    caller is a single unbranched line at the end of the analysis run: partly
    because that function is grandfathered against the complexity ratchet at
    CC 31, and mostly because "is this worth baking" is one question and
    answering half of it in the worker is how the halves drift apart.

    ONLY A SPOKEN TAKE. A re-read is not a take (founder bug 2026-07-20) and
    produces no new feedback to bake; a practice clip is not this document at
    all. Baking on either would spend the Manager to store what is already
    stored, and on a document neither of them changed.
    """
    if recording_kind != "spoken":
        return False
    arc = str(arc_id or "")
    actor = str(actor_id or "")
    if not _bake_enabled() or not arc or not actor:
        return False
    try:
        from services import job_queue
        if not job_queue.queue_configured():
            return False
        return job_queue.enqueue(
            BAKE_TASK_PATH, arc, actor,
            # One pending bake per document. A second take landing while the
            # first bake is queued replaces it rather than stacking, and the
            # job reads the head when it runs, so the survivor is always the
            # one that bakes the current document.
            rq_job_id=f"ideal-text-bake:{arc_id}:{actor_id}",
        )
    except Exception as error:
        logger.warning("ideal-text feedback bake not enqueued arc=%s: %s",
                       arc_id, error)
        return False


def run_pending_bake(arc_id: str, actor_id: str) -> None:
    """RQ entry point. Bakes the head as it stands when the job runs.

    It reads the head rather than trusting a snapshot id handed over the wire,
    for the same reason `run_pending_publication` re-reads the generation: by
    the time a queued job runs the document may have moved, and a bake for a
    superseded snapshot is dead on arrival — `read_ideal_text_feedback_bake`
    would decline it on snapshot id at every future read.

    It never raises. A failed RQ job is a red mark on a dashboard for work
    that is optional by construction.
    """
    try:
        from services.db import db
        head = db.get_ideal_text_document_snapshot(str(arc_id), str(actor_id))
        if head is None:
            return
        bake_for_snapshot(db, str(arc_id), str(actor_id), head)
    except Exception as error:
        logger.warning("ideal-text feedback bake job failed arc=%s: %s",
                       arc_id, error)


def bake_for_snapshot(
    database: Any, arc_id: str, actor_id: str, published: Any,
) -> bool:
    """Compute and store the feedback block for one published head.

    Call this AFTER the publish, never before. V3's source-snapshot RPC binds
    on ``surface = served_text`` against the CURRENT published snapshot, so a
    block computed before publication is a block V3 declines outright
    (``source_snapshot_does_not_match_served_text``) — the bake would store an
    empty answer and the user would see no bookmarks at all, which is the
    exact defect this exists to end.

    Since #587 the only production caller is :func:`run_pending_bake`, which
    reaches here from the queue at the end of an analysis run. It is no longer
    reachable from `publish_for_arc`, and that is deliberate — see the note
    left at the line it used to occupy.
    """
    if not _bake_enabled():
        return False
    snapshot_id = _snapshot_id_of(published)
    if not arc_id or not actor_id or not snapshot_id:
        return False
    payload = published.get("payload") if isinstance(published, Mapping) else None
    served_text = str((payload or {}).get("text") or "")
    take_session_id = str((payload or {}).get("latest_take_session_id") or "")
    version = (payload or {}).get("version")
    if not served_text or not take_session_id:
        return False
    try:
        # LATE IMPORT, and the direction is on purpose. `_tracked_changes_block`
        # is where the Manager's dependencies are assembled — the moment maps,
        # the previous-take lookup, the locked parts, the evidence coordinates,
        # the experiment arms — and assembling a second copy here is how the
        # two would drift. It touches no Flask request state, so it runs just
        # as well inside the worker as inside a GET.
        from routes.v2.explore_ideal_text import _tracked_changes_block
        block = _tracked_changes_block(
            str(arc_id), served_text, str(actor_id), take_session_id,
            review_version=version,
        )
    except Exception as error:
        logger.warning("ideal-text feedback bake compute failed arc=%s: %s",
                       arc_id, error)
        return False
    if not isinstance(block, dict) or not block.get("changes"):
        # AN EMPTY LANE IS NOT A BAKE (founder, 2026-09-20, on the first take
        # after this shipped: "I just recorded and none of the bookmarks
        # appeared").
        #
        # `not block` was the wrong guard and it cost him his marks.
        # `build_changes_block` returns `{"changes": [], ...}` when the
        # Manager has nothing to say AT THIS MOMENT — a truthy dict with
        # nothing in it — and this moment is during assembly:
        # `ideal_text_confirmation` runs at analysis_worker.py:282, BEFORE the
        # pipeline's own feedback stages at 288 and 299. So on a fresh take
        # the bake routinely computes an empty block, stored it, and every
        # read afterwards served "no bookmarks" for the life of the snapshot.
        # The fix for marks that arrived late became marks that never arrived.
        #
        # Requiring a non-empty `changes` lane makes the failure mode the old
        # behaviour: nothing stored, so the read computes live later — after
        # the pipeline has finished — exactly as it did before this existed.
        # The speed-up survives wherever the bake genuinely has items, which
        # is every publish that happens at the END of a run.
        #
        # A document with honestly nothing to say therefore pays one live
        # computation per open. That is the right side to err on: a wasted
        # computation costs a moment, a wrongly-stored emptiness costs the
        # whole surface.
        return False
    stored = database.write_ideal_text_feedback_bake(
        str(arc_id), str(actor_id), snapshot_id, block)
    if stored:
        logger.info(
            "ideal-text feedback baked arc=%s snapshot=%s changes=%d "
            "styles=%d", arc_id, snapshot_id,
            len(block.get("changes") or []),
            len(block.get("style_changes") or []),
        )
    return stored
