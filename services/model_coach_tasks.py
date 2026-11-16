"""The coach's queue, shown in the models tab as models being taught (N642
item 6, N643 item 4; step one: nothing moves, nothing trains differently).

Each task of the queue is one row: its own signed title, its kind, how
many wait for THIS coach as the panel counts them, and where it is answered
today. The counts are read without filling a line (the panel fills an empty
line when it opens it, ``routes/v2/coach_audit._served``), so a line nobody
has opened this week reads 0 here until it is opened.

  moments      "Moments to answer": the walk's waiting moments
               (``coach_moments_queue.walk_for_coach``), opened in the queue
  hear_it      "Do you hear it?" (``error_presence_audit``)
  block_pick   "Pick the most confident" (``coach_block_pick``)
  moment_pick  "Pick the moment for feedback" (``v4_coach_sheets``, B1.8)
  surer        "Which sounds surer" (``v4_coach_sheets``, B1.9)

Only for a coach (the panel's own guard: admin or allowlisted coach) with
the ring ``chat_builder`` or ``ai_models``; anyone else reads empty lists.
``coming`` is ``model_coming``'s list.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

#: How long a coach's task list is reused. The models tab asks for it
#: several times as it opens. For those seconds the same list is returned;
#: an answer given after that shows on the next load.
_CACHE_TTL = 15.0
_CACHE: dict[tuple, tuple[float, dict]] = {}
_CACHE_LOCK = threading.Lock()
_FLIGHT: dict[tuple, threading.Event] = {}

#: "Moments to answer" (N643 item 4).
MOMENTS = "Moments to answer"


def _count(label: str, read: Callable[[], int]) -> int:
    try:
        return int(read())
    except Exception:  # noqa: BLE001 -- a line that cannot be read waits 0 here
        logger.warning("model_coach_tasks: %s could not be read", label, exc_info=True)
        return 0


def _items(result: tuple[int, dict]) -> int:
    status, payload = result
    return len(payload.get("items") or []) if status == 200 else 0


def _sheets(database: Any, coach_id: str) -> list[dict]:
    from services import coach_block_pick, error_presence_audit, v4_coach_sheets
    pick, surer = v4_coach_sheets.WORDING["pick"], v4_coach_sheets.WORDING["surer"]
    return [
        {"id": "hear_it", "kind": "hear_it", "title": error_presence_audit.WORDING["title"],
         "screen": "error_audit",
         "read": lambda: _items(error_presence_audit.queue(database, coach_id=coach_id))},
        {"id": "block_pick", "kind": "block_pick", "title": coach_block_pick.WORDING["short_title"],
         "screen": "block_pick",
         "read": lambda: _items(coach_block_pick.queue(database, coach_id=coach_id))},
        {"id": "moment_pick", "kind": "moment_pick", "title": pick["title"], "screen": "v4_moment_pick",
         "read": lambda: _items(v4_coach_sheets.pick_queue(database, rater_id=coach_id))},
        {"id": "surer", "kind": "surer", "title": surer["title"], "screen": "v4_surer",
         "read": lambda: _items(v4_coach_sheets.surer_queue(database, rater_id=coach_id))},
    ]


def clear_task_cache() -> None:
    """Drop the short list cache. Tests use it so one case cannot see another's."""
    with _CACHE_LOCK:
        _CACHE.clear()


def tasks(database: Any, coach_id: str, *, is_coach: bool, moments_waiting: Callable[[], int]) -> dict:
    """GET /v2/models/coach-tasks: {"tasks": [...], "coming": [...]}.

    The same coach's list, read a moment ago, is returned again: the tab
    asks four times as it opens. The first read counts the blind lines
    from their waiting rows (``coach_task_rows_v1`` when the database has
    it) instead of building each sheet, and reads the walk beside that.
    """
    key = (str(coach_id), bool(is_coach))
    cached = _cached(key)
    if cached is not None:
        return cached
    leader, event = _claim(key)
    if not leader:
        event.wait(30)
        cached = _cached(key)
        if cached is not None:
            return cached
    try:
        result = _build(database, coach_id, is_coach=is_coach, moments_waiting=moments_waiting)
        _remember(key, result)
        return result
    finally:
        if leader:
            _release(key, event)


def _cached(key: tuple) -> Optional[dict]:
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and now - hit[0] < _CACHE_TTL:
            return hit[1]
    return None


def _remember(key: tuple, value: dict) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic(), value)


def _claim(key: tuple) -> tuple[bool, threading.Event]:
    """True when this caller computes the list; others wait for that one."""
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is not None and time.monotonic() - hit[0] < _CACHE_TTL:
            ready = threading.Event()
            ready.set()
            return False, ready
        event = _FLIGHT.get(key)
        if event is None:
            event = threading.Event()
            _FLIGHT[key] = event
            return True, event
        return False, event


def _release(key: tuple, event: threading.Event) -> None:
    with _CACHE_LOCK:
        _FLIGHT.pop(key, None)
    event.set()


def _build(database: Any, coach_id: str, *, is_coach: bool,
           moments_waiting: Callable[[], int]) -> dict:
    from services import model_coming
    from services.parallel import run_in_parallel
    if not model_coming.on(database, coach_id):
        return {"tasks": [], "coming": []}
    coming = model_coming.listed(coach_id)
    if not is_coach:
        return {"tasks": [], "coming": coming}
    moment_n, sheets = run_in_parallel(
        lambda: _count("moments", moments_waiting),
        lambda: _sheet_counts(database, coach_id))
    out = [{"id": "moments", "kind": "moments", "title": MOMENTS, "line": "",
            "waiting": moment_n, "open": {"at": "coach_queue"}}]
    for sheet in _sheets(database, coach_id):
        out.append({"id": sheet["id"], "kind": sheet["kind"], "title": sheet["title"], "line": "",
                    "waiting": sheets.get(sheet["kind"], 0),
                    "open": {"at": "screen", "screen": sheet["screen"]}})
    return {"tasks": out, "coming": coming}


def _sheet_counts(database: Any, coach_id: str) -> dict[str, int]:
    """How many of each blind line wait, without building the sheet."""
    from services.db import rpc_object
    bundled = rpc_object(database, "coach_task_rows_v1", {"p_coach": str(coach_id)})
    if isinstance(bundled, dict) and "hear" in bundled:
        counted = _counts_from_rows(database, bundled)
        if counted is not None:
            return counted
    return _counts_from_queues(database, coach_id)


def _counts_from_queues(database: Any, coach_id: str) -> dict[str, int]:
    return {sheet["kind"]: _count(sheet["kind"], sheet["read"])
            for sheet in _sheets(database, coach_id)}


def _counts_from_rows(database: Any, bundled: dict) -> Optional[dict[str, int]]:
    """The waiting take ids, admitted the way each sheet's queue admits them."""
    from services.pair_consent import admitted_takes
    groups = {key: _take_ids(bundled.get(key)) for key in ("blocks", "picks", "surers")}
    takes = [take for ids in groups.values() for take in ids]
    admitted = {} if not takes else admitted_takes(database, takes)
    if admitted is None:
        return None

    def waiting(key: str) -> int:
        return sum(1 for take in groups[key] if admitted.get(take))

    try:
        hear = int(bundled.get("hear") or 0)
    except (TypeError, ValueError):
        return None
    return {"hear_it": hear, "block_pick": waiting("blocks"),
            "moment_pick": waiting("picks"), "surer": waiting("surers")}


def _take_ids(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def walk_waiting(queue: Any) -> int:
    """The walk's waiting moments: each speaker's ``waiting``, summed."""
    speakers = queue.get("speakers") if isinstance(queue, dict) else queue
    return sum(int(s.get("waiting") or 0) for s in speakers or [] if isinstance(s, dict))
