"""Requests per opened moment, before and after the switch (founder
2026-10-01, Phase 2 addition: "report requests per opened moment before vs
after the switch, split by kind; the founder decides later whether praise
requests become a digest").

Counts only, for the founder's ledger: moments opened (migration 0408),
and the coach requests raised since the same date, split by where they rose
(``raised_on``: at the judgement, the flow before F1; at the open, F1) and
by the kind the coach acts on (``answer_kind`` once the speaker judged, else
``kind``). Never a speaker-facing number (AC-9).
"""
from __future__ import annotations

from typing import Any

from services.judgement_follow_up import KINDS

RAISED_ON = ("judgement", "open")


def coach_load(database: Any, *, since: str) -> dict:
    """{"since", "moments_opened", "requests": {raised_on: {kind: n}},
    "per_opened_moment": {raised_on: ratio or None}}."""
    opened = int(database.count_moment_events("opened", since) or 0)
    requests: dict[str, dict[str, int]] = {
        where: {kind: 0 for kind in KINDS} for where in RAISED_ON}
    for row in database.list_exercise_coach_requests(since) or []:
        if not isinstance(row, dict):
            continue
        where = str(row.get("raised_on") or "judgement")
        kind = str(row.get("answer_kind") or row.get("kind") or "error")
        if where in requests and kind in requests[where]:
            requests[where][kind] += 1
    return {
        "since": since,
        "moments_opened": opened,
        "requests": requests,
        "per_opened_moment": {
            where: (round(sum(requests[where].values()) / opened, 2)
                    if opened else None)
            for where in RAISED_ON
        },
    }
