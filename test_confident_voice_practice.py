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
                "version": "voice-confidence-v2",
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

    def test_active_exercise_must_support_the_detected_pattern(self):
        rows = cvp.attach_exercise_offer([
            {"source": "confident_voice", "snippet_id": "snippet-a"},
        ], take_session_id="take-1", database=_Db(
            supported_patterns=["confident"],
        ))
        self.assertFalse(any("practice_exercise" in row for row in rows))

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
    ROOT = pathlib.Path(__file__).resolve().parent

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
