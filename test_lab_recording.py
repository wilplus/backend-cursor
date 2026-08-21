"""Unit tests for the pure helpers in services.lab_recording.

The orchestration (process_lab_recording) does decode/Whisper/db I/O —
not locally testable. These cover the pure, contract-shaping helpers
the Readout payload depends on: transcript-window slicing, feature
mapping, payload assembly. No numpy/db/LLM needed.

Run: python3 -m unittest test_lab_recording
"""
from __future__ import annotations

import unittest


class FeatureMapTests(unittest.TestCase):

    def _map(self, m):
        from services.lab_recording import build_readout_features
        return build_readout_features(m)

    def test_maps_renamed_keys(self):
        out = self._map({
            "wpm": 145, "pause_ms": 220, "dynamic_db": 12.0,
            "f0_mean": 165.0, "f0_sd": 28.0, "voiced_ratio": 0.7,
            "pause_ratio": 0.32, "f0_slope": 5.0, "pause_regularity": 0.8,
            "intensity_envelope": -1.2, "f0_mid_end_delta": -10.0,
        })
        self.assertEqual(out["speech_rate"], 145)     # ← wpm
        self.assertEqual(out["mean_pause"], 220)       # ← pause_ms (MS; FE converts)
        self.assertEqual(out["loudness_range"], 12.0)  # ← dynamic_db
        self.assertEqual(out["f0_mean"], 165.0)
        self.assertEqual(out["pause_ratio"], 0.32)

    def test_mean_pause_stays_milliseconds(self):
        """Guard-rail — mean_pause is emitted as the raw pause_ms value in
        MILLISECONDS; the FE converts ms→seconds at its mapper (FE PR #62).
        A server-side /1000 here would double-convert (BE PR #32, reverted).
        Do not 'fix' this to seconds without removing the FE-side divide."""
        self.assertEqual(self._map({"pause_ms": 200})["mean_pause"], 200)
        self.assertEqual(self._map({"pause_ms": 1500})["mean_pause"], 1500)
        self.assertIsNone(self._map({"pause_ms": None})["mean_pause"])
        self.assertIsNone(self._map({})["mean_pause"])

    def test_all_keys_present(self):
        out = self._map({})
        self.assertEqual(set(out.keys()), {
            "f0_mean", "f0_sd", "speech_rate", "mean_pause", "pause_ratio",
            "loudness_range", "voiced_ratio", "f0_slope", "pause_regularity",
            "intensity_envelope", "f0_mid_end_delta",
            # B2 — display-ready seconds twin of mean_pause (unit in name).
            "mean_pause_seconds",
            # Display-ready speed % (50 wpm = 100%) — twin of speech_rate.
            "speech_rate_pct",
        })

    def test_mean_pause_seconds_is_ms_over_1000(self):
        # B2: the self-describing seconds field = raw mean_pause (ms) / 1000.
        self.assertEqual(self._map({"pause_ms": 400})["mean_pause_seconds"], 0.4)
        self.assertEqual(self._map({"pause_ms": 253300})["mean_pause_seconds"], 253.3)
        self.assertIsNone(self._map({"pause_ms": None})["mean_pause_seconds"])
        # legacy mean_pause stays raw ms (unchanged contract)
        self.assertEqual(self._map({"pause_ms": 400})["mean_pause"], 400)

    def test_none_metrics_all_none(self):
        out = self._map(None)
        self.assertEqual(len(out), 13)
        for v in out.values():
            self.assertIsNone(v)


class PayloadAssemblyTests(unittest.TestCase):

    def _build(self, snippets, sticky):
        from services.lab_recording import build_readout_payload
        return build_readout_payload(snippets, sticky)

    def test_assembles_snippet_with_features_and_stickiness(self):
        out = self._build(
            [{
                "id": "s1", "index": 1, "transcript": "hi",
                "audio_ref": "https://x/parent.webm",
                "start_offset_ms": 0, "duration_ms": 8000,
                "metrics": {"wpm": 140, "f0_mean": 160.0},
            }],
            [{"snippet_id": "s1", "composite": 0.72, "comment": "On one idea."}],
        )
        snip = out["snippets"][0]
        self.assertEqual(snip["id"], "s1")
        self.assertEqual(snip["index"], 1)
        self.assertEqual(snip["audio_ref"], "https://x/parent.webm")
        self.assertEqual(snip["features"]["speech_rate"], 140)
        self.assertEqual(snip["stickiness"]["composite"], 0.72)
        self.assertEqual(snip["stickiness"]["comment"], "On one idea.")
        self.assertTrue(out["voice_metrics_available"])   # f0_mean present

    def test_voice_metrics_unavailable_when_no_acoustics(self):
        # snippet exists but every acoustic metric is null (quiet/silent take) —
        # and speech_rate alone does NOT count as voice.
        out = self._build(
            [{"id": "s1", "index": 1, "metrics": {"wpm": 130}}], [],
        )
        self.assertFalse(out["voice_metrics_available"])

    def test_voice_metrics_unavailable_on_empty(self):
        self.assertFalse(self._build([], [])["voice_metrics_available"])

    def test_voice_metrics_available_on_loudness_only(self):
        out = self._build(
            [{"id": "s1", "index": 1, "metrics": {"dynamic_db": 14.0}}], [],
        )
        self.assertTrue(out["voice_metrics_available"])   # loudness_range

    def test_stickiness_matched_by_id_not_order(self):
        out = self._build(
            [
                {"id": "a", "index": 1, "metrics": {}},
                {"id": "b", "index": 2, "metrics": {}},
            ],
            # reversed order — must still match by snippet_id
            [
                {"snippet_id": "b", "composite": 0.2, "comment": "b"},
                {"snippet_id": "a", "composite": 0.9, "comment": "a"},
            ],
        )
        self.assertEqual(out["snippets"][0]["stickiness"]["composite"], 0.9)
        self.assertEqual(out["snippets"][1]["stickiness"]["composite"], 0.2)

    def test_missing_stickiness_yields_none_block(self):
        out = self._build(
            [{"id": "s1", "index": 1, "metrics": {}}],
            [],  # no stickiness
        )
        self.assertIsNone(out["snippets"][0]["stickiness"]["composite"])
        self.assertIsNone(out["snippets"][0]["stickiness"]["comment"])

    def test_empty_snippets(self):
        self.assertEqual(self._build([], [])["snippets"], [])

    def test_transcript_defaults_to_empty_string(self):
        out = self._build([{"id": "s1", "index": 1, "metrics": {}}], [])
        self.assertEqual(out["snippets"][0]["transcript"], "")


class CanonicalPieceContractTests(unittest.TestCase):
    """The recording pipeline has one moment identity: canonical pieces."""

    WORDS = [
        {"word": "A", "start": 0.0, "end": 0.2},
        {"word": "clear", "start": 0.2, "end": 0.5},
        {"word": "opening.", "start": 0.5, "end": 0.9},
    ]

    def test_deckless_words_build_exact_canonical_pieces(self):
        from services.lab_recording import _build_canonical_pieces

        pieces = _build_canonical_pieces(self.WORDS, None)

        self.assertEqual(len(pieces), 1)
        self.assertEqual(pieces[0]["transcript"], "A clear opening.")
        self.assertEqual(pieces[0]["start_offset_ms"], 0)
        self.assertEqual(pieces[0]["duration_ms"], 900)

    def test_missing_word_timestamps_is_an_explicit_processing_failure(self):
        from services.lab_recording import (
            PiecesCanonicalUnavailable,
            _build_canonical_pieces,
        )

        with self.assertRaisesRegex(
            PiecesCanonicalUnavailable,
            "word-level timestamps",
        ):
            _build_canonical_pieces([], {"slides": [{"title": "Opening"}]})

    def test_malformed_words_cannot_silently_activate_another_pipeline(self):
        from services.lab_recording import (
            PiecesCanonicalUnavailable,
            _build_canonical_pieces,
        )

        with self.assertRaises(PiecesCanonicalUnavailable):
            _build_canonical_pieces(
                [{"word": "missing timestamps"}],
                None,
            )

    def test_legacy_creation_switch_and_branch_are_absent(self):
        import inspect
        from services import lab_recording as lr

        module_source = inspect.getsource(lr)
        process_source = inspect.getsource(lr.process_lab_recording)
        self.assertNotIn("PIECES_CANONICAL_ENABLED", module_source)
        self.assertNotIn("_pieces_canonical_enabled", module_source)
        self.assertNotIn("segment_into_snippets", process_source)
        self.assertNotIn("select_extremes_by_control", process_source)
        self.assertNotIn("dedupe_window_transcripts", module_source)


class VoiceMetricsDiagnosticTests(unittest.TestCase):
    def _diagnose(self, snippets, segments):
        from services.lab_recording import _voice_metrics_diagnostic
        return _voice_metrics_diagnostic(snippets, segments)

    def test_no_persisted_pieces(self):
        self.assertEqual(self._diagnose([], [{"text": "spoken"}]),
                         (False, "no_snippets"))

    def test_pieces_without_acoustics(self):
        snippets = [{"metrics": {"wpm": 130}}]
        self.assertEqual(self._diagnose(snippets, [{"text": "spoken"}]),
                         (False, "no_voiced_speech"))

    def test_acoustics_without_segment_transcript(self):
        snippets = [{"metrics": {"f0_mean": 150.0}}]
        self.assertEqual(self._diagnose(snippets, []),
                         (True, "ok_acoustics_no_transcript"))

    def test_acoustics_and_transcript(self):
        snippets = [{"metrics": {"dynamic_db": 10.0}}]
        self.assertEqual(self._diagnose(snippets, [{"text": "spoken"}]),
                         (True, "ok"))


class FullTranscriptTextTests(unittest.TestCase):
    def _text(self, segments, words):
        from services.lab_recording import _full_transcript_text
        return _full_transcript_text(segments, words)

    def test_segment_text_has_priority(self):
        self.assertEqual(
            self._text([{"text": "Segment truth."}], [{"word": "words"}]),
            "Segment truth.",
        )

    def test_words_are_the_fallback(self):
        self.assertEqual(
            self._text([], [{"word": "Word"}, {"word": "truth."}]),
            "Word truth.",
        )

    def test_malformed_and_blank_entries_are_ignored(self):
        self.assertEqual(
            self._text([None, {"text": "  "}], ["bad", {"word": " usable "}]),
            "usable",
        )

    def test_empty_sources_return_empty_text(self):
        self.assertEqual(self._text(None, None), "")


class OverallRankingTests(unittest.TestCase):
    PRELIM = [
        {"start_ms": 3000},
        {"start_ms": 1000},
        {"start_ms": 2000},
    ]

    def _rank(self, sticky, slide_scores, budget):
        from services.lab_recording import _compute_overall_ranking
        return _compute_overall_ranking(
            self.PRELIM,
            sticky,
            slide_scores,
            budget,
        )

    def test_blends_delivery_and_slide_scores(self):
        overall, ranks = self._rank(
            [{"composite": 0.8}, {"composite": 0.6}],
            [{"composite": 0.4}, {"composite": 1.0}],
            {0, 1},
        )
        self.assertAlmostEqual(overall[0], 0.6)
        self.assertAlmostEqual(overall[1], 0.8)
        self.assertEqual(ranks, {1: 1, 0: 2})

    def test_missing_slide_score_falls_back_to_delivery(self):
        overall, ranks = self._rank([{"composite": 0.7}], [], {0})
        self.assertEqual(overall, {0: 0.7})
        self.assertEqual(ranks, {0: 1})

    def test_only_budget_pieces_receive_overall_and_rank(self):
        overall, ranks = self._rank(
            [{"composite": 0.9}, {"composite": 0.8}, {"composite": 0.7}],
            [],
            {1},
        )
        self.assertEqual(overall, {1: 0.8})
        self.assertEqual(ranks, {1: 1})

    def test_equal_scores_use_earliest_offset(self):
        _, ranks = self._rank(
            [{"composite": 0.5}, {"composite": 0.5}, {"composite": 0.5}],
            [],
            {0, 1, 2},
        )
        self.assertEqual(ranks, {1: 1, 2: 2, 0: 3})

    def test_non_numeric_delivery_score_is_zero(self):
        overall, _ = self._rank([{"composite": "high"}], [], {0})
        self.assertEqual(overall, {0: 0.0})



if __name__ == "__main__":
    unittest.main()
