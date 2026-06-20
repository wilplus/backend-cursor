"""GET /v2/user/strengths — presentation-grouped strong-sides view.

New contract (FE handoff):
  general:       no-deck moments + their features + rank
  presentations: grouped by a STABLE presentation_id (hash of deck text);
                 each carries best_lines (cross-take best per slide) +
                 takes[] numbered chronologically (take_number = 1, 2, ...).
"""
from __future__ import annotations

import unittest

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _RT_ERR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _RT_ERR = e


@unittest.skipIf(_RT_ERR is not None, f"needs app deps: {_RT_ERR}")
class StrengthsV2Tests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._origs = {}
        # Two takes of the SAME deck text (different ref URLs — to prove
        # presentation_id groups by CONTENT, not URL) + a no-deck session.
        self.SAME_DECK = [
            {"title": "Intro", "body": "welcome"},
            {"title": "Wrap-up", "body": "thank you"},
        ]
        self._patch("get_strong_sides_library", lambda uid, tag=None: [
            # take 2 (newer): two strong snippets
            {"session_id": "t2", "snippet_id": "t2a", "tag": "strong",
             "note": "better open", "created_at": "2026-06-12",
             "snippet_ref": {"transcript": "opening v2", "start_offset_ms": 1000,
                             "duration_ms": 7000, "audio_ref": "p/t2.wav",
                             "features": {"speech_rate": 130}}},
            {"session_id": "t2", "snippet_id": "t2b", "tag": "strong",
             "note": "good close", "created_at": "2026-06-12",
             "snippet_ref": {"transcript": "wrap v2", "start_offset_ms": 12000,
                             "duration_ms": 6000, "audio_ref": "p/t2.wav",
                             "features": {"speech_rate": 120}}},
            # take 1 (older): one strong snippet (the opening was best back then)
            {"session_id": "t1", "snippet_id": "t1a", "tag": "strong",
             "note": "first opener", "created_at": "2026-06-05",
             "snippet_ref": {"transcript": "opening v1", "start_offset_ms": 1500,
                             "duration_ms": 7000, "audio_ref": "p/t1.wav",
                             "features": {"speech_rate": 100}}},
            # no-deck session
            {"session_id": "flat", "snippet_id": "f1", "tag": "strong",
             "note": "warm", "created_at": "2026-05-01",
             "snippet_ref": {"transcript": "warmth", "start_offset_ms": 0,
                             "duration_ms": 5000, "audio_ref": "p/f.wav",
                             "features": {"speech_rate": 110}}},
        ])
        self._patch("v2_get_session_by_id", lambda sid: {
            "t2": {"created_at": "2026-06-12T00:00:00Z",
                   "intake_context": {
                       "topic": "Q3 launch",
                       "slides": self.SAME_DECK,
                       "slide_advances": [{"index": 0, "t_ms": 0},
                                          {"index": 1, "t_ms": 10000}],
                       "presentation_ref": "https://x/t2.pdf"}},
            "t1": {"created_at": "2026-06-05T00:00:00Z",
                   "intake_context": {
                       "topic": "Q3 launch",
                       "slides": self.SAME_DECK,
                       "slide_advances": [{"index": 0, "t_ms": 0}],
                       "presentation_ref": "https://x/t1.pdf"}},  # DIFFERENT URL
            "flat": {"created_at": "2026-05-01T00:00:00Z",
                     "intake_context": {"topic": "casual practice"}},
        }.get(sid))
        # ranks: t2a=1 (best in t2), t2b=2, t1a=3 (worst overall)
        self._patch("get_snippets_by_session", lambda sid: {
            "t2": [{"id": "t2a", "metrics": {"rank": 1}},
                   {"id": "t2b", "metrics": {"rank": 2}}],
            "t1": [{"id": "t1a", "metrics": {"rank": 3}}],
        }.get(sid, []))

    def tearDown(self):
        for attr, orig in self._origs.items():
            setattr(v2.db, attr, orig)

    def _patch(self, attr, fn):
        self._origs[attr] = getattr(v2.db, attr, None)
        setattr(v2.db, attr, fn)

    def _get(self):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2.v2_user_get_strengths.__wrapped__()
            return status, resp.get_json()

    def test_top_level_shape(self):
        status, data = self._get()
        self.assertEqual(status, 200)
        self.assertIn("general", data)
        self.assertIn("presentations", data)
        # no-deck session → general
        self.assertEqual(len(data["general"]), 1)
        self.assertEqual(data["general"][0]["transcript"], "warmth")
        # features and rank carried through on general moments too
        self.assertEqual(data["general"][0]["features"], {"speech_rate": 110})

    def test_uncoached_presentation_appears_pre_coach(self):
        # Founder 2026-06-18: a freshly-recorded deck appears on Trainings even
        # with NO coach strong lines — deck + take + arc_id present, best_lines
        # empty (they layer in on publish). Only patches the new lab-list source.
        self._patch("v2_list_user_lab_sessions", lambda uid: [
            {"id": "rec1", "created_at": "2026-06-20T00:00:00Z", "arc_id": "arc-x",
             "intake_context": {
                 "topic": "Brand new talk",
                 "slides": [{"title": "New", "body": "deck"}],
                 "presentation_ref": "https://x/rec1.pdf",
                 "slide_advances": [{"index": 0, "t_ms": 0}]}},
        ])
        _, data = self._get()
        by_arc = {p.get("arc_id"): p for p in data["presentations"]}
        self.assertIn("arc-x", by_arc)               # the un-coached deck shows up
        new_pres = by_arc["arc-x"]
        self.assertEqual(new_pres["presentation_ref"], "https://x/rec1.pdf")
        self.assertEqual(new_pres["best_lines"], [])  # no coach lines yet
        self.assertEqual(len(new_pres["takes"]), 1)
        self.assertEqual(new_pres["takes"][0]["session_id"], "rec1")

    def test_group_arc_id_picks_the_arc_with_most_takes(self):
        # A deck re-recorded as a SEPARATE arc spreads takes across arc_ids.
        # The group-level arc_id (what the FE opens the best-presentation with)
        # must be the MOST-DEVELOPED arc (most takes), not the newest stray
        # 1-take re-record — else the FE take-count and the overlay's per-arc
        # count disagree ("open" → "need 2 more").
        deck = [{"title": "Canon", "body": "deck"}]
        adv = [{"index": 0, "t_ms": 0}]
        self._patch("v2_list_user_lab_sessions", lambda uid: [
            # arc-A: 2 takes; arc-B: 1 take (the newest). Same deck → one group.
            {"id": "b1", "created_at": "2026-06-20T03:00:00Z", "arc_id": "arc-B",
             "intake_context": {"topic": "T", "slides": deck,
                                "presentation_ref": "https://x/b1.pdf",
                                "slide_advances": adv}},
            {"id": "a2", "created_at": "2026-06-20T02:00:00Z", "arc_id": "arc-A",
             "intake_context": {"topic": "T", "slides": deck,
                                "presentation_ref": "https://x/a2.pdf",
                                "slide_advances": adv}},
            {"id": "a1", "created_at": "2026-06-20T01:00:00Z", "arc_id": "arc-A",
             "intake_context": {"topic": "T", "slides": deck,
                                "presentation_ref": "https://x/a1.pdf",
                                "slide_advances": adv}},
        ])
        _, data = self._get()
        pres = next(p for p in data["presentations"] if len(p["takes"]) == 3)
        self.assertEqual(pres["arc_id"], "arc-A")  # 2 takes beats arc-B's 1

    def test_stable_presentation_id_groups_by_content_not_url(self):
        # t1 and t2 have DIFFERENT presentation_ref URLs but the SAME deck text
        # → must group under ONE presentation.
        _, data = self._get()
        self.assertEqual(len(data["presentations"]), 1)
        pres = data["presentations"][0]
        self.assertTrue(pres["presentation_id"])
        # presentation_ref reflects the LATEST take (t2's URL)
        self.assertEqual(pres["presentation_ref"], "https://x/t2.pdf")
        # the slides come back too
        self.assertEqual([s["title"] for s in pres["slides"]], ["Intro", "Wrap-up"])

    def test_take_numbers_chronological(self):
        _, data = self._get()
        takes = data["presentations"][0]["takes"]
        # Newest take FIRST in response
        self.assertEqual([t["session_id"] for t in takes], ["t2", "t1"])
        # But take_number is chronological — t1 = take 1, t2 = take 2
        by_session = {t["session_id"]: t for t in takes}
        self.assertEqual(by_session["t1"]["take_number"], 1)
        self.assertEqual(by_session["t2"]["take_number"], 2)

    def test_best_lines_pick_lowest_rank_across_takes(self):
        # Slide 0 (Intro): t2a (rank 1) vs t1a (rank 3) → t2a wins
        # Slide 1 (Wrap-up): only t2b (rank 2)
        _, data = self._get()
        bl = data["presentations"][0]["best_lines"]
        self.assertEqual(len(bl), 2)
        by_idx = {b["slide_index"]: b for b in bl}
        self.assertEqual(by_idx[0]["transcript"], "opening v2")
        self.assertEqual(by_idx[0]["rank"], 1)
        self.assertEqual(by_idx[0]["features"], {"speech_rate": 130})
        self.assertEqual(by_idx[1]["transcript"], "wrap v2")
        self.assertEqual(by_idx[1]["rank"], 2)

    def test_features_carried_through_to_take_snippets(self):
        _, data = self._get()
        t2 = next(t for t in data["presentations"][0]["takes"]
                  if t["session_id"] == "t2")
        # The "Intro" slide in take t2 carries t2a, with its features
        snips = t2["slides"][0]["strong_snippets"]
        self.assertEqual(snips[0]["features"], {"speech_rate": 130})

    def test_empty_library_returns_empty(self):
        self._patch("get_strong_sides_library", lambda uid, tag=None: [])
        status, data = self._get()
        self.assertEqual(status, 200)
        self.assertEqual(data, {"general": [], "presentations": []})


class PresentationIdHashTests(unittest.TestCase):
    """The hash is the cornerstone for grouping — test it directly."""

    def test_same_content_same_hash(self):
        if v2 is None:
            self.skipTest(_RT_ERR)
        fn = v2._presentation_id_from_slides
        a = [{"title": "Intro", "body": "hi"}, {"title": "End", "body": ""}]
        b = [{"title": "Intro", "body": "hi"}, {"title": "End", "body": ""}]
        self.assertEqual(fn(a), fn(b))

    def test_different_content_different_hash(self):
        if v2 is None:
            self.skipTest(_RT_ERR)
        fn = v2._presentation_id_from_slides
        a = [{"title": "Intro", "body": "hi"}]
        b = [{"title": "Intro", "body": "hello"}]
        self.assertNotEqual(fn(a), fn(b))

    def test_empty_deck_empty_id(self):
        if v2 is None:
            self.skipTest(_RT_ERR)
        self.assertEqual(v2._presentation_id_from_slides([]), "")
        self.assertEqual(v2._presentation_id_from_slides(None), "")


if __name__ == "__main__":
    unittest.main()
