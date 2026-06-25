"""Unit tests for the pure helpers in services.lab_recording.

The orchestration (process_lab_recording) does decode/Whisper/db I/O —
not locally testable. These cover the pure, contract-shaping helpers
the Readout payload depends on: transcript-window slicing, feature
mapping, payload assembly. No numpy/db/LLM needed.

Run: python3 -m unittest test_lab_recording
"""
from __future__ import annotations

import unittest


class SliceTranscriptTests(unittest.TestCase):

    def _slice(self, segs, a, b):
        from services.lab_recording import slice_transcript_for_window
        return slice_transcript_for_window(segs, a, b)

    SEGS = [
        {"start": 0.0, "end": 3.0, "text": "Hello there"},
        {"start": 3.0, "end": 6.0, "text": "this is the middle"},
        {"start": 6.0, "end": 9.0, "text": "and the end"},
    ]

    def test_window_picks_overlapping_segments(self):
        # [2.5s, 6.5s] overlaps seg0 (ends 3.0), seg1 (3-6), seg2 (starts 6.0)
        out = self._slice(self.SEGS, 2500, 6500)
        self.assertIn("Hello there", out)
        self.assertIn("this is the middle", out)
        self.assertIn("and the end", out)

    def test_window_excludes_non_overlapping(self):
        # [3.0s, 6.0s] — seg0 ends exactly at 3.0 (e>start false), seg2
        # starts exactly at 6.0 (s<end false) → only the middle
        out = self._slice(self.SEGS, 3000, 6000)
        self.assertEqual(out, "this is the middle")

    def test_empty_segments_returns_empty(self):
        self.assertEqual(self._slice([], 0, 5000), "")
        self.assertEqual(self._slice(None, 0, 5000), "")

    def test_malformed_segments_skipped(self):
        segs = [
            {"start": "bad", "end": 3.0, "text": "skip me"},
            "not a dict",
            {"start": 0.0, "end": 2.0, "text": "keep me"},
        ]
        out = self._slice(segs, 0, 5000)
        self.assertEqual(out, "keep me")


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


if __name__ == "__main__":
    unittest.main()
