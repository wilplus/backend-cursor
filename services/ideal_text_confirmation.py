"""Take 1 Ideal Text confirmation boundary.

Take 1 is not successful merely because transcription and feedback finished.
Its load-bearing deliverable is the first canonical Ideal Text, so success is
allowed only after a read from ``coach_arc_ideal_text`` proves that non-empty
text was durably persisted.  The retry entry point in ``pipeline_jobs`` calls
the same builder, but supplies only database identities; it never re-enters the
audio, upload, or transcription pipeline.
"""
from __future__ import annotations

import logging
import threading
import time
import uuid
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


FAILED_IDEAL_TEXT_UNCONFIRMED = "failed_ideal_text_unconfirmed"
IDEAL_TEXT_CONFIRM_TIMEOUT_SECONDS = 120.0
IDEAL_TEXT_CONFIRM_POLL_SECONDS = 1.0
IDEAL_TEXT_UNCONFIRMED_BODY = (
    "We processed your take, but couldn’t create your Ideal Text."
)


class IdealTextUnconfirmedError(RuntimeError):
    """The document did not become durably observable in time."""

    def __init__(self, arc_id: str):
        # Take-agnostic since Option A (2026-09-22): a later Take recovering
        # a Project that never had a document raises this too, and naming
        # Take 1 in its message sent readers looking at the wrong recording.
        super().__init__(
            "The Ideal Text was not confirmed in the database within "
            "120 seconds"
        )
        self.arc_id = str(arc_id)


def confirmed_ideal_text(row: Any) -> Optional[dict]:
    """Return the persisted row only when it proves a usable document.

    Reading the row back is intentional: the assembler's return value is not
    confirmation because a best-effort database write can fail or be rejected
    by a guard after generation completed in memory.
    """
    if not isinstance(row, dict):
        return None
    text = str(row.get("auto_text") or row.get("text") or "").strip()
    return row if text else None


def take_creates_ideal_text(
    database: Any, arc_id: Any, take_index: Any,
) -> bool:
    """Is this the Take that creates the Project's one canonical document?

    FOUNDER DECISION, 2026-09-22 (Option A). A Project whose Take 1 never
    confirmed an Ideal Text could never recover: only Take 1 was allowed to
    create the document, Take 1 was over, and every later Take was refused
    for the document's absence — correctly, by a rule that then had no way
    back. One real Project sat like that for eleven days.

    So the question stops being "which Take is this" and becomes "does this
    Project still have no document". Take 1 answers yes as it always did; a
    later Take answers yes ONLY when a database read proves nothing is there.

    THAT READ IS THE L1 GUARD, and it is the whole reason this is safe. L1
    says a later Take may never rebuild or silently overwrite the canonical
    words. This cannot: the one path to True for a later Take requires the
    canonical row to be absent or empty, so there are no words to overwrite.
    It fills a hole; it never replaces anything. A Project with a document —
    machine-made, user-edited or coach-written — takes the False branch on
    every Take for the rest of its life.

    Conservative on failure, in the direction that protects the document: a
    read that raises answers False, which is exactly today's behaviour for
    every Take after the first.
    """
    if isinstance(take_index, bool) or not isinstance(take_index, int):
        return False
    if take_index < 1:
        return False
    if take_index == 1:
        return True
    if not arc_id:
        return False
    try:
        existing = confirmed_ideal_text(
            database.ideal_text.get_coach_arc_ideal_text(str(arc_id)))
    except Exception:
        return False
    return existing is None


def wait_for_ideal_text_confirmation(
    database: Any,
    arc_id: str,
    *,
    timeout_seconds: float = IDEAL_TEXT_CONFIRM_TIMEOUT_SECONDS,
    poll_seconds: float = IDEAL_TEXT_CONFIRM_POLL_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> dict:
    """Poll the database until Take 1's document is explicit or time expires."""
    started = monotonic()
    timeout = max(0.0, float(timeout_seconds))
    interval = max(0.001, float(poll_seconds))
    while True:
        confirmed = confirmed_ideal_text(
            database.ideal_text.get_coach_arc_ideal_text(str(arc_id))
        )
        if confirmed is not None:
            return confirmed
        elapsed = monotonic() - started
        if elapsed >= timeout:
            raise IdealTextUnconfirmedError(str(arc_id))
        sleep(min(interval, timeout - elapsed))


def build_initial_ideal_text_from_stored_artifacts(
    database: Any,
    arc_id: str,
    *,
    source_session_id: Optional[str] = None,
    include_suggestion_anchors: bool = False,
    timeout_seconds: float = IDEAL_TEXT_CONFIRM_TIMEOUT_SECONDS,
    degradation: Optional[Any] = None,
    on_late_confirmation: Optional[Callable[[dict], None]] = None,
) -> dict:
    """Build and confirm Take 1 using already-persisted transcript artifacts.

    This deliberately imports only the Ideal Text assembler.  In particular it
    does not import ``analysis_worker``, audio storage, Whisper, or any upload
    service.  Repeated calls are safe: the assembler returns the existing
    canonical row without overwriting user/coach-owned text, then this function
    confirms that same row from the database.
    """
    from services.ideal_text_block import maybe_assemble_ideal_text

    # The 120 seconds covers GENERATION AND THE CONFIRMATION READS. Either the
    # model provider or a database request can stall, so both live behind one
    # owner-thread Event.wait deadline.
    #
    # FOUNDER 2026-09-24: "Ideal text generation fails" -- with the v1.0 ready
    # card and the failure card sitting in the same thread. That pair is this
    # deadline. The wait bounds the OWNER; it cannot cancel the worker, so a
    # generation finishing at 121 seconds persists a perfectly good document
    # seconds after the owner already declared it lost. This module used to
    # call that harmless because the late write "never silently changes the
    # already-failed session state back to success" -- but leaving a false
    # failure standing over a document that exists is not safety, it is the
    # bug. The thread that makes the failure untrue is the one that must say
    # so: `on_late_confirmation` is that announcement, and every writer of the
    # terminal state now reads the document before claiming anything.
    timeout = max(0.0, float(timeout_seconds))
    finished = threading.Event()
    abandoned = threading.Event()
    result: list[dict] = []
    failure: list[Exception] = []

    def assemble_and_confirm() -> None:
        try:
            maybe_assemble_ideal_text(
                str(arc_id),
                database=database,
                require_target=False,
                include_suggestion_anchors=include_suggestion_anchors,
                source_session_id=source_session_id,
                # Only when the caller shares a log: the assembler creates
                # its own otherwise, and the call stays as it was.
                **({"degradation": degradation} if degradation is not None
                   else {}),
            )
            result.append(wait_for_ideal_text_confirmation(
                database,
                str(arc_id),
                timeout_seconds=timeout,
            ))
        except Exception as exc:  # propagated on the owning worker thread
            failure.append(exc)
        finally:
            finished.set()
        if result and abandoned.is_set() and on_late_confirmation is not None:
            try:
                on_late_confirmation(result[0])
            except Exception:  # never turn a confirmed document into a crash
                logger.warning(
                    "ideal_text_confirmation: late confirmation handler "
                    "failed arc=%s", arc_id, exc_info=True,
                )

    threading.Thread(
        target=assemble_and_confirm,
        name=f"ideal-text-take-1-{arc_id}",
        daemon=True,
    ).start()
    if not finished.wait(timeout):
        abandoned.set()
        # The worker may have confirmed in the gap between its final poll and
        # this deadline; that answer is free to take. DELIBERATELY NO FRESH
        # READ HERE -- a database read on the way out would put an unbounded
        # call back inside a boundary whose entire job is to be bounded (see
        # test_database_confirmation_read_is_inside_the_timeout_boundary). The
        # late document is caught by `on_late_confirmation` instead, and by
        # the confirmation read in `mark_ideal_text_unconfirmed`, both of
        # which run AFTER this deadline has already been honoured.
        if result:
            return result[0]
        raise IdealTextUnconfirmedError(str(arc_id))
    if result:
        return result[0]
    if failure:
        raise IdealTextUnconfirmedError(str(arc_id)) from failure[0]
    raise IdealTextUnconfirmedError(str(arc_id))


def mark_ideal_text_unconfirmed(
    database: Any,
    *,
    session_id: Any,
    user_id: Any,
    arc_id: Any,
    take_index: Any,
    error: Any = None,
) -> bool:
    """Persist the exact terminal state and its idempotent Lounge card.

    Any Take that was CREATING the document can land here, not only Take 1
    (2026-09-22). The state means "we processed your take, but couldn't
    create your Ideal Text", and that sentence is equally true of the Take 3
    that found the Project still had none.
    """
    if (
        not session_id
        or not arc_id
        or isinstance(take_index, bool)
        or not isinstance(take_index, int)
        or take_index < 1
    ):
        return False
    # LAST READ BEFORE THE CLAIM (founder 2026-09-24). Every caller arrives
    # here off a DEADLINE, not off a refusal, so the document may have landed
    # while that deadline was expiring. Writing the terminal state without
    # looking is what put "couldn't create your Ideal Text" underneath a ready
    # v1.0 card. If the document is there this Take did not fail, so record
    # the success instead of the failure -- and retract any card an earlier
    # writer (the browser has its own cap) already put in the thread.
    if resolve_ideal_text_unconfirmed(
        database, session_id=session_id, user_id=user_id, arc_id=arc_id,
    ) is not None:
        logger.info(
            "ideal_text_confirmation: failure withdrawn, document present "
            "arc=%s sid=%s", arc_id, session_id,
        )
        return False
    detail = str(error or "Ideal Text was not confirmed")[:500]
    state_written = bool(database.takes.set_session_analysis_state(
        str(session_id), FAILED_IDEAL_TEXT_UNCONFIRMED, detail,
    ))
    if user_id:
        try:
            from services.arc_notifications import fire_ideal_text_unconfirmed

            fire_ideal_text_unconfirmed(
                database,
                user_id,
                arc_id,
                session_id,
                take_index,
            )
        except Exception:
            # The session state is the terminal authority; message delivery is
            # best-effort here and the browser writes the same idempotent row.
            pass
    return state_written


def ideal_text_failure_card_client_id(take_session_id: Any) -> Optional[str]:
    """The one idempotency key every writer of the failure card agrees on.

    The worker, a reconnecting browser and every retry all converge on the
    Take's session UUID (see ``arc_notifications.fire_ideal_text_unconfirmed``
    and the frontend's ``idealTextUnconfirmedDraft``), which is what makes the
    card retractable at all: one key, one row, one truth.
    """
    try:
        return str(uuid.UUID(str(take_session_id)))
    except (ValueError, AttributeError, TypeError):
        return None


def resolve_ideal_text_unconfirmed(
    database: Any,
    *,
    session_id: Any,
    user_id: Any,
    arc_id: Any,
) -> Optional[dict]:
    """Withdraw a failure the database no longer supports.

    FOUNDER 2026-09-24. The failure card was durable and the state was
    terminal, so a Take whose document landed a few seconds late kept telling
    its speaker the document could not be created -- directly underneath the
    card announcing that it was ready. A failed note must not outlive the
    failure (the same rule the frontend's take recheck was written for on
    2026-09-21); it had simply never been applied to the durable card.

    EVIDENCE ONLY, and the evidence is the document itself. A read that finds
    nothing changes nothing and returns None, so this can never talk a real
    failure away. L1 is untouched: this reads the canonical row and never
    writes it -- the only writes are the session's job state and the removal
    of a card that is no longer true.

    Returns the confirmed document row when the failure was withdrawn.
    """
    if not session_id or not arc_id:
        return None
    try:
        confirmed = confirmed_ideal_text(
            database.ideal_text.get_coach_arc_ideal_text(str(arc_id)))
    except Exception:
        return None
    if confirmed is None:
        return None
    try:
        database.takes.set_session_analysis_state(str(session_id), "ready")
    except Exception:
        logger.warning(
            "ideal_text_confirmation: could not clear failed state sid=%s",
            session_id, exc_info=True,
        )
    client_id = ideal_text_failure_card_client_id(session_id)
    if user_id and client_id:
        try:
            database.delete_lounge_message_by_client_id(
                str(user_id), client_id)
        except Exception:
            # The state is the authority; a card that outlives one attempt is
            # retracted by the next read of this take.
            logger.warning(
                "ideal_text_confirmation: failure card not retracted sid=%s",
                session_id, exc_info=True,
            )
    return confirmed


def withdraw_and_announce_confirmed_document(
    database: Any,
    *,
    session_id: Any,
    user_id: Any,
    arc_id: Any,
    take_index: Any,
) -> Optional[dict]:
    """The retry asked for a document that is already there.

    The commonest shape of this bug: the deadline declared the document lost,
    it landed anyway, and the speaker taps "Try creating it again" on a card
    describing a failure that is over. Nothing needs rebuilding -- the L1
    guard is exactly this branch -- so withdraw the failure and announce the
    document that exists. Lives here rather than in the route because the
    route may hold neither the database reads nor this much of the decision.
    """
    try:
        confirmed = confirmed_ideal_text(
            database.ideal_text.get_coach_arc_ideal_text(str(arc_id)))
    except Exception:
        return None
    if confirmed is None:
        return None
    resolve_ideal_text_unconfirmed(
        database, session_id=session_id, user_id=user_id, arc_id=arc_id,
    )
    if user_id:
        try:
            from services.arc_notifications import fire_ideal_version_ready

            fire_ideal_version_ready(
                database,
                user_id,
                arc_id,
                confirmed.get("version") or 1,
                # 1 is right only on Take 1; a recovery omits the nudge.
                **({"spoken_take_count": 1} if take_index == 1 else {}),
            )
        except Exception:
            logger.warning(
                "ideal_text_confirmation: ready card not announced arc=%s",
                arc_id, exc_info=True,
            )
    return confirmed
