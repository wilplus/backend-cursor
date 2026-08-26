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
    """The Take 1 document did not become durably observable in time."""

    def __init__(self, arc_id: str):
        super().__init__(
            "Take 1 Ideal Text was not confirmed in the database within "
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
            database.get_coach_arc_ideal_text(str(arc_id))
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
    """Persist the exact Take 1 terminal state and its idempotent Lounge card."""
    if (
        not session_id
        or not arc_id
        or isinstance(take_index, bool)
        or take_index != 1
    ):
        return False
    detail = str(error or "Ideal Text was not confirmed")[:500]
    state_written = bool(database.set_session_analysis_state(
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
