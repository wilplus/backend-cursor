"""The founder's labels as the golden set for both pickers (N702).

The founder labels moments in the Pattern Library, on their own app Takes
and on Training Corpus clips (``speaking_pattern_examples``). Until N702
nothing read those labels. This read lines each label on an app Take up
against what the app actually served on that Take, and counts agreement.
It changes nothing that is served: it is a founder-only report.

THE MOMENT PICKER. What a Take showed is its frozen selection
(``ideal_text_feedback_sets.selected_keys``: insert-once per Take, each key
carrying the snippet it landed on; the same freeze the coach queue marks as
"bookmarked"). A label of ``error`` or ``praise`` agrees when the picker
showed that clip; a ``control`` label (nothing to say here) agrees when it
did not; ``unsure`` is left out.

THE INTERVENTION PICKER. What a moment got is its exercise assignment
(``confident_voice_exercise_assignments``, one per Take and clip). On an
``error`` label the founder's tool and the served exercise are listed side
by side. Agreement is counted only where the meaning is unambiguous:
nothing served and no tool chosen, or something served and a tool chosen.
Which exercise id matches which of the founder's tools (Sniper, AI Audio,
Rephrase, Coach video) has no mapping in the library yet, so a tool-for-tool
rate is not computed: the pairs are shown instead, never a guess.

Training Corpus labels have no served walk, so they are counted, not
compared. Nothing here reaches a speaker; no score is shown to one.
"""
from __future__ import annotations

import logging
from typing import Any

from services import speaking_patterns

logger = logging.getLogger(__name__)

#: Labels read per report; the founder's library is far below this.
MAX_LABELS = 2000
MOMENT_KINDS = ("error", "praise", "control")


def _labels(database: Any, curator: str) -> list[dict]:
    query = speaking_patterns.examples_for(database, curator)
    return list(query.order("created_at").limit(MAX_LABELS).execute().data or [])


def _shown(database: Any, user: str, take: str) -> set | None:
    """The clips this Take's walk showed, or None when unknown (no Take, no
    frozen selection yet, or a read that failed)."""
    from services.take_feedback_set import sanitize_selected_keys
    try:
        session = database.takes.v2_get_session(take, user)
        arc = str((session or {}).get("arc_id") or "")
        if not arc or str((session or {}).get("user_id") or "") != str(user):
            return None
        frozen = database.get_ideal_text_feedback_set(arc, take)
    except Exception:
        logger.warning("picker golden: the frozen selection was not read for %s", take, exc_info=True)
        return None
    if not frozen:
        return None
    return {str(key["snippet_id"]) for key in sanitize_selected_keys(frozen.get("selected_keys"))
            if key.get("snippet_id")}


def _served(database: Any, take: str) -> dict | None:
    """Clip id to the exercise it was given on this Take, or None unread."""
    try:
        rows = (database.client.table("confident_voice_exercise_assignments")
                .select("snippet_id,selected_exercise_id").eq("take_session_id", take)
                .limit(500).execute().data or [])
    except Exception:
        logger.warning("picker golden: exercises were not read for %s", take, exc_info=True)
        return None
    return {str(r["snippet_id"]): str(r["selected_exercise_id"]) for r in rows if r.get("snippet_id")}


def _tool(label: dict) -> str | None:
    value = label.get("intervention")
    return str(value["tool"]) if isinstance(value, dict) and value.get("tool") else None


def compare(labels: list[dict], shown_by_take: dict, served_by_take: dict) -> dict:
    """Pure: the report from the labels and what each Take served."""
    moment = {"agree": 0, "differ": 0, "unknown": 0}
    intervention = {"agree": 0, "differ": 0, "unknown": 0}
    cases: list[dict] = []
    corpus = 0
    for label in labels:
        if label.get("source") != "take":
            corpus += 1
            continue
        kind = label.get("kind")
        if kind not in MOMENT_KINDS:
            continue
        take, clip = str(label.get("session_id")), str(label.get("snippet_id"))
        shown = shown_by_take.get(take)
        picked = None if shown is None else clip in shown
        if picked is None:
            moment["unknown"] += 1
            moment_agrees = None
        else:
            moment_agrees = picked if kind in ("error", "praise") else not picked
            moment["agree" if moment_agrees else "differ"] += 1
        served_map = served_by_take.get(take)
        served = None if served_map is None else served_map.get(clip)
        tool = _tool(label)
        tool_agrees = None
        if kind == "error":
            if served_map is None:
                intervention["unknown"] += 1
            else:
                tool_agrees = bool(served) == bool(tool)
                intervention["agree" if tool_agrees else "differ"] += 1
        cases.append({
            "example_id": label.get("id"), "session_id": take, "snippet_id": clip,
            "kind": kind, "pattern": label.get("pattern"),
            "picker_showed": picked, "moment_agrees": moment_agrees,
            "your_tool": tool, "served_exercise": served, "tool_agrees": tool_agrees,
        })
    return {"moment": moment, "intervention": intervention, "corpus_labels": corpus,
            "cases": cases}


def report(database: Any, curator: str) -> dict:
    """GET /v2/user/speaking-patterns/golden: the founder's own labels."""
    labels = _labels(database, curator)
    takes = sorted({str(r["session_id"]) for r in labels
                    if r.get("source") == "take" and r.get("kind") in MOMENT_KINDS})
    shown = {take: _shown(database, curator, take) for take in takes}
    served = {take: _served(database, take) for take in takes}
    return compare(labels, shown, served)
