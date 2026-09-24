"""What a readout route serves INSTEAD of a readout, and when.

Both readout routes (the authed one and the guest Lab one) answer the same
question before they build anything: is this Take's background analysis still
running, or did it end badly? While either is true they serve the job state
and a null readout, and the frontend polls until it goes terminal.

That decision is here rather than inline because it is no longer a field read.
A Take can hold `failed_ideal_text_unconfirmed` over a document that exists,
and the only honest answer to a read in that state is to check.
"""
from __future__ import annotations

from typing import Any, Optional

from services.ideal_text_confirmation import (
    FAILED_IDEAL_TEXT_UNCONFIRMED,
    resolve_ideal_text_unconfirmed,
)

#: Job states that are served in place of a readout.
NON_TERMINAL_STATES = ("processing", "failed", FAILED_IDEAL_TEXT_UNCONFIRMED)


def served_analysis_state(
    database: Any, session: Any, *, session_id: Any = None,
) -> Optional[str]:
    """The job state to serve instead of this Take's readout, or None.

    None means "read normally" -- the analysis finished, or the row predates
    the async job state entirely (legacy/sync rows carry NULL and were only
    ever persisted after a completed analysis).

    THE STUCK FAILURE MUST NOT BE OBSERVABLE (founder 2026-09-24). The Ideal
    Text failure state is written off a 120-second deadline, not off a
    refusal, and the document can land after it -- which is how a speaker came
    to be shown "we couldn't create your Ideal Text" directly underneath the
    card announcing that it was ready. So a read that finds that state asks
    the database whether it is still true, and withdraws it, card included,
    when it is not. Evidence outranks the stored verdict; a read that finds
    nothing changes nothing, so this can never talk a real failure away.
    """
    if not isinstance(session, dict):
        return None
    state = session.get("analysis_state")
    if state not in NON_TERMINAL_STATES:
        return None
    if state != FAILED_IDEAL_TEXT_UNCONFIRMED:
        return str(state)
    withdrawn = resolve_ideal_text_unconfirmed(
        database,
        session_id=session_id or session.get("id"),
        user_id=session.get("user_id"),
        arc_id=session.get("arc_id"),
    )
    return None if withdrawn is not None else str(state)
