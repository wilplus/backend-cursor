"""Executable N1 collection contract for rushed phrase endings.

This module records transparent raw before/after evidence.  It deliberately
does not decide whether speech is rushed, improved, confident, or effective.
"""
from __future__ import annotations

import math
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

import numpy as np

SAMPLE_RATE = 16_000
PAUSE_THRESHOLD_MS = 250
CLIPPING_AMPLITUDE_FS = 0.999
ENDING_WORD_COUNT = 3
MIN_PREFIX_WORD_COUNT = 3
LANGUAGE_SCOPE = "en"
EXTRACTOR_VERSION = "rushed-phrase-endings-n1-extractor-v1"
FEATURE_SCHEMA_VERSION = "rushed-phrase-endings-n1-features-v1"
VALIDITY_CONTRACT_VERSION = "rushed-phrase-endings-n1-validity-v1"

_TOKEN = re.compile(r"[a-z]+(?:'[a-z]+)?")
_VOWELS = re.compile(r"[aeiouy]+")


def _round(value: float, places: int = 4) -> float:
    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall((text or "").lower())


def _edit_distance(left: list[str], right: list[str]) -> int:
    previous = list(range(len(right) + 1))
    for i, lhs in enumerate(left, 1):
        current = [i]
        for j, rhs in enumerate(right, 1):
            current.append(min(
                current[-1] + 1,
                previous[j] + 1,
                previous[j - 1] + (lhs != rhs),
            ))
        previous = current
    return previous[-1]


def _syllables(token: str) -> tuple[int | None, bool]:
    """Versioned English orthographic estimate; unsupported tokens are OOV."""
    if not _TOKEN.fullmatch(token):
        return None, True
    groups = _VOWELS.findall(token)
    if not groups:
        return None, True
    count = len(groups)
    if token.endswith("e") and not token.endswith(("le", "ye")) and count > 1:
        count -= 1
    return max(1, count), False


def _span_audio(pcm: np.ndarray, start_ms: int, end_ms: int) -> np.ndarray:
    start = max(0, int(start_ms * SAMPLE_RATE / 1000))
    end = min(len(pcm), int(end_ms * SAMPLE_RATE / 1000))
    return pcm[start:end] if end > start else np.asarray([], dtype=np.float32)


def _acoustics(pcm: np.ndarray, start_ms: int, end_ms: int) -> dict[str, Any]:
    values = _span_audio(pcm, start_ms, end_ms)
    if values.size == 0:
        return {"rms_dbfs": None, "clipping_fraction": None}
    rms = math.sqrt(float(np.mean(np.square(values, dtype=np.float64))))
    return {
        "rms_dbfs": None if rms <= 0 else _round(20.0 * math.log10(rms)),
        "clipping_fraction": _round(float(np.mean(
            np.abs(values) >= CLIPPING_AMPLITUDE_FS
        ))),
    }


def extract_rushed_phrase_endings_n1(
    *,
    exact_passage: str,
    transcript: str,
    words: list[dict[str, Any]],
    pcm: np.ndarray | None,
    language: str | None,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    """Return raw measurements, safeguards, and typed technical-invalidity.

    Word error rate is exact normalized word-level Levenshtein distance divided
    by reference token count.  No hidden similarity threshold is applied.
    """
    reference = _tokens(exact_passage)
    hypothesis = _tokens(transcript)
    reasons: list[str] = []
    if not transcript.strip():
        reasons.append("transcript_missing")
    if not language:
        reasons.append("language_missing")
    elif language.lower().split("-")[0] != LANGUAGE_SCOPE:
        reasons.append("language_out_of_scope")
    if pcm is None or len(pcm) == 0:
        reasons.append("audio_decode_failed")

    normalized_words: list[dict[str, Any]] = []
    timing_invalid = False
    for raw in words or []:
        token_values = _tokens(str(raw.get("word") or ""))
        if len(token_values) != 1:
            continue
        try:
            start_ms = int(round(float(raw["start"]) * 1000))
            end_ms = int(round(float(raw["end"]) * 1000))
        except (KeyError, TypeError, ValueError):
            timing_invalid = True
            continue
        if start_ms < 0 or end_ms <= start_ms:
            timing_invalid = True
            continue
        confidence = raw.get("confidence")
        try:
            confidence = None if confidence is None else float(confidence)
        except (TypeError, ValueError):
            confidence = None
        if confidence is not None and not 0.0 <= confidence <= 1.0:
            confidence = None
        normalized_words.append({
            "token": token_values[0],
            "start_ms": start_ms,
            "end_ms": end_ms,
            "confidence": confidence,
        })
    if timing_invalid:
        reasons.append("word_timing_invalid")
    if len(normalized_words) < ENDING_WORD_COUNT + MIN_PREFIX_WORD_COUNT:
        reasons.append("insufficient_phrase_words")

    wer = None
    if reference:
        wer = _round(_edit_distance(reference, hypothesis) / len(reference))
        if wer != 0.0:
            reasons.append("exact_passage_mismatch")
    else:
        reasons.append("reference_passage_missing")

    prefix = normalized_words[:-ENDING_WORD_COUNT]
    ending = normalized_words[-ENDING_WORD_COUNT:]
    usable_spans = len(prefix) >= MIN_PREFIX_WORD_COUNT and len(ending) == 3

    def span(values: list[dict[str, Any]]) -> dict[str, Any]:
        if not values:
            return {
                "start_ms": None, "end_ms": None, "duration_ms": None,
                "word_count": 0, "wpm": None, "pause_count": None,
                "pause_total_ms": None, "syllable_count": None,
                "syllables_per_second": None, "oov_tokens": [],
                "asr_confidence_mean": None, "asr_confidence_min": None,
                "rms_dbfs": None, "clipping_fraction": None,
            }
        start_ms, end_ms = values[0]["start_ms"], values[-1]["end_ms"]
        duration_ms = end_ms - start_ms
        gaps = [
            max(0, right["start_ms"] - left["end_ms"])
            for left, right in zip(values, values[1:])
        ]
        pauses = [gap for gap in gaps if gap >= PAUSE_THRESHOLD_MS]
        syllable_count = 0
        oov: list[str] = []
        for value in values:
            count, is_oov = _syllables(value["token"])
            if is_oov or count is None:
                oov.append(value["token"])
            else:
                syllable_count += count
        confidences = [
            value["confidence"] for value in values
            if value["confidence"] is not None
        ]
        acoustic = (
            _acoustics(pcm, start_ms, end_ms)
            if pcm is not None else {"rms_dbfs": None, "clipping_fraction": None}
        )
        return {
            "start_ms": start_ms,
            "end_ms": end_ms,
            "duration_ms": duration_ms,
            "word_count": len(values),
            "wpm": None if duration_ms <= 0 else _round(
                len(values) * 60_000.0 / duration_ms
            ),
            "pause_count": len(pauses),
            "pause_total_ms": sum(pauses),
            "syllable_count": syllable_count if not oov else None,
            "syllables_per_second": (
                None if duration_ms <= 0 or oov else
                _round(syllable_count * 1000.0 / duration_ms)
            ),
            "oov_tokens": oov,
            "asr_confidence_mean": (
                _round(sum(confidences) / len(confidences))
                if len(confidences) == len(values) else None
            ),
            "asr_confidence_min": (
                _round(min(confidences))
                if len(confidences) == len(values) else None
            ),
            **acoustic,
        }

    prefix_span = span(prefix if usable_spans else [])
    ending_span = span(ending if usable_spans else [])
    rate_ratio = None
    if prefix_span["wpm"] and ending_span["wpm"]:
        rate_ratio = _round(ending_span["wpm"] / prefix_span["wpm"])
    missingness: list[str] = []
    if usable_spans and any(
        value["confidence"] is None for value in normalized_words
    ):
        missingness.append("word_confidence_unavailable")
    if prefix_span["oov_tokens"] or ending_span["oov_tokens"]:
        missingness.append("syllable_estimate_oov")
    missingness.extend(reason for reason in reasons if reason not in missingness)
    status = "complete" if usable_spans and not reasons else (
        "partial" if normalized_words else "unavailable"
    )
    measurements = {
        "contract_version": "rushed-phrase-endings-n1-collection-v1",
        "language_scope": LANGUAGE_SCOPE,
        "phrase_span": {
            "start_ms": normalized_words[0]["start_ms"] if normalized_words else None,
            "end_ms": normalized_words[-1]["end_ms"] if normalized_words else None,
            "reference_word_count": len(reference),
            "hypothesis_word_count": len(hypothesis),
            "word_error_rate": wer,
        },
        "prefix_span": prefix_span,
        "ending_span": ending_span,
        "ending_to_prefix_wpm_ratio": rate_ratio,
        "measurement_status": status,
    }
    safeguards = {
        "pause_threshold_ms": PAUSE_THRESHOLD_MS,
        "rms_unit": "dBFS_float32_mono_16khz",
        "clipping_amplitude_fs": CLIPPING_AMPLITUDE_FS,
        "syllable_method": "english_orthographic_v1",
        "oov_policy": "null_aggregate_and_retain_tokens",
        "confidence_aggregation": "mean_and_min_only_when_all_words_present",
        "wer_method": "normalized_word_levenshtein_half_up_4dp",
        "uncertainty": {
            "word_confidence_complete": not any(
                value["confidence"] is None for value in normalized_words
            ),
            "no_rushed_or_improved_label_derived": True,
        },
        "missingness_reasons": sorted(set(missingness)),
    }
    return measurements, safeguards, sorted(set(reasons))
