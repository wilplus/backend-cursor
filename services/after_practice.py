"""What the speaker hears after a practice (founder 2026-10-01, F5; Phase 3
of the after-practice paths), dark behind
``Config.PRAISE_AFTER_PRACTICE_ENABLED``.

F5: "After a practice the speaker judges Yes or In-between, one signed
sentence names what measurably changed. If nothing measurably changed, a
plain 'Good job'. It is practice feedback, not a Feedback item, and carries
no budget."

THE SENTENCE DESCRIBES THE ATTEMPT THE SPEAKER LANDED ON (founder
2026-10-01, correction 4). The scorekeeper reads the FIRST valid attempt (F7,
exercise-adequacy-label-v2) and the two may disagree by design: the speaker
hears about the try they chose to stop on; the label is fixed in advance so
that choice cannot move it. Do not "fix" one to agree with the other.

WHAT "MEASURABLY CHANGED" MEANS, per lane, in this order:
  1. the targeted problem cleared: a detector signal for the practice's
     error fired on the original and none fires on the landed attempt
     (``clip_signals``, cv-exercise-signals-v1: the same detectors, both
     sides);
  2. one delivery cue moved toward confident by at least ``CUE_GAIN_MIN``
     within-speaker z (``delivery_cues``: the same cue table, the same
     baseline for both sides, read at the attempt and kept beside it as
     ``comparison["cues"]``); the first in the cue table's order wins;
  3. the machine leg: the attempt's stamped confidence is higher than the
     original's (``practice_more_confident.machine_leg``);
  4. nothing: "Good job".
A rewrite practice (29b) compares only attempts of the same accepted text,
never the original, and only the delivery (lanes 2 and 4); with a single
attempt it is "Good job" (founder 2026-10-01, Phase 3 addition).

ENCOURAGEMENT (path 3, a practice that did not land): a real measurable
step between the first and the last attempt (lane 2 between attempts), else
the effort-only line.

Every sentence comes from the closed set below, proposed for the founder's
sign-off and never composed; no number reaches the speaker (AC-9); the
sentence is never a Feedback item (L2) and is stored on the practice as
``after_practice`` for the coach and the audit. Pure except where named.
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

RULE_VERSION = "after-practice-praise-v1"
CUE_READS_VERSION = "delivery-cue-reads-v1"
#: The within-speaker z a cue must gain between the two sides to be said.
#: The same bar as delivery_cues' _MIN_CUE_Z: a cue that moved less than
#: that is noise, and a praise line that cites noise is worse than none.
CUE_GAIN_MIN = 0.5

#: The closed set (proposed 2026-10-01, awaiting founder sign-off): key →
#: (the sentence on Yes, the gentler sentence on In-between).
PRAISE: dict[str, tuple[str, str]] = {
    "cleared:rushing": (
        "You gave the words room this time.",
        "A little more room between the words this time."),
    "cleared:word_compression": (
        "Each word came through whole this time.",
        "The words came through a little more whole this time."),
    "cleared:ending_compression": (
        "You landed the last words this time.",
        "The last words landed a little more this time."),
    "cue:wide_range": (
        "Your voice moved more this time.",
        "Your voice moved a little more this time."),
    "cue:full_volume": (
        "You let the volume move this time.",
        "The volume moved a little more this time."),
    "cue:no_hesitation": (
        "You hesitated less this time.",
        "A little less hesitation this time."),
    "cue:settled_pitch": (
        "Your voice sat lower this time.",
        "Your voice sat a little lower this time."),
    "cue:kept_moving": (
        "You kept moving this time.",
        "You kept moving a little more this time."),
    "cue:landed_ending": (
        "You brought the ending down this time.",
        "The ending came down a little more this time."),
    "cue:opened_strong": (
        "You opened stronger this time.",
        "You opened a little stronger this time."),
    "more_assured": (
        "That sounded more assured than the first.",
        "That sounded a little more assured than the first."),
    "good_job": ("Good job.", "Good job."),
}
#: Path 3 (proposed, awaiting sign-off): a real step between tries, or the
#: effort alone. The cue that moved rides as data for the design, unnamed.
ENCOURAGEMENT: dict[str, str] = {
    "step": "One thing moved between your tries. Keep it.",
    "effort": "You gave it a go. That counts.",
}
VARIANTS = ("yes", "in_between")


def praise_after_practice_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "PRAISE_AFTER_PRACTICE_ENABLED", False))


# ── cue reads: kept beside each attempt, read by the praise ───────────────

def cue_reads(metrics: Any, baseline: Any) -> dict[str, float]:
    """{cue name: within-speaker z toward confident} for the measurable
    cues of one recording, from the one cue table. {} without a baseline."""
    from services.delivery_cues import _contributions
    return {name: round(float(z), 3)
            for name, z, _sign in _contributions(metrics, baseline)}


def cue_key(name: str) -> Optional[str]:
    """The praise vocabulary's key for a cue that moved toward confident."""
    from services.delivery_cues import _CUE_KEYS
    return next((key for (cue, _sign), key in _CUE_KEYS.items() if cue == name), None)


def attach_cue_reads(comparison: dict, *, original_metrics: Any,
                     attempt_metrics: Any, baseline: Any,
                     baseline_kind: Any) -> dict:
    """Both sides read against the same baseline, kept on the attempt's
    comparison blob (additive; no number leaves the row). Pure."""
    if not baseline:
        return comparison
    comparison["cues"] = {
        "version": CUE_READS_VERSION,
        "baseline": baseline_kind if baseline_kind in ("user", "take") else "take",
        "original": cue_reads(original_metrics, baseline),
        "attempt": cue_reads(attempt_metrics, baseline),
    }
    return comparison


def cue_gains(before: Any, after: Any) -> list[tuple[str, float]]:
    """[(praise key, gain)] for every cue that moved toward confident by at
    least CUE_GAIN_MIN, in the cue table's order. Pure."""
    from services.voice_confidence import confidence_cues
    if not isinstance(before, dict) or not isinstance(after, dict):
        return []
    out: list[tuple[str, float]] = []
    for name, _members, _weight in confidence_cues():
        b, a = before.get(name), after.get(name)
        if not isinstance(b, (int, float)) or not isinstance(a, (int, float)) \
                or isinstance(b, bool) or isinstance(a, bool):
            continue
        gain = float(a) - float(b)
        key = cue_key(name)
        if gain >= CUE_GAIN_MIN and key:
            out.append((key, round(gain, 3)))
    return out


# ── the praise ─────────────────────────────────────────────────────────────

def targeted_errors(practice: Any) -> set[str]:
    """The error(s) the practised exercise is written for: its main target,
    else every error its matching names, else the original's fired ones."""
    from services.confident_voice_practice import _SIGNAL_PROBLEM_TAGS
    snapshot = (practice or {}).get("exercise_snapshot")
    criteria = (snapshot.get("matching_criteria")
                if isinstance(snapshot, dict) else None) or {}
    main = (snapshot or {}).get("main_target") if isinstance(snapshot, dict) else None
    main = main or (criteria.get("primary_problem_tag") if isinstance(criteria, dict) else None)
    if isinstance(main, str) and main:
        return {main}
    fired = _fired_signals((practice or {}).get("acoustic_evidence"))
    return {tag for signal in fired for tag in _SIGNAL_PROBLEM_TAGS.get(signal, ())}


def _fired_signals(evidence: Any) -> set[str]:
    signals = evidence.get("signals") if isinstance(evidence, dict) else None
    return {k for k, v in (signals or {}).items() if v} if isinstance(signals, dict) else set()


def cleared_error(practice: Any, attempt: Any) -> Optional[str]:
    """Lane 1: an error the practice targets whose signals fired on the
    original and fire no more on the attempt's snapshot. Pure."""
    from services.confident_voice_practice import _SIGNAL_PROBLEM_TAGS, clip_signals
    targets = targeted_errors(practice)
    if not targets:
        return None
    before = _fired_signals((practice or {}).get("acoustic_evidence"))
    snapshot = (attempt or {}).get("acoustic_metrics")
    after = {k for k, v in clip_signals(snapshot if isinstance(snapshot, dict) else {}).items() if v}
    for error in sorted(targets):
        signals = {s for s, tags in _SIGNAL_PROBLEM_TAGS.items() if error in tags}
        if signals & before and not (signals & after):
            return error
    return None


def _reads(attempt: Any, side: str) -> Any:
    comparison = (attempt or {}).get("comparison")
    cues = comparison.get("cues") if isinstance(comparison, dict) else None
    return cues.get(side) if isinstance(cues, dict) else None


def _confidence(snapshot: Any) -> Any:
    return snapshot.get("confidence") if isinstance(snapshot, dict) else None


def praise_after_practice(practice: Any, attempts: Iterable[Any],
                          landed_attempt_id: Any, answer: Any) -> dict:
    """The one sentence for the attempt the speaker landed on. Pure.

    {"key", "sentence", "variant", "lane", "rule_version", "attempt_index",
     "cue" | "error" where one was named}."""
    rows = [r for r in attempts if isinstance(r, dict)]
    landed = next((r for r in rows if str(r.get("id")) == str(landed_attempt_id)), None)
    variant = "in_between" if answer == "in_between" else "yes"
    base = {"rule_version": RULE_VERSION, "variant": variant,
            "attempt_index": (landed or {}).get("attempt_index")}
    if landed is None:
        return _say("good_job", variant, "none", base)
    if str((practice or {}).get("kind") or "exercise") == "rewrite":
        return _rewrite_praise(rows, landed, variant, base)
    return _original_praise(practice, landed, variant, base)


def _rewrite_praise(rows: list, landed: dict, variant: str, base: dict) -> dict:
    """The accepted text, never the original (Phase 3 addition): the
    previous attempt of the same words, or nothing to compare."""
    index = int(landed.get("attempt_index") or 0)
    earlier = [r for r in rows if int(r.get("attempt_index") or 0) < index]
    previous = max(earlier, key=lambda r: int(r.get("attempt_index") or 0), default=None)
    gains = cue_gains(_reads(previous, "attempt"), _reads(landed, "attempt")) if previous else []
    if gains:
        return _say(f"cue:{gains[0][0]}", variant, "cue", base, cue=gains[0][0])
    return _say("good_job", variant, "none", base)


def _original_praise(practice: Any, landed: dict, variant: str, base: dict) -> dict:
    """Lanes 1 to 4 against the original clip."""
    from services.practice_more_confident import machine_leg
    error = cleared_error(practice, landed)
    if error and f"cleared:{error}" in PRAISE:
        return _say(f"cleared:{error}", variant, "cleared", base, error=error)
    gains = cue_gains(_reads(landed, "original"), _reads(landed, "attempt"))
    if gains:
        return _say(f"cue:{gains[0][0]}", variant, "cue", base, cue=gains[0][0])
    evidence = (practice or {}).get("acoustic_evidence")
    original = evidence.get("snapshot") if isinstance(evidence, dict) else None
    if machine_leg(_confidence(original), _confidence(landed.get("acoustic_metrics"))) == "higher":
        return _say("more_assured", variant, "machine_leg", base)
    return _say("good_job", variant, "none", base)


def encouragement(attempts: Iterable[Any]) -> dict:
    """Path 3: a real step between the first and the last attempt, else the
    effort alone. Pure."""
    rows = sorted((r for r in attempts if isinstance(r, dict)),
                  key=lambda r: int(r.get("attempt_index") or 0))
    gains = (cue_gains(_reads(rows[0], "attempt"), _reads(rows[-1], "attempt"))
             if len(rows) >= 2 else [])
    if gains:
        return {"key": "step", "sentence": ENCOURAGEMENT["step"], "cue": gains[0][0],
                "rule_version": RULE_VERSION}
    return {"key": "effort", "sentence": ENCOURAGEMENT["effort"],
            "rule_version": RULE_VERSION}


def _say(key: str, variant: str, lane: str, base: dict, **named: Any) -> dict:
    yes, gentle = PRAISE[key]
    return {**base, "key": key, "lane": lane,
            "sentence": gentle if variant == "in_between" else yes, **named}


# ── the hooks the live loop calls (never raise) ───────────────────────────

def after_landing(database: Any, practice: Any, attempts: Iterable[Any],
                  landed_attempt_id: Any, answer: Any) -> Optional[dict]:
    """The praise for a practice that landed, kept on the practice row.
    None when the switch is off or the write fails."""
    if not praise_after_practice_enabled():
        return None
    try:
        said = praise_after_practice(practice, attempts, landed_attempt_id, answer)
        return said if _keep(database, practice, said) else None
    except Exception as e:  # noqa: BLE001 — never costs the judgement
        _log.warning("praise after practice failed practice=%s: %s",
                     (practice or {}).get("id"), e, exc_info=True)
        return None


def after_dismissal(database: Any, practice: Any) -> Optional[dict]:
    """The encouragement for a practice the speaker left, kept on the row.
    Reads the attempts itself, so the route's fence stays."""
    if not praise_after_practice_enabled():
        return None
    try:
        attempts = database.list_confident_voice_practice_attempts(
            str((practice or {}).get("id") or "")) or []
        said = encouragement(attempts)
        return said if _keep(database, practice, said) else None
    except Exception as e:  # noqa: BLE001 — never costs the close
        _log.warning("encouragement failed practice=%s: %s",
                     (practice or {}).get("id"), e, exc_info=True)
        return None


def _keep(database: Any, practice: Any, said: dict) -> bool:
    return database.update_confident_voice_practice(
        str(practice.get("id")), str(practice.get("owner_user_id") or ""),
        {"after_practice": said}) is not None
