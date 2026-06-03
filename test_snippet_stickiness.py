"""Unit tests for services.snippet_stickiness (willab Readout §5).

Pure-ish module (no numpy/db at import); LLM call patched. Tests the
shaping/clamping contract + the all-empty short-circuit + the
LLM-failure fallback.

Run: python3 -m unittest test_snippet_stickiness
"""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock


class ShapeTests(unittest.TestCase):
    """_shape: map per_snippet array onto snippets, clamp + clean."""

    def _shape(self, parsed, snippets):
        from services.snippet_stickiness import _shape
        return _shape(parsed, snippets)

    def test_aligns_and_passes_snippet_id(self):
        out = self._shape(
            [{"composite": 0.7, "comment": "Stayed on one idea."},
             {"composite": 0.2, "comment": "Jumped around."}],
            [{"id": "a"}, {"id": "b"}],
        )
        self.assertEqual(out[0]["snippet_id"], "a")
        self.assertEqual(out[0]["composite"], 0.7)
        self.assertEqual(out[0]["comment"], "Stayed on one idea.")
        self.assertEqual(out[1]["snippet_id"], "b")

    def test_clamps_out_of_range(self):
        out = self._shape(
            [{"composite": 1.8, "comment": "x"},
             {"composite": -0.5, "comment": "y"}],
            [{"id": "a"}, {"id": "b"}],
        )
        self.assertEqual(out[0]["composite"], 1.0)
        self.assertEqual(out[1]["composite"], 0.0)

    def test_non_numeric_and_bool_composite_to_none(self):
        out = self._shape(
            [{"composite": "0.5", "comment": "x"},
             {"composite": True, "comment": "y"}],
            [{"id": "a"}, {"id": "b"}],
        )
        self.assertIsNone(out[0]["composite"])
        self.assertIsNone(out[1]["composite"])

    def test_empty_comment_to_none(self):
        out = self._shape([{"composite": 0.5, "comment": "   "}], [{"id": "a"}])
        self.assertIsNone(out[0]["comment"])

    def test_long_comment_truncated(self):
        from services.snippet_stickiness import _MAX_COMMENT_LEN
        out = self._shape(
            [{"composite": 0.5, "comment": "x" * (_MAX_COMMENT_LEN + 50)}],
            [{"id": "a"}],
        )
        self.assertLessEqual(len(out[0]["comment"]), _MAX_COMMENT_LEN + 1)
        self.assertTrue(out[0]["comment"].endswith("…"))

    def test_short_llm_array_pads_with_none(self):
        # model returned 1 entry for 3 snippets → 2 trailing all-None
        out = self._shape([{"composite": 0.5, "comment": "ok"}],
                          [{"id": "a"}, {"id": "b"}, {"id": "c"}])
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0]["composite"], 0.5)
        self.assertIsNone(out[1]["composite"])
        self.assertIsNone(out[1]["comment"])
        self.assertIsNone(out[2]["composite"])

    def test_long_llm_array_truncated_to_snippets(self):
        out = self._shape(
            [{"composite": 0.1, "comment": "a"},
             {"composite": 0.2, "comment": "b"},
             {"composite": 0.3, "comment": "c"}],
            [{"id": "x"}],
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["composite"], 0.1)

    def test_non_list_parsed_yields_all_none(self):
        out = self._shape(None, [{"id": "a"}, {"id": "b"}])
        self.assertEqual(len(out), 2)
        for e in out:
            self.assertIsNone(e["composite"])
            self.assertIsNone(e["comment"])


class ScoreTests(unittest.TestCase):

    def test_empty_snippets_returns_empty(self):
        from services.snippet_stickiness import score_snippets_stickiness
        self.assertEqual(score_snippets_stickiness([]), [])

    def test_all_empty_transcripts_skip_llm_all_none(self):
        from services import snippet_stickiness as mod
        # Patch _llm_score to blow up if called — it must NOT be called.
        with patch.object(mod, "_llm_score",
                          side_effect=AssertionError("LLM should be skipped")):
            out = mod.score_snippets_stickiness([
                {"id": "a", "transcript": ""},
                {"id": "b", "transcript": "   "},
            ])
        self.assertEqual(len(out), 2)
        for e in out:
            self.assertIsNone(e["composite"])
            self.assertIsNone(e["comment"])

    def test_llm_failure_yields_all_none(self):
        from services import snippet_stickiness as mod
        with patch.object(mod, "_llm_score", return_value=None):
            out = mod.score_snippets_stickiness([
                {"id": "a", "transcript": "real content here"},
            ])
        self.assertEqual(len(out), 1)
        self.assertIsNone(out[0]["composite"])
        self.assertIsNone(out[0]["comment"])

    def test_happy_path_with_mocked_llm(self):
        from services import snippet_stickiness as mod
        with patch.object(
            mod, "_llm_score",
            return_value=[{"composite": 0.72, "comment": "Built on one idea."}],
        ):
            out = mod.score_snippets_stickiness([
                {"id": "a", "transcript": "i kept talking about the demo"},
            ])
        self.assertEqual(out[0]["composite"], 0.72)
        self.assertEqual(out[0]["comment"], "Built on one idea.")
        self.assertEqual(out[0]["snippet_id"], "a")


if __name__ == "__main__":
    unittest.main()
