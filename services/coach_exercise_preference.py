"""The coach's exercise preference, F8 (founder 2026-10-01; Phase 1b of the
coach panel), dark behind ``Config.COACH_EXERCISE_PREFERENCE_ENABLED``.

F8: "When a coach keeps, swaps or replaces the exercise the machine served,
that explicit choice is recorded as the coach's preference. It may propose
a ranking, but only outcomes decide whether an exercise helps. Coach-chosen
exercises never enter the fair test; their outcomes stay in their own
pile."

WHAT IS RECORDED (append-only, provenance ``coach_preference``, migration
0411): the moment, the coach, the speaker; the exercise the machine served
with its version; the draw it came from (top, exploration, the deterministic
singleton, a fallback rung, or coach-chosen) and the fit (exact, trial,
general, warm-up); the errors that fired and the signal rules, from the
frozen match trace; the action (kept, swapped, new); on a swap, the exercise
chosen and whether it was in the pool the trace ranked. Keep is explicit:
silence records nothing. Never mixed with adequacy labels, detector
verdicts, F6 answers, confidence labels or owner answers (L3). Purged with
the speaker's Take AND with the coach.

THE SWAP LIST is the eligible pool from the frozen trace's ranked
candidates, shuffled, no rank and no score shown; the served one is marked
"served". Decision 3 (migration 0398) holds: a coach-chosen exercise stays a
coach_chosen assignment, the fair test leaves it out, its outcomes sit in the
with_coach_picks pile, and the live order keeps reading machine draws only.

THE SECOND RANKER, exercise-coach-preferred-v1 (sealed like the learned
order): orders the eligible pool by keep against swap-away, rates compared
within the same draw (top with top, exploration with exploration), learned
only from split_of == "train" speakers, a rate trusted at MIN_ACTIONS
actions per exercise, graded by the same fair test against outcomes. It
never promotes itself. A swap outside the pool keeps "attach teaches the
library": recorded, never a ranking preference.
"""
from __future__ import annotations

import logging
import random
from collections import Counter, defaultdict
from typing import Any, Callable, Iterable, Optional

_log = logging.getLogger(__name__)

ACTIONS = ("kept", "swapped", "new")
DRAWS = ("top", "exploration", "deterministic_singleton", "fallback", "coach_chosen")
RANKER_VERSION = "exercise-coach-preferred-v1"
#: Actions per exercise (within one draw) before its rate is trusted.
MIN_ACTIONS = 30
PROVENANCE = "coach_preference"


def preference_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "COACH_EXERCISE_PREFERENCE_ENABLED", False))


# ── what was served, and the swap list ────────────────────────────────────

def _draw_of(assignment: dict, trace: Any) -> str:
    from services.confident_voice_practice import (
        COACH_REQUEST_POLICY_VERSION, COACH_REVIEW_POLICY_VERSION,
    )
    policy = str(assignment.get("matching_policy_version") or "")
    if policy in (COACH_REQUEST_POLICY_VERSION, COACH_REVIEW_POLICY_VERSION) \
            or assignment.get("selection_mode") == "coach_chosen":
        return "coach_chosen"
    if isinstance(trace, dict) and trace.get("fallback"):
        return "fallback"
    mode = str(assignment.get("selection_mode") or "")
    return mode if mode in DRAWS else "top"


def _labels(database: Any) -> dict:
    rows = (database.list_speaking_errors() or []
            if hasattr(database, "list_speaking_errors") else [])
    return {str(r.get("error_id")): r.get("label")
            for r in rows if isinstance(r, dict) and r.get("error_id")}


def _exercise(database: Any, exercise_id: Any) -> dict:
    row = database.get_active_diagnostic_exercise(str(exercise_id or "")) if exercise_id else None
    return row if isinstance(row, dict) else {}


def _pool_ids(trace: dict, served_id: str, rng: Any) -> list[str]:
    """The ranked candidates of the frozen trace, the served one included,
    shuffled: no rank, no score."""
    ids = [str(c.get("exercise_id")) for c in (trace.get("candidates") or [])
           if isinstance(c, dict) and c.get("outcome") == "ranked" and c.get("exercise_id")]
    if served_id and served_id not in ids:
        ids.append(served_id)
    (rng or random.Random()).shuffle(ids)
    return ids


def _treats(trace: dict, served_id: str, labels: dict) -> list[dict]:
    targets = sorted({t for c in (trace.get("candidates") or [])
                      if isinstance(c, dict) and str(c.get("exercise_id")) == served_id
                      for t in (c.get("main_targets") or [])})
    return [{"error_id": t, "label": labels.get(t) or t} for t in targets]


def served_view(database: Any, *, take_session_id: str, snippet_id: str,
                rng: Any = None) -> Optional[dict]:
    """The exercise the machine served on this moment, the pool it could
    have swapped to (shuffled, no rank, the served one marked), and the
    frozen facts the record needs. None when no exercise was drawn."""
    assignment = database.get_confident_voice_exercise_assignment(
        str(take_session_id), str(snippet_id))
    if not isinstance(assignment, dict):
        return None
    trace_row = database.get_exercise_match_trace(str(assignment.get("id") or ""))
    trace = trace_row.get("trace") if isinstance(trace_row, dict) else None
    trace = trace if isinstance(trace, dict) else {}
    served_id = str(assignment.get("selected_exercise_id") or "")
    pool_ids = _pool_ids(trace, served_id, rng)
    rows = {eid: _exercise(database, eid) for eid in pool_ids}
    served = rows.get(served_id) or {}
    return {
        "served": {
            "exercise_id": served_id,
            "version": assignment.get("selected_exercise_version"),
            "title": served.get("title"),
            "instruction": served.get("instruction"),
            "treats": _treats(trace, served_id, _labels(database)),
        },
        "draw": _draw_of(assignment, trace),
        "fit": trace.get("fit"),
        "fired": sorted(str(t) for t in (trace.get("observed_tags") or [])),
        "signal_rules_version": trace.get("signal_rules_version"),
        "pool": [{"exercise_id": eid, "served": eid == served_id,
                  **{k: rows[eid].get(k) for k in ("title", "instruction")}}
                 for eid in pool_ids if rows[eid] or eid == served_id],
    }


# ── the record ─────────────────────────────────────────────────────────────

def record(database: Any, *, coach_id: str, take_session_id: str, snippet_id: str,
           speaker_user_id: Optional[str], body: Any) -> tuple[int, dict]:
    """One explicit choice: kept, swapped (to a named exercise), or new
    (an exercise authored now, named when known). (status, payload)."""
    if not preference_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    fields: dict = body if isinstance(body, dict) else {}
    action = fields.get("action")
    if action not in ACTIONS:
        return 400, {"code": "INVALID_INPUT", "error": "action must be kept, swapped or new"}
    chosen = fields.get("chosen_exercise_id")
    if chosen is not None and (not isinstance(chosen, str) or not chosen.strip()):
        return 400, {"code": "INVALID_INPUT", "error": "chosen_exercise_id must be a string"}
    view = served_view(database, take_session_id=take_session_id, snippet_id=snippet_id)
    if view is None:
        return 404, {"code": "NO_SERVED_EXERCISE",
                     "error": "The machine served no exercise on this moment."}
    served_id = view["served"]["exercise_id"]
    if action == "swapped":
        if not chosen or chosen == served_id:
            return 400, {"code": "INVALID_INPUT",
                         "error": "A swap names a different exercise."}
    pool_ids = {p["exercise_id"] for p in view["pool"]}
    row = database.insert_coach_exercise_preference({
        "take_session_id": str(take_session_id), "snippet_id": str(snippet_id),
        "coach_id": str(coach_id), "speaker_user_id": str(speaker_user_id or ""),
        "served_exercise_id": served_id,
        "served_exercise_version": view["served"].get("version"),
        "draw": view["draw"], "fit": view.get("fit"),
        "fired_errors": view["fired"],
        "signal_rules_version": view.get("signal_rules_version"),
        "action": action,
        "chosen_exercise_id": chosen if action != "kept" else None,
        "chosen_in_pool": (chosen in pool_ids) if action == "swapped" else None,
        "provenance": PROVENANCE,
    })
    if not isinstance(row, dict):
        return 500, {"code": "V2_ERROR", "error": "Could not record the choice."}
    return 201, {"preference": {
        "id": str(row.get("id")), "action": action, "served_exercise_id": served_id,
        "chosen_exercise_id": row.get("chosen_exercise_id"),
        "chosen_in_pool": row.get("chosen_in_pool"), "created_at": row.get("created_at"),
    }}


# ── the second ranker (sealed; never promotes itself) ─────────────────────

def preference_rates(rows: Iterable[Any]) -> dict[tuple[str, str], dict]:
    """{(exercise_id, draw): {kept, swapped_away, actions, rate, trusted}}
    from preference rows; rate = kept / (kept + swapped away), compared only
    within one draw. A "new" counts as a swap away. Pure."""
    out: dict[tuple[str, str], dict] = {}
    for row in rows:
        if not isinstance(row, dict) or not row.get("served_exercise_id"):
            continue
        key = (str(row["served_exercise_id"]), str(row.get("draw") or "top"))
        entry = out.setdefault(key, {"kept": 0, "swapped_away": 0})
        if row.get("action") == "kept":
            entry["kept"] += 1
        elif row.get("action") in ("swapped", "new"):
            entry["swapped_away"] += 1
    for entry in out.values():
        actions = entry["kept"] + entry["swapped_away"]
        entry["actions"] = actions
        entry["rate"] = round(entry["kept"] / actions, 3) if actions else None
        entry["trusted"] = actions >= MIN_ACTIONS
    return out


def _train_rates(rows: Iterable[Any]) -> dict[tuple[str, str], dict]:
    """``preference_rates`` over study-group ("train") speakers only."""
    from services.exercise_fair_test import split_of
    return preference_rates(
        r for r in rows or []
        if isinstance(r, dict) and split_of(str(r.get("speaker_user_id") or "")) == "train")


def _ordered(rates: dict, pool_ids: Iterable[str], draw: str) -> Optional[list[str]]:
    ids = [str(i) for i in pool_ids]
    if not ids or any(not rates.get((i, draw), {}).get("trusted") for i in ids):
        return None
    return sorted(ids, key=lambda i: (-float(rates[(i, draw)]["rate"] or 0.0), i))


def coach_preferred_order(database: Any, pool_ids: Iterable[str], *,
                          draw: str) -> Optional[list[str]]:
    """The pool ordered by trusted keep rate within `draw`, learned from
    train-split speakers only; None unless every exercise in the pool has
    a trusted rate (a partial order is no order). Never served live."""
    return _ordered(_train_rates(database.list_coach_exercise_preferences() or []),
                    pool_ids, draw)


def preferred_choose(rows: Iterable[Any]) -> Callable[[dict], Optional[str]]:
    """exercise-coach-preferred-v1 as the fair test's candidate (35g-7, W6
    2026-10-05: "graded by the same fair test"). On each evaluation unit:
    the top of its own pool by trusted keep rate within the unit's own draw
    (``coach_preferred_order``'s rule, learned from study-group speakers);
    where any pooled exercise has no trusted rate, today's fixed ranking (a
    partial order is no order). Graded on exam-group speakers by
    ``exercise_fair_test.compare``; it never serves and never promotes."""
    from services.exercise_fair_test import fixed_ranking
    rates = _train_rates(rows)

    def choose(unit: dict) -> Optional[str]:
        order = _ordered(rates, unit.get("pool") or (), str(unit.get("draw") or "top"))
        return order[0] if order else fixed_ranking(unit)
    return choose


def graded(rows: Iterable[Any], units: list[dict]) -> dict:
    """The ranker's fair test, beside what it learned from. Pure."""
    from services.exercise_fair_test import compare, split_of
    rows = [r for r in rows or [] if isinstance(r, dict)]
    train = [r for r in rows
             if split_of(str(r.get("speaker_user_id") or "")) == "train"]
    rates = _train_rates(rows)
    return {
        "version": RANKER_VERSION,
        "learned_from": {"actions": len(train),
                         "speakers": len({str(r.get("speaker_user_id") or "") for r in train}),
                         "trusted_rates": sum(1 for v in rates.values() if v.get("trusted"))},
        "fair_test": compare(units, preferred_choose(rows)),
    }


def ledger(database: Any) -> dict:
    """Per exercise: kept, swapped, new; the most common swaps A → B.
    Founder only; counts about the library, never about a person."""
    rows = [r for r in (database.list_coach_exercise_preferences() or []) if isinstance(r, dict)]
    per: dict[str, Counter] = defaultdict(Counter)
    swaps: Counter = Counter()
    for row in rows:
        per[str(row.get("served_exercise_id"))][str(row.get("action"))] += 1
        if row.get("action") == "swapped" and row.get("chosen_exercise_id"):
            swaps[(str(row["served_exercise_id"]), str(row["chosen_exercise_id"]))] += 1
    return {
        "ranker_version": RANKER_VERSION, "min_actions": MIN_ACTIONS,
        "per_exercise": {eid: {a: counts.get(a, 0) for a in ACTIONS} for eid, counts in per.items()},
        "top_swaps": [{"from": a, "to": b, "count": n} for (a, b), n in swaps.most_common(10)],
    }
