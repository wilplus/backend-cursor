"""Tests for the offline ASR eval harness (asr_eval/).

An eval with a bug is worse than no eval — it launders a wrong answer as a
measured one. These tests exist so the harness itself is gated before it is
used to gate an ASR migration.

Pure: no network, no API key, no DB. Safe for the CI unit tier.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from asr_eval import corpus, metrics, normalize, report


def _w(token, start, end=None):
    return {"word": token, "start": start,
            "end": start if end is None else end}


class NormalizeTests(unittest.TestCase):

    def test_tokens_lowercase_and_strip_punctuation(self):
        self.assertEqual(
            normalize.tokens("Hello, WORLD! It's fine."),
            ["hello", "world", "it's", "fine"])

    def test_curly_apostrophe_matches_straight(self):
        # Cross-provider punctuation differences must not read as errors.
        self.assertEqual(normalize.tokens("don’t"),
                         normalize.tokens("don't"))

    def test_tokens_on_garbage_returns_empty(self):
        for bad in (None, 123, {"a": 1}, []):
            self.assertEqual(normalize.tokens(bad), [])

    def test_multi_word_filler_stripped_as_phrase(self):
        # "you know" is a filler; a standalone "know" is content and must
        # survive. Token-wise stripping would delete both.
        out = normalize.tokens("i know you know the answer",
                               strip_fillers=True, language="en")
        self.assertIn("know", out)
        self.assertNotIn("you", out)
        # "i mean" is also a filler phrase, but bare "i" + "know" is not.
        self.assertEqual(out.count("know"), 1)

    def test_single_word_filler_stripped(self):
        out = normalize.tokens("um so uh hello", strip_fillers=True,
                               language="en")
        self.assertEqual(out, ["hello"])

    def test_verbatim_keeps_fillers(self):
        out = normalize.tokens("um hello", language="en")
        self.assertEqual(out, ["um", "hello"])

    def test_word_tokens_sorted_and_punctuation_dropped(self):
        got = normalize.word_tokens([_w(" world,", 1.0), _w("Hello", 0.5),
                                     _w("!!!", 2.0)])
        self.assertEqual([t["token"] for t in got], ["hello", "world"])

    def test_word_tokens_drops_nonfinite_and_missing_starts(self):
        got = normalize.word_tokens([
            _w("a", 0.1),
            {"word": "b"},                      # no start
            {"word": "c", "start": float("nan")},
            {"word": "d", "start": float("inf")},
            {"word": "e", "start": True},       # bool is not a time
            "not a dict",
        ])
        self.assertEqual([t["token"] for t in got], ["a"])

    def test_word_tokens_splits_compound_and_carries_timing(self):
        got = normalize.word_tokens([_w("well—okay", 3.0, 3.4)])
        self.assertEqual([t["token"] for t in got], ["well", "okay"])
        self.assertTrue(all(t["start"] == 3.0 for t in got))


class WerTests(unittest.TestCase):

    def test_identical_is_zero(self):
        toks = normalize.tokens("the quick brown fox jumps over")
        m = metrics.word_error_rate(toks, toks)
        self.assertEqual(m["wer"], 0.0)
        self.assertEqual(m["hits"], 6)

    def test_single_substitution(self):
        m = metrics.word_error_rate(
            normalize.tokens("the quick brown fox"),
            normalize.tokens("the slow brown fox"))
        self.assertEqual(m["substitutions"], 1)
        self.assertEqual(m["deletions"], 0)
        self.assertEqual(m["insertions"], 0)
        self.assertAlmostEqual(m["wer"], 0.25)

    def test_single_deletion(self):
        m = metrics.word_error_rate(
            normalize.tokens("the quick brown fox"),
            normalize.tokens("the quick brown"))
        self.assertEqual(m["deletions"], 1)
        self.assertAlmostEqual(m["wer"], 0.25)

    def test_single_insertion(self):
        m = metrics.word_error_rate(
            normalize.tokens("the quick brown fox"),
            normalize.tokens("the quick brown fox jumps"))
        self.assertEqual(m["insertions"], 1)
        self.assertAlmostEqual(m["wer"], 0.25)

    def test_empty_reference_gives_none_not_zero(self):
        # A perfect-looking 0.0 on an empty reference is the exact way a
        # broken corpus entry reads as a passing candidate.
        m = metrics.word_error_rate([], normalize.tokens("anything at all"))
        self.assertIsNone(m["wer"])
        self.assertEqual(m["insertions"], 3)

    def test_empty_hypothesis_is_total_loss(self):
        m = metrics.word_error_rate(normalize.tokens("a b c d"), [])
        self.assertEqual(m["deletions"], 4)
        self.assertEqual(m["wer"], 1.0)

    def test_long_transcript_with_anchors_stays_exact(self):
        # Exercises the anchor-splitting path: >_ANCHOR_MIN exact runs
        # around a single substitution.
        ref = normalize.tokens(" ".join(f"w{i}" for i in range(200)))
        hyp = list(ref)
        hyp[100] = "different"
        m = metrics.word_error_rate(ref, hyp)
        self.assertEqual(m["substitutions"], 1)
        self.assertEqual(m["deletions"], 0)
        self.assertEqual(m["insertions"], 0)


class TimestampTests(unittest.TestCase):

    def test_delta_measures_only_matched_words(self):
        ref = normalize.word_tokens([_w("alpha", 1.0), _w("bravo", 2.0)])
        hyp = normalize.word_tokens([_w("alpha", 1.1), _w("charlie", 9.0)])
        d = metrics.timestamp_delta(ref, hyp)
        self.assertEqual(d["matched"], 1)
        self.assertAlmostEqual(d["median_ms"], 100.0, places=3)

    def test_within_tolerance_shares(self):
        ref = normalize.word_tokens([_w("a", 1.0), _w("b", 2.0),
                                     _w("c", 3.0), _w("d", 4.0)])
        hyp = normalize.word_tokens([_w("a", 1.02), _w("b", 2.02),
                                     _w("c", 3.02), _w("d", 4.9)])
        d = metrics.timestamp_delta(ref, hyp)
        self.assertEqual(d["matched"], 4)
        self.assertAlmostEqual(d["within_50ms"], 0.75)

    def test_no_overlap_reports_zero_matched_not_perfect_score(self):
        ref = normalize.word_tokens([_w("alpha", 1.0)])
        hyp = normalize.word_tokens([_w("zulu", 1.0)])
        d = metrics.timestamp_delta(ref, hyp)
        self.assertEqual(d["matched"], 0)
        self.assertIsNone(d["median_ms"])


class SlideBucketTests(unittest.TestCase):
    """THE metric. A timing shift that crosses a tap is an F1 regression
    even when the words are transcribed perfectly."""

    SLIDES = [{}, {}]
    ADVANCES = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}]

    def test_shift_across_boundary_is_caught(self):
        ref = normalize.word_tokens([_w("alpha", 4.8), _w("bravo", 5.2)])
        hyp = normalize.word_tokens([_w("alpha", 5.3), _w("bravo", 5.7)])
        got = metrics.slide_bucket_agreement(ref, hyp, self.ADVANCES,
                                             self.SLIDES)
        self.assertEqual(got["matched"], 2)
        self.assertEqual(got["agreed"], 1)
        self.assertAlmostEqual(got["disagreement_rate"], 0.5)
        # alpha left slide 0 and arrived on slide 1.
        self.assertEqual(got["net_slide_word_delta"], {0: -1, 1: 1})

    def test_boundary_rate_isolates_the_damage(self):
        got = metrics.slide_bucket_agreement(
            normalize.word_tokens([_w("alpha", 4.8), _w("bravo", 5.2)]),
            normalize.word_tokens([_w("alpha", 5.3), _w("bravo", 5.7)]),
            self.ADVANCES, self.SLIDES)
        self.assertEqual(got["boundary_matched"], 2)
        self.assertAlmostEqual(got["boundary_disagreement_rate"], 0.5)

    def test_identical_timing_agrees_completely(self):
        ws = normalize.word_tokens([_w("alpha", 4.8), _w("bravo", 5.2)])
        got = metrics.slide_bucket_agreement(ws, ws, self.ADVANCES,
                                             self.SLIDES)
        self.assertEqual(got["disagreement_rate"], 0.0)
        self.assertEqual(got["net_slide_word_delta"], {})

    def test_shift_away_from_boundary_costs_nothing(self):
        # Same 500ms shift, but mid-slide: bucketing is unaffected. This is
        # why a raw timestamp error is not the decision metric.
        ref = normalize.word_tokens([_w("alpha", 1.0), _w("bravo", 2.0)])
        hyp = normalize.word_tokens([_w("alpha", 1.5), _w("bravo", 2.5)])
        got = metrics.slide_bucket_agreement(ref, hyp, self.ADVANCES,
                                             self.SLIDES)
        self.assertEqual(got["disagreement_rate"], 0.0)

    def test_deckless_take_is_unmeasurable_not_perfect(self):
        ws = normalize.word_tokens([_w("alpha", 1.0)])
        self.assertIsNone(
            metrics.slide_bucket_agreement(ws, ws, [], []))
        self.assertIsNone(
            metrics.slide_bucket_agreement(ws, ws, self.ADVANCES, []))

    def test_recording_start_tap_alone_is_not_a_boundary(self):
        ws = normalize.word_tokens([_w("alpha", 1.0)])
        self.assertIsNone(metrics.slide_bucket_agreement(
            ws, ws, [{"index": 0, "t_ms": 0}], self.SLIDES))


class BoundaryCriticalWerTests(unittest.TestCase):

    ADVANCES = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}]

    def test_only_boundary_adjacent_words_counted(self):
        ref = normalize.word_tokens([_w("far", 1.0), _w("near", 4.9)])
        hyp = normalize.word_tokens([_w("wrong", 1.0), _w("near", 4.9)])
        m = metrics.boundary_critical_wer(ref, hyp, self.ADVANCES)
        # "far" sits 3.9s from the tap → outside the window → not counted.
        self.assertEqual(m["ref_words"], 1)
        self.assertEqual(m["wer"], 0.0)

    def test_error_at_boundary_is_counted(self):
        ref = normalize.word_tokens([_w("near", 4.9)])
        hyp = normalize.word_tokens([_w("wrong", 4.9)])
        m = metrics.boundary_critical_wer(ref, hyp, self.ADVANCES)
        self.assertEqual(m["substitutions"], 1)
        self.assertEqual(m["wer"], 1.0)

    def test_no_boundary_words_returns_none(self):
        ref = normalize.word_tokens([_w("far", 1.0)])
        self.assertIsNone(
            metrics.boundary_critical_wer(ref, ref, self.ADVANCES))


class CoverageTests(unittest.TestCase):
    """The gpt-4o-transcribe case: text but no word timestamps."""

    def test_text_without_words_fails_coverage(self):
        c = metrics.coverage({"text": "hello world", "words": []})
        self.assertFalse(c["ok"])
        self.assertIn("no word timestamps", c["reason"])

    def test_empty_transcript_fails(self):
        self.assertFalse(metrics.coverage({"text": "", "words": []})["ok"])

    def test_none_result_fails(self):
        self.assertFalse(metrics.coverage(None)["ok"])

    def test_text_and_words_passes(self):
        c = metrics.coverage({"text": "hi", "words": [_w("hi", 0.1)]})
        self.assertTrue(c["ok"])

    def test_evaluate_take_short_circuits_on_no_words(self):
        out = metrics.evaluate_take(
            reference_text="hello world",
            candidate={"text": "hello world", "words": []})
        self.assertIn("skipped", out)
        # No WER is reported for an unusable provider — a good-looking WER
        # next to "no timestamps" is exactly the misread to prevent.
        self.assertNotIn("wer_verbatim", out)


class EvaluateTakeTests(unittest.TestCase):

    SLIDES = [{}, {}]
    ADVANCES = [{"index": 0, "t_ms": 0}, {"index": 1, "t_ms": 5000}]

    def test_tier3_when_only_baseline_available(self):
        cand = {"text": "alpha bravo",
                "words": [_w("alpha", 4.8), _w("bravo", 5.2)]}
        base = {"text": "alpha bravo",
                "words": [_w("alpha", 4.8), _w("bravo", 5.2)]}
        out = metrics.evaluate_take(
            reference_text="alpha bravo", candidate=cand, baseline=base,
            slide_advances=self.ADVANCES, slides=self.SLIDES)
        self.assertEqual(out["timing"]["tier"], "tier3_agreement")
        self.assertEqual(out["slide_bucket"]["disagreement_rate"], 0.0)
        self.assertEqual(out["wer_verbatim"]["wer"], 0.0)

    def test_tier2_when_reference_words_supplied(self):
        cand = {"text": "alpha bravo",
                "words": [_w("alpha", 4.9), _w("bravo", 5.2)]}
        out = metrics.evaluate_take(
            reference_text="alpha bravo", candidate=cand,
            reference_words=[_w("alpha", 4.8), _w("bravo", 5.2)],
            slide_advances=self.ADVANCES, slides=self.SLIDES)
        self.assertEqual(out["timing"]["tier"], "tier2_accuracy")
        self.assertIn("wer_boundary_critical", out)


class GateTests(unittest.TestCase):

    def _summary(self, **kw):
        base = {
            "provider": "cand", "takes_total": 10, "takes_usable": 10,
            "takes_failed": 0, "failure_reasons": [],
            "wer_verbatim": {"wer_micro": 0.10, "deletion_share": 0.3,
                             "ref_words": 1000},
            "wer_content": {}, "wer_boundary_critical": {},
            "timing": {"tier": "tier2_accuracy", "p90_ms": 90.0},
            "slide_bucket": {"disagreement_rate": 0.001,
                             "boundary_disagreement_rate": 0.01},
        }
        base.update(kw)
        return base

    def test_clean_candidate_passes(self):
        self.assertEqual(report.gate(self._summary())["verdict"], "PASS")

    def test_no_usable_takes_fails(self):
        g = report.gate(self._summary(takes_usable=0, takes_failed=10,
                                      failure_reasons=["no word timestamps"]))
        self.assertEqual(g["verdict"], "FAIL")

    def test_unmeasurable_bucket_is_insufficient_data_not_pass(self):
        g = report.gate(self._summary(
            slide_bucket={"disagreement_rate": None,
                          "boundary_disagreement_rate": None}))
        self.assertEqual(g["verdict"], "INSUFFICIENT-DATA")
        self.assertIn("bucket unmeasurable", g["blocking"])

    def test_bucket_regression_fails(self):
        g = report.gate(self._summary(
            slide_bucket={"disagreement_rate": 0.05,
                          "boundary_disagreement_rate": 0.30}))
        self.assertEqual(g["verdict"], "FAIL")
        self.assertIn("bucket disagreement", g["blocking"])

    def test_wer_regression_vs_baseline_fails(self):
        cand = self._summary(wer_verbatim={"wer_micro": 0.15,
                                           "deletion_share": 0.3,
                                           "ref_words": 1000})
        base = self._summary(provider="whisper-1",
                             wer_verbatim={"wer_micro": 0.10,
                                           "deletion_share": 0.3,
                                           "ref_words": 1000})
        g = report.gate(cand, baseline=base)
        self.assertEqual(g["verdict"], "FAIL")
        self.assertIn("wer regression", g["blocking"])

    def test_deletion_shift_fails_even_at_equal_wer(self):
        cand = self._summary(wer_verbatim={"wer_micro": 0.10,
                                           "deletion_share": 0.70,
                                           "ref_words": 1000})
        base = self._summary(provider="whisper-1",
                             wer_verbatim={"wer_micro": 0.10,
                                           "deletion_share": 0.30,
                                           "ref_words": 1000})
        g = report.gate(cand, baseline=base)
        self.assertEqual(g["verdict"], "FAIL")
        self.assertIn("deletion shift", g["blocking"])

    def test_tier3_timing_is_flagged_in_reasons(self):
        g = report.gate(self._summary(
            timing={"tier": "tier3_agreement", "p90_ms": 90.0}))
        self.assertTrue(any("TIER 3" in r for r in g["reasons"]))

    def test_timing_p90_regression_fails(self):
        g = report.gate(self._summary(
            timing={"tier": "tier2_accuracy", "p90_ms": 400.0}))
        self.assertEqual(g["verdict"], "FAIL")
        self.assertIn("timing p90", g["blocking"])


class CorpusTests(unittest.TestCase):

    def _manifest(self, tmp, takes):
        p = os.path.join(tmp, "manifest.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"takes": takes}, fh)
        return p

    def test_float_t_ms_is_coerced_to_int(self):
        # slide_index_for_offset requires real ints and SILENTLY skips
        # float entries — a manifest written with 18400.0 would bucket
        # every word to slide 0 while looking fine.
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [{
                "take_id": "t1", "audio": "a.mp3",
                "slide_advances": [{"index": 0, "t_ms": 0.0},
                                   {"index": 1.0, "t_ms": 18400.0}],
            }])
            c = corpus.load_manifest(p)
            for a in c["takes"][0]["slide_advances"]:
                self.assertIsInstance(a["t_ms"], int)
                self.assertIsInstance(a["index"], int)

    def test_missing_required_field_is_a_collected_blocker(self):
        # Take-level: one malformed entry must not kill a 60-take manifest.
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [{"audio": "a.mp3"},
                                     {"take_id": "ok", "audio": "b.mp3"}])
            c = corpus.load_manifest(p)
            self.assertEqual([t["take_id"] for t in c["takes"]], ["ok"])
            self.assertTrue(any("take_id" in e for e in c["load_errors"]))
            self.assertFalse(corpus.readiness(c)["ready"])

    def test_duplicate_take_id_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [
                {"take_id": "dup", "audio": "a.mp3"},
                {"take_id": "dup", "audio": "b.mp3"}])
            with self.assertRaises(corpus.CorpusError):
                corpus.load_manifest(p)

    def test_reference_text_read_from_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "ref.txt"), "w", encoding="utf-8") as fh:
                fh.write("hello from a file")
            p = self._manifest(tmp, [{"take_id": "t1", "audio": "a.mp3",
                                      "reference_text": "ref.txt"}])
            c = corpus.load_manifest(p)
            self.assertEqual(c["takes"][0]["reference_text"],
                             "hello from a file")

    def test_inline_reference_text_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [{"take_id": "t1", "audio": "a.mp3",
                                      "reference_text": "inline words here"}])
            c = corpus.load_manifest(p)
            self.assertEqual(c["takes"][0]["reference_text"],
                             "inline words here")

    def test_slides_as_count_expands(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [{"take_id": "t1", "audio": "a.mp3",
                                      "slides": 4}])
            c = corpus.load_manifest(p)
            self.assertEqual(len(c["takes"][0]["slides"]), 4)

    def test_readiness_blocks_when_no_deck_timeline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [{"take_id": "t1", "audio": "a.mp3",
                                      "reference_text": "hello"}])
            r = corpus.readiness(corpus.load_manifest(p))
            self.assertFalse(r["ready"])
            self.assertFalse(r["can_compute_slide_bucket"])
            self.assertTrue(any("slide-bucket" in b for b in r["blockers"]))

    def test_readiness_warns_on_missing_reference_times(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "a.mp3"), "wb").close()
            p = self._manifest(tmp, [{
                "take_id": "t1", "audio": "a.mp3",
                "reference_text": "hello", "slides": 2,
                "slide_advances": [{"index": 0, "t_ms": 0},
                                   {"index": 1, "t_ms": 5000}],
            }])
            r = corpus.readiness(corpus.load_manifest(p))
            self.assertTrue(r["can_compute_slide_bucket"])
            self.assertFalse(r["can_compute_timestamp_accuracy"])
            self.assertTrue(any("TIER 3" in w for w in r["warnings"]))

    def test_thin_stratum_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "a.mp3"), "wb").close()
            p = self._manifest(tmp, [{"take_id": "t1", "audio": "a.mp3",
                                      "accent": "polish-l2-en"}])
            r = corpus.readiness(corpus.load_manifest(p))
            self.assertTrue(any("strata below" in w for w in r["warnings"]))


class LanguageDetectionTests(unittest.TestCase):
    """The catastrophic failure for an L2-accented user base, and the one
    no WER number can see."""

    def test_correct_detection(self):
        d = metrics.language_detection({"language": "en"}, expected="en")
        self.assertTrue(d["ok"])
        self.assertFalse(d["flipped_to_l1"])

    def test_flip_to_speaker_l1_is_isolated(self):
        # Polish-accented English heard as Polish — the signature failure.
        d = metrics.language_detection({"language": "pl"}, expected="en",
                                       accent_l1="pl")
        self.assertFalse(d["ok"])
        self.assertTrue(d["flipped_to_l1"])

    def test_generic_confusion_is_not_an_l1_flip(self):
        d = metrics.language_detection({"language": "de"}, expected="en",
                                       accent_l1="pl")
        self.assertFalse(d["ok"])
        self.assertFalse(d["flipped_to_l1"])

    def test_native_polish_flipping_to_english_is_caught(self):
        # The other direction: fluent Polish heard as English.
        d = metrics.language_detection({"language": "en"}, expected="pl",
                                       accent_l1="pl")
        self.assertFalse(d["ok"])
        self.assertFalse(d["flipped_to_l1"])   # detected != l1

    def test_locale_suffix_normalized(self):
        d = metrics.language_detection({"language": "en-US"}, expected="en")
        self.assertTrue(d["ok"])

    def test_provider_reporting_no_language(self):
        d = metrics.language_detection({"language": None}, expected="en")
        self.assertIsNone(d["ok"])
        self.assertFalse(d["reported"])

    def test_none_when_nothing_to_check_against(self):
        self.assertIsNone(
            metrics.language_detection({"language": "en"}, expected=None))

    def test_evaluated_even_when_take_is_unusable(self):
        # A flip is a plausible CAUSE of an unusable result; losing the
        # diagnosis to the coverage short-circuit is the bug this prevents.
        out = metrics.evaluate_take(
            reference_text="hello", language="en", accent_l1="pl",
            candidate={"text": "dzien dobry", "words": [], "language": "pl"})
        self.assertIn("skipped", out)
        self.assertTrue(out["language_detection"]["flipped_to_l1"])

    def test_gate_blocks_on_any_flip(self):
        s = report.summarize("cand", [
            {"take": {}, "result": {
                "coverage": {"ok": True},
                "language_detection": {"expected": "en", "detected": "pl",
                                       "ok": False, "reported": True,
                                       "flipped_to_l1": True,
                                       "hint_given": False}}}])
        g = report.gate(s)
        self.assertIn("language flip", g["blocking"])
        self.assertTrue(any("NATIVE language" in r for r in g["reasons"]))

    def test_flip_rate_pooled_by_expected_language(self):
        rows = [{"take": {}, "result": {
            "coverage": {"ok": True},
            "language_detection": {"expected": e, "detected": d,
                                   "ok": e == d, "reported": True,
                                   "flipped_to_l1": False,
                                   "hint_given": False}}}
            for e, d in (("en", "en"), ("en", "pl"), ("pl", "pl"))]
        ld = report.summarize("x", rows)["language_detection"]
        self.assertEqual(ld["checked"], 3)
        self.assertEqual(ld["wrong"], 1)
        self.assertAlmostEqual(ld["flip_rate"], 1 / 3)
        self.assertEqual(ld["by_expected_language"]["en"]["detected_as"],
                         {"pl": 1})


class TrackDerivationTests(unittest.TestCase):
    """L2-English and native non-English run under DIFFERENT prompt
    configurations, so they must never be averaged."""

    def _track(self, **entry):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "manifest.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump({"takes": [{"take_id": "t", "audio": "a.mp3",
                                      **entry}]}, fh)
            return corpus.load_manifest(p)["takes"][0]["track"]

    def test_accented_english_is_l2(self):
        self.assertEqual(
            self._track(language="en", accent="polish-l2-en"), "l2_english")

    def test_native_polish_is_native_non_english(self):
        self.assertEqual(
            self._track(language="pl", accent="pl-native"),
            "native_non_english")

    def test_native_english_control_is_separate(self):
        self.assertEqual(
            self._track(language="en", accent="en-native-us"), "en_native")

    def test_explicit_track_wins_over_derivation(self):
        self.assertEqual(
            self._track(language="en", accent="polish-l2-en",
                        track="custom"), "custom")

    def test_accent_l1_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "manifest.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump({"takes": [{"take_id": "t", "audio": "a.mp3",
                                      "accent_l1": "PL-pl"}]}, fh)
            self.assertEqual(
                corpus.load_manifest(p)["takes"][0]["accent_l1"], "pl")


class ReferencePathTests(unittest.TestCase):
    """A typo'd reference path must never become the reference transcript."""

    def _manifest(self, tmp, takes):
        p = os.path.join(tmp, "manifest.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"takes": takes}, fh)
        return p

    def test_missing_reference_file_is_a_blocker_not_an_inline_fallback(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [{"take_id": "t1", "audio": "a.mp3",
                                      "reference_text": "refs/nope.txt"}])
            c = corpus.load_manifest(p)
            self.assertEqual(c["takes"], [])
            self.assertTrue(any("looks like a path" in e
                                for e in c["load_errors"]))
            self.assertFalse(corpus.readiness(c)["ready"])

    def test_all_bad_takes_reported_not_just_the_first(self):
        # A 60-take corpus with three bad paths should surface all three in
        # one run, not die on the first.
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [
                {"take_id": f"t{i}", "audio": "a.mp3",
                 "reference_text": f"refs/nope{i}.txt"} for i in range(3)])
            c = corpus.load_manifest(p)
            self.assertEqual(len(c["load_errors"]), 3)

    def test_good_takes_survive_alongside_bad_ones(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [
                {"take_id": "bad", "audio": "a.mp3",
                 "reference_text": "refs/nope.txt"},
                {"take_id": "good", "audio": "a.mp3",
                 "reference_text": "actual prose here"}])
            c = corpus.load_manifest(p)
            self.assertEqual([t["take_id"] for t in c["takes"]], ["good"])
            self.assertEqual(len(c["load_errors"]), 1)

    def test_bare_txt_name_is_also_treated_as_a_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [{"take_id": "t1", "audio": "a.mp3",
                                      "reference_text": "take01.txt"}])
            self.assertTrue(corpus.load_manifest(p)["load_errors"])

    def test_empty_reference_file_means_no_reference_not_empty_transcript(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.makedirs(os.path.join(tmp, "refs"))
            open(os.path.join(tmp, "refs", "t1.txt"), "w").close()
            p = self._manifest(tmp, [{"take_id": "t1", "audio": "a.mp3",
                                      "reference_text": "refs/t1.txt"}])
            c = corpus.load_manifest(p)
            self.assertEqual(c["load_errors"], [])
            self.assertFalse(c["takes"][0]["reference_text"])
            self.assertEqual(corpus.readiness(c)["with_reference_text"], 0)

    def test_ordinary_prose_still_accepted_inline(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = self._manifest(tmp, [{
                "take_id": "t1", "audio": "a.mp3",
                "reference_text": "so um this is the actual transcript"}])
            c = corpus.load_manifest(p)
            self.assertTrue(
                c["takes"][0]["reference_text"].startswith("so um"))


class RunnerEndToEndTests(unittest.TestCase):
    """Exercises scripts/asr_eval_run.py with a stub provider — the metric
    code is tested above; this covers the wiring that carries it."""

    @staticmethod
    def _load_runner():
        import importlib.util
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "scripts", "asr_eval_run.py")
        spec = importlib.util.spec_from_file_location("asr_eval_run", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def _corpus(self, tmp):
        for name in ("t1.mp3", "t2.mp3"):
            open(os.path.join(tmp, name), "wb").close()
        p = os.path.join(tmp, "manifest.json")
        takes = [{
            "take_id": tid, "audio": f"{tid}.mp3",
            "reference_text": "alpha bravo charlie delta",
            "language": "en", "accent": "test-stratum", "slides": 2,
            "slide_advances": [{"index": 0, "t_ms": 0},
                               {"index": 1, "t_ms": 5000}],
        } for tid in ("t1", "t2")]
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"takes": takes}, fh)
        return p

    def test_sweep_flags_a_provider_with_no_word_timestamps(self):
        from asr_eval import providers

        # Incumbent: correct text, correct word times.
        providers.register("stub:good")(lambda path, **kw: {
            "text": "alpha bravo charlie delta",
            "duration": 10.0, "language": "en", "segments": [],
            "words": [_w("alpha", 4.8), _w("bravo", 5.2),
                      _w("charlie", 6.0), _w("delta", 7.0)]})
        # The gpt-4o-transcribe shape: perfect text, NO timestamps.
        providers.register("stub:no-timestamps")(lambda path, **kw: {
            "text": "alpha bravo charlie delta",
            "duration": 10.0, "language": "en", "segments": [], "words": []})

        runner = self._load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "res.json")
            rc = runner.main([
                "--manifest", self._corpus(tmp),
                "--providers", "stub:good,stub:no-timestamps",
                "--baseline", "stub:good", "--out", out, "--force"])
            self.assertEqual(rc, 1)          # candidate failed its gate
            with open(out, encoding="utf-8") as fh:
                res = json.load(fh)

        gates = {g["provider"]: g for g in res["gates"]}
        self.assertEqual(gates["stub:no-timestamps"]["verdict"], "FAIL")
        self.assertTrue(any("no usable takes" in r
                            for r in gates["stub:no-timestamps"]["reasons"]))

    def test_sweep_catches_a_boundary_crossing_timing_shift(self):
        from asr_eval import providers

        providers.register("stub:base")(lambda path, **kw: {
            "text": "alpha bravo charlie delta", "duration": 10.0,
            "language": "en", "segments": [],
            "words": [_w("alpha", 4.8), _w("bravo", 5.2),
                      _w("charlie", 6.0), _w("delta", 7.0)]})
        # Same words, +600ms — "alpha" crosses the 5s tap onto slide 1.
        providers.register("stub:shifted")(lambda path, **kw: {
            "text": "alpha bravo charlie delta", "duration": 10.0,
            "language": "en", "segments": [],
            "words": [_w("alpha", 5.4), _w("bravo", 5.8),
                      _w("charlie", 6.6), _w("delta", 7.6)]})

        runner = self._load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "res.json")
            rc = runner.main([
                "--manifest", self._corpus(tmp),
                "--providers", "stub:base,stub:shifted",
                "--baseline", "stub:base", "--out", out, "--force"])
            self.assertEqual(rc, 1)
            with open(out, encoding="utf-8") as fh:
                res = json.load(fh)

        gates = {g["provider"]: g for g in res["gates"]}
        summaries = {s["provider"]: s for s in res["summaries"]}
        # Text is byte-identical, so WER is clean...
        self.assertEqual(
            summaries["stub:shifted"]["wer_verbatim"]["wer_micro"], 0.0)
        # ...and the migration still fails, on the metric that matters.
        self.assertEqual(gates["stub:shifted"]["verdict"], "FAIL")
        self.assertIn("bucket disagreement",
                      gates["stub:shifted"]["blocking"])

    def test_check_only_makes_no_provider_calls(self):
        runner = self._load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            rc = runner.main(["--manifest", self._corpus(tmp), "--check"])
            self.assertEqual(rc, 0)          # audio present, deck present

    def test_scaffold_creates_layout_that_then_loads(self):
        runner = self._load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            p = os.path.join(tmp, "manifest.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump({"takes": [{
                    "take_id": "t1", "audio": "audio/t1.mp3",
                    "reference_text": "refs/t1.txt", "language": "en",
                    "accent": "polish-l2-en", "accent_l1": "pl"}]}, fh)
            # Before: the manifest cannot load (reference path unresolved).
            self.assertTrue(corpus.load_manifest(p)["load_errors"])
            self.assertEqual(runner.main(["--manifest", p, "--scaffold"]), 0)
            # After: it loads clean, with the reference correctly absent
            # rather than silently filled with placeholder prose.
            c = corpus.load_manifest(p)
            self.assertEqual(c["load_errors"], [])
            self.assertEqual(len(c["takes"]), 1)
            self.assertFalse(c["takes"][0]["reference_text"])
            self.assertTrue(os.path.isdir(os.path.join(tmp, "audio")))

    def test_no_language_hint_mode_marks_results_auto_detected(self):
        from asr_eval import providers

        # Provider mishears Polish-accented English as Polish.
        providers.register("stub:flipper")(lambda path, **kw: {
            "text": "alpha bravo charlie delta", "duration": 10.0,
            "language": "pl", "segments": [],
            "words": [_w("alpha", 4.8), _w("bravo", 5.2),
                      _w("charlie", 6.0), _w("delta", 7.0)]})

        runner = self._load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            for name in ("t1.mp3", "t2.mp3"):
                open(os.path.join(tmp, name), "wb").close()
            p = os.path.join(tmp, "manifest.json")
            with open(p, "w", encoding="utf-8") as fh:
                json.dump({"takes": [{
                    "take_id": tid, "audio": f"{tid}.mp3",
                    "reference_text": "alpha bravo charlie delta",
                    "language": "en", "accent": "polish-l2-en",
                    "accent_l1": "pl", "slides": 2,
                    "slide_advances": [{"index": 0, "t_ms": 0},
                                       {"index": 1, "t_ms": 5000}],
                } for tid in ("t1", "t2")]}, fh)
            out = os.path.join(tmp, "res.json")
            rc = runner.main(["--manifest", p, "--providers", "stub:flipper",
                              "--baseline", "stub:flipper",
                              "--no-language-hint", "--out", out, "--force"])
            with open(out, encoding="utf-8") as fh:
                res = json.load(fh)

        ld = res["summaries"][0]["language_detection"]
        self.assertEqual(ld["checked"], 2)
        self.assertEqual(ld["wrong"], 2)
        self.assertEqual(ld["flips_to_l1"], 2)
        self.assertEqual(ld["auto_detected"], 2)
        self.assertEqual(ld["hinted"], 0)
        # Baseline is not gated, so the run itself is clean...
        self.assertEqual(rc, 0)
        # ...but the flip is recorded and would block any candidate.
        g = report.gate(res["summaries"][0])
        self.assertIn("language flip", g["blocking"])

    def test_unknown_provider_is_rejected(self):
        runner = self._load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            rc = runner.main(["--manifest", self._corpus(tmp),
                              "--providers", "nope:not-a-model", "--force"])
            self.assertEqual(rc, 2)


class AgreementOnlyTests(unittest.TestCase):
    """The zero-transcription first read: audio + slide timelines only."""

    def _corpus_no_refs(self, tmp):
        for name in ("t1.mp3", "t2.mp3"):
            open(os.path.join(tmp, name), "wb").close()
        p = os.path.join(tmp, "manifest.json")
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"takes": [{
                "take_id": tid, "audio": f"{tid}.mp3", "language": "en",
                "accent": "polish-l2-en", "accent_l1": "pl", "slides": 2,
                "slide_advances": [{"index": 0, "t_ms": 0},
                                   {"index": 1, "t_ms": 5000}],
            } for tid in ("t1", "t2")]}, fh)
        return p

    def test_missing_references_block_by_default(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = corpus.load_manifest(self._corpus_no_refs(tmp))
            r = corpus.readiness(c)
            self.assertFalse(r["ready"])
            self.assertTrue(any("reference_text" in b for b in r["blockers"]))

    def test_agreement_only_does_not_block_on_missing_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = corpus.load_manifest(self._corpus_no_refs(tmp))
            r = corpus.readiness(c, require_reference=False)
            self.assertTrue(r["ready"])
            self.assertTrue(r["can_compute_slide_bucket"])
            self.assertFalse(r["can_compute_wer"])
            self.assertTrue(any("AGREEMENT-ONLY" in w for w in r["warnings"]))

    def test_end_to_end_agreement_run_needs_no_transcripts(self):
        from asr_eval import providers

        providers.register("stub:inc")(lambda path, **kw: {
            "text": "alpha bravo charlie delta", "duration": 10.0,
            "language": "en", "segments": [],
            "words": [_w("alpha", 4.8), _w("bravo", 5.2),
                      _w("charlie", 6.0), _w("delta", 7.0)]})
        providers.register("stub:cand")(lambda path, **kw: {
            "text": "alpha bravo charlie delta", "duration": 10.0,
            "language": "en", "segments": [],
            "words": [_w("alpha", 5.4), _w("bravo", 5.8),
                      _w("charlie", 6.6), _w("delta", 7.6)]})

        runner = RunnerEndToEndTests._load_runner()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "res.json")
            rc = runner.main(["--manifest", self._corpus_no_refs(tmp),
                              "--providers", "stub:inc,stub:cand",
                              "--baseline", "stub:inc",
                              "--agreement-only", "--out", out])
            self.assertEqual(rc, 0)          # no gate verdict to fail on
            with open(out, encoding="utf-8") as fh:
                res = json.load(fh)

        cand = next(s for s in res["summaries"] if s["provider"] == "stub:cand")
        # No reference anywhere...
        self.assertIsNone(cand["wer_verbatim"]["wer_micro"])
        # ...and the metric that decides the migration still computed.
        self.assertAlmostEqual(cand["slide_bucket"]["disagreement_rate"], 0.25)
        t = next(x for x in res["triage"] if x["provider"] == "stub:cand")
        self.assertEqual(t["risk"], "HIGH")
        self.assertIn("AGREEMENT, not accuracy", t["caveat"])


class TriageTests(unittest.TestCase):

    def _summary(self, bd, **kw):
        base = {
            "provider": "cand", "takes_total": 8, "takes_usable": 8,
            "takes_failed": 0, "failure_reasons": [],
            "slide_bucket": {"disagreement_rate": bd,
                             "boundary_disagreement_rate": bd * 2,
                             "worst_slide_word_delta": 3},
            "timing": {"tier": "tier3_agreement", "p90_ms": 120.0},
            "language_detection": {"checked": 8, "wrong": 0,
                                   "flips_to_l1": 0, "flip_rate": 0.0},
        }
        base.update(kw)
        return base

    def test_low_risk_when_bucketing_matches(self):
        t = report.triage(self._summary(0.0005))
        self.assertEqual(t["risk"], "LOW")
        self.assertIn("not urgency", t["recommendation"])

    def test_moderate_risk_band(self):
        self.assertEqual(report.triage(self._summary(0.01))["risk"], "MODERATE")

    def test_high_risk_demands_the_corpus(self):
        t = report.triage(self._summary(0.08))
        self.assertEqual(t["risk"], "HIGH")
        self.assertIn("REQUIRED", t["recommendation"])

    def test_any_language_flip_forces_high_regardless_of_bucketing(self):
        t = report.triage(self._summary(
            0.0001, language_detection={"checked": 8, "wrong": 1,
                                        "flips_to_l1": 1, "flip_rate": 0.125}))
        self.assertEqual(t["risk"], "HIGH")
        self.assertTrue(any("WRONG LANGUAGE" in n for n in t["notes"]))

    def test_unmeasurable_when_no_deck_timeline(self):
        t = report.triage(self._summary(
            0.01, slide_bucket={"disagreement_rate": None}))
        self.assertEqual(t["risk"], "UNMEASURABLE")

    def test_unmeasurable_when_provider_produced_nothing(self):
        t = report.triage(self._summary(0.01, takes_usable=0,
                                        failure_reasons=["no timestamps"]))
        self.assertEqual(t["risk"], "UNMEASURABLE")

    def test_never_claims_the_candidate_is_better(self):
        # The caveat is load-bearing: triage sizes the change, it does not
        # say which direction it goes.
        for bd in (0.0001, 0.01, 0.08):
            self.assertIn("not accuracy", report.triage(self._summary(bd))["caveat"])


class RenderTests(unittest.TestCase):

    def test_render_does_not_raise_on_sparse_summary(self):
        s = report.summarize("x", [{"take": {}, "result": {
            "coverage": {"ok": False}, "skipped": "no word timestamps"}}])
        out = report.render([s], [report.gate(s)])
        self.assertIn("x", out)
        self.assertIn("FAIL", out)


if __name__ == "__main__":
    unittest.main()
