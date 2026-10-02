"""The delayed blind human measure, exercise-human-delayed-v1 (founder
2026-10-01; Phase 5 of the after-practice paths), dark behind
``Config.DELAYED_MEASURE_ENABLED`` (on from 2026-10-02, N25: the founder
signed docs/MEASURE-exercise-human-delayed-v1.md and answered C1 to C3
himself, N24, N23).

The definition is written BEFORE any data: which attempt (the first valid
among the first three, F7), which horizon (seven days), what counts as
better (the quorum-settled ladder, after above before), who may not vote
(the speaker; the coach who handled the moment; anyone already exposed).
Fallback rungs and rewrite practices are excluded. Nothing here reaches a
speaker, and nothing here trains anything.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

MEASURE_VERSION = "exercise-human-delayed-v1"
HORIZON_DAYS = 7
CLIPS = ("before", "after")
RATER_KINDS = ("peer", "coach")
_LADDER = {"no": 0, "in_between": 1, "yes": 2}


def delayed_measure_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "DELAYED_MEASURE_ENABLED", False))


# ── the pair ───────────────────────────────────────────────────────────────

def pair_for_practice(practice: Any, attempts: Iterable[Any],
                      trace: Any) -> tuple[Optional[dict], Optional[str]]:
    """(the pair row to enrol, None) or (None, the exclusion named). Pure.

    The after is the FIRST VALID attempt (F7); the before is the original
    moment's clip. A rewrite or plain practice, a fallback rung, or a
    practice with no valid attempt makes no pair."""
    from services.exercise_learning_readiness import endpoint_attempt
    row = practice if isinstance(practice, dict) else {}
    if str(row.get("kind") or "exercise") != "exercise":
        return None, "not_an_exercise"
    if isinstance(trace, dict) and trace.get("fallback"):
        return None, "fallback"
    endpoint = endpoint_attempt(list(attempts or []))
    if not isinstance(endpoint, dict) or not endpoint.get("id"):
        return None, "no_valid_attempt"
    if not row.get("snippet_id") or not row.get("id"):
        return None, "no_moment"
    return {
        "practice_id": str(row["id"]),
        "owner_user_id": str(row.get("owner_user_id") or ""),
        "take_session_id": str(row.get("take_session_id") or ""),
        "before_snippet_id": str(row["snippet_id"]),
        "after_attempt_id": str(endpoint["id"]),
        "exercise_id": row.get("exercise_id"),
        "exercise_version": row.get("exercise_version"),
        "measure_version": MEASURE_VERSION,
        "practice_closed_at": row.get("closed_at"),
    }, None


def enrol(database: Any, practice: Any) -> Optional[dict]:
    """Enrol one closed practice's pair, insert-once. None when off, when
    excluded, or when the write fails (logged). Never raises."""
    if not delayed_measure_enabled():
        return None
    try:
        attempts = database.list_confident_voice_practice_attempts(str(practice.get("id")))
        assignment = database.get_confident_voice_exercise_assignment(
            str(practice.get("take_session_id") or ""), str(practice.get("snippet_id") or ""))
        trace = (database.get_exercise_match_trace(str(assignment.get("id")))
                 if isinstance(assignment, dict) and assignment.get("id") else None)
        pair, why_not = pair_for_practice(practice, attempts, trace)
        if pair is None:
            _log.info("delayed measure: practice %s excluded (%s)", practice.get("id"), why_not)
            return None
        return database.insert_delayed_measure_pair(pair)
    except Exception as e:  # noqa: BLE001 — bookkeeping behind the close
        _log.warning("delayed measure enrol failed practice=%s: %s",
                     (practice or {}).get("id"), e, exc_info=True)
        return None


# ── the horizon and the clips ─────────────────────────────────────────────

def ripe(pair: Any, *, now: Optional[datetime] = None) -> bool:
    """Seven days after the practice closed, the pair's clips may be judged."""
    closed = (pair or {}).get("practice_closed_at")
    if not closed:
        return False
    try:
        when = datetime.fromisoformat(str(closed).replace("Z", "+00:00"))
    except ValueError:
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (now or datetime.now(timezone.utc)) - when >= timedelta(days=HORIZON_DAYS)


def clips_for_listener(database: Any, *, listener_id: str) -> list[dict]:
    """The ripe pairs' clips as Lend your ear candidates: two unlabelled
    clips per pair carrying the pair id (so one set never holds both and
    the partner waits a day), never the speaker's own. [] off."""
    if not delayed_measure_enabled():
        return []
    out: list[dict] = []
    voted = {(str(v.get("pair_id")), str(v.get("clip"))) for v in
             (database.list_delayed_measure_votes_by_rater(str(listener_id)) or [])
             if isinstance(v, dict)}
    # Q3-A (founder 2026-10-02): another user hears a clip of somebody's
    # voice only with that recording's own switch on; switching it off
    # pulls the clip from both pools at once. A pair's clips are the
    # original moment and its attempt: both ride the original's share.
    shared = {str(r.get("snippet_id")) for r in (database.list_shared_clips_live() or [])
              if isinstance(r, dict) and r.get("snippet_id")}
    for pair in database.list_delayed_measure_pairs_open() or []:
        if not isinstance(pair, dict) or str(pair.get("owner_user_id")) == str(listener_id):
            continue
        if str(pair.get("before_snippet_id") or "") not in shared:
            continue
        if not ripe(pair):
            continue
        pid = str(pair.get("id"))
        for clip in CLIPS:
            if (pid, clip) in voted:
                continue
            out.append({"clip_id": f"{pid}:{clip}", "source": "delayed", "pair_id": pid,
                        "stratum": "unknown", "pair": pair, "clip": clip})
    return out


def audio_for(database: Any, candidate: dict) -> tuple[Optional[str], Any]:
    """(audio ref, duration) for one pair clip, resolved like any other."""
    from services.audio_ref_resolver import resolve_playable_ref
    from services.snippet_audio_url import resolve_snippet_audio_url
    pair = candidate.get("pair") or {}
    if candidate.get("clip") == "before":
        snippet = database.get_snippet_by_id(str(pair.get("before_snippet_id") or "")) or {}
        return (resolve_snippet_audio_url(snippet, database=database)
                or resolve_playable_ref(snippet.get("audio_segment_path")), snippet.get("duration_ms"))
    attempt = database.get_confident_voice_practice_attempt(str(pair.get("after_attempt_id") or "")) or {}
    return resolve_playable_ref(attempt.get("audio_ref")), attempt.get("duration_ms")


# ── the vote ───────────────────────────────────────────────────────────────

def may_vote(database: Any, *, pair: dict, rater_id: str, rater_kind: str) -> Optional[str]:
    """None when the rater may vote on this pair, else why not: the
    speaker, the coach who handled the moment (correction 6), or a rater
    already exposed to either clip (task 4)."""
    if str(pair.get("owner_user_id")) == str(rater_id):
        return "own_clip"
    take, snippet = str(pair.get("take_session_id") or ""), str(pair.get("before_snippet_id") or "")
    if rater_kind == "coach" and database.coach_handled_moment(str(rater_id), take, snippet):
        return "handled_the_moment"
    exposed = getattr(database, "rater_exposed_to", None)
    if exposed is not None and exposed(str(rater_id), [snippet, str(pair.get("after_attempt_id") or "")]):
        return "exposed"
    return None


def vote(database: Any, *, pair_id: str, clip: str, rater_id: str, rater_kind: str,
         value: Any, blind: bool = True) -> tuple[int, dict]:
    """One vote per rater per clip, under the exclusions. (status, payload)."""
    from services.state_ratings import VALUES
    if not delayed_measure_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    if clip not in CLIPS or rater_kind not in RATER_KINDS or value not in VALUES:
        return 400, {"code": "INVALID_INPUT", "error": "clip, rater_kind or value is not valid"}
    pair = database.get_delayed_measure_pair(str(pair_id))
    if not isinstance(pair, dict):
        return 404, {"code": "NOT_FOUND", "error": "pair not found"}
    why_not = may_vote(database, pair=pair, rater_id=str(rater_id), rater_kind=rater_kind)
    if why_not:
        return 409, {"code": "MAY_NOT_VOTE", "error": "This rater may not vote on this pair.",
                     "reason": why_not}
    saved = database.insert_delayed_measure_vote({
        "pair_id": str(pair_id), "clip": clip, "rater_id": str(rater_id),
        "rater_kind": rater_kind, "value": str(value), "blind": bool(blind),
        "measure_version": MEASURE_VERSION,
    })
    if not isinstance(saved, dict):
        return 409, {"code": "ALREADY_VOTED", "error": "One vote per clip."}
    return 200, {"recorded": True}


# ── the outcome ────────────────────────────────────────────────────────────

def settled_value(votes: Iterable[Any]) -> Optional[str]:
    """The quorum-settled ternary for one clip, from blind votes shaped
    like label rows; None until settled."""
    from services.label_quorum import SETTLED_STATUSES, resolve
    rows = [{"value": v.get("value"), "lane": "coach" if v.get("rater_kind") == "coach" else "game_peer",
             "rater_id": v.get("rater_id"), "self_report": False}
            for v in votes if isinstance(v, dict) and v.get("blind", True)]
    verdict = resolve(rows)
    if verdict.get("status") not in SETTLED_STATUSES:
        return None
    value = verdict.get("value")
    return str(value) if value in _LADDER else None


def pair_outcome(votes: Iterable[Any]) -> str:
    """better | same | worse | pending, read only once both clips settled."""
    rows = [v for v in votes if isinstance(v, dict)]
    before = settled_value(v for v in rows if v.get("clip") == "before")
    after = settled_value(v for v in rows if v.get("clip") == "after")
    if before is None or after is None:
        return "pending"
    if _LADDER[after] > _LADDER[before]:
        return "better"
    return "same" if _LADDER[after] == _LADDER[before] else "worse"


def report(database: Any) -> dict:
    """Per exercise: pairs enrolled and settled, the share better. Founder
    only; the interval is the fair test's bootstrap when a split exists."""
    out: dict[str, dict] = {}
    if not delayed_measure_enabled():
        return {"measure_version": MEASURE_VERSION, "enabled": False, "exercises": out}
    for pair in database.list_delayed_measure_pairs_open() or []:
        if not isinstance(pair, dict):
            continue
        key = str(pair.get("exercise_id") or "?")
        entry = out.setdefault(key, {"enrolled": 0, "settled": 0, "better": 0, "same": 0, "worse": 0})
        entry["enrolled"] += 1
        outcome = pair_outcome(database.list_delayed_measure_votes(str(pair.get("id"))) or [])
        if outcome != "pending":
            entry["settled"] += 1
            entry[outcome] += 1
    return {"measure_version": MEASURE_VERSION, "enabled": True, "exercises": out}
