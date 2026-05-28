"""Session-1 completion gate for the cold-start interview funnel.

MVP1 satisfaction check (per the brainstorm + the BE handoff for
task 6): a guest interview session is "session 1 complete" iff
ALL THREE of these hold:

  (a) ≥ 1 snippet with question_tone = "charisma"
  (b) ≥ 1 snippet with question_tone = "stress"
  (c) sum of snippet duration_ms ≥ 60_000  (= 60s of accepted audio)

Replaces the legacy 30s-duration-only gate. The 30s was satisfiable
with five stress answers and zero charisma answers — extractor got
nothing useful for the charisma highlight reel, /results rendered
half-empty. This gate forces both intents AND a real minimum of
voice to work with.

Why this lives in its own module
--------------------------------
Two callers today:
  - POST /v2/public/interview/upload-answer surfaces the gate state
    on every turn so the FE can render live progress ("X / 1
    charisma answers, Ys / 60s audio")
  - The frontend uses the same shape to decide when to fire its
    onThresholdReached callback

A third caller (the finalize chain) may consult this when the
trigger pipeline (AI commentary + stickiness + signup CTA) wants
a server-authoritative readiness check. Centralising the predicate
here keeps all three reading the same definition.

Per-snippet question_tone is set at upload-answer time from the
FE-supplied form field. We don't need a separate per-recording
`prompt_intent` column — the snippet IS the granularity at which
intent matters (one guest session shares one parent recording but
has N snippets, each with its own tone).

Scope note: this gate applies to the **guest funnel cold-start**
session only. Retention loop / roleplay sessions have different
completion semantics (3-turn cap, 120s duration, etc.) and are
intentionally outside this helper's contract.
"""
from __future__ import annotations

import logging
from typing import Any

from services.db import db


logger = logging.getLogger(__name__)


# Minimum accepted audio seconds across all snippets in the session.
# Configurable per-call (the route can override for testing /
# alternate flows) but defaults to the brainstorm's spec value.
DEFAULT_THRESHOLD_SECONDS = 60

# Tones counted toward gate satisfaction. "ebcp" / "trust" / etc.
# don't count for either bucket — the gate is specifically about
# charisma vs stress balance.
_CHARISMA_TONE = "charisma"
_STRESS_TONE = "stress"


def session_1_completion_state(
    session_id: str,
    *,
    threshold_seconds: int = DEFAULT_THRESHOLD_SECONDS,
) -> dict[str, Any]:
    """Evaluate the three-criterion completion gate for a session.

    Returns the dict shape the FE consumes verbatim on every
    upload-answer response::

        {
          "session_1_complete": bool,
          "session_1_gate": {
            "charisma_count":    int,
            "stress_count":      int,
            "duration_seconds":  float,
            "threshold_seconds": int,            # echoed so FE
                                                  # never hardcodes 60
            "missing": ["charisma" | "stress" | "duration", ...]
                                                  # empty when complete
          }
        }

    Best-effort: a DB read failure returns the "all zeros, all
    missing" shape so the FE keeps the recorder open rather than
    crashing or fake-completing the session. The structured log
    line below is the audit trail when this happens.

    Pure read — no writes, no LLM, no side effects. Cheap (one
    indexed query on charisma_snippets by session_id).
    """
    charisma_count = 0
    stress_count = 0
    duration_ms_total = 0

    try:
        rows = db.get_snippets_by_session(session_id) or []
    except Exception as e:
        logger.warning(
            "completion_gate: snippet load failed sid=%s err=%s "
            "— returning empty state (gate stays closed)",
            session_id, e,
        )
        rows = []

    for row in rows:
        tone = (row.get("question_tone") or "").strip().lower()
        if tone == _CHARISMA_TONE:
            charisma_count += 1
        elif tone == _STRESS_TONE:
            stress_count += 1
        # Duration sums across ALL snippets regardless of tone —
        # a "ebcp" or untagged turn still counts toward the
        # 60-second minimum, it just doesn't satisfy a tone bucket.
        d = row.get("duration_ms")
        if isinstance(d, (int, float)) and d > 0:
            duration_ms_total += int(d)

    duration_seconds = duration_ms_total / 1000.0
    has_charisma = charisma_count >= 1
    has_stress = stress_count >= 1
    duration_ok = duration_seconds >= threshold_seconds

    missing: list[str] = []
    if not has_charisma:
        missing.append("charisma")
    if not has_stress:
        missing.append("stress")
    if not duration_ok:
        missing.append("duration")

    complete = has_charisma and has_stress and duration_ok

    return {
        "session_1_complete": complete,
        "session_1_gate": {
            "charisma_count": charisma_count,
            "stress_count": stress_count,
            "duration_seconds": round(duration_seconds, 1),
            "threshold_seconds": threshold_seconds,
            "missing": missing,
        },
    }
