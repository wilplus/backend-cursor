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
  moment_pick  "Pick the moment for feedback" (``v4_coach_sheets``, B1.8)

Only for a coach (the panel's own guard: admin or allowlisted coach) with
the ring ``chat_builder`` or ``ai_models``; anyone else reads empty lists.
``coming`` is ``model_coming``'s list.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

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
    from services import error_presence_audit, v4_coach_sheets
    pick = v4_coach_sheets.WORDING["pick"]
    return [
        {"id": "hear_it", "kind": "hear_it", "title": error_presence_audit.WORDING["title"],
         "screen": "error_audit",
         "read": lambda: _items(error_presence_audit.queue(database, coach_id=coach_id))},
        {"id": "moment_pick", "kind": "moment_pick", "title": pick["title"], "screen": "v4_moment_pick",
         "read": lambda: _items(v4_coach_sheets.pick_queue(database, rater_id=coach_id))},
    ]


def tasks(database: Any, coach_id: str, *, is_coach: bool, moments_waiting: Callable[[], int]) -> dict:
    """GET /v2/models/coach-tasks: {"tasks": [...], "coming": [...]}."""
    from services import model_coming
    if not model_coming.on(database, coach_id):
        return {"tasks": [], "coming": []}
    # "Images, coming" is no longer listed here (N702): it trains nothing.
    coming: list = []
    if not is_coach:
        return {"tasks": [], "coming": coming}
    out = [{"id": "moments", "kind": "moments", "title": MOMENTS, "line": "",
            "waiting": _count("moments", moments_waiting), "open": {"at": "coach_queue"}}]
    for sheet in _sheets(database, coach_id):
        out.append({"id": sheet["id"], "kind": sheet["kind"], "title": sheet["title"], "line": "",
                    "waiting": _count(sheet["kind"], sheet["read"]),
                    "open": {"at": "screen", "screen": sheet["screen"]}})
    return {"tasks": out, "coming": coming}


def walk_waiting(queue: Any) -> int:
    """The walk's waiting moments: each speaker's ``waiting``, summed."""
    speakers = queue.get("speakers") if isinstance(queue, dict) else queue
    return sum(int(s.get("waiting") or 0) for s in speakers or [] if isinstance(s, dict))
