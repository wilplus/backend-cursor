"""Session identity rules for accepting a new Lab recording."""
from __future__ import annotations

import uuid
from typing import Any, Callable


_SPENT_SESSION_FIELDS = (
    "recording_1_id",
    "recording_kind",
    "paired_session_id",
    "analysis_state",
    "results_published_at",
)


def choose_guest_session_id(
    requested_session_id: str | None,
    *,
    database: Any,
    log: Any,
    mint_id: Callable[[], str] | None = None,
) -> str:
    """Reuse only a fresh session; fail closed when its state is unknown."""
    session_id = str(requested_session_id or "").strip()
    if session_id:
        try:
            prior = database.v2_get_session_by_id(session_id)
            spent = bool(
                prior
                and any(prior.get(field) for field in _SPENT_SESSION_FIELDS)
            )
        except Exception as exc:
            log.warning(
                "lab: session-reuse check failed sid=%s: %s "
                "(minting fresh)",
                session_id,
                exc,
            )
            spent = True

        if spent:
            log.info(
                "lab: spent session %s not reused — minting fresh "
                "(lane guard)",
                session_id,
            )
            session_id = ""

    make_id = mint_id or (lambda: str(uuid.uuid4()))
    return session_id or make_id()
