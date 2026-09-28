"""How well a shadow cue agrees with coaches (founder 2026-09-28, D3a).

A shadow-stage detector may be promoted to `detected` — and start routing
exercises — only once its verdicts have been checked against coaches'
independent judgments. This module computes that comparison. It decides
nothing: promotion is a migration a person writes after reading it.

WHAT THE COMPARISON CAN AND CANNOT SAY. A coach's judgment here is naming the
error on a practice moment (coach_moment_error_event), after their own blind
rating. They never see a shadow verdict, so the two are independent. But a
coach only ever names what is PRESENT; nothing records "checked, and absent".
So:

  * caught — of the moments a coach named this cue on, how many the detector
    fired on. Answerable.
  * false alarms — how often the detector fires where a coach would say no.
    NOT answerable from this data, and reported as unknown rather than
    guessed. A blind yes/no audit sample would answer it.

Internal only. No number here reaches a speaker or a coach.
"""
from __future__ import annotations

from typing import Any, Optional

#: THE PROMOTION BAR (founder 2026-09-28, D3a): a shadow cue may be proposed
#: for `detected` only once at least 30 coach-named moments have been measured
#: and it fired on at least 80% of them. Proposed, not promoted: promotion is
#: still a migration a person writes. Changing the bar is the founder's call.
PROMOTION_MIN_NAMED = 30
PROMOTION_MIN_CAUGHT_RATE = 0.8


def summarise(observations: list[dict], coach_named: list[dict]) -> dict:
    """One cue's verdicts against the moments coaches named it on."""
    by_snippet = {str(o.get("snippet_id")): bool(o.get("fired"))
                  for o in observations if isinstance(o, dict)}
    measured = len(by_snippet)
    fired = sum(1 for v in by_snippet.values() if v)
    named = {str(m.get("snippet_id")) for m in coach_named
             if isinstance(m, dict) and m.get("snippet_id")}
    named_measured = [s for s in named if s in by_snippet]
    caught = sum(1 for s in named_measured if by_snippet[s])
    return {
        "clips_measured": measured,
        "clips_fired": fired,
        "fire_rate": round(fired / measured, 3) if measured else None,
        "coach_named": len(named),
        "coach_named_measured": len(named_measured),
        "caught": caught,
        "caught_rate": (round(caught / len(named_measured), 3)
                        if named_measured else None),
        "false_alarm_rate": None,
        "false_alarm_note": ("unknown: coaches record only what is present; "
                             "a blind yes/no audit sample is needed"),
    }


def meets_bar(summary: dict, *, min_named: int,
              min_caught_rate: float) -> tuple[bool, Optional[str]]:
    """Whether a cue clears a bar. Callers pass PROMOTION_MIN_NAMED and
    PROMOTION_MIN_CAUGHT_RATE; the arguments stay explicit so no call site
    can fall back to a bar nobody chose."""
    if summary.get("coach_named_measured", 0) < min_named:
        return False, (f"only {summary.get('coach_named_measured', 0)} "
                       f"coach-named moments measured; the bar needs {min_named}")
    rate = summary.get("caught_rate")
    if rate is None or rate < min_caught_rate:
        return False, f"caught {rate}; the bar needs {min_caught_rate}"
    return True, None


def report(database: Any, *, detector_version: str,
           cues: tuple[str, ...]) -> dict:
    """The comparison for every cue, read from the database."""
    return {
        cue: summarise(
            database.list_verbal_cue_shadow_observations(
                cue, detector_version),
            database.list_coach_named_moments(cue))
        for cue in cues
    }
