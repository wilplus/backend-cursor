"""Versions per error, the shadow log for acoustic detectors, and the
detector fair test (founder 2026-10-01; Phases 6b and 6c of the coach
panel).

6b. Every error has detector versions in three stages, like
confidence_rollout: ``off``, ``shadow``, ``live``. ``LIVE_DETECTOR`` names
the version in force per error; changing it is a reviewed PR after the
founder's yes, rolling back is one line. Every version in shadow or live
writes one verdict per (clip, error, version) into
``verbal_cue_shadow_observations`` (insert-once; the table ML-14 already
extended to acoustic cues), for original moments and for practice attempts
(Phase 5 asks for audits on attempts). The live version is written into
every match trace beside ``signal_rules_version``.

6c. The fair test grades every version on the SAME audited clips from
HELD-OUT speakers (``exercise_fair_test.split_of``): catch rate and
false-alarm rate, each with a speaker-resampled interval, from the blind
answers of Phase 6a. The promotion bar: better on one rate and not worse on
the other on held-out speakers, after at least four weeks in shadow. The
bar is a verdict the founder reads; nothing here flips a version.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Optional

_log = logging.getLogger(__name__)

STAGES = ("off", "shadow", "live")
ERRORS = ("rushing", "word_compression", "ending_compression")
#: The version in force per error. A change is a reviewed PR after the
#: founder's yes; rolling back is this one line.
LIVE_DETECTOR: dict[str, str] = {
    "rushing": "rules-v1",
    "word_compression": "rules-v1",
    "ending_compression": "rules-v1",
}
SHADOW_WEEKS_MIN = 4
#: A candidate may be this much worse on the other rate and still count as
#: "not worse": the noise of a small held-out set, not a licence.
NOT_WORSE_TOLERANCE = 0.02


def _rules_v1(error_id: str, snapshot: dict) -> Optional[bool]:
    """The live rule: the cv-exercise-signals-v1 thresholds, by the signal
    map of confident_voice_practice; None when nothing is measurable."""
    from services.confident_voice_practice import _SIGNAL_PROBLEM_TAGS, clip_signals
    signals = clip_signals(snapshot)
    mine = [s for s, tags in _SIGNAL_PROBLEM_TAGS.items() if error_id in tags]
    measurable = [s for s in mine if _measurable(s, snapshot)]
    if not measurable:
        return None
    return any(signals.get(s) for s in measurable)


def _measurable(signal: str, snapshot: dict) -> bool:
    needs = {
        "reduced_word_separation": ("median_gap", "tight_gap_share"),
        "compressed_ending": ("ending_duration_ratio",),
        "insufficient_pauses": ("pause_ratio",),
        "dense_articulation": ("word_occupancy",),
        "reduced_intelligibility": ("word_recognition_confidence",),
        "irregular_rushed_pacing": ("pause_regularity",),
    }.get(signal, ())
    return all(isinstance(snapshot.get(k), (int, float)) for k in needs)


#: version -> (stage, detector). A detector takes (error_id, snapshot) and
#: answers True / False / None. Candidates from Phase 6d register here in
#: ``shadow``; nothing becomes ``live`` but by LIVE_DETECTOR.
REGISTRY: dict[str, tuple[str, Callable[[str, dict], Optional[bool]]]] = {
    "rules-v1": ("live", _rules_v1),
}


def register(version: str, detector: Callable[[str, dict], Optional[bool]],
             *, stage: str = "shadow") -> None:
    if stage not in STAGES:
        raise ValueError(f"stage must be one of {STAGES}")
    REGISTRY[version] = (stage, detector)


def stage_of(version: str) -> str:
    if version in LIVE_DETECTOR.values():
        return "live"
    return REGISTRY.get(version, ("off", None))[0]


def live_version_for(error_id: str) -> Optional[str]:
    return LIVE_DETECTOR.get(error_id)


def stamp_live_versions(trace: dict) -> dict:
    """Write the versions in force into a match trace, beside
    signal_rules_version, so every choice says which detector made it."""
    if isinstance(trace, dict):
        trace["detector_versions"] = dict(LIVE_DETECTOR)
    return trace


# ── the shadow log ─────────────────────────────────────────────────────────

def observations(snapshot: Any, *, clip_id: str, take_session_id: str,
                 clip_kind: str = "snippet", recording_id: Optional[str] = None) -> list[dict]:
    """One row per (error, version) in shadow or live, for one clip's
    snapshot. Pure."""
    snap = snapshot if isinstance(snapshot, dict) else {}
    rows: list[dict] = []
    for version, (stage, detector) in REGISTRY.items():
        if stage_of(version) == "off" and stage != "shadow":
            continue
        for error_id in ERRORS:
            fired = detector(error_id, snap)
            if fired is None:
                continue
            rows.append({
                "take_session_id": str(take_session_id), "snippet_id": str(clip_id),
                "recording_id": recording_id, "error_id": error_id,
                "detector_version": version, "language": "any", "fired": bool(fired),
                "measurements": {k: snap.get(k) for k in (
                    "wpm", "pause_ratio", "pause_regularity", "median_gap", "tight_gap_share",
                    "word_occupancy", "word_recognition_confidence", "ending_duration_ratio")
                    if isinstance(snap.get(k), (int, float))},
                "clip_kind": clip_kind,
            })
    return rows


def record_take(database: Any, take_session_id: str) -> int:
    """Every version's verdict on each clip of a Take, insert-once. Same
    consent boundary as the cues. Best-effort by contract."""
    from services.confident_voice_practice import acoustic_snapshot
    from services.verbal_cues import _practice_permitted
    if not take_session_id or not _practice_permitted(database, take_session_id):
        return 0
    rows: list[dict] = []
    for snippet in database.get_snippets_by_session(str(take_session_id)) or []:
        if isinstance(snippet, dict) and snippet.get("id"):
            rows.extend(observations(acoustic_snapshot(snippet), clip_id=str(snippet["id"]),
                                     take_session_id=str(take_session_id),
                                     recording_id=str(snippet.get("recording_id") or "") or None))
    return int(database.record_verbal_cue_shadow(rows) or 0) if rows else 0


def record_attempt(database: Any, attempt: Any, *, take_session_id: str) -> int:
    """The same verdicts on a practice attempt's saved snapshot (Phase 5:
    the audit samples attempts too)."""
    if not isinstance(attempt, dict) or not attempt.get("id"):
        return 0
    rows = observations(attempt.get("acoustic_metrics"), clip_id=str(attempt["id"]),
                        take_session_id=str(take_session_id), clip_kind="practice_attempt")
    return int(database.record_verbal_cue_shadow(rows) or 0) if rows else 0


# ── the fair test ──────────────────────────────────────────────────────────

def graded_rows(audit_rows: Iterable[dict], verdicts: dict[tuple[str, str], bool], *,
                split_of: Callable[[str], str]) -> list[dict]:
    """The audited clips of held-out speakers, re-labelled with one
    version's verdict (clip_id, error_id) -> fired. Pure."""
    out: list[dict] = []
    for r in audit_rows:
        if not isinstance(r, dict) or r.get("answer") not in ("yes", "no"):
            continue
        if split_of(str(r.get("speaker_user_id") or "")) != "holdout":
            continue
        key = (str(r.get("clip_id")), str(r.get("error_id")))
        if key not in verdicts:
            continue
        out.append({**r, "fired_at_sampling": bool(verdicts[key])})
    return out


def grade(audit_rows: Iterable[dict], verdicts: dict[tuple[str, str], bool], *,
          split_of: Callable[[str], str], rng: Any = None) -> dict:
    """Per error: the four boxes and both rates with speaker-resampled
    intervals, for one version. Pure."""
    from services.error_presence_audit import report_card
    rows = graded_rows(audit_rows, verdicts, split_of=split_of)
    return report_card(rows, rng=rng or random.Random(11))


def promotion_bar(candidate: dict, live: dict, *, shadow_since: Any,
                  now: Optional[datetime] = None) -> dict:
    """Whether a candidate clears the bar on one error: at least four
    weeks in shadow, better on one rate and not worse on the other, on
    held-out speakers. A verdict for the founder; it flips nothing."""
    reasons: list[str] = []
    when = _when(shadow_since)
    if when is None or (now or datetime.now(timezone.utc)) - when < timedelta(weeks=SHADOW_WEEKS_MIN):
        reasons.append(f"fewer than {SHADOW_WEEKS_MIN} weeks in shadow")
    if not candidate.get("enough") or not live.get("enough"):
        reasons.append("not enough blind answers on held-out speakers")
    rates = [candidate.get("catch_rate"), live.get("catch_rate"),
             candidate.get("false_alarm_rate"), live.get("false_alarm_rate")]
    if any(not isinstance(r, (int, float)) or isinstance(r, bool) for r in rates):
        reasons.append("a rate is missing")
        return {"clears": False, "reasons": reasons}
    c_catch, l_catch, c_fa, l_fa = (float(r) for r in rates)  # type: ignore[arg-type]
    better_catch = c_catch > l_catch
    better_fa = c_fa < l_fa
    not_worse_catch = c_catch >= l_catch - NOT_WORSE_TOLERANCE
    not_worse_fa = c_fa <= l_fa + NOT_WORSE_TOLERANCE
    if not ((better_catch and not_worse_fa) or (better_fa and not_worse_catch)):
        reasons.append("not better on one rate while not worse on the other")
    return {"clears": not reasons, "reasons": reasons,
            "candidate": {"catch_rate": c_catch, "false_alarm_rate": c_fa},
            "live": {"catch_rate": l_catch, "false_alarm_rate": l_fa}}


def _when(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        when = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def fair_test(database: Any, *, rng: Any = None) -> dict:
    """Every registered version against the live one, per error, on the
    audited held-out clips. Founder-only."""
    from services.exercise_fair_test import split_of
    audit_rows = [r for r in (database.list_error_presence_audit_answered_all() or []) if isinstance(r, dict)]
    out: dict[str, dict] = {}
    for version in REGISTRY:
        verdicts = {(str(o.get("snippet_id")), str(o.get("error_id"))): bool(o.get("fired"))
                    for o in (database.list_shadow_observations_by_version(version) or [])
                    if isinstance(o, dict)}
        out[version] = {"stage": stage_of(version),
                        "per_error": grade(audit_rows, verdicts, split_of=split_of, rng=rng)}
    verdicts_by_error: dict[str, dict] = {}
    for error_id, live_version in LIVE_DETECTOR.items():
        live = out.get(live_version, {}).get("per_error", {}).get(error_id, {})
        verdicts_by_error[error_id] = {
            version: promotion_bar(out[version]["per_error"].get(error_id, {}), live,
                                   shadow_since=database.shadow_since(version))
            for version in REGISTRY if version != live_version
        }
    return {"live": dict(LIVE_DETECTOR), "versions": out, "promotion": verdicts_by_error}
