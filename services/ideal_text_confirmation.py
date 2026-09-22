"""Take 1 Ideal Text confirmation boundary.

Take 1 is not successful merely because transcription and feedback finished.
Its load-bearing deliverable is the first canonical Ideal Text, so success is
allowed only after a read from ``coach_arc_ideal_text`` proves that non-empty
text was durably persisted.  The retry entry point in ``pipeline_jobs`` calls
the same builder, but supplies only database identities; it never re-enters the
audio, upload, or transcription pipeline.
"""
from __future__ import annotations

import threading
import time
from typing import Any, Callable, Optional


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
    # owner-thread Event.wait deadline. If a non-cancellable call returns later,
    # its guarded/idempotent database write is harmless; it never silently
    # changes the already-failed session state back to success.
    timeout = max(0.0, float(timeout_seconds))
    finished = threading.Event()
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

    threading.Thread(
        target=assemble_and_confirm,
        name=f"ideal-text-take-1-{arc_id}",
        daemon=True,
    ).start()
    if not finished.wait(timeout):
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
