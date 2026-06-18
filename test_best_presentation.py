"""Best-Presentation composition (willab Prompt D §4). Pure parts + the
orchestration with a fake db and stubbed LLM (no network).

Run: python3 -m unittest test_best_presentation
"""
from __future__ import annotations

import unittest

import services.best_presentation as bp


def _cand(slide_index, sid, direction, **kw):
    base = {
        "slide_index": slide_index, "snippet_id": sid,
        "transcript": kw.get("transcript", f"line {sid}"),
        "audio_ref": kw.get("audio_ref", f"s3://{sid}"),
        "take_index": kw.get("take_index", 1),
        "direction": direction, "breakthrough": kw.get("breakthrough", False),
        "activation": kw.get("activation", 0.5),
        "slide_stickiness": kw.get("slide_stickiness", 0.0),
        "tag": kw.get("tag"),
    }
    return base


class SelectBestPerSlideTests(unittest.TestCase):
    def test_challenge_outranks_threat_by_rating(self):
        # NOT a hard filter — challenge wins because its rating is boosted
        # (+1) while threat is penalised (-1), even with lower activation.
        cands = [
            _cand(0, "t", "threat", activation=0.9),
            _cand(0, "c", "challenge", activation=0.4),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "c")

    def test_threat_surfaces_when_it_is_all_the_slide_has(self):
        # No challenge-only filter → a slide with only threat still gets its
        # best line (never blank).
        cands = [
            _cand(0, "lo", "threat", activation=0.2),
            _cand(0, "hi", "threat", activation=0.8),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "hi")

    def test_best_challenge_per_slide(self):
        cands = [
            _cand(0, "lo", "challenge", activation=0.2),
            _cand(0, "hi", "challenge", activation=0.9),
            _cand(1, "x", "challenge", activation=0.5),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "hi")
        self.assertEqual(best[1]["snippet_id"], "x")

    def test_breakthrough_wins_over_higher_activation(self):
        cands = [
            _cand(0, "plain", "challenge", activation=0.9),
            _cand(0, "bt", "challenge", activation=0.2, breakthrough=True),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "bt")

    def test_drops_bad_slide_index_and_input(self):
        self.assertEqual(bp.select_best_per_slide(None), {})
        self.assertEqual(bp.select_best_per_slide([_cand(-1, "x", "challenge")]), {})


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self._orig = bp._render_composition

    def tearDown(self):
        bp._render_composition = self._orig

    def test_verbatim_fallback_when_llm_returns_none(self):
        bp._render_composition = lambda picks, slides: None
        picks = {0: _cand(0, "c", "challenge", transcript="my best line")}
        out = bp.compose_presentation(picks, [{"title": "S1", "body": "b"}])
        self.assertEqual(out[0]["text"], "my best line")  # verbatim
        self.assertEqual(out[0]["title"], "S1")

    def test_light_edit_used_when_present(self):
        bp._render_composition = lambda picks, slides: {0: "my polished line"}
        picks = {0: _cand(0, "c", "challenge", transcript="my best line")}
        out = bp.compose_presentation(picks, [{"title": "S1", "body": "b"}])
        self.assertEqual(out[0]["text"], "my polished line")

    def test_empty_slide_stays_blank(self):
        bp._render_composition = lambda picks, slides: {}
        # slide 1 has no pick → blank, never invented.
        picks = {0: _cand(0, "c", "challenge", transcript="line")}
        out = bp.compose_presentation(picks, [{"title": "S1"}, {"title": "S2"}])
        self.assertEqual(out[1]["text"], "")
        self.assertIsNone(out[1]["audio_ref"])

    def test_ac9_no_internal_score_leaks(self):
        bp._render_composition = lambda picks, slides: {}
        picks = {0: _cand(0, "c", "challenge")}
        out = bp.compose_presentation(picks, [{"title": "S1"}])
        for k in ("_score", "activation", "slide_stickiness", "direction", "snippet_id"):
            self.assertNotIn(k, out[0])
        self.assertIn("breakthrough", out[0])  # the marker is allowed

    def test_breakthrough_note_only_when_breakthrough(self):
        bp._render_composition = lambda picks, slides: {}
        picks = {
            0: {**_cand(0, "bt", "challenge", breakthrough=True),
                "note": "Comfortable pace, natural rise and fall."},
            1: {**_cand(1, "plain", "challenge"), "note": "Some note."},
        }
        out = bp.compose_presentation(picks, [{"title": "S1"}, {"title": "S2"}])
        # the breakthrough slide carries the "why"; the plain one does not
        self.assertEqual(out[0]["breakthrough_note"],
                         "Comfortable pace, natural rise and fall.")
        self.assertIsNone(out[1]["breakthrough_note"])


class ProgressTests(unittest.TestCase):
    def test_counts_and_ready_threshold(self):
        self.assertEqual(bp.presentation_progress(0), {
            "takes_done": 0, "takes_target": 3,
            "takes_remaining": 3, "ready": False,
        })
        self.assertTrue(bp.presentation_progress(3)["ready"])
        self.assertTrue(bp.presentation_progress(4)["ready"])
        self.assertFalse(bp.presentation_progress(2)["ready"])
        self.assertEqual(bp.presentation_progress(-5)["takes_done"], 0)

    def test_takes_remaining_drives_the_two_more_message(self):
        # 1 take → "we need 2 more takes to generate your best lines".
        self.assertEqual(bp.presentation_progress(1)["takes_remaining"], 2)
        self.assertEqual(bp.presentation_progress(3)["takes_remaining"], 0)
        self.assertEqual(bp.presentation_progress(5)["takes_remaining"], 0)


class _FakeDB:
    def __init__(self, sessions, snippets_by_session, labels_by_session):
        self._sessions = sessions
        self._snips = snippets_by_session
        self._labels = labels_by_session

    def get_arc_sessions(self, arc_id):
        return list(self._sessions)

    def get_snippets_by_session(self, sid):
        return list(self._snips.get(sid, []))

    def get_training_labels(self, sid):
        return list(self._labels.get(sid, []))


class BuildTests(unittest.TestCase):
    def setUp(self):
        self._orig = bp._render_composition
        bp._render_composition = lambda picks, slides: None  # verbatim path

    def tearDown(self):
        bp._render_composition = self._orig

    def _db(self):
        # One take, advances map every offset → slide 0. threat then challenge.
        sessions = [{
            "id": "s1", "take_index": 1,
            "intake_context": {
                "slides": [{"title": "Slide 1", "body": "the point"}],
                "slide_advances": [{"index": 0, "t_ms": 0}],
            },
        }]
        snips = {"s1": [
            {"id": "t1", "start_offset_ms": 0, "transcript": "nervous open",
             "storage_path": "s3://t1", "metrics": {"overall_score": 0.9}},
            {"id": "c1", "start_offset_ms": 2000, "transcript": "strong close",
             "storage_path": "s3://c1", "metrics": {"overall_score": 0.4}},
        ]}
        labels = {"s1": [
            {"snippet_id": "t1", "value": "threat"},
            {"snippet_id": "c1", "value": "challenge"},
        ]}
        return _FakeDB(sessions, snips, labels)

    def test_build_surfaces_challenge_breakthrough(self):
        out = bp.build_best_presentation("arc1", database=self._db())
        self.assertEqual(out["progress"]["takes_done"], 1)
        self.assertFalse(out["ready"])  # only 1 of 3 takes
        slide0 = out["slides"][0]
        # The challenge close wins (threat 'nervous open' is filtered out),
        # and it follows a threat → breakthrough.
        self.assertEqual(slide0["text"], "strong close")
        self.assertTrue(slide0["breakthrough"])
        self.assertEqual(slide0["audio_ref"], "s3://c1")

    def test_no_coach_labels_no_breakthrough_badge(self):
        # Coach-confirmed only: with NO coach labels, there's no breakthrough
        # badge even though the moments would form a threat→challenge sequence
        # if a model had guessed. Selection falls back to acoustics (the louder
        # 'nervous open', overall 0.9, wins).
        sessions = [{
            "id": "s1", "take_index": 1,
            "intake_context": {
                "slides": [{"title": "S1", "body": "p"}],
                "slide_advances": [{"index": 0, "t_ms": 0}],
            },
        }]
        snips = {"s1": [
            {"id": "t1", "start_offset_ms": 0, "transcript": "nervous open",
             "storage_path": "s3://t1", "metrics": {"overall_score": 0.9}},
            {"id": "c1", "start_offset_ms": 2000, "transcript": "strong close",
             "storage_path": "s3://c1", "metrics": {"overall_score": 0.4}},
        ]}
        out = bp.build_best_presentation(
            "arc1", database=_FakeDB(sessions, snips, {}),  # no labels
        )
        slide0 = out["slides"][0]
        self.assertFalse(slide0["breakthrough"])
        self.assertIsNone(slide0["breakthrough_note"])
        self.assertEqual(slide0["text"], "nervous open")  # acoustic fallback

    def test_build_empty_arc(self):
        empty = _FakeDB([], {}, {})
        out = bp.build_best_presentation("arc1", database=empty)
        self.assertFalse(out["ready"])
        self.assertEqual(out["progress"]["takes_done"], 0)
        self.assertEqual(out["slides"], [])


if __name__ == "__main__":
    unittest.main()
