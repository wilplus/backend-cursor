"""Did a practised exercise hold into the next Take? (founder 2026-10-18,
Linear WIL-29; concept docs/history/CONCEPT-per-user-exercise-effectiveness-2026-10-18.md;
migration 0476.)

Every other measure asks whether an exercise helped the moment it was
practised on, minutes later. This one asks whether it held: when the
speaker recorded the whole talk again, did the problem the exercise
targeted come back on that passage?

THE RULE, exercise-held-next-take-v1, fixed before any data is read:

  * one library-exercise practice gives at most one result, decided when
    the speaker's NEXT Take of the same project is ready (founder: "next
    time is the next Take of the same project"); a later Take never
    revises it (the table refuses UPDATE);
  * only a practice tried before that Take was recorded counts: a try made
    afterwards cannot have shaped it;
  * the targeted problems come from the practice's frozen match trace, read
    exactly as the scorekeeper reads them (``targeted_problems``);
  * the passage is found by its words: the clip of the next Take whose
    transcript passes the same exact-passage guard a practice attempt
    passes (``passage_alignment``). A paragraph rewritten, split or cut is
    ``unknown``, never ``held`` (founder default, 2026-10-18);
  * "fires" is the same detector under the same signal rules and the same
    library vocabulary the trace was written under; a rule change in
    between is ``unknown``.

Best-effort by contract: it runs after the Take is ready, beside the shadow
logs, and a Take is never slower or worse for its speaker because of it.
Same consent boundary as every exercise path ("Personalised practice").

Never a label, never shown to a speaker or a coach (AC-9). Counts about
exercises go on the founder's pace panel; one person's list on the
founder's view of their page.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

RULE_VERSION = "exercise-held-next-take-v1"
TABLE = "exercise_held_next_take_outcomes"
OUTCOMES = ("held", "came_back", "unknown")


def _trace_for(practice: dict, traces: Iterable[Any]) -> Optional[dict]:
    """The frozen trace of the moment this practice was opened on, whose
    candidates name the practice's exercise."""
    snippet_id = str(practice.get("snippet_id") or "")
    exercise_id = str(practice.get("exercise_id") or "")
    for row in traces:
        if not isinstance(row, dict) or str(row.get("snippet_id")) != snippet_id:
            continue
        trace = row.get("trace")
        if isinstance(trace, dict) and any(
                isinstance(c, dict) and str(c.get("exercise_id")) == exercise_id
                for c in trace.get("candidates") or ()):
            return trace
    return None


def _find_passage(passage: str, snippets: Iterable[Any]) -> Optional[dict]:
    """The next Take's clip that says the practised passage, by the same
    guard a practice attempt passes; the closest when several do."""
    from services.confident_voice_practice import passage_alignment
    best: Optional[tuple[float, dict]] = None
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        heard = str(snippet.get("transcript") or "")
        fit = passage_alignment(passage, heard)
        if fit["matches"] and (best is None or fit["ratio"] > best[0]):
            best = (float(fit["ratio"]), snippet)
    return best[1] if best else None


def _unknown(reason: str, **fields: Any) -> dict:
    return {"outcome": "unknown", "unknown_reason": reason,
            "still_firing": [], "next_snippet_id": None, **fields}


def decide(practice: dict, trace: Optional[dict], snippets: list[dict], *,
           signal_rules_version: str) -> dict:
    """One practice's result against its next Take's clips. Pure."""
    from services.confident_voice_practice import (
        _audio_reliable, acoustic_snapshot, clip_signals, observed_problem_tags,
    )
    from services.exercise_learning_readiness import targeted_problems

    if not isinstance(trace, dict):
        return _unknown("no_trace", targeted_problems=[],
                        signal_rules_version=None)
    rules = trace.get("signal_rules_version")
    targets = sorted(targeted_problems(trace, str(practice.get("exercise_id") or "")))
    base = {"targeted_problems": targets, "signal_rules_version": rules}
    if trace.get("fallback") or not targets:
        return _unknown("no_targeted_problem", **base)
    if rules != signal_rules_version:
        return _unknown("rules_changed", **base)
    found = _find_passage(str(practice.get("exact_passage") or ""), snippets)
    if found is None:
        return _unknown("passage_not_found", **base)
    snap = acoustic_snapshot(found)
    if not _audio_reliable(found, snap):
        return {**_unknown("audio_unreliable", **base),
                "next_snippet_id": str(found.get("id") or "") or None}
    fired = observed_problem_tags({"signals": clip_signals(snap)},
                                  vocabulary=trace.get("vocabulary") or None)
    still = sorted(set(targets) & fired)
    return {"outcome": "came_back" if still else "held", "unknown_reason": None,
            "still_firing": still, "next_snippet_id": str(found.get("id") or "") or None,
            **base}


# ------------------------------------------------------------------ reads

def _rows(query: Any) -> list[dict]:
    return [r for r in (query.execute().data or []) if isinstance(r, dict)]


def _previous_take(client: Any, take: dict) -> Optional[dict]:
    """The Take of the same project just before this one: by the project's
    own Take number, else (an older Take with none) by when it was made."""
    project_id = take.get("project_id")
    if not project_id:
        return None
    query = client.table("v2_sessions").select("id").eq("project_id", str(project_id))
    if take.get("take_index") is not None:
        query = (query.lt("take_index", int(take["take_index"]))
                 .order("take_index", desc=True))
    elif take.get("created_at"):
        query = query.lt("created_at", str(take["created_at"])).order("created_at", desc=True)
    else:
        return None
    rows = _rows(query.limit(1))
    return rows[0] if rows else None


def _tried_before(client: Any, practice_ids: list[str], cutoff: str) -> set[str]:
    """The practices with a try saved before ``cutoff`` (the next Take)."""
    if not practice_ids:
        return set()
    rows = _rows(client.table("confident_voice_practice_attempt")
                 .select("practice_id").in_("practice_id", practice_ids)
                 .lt("created_at", cutoff))
    return {str(r.get("practice_id")) for r in rows}


def results_for_take(database: Any, take_session_id: str) -> list[dict]:
    """The rows this Take decides: one per library-exercise practice on the
    Take before it (same project), tried before this one was recorded."""
    from services.confident_voice_practice import SIGNAL_RULES_VERSION
    client = database.client
    takes = _rows(client.table("v2_sessions").select("id,project_id,take_index,created_at")
                  .eq("id", str(take_session_id)).limit(1))
    take = takes[0] if takes else None
    previous = _previous_take(client, take) if take else None
    if not take or not previous:
        return []
    practices = _rows(client.table("confident_voice_practice")
                      .select("id,owner_user_id,project_id,take_session_id,snippet_id,"
                              "exercise_id,exact_passage,kind")
                      .eq("take_session_id", str(previous["id"])))
    practices = [p for p in practices if (p.get("kind") or "exercise") == "exercise"
                 and p.get("exercise_id")]
    tried = _tried_before(client, [str(p["id"]) for p in practices],
                          str(take["created_at"]))
    practices = [p for p in practices if str(p["id"]) in tried]
    if not practices:
        return []
    traces = _rows(client.table("confident_voice_exercise_match_traces")
                   .select("snippet_id,trace").eq("take_session_id", str(previous["id"])))
    snippets = database.get_snippets_by_session(str(take_session_id)) or []
    out = []
    for practice in practices:
        result = decide(practice, _trace_for(practice, traces), snippets,
                        signal_rules_version=SIGNAL_RULES_VERSION)
        out.append({
            "practice_id": str(practice["id"]),
            "owner_user_id": str(practice.get("owner_user_id")),
            "project_id": str(practice.get("project_id") or take["project_id"]),
            "practice_take_id": str(previous["id"]),
            "next_take_id": str(take_session_id),
            "exercise_id": str(practice["exercise_id"]),
            "rule_version": RULE_VERSION,
            **result,
        })
    return out


def record_take(database: Any, take_session_id: str) -> int:
    """Decide and store, insert-once, every result this Take decides.
    Returns the rows offered. Best-effort: the caller runs it under the
    DegradationLog after the Take is ready."""
    from services.verbal_cues import _practice_permitted
    if not take_session_id or not _practice_permitted(database, take_session_id):
        return 0
    rows = results_for_take(database, take_session_id)
    if rows:
        (database.client.table(TABLE)
         .upsert(rows, on_conflict="practice_id", ignore_duplicates=True).execute())
    return len(rows)


def held_counts(database: Any) -> dict:
    """Counts about exercises for the founder's pace panel: per exercise,
    how many practices held, came back, or could not be read, and why."""
    rows = _rows(database.client.table(TABLE)
                 .select("exercise_id,outcome,unknown_reason"))
    exercises: dict[str, dict] = {}
    for row in rows:
        slot = exercises.setdefault(str(row.get("exercise_id")), {
            "held": 0, "came_back": 0, "unknown": 0, "unknown_reasons": {}})
        outcome = str(row.get("outcome"))
        if outcome in OUTCOMES:
            slot[outcome] += 1
        if outcome == "unknown":
            reason = str(row.get("unknown_reason") or "")
            slot["unknown_reasons"][reason] = slot["unknown_reasons"].get(reason, 0) + 1
    return {"rule_version": RULE_VERSION, "exercises": exercises}
