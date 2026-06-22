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

    def test_prefers_complete_sentence_over_higher_scored_fragment(self):
        # #4: a complete line beats a higher-scored truncated fragment.
        cands = [
            _cand(0, "frag", "challenge", activation=0.9,
                  transcript="and going back to the days when I"),
            _cand(0, "whole", "challenge", activation=0.3,
                  transcript="We are raising two million dollars."),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "whole")

    def test_keeps_best_when_no_candidate_is_complete(self):
        # No complete line on the slide → still keep the best-scored (#4: never
        # blank).
        cands = [
            _cand(0, "lo", "challenge", activation=0.2, transcript="a stray bit"),
            _cand(0, "hi", "challenge", activation=0.9, transcript="another stray"),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "hi")

    def test_dedupes_same_line_across_slides(self):
        # #4: the same line never lands on two slides — slide 1 takes its next.
        same = "We are raising two million dollars."
        cands = [
            _cand(0, "s0", "challenge", activation=0.9, transcript=same),
            _cand(1, "s1", "challenge", activation=0.9, transcript=same),
            _cand(1, "alt", "challenge", activation=0.4,
                  transcript="So here is exactly where it goes."),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "s0")
        self.assertEqual(best[1]["snippet_id"], "alt")  # not the duplicate

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
        # stable shape — the playback span keys exist (null) on a blank slide.
        self.assertIsNone(out[1]["start_offset_ms"])
        self.assertIsNone(out[1]["duration_ms"])

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
    def __init__(self, sessions, snippets_by_session, labels_by_session,
                 edits=None):
        self._sessions = sessions
        self._snips = snippets_by_session
        self._labels = labels_by_session
        self._edits = edits or {}

    def get_arc_sessions(self, arc_id):
        return list(self._sessions)

    def get_snippets_by_session(self, sid):
        return list(self._snips.get(sid, []))

    def get_training_labels(self, sid):
        return list(self._labels.get(sid, []))

    def get_best_presentation_edits(self, arc_id):
        return dict(self._edits)


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
            {"id": "t1", "start_offset_ms": 0, "duration_ms": 1800,
             "transcript": "nervous open",
             "storage_path": "s3://t1", "metrics": {"overall_score": 0.9}},
            {"id": "c1", "start_offset_ms": 2000, "duration_ms": 1500,
             "transcript": "strong close",
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
        # #1 — the line's span rides through so the FE clamps playback to it.
        self.assertEqual(slide0["start_offset_ms"], 2000)
        self.assertEqual(slide0["duration_ms"], 1500)

    def test_coach_reviewed_false_pre_publish(self):
        # Auto-composed from the takes before any coach review → draft.
        out = bp.build_best_presentation("arc1", database=self._db())
        self.assertFalse(out["coach_reviewed"])

    def test_coach_reviewed_true_when_a_take_is_published(self):
        db = self._db()
        db._sessions[0]["results_published_at"] = "2026-06-21T00:00:00Z"
        out = bp.build_best_presentation("arc1", database=db)
        self.assertTrue(out["coach_reviewed"])

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
            {"id": "t1", "start_offset_ms": 0, "duration_ms": 1800,
             "transcript": "nervous open",
             "storage_path": "s3://t1", "metrics": {"overall_score": 0.9}},
            {"id": "c1", "start_offset_ms": 2000, "duration_ms": 1500,
             "transcript": "strong close",
             "storage_path": "s3://c1", "metrics": {"overall_score": 0.4}},
        ]}
        out = bp.build_best_presentation(
            "arc1", database=_FakeDB(sessions, snips, {}),  # no labels
        )
        slide0 = out["slides"][0]
        self.assertFalse(slide0["breakthrough"])
        self.assertIsNone(slide0["breakthrough_note"])
        self.assertEqual(slide0["text"], "nervous open")  # acoustic fallback

    def test_saved_edit_overrides_composed_text(self):
        # A pencil-edit for slide 0 overrides the composed text + flags edited.
        db = self._db()
        db._edits = {0: "my hand-edited line"}
        out = bp.build_best_presentation("arc1", database=db)
        slide0 = out["slides"][0]
        self.assertEqual(slide0["text"], "my hand-edited line")
        self.assertTrue(slide0["edited"])

    def test_unedited_slides_flag_false(self):
        out = bp.build_best_presentation("arc1", database=self._db())
        self.assertFalse(out["slides"][0]["edited"])

    def test_presentation_ref_not_clobbered_by_later_take_without_it(self):
        # take 1 has the deck PDF; take 2 (equal slides) dropped it → the ref
        # must SURVIVE (first non-null wins, never clobbered to None).
        sessions = [
            {"id": "s1", "take_index": 1, "intake_context": {
                "slides": [{"title": "S1", "body": "b"}],
                "slide_advances": [{"index": 0, "t_ms": 0}],
                "presentation_ref": "https://deck.pdf"}},
            {"id": "s2", "take_index": 2, "intake_context": {
                "slides": [{"title": "S1", "body": "b"}],
                "slide_advances": [{"index": 0, "t_ms": 0}]}},  # no ref
        ]
        snips = {
            "s1": [{"id": "a", "start_offset_ms": 0, "transcript": "x",
                    "storage_path": "s3://a", "metrics": {"overall_score": 0.5}}],
            "s2": [{"id": "b", "start_offset_ms": 0, "transcript": "y",
                    "storage_path": "s3://b", "metrics": {"overall_score": 0.5}}],
        }
        out = bp.build_best_presentation("arc1", database=_FakeDB(sessions, snips, {}))
        self.assertEqual(out["presentation_ref"], "https://deck.pdf")

    def test_payload_carries_presentation_ref_and_slide_body(self):
        # FE renders the deck via presentation_ref (PDF) or title/body fallback.
        sessions = [{
            "id": "s1", "take_index": 1,
            "intake_context": {
                "slides": [{"title": "S1", "body": "the body"}],
                "slide_advances": [{"index": 0, "t_ms": 0}],
                "presentation_ref": "https://deck.pdf",
            },
        }]
        snips = {"s1": [{"id": "a", "start_offset_ms": 0, "transcript": "line",
                         "storage_path": "s3://a", "metrics": {"overall_score": 0.5}}]}
        out = bp.build_best_presentation("arc1", database=_FakeDB(sessions, snips, {}))
        self.assertEqual(out["presentation_ref"], "https://deck.pdf")
        self.assertEqual(out["slides"][0]["body"], "the body")

    def test_build_empty_arc(self):
        empty = _FakeDB([], {}, {})
        out = bp.build_best_presentation("arc1", database=empty)
        self.assertFalse(out["ready"])
        self.assertEqual(out["progress"]["takes_done"], 0)
        self.assertEqual(out["slides"], [])


class ArcBreakthroughsTests(unittest.TestCase):
    """build_arc_breakthroughs (#5) — every coach-confirmed breakthrough in the
    arc with playback data, newest → oldest. Same gate as the badge."""

    def _db(self, labels):
        # take 1: t1(threat)→c1(challenge); take 2: t2(threat)→c2(challenge).
        sessions = [
            {"id": "s1", "take_index": 1, "created_at": "2026-06-05T00:00:00Z",
             "intake_context": {"slides": [{"title": "S1", "body": "p"}],
                                "slide_advances": [{"index": 0, "t_ms": 0}]}},
            {"id": "s2", "take_index": 2, "created_at": "2026-06-12T00:00:00Z",
             "intake_context": {"slides": [{"title": "S1", "body": "p"}],
                                "slide_advances": [{"index": 0, "t_ms": 0}]}},
        ]
        snips = {
            "s1": [
                {"id": "t1", "start_offset_ms": 0, "duration_ms": 1800,
                 "transcript": "nervous open take1", "storage_path": "s3://t1",
                 "metrics": {"overall_score": 0.9}},
                {"id": "c1", "start_offset_ms": 2000, "duration_ms": 1500,
                 "transcript": "strong close take1", "storage_path": "s3://c1",
                 "metrics": {"overall_score": 0.4}},
            ],
            "s2": [
                {"id": "t2", "start_offset_ms": 0, "duration_ms": 1700,
                 "transcript": "nervous open take2", "storage_path": "s3://t2",
                 "metrics": {"overall_score": 0.8}},
                {"id": "c2", "start_offset_ms": 2000, "duration_ms": 1600,
                 "transcript": "strong close take2", "storage_path": "s3://c2",
                 "metrics": {"overall_score": 0.5}},
            ],
        }
        return _FakeDB(sessions, snips, labels)

    def test_collects_coach_confirmed_breakthroughs_newest_first(self):
        labels = {
            "s1": [{"snippet_id": "t1", "value": "threat"},
                   {"snippet_id": "c1", "value": "challenge"}],
            "s2": [{"snippet_id": "t2", "value": "threat"},
                   {"snippet_id": "c2", "value": "challenge"}],
        }
        out = bp.build_arc_breakthroughs("arc1", database=self._db(labels))
        self.assertEqual(out["count"], 2)
        # newest take first (s2 created later than s1)
        self.assertEqual([b["snippet_id"] for b in out["breakthroughs"]],
                         ["c2", "c1"])
        top = out["breakthroughs"][0]
        # playback data rides through for the FE list
        self.assertEqual(top["audio_ref"], "s3://c2")
        self.assertEqual(top["start_offset_ms"], 2000)
        self.assertEqual(top["duration_ms"], 1600)
        self.assertEqual(top["session_id"], "s2")
        self.assertEqual(top["slide_index"], 0)

    def test_only_breakthroughs_no_threat_or_plain(self):
        labels = {"s1": [{"snippet_id": "t1", "value": "threat"},
                         {"snippet_id": "c1", "value": "challenge"}]}
        out = bp.build_arc_breakthroughs("arc1", database=self._db(labels))
        ids = [b["snippet_id"] for b in out["breakthroughs"]]
        self.assertEqual(ids, ["c1"])          # the threat t1 is NOT included
        self.assertNotIn("t1", ids)

    def test_no_coach_labels_empty(self):
        out = bp.build_arc_breakthroughs("arc1", database=self._db({}))
        self.assertEqual(out, {"breakthroughs": [], "count": 0})

    def test_ac9_no_scores_leak(self):
        labels = {"s1": [{"snippet_id": "t1", "value": "threat"},
                         {"snippet_id": "c1", "value": "challenge"}]}
        out = bp.build_arc_breakthroughs("arc1", database=self._db(labels))
        b = out["breakthroughs"][0]
        for k in ("_score", "activation", "direction", "coach_direction",
                  "metrics", "slide_stickiness"):
            self.assertNotIn(k, b)

    def test_empty_arc(self):
        out = bp.build_arc_breakthroughs("arc1", database=_FakeDB([], {}, {}))
        self.assertEqual(out, {"breakthroughs": [], "count": 0})


if __name__ == "__main__":
    unittest.main()
