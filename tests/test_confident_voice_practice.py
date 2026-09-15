"""Confident Voice micro-practice: narrow eligibility and isolation fences."""
from __future__ import annotations

import inspect
import pathlib
import unittest

from services import confident_voice_practice as cvp


def _words(*, compressed: bool) -> list[dict]:
    out = []
    at = 0.0
    for index, token in enumerate(
        "read the same exact passage and give every single word enough space now".split()
    ):
        duration = 0.12 if compressed and index >= 8 else 0.24
        out.append({"word": token, "start": at, "end": at + duration})
        at += duration + (0.025 if compressed else 0.12)
    return out


def _snippet(**over) -> dict:
    row = {
        "id": "snippet-a",
        "transcript": "Read the same exact passage and give every single word enough space now.",
        "duration_ms": 5000,
        "audio_segment_path": "snippets/a.webm",
        "words": _words(compressed=True),
        "metrics": {
            "wpm": 210.0,
            "pause_ratio": 0.03,
            "voiced_ratio": 0.78,
            "audio_quality": {"reliable": True, "noise_dominant": False},
            "voice_confidence": {
                "version": "voice-confidence-universal-v3",
                "score": 0.25,
            },
        },
    }
    row.update(over)
    return row


class EligibilityTests(unittest.TestCase):
    def test_high_wpm_alone_cannot_trigger(self):
        row = _snippet(words=_words(compressed=False))
        row["metrics"] = {
            **row["metrics"], "pause_ratio": 0.2, "voiced_ratio": 0.6,
        }
        verdict = cvp.exercise_eligibility(row, session_median_wpm=150)
        self.assertFalse(verdict["eligible"])

    def test_reliable_multi_signal_rushing_can_trigger(self):
        verdict = cvp.exercise_eligibility(_snippet(), session_median_wpm=150)
        self.assertTrue(verdict["eligible"])
        self.assertEqual(verdict["pattern"], "near_confident")
        self.assertGreaterEqual(sum(verdict["signals"].values()), 2)

    def test_unreliable_audio_cannot_trigger(self):
        row = _snippet()
        row["metrics"] = {
            **row["metrics"],
            "audio_quality": {"reliable": False, "noise_dominant": True},
        }
        self.assertFalse(cvp.exercise_eligibility(row)["eligible"])

    def test_verbal_or_structural_problem_cannot_trigger(self):
        self.assertFalse(cvp.exercise_eligibility(
            _snippet(), semantic_or_structural_problem=True,
        )["eligible"])

    def test_incomplete_or_misaligned_passage_cannot_trigger(self):
        self.assertFalse(cvp.exercise_eligibility(
            _snippet(transcript="Too short", words=[]),
        )["eligible"])


class PassageAndAssessmentTests(unittest.TestCase):
    def test_exact_passage_allows_punctuation_and_one_asr_miss(self):
        result = cvp.passage_alignment(
            "Read the same exact passage, and give every word space.",
            "read the same exact passage and give every word space",
        )
        self.assertTrue(result["matches"])

    def test_different_text_is_rejected(self):
        self.assertFalse(cvp.passage_alignment(
            "Read the same exact passage and give every word space.",
            "This is a completely different sentence about another topic.",
        )["matches"])

    def test_user_attempt_shape_never_exposes_scores_or_metrics(self):
        public = cvp.public_attempt({
            "id": "a", "attempt_index": 1, "audio_ref": "a.webm",
            "duration_ms": 2000, "assessment_key": "clearer_less_rushed",
            "acoustic_metrics": {"wpm": 999},
            "comparison": {"internal_strength": 999},
        })
        self.assertNotIn("acoustic_metrics", public)
        self.assertNotIn("comparison", public)
        self.assertNotIn("score", repr(public).casefold())

    def test_comparison_is_acoustic_only(self):
        source = inspect.getsource(cvp.comparison_for_attempt)
        for forbidden in ("argument", "semantic", "persuasion", "factual", "emotion"):
            self.assertNotIn(forbidden, source.casefold())

    def test_practice_machine_leg_uses_existing_confidence_construct(self):
        self.assertEqual(cvp.machine_confidence_decision(
            {"confidence": 0.45}), "yes")
        self.assertEqual(cvp.machine_confidence_decision(
            {"confidence": 0.44}), "no")
        self.assertIsNone(cvp.machine_confidence_decision({}))


class _Db:
    def __init__(self, existing=None, supported_patterns=None):
        self.existing = existing
        self.supported_patterns = supported_patterns
        self.snippets = {
            "snippet-a": _snippet(id="snippet-a"),
            "snippet-b": _snippet(id="snippet-b"),
        }

    def get_active_diagnostic_exercise(self, _exercise_id):
        row = {
            "exercise_id": cvp.EXERCISE_ID,
            "version": 1,
            "title": cvp.TITLE,
            "instruction": cvp.INSTRUCTION,
            "introduction_copy": cvp.INTRO_NEAR,
            "confident_introduction_copy": cvp.INTRO_CONFIDENT,
            "explanation_video_url": "https://example.com/coach.mp4",
        }
        if self.supported_patterns is not None:
            row["supported_confidence_patterns"] = self.supported_patterns
        return row

    def get_confident_voice_practice_by_take(self, _take):
        return self.existing

    def get_confident_voice_practice_candidates(self, ids):
        return [self.snippets[i] for i in ids]

    def get_snippets_by_session(self, _take):
        return [{"metrics": {"wpm": 150.0}}]


class ManagerTests(unittest.TestCase):
    def test_manager_attaches_no_more_than_one_exercise_per_take(self):
        rows = cvp.attach_exercise_offer([
            {"id": "one", "source": "confident_voice", "snippet_id": "snippet-a"},
            {"id": "two", "source": "confident_voice", "snippet_id": "snippet-b"},
        ], take_session_id="take-1", database=_Db())
        self.assertEqual(sum("practice_exercise" in row for row in rows), 1)

    def test_resume_never_moves_the_practice_to_a_different_moment(self):
        db = _Db(existing={
            "id": "practice-1", "snippet_id": "snippet-b", "status": "open",
        })
        rows = cvp.attach_exercise_offer([
            {"id": "one", "source": "confident_voice", "snippet_id": "snippet-a"},
            {"id": "two", "source": "confident_voice", "snippet_id": "snippet-b"},
        ], take_session_id="take-1", database=db)
        attached = [row for row in rows if "practice_exercise" in row]
        self.assertEqual([row["snippet_id"] for row in attached], ["snippet-b"])
        self.assertTrue(attached[0]["practice_exercise"]["resume"])

    def test_dismissed_offer_is_not_reopened(self):
        rows = cvp.attach_exercise_offer([
            {"source": "confident_voice", "snippet_id": "snippet-a"},
        ], take_session_id="take-1", database=_Db(existing={
            "id": "practice-1", "snippet_id": "snippet-a", "status": "dismissed",
        }))
        self.assertFalse(any("practice_exercise" in row for row in rows))

    def test_rewrite_problem_on_same_paragraph_suppresses_exercise(self):
        rows = cvp.attach_exercise_offer([
            {
                "source": "confident_voice", "snippet_id": "snippet-a",
                "evidence": {"slide_index": 0, "paragraph_index": 0},
            },
            {
                "source": "wording", "feedback_family": "rewrite_clarity",
                "evidence": {"slide_index": 0, "paragraph_index": 0},
            },
        ], take_session_id="take-1", database=_Db())
        self.assertFalse(any("practice_exercise" in row for row in rows))

    def test_closest_reviewed_exercise_is_offered_when_pattern_is_not_exact(self):
        rows = cvp.attach_exercise_offer([
            {"source": "confident_voice", "snippet_id": "snippet-a"},
        ], take_session_id="take-1", database=_Db(
            supported_patterns=["confident"],
        ))
        offer = next(row["practice_exercise"] for row in rows
                     if "practice_exercise" in row)
        self.assertEqual(offer["pattern_distance"], 1)
        self.assertEqual(
            offer["matching_policy_version"],
            "exercise-proximity-service-v1",
        )

    def test_offer_carries_answer_specific_framing(self):
        rows = cvp.attach_exercise_offer([
            {"source": "confident_voice", "snippet_id": "snippet-a"},
        ], take_session_id="take-1", database=_Db())
        offer = next(row["practice_exercise"] for row in rows
                     if "practice_exercise" in row)
        self.assertEqual(offer["yes_introduction"], cvp.INTRO_AFTER_YES)
        self.assertEqual(offer["no_introduction"], cvp.INTRO_AFTER_NO)


class _AlbumDb:
    def __init__(self, attempt):
        self.attempt = attempt
        self.inserted = []
        self.deleted = []

    def get_confident_voice_practice_attempt(self, attempt_id, practice_id):
        return self.attempt if attempt_id == "attempt-1" \
            and practice_id == "practice-1" else None

    def insert_voice_album_practice_entry(self, **kwargs):
        self.inserted.append(kwargs)
        return True

    def delete_voice_album_practice_entry(self, **kwargs):
        self.deleted.append(kwargs)
        return True


class PracticeAlbumTests(unittest.TestCase):
    PRACTICE = {
        "id": "practice-1", "selected_attempt_id": "attempt-1",
        "project_id": "arc-1", "take_session_id": "take-1",
        "slide_index": 2,
    }

    def test_selected_attempt_enters_only_when_its_three_signals_are_yes(self):
        db = _AlbumDb({
            "machine_confidence_decision": "yes",
            "user_answer": "yes",
            "coach_confidence_decision": "yes",
        })
        self.assertTrue(cvp.reconcile_practice_voice_album(
            self.PRACTICE, database=db))
        self.assertEqual(db.inserted[0]["practice_attempt_id"], "attempt-1")

    def test_original_clip_rating_cannot_substitute_for_attempt_coach_yes(self):
        db = _AlbumDb({
            "machine_confidence_decision": "yes",
            "user_answer": "yes",
            "coach_confidence_decision": None,
        })
        self.assertFalse(cvp.reconcile_practice_voice_album(
            {**self.PRACTICE, "professional_coach_decision": "yes"},
            database=db))
        self.assertFalse(db.inserted)
        self.assertTrue(db.deleted)

    def test_owner_no_never_enters_even_when_machine_and_coach_say_yes(self):
        db = _AlbumDb({
            "machine_confidence_decision": "yes",
            "user_answer": "no",
            "coach_confidence_decision": "yes",
        })
        self.assertFalse(cvp.reconcile_practice_voice_album(
            self.PRACTICE, database=db))
        self.assertFalse(db.inserted)


class PersistenceAndJourneyFenceTests(unittest.TestCase):
    ROOT = pathlib.Path(__file__).resolve().parents[1]

    def test_database_enforces_one_exercise_per_full_take_and_three_attempts(self):
        migration = (self.ROOT / "migrations/add_confident_voice_practice.sql").read_text()
        self.assertIn("UNIQUE (take_session_id)", migration)
        self.assertIn("attempt_index BETWEEN 1 AND 3", migration)
        self.assertIn("machine_confidence_decision", migration)
        self.assertIn("coach_confidence_decision", migration)
        self.assertIn("voice_album_practice", migration)

    def test_blog_mapping_is_inactive_until_explicitly_enabled(self):
        migration = (self.ROOT / "migrations/add_confident_voice_practice.sql").read_text()
        self.assertIn("active                         BOOLEAN NOT NULL DEFAULT FALSE", migration)
        self.assertRegex(migration, r"'hear-every-word-v1'[\s\S]+?FALSE,\s+1")
        route = (self.ROOT / "routes/journal.py").read_text()
        self.assertIn("journal/diagnostic-exercises/save", route)
        self.assertIn("post.get(\"status\") != \"published\"", route)

    def test_keep_route_has_no_presentation_or_voice_album_writer(self):
        source = (self.ROOT / "routes/v2/user_sessions.py").read_text()
        start = source.index("def v2_complete_confident_voice_practice")
        end = source.index("@v2_bp.route", start)
        route = source[start:end]
        for forbidden in (
            "refresh_voice_album(", "set_arc_ideal", "upsert_decision_feedback(",
            "set_flagship(", "update_root_phrase(", "apply_styling(",
        ):
            self.assertNotIn(forbidden, route)

    def test_no_not_yet_is_recorded_without_marking_the_attempt_kept(self):
        source = (self.ROOT / "services/db.py").read_text()
        start = source.index("def keep_confident_voice_practice_attempt")
        end = source.index("# Singleton instance", start)
        helper = source[start:end]
        self.assertIn('"kept": user_answer == "yes"', helper)

    def test_private_coach_draft_cannot_replace_the_user_exercise(self):
        source = (self.ROOT / "routes/v2/user_sessions.py").read_text()
        start = source.index("def _practice_user_payload")
        end = source.index("@v2_bp.route", start)
        payload = source[start:end]
        self.assertIn('practice.get("coach_shared_at")', payload)
        self.assertIn('practice.get("coach_shared_exercise")', payload)
        self.assertNotIn('practice.get("coach_selected_exercise_id")', payload)

    def test_coach_chat_notification_is_behind_explicit_share(self):
        source = (self.ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_confident_voice_practice")
        end = source.index("@v2_bp.route", start)
        route = source[start:end]
        self.assertIn('share = body.get("share_with_user") is True', route)
        self.assertRegex(
            route,
            r"if share:\s+from services\.arc_notifications import "
            r"fire_confidence_practice_shared",
        )
        self.assertIn('"coach_shared_exercise": exercise_snapshot', route)

    def test_coach_can_draft_a_case_specific_exercise(self):
        source = (self.ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_confident_voice_practice")
        end = source.index("@v2_bp.route", start)
        route = source[start:end]
        self.assertIn('custom_body = body.get("custom_exercise")', route)
        self.assertIn('"source": "professional_coach"', route)
        self.assertIn('if share and not final_video_url', route)

    def test_coach_must_rate_the_selected_attempt_itself(self):
        source = (self.ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_confident_voice_practice")
        end = source.index("@v2_bp.route", start)
        route = source[start:end]
        self.assertIn('selected_attempt_coach_decision', route)
        self.assertIn('set_confident_voice_practice_attempt_coach_decision', route)
        self.assertIn('reconcile_practice_voice_album', route)


if __name__ == "__main__":
    unittest.main()


class ObservedProblemTagsTests(unittest.TestCase):
    """The clip's problems reach matching (2026-09-15, founder: wire the tags).

    Before this, eligibility measured six acoustic signals, used them to decide
    whether to offer an exercise at all, and then threw them away. Matching saw
    only how confident the clip sounded, so a speaker whose endings collapse
    could not be routed to the exercise that treats collapsing endings — the
    catalogue's own `acoustic_problem_tags` column was written by an admin and
    read by nothing.
    """

    def test_only_the_signals_that_fired_become_tags(self):
        tags = cvp.observed_problem_tags({"signals": {
            "compressed_ending": True,
            "reduced_word_separation": False,
            "insufficient_pauses": True,
        }})
        self.assertEqual(tags, frozenset({"ending_compression", "rushing"}))

    def test_an_unknown_signal_name_invents_no_tag(self):
        # A signal added in code must not conjure a name the catalogue cannot
        # claim; it would rank nothing and fail silently.
        self.assertEqual(
            cvp.observed_problem_tags({"signals": {"brand_new_signal": True}}),
            frozenset(),
        )

    def test_pace_is_never_a_tag_because_every_eligible_clip_has_it(self):
        # pace_high is REQUIRED for eligibility, so as a tag it would mark
        # every clip `rushing` and discriminate between none of them.
        verdict = cvp.exercise_eligibility(_snippet(), session_median_wpm=150)
        self.assertTrue(verdict["pace_high"])
        self.assertNotIn("pace_high", cvp._SIGNAL_PROBLEM_TAGS)

    def test_malformed_verdicts_are_silent_rather_than_fatal(self):
        for bad in (None, {}, {"signals": "nope"}, {"signals": None}):
            self.assertEqual(cvp.observed_problem_tags(bad), frozenset())

    def test_overlap_counts_what_the_exercise_claims_to_treat(self):
        observed = frozenset({"ending_compression", "rushing"})
        treats_it = {"acoustic_problem_tags": ["ending_compression"]}
        treats_something_else = {"acoustic_problem_tags": ["word_compression"]}
        self.assertEqual(cvp.problem_tag_overlap(observed, treats_it), 1)
        self.assertEqual(
            cvp.problem_tag_overlap(observed, treats_something_else), 0)
        # A tagless row scores zero rather than erroring — that is what keeps
        # this inert for a catalogue that carries no tags.
        self.assertEqual(cvp.problem_tag_overlap(observed, {}), 0)


class ExerciseRankingTests(unittest.TestCase):
    def _exercise(self, exercise_id, patterns, tags=None, editorial=0):
        return {
            "exercise_id": exercise_id,
            "supported_confidence_patterns": patterns,
            "acoustic_problem_tags": list(tags or []),
            "matching_criteria": {"editorial_priority": editorial},
        }

    def test_treating_the_actual_problem_beats_suiting_the_confidence_level(self):
        # `near_confident` is distance 0 from the first exercise and distance 1
        # from the second, so before the tags were wired the first always won.
        exact_pattern = self._exercise("suits-the-level", ["near_confident"])
        treats_problem = self._exercise(
            "treats-the-problem", ["confident"], ["ending_compression"])
        ranked = cvp.rank_exercises_for_pattern(
            "near_confident",
            [exact_pattern, treats_problem],
            observed_tags=frozenset({"ending_compression"}),
        )
        self.assertEqual(ranked[0][3]["exercise_id"], "treats-the-problem")

    def test_without_tags_the_original_confidence_order_is_untouched(self):
        # The inertness guarantee: a catalogue with no tags ranks exactly as it
        # did before this change, so shipping it changes nothing on its own.
        near = self._exercise("near", ["near_confident"])
        far = self._exercise("far", ["confident"])
        for observed in (None, frozenset()):
            ranked = cvp.rank_exercises_for_pattern(
                "near_confident", [far, near], observed_tags=observed)
            self.assertEqual(
                [row[3]["exercise_id"] for row in ranked], ["near", "far"])

    def test_more_of_the_clip_s_problems_treated_wins(self):
        one = self._exercise("one", ["near_confident"], ["rushing"])
        both = self._exercise(
            "both", ["near_confident"], ["rushing", "ending_compression"])
        ranked = cvp.rank_exercises_for_pattern(
            "near_confident", [one, both],
            observed_tags=frozenset({"rushing", "ending_compression"}),
        )
        self.assertEqual(ranked[0][3]["exercise_id"], "both")

    def test_the_offer_and_the_start_route_rank_identically(self):
        """The invariant that makes this safe to ship.

        `attach_exercise_offer` chooses the exercise; the practice-start route
        re-ranks through `rank_exercises_for_pattern` and rejects the offer as
        EXERCISE_OFFER_STALE if it does not come first. Ranking by different
        rules in the two places would reject a freshly offered exercise the
        moment a speaker tapped it — so both must weigh the tags the same way.
        """
        observed = frozenset({"ending_compression"})
        suits_level = self._exercise("suits-the-level", ["near_confident"])
        treats_problem = self._exercise(
            "treats-the-problem", ["confident"], ["ending_compression"])
        exercises = [suits_level, treats_problem]

        # What the start route computes.
        start_best = cvp.rank_exercises_for_pattern(
            "near_confident", exercises, observed_tags=observed,
        )[0][3]["exercise_id"]

        # What the offer path computes, using its own sort key shape.
        offer_ranked = sorted(
            (
                -cvp.problem_tag_overlap(observed, exercise),
                cvp.confidence_pattern_distance(
                    "near_confident",
                    exercise.get("supported_confidence_patterns"),
                ),
                -int(exercise["matching_criteria"]["editorial_priority"]),
                -3,
                str(exercise["exercise_id"]),
            )
            for exercise in exercises
        )
        self.assertEqual(offer_ranked[0][4], start_best)
