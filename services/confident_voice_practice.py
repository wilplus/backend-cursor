"""Narrow, optional Confident Voice micro-practice.

This module deliberately does two jobs and no more:

* decide whether the already-selected Confident Voice moment has enough
  acoustic evidence for ``Hear every word``; and
* compare repeated readings of the *same* passage.

It never selects feedback, edits the presentation, or emits a training label.
A retained attempt can be reconciled into the Voice Album only after its own
machine, owner, and professional-coach decisions all say yes.  All numeric
evidence stays in persistence; user payloads receive closed qualitative copy
only.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import statistics
from difflib import SequenceMatcher
from typing import Any, Optional

_log = logging.getLogger(__name__)


EXERCISE_ID = "hear-every-word-v1"
TITLE = "Hear every word"
INSTRUCTION = (
    "Read the same text again, slightly more slowly. Give every word enough "
    "space to be heard clearly without forcing your voice."
)
INTRO_NEAR = (
    "You’re close to a confident delivery here. Your pace is carrying "
    "energy, but some words become compressed. Try the same text again while "
    "giving each word enough space."
)
INTRO_CONFIDENT = (
    "Your original already carries confident energy. This is an optional "
    "refinement: try the same text again while giving each word enough space."
)
INTRO_AFTER_YES = (
    "This already sounds confident. Try this optional refinement to make the "
    "words clearer."
)
INTRO_AFTER_NO = (
    "You’re close. Try this exercise and see whether slowing down makes the "
    "confidence easier to hear."
)
FINAL_STRONGEST = (
    "Listen to this attempt beside your original and decide for yourself."
)
FINAL_QUESTION = "Does this sound better to you than the original?"
UNSUCCESSFUL = (
    "We haven’t found the right adjustment yet. A coach can review this "
    "pattern and may recommend a more suitable exercise."
)

ASSESSMENT_COPY = {
    "recorded_for_comparison":
        "Recorded. Listen to it beside your original and trust your own judgment.",
    "clearer_less_rushed":
        "This sounded clearer and less rushed. Each word had more space.",
    "opening_improved_ending_compressed":
        "The beginning improved, but the ending still became compressed.",
    "faster_than_original":
        "This attempt was faster than the original. Try once more and focus "
        "on hearing the final word.",
    "clearer_choose_natural":
        "Your original already carried strong energy. This version is clearer, "
        "but choose the one that feels more natural to you.",
    "similar_try_ending":
        "This was close to the previous version. Try once more and leave a "
        "little more space around the final words.",
}

_WORD_RE = re.compile(r"[^\w’']+", re.UNICODE)


def _number(value: Any) -> Optional[float]:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _tokens(text: Any) -> list[str]:
    if not isinstance(text, str):
        return []
    return [p for p in (_WORD_RE.sub(" ", text.casefold())).split() if p]


def passage_alignment(expected: str, heard: str) -> dict:
    """Tolerant Whisper alignment for the exact-passage guard.

    A speaker cannot be punished for punctuation or one ASR miss.  The guard
    compares normalized word sequences and requires both broad similarity and
    substantial token coverage.  The numeric fields are stored internally but
    are not returned by any user route.
    """
    exp, got = _tokens(expected), _tokens(heard)
    if not exp or not got:
        return {"matches": False, "ratio": 0.0, "coverage": 0.0}
    ratio = SequenceMatcher(a=exp, b=got, autojunk=False).ratio()
    exp_set = set(exp)
    coverage = sum(1 for token in got if token in exp_set) / max(1, len(exp))
    matches = ratio >= 0.72 and coverage >= 0.65
    return {
        "matches": bool(matches),
        "ratio": round(float(ratio), 4),
        "coverage": round(min(1.0, float(coverage)), 4),
    }


def _word_features(words: Any, duration_ms: Any) -> dict:
    ordered = []
    recognition_confidence = []
    for word in words if isinstance(words, list) else []:
        if not isinstance(word, dict):
            continue
        start, end = _number(word.get("start")), _number(word.get("end"))
        if start is None or end is None or end <= start:
            continue
        ordered.append((start, end))
        confidence = _number(
            word.get("probability")
            if word.get("probability") is not None
            else word.get("confidence")
        )
        if confidence is not None and 0 <= confidence <= 1:
            recognition_confidence.append(confidence)
    ordered.sort()
    if len(ordered) < 4:
        return {"aligned_words": len(ordered)}
    gaps = [max(0.0, ordered[i][0] - ordered[i - 1][1])
            for i in range(1, len(ordered))]
    lengths = [end - start for start, end in ordered]
    ending = lengths[-3:]
    earlier = lengths[:-3] or lengths
    duration = _number(duration_ms)
    duration_s = (duration / 1000.0) if duration and duration > 0 else None
    occupied = sum(lengths) / duration_s if duration_s else None
    return {
        "aligned_words": len(ordered),
        "word_recognition_confidence": (
            statistics.mean(recognition_confidence)
            if recognition_confidence else None
        ),
        "median_gap": statistics.median(gaps) if gaps else None,
        "tight_gap_share": (sum(1 for g in gaps if g < 0.055) / len(gaps))
        if gaps else None,
        "ending_duration_ratio": (
            statistics.mean(ending) / max(0.001, statistics.mean(earlier))
        ),
        "word_occupancy": occupied,
    }


def acoustic_snapshot(snippet: dict) -> dict:
    raw_metrics = snippet.get("metrics")
    metrics: dict = raw_metrics if isinstance(raw_metrics, dict) else {}
    duration_ms = snippet.get("duration_ms")
    wf = _word_features(snippet.get("words"), duration_ms)
    try:
        from services.voice_confidence import stamped_score
        confidence = stamped_score(metrics)
    except Exception:
        confidence = None
    return {
        "wpm": _number(metrics.get("wpm")),
        "pause_ratio": _number(metrics.get("pause_ratio")),
        "pause_regularity": _number(metrics.get("pause_regularity")),
        "voiced_ratio": _number(metrics.get("voiced_ratio")),
        "voiced_duration_sec": _number(metrics.get("voiced_duration_sec")),
        "dynamic_db": _number(metrics.get("dynamic_db")),
        "confidence": confidence,
        **wf,
    }


def machine_confidence_decision(snapshot: dict) -> Optional[str]:
    """Independent machine leg for a selected practice recording.

    This reuses the existing versioned ``confidence`` construct read.  It is
    persisted as provenance, never serialized to the owner or shown to the
    coach before their own explicit judgment.  Missing evidence stays unknown
    rather than being silently converted to a No.
    """
    confidence = _number((snapshot or {}).get("confidence"))
    if confidence is None:
        return None
    return "yes" if confidence >= 0.45 else "no"


def _audio_reliable(snippet: dict, snap: dict) -> bool:
    duration = _number(snippet.get("duration_ms"))
    if duration is None or duration < 2000:
        return False
    if not (snippet.get("audio_segment_path") or snippet.get("audio_ref")):
        return False
    raw_metrics = snippet.get("metrics")
    metrics: dict = raw_metrics if isinstance(raw_metrics, dict) else {}
    quality = metrics.get("audio_quality")
    if isinstance(quality, dict) and (
        quality.get("reliable") is False or quality.get("noise_dominant") is True
    ):
        return False
    voiced = snap.get("voiced_ratio")
    if isinstance(voiced, (int, float)) and not 0.32 <= voiced <= 0.99:
        return False
    return True


def clip_signals(snap: dict) -> dict[str, bool]:
    """The six acoustic problem signals on one clip's snapshot.

    One definition for the original clip (`exercise_eligibility`) and for a
    practice attempt's saved snapshot (the adequacy label, §3.5 item 1:
    "measured by the same detectors"). Part of SIGNAL_RULES_VERSION.
    """
    return {
        "reduced_word_separation": bool(
            (snap.get("median_gap") is not None and snap["median_gap"] < 0.07)
            and (snap.get("tight_gap_share") is not None
                 and snap["tight_gap_share"] >= 0.5)
        ),
        "compressed_ending": bool(
            snap.get("ending_duration_ratio") is not None
            and snap["ending_duration_ratio"] < 0.78
        ),
        "insufficient_pauses": bool(
            snap.get("pause_ratio") is not None and snap["pause_ratio"] < 0.08
        ),
        "dense_articulation": bool(
            snap.get("word_occupancy") is not None
            and snap["word_occupancy"] > 0.78
        ),
        "reduced_intelligibility": bool(
            snap.get("word_recognition_confidence") is not None
            and snap["word_recognition_confidence"] < 0.82
        ),
        "irregular_rushed_pacing": bool(
            snap.get("pause_regularity") is not None
            and snap["pause_regularity"] < 0.5
        ),
    }


def exercise_eligibility(snippet: dict, *, session_median_wpm: Any = None,
                         semantic_or_structural_problem: bool = False) -> dict:
    """Internal eligibility + evidence.  WPM is never sufficient by itself."""
    transcript = (snippet.get("transcript") or "").strip()
    snap = acoustic_snapshot(snippet)
    if semantic_or_structural_problem:
        return {"eligible": False, "reason": "semantic_or_structural"}
    if len(_tokens(transcript)) < 4 or snap.get("aligned_words", 0) < 4:
        return {"eligible": False, "reason": "alignment_or_passage"}
    if not _audio_reliable(snippet, snap):
        return {"eligible": False, "reason": "audio_quality"}

    wpm = snap.get("wpm")
    baseline = _number(session_median_wpm)
    pace_high = bool(
        isinstance(wpm, (int, float)) and
        ((baseline is not None and wpm >= max(baseline + 18.0, baseline * 1.12))
         or (baseline is None and wpm >= 175.0))
    )
    signals = clip_signals(snap)
    supporting_count = sum(1 for value in signals.values() if value)
    confidence = snap.get("confidence")
    if not isinstance(confidence, (int, float)):
        return {"eligible": False, "reason": "confidence_unavailable"}
    pattern = (
        "confident" if confidence >= 0.45 else
        "near_confident" if confidence > 0 else
        "low_confidence_rushing_dominant"
    )
    # A low-confidence moment is eligible only when the rush evidence is
    # overwhelming; this module still cannot surface it unless the manager has
    # independently selected it as Confident Voice feedback.
    threshold = 3 if confidence <= 0 else 2
    eligible = pace_high and supporting_count >= threshold
    return {
        "eligible": bool(eligible),
        "reason": None if eligible else "weak_acoustic_evidence",
        "priority": 3 if pattern == "near_confident" else
                    2 if pattern == "confident" else 1,
        "pattern": pattern,
        "signals": signals,
        "snapshot": snap,
        "pace_high": pace_high,
    }


def _median_wpm(snippets: list[dict]) -> Optional[float]:
    values = []
    for row in snippets:
        raw_metrics = row.get("metrics")
        metrics: dict = raw_metrics if isinstance(raw_metrics, dict) else {}
        value = _number(metrics.get("wpm"))
        if value is not None:
            values.append(value)
    return statistics.median(values) if values else None


_PATTERN_ORDINAL = {
    "low_confidence_rushing_dominant": 0,
    "near_confident": 1,
    "confident": 2,
}


"""The controlled problem vocabulary the exercise catalogue already speaks
(``diagnostic_exercise.acoustic_problem_tags``), mapped from the signals
eligibility already measures.

Until 2026-09-15 this column was written by an administrator and read by
nothing: eligibility computed six acoustic signals, used them to decide
whether to offer an exercise AT ALL, and then discarded them. Matching saw
only how confident the clip sounded, so nothing could route a speaker whose
endings collapse to the exercise that treats collapsing endings.

The mapping is deliberately many-to-one. Six measured signals, three names,
because three is what the catalogue can currently claim. Widening the
vocabulary is a catalogue change and belongs with the error-library table,
not here — a name invented in this file would match no exercise row and
silently rank nothing.

``pace_high`` is deliberately absent. It is REQUIRED for eligibility, so it is
true for every clip that reaches matching; as a tag it would mark all of them
``rushing`` and discriminate between none of them.
"""
_SIGNAL_PROBLEM_TAGS: dict[str, tuple[str, ...]] = {
    "reduced_word_separation": ("word_compression",),
    "dense_articulation": ("word_compression",),
    "reduced_intelligibility": ("word_compression",),
    "compressed_ending": ("ending_compression",),
    "insufficient_pauses": ("rushing",),
    "irregular_rushed_pacing": ("rushing",),
}


def detected_problem_vocabulary(database: Any) -> frozenset[str]:
    """The error ids the library says code can ACTUALLY detect.

    An empty result means the library is unavailable — migration not yet
    applied, or the read failed — and every caller must then skip filtering
    rather than conclude that nothing is detectable. Read the other way, a
    pending migration would drop every tag and silently undo matching.
    """
    if not hasattr(database, "list_speaking_errors"):
        return frozenset()
    rows = database.list_speaking_errors() or []
    return frozenset(
        str(row.get("error_id"))
        for row in rows
        if isinstance(row, dict)
        and row.get("status") == "detected"
        and row.get("error_id")
    )


def observed_problem_tags(
    verdict: Any, *, vocabulary: Any = None,
) -> frozenset[str]:
    """The library's names for the problems that ACTUALLY fired on this clip.

    Internal routing only. These names never reach a user payload, and they are
    a detector verdict — never a coach judgement, never a training label.
    Unknown signal names are ignored rather than guessed at, so adding a signal
    in code cannot invent a tag no exercise can claim.

    ``vocabulary`` is the library's ``detected`` set. When supplied, a tag this
    file maps but the library does not call detectable is dropped: the library
    is the authority on what counts as a recognised error, and code claiming
    otherwise is drift. When it is empty the filter is skipped entirely, so a
    pending migration degrades to the pre-library behaviour.
    """
    if not isinstance(verdict, dict):
        return frozenset()
    signals = verdict.get("signals")
    if not isinstance(signals, dict):
        return frozenset()
    tags: set[str] = set()
    for name, fired in signals.items():
        if fired:
            tags.update(_SIGNAL_PROBLEM_TAGS.get(str(name), ()))
    if vocabulary:
        tags &= set(vocabulary)
    return frozenset(tags)


def problem_tag_overlap(observed: Any, exercise: Any) -> int:
    """How many of the clip's observed problems this exercise claims to treat.

    Counts main and secondary targets alike. Ranking no longer reads it — it
    reads ``exercise_fit`` — but it stays as the plain answer to "does this
    exercise say it treats anything that fired here".
    """
    if not observed or not isinstance(exercise, dict):
        return 0
    main, secondary = exercise_targets(exercise)
    return len((main | secondary) & set(observed))


#: How close an exercise is to what fired on a clip (founder 2026-09-28,
#: decisions D1, D5, D5a, D6). A category, never a number, so there is no
#: closeness figure to leak and anyone can check why an exercise was chosen.
#:
#:   exact  the exercise's MAIN target fired on this clip;
#:   trial  no exercise's main target fired, but this one lists a fired
#:          problem as a SECONDARY target. Shown like any other exercise; kept
#:          apart internally so its outcomes can say whether it helps;
#:   none   nothing it targets fired. Never shown (D1): an exercise with no
#:          spotted problem behind it is a guess, and a guess is not evidence.
FIT_EXACT = "exact"
FIT_TRIAL = "trial"
_FIT_ORDER = {FIT_EXACT: 0, FIT_TRIAL: 1}


def exercise_targets(exercise: Any) -> tuple[frozenset[str], frozenset[str]]:
    """(main targets, secondary targets) as the exercise's author declared them.

    The author names ONE main target in ``matching_criteria.primary_problem_tag``;
    every other tag is secondary. An exercise that names none keeps the claim
    it was written with — every tag is a main target — so the catalogue that
    exists today routes exactly as it did.

    A main target that is declared but no longer among the tags (a teaching
    was undone) leaves NO main target, not every tag: the author said the rest
    were secondary, and promoting them silently would turn trials into exact
    fits nobody chose.
    """
    if not isinstance(exercise, dict):
        return frozenset(), frozenset()
    raw = exercise.get("acoustic_problem_tags")
    tags = frozenset(
        tag for tag in (raw if isinstance(raw, list) else [])
        if isinstance(tag, str) and tag)
    criteria = exercise.get("matching_criteria")
    primary = (criteria.get("primary_problem_tag")
               if isinstance(criteria, dict) else None)
    if not isinstance(primary, str) or not primary:
        return tags, frozenset()
    if primary in tags:
        return frozenset({primary}), tags - {primary}
    return frozenset(), tags


def exercise_fit(observed: Any, exercise: Any) -> Optional[tuple[str, int]]:
    """(fit, how many fired problems it covers at that fit), or None.

    Exact beats trial whatever the counts: one fired main target outranks any
    number of fired secondary ones.
    """
    fired = set(observed or ())
    if not fired:
        return None
    main, secondary = exercise_targets(exercise)
    if hits := len(main & fired):
        return FIT_EXACT, hits
    if hits := len(secondary & fired):
        return FIT_TRIAL, hits
    return None


def confidence_pattern_distance(pattern: str, supported: Any) -> Optional[int]:
    """Deterministic proximity used only to route an eligible exercise.

    It is not a confidence score or an outcome label. Unknown source or
    exercise patterns fail closed.
    """
    source = _PATTERN_ORDINAL.get(str(pattern))
    if source is None or not isinstance(supported, list):
        return None
    values = [
        abs(source - _PATTERN_ORDINAL[value])
        for value in supported
        if value in _PATTERN_ORDINAL
    ]
    return min(values) if values else None


def _editorial(exercise: dict) -> int:
    criteria = exercise.get("matching_criteria")
    return (int(criteria.get("editorial_priority") or 0)
            if isinstance(criteria, dict) else 0)


#: A problem counts as REPEATED for a speaker once it was spotted on at least
#: this many of their earlier Takes (step 7, founder 2026-09-28).
REPEATED_PATTERN_MIN_TAKES = 2
#: How many earlier Takes of each record kind the history reads.
HISTORY_TAKES = 20

EMPTY_HISTORY: dict = {"repeated_patterns": frozenset(),
                       "done_before": frozenset(), "earlier_takes": 0,
                       "available": False}


def speaker_history(database: Any, owner_user_id: Any,
                    take_session_id: Any) -> dict:
    """What the speaker's earlier Takes say, for ranking this one (step 7).

    * repeated_patterns — problems spotted on at least
      REPEATED_PATTERN_MIN_TAKES of their earlier Takes;
    * done_before — exercises they already completed.

    Read from the frozen records of those Takes (as of now, never the current
    one). EMPTY_HISTORY when there is no owner or the read fails: ranking
    then proceeds exactly as without history, rather than on a guess.
    """
    reader = getattr(database, "speaker_exercise_history", None)
    if reader is None or not owner_user_id:
        return dict(EMPTY_HISTORY)
    try:
        raw = reader(str(owner_user_id), str(take_session_id or ""),
                     limit=HISTORY_TAKES)
    except Exception as e:  # noqa: BLE001 — history never costs the offer
        _log.warning("speaker history failed owner=%s take=%s: %s",
                     owner_user_id, take_session_id, e)
        return dict(EMPTY_HISTORY)
    raw = raw if isinstance(raw, dict) else {}
    takes = raw.get("pattern_takes")
    takes = takes if isinstance(takes, dict) else {}
    return {
        "repeated_patterns": frozenset(
            str(tag) for tag, seen in takes.items()
            if isinstance(seen, (list, tuple, set))
            and len(set(seen)) >= REPEATED_PATTERN_MIN_TAKES),
        "done_before": frozenset(
            str(e) for e in raw.get("completed_exercises") or []),
        "earlier_takes": int(raw.get("earlier_takes") or 0),
        "available": True,
    }


def _history_terms(fit: tuple[str, int], observed: Any, exercise: dict,
                   history: Any) -> tuple[int, int]:
    """(repeat hits, done before) for one exercise against one speaker."""
    if not isinstance(history, dict):
        return 0, 0
    main, secondary = exercise_targets(exercise)
    targets = main if fit[0] == FIT_EXACT else secondary
    repeated = history.get("repeated_patterns") or frozenset()
    hits = len(targets & set(observed or ()) & set(repeated))
    done = str(exercise.get("exercise_id") or "") in (
        history.get("done_before") or frozenset())
    return hits, int(done)


#: Positions in the sort key that callers read back.
KEY_DISTANCE, KEY_EDITORIAL, KEY_ID = 5, 6, 7


def _exercise_key(pattern: str, observed_tags: Any,
                  exercise: dict, history: Any = None) -> Optional[tuple]:
    """The one sort key every lane ranks by, or None when the exercise may not
    be offered on this clip at all.

    (fit, -covered, -repeat hits, done before, claimed, confidence distance,
     -editorial, id):

    * fit first — exact before trial (D5);
    * then how many of the clip's fired problems it covers at that fit;
    * then THIS SPEAKER (step 7): an exercise for a problem they keep showing
      beats an equally good one, and one they have not done yet beats one
      they have — ranked after, never removed, so a speaker is never left
      with nothing (contract 35d: not unknowingly repeated);
    * then the SPECIALIST: fewer claimed targets wins a tie. Counting overlap
      alone let an exercise that claims every problem outrank the one written
      for the problem that actually fired;
    * then how well it suits the clip's confidence level, editorial priority,
      and the id, so the order is total and reproducible.
    """
    fit = exercise_fit(observed_tags, exercise)
    if fit is None:
        return None
    distance = confidence_pattern_distance(
        pattern, exercise.get("supported_confidence_patterns"))
    if distance is None:
        return None
    main, secondary = exercise_targets(exercise)
    hits, done = _history_terms(fit, observed_tags, exercise, history)
    return (_FIT_ORDER[fit[0]], -fit[1], -hits, done, len(main | secondary),
            distance, -_editorial(exercise),
            str(exercise.get("exercise_id") or ""))


def fit_of_key(key: Any) -> Optional[str]:
    """The fit a key from ``_exercise_key`` was made at."""
    if not isinstance(key, tuple) or not key:
        return None
    return next((fit for fit, order in _FIT_ORDER.items()
                 if order == key[0]), None)


def matched_exercises(
    pattern: str, exercises: list[dict], *, observed_tags: Any = None,
    history: Any = None,
) -> tuple[Optional[str], list[tuple[tuple, dict]]]:
    """(fit, [(key, exercise), ...] best first) for one clip.

    Only the best fit present is returned (D6): trials fill the gap when no
    exact fit exists, and never compete with one, not even in the 80/20
    exploration slot. Nothing fired, or nothing targets what fired, returns
    (None, []) — no exercise (D1).
    """
    keyed = sorted(
        ((key, exercise) for exercise in exercises
         if (key := _exercise_key(str(pattern), observed_tags, exercise,
                                  history)) is not None),
        key=lambda item: item[0])
    if not keyed:
        return None, []
    best = keyed[0][0][0]
    return fit_of_key(keyed[0][0]), [
        item for item in keyed if item[0][0] == best]


def matching_policy_for(fit: Optional[str]) -> str:
    """The policy version an assignment is frozen under, with its fit.

    One Take's pool is always a single fit (D6), so the fit is a property of
    the whole assignment and rides on its policy version:
    ``exercise-fit-tier-v1:trial`` marks every trial ever served. Internal
    only — the speaker's payload carries the bare version.
    """
    return f"{MATCHING_POLICY_VERSION}:{fit}" if fit else MATCHING_POLICY_VERSION


def fit_from_policy(policy: Any) -> Optional[str]:
    """Inverse of ``matching_policy_for``; None for assignments made before
    fits existed."""
    text = str(policy or "")
    prefix = MATCHING_POLICY_VERSION + ":"
    fit = text[len(prefix):] if text.startswith(prefix) else None
    return fit if fit in _FIT_ORDER else None


#: The schema of one match trace (migration 0384).
MATCH_TRACE_SCHEMA = "exercise-match-trace-v1"

#: The version of the measuring rules a trace was made under: the thresholds
#: in ``exercise_eligibility`` and the signal-to-problem map above. Bump it
#: with any change to either; ``test_the_signal_rules_are_versioned`` fails
#: until you do, because a trace that names the wrong rules explains nothing.
SIGNAL_RULES_VERSION = "cv-exercise-signals-v1"


def _json_safe(value: Any) -> Any:
    """Measurements as JSON: non-finite numbers become null, not an error."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _routing_fields(exercise: dict) -> dict:
    """What an exercise claims, as matching reads it — its catalogue entry."""
    main, secondary = exercise_targets(exercise)
    return {
        "exercise_id": str(exercise.get("exercise_id") or ""),
        "version": int(exercise.get("version") or 1),
        "main_targets": sorted(main),
        "secondary_targets": sorted(secondary),
        "supported_confidence_patterns": sorted(
            str(p) for p in exercise.get("supported_confidence_patterns") or []),
        "editorial_priority": _editorial(exercise),
    }


def _sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def build_match_trace(*, lane: str, verdict: dict, vocabulary: Any,
                      exercises: list[dict], ranked: list[dict],
                      fit: Optional[str], snippet: Any,
                      take_session_id: str, snippet_id: str,
                      history: Any = None) -> dict:
    """Why one moment got the exercise it got (step 2, founder 2026-09-28).

    Every exercise in the offerable catalogue appears once: ``ranked`` (in the
    pool the draw chose from, with its rank) or ``excluded`` with the reason,
    in the order matching tests them. The measurements are copied as they
    were at the moment of choosing, so a later change to a threshold cannot
    rewrite what this choice was based on. No transcript text is copied.

    Internal only: nothing here is serialised to the speaker.
    """
    pattern = str(verdict.get("pattern") or "")
    observed = observed_problem_tags(verdict, vocabulary=vocabulary)
    rank_of = {str(ex.get("exercise_id") or ""): i
               for i, ex in enumerate(ranked, start=1)}
    catalogue = []
    candidates = []
    for exercise in exercises:
        routing = _routing_fields(exercise)
        catalogue.append(routing)
        exercise_id = routing["exercise_id"]
        found = exercise_fit(observed, exercise)
        distance = confidence_pattern_distance(
            pattern, exercise.get("supported_confidence_patterns"))
        hits, done = (_history_terms(found, observed, exercise, history)
                      if found else (0, 0))
        if exercise_id in rank_of:
            outcome, reason = "ranked", None
        elif not observed:
            outcome, reason = "excluded", "nothing_spotted"
        elif found is None:
            outcome, reason = "excluded", "targets_nothing_that_fired"
        elif distance is None:
            outcome, reason = "excluded", "confidence_level_unplaceable"
        else:
            outcome, reason = "excluded", "lower_fit_than_pool"
        candidates.append({
            **routing,
            "outcome": outcome,
            "reason": reason,
            "rank": rank_of.get(exercise_id),
            "fit": found[0] if found else None,
            "covered": found[1] if found else 0,
            "claimed": len(routing["main_targets"])
                       + len(routing["secondary_targets"]),
            "pattern_distance": distance,
            "repeat_hits": hits,
            "done_before": bool(done),
        })
    row = snippet if isinstance(snippet, dict) else {}
    h = history if isinstance(history, dict) else EMPTY_HISTORY
    signals = verdict.get("signals")
    return _json_safe({
        "trace_schema": MATCH_TRACE_SCHEMA,
        "lane": lane,
        "fit": fit,
        "matching_policy_version": matching_policy_for(fit),
        "signal_rules_version": SIGNAL_RULES_VERSION,
        "clip": {
            "snippet_id": str(snippet_id),
            "take_session_id": str(take_session_id),
            "audio_ref": str(row.get("audio_segment_path")
                             or row.get("audio_ref") or ""),
            "start_offset_ms": row.get("start_offset_ms"),
            "duration_ms": row.get("duration_ms"),
        },
        "pattern": pattern,
        "gate": {
            "eligible": bool(verdict.get("eligible")),
            "reason": verdict.get("reason"),
            "pace_high": verdict.get("pace_high"),
        },
        "signals": dict(signals) if isinstance(signals, dict) else {},
        "features": dict(verdict.get("snapshot") or {}),
        "signal_tag_map": {k: list(v) for k, v in _SIGNAL_PROBLEM_TAGS.items()},
        "vocabulary": sorted(vocabulary or ()),
        "vocabulary_available": bool(vocabulary),
        "observed_tags": sorted(observed),
        # What the speaker's earlier Takes said, as of this choice (step 7).
        "history": {
            "available": bool(h.get("available")),
            "repeated_patterns": sorted(h.get("repeated_patterns") or ()),
            "done_before": sorted(h.get("done_before") or ()),
            "earlier_takes": int(h.get("earlier_takes") or 0),
        },
        "catalogue_scope": "offerable_active",
        "catalogue_sha256": _sha256(sorted(
            catalogue, key=lambda r: r["exercise_id"])),
        "candidates": candidates,
    })


def rank_exercises_for_pattern(
    pattern: str, exercises: list[dict], *, observed_tags: Any = None,
) -> list[tuple[int, int, str, dict]]:
    """Complete deterministic order for already reviewed active exercises.

    ``observed_tags`` is the clip's fired problems (``observed_problem_tags``).
    Only exercises at the clip's best fit are returned (``matched_exercises``);
    with nothing fired the list is empty. The tuple shape — (confidence
    distance, -editorial, id, exercise) — is unchanged for every caller.

    This ordering must agree with the offer lanes below, because the
    practice-start route re-ranks here to decide whether an offer has gone
    stale. They all rank through ``matched_exercises`` for that reason.
    """
    _, matched = matched_exercises(
        pattern, exercises, observed_tags=observed_tags)
    return [(key[KEY_DISTANCE], key[KEY_EDITORIAL], key[KEY_ID], exercise)
            for key, exercise in matched]


def reviewed_active_exercises(database: Any) -> list[dict]:
    """Every catalogue row whose assets are live, in catalogue order.

    `get_active_diagnostic_exercise` is the gate: the row must be `active`, and
    must carry both an explanation video and a journal post that is actually
    published. A row that names assets it does not have never reaches matching.
    """
    out: list[dict] = []
    for row in database.list_diagnostic_exercises() or []:
        active = database.get_active_diagnostic_exercise(
            str(row.get("exercise_id") or ""))
        if active:
            out.append(active)
    return out


def rank_exercises_for_clip(
    verdict: Any, database: Any, *, exercises: Optional[list[dict]] = None,
    history: Any = None,
) -> list[tuple[int, int, str, dict]]:
    """THE one composition both ranking paths use.

    The offer path chooses an exercise; the practice-start route re-ranks and
    rejects the offer as EXERCISE_OFFER_STALE if a different one now comes
    first. Composing the pattern, the catalogue and the problem vocabulary in
    two places is how those two silently drift into disagreeing — so they
    compose here, once.

    ``exercises`` lets a caller that already holds the reviewed catalogue pass
    it in rather than read it twice. It must BE ``reviewed_active_exercises``;
    anything else would rank a different pool than the speaker is offered.
    """
    _, matched = match_for_clip(verdict, database, exercises=exercises,
                                history=history)
    return [(key[KEY_DISTANCE], key[KEY_EDITORIAL], key[KEY_ID], exercise)
            for key, exercise in matched]


def match_for_clip(
    verdict: Any, database: Any, *, exercises: Optional[list[dict]] = None,
    history: Any = None,
) -> tuple[Optional[str], list[tuple[tuple, dict]]]:
    """``matched_exercises`` for one clip's verdict against the reviewed
    catalogue: the fit and the keyed pool, best first."""
    pool = (reviewed_active_exercises(database)
            if exercises is None else exercises)
    return matched_exercises(
        str(verdict.get("pattern") or "") if isinstance(verdict, dict) else "",
        pool,
        observed_tags=observed_problem_tags(
            verdict, vocabulary=detected_problem_vocabulary(database),
        ),
        history=history,
    )


def stored_practice_verdict(practice: Any) -> dict:
    """The verdict a practice was OFFERED on, rebuilt from its own row.

    `rank_exercises_for_clip` reads only the pattern and the fired signals,
    and the practice stored both when it was created
    (`machine_assessment.pattern`, `acoustic_evidence.signals`). Reading them
    back rather than recomputing from the snippet means the coach ranks the
    very clip the speaker was offered on, even if the session's median pace
    has moved since.
    """
    row = practice if isinstance(practice, dict) else {}
    assessment = row.get("machine_assessment")
    evidence = row.get("acoustic_evidence")
    return {
        "pattern": (assessment.get("pattern")
                    if isinstance(assessment, dict) else None),
        "signals": (evidence.get("signals")
                    if isinstance(evidence, dict) else None),
    }


def coach_exercise_order(practice: Any, database: Any) -> list[dict]:
    """Every reviewed exercise, best match for THIS clip first.

    FOUNDER 2026-09-25: "show all exercises, best match first". Two halves.

    BEST MATCH FIRST, by the speaker's own rule. The head of this list is
    `rank_exercises_for_clip` on the verdict the practice was offered on, so
    the exercise the coach sees at the top is the one the matcher would pick.
    A second ranking written for the coach would disagree with the speaker's
    sooner or later, and the coach would be judging a list nobody is served.

    ALL OF THEM. The matcher drops an exercise whose confidence patterns it
    cannot place, which is right for choosing one to OFFER but wrong for a
    coach choosing by hand: an exercise they can see in the library must not
    vanish from this list. Those follow the ranked ones, in catalogue order.

    Internal order only — no score, distance or overlap leaves this function.
    """
    pool = reviewed_active_exercises(database)
    row = practice if isinstance(practice, dict) else {}
    ranked = [item[3] for item in rank_exercises_for_clip(
        stored_practice_verdict(practice), database, exercises=pool,
        history=speaker_history(database, row.get("owner_user_id"),
                                row.get("take_session_id")))]
    placed = {str(row.get("exercise_id") or "") for row in ranked}
    return ranked + [
        row for row in pool
        if str(row.get("exercise_id") or "") not in placed
    ]


#: The 80/20 exposure policy (founder 2026-09-26). The frozen draw lives in
#: `confident_voice_exercise_assignments`; see migration 0372.
EXPOSURE_POLICY_VERSION = "exercise-80-20-v1"
MATCHING_POLICY_VERSION = "exercise-fit-tier-v1"

#: `exercise_eligibility` refusals that mean THIS CLIP cannot carry practice
#: at all — too few aligned words, unreliable audio, a verbal problem, no
#: confidence read. Every lane keeps them. The remaining refusal,
#: `weak_acoustic_evidence`, is the rush gate: the legacy lane's way of
#: choosing a moment. V3 already chooses the moment (the weakest block below
#: the neutral band, contract 24f), so on V3's moment it does not apply
#: (founder 2026-09-26: "Follow V3").
_CLIP_REFUSALS = frozenset({
    "semantic_or_structural", "alignment_or_passage", "audio_quality",
    "confidence_unavailable",
})


def clip_can_carry_exercise(verdict: Any) -> bool:
    """Whether a clip passes the safety half of `exercise_eligibility`."""
    if not isinstance(verdict, dict):
        return False
    return bool(verdict.get("eligible")) or (
        verdict.get("reason") == "weak_acoustic_evidence"
        and verdict.get("pattern") is not None)


def _with_default_patterns(active: dict) -> dict:
    if (str(active.get("exercise_id") or "") == EXERCISE_ID
            and not active.get("supported_confidence_patterns")):
        return {**active,
                "supported_confidence_patterns": list(_PATTERN_ORDINAL)}
    return active


def offerable_exercises(database: Any) -> list[dict]:
    """The live catalogue the speaker's offer is chosen from."""
    exercise_rows = (
        database.list_diagnostic_exercises() or []
        if hasattr(database, "list_diagnostic_exercises")
        else [{"exercise_id": EXERCISE_ID}]
    )
    exercises = []
    for row in exercise_rows:
        active = database.get_active_diagnostic_exercise(
            str(row.get("exercise_id") or ""))
        if active:
            exercises.append(_with_default_patterns(active))
    return exercises


def _blocked_by_existing(existing: Any, snippet_id: str) -> bool:
    """One exercise per Take: a finished or declined one ends the offer, and
    an open one keeps its original moment (its passage and audio are bound)."""
    if not existing:
        return False
    if existing.get("status") in ("completed", "dismissed"):
        return True
    return str(existing.get("snippet_id")) != str(snippet_id)


def choose_exercise(ranked: list[dict], *, owner_user_id: str,
                    take_session_id: str, snippet_id: str, lane: str,
                    database: Any, fit: Optional[str] = None,
                    trace: Optional[dict] = None) -> Optional[dict]:
    """The 80/20 choice among a moment's ranked exercises, frozen once.

    The database draws and stores it (migration 0372), so every later read
    of the same moment gets the same exercise. Without the table (not yet
    migrated) or an owner, the best match is served exactly as before.
    Returns None when a frozen choice is no longer in the live catalogue:
    serving a different exercise would contradict the stored assignment.
    """
    if not ranked:
        return None
    assign = getattr(database, "assign_confident_voice_exercise", None)
    if not owner_user_id or assign is None:
        return ranked[0]
    extra = {"trace": trace} if trace is not None else {}
    try:
        assignment = assign(
            **extra,
            owner_user_id=str(owner_user_id),
            take_session_id=str(take_session_id),
            snippet_id=str(snippet_id),
            lane=lane,
            matching_policy_version=matching_policy_for(fit),
            candidates=[{
                "exercise_id": str(item.get("exercise_id") or ""),
                "version": int(item.get("version") or 1),
            } for item in ranked],
        )
    except Exception as e:  # noqa: BLE001 — never lose the feedback
        _log.warning(
            "exercise assignment failed take=%s snip=%s: %s",
            take_session_id, snippet_id, e)
        return ranked[0]
    if not isinstance(assignment, dict):
        return ranked[0]
    selected = str(assignment.get("selected_exercise_id") or "")
    return next((item for item in ranked
                 if str(item.get("exercise_id") or "") == selected), None)


def _offer_payload(exercise: dict, verdict: dict, snippet: dict,
                   chosen: dict, existing: Any) -> dict:
    intro = (exercise.get("confident_introduction_copy")
             if verdict.get("pattern") == "confident" else
             exercise.get("introduction_copy"))
    return {
        "exercise_id": str(exercise.get("exercise_id")),
        "version": int(exercise.get("version") or 1),
        "title": exercise.get("title") or TITLE,
        "instruction": exercise.get("instruction") or INSTRUCTION,
        "introduction": intro or INTRO_NEAR,
        "yes_introduction": INTRO_AFTER_YES,
        "no_introduction": INTRO_AFTER_NO,
        "explanation_video_ref": exercise.get("explanation_video_url"),
        "passage": (snippet.get("transcript") or chosen.get("quote") or "").strip(),
        "practice_id": str(existing.get("id")) if existing else None,
        "resume": bool(existing and existing.get("status") == "open"),
        "matching_policy_version": MATCHING_POLICY_VERSION,
        "pattern_distance": confidence_pattern_distance(
            str(verdict.get("pattern") or ""),
            exercise.get("supported_confidence_patterns"),
        ),
    }


def _done_before(database: Any, owner_user_id: str, exercise_id: str,
                 take_session_id: str) -> bool:
    """THE GREEN "DONE" LABEL (founder 2026-09-26, Q44/Q45 A, contract 35d):
    the owner already completed this exercise on an earlier Take, so the
    product does not repeat it unknowingly. A flag, never a count (AC-9)."""
    check = getattr(database, "completed_exercise_before", None)
    if check is None or not owner_user_id:
        return False
    try:
        return bool(check(str(owner_user_id), str(exercise_id),
                          str(take_session_id or "")))
    except Exception:  # noqa: BLE001 — a label never costs the offer
        return False


def _rewrite_on_same_paragraph(row: dict, rows: list[dict]) -> bool:
    raw_evidence = row.get("evidence")
    evidence: dict = raw_evidence if isinstance(raw_evidence, dict) else {}
    for other in rows:
        other_evidence = other.get("evidence")
        if (other is not row and isinstance(other_evidence, dict)
                and other.get("feedback_family") == "rewrite_clarity"
                and other_evidence.get("slide_index")
                == evidence.get("slide_index")
                and other_evidence.get("paragraph_index")
                == evidence.get("paragraph_index")):
            return True
    return False


def attach_exercise_offer(changes: list[dict], *, take_session_id: str,
                          database: Any, owner_user_id: str = "") -> list[dict]:
    """Attach at most one active exercise after Feedback Manager selection.

    The LEGACY lane: it chooses the moment itself, by the rush gate. V3 Takes
    use `attach_v3_exercise_offer`, where V3 has already chosen the moment.
    """
    rows = [dict(row) for row in (changes or [])]
    candidates = [row for row in rows if row.get("source") == "confident_voice"
                  and row.get("snippet_id")]
    if not candidates or not take_session_id:
        return rows
    exercises = offerable_exercises(database)
    if not exercises:
        return rows
    existing = database.get_confident_voice_practice_by_take(take_session_id)
    if existing:
        candidates = [row for row in candidates if not _blocked_by_existing(
            existing, str(row.get("snippet_id")))]
        if not candidates:
            return rows
    snippet_ids = [str(row["snippet_id"]) for row in candidates]
    snippets = database.get_confident_voice_practice_candidates(snippet_ids) or []
    by_id = {str(row.get("id")): row for row in snippets}
    median_wpm = _median_wpm(
        database.get_snippets_by_session(take_session_id) or [])
    # Read the library and the speaker's history ONCE for the whole take,
    # not per candidate clip.
    vocabulary = detected_problem_vocabulary(database)
    history = speaker_history(database, owner_user_id, take_session_id)
    # (fit, -covered, claimed, distance, -editorial, -priority, id, index)
    ranked: list[tuple[tuple, dict, dict, dict, dict]] = []
    for index, row in enumerate(candidates):
        snippet = by_id.get(str(row.get("snippet_id")))
        if not snippet:
            continue
        verdict = exercise_eligibility(
            snippet,
            session_median_wpm=median_wpm,
            semantic_or_structural_problem=bool(
                row.get("semantic_or_structural_problem")
                or _rewrite_on_same_paragraph(row, rows)),
        )
        if not verdict.get("eligible"):
            continue
        # WHAT WENT WRONG, not just how confident it sounded. The fit leads
        # the sort key, so an exercise that treats this clip's actual
        # problems beats one that merely suits its confidence level.
        _, matched = matched_exercises(
            str(verdict.get("pattern") or ""), exercises,
            observed_tags=observed_problem_tags(
                verdict, vocabulary=vocabulary), history=history)
        for key, exercise in matched:
            ranked.append((
                (*key[:KEY_ID], -int(verdict.get("priority") or 0),
                 key[KEY_ID], index),
                row, snippet, verdict, exercise,
            ))
    if not ranked:
        return rows
    ranked.sort(key=lambda item: item[0])
    top, chosen, snippet, verdict, _ = ranked[0]
    # Each moment's list is already a single fit; the chosen moment's is the
    # best fit on offer anywhere in the Take.
    moment = [item[4] for item in ranked if item[1] is chosen]
    fit = fit_of_key(top)
    served = choose_exercise(
        moment, owner_user_id=owner_user_id, take_session_id=take_session_id,
        snippet_id=str(chosen.get("snippet_id")), lane="legacy_offer",
        database=database, fit=fit, trace=build_match_trace(
            lane="legacy_offer", verdict=verdict, vocabulary=vocabulary,
            exercises=exercises, ranked=moment, fit=fit, snippet=snippet,
            history=history,
            take_session_id=take_session_id,
            snippet_id=str(chosen.get("snippet_id"))))
    if served is None:
        return rows
    chosen["practice_exercise"] = _offer_payload(
        served, verdict, snippet, chosen, existing)
    chosen["practice_exercise"]["done_before"] = _done_before(
        database, owner_user_id, str(served.get("exercise_id") or ""),
        take_session_id)
    return rows


def attach_v3_exercise_offer(
    changes: list[dict], *, take_session_id: str, owner_user_id: str,
    database: Any, ground: Any, verbal_problem: bool = False,
) -> list[dict]:
    """The exercise on the one V3 item that carries it (contract 24f).

    V3 marks exactly one Confident Voice item per Take `bookmark_tier =
    "exercise"`: the weakest below the neutral band. That item gets the best
    matching exercise for its clip under the 80/20 policy. The clip must still
    be able to carry practice (`clip_can_carry_exercise`), and `ground` must
    prove its exact evidence coordinates, which the practice needs; failing
    either, the item is served exactly as V3 made it, without an exercise.

    When nothing fits (D1), the coach hears about it instead
    (``_coach_request_offer``), and an exercise the coach later shares for
    this exact moment is what the item carries.
    """
    rows = [dict(row) for row in (changes or [])]
    target = next((row for row in rows
                   if row.get("source") == "confident_voice"
                   and row.get("bookmark_tier") == "exercise"
                   and row.get("snippet_id")), None)
    if target is None or not take_session_id or verbal_problem:
        return rows
    snippet_id = str(target["snippet_id"])
    existing = database.get_confident_voice_practice_by_take(take_session_id)
    if _blocked_by_existing(existing, snippet_id):
        return rows
    exercises = offerable_exercises(database)
    snippet = next(iter(
        database.get_confident_voice_practice_candidates([snippet_id]) or []),
        None)
    if not isinstance(snippet, dict):
        return rows
    verdict = exercise_eligibility(
        snippet, session_median_wpm=_median_wpm(
            database.get_snippets_by_session(take_session_id) or []))
    if not clip_can_carry_exercise(verdict):
        return rows
    # Nothing spotted on this clip, or nothing in the catalogue targets what
    # was: the item is served exactly as V3 made it — "Let's practice" with
    # no exercise (D1). The clip's confidence level alone never picks one.
    vocabulary = detected_problem_vocabulary(database)
    # History is read only when this moment has not been drawn yet: once it
    # has, the draw is frozen and ranking again changes nothing, and this
    # runs on every poll of the Ideal Text.
    getter = getattr(database, "get_confident_voice_exercise_assignment", None)
    drawn = getter(take_session_id, snippet_id) if getter is not None else None
    history = (dict(EMPTY_HISTORY) if isinstance(drawn, dict)
               else speaker_history(database, owner_user_id, take_session_id))
    fit, keyed = matched_exercises(
        str(verdict.get("pattern") or ""), exercises,
        observed_tags=observed_problem_tags(verdict, vocabulary=vocabulary),
        history=history)
    if not keyed:
        return _coach_request_offer(
            rows, target, verdict=verdict, vocabulary=vocabulary,
            exercises=exercises, snippet=snippet, existing=existing,
            take_session_id=take_session_id, owner_user_id=owner_user_id,
            database=database, ground=ground)
    evidence = ground(target)
    if not isinstance(evidence, dict):
        return rows
    ranked = [item[1] for item in keyed]
    exercise = choose_exercise(
        ranked, owner_user_id=owner_user_id,
        take_session_id=take_session_id, snippet_id=snippet_id,
        lane="v3_exercise_block", database=database, fit=fit,
        trace=build_match_trace(
            lane="v3_exercise_block", verdict=verdict, vocabulary=vocabulary,
            exercises=exercises, ranked=ranked, fit=fit, snippet=snippet,
            history=history,
            take_session_id=take_session_id, snippet_id=snippet_id))
    if exercise is None:
        return rows
    target["evidence"] = evidence
    target["practice_exercise"] = _offer_payload(
        exercise, verdict, snippet, target, existing)
    target["practice_exercise"]["done_before"] = _done_before(
        database, owner_user_id, str(exercise.get("exercise_id") or ""),
        take_session_id)
    return rows


#: The policy a coach-shared exercise is served under: no match, no draw.
COACH_REQUEST_POLICY_VERSION = "exercise-coach-request-v1"


def _coach_request_offer(
    rows: list[dict], target: dict, *, verdict: dict, vocabulary: Any,
    exercises: list[dict], snippet: dict, existing: Any,
    take_session_id: str, owner_user_id: str, database: Any, ground: Any,
) -> list[dict]:
    """No exercise fits this moment: record the coach request (contract 35b),
    and serve the exercise the coach shared for it, if they have.

    The request is written insert-once (migration 0385): this runs on every
    feedback build, and every call after the first returns the same row with
    whatever resolution it has gained. Nothing waits on it — the item is
    served now, exactly as V3 made it, and the coach's answer arrives on a
    later read. A failed write never costs the feedback.
    """
    request_fn = getattr(database, "request_exercise_from_coach", None)
    if request_fn is None or not owner_user_id:
        return rows
    snippet_id = str(target["snippet_id"])
    observed = observed_problem_tags(verdict, vocabulary=vocabulary)
    try:
        request = request_fn(
            owner_user_id=str(owner_user_id),
            take_session_id=str(take_session_id), snippet_id=snippet_id,
            reason="nothing_targets_it" if observed else "nothing_spotted",
            pattern=verdict.get("pattern"), observed_tags=sorted(observed),
            request_trace=build_match_trace(
                lane="v3_exercise_block", verdict=verdict,
                vocabulary=vocabulary, exercises=exercises, ranked=[],
                fit=None, snippet=snippet, take_session_id=take_session_id,
                snippet_id=snippet_id))
    except Exception as e:  # noqa: BLE001 — never lose the feedback
        _log.warning("exercise coach request failed take=%s snip=%s: %s",
                     take_session_id, snippet_id, e)
        return rows
    exercise = coach_shared_exercise(request, database)
    if exercise is None:
        return rows
    evidence = ground(target)
    if not isinstance(evidence, dict):
        return rows
    target["evidence"] = evidence
    target["practice_exercise"] = {
        **_offer_payload(exercise, verdict, snippet, target, existing),
        "matching_policy_version": COACH_REQUEST_POLICY_VERSION,
        "pattern_distance": None,
        "chosen_by_coach": True,
        "done_before": _done_before(
            database, owner_user_id, str(exercise.get("exercise_id") or ""),
            take_session_id),
    }
    return rows


def _shared_request_for(database: Any, take_session_id: str,
                        snippet_id: str) -> Optional[dict]:
    getter = getattr(database, "get_exercise_coach_request", None)
    request = (getter(take_session_id, snippet_id)
               if getter is not None else None)
    return request if coach_shared_exercise(request, database) else None


def coach_shared_exercise(request: Any, database: Any) -> Optional[dict]:
    """The live exercise a coach resolved and shared this request with, or
    None. The version must still be the one they shared: an exercise edited
    since is not the one they chose."""
    if not isinstance(request, dict) or not request.get("shared_at"):
        return None
    exercise_id = str(request.get("resolved_exercise_id") or "")
    if not exercise_id:
        return None
    active = database.get_active_diagnostic_exercise(exercise_id)
    if not isinstance(active, dict):
        return None
    if int(active.get("version") or 1) != int(
            request.get("resolved_exercise_version") or 0):
        return None
    return active


def start_exercise_check(*, snippet: dict, take_session_id: str,
                         snippet_id: str, exercise_id: str,
                         session_median_wpm: Any, database: Any,
                         owner_user_id: str = ""):
    """Whether the practice-start route may open `exercise_id` on this clip.

    Returns `(error_code, verdict, matching)`: `error_code` is None when it
    may. With a frozen 80/20 assignment for the moment, the tapped exercise
    must be the assigned one and the clip must pass the safety half of the
    gate. Without one (the table not migrated yet), the pre-80/20 rule holds:
    the clip passes the full gate and the exercise is the current best match.
    """
    verdict = exercise_eligibility(
        snippet, session_median_wpm=session_median_wpm)
    getter = getattr(database, "get_confident_voice_exercise_assignment", None)
    assignment = (getter(take_session_id, snippet_id)
                  if getter is not None else None)
    if isinstance(assignment, dict):
        if not clip_can_carry_exercise(verdict):
            return "NOT_ELIGIBLE", verdict, None
        if str(assignment.get("selected_exercise_id")) != str(exercise_id):
            return "EXERCISE_OFFER_STALE", verdict, None
        active = database.get_active_diagnostic_exercise(str(exercise_id))
        return None, verdict, {
            "pattern_distance": confidence_pattern_distance(
                str(verdict.get("pattern") or ""),
                _with_default_patterns(active or {}).get(
                    "supported_confidence_patterns")),
            "matching_policy_version": MATCHING_POLICY_VERSION,
            "exposure_policy_version": EXPOSURE_POLICY_VERSION,
            "exercise_assignment_id": str(assignment.get("id") or ""),
            # Stored with the practice (machine_assessment), never returned
            # to the speaker: which practices were trials.
            "exercise_fit": fit_from_policy(
                assignment.get("matching_policy_version")),
        }
    shared = _shared_request_for(database, take_session_id, snippet_id)
    if shared is not None and str(
            shared.get("resolved_exercise_id")) == str(exercise_id):
        if not clip_can_carry_exercise(verdict):
            return "NOT_ELIGIBLE", verdict, None
        return None, verdict, {
            "matching_policy_version": COACH_REQUEST_POLICY_VERSION,
            "exercise_fit": None,
            "exercise_coach_request_id": str(shared.get("id") or ""),
        }
    if not verdict.get("eligible"):
        return "NOT_ELIGIBLE", verdict, None
    # The same history the offer ranked with, so the two agree on the best.
    fit, matched = match_for_clip(
        verdict, database,
        history=speaker_history(database, owner_user_id, take_session_id))
    if not matched:
        return "NOT_MATCHABLE", verdict, None
    best_key, best_exercise = matched[0]
    if str(best_exercise.get("exercise_id")) != str(exercise_id):
        return "EXERCISE_OFFER_STALE", verdict, None
    return None, verdict, {
        "pattern_distance": best_key[KEY_DISTANCE],
        "matching_policy_version": MATCHING_POLICY_VERSION,
        "exercise_fit": fit,
    }


def reconcile_practice_voice_album(practice: dict, *, database: Any) -> bool:
    """Mirror one selected practice recording into/out of the Voice Album.

    Keeping the attempt never calls this function.  It is invoked only after
    a coach explicitly judges the selected attempt itself.  The original
    snippet's blind coach rating cannot satisfy this separate coach leg.
    """
    if not isinstance(practice, dict) or not practice.get("selected_attempt_id"):
        return False
    attempt_id = str(practice["selected_attempt_id"])
    attempt = database.get_confident_voice_practice_attempt(
        attempt_id, str(practice.get("id") or ""))
    if not attempt:
        return False
    aligned = (
        attempt.get("machine_confidence_decision") == "yes"
        and attempt.get("user_answer") == "yes"
        and attempt.get("coach_confidence_decision") == "yes"
    )
    kwargs = {
        "arc_id": str(practice.get("project_id") or ""),
        "practice_attempt_id": attempt_id,
        "take_session_id": str(practice.get("take_session_id") or "") or None,
        "slide_index": practice.get("slide_index"),
    }
    if aligned:
        return bool(database.insert_voice_album_practice_entry(**kwargs))
    database.delete_voice_album_practice_entry(
        arc_id=kwargs["arc_id"], practice_attempt_id=attempt_id)
    return False


def comparison_for_attempt(original: dict, current: dict,
                           previous: Optional[dict] = None,
                           best: Optional[dict] = None) -> dict:
    """Internal relative comparison + closed user-facing assessment key."""
    def value(row: Optional[dict], key: str) -> Optional[float]:
        return _number((row or {}).get(key))

    ow, cw = value(original, "wpm"), value(current, "wpm")
    og, cg = value(original, "median_gap"), value(current, "median_gap")
    oe, ce = value(original, "ending_duration_ratio"), value(current, "ending_duration_ratio")
    oi = value(original, "word_recognition_confidence")
    ci = value(current, "word_recognition_confidence")
    oc, cc = value(original, "confidence"), value(current, "confidence")
    pace_delta = (cw - ow) if cw is not None and ow is not None else None
    gap_delta = (cg - og) if cg is not None and og is not None else None
    ending_delta = (ce - oe) if ce is not None and oe is not None else None
    confidence_delta = (cc - oc) if cc is not None and oc is not None else None
    intelligibility_delta = (ci - oi) if ci is not None and oi is not None else None
    clearer = bool((gap_delta is not None and gap_delta >= 0.018)
                   or (ending_delta is not None and ending_delta >= 0.10)
                   or (intelligibility_delta is not None
                       and intelligibility_delta >= 0.04))
    less_rushed = bool(pace_delta is not None and pace_delta <= -8.0)
    faster = bool(pace_delta is not None and pace_delta >= 8.0)
    ending_compressed = bool(ce is not None and ce < 0.8)
    if faster:
        key = "faster_than_original"
    elif clearer and less_rushed and ending_compressed:
        key = "opening_improved_ending_compressed"
    elif clearer and less_rushed:
        key = "clearer_less_rushed"
    elif clearer:
        key = "clearer_choose_natural"
    else:
        key = "similar_try_ending"
    # Internal score exists solely to choose the strongest attempt. It is not
    # a confidence score and is never serialized by the route.
    internal_strength = (
        (min(0.15, max(-0.15, gap_delta or 0.0)) * 4.0)
        + (min(0.4, max(-0.4, ending_delta or 0.0)))
        + (min(0.25, max(-0.25, intelligibility_delta or 0.0)) * 0.5)
        + (0.25 if less_rushed else -0.15 if faster else 0.0)
        + (min(0.2, max(-0.2, confidence_delta or 0.0)) * 0.5)
    )
    return {
        "assessment_key": key,
        "assessment": ASSESSMENT_COPY[key],
        "internal_strength": round(internal_strength, 4),
        "relative_to_original": {
            "pace_delta": pace_delta,
            "word_separation_delta": gap_delta,
            "ending_compression_delta": ending_delta,
            "intelligibility_delta": intelligibility_delta,
            "confidence_signal_delta": confidence_delta,
        },
        "relative_to_previous": _relative(current, previous),
        "relative_to_best": _relative(current, best),
        "improved": bool(clearer or less_rushed),
    }


def _relative(current: dict, other: Optional[dict]) -> Optional[dict]:
    if not other:
        return None
    out = {}
    for key in (
        "wpm", "median_gap", "ending_duration_ratio", "pause_ratio",
        "confidence", "word_recognition_confidence",
    ):
        a, b = _number(current.get(key)), _number(other.get(key))
        if a is not None and b is not None:
            out[key] = round(a - b, 4)
    return out or None


def public_attempt(attempt: dict) -> dict:
    """The only attempt shape a user route may return — no raw metrics."""
    raw_key = attempt.get("assessment_key")
    key = str(raw_key) if raw_key is not None else ""
    return {
        "id": str(attempt.get("id")),
        "attempt_index": int(attempt.get("attempt_index") or 0),
        "audio_ref": attempt.get("audio_ref"),
        "duration_ms": attempt.get("duration_ms"),
        "assessment": ASSESSMENT_COPY.get(
            key, ASSESSMENT_COPY["recorded_for_comparison"]
        ),
        "is_strongest": bool(attempt.get("is_strongest")),
        "kept": bool(attempt.get("kept")),
        "user_answer": attempt.get("user_answer"),
    }
