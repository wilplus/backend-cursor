"""Confident Voice micro-practice: narrow eligibility and isolation fences."""
from __future__ import annotations

import hashlib
import importlib
import json
import inspect
import re
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

    def test_each_attempt_records_its_machine_leg(self):
        # Founder 2026-09-28: the attempt route wrote None here, so no
        # practice recording could ever reach the Voice Album (35g). It now
        # stores the machine leg from the attempt's own snapshot.
        route = (pathlib.Path(__file__).resolve().parents[1]
                 / "routes" / "v2" / "user_sessions.py").read_text()
        # Same composite and 0.45 cut-off that call the original clip
        # confident (machine_confidence_decision, tested above).
        self.assertIn('"machine_confidence_decision": machine_confidence_decision'
                      '(current_snapshot),', route)
        self.assertNotIn('"machine_confidence_decision": None,', route)


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
            # The seed row's claim (add_confident_voice_practice.sql). Without
            # tags an exercise is never offered (D1, 2026-09-28).
            "acoustic_problem_tags": [
                "rushing", "word_compression", "ending_compression"],
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
        # The routing number never reaches the speaker (AC-9, 2026-09-29).
        self.assertNotIn("pattern_distance", offer)
        # The bare version: whether this was a trial never reaches the
        # speaker's payload.
        self.assertEqual(
            offer["matching_policy_version"],
            "exercise-fit-tier-v1",
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


class DoneBeforeLabelTests(unittest.TestCase):
    """THE GREEN "DONE" LABEL (founder 2026-09-26, Q44 / Q45 A): the offer says
    when the owner already completed this exercise on an earlier Take."""

    def _offer(self, db):
        rows = cvp.attach_exercise_offer([
            {"id": "one", "source": "confident_voice", "snippet_id": "snippet-a"},
        ], take_session_id="take-1", database=db, owner_user_id="owner-1")
        return next(row["practice_exercise"] for row in rows
                    if "practice_exercise" in row)

    def test_done_before_when_completed_on_an_earlier_take(self):
        db = _Db()
        calls = []
        db.completed_exercise_before = (
            lambda owner, ex, take: calls.append((owner, ex, take)) or True)
        offer = self._offer(db)
        self.assertIs(offer["done_before"], True)
        self.assertEqual(calls[0][0], "owner-1")
        self.assertEqual(calls[0][2], "take-1")

    def test_new_exercise_is_not_done(self):
        db = _Db()
        db.completed_exercise_before = lambda owner, ex, take: False
        self.assertIs(self._offer(db)["done_before"], False)

    def test_a_failing_read_never_costs_the_offer(self):
        db = _Db()

        def boom(*_args):
            raise RuntimeError("down")
        db.completed_exercise_before = boom
        self.assertIs(self._offer(db)["done_before"], False)

    def test_a_flag_never_a_count(self):
        db = _Db()
        db.completed_exercise_before = lambda owner, ex, take: 3
        self.assertIs(self._offer(db)["done_before"], True)


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
        # The draft rule moved out of the route on 2026-09-16, when the
        # catalogue became dynamic and the route shrank to a thin caller. The
        # RULE is unchanged — an exercise cannot go live on an unpublished
        # post — so the fence follows it to where it now lives rather than
        # being dropped.
        catalogue = (
            self.ROOT / "services/diagnostic_exercise_catalogue.py"
        ).read_text()
        self.assertIn("post.get(\"status\") != \"published\"", catalogue)
        self.assertIn("publish the post before switching the exercise on",
                      catalogue)

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
        """Still drafted on the spot -- but FILED, not minted (founder
        2026-09-25). It used to be built inline with no error on it, which
        meant it could never route to anyone: matching compares an exercise's
        errors against the errors a detector found on a clip, and one naming
        none matches nothing, forever."""
        source = (self.ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_confident_voice_practice")
        end = source.index("@v2_bp.route", start)
        route = source[start:end]
        self.assertIn('custom_body = body.get("custom_exercise")', route)
        self.assertIn("file_coach_exercise(", route)
        # The route no longer decides what a valid exercise is; the catalogue
        # does, and its refusals reach the coach verbatim.
        self.assertIn("except CatalogueRefusal as refusal", route)
        self.assertNotIn('"source": "professional_coach"', route)
        self.assertIn('if share and not final_video_url', route)

    def test_a_drafted_exercise_must_name_an_error_it_treats(self):
        from services import diagnostic_exercise_catalogue as cat

        class _Db:
            def list_speaking_errors(self):
                return [{"error_id": "ending_compression", "status": "detected"}]

            def upsert_diagnostic_exercise(self, row):
                return row

        base = {
            "title": "Land the last word",
            "instruction": "Say the final word at full volume.",
            "explanation_video_url": "https://example.com/v.mp4",
        }
        with self.assertRaises(cat.CatalogueRefusal):
            cat.file_coach_exercise(_Db(), practice_id="p1", fields=base)

        # An error code cannot hear is refused with the sentence that explains
        # why, rather than saved as something that would route nothing.
        with self.assertRaises(cat.CatalogueRefusal) as ctx:
            cat.file_coach_exercise(
                _Db(), practice_id="p1",
                fields={**base, "acoustic_problem_tags": ["mumbling"]})
        self.assertEqual(ctx.exception.code, "TAG_NOT_DETECTED")

        row = cat.file_coach_exercise(
            _Db(), practice_id="p1",
            fields={**base, "acoustic_problem_tags": ["ending_compression"]})
        self.assertEqual(row["exercise_id"], "coach-custom-p1")
        self.assertEqual(row["acoustic_problem_tags"], ["ending_compression"])
        # Once per take is the library default, which is the budget already.
        self.assertEqual(row["matching_criteria"]["max_per_take"], 1)

    def test_a_main_target_must_be_one_of_the_exercise_s_own_tags(self):
        from services import diagnostic_exercise_catalogue as cat

        class _Db:
            def list_speaking_errors(self):
                return [{"error_id": e, "status": "detected"}
                        for e in ("ending_compression", "rushing")]

            def upsert_diagnostic_exercise(self, row):
                return row

        base = {
            "title": "Land the last word",
            "explanation_video_url": "https://example.com/v.mp4",
            "acoustic_problem_tags": ["ending_compression", "rushing"],
        }
        for bad in ("word_compression", 7):
            with self.assertRaises(cat.CatalogueRefusal):
                cat.file_coach_exercise(_Db(), practice_id="p1", fields={
                    **base, "matching_criteria": {"primary_problem_tag": bad}})
        row = cat.file_coach_exercise(_Db(), practice_id="p1", fields={
            **base,
            "matching_criteria": {"primary_problem_tag": "ending_compression"}})
        self.assertEqual(row["matching_criteria"]["primary_problem_tag"],
                         "ending_compression")

    def test_a_drafted_exercise_still_needs_its_video(self):
        """The library has always required one; this path used to treat it as
        optional, so a coach could file something with nothing to show."""
        from services import diagnostic_exercise_catalogue as cat

        class _Db:
            def list_speaking_errors(self):
                return [{"error_id": "ending_compression", "status": "detected"}]

            def upsert_diagnostic_exercise(self, row):
                return row

        with self.assertRaises(cat.CatalogueRefusal):
            cat.file_coach_exercise(_Db(), practice_id="p1", fields={
                "title": "Land the last word",
                "acoustic_problem_tags": ["ending_compression"],
            })

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

    def test_nothing_spotted_means_no_exercise(self):
        # D1 (founder 2026-09-28). This used to fall back to the confidence
        # order, so a clip with no spotted problem still got an exercise.
        near = self._exercise("near", ["near_confident"], ["rushing"])
        far = self._exercise("far", ["confident"], ["rushing"])
        for observed in (None, frozenset()):
            self.assertEqual(cvp.rank_exercises_for_pattern(
                "near_confident", [far, near], observed_tags=observed), [])

    def test_an_exercise_that_targets_nothing_that_fired_is_never_offered(self):
        tagless = self._exercise("tagless", ["near_confident"])
        elsewhere = self._exercise(
            "elsewhere", ["near_confident"], ["word_compression"])
        self.assertEqual(cvp.rank_exercises_for_pattern(
            "near_confident", [tagless, elsewhere],
            observed_tags=frozenset({"rushing"})), [])

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

        # What both offer lanes compute.
        _, offered = cvp.matched_exercises(
            "near_confident", exercises, observed_tags=observed)
        self.assertEqual(offered[0][1]["exercise_id"], start_best)


class SpeakingErrorLibraryTests(unittest.TestCase):
    """The library and the matcher must not drift apart (founder 2026-09-15).

    "we have the library of the errors so we can recognise them and we have the
    exercise matching algorithm and they should go hand in hand."

    These read the migration directly rather than a database, so drift is
    caught in the unit tier at the moment it is introduced.
    """

    @staticmethod
    def _migration() -> str:
        return (pathlib.Path(__file__).resolve().parents[1]
                / "migrations" / "add_speaking_error_library.sql").read_text()

    def _seeded(self) -> dict[str, str]:
        """Every seeded error id mapped to its status.

        Split on a `)` that OWNS its line: the definitions themselves contain
        `(pause_ratio < 0.08),` inline, so splitting on `),` anywhere cuts a
        row in half and reports its status as whatever precedes the threshold.
        """
        sql = self._migration()
        body = sql[sql.index("INSERT INTO public.speaking_error"):]
        out: dict[str, str] = {}
        for block in re.split(r"\n\),?\n", body):
            found = re.search(r"^\s*'([a-z0-9_]+)',\s*$", block, re.MULTILINE)
            if not found:
                continue
            out[found.group(1)] = (
                "detected" if "'detected'," in block else "observed"
            )
        return out

    def test_every_name_the_matcher_maps_exists_in_the_library(self):
        # The drift guard. A tag the code can produce but the library does not
        # define is a measured state with no written definition — the exact
        # defect the CONSTRUCT fence exists to prevent.
        mapped = {
            tag
            for tags in cvp._SIGNAL_PROBLEM_TAGS.values()
            for tag in tags
        }
        seeded = self._seeded()
        self.assertTrue(seeded, "no seeded errors parsed from the migration")
        missing = mapped - set(seeded)
        self.assertEqual(missing, set(), f"undefined in the library: {missing}")

    def test_every_name_the_matcher_maps_is_marked_detected(self):
        # `observed` means a human named it and no code can find it. A name the
        # matcher can produce is by definition detectable, so the two states
        # would contradict each other.
        seeded = self._seeded()
        for tags in cvp._SIGNAL_PROBLEM_TAGS.values():
            for tag in tags:
                self.assertEqual(seeded.get(tag), "detected", tag)

    def test_the_library_refuses_a_detected_row_with_no_detector(self):
        # Structural, not aspirational: the database rejects the claim, so
        # nobody has to remember the rule at review time.
        sql = self._migration()
        self.assertIn("speaking_error_detected_needs_detector", sql)
        self.assertIn("status <> 'detected' OR detector_ref IS NOT NULL", sql)

    def test_the_library_refuses_an_id_that_could_never_match(self):
        # Matching is string overlap: `word compression` would match nothing,
        # raise nothing and route nothing. Unrepresentable is the only safe
        # answer to a silent failure.
        self.assertIn("speaking_error_id_shape", self._migration())
        self.assertIn("'^[a-z][a-z0-9_]{1,62}$'", self._migration())

    def test_every_seeded_error_carries_a_definition_and_one_question(self):
        sql = self._migration()
        self.assertIn("definition    TEXT NOT NULL", sql)
        self.assertIn("asks          TEXT NOT NULL", sql)

    def test_the_migration_is_idempotent_and_rls_guarded(self):
        sql = self._migration()
        self.assertIn("CREATE TABLE IF NOT EXISTS public.speaking_error", sql)
        self.assertIn("ON CONFLICT (error_id) DO NOTHING", sql)
        self.assertIn("ENABLE ROW LEVEL SECURITY", sql)

    def test_it_is_registered_to_run(self):
        manifest = (pathlib.Path(__file__).resolve().parents[1]
                    / "migrations" / "manifest.txt").read_text()
        self.assertIn("add_speaking_error_library.sql", manifest)


class VocabularyFilterTests(unittest.TestCase):
    class _Db:
        def __init__(self, rows):
            self.rows = rows

        def list_speaking_errors(self):
            return self.rows

    def test_only_detected_entries_enter_the_vocabulary(self):
        database = self._Db([
            {"error_id": "ending_compression", "status": "detected"},
            {"error_id": "trailing_mumble", "status": "observed"},
        ])
        self.assertEqual(
            cvp.detected_problem_vocabulary(database),
            frozenset({"ending_compression"}),
        )

    def test_a_name_the_library_does_not_call_detectable_is_dropped(self):
        verdict = {"signals": {"compressed_ending": True,
                               "insufficient_pauses": True}}
        self.assertEqual(
            cvp.observed_problem_tags(
                verdict, vocabulary=frozenset({"ending_compression"})),
            frozenset({"ending_compression"}),
        )

    def test_an_unavailable_library_does_not_erase_every_tag(self):
        # The dangerous misreading: empty means "no library", never "nothing is
        # detectable". Filtering on empty would silently undo matching the
        # moment a read failed or a migration lagged.
        verdict = {"signals": {"compressed_ending": True}}
        for empty in (None, frozenset(), set(), []):
            self.assertEqual(
                cvp.observed_problem_tags(verdict, vocabulary=empty),
                frozenset({"ending_compression"}),
            )
        self.assertEqual(
            cvp.detected_problem_vocabulary(self._Db([])), frozenset())
        self.assertEqual(
            cvp.detected_problem_vocabulary(object()), frozenset())


class _CatalogueDb:
    """A catalogue and an error library, and nothing else."""

    def __init__(self, rows, detected=("rushing", "word_compression",
                                       "ending_compression")):
        self._rows = rows
        self._detected = detected

    def list_diagnostic_exercises(self):
        return [dict(row) for row in self._rows]

    def get_active_diagnostic_exercise(self, exercise_id):
        for row in self._rows:
            if (row["exercise_id"] == exercise_id and row.get("active", True)
                    and row.get("explanation_video_url")):
                return dict(row)
        return None

    def list_speaking_errors(self):
        return [{"error_id": e, "status": "detected"} for e in self._detected]


class CoachExerciseOrderTests(unittest.TestCase):
    """FOUNDER 2026-09-25: the coach sees every exercise, best match first."""

    def _exercise(self, exercise_id, patterns, tags=(), **over):
        row = {
            "exercise_id": exercise_id,
            "supported_confidence_patterns": list(patterns),
            "acoustic_problem_tags": list(tags),
            "matching_criteria": {"editorial_priority": 0},
            "explanation_video_url": f"https://cdn.example/{exercise_id}.mp4",
            "active": True,
        }
        row.update(over)
        return row

    def _practice(self, pattern="near_confident", **signals):
        return {
            "machine_assessment": {"pattern": pattern},
            "acoustic_evidence": {"signals": signals},
        }

    def _ids(self, rows):
        return [row["exercise_id"] for row in rows]

    def test_the_exercise_treating_the_clip_s_problem_comes_first(self):
        db = _CatalogueDb([
            self._exercise("a-suits-the-level", ["near_confident"]),
            self._exercise("b-treats-the-ending", ["confident"],
                           ["ending_compression"]),
        ])
        order = cvp.coach_exercise_order(
            self._practice(compressed_ending=True), db)
        self.assertEqual(self._ids(order)[0], "b-treats-the-ending")

    def test_the_top_is_what_the_speaker_s_matcher_would_pick(self):
        # Parity, not a second ranking: the head of the coach's list is the
        # head of rank_exercises_for_clip on the verdict the practice stored.
        rows = [
            self._exercise("a", ["confident"], ["rushing"]),
            self._exercise("b", ["near_confident"], ["word_compression"]),
            self._exercise("c", ["near_confident"],
                           ["word_compression", "ending_compression"]),
        ]
        db = _CatalogueDb(rows)
        practice = self._practice(
            compressed_ending=True, dense_articulation=True)
        speaker_best = cvp.rank_exercises_for_clip(
            cvp.stored_practice_verdict(practice), db)[0][3]["exercise_id"]
        self.assertEqual(
            self._ids(cvp.coach_exercise_order(practice, db))[0], speaker_best)
        self.assertEqual(speaker_best, "c")

    def test_an_exercise_the_matcher_cannot_place_stays_in_the_list_last(self):
        # The matcher drops it, which is right for an offer; a coach choosing
        # by hand must still see everything the library holds.
        db = _CatalogueDb([
            self._exercise("a-unplaceable", ["not_a_pattern"], ["rushing"]),
            self._exercise("b-placed", ["near_confident"], ["rushing"]),
        ])
        self.assertEqual(
            self._ids(cvp.coach_exercise_order(
                self._practice(insufficient_pauses=True), db)),
            ["b-placed", "a-unplaceable"])

    def test_nothing_unpublished_is_listed(self):
        db = _CatalogueDb([
            self._exercise("live", ["near_confident"]),
            self._exercise("no-video", ["near_confident"],
                           explanation_video_url=None),
            self._exercise("retired", ["near_confident"], active=False),
        ])
        self.assertEqual(
            self._ids(cvp.coach_exercise_order(self._practice(), db)),
            ["live"])

    def test_a_practice_without_a_stored_verdict_keeps_catalogue_order(self):
        db = _CatalogueDb([
            self._exercise("a", ["near_confident"]),
            self._exercise("b", ["confident"], ["rushing"]),
        ])
        for practice in ({}, None, {"machine_assessment": "junk"}):
            self.assertEqual(
                self._ids(cvp.coach_exercise_order(practice, db)), ["a", "b"])

    def test_the_catalogue_is_read_once(self):
        db = _CatalogueDb([self._exercise("a", ["near_confident"])])
        calls = []
        original = db.list_diagnostic_exercises
        db.list_diagnostic_exercises = lambda: calls.append(1) or original()
        cvp.coach_exercise_order(self._practice(), db)
        self.assertEqual(len(calls), 1)

    def test_the_coach_payload_uses_it_and_carries_no_rank(self):
        source = inspect.getsource(importlib.import_module("routes.v2.coach")
                                   ._coach_practice_payload)
        self.assertIn("coach_exercise_order(practice, db)", source)
        block = source[source.index("available_exercises = ["):
                       source.index("for active in coach_exercise_order")]
        for leaked in ("distance", "overlap", "rank", "score", "priority"):
            self.assertNotIn(leaked, block)

class ExerciseFitTests(unittest.TestCase):
    """Exact, trial, none (founder 2026-09-28: D1, D5, D5a, D6)."""

    def _exercise(self, exercise_id, tags, primary=None,
                  patterns=("near_confident",)):
        criteria = {"editorial_priority": 0}
        if primary is not None:
            criteria["primary_problem_tag"] = primary
        return {
            "exercise_id": exercise_id,
            "supported_confidence_patterns": list(patterns),
            "acoustic_problem_tags": list(tags),
            "matching_criteria": criteria,
        }

    def _rank(self, exercises, *fired):
        return cvp.matched_exercises(
            "near_confident", exercises, observed_tags=frozenset(fired))

    def test_undeclared_main_target_keeps_every_tag_a_main_target(self):
        legacy = self._exercise("legacy", ["rushing", "ending_compression"])
        self.assertEqual(
            cvp.exercise_targets(legacy),
            (frozenset({"rushing", "ending_compression"}), frozenset()))
        self.assertEqual(cvp.exercise_fit({"rushing"}, legacy),
                         (cvp.FIT_EXACT, 1))

    def test_declared_main_target_makes_the_rest_secondary(self):
        ex = self._exercise("land-the-ending",
                            ["ending_compression", "rushing"],
                            primary="ending_compression")
        self.assertEqual(cvp.exercise_fit({"ending_compression"}, ex),
                         (cvp.FIT_EXACT, 1))
        self.assertEqual(cvp.exercise_fit({"rushing"}, ex),
                         (cvp.FIT_TRIAL, 1))
        self.assertIsNone(cvp.exercise_fit({"word_compression"}, ex))

    def test_an_undone_main_target_promotes_nothing(self):
        # The teaching that added the main target was undone: the author
        # still said the rest were secondary, so they stay trials.
        ex = self._exercise("orphan", ["rushing"], primary="ending_compression")
        self.assertEqual(cvp.exercise_targets(ex),
                         (frozenset(), frozenset({"rushing"})))
        self.assertEqual(cvp.exercise_fit({"rushing"}, ex), (cvp.FIT_TRIAL, 1))

    def test_a_trial_is_offered_when_no_exact_fit_exists(self):
        trial = self._exercise("room-to-follow", ["word_compression", "rushing"],
                               primary="word_compression")
        fit, matched = self._rank([trial], "rushing")
        self.assertEqual(fit, cvp.FIT_TRIAL)
        self.assertEqual([m[1]["exercise_id"] for m in matched],
                         ["room-to-follow"])

    def test_a_trial_never_competes_with_an_exact_fit(self):
        # D6: not even in the 80/20 exploration slot, so it is not in the
        # pool at all.
        exact = self._exercise("exact", ["rushing"], primary="rushing")
        trial = self._exercise("trial", ["word_compression", "rushing"],
                               primary="word_compression")
        fit, matched = self._rank([trial, exact], "rushing")
        self.assertEqual(fit, cvp.FIT_EXACT)
        self.assertEqual([m[1]["exercise_id"] for m in matched], ["exact"])

    def test_one_main_hit_beats_any_number_of_secondary_hits(self):
        exact = self._exercise("exact", ["rushing"], primary="rushing")
        broad = self._exercise(
            "broad", ["word_compression", "rushing", "ending_compression"],
            primary="word_compression")
        fit, matched = self._rank([broad, exact],
                                  "rushing", "ending_compression")
        self.assertEqual(fit, cvp.FIT_EXACT)
        self.assertEqual(matched[0][1]["exercise_id"], "exact")

    def test_the_specialist_beats_the_generalist_on_the_same_problem(self):
        # Counting overlap alone ranked these equal, and the id broke the
        # tie; the one written for the problem that fired must win.
        generalist = self._exercise(
            "a-generalist", ["rushing", "word_compression", "ending_compression"])
        specialist = self._exercise("b-specialist", ["ending_compression"])
        _, matched = self._rank([generalist, specialist], "ending_compression")
        self.assertEqual([m[1]["exercise_id"] for m in matched],
                         ["b-specialist", "a-generalist"])

    def test_covering_more_of_what_fired_still_beats_specialising(self):
        generalist = self._exercise("a", ["rushing", "ending_compression"])
        specialist = self._exercise("b", ["ending_compression"])
        _, matched = self._rank([specialist, generalist],
                                "rushing", "ending_compression")
        self.assertEqual(matched[0][1]["exercise_id"], "a")

    def test_the_fit_rides_on_the_assignment_policy_and_back(self):
        for fit in (cvp.FIT_EXACT, cvp.FIT_TRIAL):
            self.assertEqual(
                cvp.fit_from_policy(cvp.matching_policy_for(fit)), fit)
        self.assertIsNone(cvp.fit_from_policy("exercise-proximity-service-v1"))
        self.assertEqual(cvp.matching_policy_for(None),
                         cvp.MATCHING_POLICY_VERSION)


class V3ExerciseFitTests(unittest.TestCase):
    """The V3 lane under D1/D5/D6, end to end through the 80/20 call."""

    class _Db(_Db):
        def __init__(self, rows, signals):
            super().__init__()
            self._rows = rows
            self.snippets["snippet-a"] = _snippet(id="snippet-a")
            self._signals = signals
            self.assigned = []

        def list_diagnostic_exercises(self):
            return [{"exercise_id": r["exercise_id"]} for r in self._rows]

        def get_active_diagnostic_exercise(self, exercise_id):
            return next((dict(r) for r in self._rows
                         if r["exercise_id"] == exercise_id), None)

        def list_speaking_errors(self):
            return [{"error_id": e, "status": "detected"} for e in
                    ("rushing", "word_compression", "ending_compression")]

        def assign_confident_voice_exercise(self, **kwargs):
            self.assigned.append(kwargs)
            return {"selected_exercise_id": kwargs["candidates"][0]["exercise_id"]}

        def completed_exercise_before(self, *_args):
            return False

    def _row(self, exercise_id, tags, primary=None):
        criteria = {} if primary is None else {"primary_problem_tag": primary}
        return {"exercise_id": exercise_id, "version": 1, "title": exercise_id,
                "instruction": "", "introduction_copy": "",
                "explanation_video_url": "https://cdn.example/x.mp4",
                "acoustic_problem_tags": tags, "matching_criteria": criteria,
                "supported_confidence_patterns": [
                    "low_confidence_rushing_dominant", "near_confident",
                    "confident"]}

    def _offer(self, db, fired):
        target = {"source": "confident_voice", "bookmark_tier": "exercise",
                  "snippet_id": "snippet-a"}
        # Read weak: the library video is for a clip the machine reads weak
        # (the follow-up matrix, founder 2026-09-29).
        verdict = {"eligible": True, "pattern": "low_confidence_rushing_dominant",
                   "priority": 1, "signals": fired, "snapshot": {}}
        original = cvp.exercise_eligibility
        cvp.exercise_eligibility = lambda *_a, **_k: verdict
        try:
            rows = cvp.attach_v3_exercise_offer(
                [target], take_session_id="take-1", owner_user_id="owner-1",
                database=db, ground=lambda _row: {"slide_index": 0})
        finally:
            cvp.exercise_eligibility = original
        return rows[0].get("practice_exercise")

    def test_nothing_spotted_serves_no_exercise(self):
        db = self._Db([self._row("any", ["rushing"])], {})
        self.assertIsNone(self._offer(db, {}))
        self.assertEqual(db.assigned, [])

    def test_a_trial_is_frozen_as_a_trial_and_the_speaker_never_sees_it(self):
        db = self._Db([self._row("room", ["word_compression", "rushing"],
                                 primary="word_compression")], {})
        offer = self._offer(db, {"insufficient_pauses": True})
        self.assertEqual(offer["exercise_id"], "room")
        self.assertEqual(db.assigned[0]["matching_policy_version"],
                         "exercise-fit-tier-v1:trial")
        self.assertNotIn("trial", repr(offer))

    def test_an_exact_fit_is_frozen_as_exact(self):
        db = self._Db([self._row("exact", ["rushing"], primary="rushing"),
                       self._row("trial", ["word_compression", "rushing"],
                                 primary="word_compression")], {})
        offer = self._offer(db, {"insufficient_pauses": True})
        self.assertEqual(offer["exercise_id"], "exact")
        self.assertEqual(db.assigned[0]["matching_policy_version"],
                         "exercise-fit-tier-v1:exact")
        self.assertEqual([c["exercise_id"] for c in db.assigned[0]["candidates"]],
                         ["exact"])


class MatchTraceTests(unittest.TestCase):
    """Why an exercise was chosen, frozen with the draw (step 2, 2026-09-28)."""

    _Db = V3ExerciseFitTests._Db
    _row = V3ExerciseFitTests._row
    _offer = V3ExerciseFitTests._offer

    def _catalogue(self):
        return [
            self._row("exact", ["rushing"], primary="rushing"),
            self._row("trial", ["word_compression", "rushing"],
                      primary="word_compression"),
            self._row("elsewhere", ["ending_compression"]),
        ]

    def _trace(self):
        db = self._Db(self._catalogue(), {})
        offer = self._offer(db, {"insufficient_pauses": True})
        return offer, db.assigned[0]

    def test_every_catalogue_exercise_is_accounted_for_with_a_reason(self):
        _, call = self._trace()
        by_id = {c["exercise_id"]: c for c in call["trace"]["candidates"]}
        self.assertEqual(set(by_id), {"exact", "trial", "elsewhere"})
        self.assertEqual((by_id["exact"]["outcome"], by_id["exact"]["rank"]),
                         ("ranked", 1))
        self.assertEqual(by_id["trial"]["reason"], "lower_fit_than_pool")
        self.assertEqual(by_id["elsewhere"]["reason"],
                         "targets_nothing_that_fired")

    def test_the_ranked_candidates_are_exactly_the_pool_drawn_from(self):
        # The database refuses a trace that disagrees; this is the same rule.
        _, call = self._trace()
        ranked = sorted((c for c in call["trace"]["candidates"]
                         if c["outcome"] == "ranked"), key=lambda c: c["rank"])
        self.assertEqual([c["exercise_id"] for c in ranked],
                         [c["exercise_id"] for c in call["candidates"]])

    def test_the_trace_names_what_fired_and_the_rules_it_was_measured_by(self):
        _, call = self._trace()
        trace = call["trace"]
        self.assertEqual(trace["trace_schema"], cvp.MATCH_TRACE_SCHEMA)
        self.assertEqual(trace["observed_tags"], ["rushing"])
        self.assertTrue(trace["signals"]["insufficient_pauses"])
        self.assertEqual(trace["signal_rules_version"], cvp.SIGNAL_RULES_VERSION)
        self.assertEqual(trace["fit"], cvp.FIT_EXACT)
        self.assertEqual(trace["matching_policy_version"],
                         call["matching_policy_version"])
        self.assertEqual(trace["clip"]["snippet_id"], "snippet-a")
        self.assertEqual(trace["clip"]["take_session_id"], "take-1")
        self.assertRegex(trace["catalogue_sha256"], r"^[0-9a-f]{64}$")

    def test_no_transcript_text_is_copied_into_the_trace(self):
        db = self._Db(self._catalogue(), {})
        passage = db.snippets["snippet-a"]["transcript"]
        self._offer(db, {"insufficient_pauses": True})
        self.assertNotIn(passage, json.dumps(db.assigned[0]["trace"]))

    def test_the_trace_never_reaches_the_speaker(self):
        offer, _ = self._trace()
        text = repr(offer)
        for internal in ("trace", "candidates", "observed_tags", "signals"):
            self.assertNotIn(internal, text)

    def test_the_trace_is_valid_json_even_with_a_broken_measurement(self):
        trace = cvp.build_match_trace(
            lane="v3_exercise_block",
            verdict={"pattern": "near_confident",
                     "signals": {"insufficient_pauses": True},
                     "snapshot": {"wpm": float("nan")}},
            vocabulary=frozenset({"rushing"}), exercises=[], ranked=[],
            fit=None, snippet={}, take_session_id="t", snippet_id="s")
        self.assertIsNone(trace["features"]["wpm"])
        json.dumps(trace, allow_nan=False)

    def test_the_signal_rules_are_versioned(self):
        """Changing a threshold or the signal map changes what every future
        trace means. Bump SIGNAL_RULES_VERSION, then update this fingerprint."""
        source = (inspect.getsource(cvp.exercise_eligibility)
                  + inspect.getsource(cvp.clip_signals)
                  + json.dumps(cvp._SIGNAL_PROBLEM_TAGS, sort_keys=True))
        self.assertEqual(
            (cvp.SIGNAL_RULES_VERSION,
             hashlib.sha256(source.encode()).hexdigest()),
            ("cv-exercise-signals-v1",
             "cac03cd2657bcccbd7f628167dee086d522d5202f688786349e2b9d15d431cc9"))


class AssignmentWrapperTests(unittest.TestCase):
    """services/db.py: v2 with a trace, v1 only while 0384 is not applied."""

    class _Client:
        def __init__(self, v2_error=None):
            self.v2_error = v2_error
            self.calls = []

        def rpc(self, name, params):
            client = self

            class Call:
                def execute(self_inner):
                    client.calls.append((name, params))
                    if name.endswith("_v2") and client.v2_error:
                        raise client.v2_error
                    return type("R", (), {"data": [{"id": "asg"}]})()
            return Call()

    def _db(self, client):
        from services.db import DatabaseService
        db = object.__new__(DatabaseService)
        db.client = client
        return db

    def _assign(self, db, trace):
        return db.assign_confident_voice_exercise(
            owner_user_id="o", take_session_id="t", snippet_id="s",
            lane="v3_exercise_block", matching_policy_version="p",
            candidates=[{"exercise_id": "a", "version": 1}], trace=trace)

    def test_a_trace_goes_with_the_draw(self):
        client = self._Client()
        self._assign(self._db(client), {"trace_schema": "x"})
        self.assertEqual([c[0] for c in client.calls],
                         ["assign_confident_voice_exercise_v2"])
        self.assertEqual(client.calls[0][1]["p_trace"], {"trace_schema": "x"})

    def test_before_the_migration_the_draw_still_happens(self):
        client = self._Client(RuntimeError("PGRST202 function not found"))
        self._assign(self._db(client), {"trace_schema": "x"})
        self.assertEqual([c[0] for c in client.calls],
                         ["assign_confident_voice_exercise_v2",
                          "assign_confident_voice_exercise_v1"])

    def test_a_refused_trace_is_not_silently_dropped(self):
        client = self._Client(RuntimeError(
            "CV_EXERCISE_MATCH_TRACE_DISAGREES_WITH_POOL"))
        with self.assertRaises(RuntimeError):
            self._assign(self._db(client), {"trace_schema": "x"})
        self.assertEqual(len(client.calls), 1)

    def test_without_a_trace_nothing_changes(self):
        client = self._Client()
        self._assign(self._db(client), None)
        self.assertEqual([c[0] for c in client.calls],
                         ["assign_confident_voice_exercise_v1"])
