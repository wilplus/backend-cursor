"""The fast read of every practise try (V4 Phase 1, B1.4; build plan D-ML-9;
founder O5, V7 A; migration 0450).

THE READ ('willfidence-v1-machine-fast'). S is the try's own universal-v3
sound read, stretched to 0..1 (V4 A); the upload route reads it already.
The fast W is the mean of the try's filler and hedging signals (S-B1 A, V5
B), the two word signals that can be read inside the time budget. The
database computes W and S*W from what is sent here.

THE BUDGET (O5). The read must reach the phone within ``LIMIT_MS`` of Stop
for 9 tries in 10, on the phone's clock (V7 A). The server stamps when the
try arrived and when its read was ready; the phone sends its own Stop and
"answer shown" times once, afterwards. ``wait_ms`` prefers the phone's wait
and falls back to the server's, saying which. A read that failed, or came
late, counts as "not reached yet" (``reached_state``) and is still stored.

NEVER BLOCKING. Every function that touches the database here returns
instead of raising; a failed read or timing write leaves the try, its
comparison and the practise check exactly as they were (LIVE LOOP). Nothing
here is ever returned to the speaker (AC-9).
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from services import willfidence as wf

logger = logging.getLogger(__name__)

READ_VERSION = "willfidence-v1-machine-fast"
#: O5: "under 5 s for 9 in 10 attempts".
LIMIT_MS = 5000
TARGET_SHARE = 0.9


def fast_read(metrics: Any, transcript: Any) -> dict:
    """S, filler and hedging for one try. Pure; never raises."""
    read = (metrics or {}).get("voice_confidence") if isinstance(metrics, dict) else None
    s = None
    if isinstance(read, dict) and read.get("version") == wf.SOUND_VERSION:
        s = wf.stretch(read.get("score"))
    return {"s": s, "filler": wf.filler(transcript), "hedging": wf.hedging(transcript)}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _request_received_at() -> datetime:
    """When the current request arrived (request_context stamps it), or now
    outside a request."""
    try:
        from flask import g, has_request_context
        if has_request_context() and isinstance(getattr(g, "received_at", None), datetime):
            return g.received_at
    except Exception:  # noqa: BLE001 -- a timing, never worth the try
        pass
    return _now()


def record_for_attempt(database: Any, attempt: Any) -> Optional[dict]:
    """The fast read of one saved try, from the row the upload route wrote:
    its words and its acoustic snapshot, whose ``confidence`` is the
    universal-v3 read (``voice_confidence.stamped_score``). Never raises."""
    row = attempt if isinstance(attempt, dict) else {}
    raw = row.get("acoustic_metrics")
    snapshot: dict = raw if isinstance(raw, dict) else {}
    score = snapshot.get("confidence")
    metrics = ({"voice_confidence": {"version": wf.SOUND_VERSION, "score": score}}
               if isinstance(score, (int, float)) and not isinstance(score, bool) else {})
    return record(database, row.get("id"), received_at=_request_received_at(),
                  metrics=metrics, transcript=row.get("transcript"))


def record(database: Any, attempt_id: Any, *, received_at: datetime,
           metrics: Any, transcript: Any) -> Optional[dict]:
    """Read one try and store the read with the server's times. Never raises."""
    attempt = str(attempt_id or "").strip()
    if not attempt:
        return None
    try:
        values, outcome = fast_read(metrics, transcript), "read"
    except Exception as error:  # noqa: BLE001 -- stored as a failed read
        logger.warning("v4 practice read failed attempt=%s: %s", attempt, error)
        values, outcome = {"s": None, "filler": None, "hedging": None}, "failed"
    try:
        return database.record_v4_practice_read(
            attempt, outcome=outcome, received_at=received_at,
            read_at=_now(), **values)
    except Exception as error:  # noqa: BLE001 -- dark measure; the try stands
        logger.warning("v4 practice read not stored attempt=%s: %s", attempt, error)
        return None


def _ms(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)) or float(value) < 0:
        return None
    return int(value)


def record_timing(database: Any, attempt_id: Any, owner_user_id: Any,
                  body: Any) -> bool:
    """Store the phone's Stop and "answer shown" times once. Never raises.

    ``body``: {"stopped_at_ms", "shown_at_ms"}, both on the phone's clock."""
    row = body if isinstance(body, dict) else {}
    stopped, shown = _ms(row.get("stopped_at_ms")), _ms(row.get("shown_at_ms"))
    if stopped is None or shown is None or not 0 <= shown - stopped <= 600_000:
        return False
    try:
        saved = database.record_v4_practice_timing(
            str(attempt_id), str(owner_user_id), stopped, shown)
        return bool(saved and saved.get("outcome") == "stored")
    except Exception as error:  # noqa: BLE001 -- dark measure
        logger.warning("v4 practice timing not stored attempt=%s: %s",
                       attempt_id, error)
        return False


def _parse(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def wait_ms(row: dict) -> tuple[Optional[int], str]:
    """The try's wait and its clock: the phone's when it sent its times
    (V7 A), else the server's own wait."""
    phone = row.get("phone_wait_ms")
    if isinstance(phone, int) and not isinstance(phone, bool):
        return phone, "phone"
    received, read = _parse(row.get("server_received_at")), _parse(row.get("server_read_at"))
    if received and read:
        return int((read - received).total_seconds() * 1000), "server"
    return None, "none"


def late(row: dict) -> bool:
    """A failed read is late by definition; so is one past the limit or
    one whose wait cannot be known."""
    if row.get("outcome") != "read":
        return True
    wait, _ = wait_ms(row)
    return wait is None or wait > LIMIT_MS


def reached_state(row: Optional[dict], bar: float) -> str:
    """What the walk may do with a try (Phase 2): 'reached' only for an
    on-time read whose S*W meets the bar; every other case, a missing,
    failed or late read included, is 'not_reached_yet' (O5)."""
    if not row or late(row):
        return "not_reached_yet"
    value = row.get("willfident")
    try:
        return "reached" if value is not None and float(value) >= float(bar) \
            else "not_reached_yet"
    except (TypeError, ValueError):
        return "not_reached_yet"


def p90_report(rows: Iterable[dict]) -> dict:
    """The O5 report: p90 of the waits (nearest rank), the share on time,
    and how many waits came from each clock. A failed read counts as late
    and as a wait past the limit."""
    waits: list[int] = []
    clocks = {"phone": 0, "server": 0, "none": 0}
    on_time = total = 0
    for row in rows:
        total += 1
        wait, clock = wait_ms(row)
        clocks[clock] += 1
        if row.get("outcome") != "read" or wait is None:
            wait = LIMIT_MS + 1
        waits.append(wait)
        on_time += 0 if late(row) else 1
    waits.sort()
    p90 = waits[max(0, math.ceil(TARGET_SHARE * len(waits)) - 1)] if waits else None
    return {
        "tries": total,
        "p90_ms": p90,
        "on_time_share": (on_time / total) if total else None,
        "meets_o5": p90 is not None and p90 <= LIMIT_MS,
        "clocks": clocks,
    }
