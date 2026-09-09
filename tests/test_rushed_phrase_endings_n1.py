from __future__ import annotations

import numpy as np

from services.rushed_phrase_endings_n1 import (
    CLIPPING_AMPLITUDE_FS,
    EXTRACTOR_VERSION,
    FEATURE_SCHEMA_VERSION,
    PAUSE_THRESHOLD_MS,
    VALIDITY_CONTRACT_VERSION,
    extract_rushed_phrase_endings_n1,
)


def _words() -> list[dict]:
    tokens = "we make every ending sound calm and clear".split()
    return [
        {"word": token, "start": index * 0.5, "end": index * 0.5 + 0.3,
         "confidence": 0.9}
        for index, token in enumerate(tokens)
    ]


def test_exact_n1_fixture_freezes_spans_units_and_rounding():
    pcm = np.full(16_000 * 4, 0.5, dtype=np.float32)
    raw, safeguards, reasons = extract_rushed_phrase_endings_n1(
        exact_passage="We make every ending sound calm and clear.",
        transcript="We make every ending sound calm and clear.",
        words=_words(),
        pcm=pcm,
        language="en",
    )
    assert reasons == []
    assert raw["measurement_status"] == "complete"
    assert raw["prefix_span"]["word_count"] == 5
    assert raw["ending_span"]["word_count"] == 3
    assert raw["phrase_span"]["word_error_rate"] == 0.0
    assert raw["ending_to_prefix_wpm_ratio"] is not None
    assert safeguards["pause_threshold_ms"] == PAUSE_THRESHOLD_MS
    assert safeguards["rms_unit"] == "dBFS_float32_mono_16khz"
    assert safeguards["clipping_amplitude_fs"] == CLIPPING_AMPLITUDE_FS
    assert safeguards["uncertainty"]["no_rushed_or_improved_label_derived"]


def test_n1_missingness_and_exact_mismatch_are_typed_not_labels():
    raw, safeguards, reasons = extract_rushed_phrase_endings_n1(
        exact_passage="one two three four five six",
        transcript="one two three",
        words=[],
        pcm=None,
        language="pl",
    )
    assert raw["measurement_status"] == "unavailable"
    assert {
        "language_out_of_scope", "audio_decode_failed",
        "insufficient_phrase_words", "exact_passage_mismatch",
    } <= set(reasons)
    assert set(reasons) <= set(safeguards["missingness_reasons"])
    assert "improved" not in raw
    assert "rushed" not in raw


def test_n1_contract_versions_are_explicit():
    assert EXTRACTOR_VERSION == "rushed-phrase-endings-n1-extractor-v1"
    assert FEATURE_SCHEMA_VERSION == "rushed-phrase-endings-n1-features-v1"
    assert VALIDITY_CONTRACT_VERSION == "rushed-phrase-endings-n1-validity-v1"


def test_n1_missing_language_is_explicitly_invalid():
    _, safeguards, reasons = extract_rushed_phrase_endings_n1(
        exact_passage="We make every ending sound calm and clear.",
        transcript="We make every ending sound calm and clear.",
        words=_words(),
        pcm=np.zeros(16_000 * 4, dtype=np.float32),
        language=None,
    )
    assert "language_missing" in reasons
    assert "language_missing" in safeguards["missingness_reasons"]
