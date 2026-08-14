"""Best-Presentation composition (willab Prompt D §4). Pure parts + the
orchestration with a fake db and stubbed LLM (no network).

Run: python3 -m unittest test_best_presentation
"""
from __future__ import annotations

import unittest

import services.best_presentation as bp


def _cand(slide_index, sid, confidence, **kw):
    """One ranking candidate. ``confidence`` is the MACHINE composite in
    [-1, 1] — SPEC §7.2's re-point of the retired challenge/threat direction
    term. Positive = the speaker sounded assured on this line, negative =
    unsure, 0.0/None = the dead-zone middle."""
    base = {
        "slide_index": slide_index, "snippet_id": sid,
        "transcript": kw.get("transcript", f"line {sid}"),
        "audio_ref": kw.get("audio_ref", f"s3://{sid}"),
        "take_index": kw.get("take_index", 1),
        "machine_confidence": confidence,
        "activation": kw.get("activation", 0.5),
        "slide_stickiness": kw.get("slide_stickiness", 0.0),
        "tag": kw.get("tag"),
    }
    return base


class SelectBestPerSlideTests(unittest.TestCase):
    def test_an_assured_line_outranks_an_unsure_one_by_rating(self):
        # NOT a hard filter — the assured line wins because confidence lifts
        # its rating and doubt sinks the other, even at lower activation.
        cands = [
            _cand(0, "t", -0.8, activation=0.9),
            _cand(0, "c", 0.8, activation=0.4),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "c")

    def test_an_unsure_line_surfaces_when_it_is_all_the_slide_has(self):
        # No confidence-only filter → a slide with only unsure lines still
        # gets its best one (never blank).
        cands = [
            _cand(0, "lo", -0.8, activation=0.2),
            _cand(0, "hi", -0.8, activation=0.8),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "hi")

    def test_best_line_per_slide(self):
        cands = [
            _cand(0, "lo", 0.8, activation=0.2),
            _cand(0, "hi", 0.8, activation=0.9),
            _cand(1, "x", 0.8, activation=0.5),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "hi")
        self.assertEqual(best[1]["snippet_id"], "x")

    def test_no_quorum_bonus_survives_selection(self):
        # Founder verdict 2026-08-13 evening: `_W_B` deleted. A stray
        # album_quorum key on a candidate is inert — higher activation wins.
        cands = [
            _cand(0, "plain", 0.8, activation=0.9),
            _cand(0, "bt", 0.8, activation=0.2),
        ]
        cands[1]["album_quorum"] = True   # stale producer key — must be inert
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "plain")

    def test_prefers_complete_sentence_over_higher_scored_fragment(self):
        # #4: a complete line beats a higher-scored truncated fragment.
        cands = [
            _cand(0, "frag", 0.8, activation=0.9,
                  transcript="and going back to the days when I"),
            _cand(0, "whole", 0.8, activation=0.3,
                  transcript="We are raising two million dollars."),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "whole")

    def test_keeps_best_when_no_candidate_is_complete(self):
        # No complete line on the slide → still keep the best-scored (#4: never
        # blank).
        cands = [
            _cand(0, "lo", 0.8, activation=0.2, transcript="a stray bit"),
            _cand(0, "hi", 0.8, activation=0.9, transcript="another stray"),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "hi")

    def test_dedupes_same_line_across_slides(self):
        # #4: the same line never lands on two slides — slide 1 takes its next.
        same = "We are raising two million dollars."
        cands = [
            _cand(0, "s0", 0.8, activation=0.9, transcript=same),
            _cand(1, "s1", 0.8, activation=0.9, transcript=same),
            _cand(1, "alt", 0.8, activation=0.4,
                  transcript="So here is exactly where it goes."),
        ]
        best = bp.select_best_per_slide(cands)
        self.assertEqual(best[0]["snippet_id"], "s0")
        self.assertEqual(best[1]["snippet_id"], "alt")  # not the duplicate

    def test_drops_bad_slide_index_and_input(self):
        self.assertEqual(bp.select_best_per_slide(None), {})
        self.assertEqual(bp.select_best_per_slide([_cand(-1, "x", 0.8)]), {})


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self._orig = bp._render_composition

    def tearDown(self):
        bp._render_composition = self._orig

    def test_verbatim_fallback_when_llm_returns_none(self):
        bp._render_composition = lambda picks, slides: None
        picks = {0: _cand(0, "c", 0.8, transcript="my best line")}
        out = bp.compose_presentation(picks, [{"title": "S1", "body": "b"}])
        self.assertEqual(out[0]["text"], "my best line")  # verbatim
        self.assertEqual(out[0]["title"], "S1")

    def test_light_edit_used_when_present(self):
        bp._render_composition = lambda picks, slides: {0: "my polished line"}
        picks = {0: _cand(0, "c", 0.8, transcript="my best line")}
        out = bp.compose_presentation(picks, [{"title": "S1", "body": "b"}])
        self.assertEqual(out[0]["text"], "my polished line")

    def test_empty_slide_stays_blank(self):
        bp._render_composition = lambda picks, slides: {}
        # slide 1 has no pick → blank, never invented.
        picks = {0: _cand(0, "c", 0.8, transcript="line")}
        out = bp.compose_presentation(picks, [{"title": "S1"}, {"title": "S2"}])
        self.assertEqual(out[1]["text"], "")
        self.assertIsNone(out[1]["audio_ref"])
        # stable shape — the playback span keys exist (null) on a blank slide.
        self.assertIsNone(out[1]["start_offset_ms"])
        self.assertIsNone(out[1]["duration_ms"])

    def test_ac9_no_internal_score_leaks(self):
        bp._render_composition = lambda picks, slides: {}
        picks = {0: _cand(0, "c", 0.8)}
        out = bp.compose_presentation(picks, [{"title": "S1"}])
        # RANKING internals must never leak (AC-9). snippet_id is NOT one —
        # it's an opaque reference the FE deep-links the PDF's "Key moment"
        # to /game?snippet=<id> (P8), same class as take_index / audio_ref.
        for k in ("_score", "activation", "slide_stickiness", "direction"):
            self.assertNotIn(k, out[0])
        self.assertIn("breakthrough", out[0])  # the marker is allowed
        self.assertEqual(out[0]["snippet_id"], "c")  # the sanctioned deep-link id

    def test_breakthrough_note_only_when_breakthrough(self):
        bp._render_composition = lambda picks, slides: {}
        picks = {
            0: {**_cand(0, "bt", 0.8), "breakthrough": True,
                "note": "Comfortable pace, natural rise and fall."},
            1: {**_cand(1, "plain", 0.8), "note": "Some note."},
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
                 edits=None, coach_edits=None):
        self._sessions = sessions
        self._snips = snippets_by_session
        self._labels = labels_by_session
        self._edits = edits or {}
        self._coach_edits = coach_edits or {}

    def get_arc_sessions(self, arc_id):
        return list(self._sessions)

    def get_snippets_by_session(self, sid):
        return list(self._snips.get(sid, []))

    def get_training_labels(self, sid):
        return list(self._labels.get(sid, []))

    def get_best_presentation_edits(self, arc_id):
        return dict(self._edits)

    def get_coach_best_presentation_edits(self, arc_id):
        return dict(self._coach_edits)


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

    def test_build_ranks_on_the_measured_terms_not_the_coach_label(self):
        """THE BEHAVIOUR CHANGE OF THE 2026-08-13 RE-POINT, pinned.

        This fixture is the old blend's showcase: 'nervous open' has the far
        better content score (0.9 vs 0.4) and lost anyway, because a coach
        `challenge` mark on 'strong close' was worth +1.0 direction AND the
        +2.5 breakthrough bonus — 3.5 points of override on a 1.6-point scale.
        One subjective label outranked every measurement in the blend.

        SPEC §7.2 retired the direction term and re-pointed the bonus onto the
        album quorum, so the labels no longer touch ranking at all and the
        higher-activation line wins on its merits. THE BADGE IS UNAFFECTED —
        it is still the coach's own mark, on the snippet they marked (see the
        next test). Ranking and badging were one thing; now they are two.

        coach_view=True: this verifies COMPOSITION/SELECTION logic, the
        surface where the auto-assembled draft is actually visible (founder
        2026-07-06 — the student never sees it pre-coach-correction; see
        CoachFinalizedGateTests below for that gate itself).
        """
        out = bp.build_best_presentation(
            "arc1", database=self._db(), coach_view=True,
        )
        self.assertEqual(out["progress"]["takes_done"], 1)
        self.assertFalse(out["ready"])  # only 1 of 3 takes
        slide0 = out["slides"][0]
        self.assertEqual(slide0["text"], "nervous open")
        self.assertEqual(slide0["audio_ref"], "s3://t1")
        # #1 — the line's span rides through so the FE clamps playback to it.
        self.assertEqual(slide0["start_offset_ms"], 0)
        self.assertEqual(slide0["duration_ms"], 1800)

    def test_the_breakthrough_badge_still_follows_the_coachs_own_mark(self):
        """The re-point took the coach's label OUT OF RANKING; it did not take
        the badge away from them. `c1` carries the coach's `challenge` mark, so
        `c1` is the breakthrough — whether or not it wins its slide."""
        out = bp.build_best_presentation(
            "arc1", database=self._db(), coach_view=True,
        )
        by_id = {s.get("snippet_id"): s for s in out["slides"]}
        self.assertNotIn("c1", by_id)          # it did not win the slide…
        # …and the winning slide is not badged, because its snippet was the
        # one the coach marked `threat`.
        self.assertFalse(out["slides"][0]["breakthrough"])

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
            coach_view=True,  # composition-logic test — see module docstring
        )
        slide0 = out["slides"][0]
        self.assertFalse(slide0["breakthrough"])
        self.assertIsNone(slide0["breakthrough_note"])
        self.assertEqual(slide0["text"], "nervous open")  # acoustic fallback

    def test_saved_edit_overrides_composed_text(self):
        # A pencil-edit for slide 0 overrides the composed text + flags edited.
        # User edits only apply once coach_finalized (founder 2026-07-06), so
        # seed a coach edit too — the user's edit still wins on top of it.
        db = self._db()
        db._coach_edits = {0: "the coach's corrected line"}
        db._edits = {0: "my hand-edited line"}
        out = bp.build_best_presentation("arc1", database=db)
        slide0 = out["slides"][0]
        self.assertTrue(out["coach_finalized"])
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


class CoachFinalizedGateTests(unittest.TestCase):
    """Founder 2026-07-06 — the coach-owned ideal-text correction. The raw
    auto-assembled draft must NEVER reach the student: every slide's `text`
    is hidden ("") until the coach has corrected EVERY slide (coach_finalized),
    regardless of arc payment (payment is a separate, route-level 402 gate).
    ``coach_view=True`` (the coach's OWN editing surface) always sees the
    current draft/progress, never hidden, and does not apply the student's
    pencil-edits."""

    def setUp(self):
        self._orig = bp._render_composition
        bp._render_composition = lambda picks, slides: None  # verbatim path

    def tearDown(self):
        bp._render_composition = self._orig

    def _two_slide_db(self, coach_edits=None, user_edits=None):
        sessions = [{
            "id": "s1", "take_index": 1,
            "intake_context": {
                "slides": [{"title": "Slide 1", "body": "p1"},
                           {"title": "Slide 2", "body": "p2"}],
                "slide_advances": [{"index": 0, "t_ms": 0},
                                   {"index": 1, "t_ms": 5000}],
            },
        }]
        snips = {"s1": [
            {"id": "a", "start_offset_ms": 0, "duration_ms": 1000,
             "transcript": "auto line one", "storage_path": "s3://a",
             "metrics": {"overall_score": 0.5}},
            {"id": "b", "start_offset_ms": 5000, "duration_ms": 1000,
             "transcript": "auto line two", "storage_path": "s3://b",
             "metrics": {"overall_score": 0.5}},
        ]}
        return _FakeDB(sessions, snips, {}, edits=user_edits,
                       coach_edits=coach_edits)

    def test_no_coach_edits_not_finalized_student_sees_nothing(self):
        out = bp.build_best_presentation(
            "arc1", database=self._two_slide_db(),
        )
        self.assertFalse(out["coach_finalized"])
        for s in out["slides"]:
            self.assertEqual(s["text"], "")
            self.assertFalse(s["coach_edited"])

    def test_partial_coach_edits_still_not_finalized(self):
        # Only slide 0 corrected → the WHOLE arc stays hidden from the student
        # (all-or-nothing, mirrors the "every take published" precedent).
        out = bp.build_best_presentation(
            "arc1", database=self._two_slide_db(
                coach_edits={0: "coach fixed slide one"}),
        )
        self.assertFalse(out["coach_finalized"])
        for s in out["slides"]:
            self.assertEqual(s["text"], "")

    def test_every_slide_corrected_finalizes_and_shows_coach_text(self):
        out = bp.build_best_presentation(
            "arc1", database=self._two_slide_db(coach_edits={
                0: "coach fixed slide one", 1: "coach fixed slide two",
            }),
        )
        self.assertTrue(out["coach_finalized"])
        self.assertEqual(out["slides"][0]["text"], "coach fixed slide one")
        self.assertEqual(out["slides"][1]["text"], "coach fixed slide two")
        self.assertTrue(out["slides"][0]["coach_edited"])
        self.assertTrue(out["slides"][1]["coach_edited"])

    def test_user_pencil_edit_wins_over_coach_text_once_finalized(self):
        out = bp.build_best_presentation(
            "arc1", database=self._two_slide_db(
                coach_edits={0: "coach fixed slide one",
                             1: "coach fixed slide two"},
                user_edits={0: "user's own tweak"},
            ),
        )
        self.assertEqual(out["slides"][0]["text"], "user's own tweak")
        self.assertTrue(out["slides"][0]["edited"])
        # slide 1 has no user edit — coach text stands.
        self.assertEqual(out["slides"][1]["text"], "coach fixed slide two")
        self.assertFalse(out["slides"][1]["edited"])

    def test_coach_view_always_shows_draft_even_unfinalized(self):
        # coach_view=True: the coach's own preview — never hidden, no
        # "still preparing" state, regardless of finalized status.
        out = bp.build_best_presentation(
            "arc1", database=self._two_slide_db(), coach_view=True,
        )
        self.assertFalse(out["coach_finalized"])
        self.assertEqual(out["slides"][0]["text"], "auto line one")
        self.assertEqual(out["slides"][1]["text"], "auto line two")

    def test_coach_view_shows_own_partial_progress(self):
        out = bp.build_best_presentation(
            "arc1", database=self._two_slide_db(
                coach_edits={0: "coach fixed slide one"}),
            coach_view=True,
        )
        self.assertEqual(out["slides"][0]["text"], "coach fixed slide one")
        self.assertTrue(out["slides"][0]["coach_edited"])
        # slide 1 untouched by the coach — shows the auto draft, not hidden.
        self.assertEqual(out["slides"][1]["text"], "auto line two")
        self.assertFalse(out["slides"][1]["coach_edited"])

    def test_coach_view_ignores_user_pencil_edits(self):
        # The coach's editing surface is not confused by the student's own
        # personalization — it always shows auto/coach text, never the user's.
        out = bp.build_best_presentation(
            "arc1", database=self._two_slide_db(
                coach_edits={0: "coach fixed slide one",
                             1: "coach fixed slide two"},
                user_edits={0: "user's own tweak"},
            ),
            coach_view=True,
        )
        self.assertEqual(out["slides"][0]["text"], "coach fixed slide one")
        self.assertNotIn("edited", out["slides"][0])  # user-edit key not set


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

    def test_coach_note_and_video_ride_through(self):
        """The FE mapper contract (HANDOFF-BE-2026-07-28 §1): `note` IS the
        coach's key-moment note, `comment` is the system's explanation, and
        the FE renders exactly one (coach overrides system). `video_ref` is
        named to match the game so the FE reuses its player."""
        labels = {"s1": [{"snippet_id": "t1", "value": "threat"},
                         {"snippet_id": "c1", "value": "challenge"}]}
        db = self._db(labels)
        db.get_coach_snippet_drafts = lambda sid: ([
            {"snippet_id": "c1", "note": "This is where you took the room.",
             "breakthrough_video_ref": "r2://coach/bt-c1.mp4"},
            {"snippet_id": "t1", "note": "never surfaced (not a breakthrough)"},
        ] if sid == "s1" else [])
        out = bp.build_arc_breakthroughs("arc1", database=db)
        b = out["breakthroughs"][0]
        self.assertEqual(b["note"], "This is where you took the room.")
        self.assertEqual(b["video_ref"], "r2://coach/bt-c1.mp4")
        # The system explanation rides SEPARATELY — never in the coach slot.
        self.assertIn("comment", b)
        self.assertNotEqual(b["comment"], b["note"])

    def test_machine_text_never_wears_the_coach_slot(self):
        """No coach note → `note` is NULL, and the system's explanation sits
        in `comment`. Before 2026-07-28 `note` carried the machine text; the
        shipped FE renders `note` as the coach's words, so machine prose
        there would misattribute machine voice as the human coach."""
        labels = {"s1": [{"snippet_id": "t1", "value": "threat"},
                         {"snippet_id": "c1", "value": "challenge"}]}
        out = bp.build_arc_breakthroughs("arc1", database=self._db(labels))
        b = out["breakthroughs"][0]
        self.assertIsNone(b["note"])
        self.assertIsNone(b["video_ref"])
        # the system explanation exists for the fallback slot (metrics on the
        # fake rows carry no observation buckets, so "" is legal — the key
        # must exist either way)
        self.assertIn("comment", b)

    def test_drafts_read_failure_is_non_fatal(self):
        labels = {"s1": [{"snippet_id": "t1", "value": "threat"},
                         {"snippet_id": "c1", "value": "challenge"}]}
        db = self._db(labels)

        def _boom(_sid):
            raise RuntimeError("drafts table down")
        db.get_coach_snippet_drafts = _boom
        out = bp.build_arc_breakthroughs("arc1", database=db)
        self.assertEqual(out["count"], 1)
        self.assertIsNone(out["breakthroughs"][0]["note"])


class _CachingFakeDB(_FakeDB):
    """_FakeDB + the Part B cache methods + a snippet-read counter."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._cache: dict = {}
        self.snippet_reads = 0

    def get_snippets_by_session(self, sid):
        self.snippet_reads += 1
        return super().get_snippets_by_session(sid)

    def get_best_presentation_cache(self, arc_id):
        return self._cache.get(arc_id)

    def upsert_best_presentation_cache(self, arc_id, signature, payload):
        self._cache[arc_id] = {"signature": signature, "payload": payload}
        return True


class BestPresentationCacheTests(unittest.TestCase):
    """Part B — the composed slides are cached by arc + content signature."""

    def setUp(self):
        self._orig = bp._render_composition
        self.compose_calls = []
        bp._render_composition = lambda picks, slides: (
            self.compose_calls.append(1) or None  # verbatim path
        )

    def tearDown(self):
        bp._render_composition = self._orig

    def _db(self):
        sessions = [{"id": "s1", "take_index": 1, "intake_context": {
            "slides": [{"title": "S1", "body": "p"}],
            "slide_advances": [{"index": 0, "t_ms": 0}]}}]
        snips = {"s1": [{"id": "c1", "start_offset_ms": 0, "duration_ms": 1000,
                         "transcript": "line", "storage_path": "s3://c1",
                         "metrics": {"overall_score": 0.5}}]}
        return _CachingFakeDB(sessions, snips, {})

    def test_miss_then_hit_skips_compose_and_snippet_read(self):
        db = self._db()
        # coach_view=True: verifying cache behavior on the actual composed
        # text, the surface where it's visible pre-coach-finalization.
        out1 = bp.build_best_presentation("arc1", database=db, coach_view=True)
        self.assertEqual(len(self.compose_calls), 1)   # composed on the miss
        self.assertEqual(out1["slides"][0]["text"], "line")
        self.assertEqual(db.snippet_reads, 1)
        out2 = bp.build_best_presentation("arc1", database=db, coach_view=True)
        self.assertEqual(len(self.compose_calls), 1)   # HIT → no recompose
        self.assertEqual(db.snippet_reads, 1)          # HIT → no snippet read
        self.assertEqual(out2["slides"][0]["text"], "line")

    def test_new_take_busts_cache(self):
        db = self._db()
        bp.build_best_presentation("arc1", database=db)
        db._sessions.append({"id": "s2", "take_index": 2, "intake_context": {
            "slides": [{"title": "S1", "body": "p"}],
            "slide_advances": [{"index": 0, "t_ms": 0}]}})
        db._snips["s2"] = [{"id": "c2", "start_offset_ms": 0,
                            "duration_ms": 1000, "transcript": "line2",
                            "storage_path": "s3://c2",
                            "metrics": {"overall_score": 0.5}}]
        bp.build_best_presentation("arc1", database=db)
        self.assertEqual(len(self.compose_calls), 2)   # signature changed

    def test_coach_publish_busts_cache(self):
        db = self._db()
        bp.build_best_presentation("arc1", database=db)
        db._sessions[0]["results_published_at"] = "2026-06-22T00:00:00Z"
        bp.build_best_presentation("arc1", database=db)
        self.assertEqual(len(self.compose_calls), 2)

    def test_edits_applied_fresh_on_cache_hit(self):
        # User edits only apply once coach_finalized (founder 2026-07-06) —
        # seed a coach edit up front so the user edit added AFTER the cache is
        # warm still lands fresh on the hit (edits are never part of the cache).
        db = self._db()
        db._coach_edits = {0: "the coach's corrected line"}
        bp.build_best_presentation("arc1", database=db)   # miss → caches
        db._edits = {0: "my hand edit"}
        out = bp.build_best_presentation("arc1", database=db)  # hit
        self.assertEqual(len(self.compose_calls), 1)      # no recompose
        self.assertTrue(out["coach_finalized"])
        self.assertEqual(out["slides"][0]["text"], "my hand edit")
        self.assertTrue(out["slides"][0]["edited"])


class _BatchingFakeDB(_FakeDB):
    """_FakeDB + the batched arc reads — proves build_* uses ONE query each,
    not the per-take N+1."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.singular_snippet_calls = 0
        self.singular_label_calls = 0
        self.batch_snippet_calls = 0
        self.batch_label_calls = 0

    def get_snippets_by_session(self, sid):
        self.singular_snippet_calls += 1
        return super().get_snippets_by_session(sid)

    def get_training_labels(self, sid):
        self.singular_label_calls += 1
        return super().get_training_labels(sid)

    def get_snippets_by_sessions(self, ids, *, include_words=False):
        self.batch_snippet_calls += 1
        return {str(s): super(_BatchingFakeDB, self).get_snippets_by_session(s)
                for s in ids}

    def get_training_labels_by_sessions(self, ids):
        self.batch_label_calls += 1
        return {str(s): (super(_BatchingFakeDB, self).get_training_labels(s) or [])
                for s in ids}


class BatchedArcReadsTests(unittest.TestCase):
    """build_best_presentation / build_arc_breakthroughs read the whole arc in
    ONE snippets + ONE labels query (no per-take N+1)."""

    def setUp(self):
        self._orig = bp._render_composition
        bp._render_composition = lambda picks, slides: None  # verbatim path

    def tearDown(self):
        bp._render_composition = self._orig

    def _db(self):
        sessions = [
            {"id": "s1", "take_index": 1, "intake_context": {
                "slides": [{"title": "S1", "body": "p"}],
                "slide_advances": [{"index": 0, "t_ms": 0}]}},
            {"id": "s2", "take_index": 2, "intake_context": {
                "slides": [{"title": "S1", "body": "p"}],
                "slide_advances": [{"index": 0, "t_ms": 0}]}},
        ]
        snips = {
            "s1": [{"id": "a", "start_offset_ms": 0, "transcript": "one",
                    "storage_path": "s3://a", "metrics": {"overall_score": 0.6}}],
            "s2": [{"id": "b", "start_offset_ms": 0, "transcript": "two",
                    "storage_path": "s3://b", "metrics": {"overall_score": 0.5}}],
        }
        return _BatchingFakeDB(sessions, snips, {})

    def test_build_best_presentation_uses_one_query_each(self):
        db = self._db()
        # coach_view=True: verifying compose behavior, the surface where the
        # auto draft is visible (founder 2026-07-06 gate — see
        # CoachFinalizedGateTests).
        out = bp.build_best_presentation("arc1", database=db, coach_view=True)
        self.assertEqual(db.batch_snippet_calls, 1)   # ONE snippets query
        self.assertEqual(db.batch_label_calls, 1)     # ONE labels query
        self.assertEqual(db.singular_snippet_calls, 0)  # no per-take N+1
        self.assertEqual(db.singular_label_calls, 0)
        # behavior intact — slide 0 still composes the best line
        self.assertEqual(out["slides"][0]["text"], "one")

    def test_build_arc_breakthroughs_uses_one_query_each(self):
        db = self._db()
        bp.build_arc_breakthroughs("arc1", database=db)
        self.assertEqual(db.batch_snippet_calls, 1)
        self.assertEqual(db.batch_label_calls, 1)
        self.assertEqual(db.singular_snippet_calls, 0)
        self.assertEqual(db.singular_label_calls, 0)

    def test_matches_per_session_fallback_result(self):
        # the batched result equals the legacy per-session path (parity).
        # coach_view=True so the compared text is the actual composed content,
        # not both sides trivially "" (student view hides pre-finalization).
        batched = bp.build_best_presentation(
            "arc1", database=self._db(), coach_view=True,
        )
        legacy = bp.build_best_presentation(
            "arc1", database=_FakeDB(
                self._db()._sessions, self._db()._snips, {}),
            coach_view=True,
        )
        self.assertEqual([s["text"] for s in batched["slides"]],
                         [s["text"] for s in legacy["slides"]])



class KeyPhrasesTests(unittest.TestCase):
    """Backlog 1.7 — per-slide glanceable phrases from the winning pick's
    Say-It-Stronger upgrades. Display hints only (L1: never the text)."""

    def _sis(self, *upgrades):
        return {"already_strong": False,
                "upgrades": [{"original": o, "upgrade": u, "reason": None}
                             for o, u in upgrades],
                "rewrite_your_voice": "x", "rewrite_polished": "x",
                "why": None, "version": 1}

    def test_phrases_from_upgrades_dedup_and_cap(self):
        pick = {"say_it_stronger": self._sis(
            ("holds it tightly", "is firmly structured"),
            ("HOLDS IT TIGHTLY", "Is Firmly Structured"),  # dup, case-insens
            ("a", "b"), ("c", "d"), ("e", "f"), ("g", "h"), ("i", "j"),
        )}
        out = bp._key_phrases(pick)
        self.assertEqual(out[0], "is firmly structured")
        self.assertEqual(len(out), 5)  # capped
        self.assertEqual(len({p.lower() for p in out}), 5)  # deduped

    def test_over_long_phrase_skipped(self):
        pick = {"say_it_stronger": self._sis(("x", "y" * 61), ("a", "keep"))}
        self.assertEqual(bp._key_phrases(pick), ["keep"])

    def test_no_suggestions_empty(self):
        self.assertEqual(bp._key_phrases({}), [])
        self.assertEqual(bp._key_phrases({"say_it_stronger": None}), [])
        self.assertEqual(bp._key_phrases(None), [])

    def test_compose_carries_key_phrases_per_slide(self):
        picks = {0: {"transcript": "strong close", "say_it_stronger": self._sis(
            ("sort of good", "genuinely good"))}}
        slides = [{"title": "S1", "body": ""}, {"title": "S2", "body": ""}]
        orig = bp._render_composition
        bp._render_composition = lambda p, s: None
        try:
            out = bp.compose_presentation(picks, slides)
        finally:
            bp._render_composition = orig
        self.assertEqual(out[0]["key_phrases"], ["genuinely good"])
        self.assertEqual(out[1]["key_phrases"], [])  # no pick -> empty



class CorrectedVerbatimTests(unittest.TestCase):
    """Engine 2 (2026-07-11): the assembler's verbatim source is the COACH-
    corrected transcript when one exists — assembled from the corrected
    takes (L1: the coach's verbatim, never an AI rewrite)."""

    def setUp(self):
        self._orig = bp._render_composition
        bp._render_composition = lambda picks, slides: None  # verbatim path

    def tearDown(self):
        bp._render_composition = self._orig

    def _db(self, corrected=None):
        sessions = [{
            "id": "s1", "take_index": 1,
            "intake_context": {
                "slides": [{"title": "Slide 1", "body": "p"}],
                "slide_advances": [{"index": 0, "t_ms": 0}],
            },
        }]
        snips = {"s1": [
            {"id": "c1", "start_offset_ms": 0, "duration_ms": 1500,
             "transcript": "strong close",
             "storage_path": "s3://c1", "metrics": {"overall_score": 0.9}},
        ]}
        labels = {"s1": [{"snippet_id": "c1", "value": "challenge"}]}
        db = _FakeDB(sessions, snips, labels)
        if corrected is not None:
            db.get_coach_snippet_drafts = lambda sid: [
                {"snippet_id": "c1", "transcript_corrected": corrected},
            ]
        return db

    def test_corrected_transcript_wins(self):
        out = bp.build_best_presentation(
            "arc1", database=self._db(corrected="the corrected close"),
            coach_view=True,
        )
        self.assertEqual(out["slides"][0]["text"], "the corrected close")

    def test_no_correction_keeps_raw_verbatim(self):
        out = bp.build_best_presentation(
            "arc1", database=self._db(), coach_view=True)
        self.assertEqual(out["slides"][0]["text"], "strong close")

    def test_signature_changes_with_corrections(self):
        sessions = [{"id": "s1", "take_index": 1,
                     "results_published_at": None}]
        a = bp._bp_signature(sessions, {})
        b = bp._bp_signature(sessions, {"c1": "corrected"})
        c = bp._bp_signature(sessions, {"c1": "corrected v2"})
        self.assertNotEqual(a, b)
        self.assertNotEqual(b, c)


class SelectBestDecklessTests(unittest.TestCase):
    """Deckless section selection — same blended ranking, speech order."""

    def _cand(self, sid, text, offset, score=0.5, confidence=0.8):
        return {"snippet_id": sid, "transcript": text,
                "start_offset_ms": offset, "duration_ms": 1000,
                "machine_confidence": confidence,
                "activation": score, "slide_stickiness": None,
                "tag": None, "slide_index": None}

    def test_top_k_in_speech_order(self):
        out = bp.select_best_deckless([
            self._cand("a", "Late but strongest line.", 9000, score=0.9),
            self._cand("b", "Early good line.", 1000, score=0.7),
            self._cand("c", "Middling line here.", 5000, score=0.5),
        ], max_sections=2)
        # top-2 by score = a, b; ordered by offset = b (1000) then a (9000)
        self.assertEqual([c["snippet_id"] for c in out.values()], ["b", "a"])
        self.assertEqual(sorted(out), [0, 1])

    def test_dedupes_identical_text(self):
        out = bp.select_best_deckless([
            self._cand("a", "Same line.", 1000, score=0.9),
            self._cand("b", "same   LINE.", 2000, score=0.8),
            self._cand("c", "Different line.", 3000, score=0.1),
        ])
        self.assertEqual(len(out), 2)

    def test_empty_safe(self):
        self.assertEqual(bp.select_best_deckless([]), {})
        self.assertEqual(bp.select_best_deckless(None), {})
        self.assertEqual(bp.select_best_deckless(
            [self._cand("a", "   ", 0)]), {})


class DecklessBuildTests(unittest.TestCase):
    """Deckless end-to-end: sections compose, the coach corrects them in the
    same editor, the student sees nothing until every section is corrected."""

    def setUp(self):
        self._orig = bp._render_composition
        bp._render_composition = lambda picks, slides: None

    def tearDown(self):
        bp._render_composition = self._orig

    def _db(self, coach_edits=None):
        sessions = [{
            "id": "s1", "take_index": 1,
            "intake_context": {"topic": "My pitch"},  # NO slides — deckless
        }]
        snips = {"s1": [
            {"id": "c1", "start_offset_ms": 1000, "duration_ms": 1500,
             "transcript": "Early strong line.",
             "storage_path": "s3://c1", "metrics": {"overall_score": 0.9}},
            {"id": "c2", "start_offset_ms": 6000, "duration_ms": 1500,
             "transcript": "Later strong close.",
             "storage_path": "s3://c2", "metrics": {"overall_score": 0.8}},
        ]}
        labels = {"s1": [{"snippet_id": "c1", "value": "challenge"},
                         {"snippet_id": "c2", "value": "challenge"}]}
        return _FakeDB(sessions, snips, labels, coach_edits=coach_edits)

    def test_sections_compose_in_speech_order(self):
        out = bp.build_best_presentation(
            "arc1", database=self._db(), coach_view=True)
        texts = [s["text"] for s in out["slides"]]
        self.assertEqual(texts, ["Early strong line.", "Later strong close."])
        self.assertEqual([s["index"] for s in out["slides"]], [0, 1])

    def test_student_hidden_until_every_section_corrected(self):
        out = bp.build_best_presentation(
            "arc1", database=self._db(coach_edits={0: "fixed one"}))
        self.assertFalse(out["coach_finalized"])
        self.assertEqual([s["text"] for s in out["slides"]], ["", ""])

    def test_finalizes_when_all_sections_corrected(self):
        out = bp.build_best_presentation(
            "arc1", database=self._db(
                coach_edits={0: "fixed one", 1: "fixed two"}))
        self.assertTrue(out["coach_finalized"])
        self.assertEqual([s["text"] for s in out["slides"]],
                         ["fixed one", "fixed two"])


class CoachKeyPhrasesTests(unittest.TestCase):
    """Coach-corrected key phrases override the auto set; both hide with the
    text until coach_finalized."""

    def setUp(self):
        self._orig = bp._render_composition
        bp._render_composition = lambda picks, slides: None

    def tearDown(self):
        bp._render_composition = self._orig

    def _db(self, coach_edits=None, coach_kp=None):
        sis = {"already_strong": False,
               "upgrades": [{"original": "x", "upgrade": "auto phrase",
                             "reason": None, "kind": "upgrade"}],
               "rewrite_your_voice": "x", "rewrite_polished": "x",
               "why": None, "version": 1}
        sessions = [{
            "id": "s1", "take_index": 1,
            "intake_context": {
                "slides": [{"title": "Slide 1", "body": "p"}],
                "slide_advances": [{"index": 0, "t_ms": 0}],
            },
        }]
        snips = {"s1": [
            {"id": "c1", "start_offset_ms": 0, "duration_ms": 1500,
             "transcript": "strong close", "say_it_stronger": sis,
             "storage_path": "s3://c1", "metrics": {"overall_score": 0.9}},
        ]}
        labels = {"s1": [{"snippet_id": "c1", "value": "challenge"}]}
        db = _FakeDB(sessions, snips, labels, coach_edits=coach_edits)
        if coach_kp is not None:
            db.get_coach_best_presentation_key_phrases = lambda arc: dict(coach_kp)
        return db

    def test_auto_phrases_without_coach_set(self):
        out = bp.build_best_presentation(
            "arc1", database=self._db(), coach_view=True)
        self.assertEqual(out["slides"][0]["key_phrases"], ["auto phrase"])

    def test_coach_set_overrides_auto(self):
        out = bp.build_best_presentation(
            "arc1", database=self._db(coach_kp={0: ["coach phrase"]}),
            coach_view=True)
        self.assertEqual(out["slides"][0]["key_phrases"], ["coach phrase"])

    def test_phrases_hidden_with_text_pre_finalize(self):
        out = bp.build_best_presentation(
            "arc1", database=self._db(coach_kp={0: ["coach phrase"]}))
        self.assertFalse(out["coach_finalized"])
        self.assertEqual(out["slides"][0]["text"], "")
        self.assertEqual(out["slides"][0]["key_phrases"], [])


if __name__ == "__main__":
    unittest.main()
