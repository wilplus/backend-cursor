"""The verbal read of one Take (founder 2026-11-02, N326, building N290
items 4 and 6; prototype https://claude.ai/artifact/KvAiek4DrxgbpDudcBFJNQ;
rules: frontend docs/flows/feedback-walk-and-chat.md H1 and
docs/flows/principles.md).

One AI call per Take, for a speaker the walk's ring row reaches who noted
something the walk may read (``services.inner_context``). It reads the
Take's moments against the outside context (the Take's set-up,
``services.take_context``) and the speaker's own notes, for the eight kinds
of N290 item 4 (``services.prompts.verbal_read.KINDS``), and says how much
each flagged moment matters for this speaker (``WEIGHTS``). Its answer is
used in two places and nowhere else:

  * the pick: a moment it weighs reads lower for the between
    (``moment_pick.lift``), and the policy keeps that pick only when its
    Clearer version passes the gate (``take_feedback_policy_v3``);
  * the Clearer version: the moments it weighs most are rewritten with its
    one line on what matters to the speaker
    (``moment_suggestions.context_rewrites``), and a rewrite carrying a
    phrase from the notes the speaker did not say is refused
    (``rewrite_gate.leaks``).

WHERE IT RUNS. Inside the Take's analysis run, so the call holds the
speaker's processing authorization like every other provider call there
(``analysis_worker.run_full_analysis``): ``start`` begins it on a thread
that keeps the run's context (``parallel.start_scoped_thread``) as the
feedback moments are found, so it runs beside them, the Ideal Text and the
KPI fold; ``finish`` waits for it at most ``JOIN_SECONDS`` before the Take
is flipped ready, then stores its Clearer versions and keeps its weights in
this process for the run's own bake (``for_pick``). Late or failed: nothing
is stored and the walk picks as it does today. The wait is the founder's
exception to "the loop never waits" (N327): at most 5 seconds, and only for a
speaker the read reaches; for everyone else it stops at the ring check.

WHAT IS KEPT. Nothing new in the database: the weights live in memory for
the run, and a later read of a frozen Take keeps its walk from the frozen
Clearer version itself (``take_feedback_policy_v3._heard_weights``). The
kinds, the weights and the line never reach a frame, a suggestion row, a
coach or a screen (Never 1, Never 2).
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_SURFACE = "verbal_read"
#: How much a flagged moment matters for this speaker, as the pick reads it.
WEIGHTS = {"high": 1.0, "some": 0.5}
#: The most moments one read may flag.
MAX_FLAGGED = 3
_MAX_MOMENTS = 40
_MAX_TEXT = 400
_MAX_OUTSIDE = 600
_MAX_FOCUS = 200
#: The longest the run waits for the read before the Take is ready.
JOIN_SECONDS = 5.0
#: How long this process keeps a read's weights for the run's bake.
_KEEP_SECONDS = 900.0
_MAX_KEPT = 256


@dataclass(frozen=True)
class Read:
    """``weights``: ``{snippet_id: weight}``; ``focus``: the line, or ""."""
    weights: dict
    focus: str = ""


def _clip(value: Any, limit: int) -> str:
    return " ".join(value.split())[:limit] if isinstance(value, str) else ""


def moments_of(snippets: Any) -> list[dict]:
    """The Take's moments for the read: ``[{snippet_id, slide, text}]`` in
    order, bounded. Pure."""
    out = []
    for row in snippets or []:
        if not isinstance(row, dict) or not row.get("id"):
            continue
        text = _clip(row.get("transcript"), _MAX_TEXT)
        if not text:
            continue
        metrics = row.get("metrics")
        piece = metrics.get("piece") if isinstance(metrics, dict) else None
        slide = piece.get("slide_index") if isinstance(piece, dict) else None
        out.append({"snippet_id": str(row["id"]), "text": text,
                    "slide": slide if isinstance(slide, int) and not isinstance(slide, bool) else None})
    return out[:_MAX_MOMENTS]


def outside_of(context: Any, setup: Any) -> dict:
    """The outside context the read gets: who the talk is for, what it
    answers, what the listener should do, the key line
    (``take_context.for_take``), and the speaker's own set-up note. Pure."""
    context = context if isinstance(context, dict) else {}
    setup = setup if isinstance(setup, dict) else {}

    def value(slot: Any) -> str:
        return _clip(slot.get("value"), _MAX_OUTSIDE) if isinstance(slot, dict) else ""
    out = {"who": value(context.get("who")), "answers": value(context.get("what")),
           "success": value(context.get("success")), "key_line": value(context.get("key_line")),
           "note": _clip(setup.get("strategic_context"), _MAX_OUTSIDE)}
    return {key: text for key, text in out.items() if text}


def parse(parsed: Any, ids: dict, said: str, noted: Any) -> Optional[Read]:
    """The model's answer, strictly: an item with an unknown id, no known
    kind or no known weight is ignored; at most ``MAX_FLAGGED``; the line is
    dropped when it carries a phrase from the notes the Take did not say.
    None when nothing is flagged. Pure."""
    from services.prompts.verbal_read import KINDS
    from services.rewrite_gate import leaks
    if not isinstance(parsed, dict) or not isinstance(parsed.get("moments"), list):
        return None
    weights: dict = {}
    for item in parsed["moments"]:
        if len(weights) >= MAX_FLAGGED:
            break
        if not isinstance(item, dict) or not isinstance(item.get("kinds"), list):
            continue
        key = item.get("id")
        snippet_id = ids.get(key) if isinstance(key, str) else None
        known = [kind for kind in item["kinds"] if isinstance(kind, str) and kind in KINDS]
        matters = item.get("matters")
        weight = WEIGHTS.get(matters) if isinstance(matters, str) else None
        if snippet_id and known and weight and snippet_id not in weights:
            weights[snippet_id] = weight
    if not weights:
        return None
    focus = _clip(parsed.get("focus"), _MAX_FOCUS)
    if focus and leaks(focus, noted, said):
        focus = ""
    return Read(weights=weights, focus=focus)


def read(moments: list[dict], outside: dict, inner: Any, *, user_id: Any = None,
         session_id: Any = None, arc_id: Any = None) -> Optional[Read]:
    """One call: the read of these moments for this speaker, or None (no
    moments, no notes, nothing flagged, or any failure)."""
    if not moments or not inner:
        return None
    ids = {f"M{at}": row["snippet_id"] for at, row in enumerate(moments, start=1)}
    payload = {"outside": outside, "speaker": inner.block,
               "moments": [{"id": key, "slide": row.get("slide"), "text": row["text"]}
                           for key, row in zip(ids, moments)]}
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_VERBAL_READ
        from services.prompts.verbal_read import SYSTEM
        result = chat_complete(spec=SPEC_VERBAL_READ, system=SYSTEM,
                               user=json.dumps(payload, ensure_ascii=False),
                               surface=_SURFACE, user_id=str(user_id) if user_id else None,
                               session_id=str(session_id) if session_id else None,
                               arc_id=str(arc_id) if arc_id else None)
    except Exception as error:  # noqa: BLE001 -- the walk as it was
        logger.warning("verbal read: call failed take=%s: %s", session_id, error)
        return None
    said = " ".join(row["text"] for row in moments)
    return parse(getattr(result, "parsed", None) if result else None, ids, said, inner.phrases)


# ── in the analysis run ────────────────────────────────────────────────────

@dataclass
class Handle:
    """One Take's read in flight."""
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[dict] = None
    late: bool = False
    #: The ring row and the notes reach this speaker: only then may the run
    #: wait for the read (N327 item 3).
    reached: bool = False


def _run(handle: Handle, database: Any, session_id: str, arc_id: str, user_id: str,
         rewrites: bool) -> None:
    try:
        from services import inner_context, take_context
        inner = inner_context.gather(database, user_id)
        if not inner:
            return
        handle.reached = True
        session = database.v2_get_session_by_id(session_id) or {}
        moments = moments_of(database.get_snippets_by_session(session_id) or [])
        found = read(moments, outside_of(take_context.for_take(database, user_id, session),
                                         session.get("intake_context")),
                     inner, user_id=user_id, session_id=session_id, arc_id=arc_id)
        if found is None or handle.late:
            return
        made: list = []
        if rewrites:
            from services.moment_suggestions import context_rewrites
            made = context_rewrites(session_id, arc_id, found.weights, found.focus,
                                    inner.phrases, database=database)
        handle.result = {"weights": dict(found.weights), "rewrites": made}
        logger.info("verbal read: take=%s flagged=%d rewritten=%d", session_id,
                    len(found.weights), len(made))
    except Exception as error:  # noqa: BLE001 -- the walk as it was
        logger.warning("verbal read: failed take=%s: %s", session_id, error, exc_info=True)
    finally:
        handle.done.set()


def start(database: Any, *, session_id: Any, arc_id: Any, user_id: Any,
          rewrites: bool = True) -> Optional[Handle]:
    """Begin the Take's read beside the run's other work, on a thread that
    keeps the run's processing authorization. ``rewrites``: the star lane is
    on, so the Clearer versions may be written. None when there is nothing
    to read; never raises."""
    if not (session_id and arc_id and user_id):
        return None
    try:
        from services.parallel import start_scoped_thread
        handle = Handle()
        start_scoped_thread(_run, args=(handle, database, str(session_id), str(arc_id),
                                        str(user_id), bool(rewrites)),
                            name=f"verbal-read-{session_id}")
        return handle
    except Exception as error:  # noqa: BLE001 -- the walk as it was
        logger.warning("verbal read: not started take=%s: %s", session_id, error)
        return None


def finish(handle: Optional[Handle], database: Any, *, session_id: Any, arc_id: Any,
           wait: float = JOIN_SECONDS) -> bool:
    """Before the Take is ready: wait at most ``wait`` seconds, then store
    the read's Clearer versions and keep its weights for the run's bake.
    False when there was nothing, or it was late (then nothing is kept and
    the walk picks as it does today). Never raises."""
    if handle is None:
        return False
    try:
        # Nobody waits for a read not yet known to reach the speaker (N327
        # item 3): a slow ring lookup never holds anyone's "ready".
        if not handle.done.is_set() and not handle.reached:
            handle.late = True
            return False
        if not handle.done.wait(max(0.0, wait)):
            handle.late = True
            logger.info("verbal read: late take=%s, the walk picks as today", session_id)
            return False
        if not handle.result:
            return False
        from services.moment_suggestions import store_context_rewrites
        store_context_rewrites(handle.result.get("rewrites"), arc_id, database=database)
        _keep(str(session_id), handle.result.get("weights") or {})
        return True
    except Exception as error:  # noqa: BLE001 -- the walk as it was
        logger.warning("verbal read: not kept take=%s: %s", session_id, error)
        return False


_kept: dict = {}
_kept_lock = threading.Lock()


def _keep(session_id: str, weights: dict) -> None:
    now = time.monotonic()
    with _kept_lock:
        for key in [k for k, (until, _w) in _kept.items() if until <= now]:
            _kept.pop(key, None)
        while len(_kept) >= _MAX_KEPT:
            _kept.pop(next(iter(_kept)))
        _kept[session_id] = (now + _KEEP_SECONDS, dict(weights))


def kept(session_id: Any) -> dict:
    """The weights this process kept for the Take, or {}."""
    with _kept_lock:
        hit = _kept.get(str(session_id or ""))
    return dict(hit[1]) if hit and hit[0] > time.monotonic() else {}


def for_pick(database: Any, user_id: Any, session: Any) -> Optional[dict]:
    """What the frame reads (`take_feedback_policy_v3.build_shadow_frame`'s
    ``verbal``): this run's weights (``lifts``) and, for a frozen Take, a
    question asked only then, whether the read reaches this speaker
    (``pin``). None without a Take or a person."""
    take_id = str((session or {}).get("id") or "") if isinstance(session, dict) else ""
    if not take_id or not user_id:
        return None
    return {"lifts": kept(take_id), "pin": _once(lambda: _reaches(database, user_id))}


def _reaches(database: Any, user_id: Any) -> bool:
    from services import inner_context
    return bool(inner_context.gather(database, user_id))


def _once(fn: Callable[[], bool]) -> Callable[[], bool]:
    box: list = []

    def call() -> bool:
        if not box:
            box.append(bool(fn()))
        return box[0]
    return call
