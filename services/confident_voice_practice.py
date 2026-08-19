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

import re
import statistics
from difflib import SequenceMatcher
from typing import Any, Optional


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
    "This was your clearest attempt. Listen once more and decide for yourself."
)
FINAL_QUESTION = "Does this take sound confident to you?"
UNSUCCESSFUL = (
    "We haven’t found the right adjustment yet. A coach can review this "
    "pattern and may recommend a more suitable exercise."
)

ASSESSMENT_COPY = {
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
    signals = {
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


def attach_exercise_offer(changes: list[dict], *, take_session_id: str,
                          database: Any) -> list[dict]:
    """Attach at most one active exercise after Feedback Manager selection."""
    rows = [dict(row) for row in (changes or [])]
    candidates = [row for row in rows if row.get("source") == "confident_voice"
                  and row.get("snippet_id")]
    if not candidates or not take_session_id:
        return rows
    exercise = database.get_active_diagnostic_exercise(EXERCISE_ID)
    if not exercise:
        return rows
    existing = database.get_confident_voice_practice_by_take(take_session_id)
    if existing and existing.get("status") in ("completed", "dismissed"):
        return rows
    if existing:
        # A resumed offer must remain attached to the exact original moment.
        # Re-running the manager may produce a different ranking, but changing
        # snippets under an open practice would break its passage/audio link.
        candidates = [
            row for row in candidates
            if str(row.get("snippet_id")) == str(existing.get("snippet_id"))
        ]
        if not candidates:
            return rows
    snippet_ids = [str(row["snippet_id"]) for row in candidates]
    snippets = database.get_confident_voice_practice_candidates(snippet_ids) or []
    by_id = {str(row.get("id")): row for row in snippets}
    take_rows = database.get_snippets_by_session(take_session_id) or []
    median_wpm = _median_wpm(take_rows)
    ranked = []
    for index, row in enumerate(candidates):
        snippet = by_id.get(str(row.get("snippet_id")))
        if not snippet:
            continue
        raw_evidence = row.get("evidence")
        evidence: dict = raw_evidence if isinstance(raw_evidence, dict) else {}
        verbal_problem = bool(row.get("semantic_or_structural_problem"))
        if not verbal_problem:
            for other in rows:
                other_evidence = other.get("evidence")
                if not isinstance(other_evidence, dict):
                    continue
                if (other is not row
                        and other.get("feedback_family") == "rewrite_clarity"
                        and other_evidence.get("slide_index")
                        == evidence.get("slide_index")
                        and other_evidence.get("paragraph_index")
                        == evidence.get("paragraph_index")):
                    verbal_problem = True
                    break
        verdict = exercise_eligibility(
            snippet,
            session_median_wpm=median_wpm,
            semantic_or_structural_problem=verbal_problem,
        )
        supported = exercise.get("supported_confidence_patterns")
        if isinstance(supported, list) and supported \
                and verdict.get("pattern") not in supported:
            continue
        if verdict.get("eligible"):
            ranked.append((verdict.get("priority", 0), index, row, snippet, verdict))
    if not ranked:
        return rows
    _, _, chosen, snippet, verdict = max(ranked, key=lambda item: (item[0], -item[1]))
    intro = (exercise.get("confident_introduction_copy")
             if verdict.get("pattern") == "confident" else
             exercise.get("introduction_copy"))
    chosen["practice_exercise"] = {
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
    }
    return rows


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
        "assessment": ASSESSMENT_COPY.get(key, ASSESSMENT_COPY["similar_try_ending"]),
        "is_strongest": bool(attempt.get("is_strongest")),
        "kept": bool(attempt.get("kept")),
        "user_answer": attempt.get("user_answer"),
    }
