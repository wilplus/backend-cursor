"""How well a shadow cue agrees with coaches (founder 2026-09-28, D3a;
amended 2026-10-05, decisions log N48.5 Q24 A).

A shadow-stage detector may be promoted to `detected` — and start routing
exercises — only once its verdicts have been checked against coaches'
independent judgments. This module computes that comparison. It decides
nothing: promotion is a migration a person writes after reading it.

WHAT COUNTS AS A COACH'S JUDGMENT (Q24 A, founder 2026-10-05: "coaches' Yes
answers in the blind error audit are what promote a shadow cue"). The coach
answers the library's own question about one error on a sampled clip, blind
(services.error_presence_audit: Yes, No, Can't tell; no verdict, no read, no
earlier answer shown). A Yes is a coach hearing the error on that clip. It
replaces the bar of "30 named by coaches": naming a pattern on the moment was
retired by N45 Q9, and the practice-attached naming path has no screen, so
that count could never grow. The named moments are still reported, as
history, never as the bar.

  * audit_yes — coaches' Yes answers for the cue, on clips sampled under the
    detector version being judged.
  * caught — of those, the share the detector fired on when the clip was
    sampled: the audit's catch rate, each answer weighted by its clip's
    sampling probability (the report card's, so a stratified sample cannot
    flatter it). The existing rule, kept: at least 80%.
  * false alarms — from the same audit's No answers on clips the detector
    fired on (``error_presence_audit.false_alarm_rate``), None below its
    floor.

A cue the audit does not sample (not in ``error_presence_audit.errors_in_scope``,
e.g. the two acoustic cues, whose library questions ask about the absence of
the error) has no Yes to count and is never READY; ``audited`` says so.

Internal only. No number here reaches a speaker or a coach.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

#: THE PROMOTION BAR (founder 2026-09-28, D3a; Q24 A, 2026-10-05): a shadow
#: cue may be proposed for `detected` only once coaches have answered Yes in
#: the blind error audit at least 30 times for it at its detector version,
#: and the detector fired on at least 80% of those moments. Proposed, not
#: promoted: promotion is still a migration a person writes. Changing the
#: bar is the founder's call.
PROMOTION_MIN_YES = 30
PROMOTION_MIN_CAUGHT_RATE = 0.8


def audit_summary(rows: Iterable[Any], *, detector_version: Optional[str] = None) -> dict:
    """The blind audit's answers for one cue: Yes, No and Can't tell, and
    the catch rate over the Yes answers (weighted by sampling probability,
    as the report card weighs them). Only rows sampled under
    ``detector_version`` when one is given. Pure."""
    from services.error_presence_audit import _boxes
    kept = [r for r in rows or [] if isinstance(r, dict) and r.get("answer")
            and (detector_version is None
                 or str(r.get("detector_version")) == str(detector_version))]
    boxes = _boxes(kept)
    return {
        "audit_yes": sum(1 for r in kept if r.get("answer") == "yes"),
        "audit_no": sum(1 for r in kept if r.get("answer") == "no"),
        "audit_cant_tell": sum(1 for r in kept if r.get("answer") == "cant_tell"),
        "caught": boxes["counts"]["caught"],
        "caught_rate": boxes["catch_rate"],
    }


def summarise(observations: list[dict], coach_named: list[dict],
              audit_rows: Iterable[Any] = (), *,
              detector_version: Optional[str] = None, audited: bool = True) -> dict:
    """One cue's verdicts, the blind audit's answers on it (the bar), and
    the moments coaches once named it on (history)."""
    by_snippet = {str(o.get("snippet_id")): bool(o.get("fired"))
                  for o in observations if isinstance(o, dict)}
    measured = len(by_snippet)
    fired = sum(1 for v in by_snippet.values() if v)
    named = {str(m.get("snippet_id")) for m in coach_named
             if isinstance(m, dict) and m.get("snippet_id")}
    named_measured = [s for s in named if s in by_snippet]
    return {
        "clips_measured": measured,
        "clips_fired": fired,
        "fire_rate": round(fired / measured, 3) if measured else None,
        "audited": bool(audited),
        **audit_summary(audit_rows, detector_version=detector_version),
        # History (N45 Q9 retired naming on the moment): never the bar.
        "coach_named": len(named),
        "coach_named_measured": len(named_measured),
        "false_alarm_rate": None,
        "false_alarm_note": ("unknown: below the blind audit's floor of answers"
                             if audited else "not in the blind audit"),
    }


def meets_bar(summary: dict, *, min_yes: int,
              min_caught_rate: float) -> tuple[bool, Optional[str]]:
    """Whether a cue clears a bar. Callers pass PROMOTION_MIN_YES and
    PROMOTION_MIN_CAUGHT_RATE; the arguments stay explicit so no call site
    can fall back to a bar nobody chose."""
    if not summary.get("audited", True):
        return False, "not in the blind error audit, so no coach has answered Yes"
    if summary.get("audit_yes", 0) < min_yes:
        return False, (f"only {summary.get('audit_yes', 0)} coaches' Yes answers "
                       f"in the blind audit; the bar needs {min_yes}")
    rate = summary.get("caught_rate")
    if rate is None or rate < min_caught_rate:
        return False, f"caught {rate}; the bar needs {min_caught_rate}"
    return True, None


def report(database: Any, *, detector_version: str,
           cues: tuple[str, ...]) -> dict:
    """The comparison for every cue, read from the database."""
    from services.error_presence_audit import errors_in_scope, false_alarm_rate
    in_scope = set(errors_in_scope())
    out = {}
    for cue in cues:
        audited = cue in in_scope
        out[cue] = summarise(
            database.list_verbal_cue_shadow_observations(cue, detector_version),
            database.list_coach_named_moments(cue),
            database.list_error_presence_audit_answered(cue) if audited else [],
            detector_version=detector_version, audited=audited)
    # 6a (0411): false alarms from the blind audit's answers on clips the
    # detector fired on; None below the floor or while the audit is off.
    for cue, summary in out.items():
        rate = false_alarm_rate(database, error_id=cue, detector_version=detector_version)
        if rate is not None:
            summary["false_alarm_rate"] = rate
            summary["false_alarm_note"] = "from the blind error audit (0411)"
    return out
