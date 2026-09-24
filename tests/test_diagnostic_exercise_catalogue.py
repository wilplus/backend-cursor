"""A catalogue of more than one — and tags that mean something.

Founder 2026-09-16: "I will add the exercises… this would need to be dynamic."

Until now the route refused any exercise_id but `hear-every-word-v1` by name,
and the CMS hardcoded acoustic_problem_tags to all three vocabulary names. A
second exercise was unrepresentable; had one existed, both would have claimed
every problem and matching would have had nothing to separate them by.

WHAT THIS PINS DOWN:
  * any well-shaped id is accepted, so a catalogue can actually grow;
  * a tag must name an error the library calls `detected`. An exercise tagged
    with a merely `observed` error would match no recording, raise nothing and
    route nothing — a silent no-op sitting in the catalogue looking healthy;
  * an unavailable library SKIPS the tag check rather than failing it, because
    empty means "no library", not "nothing is detectable" — reading it the
    other way would refuse every exercise;
  * the post is OPTIONAL since 2026-09-23 (migration 0353) — an exercise goes
    live on its video and instruction alone — but a post that IS attached must
    still be published before the exercise switches on;
  * the avatar tick cannot be set without a setup label, because a tick that
    cannot say two clips MATCH does not do the job it was added for.

Run: python3 -m unittest tests.test_diagnostic_exercise_catalogue
"""
from __future__ import annotations

import unittest

from services.diagnostic_exercise_catalogue import (
    CatalogueRefusal,
    EXERCISE_ID_SHAPE,
    save_exercise,
)


GOOD = {
    "exercise_id": "land-the-ending-v1",
    "title": "Land the ending",
    "instruction": "Give the last three words the weight of the first three.",
    "introduction_copy": "Your endings are dropping away.",
    "explanation_video_url": "https://cdn.example.com/land-the-ending.mp4",
    "acoustic_problem_tags": ["ending_compression"],
    "journal_post_id": "post-1",
    "active": False,
}

LIBRARY = [
    {"error_id": "rushing", "status": "detected"},
    {"error_id": "word_compression", "status": "detected"},
    {"error_id": "ending_compression", "status": "detected"},
    {"error_id": "trailing_mumble", "status": "observed"},
]


class _Db:
    def __init__(self, library=LIBRARY, post_status="published",
                 post_exists=True):
        self.library = library
        self.post_status = post_status
        self.post_exists = post_exists
        self.saved: list[dict] = []

    def list_speaking_errors(self, active_only: bool = True):
        return list(self.library)

    def get_journal_post_by_id(self, post_id: str):
        if not self.post_exists:
            return None
        return {"id": post_id, "status": self.post_status}

    def upsert_diagnostic_exercise(self, row: dict):
        self.saved.append(row)
        return dict(row)


class CatalogueTests(unittest.TestCase):
    def save(self, db, **over):
        return save_exercise(db, {**GOOD, **over})

    # ── the catalogue can grow ───────────────────────────────────────────

    def test_an_exercise_that_is_not_hear_every_word_is_accepted(self):
        # The whole point. Until today the route refused this by name.
        db = _Db()
        saved = self.save(db)
        self.assertEqual(saved["exercise_id"], "land-the-ending-v1")
        self.assertEqual(db.saved[0]["acoustic_problem_tags"],
                         ["ending_compression"])

    def test_each_exercise_keeps_its_own_tags(self):
        # If every exercise claimed everything, tag overlap would score them
        # identically and the ranking would choose nothing.
        db = _Db()
        self.save(db)
        self.save(db, exercise_id="slow-down-v1",
                  acoustic_problem_tags=["rushing", "word_compression"])
        self.assertEqual([row["acoustic_problem_tags"] for row in db.saved],
                         [["ending_compression"], ["rushing", "word_compression"]])

    def test_the_id_shape_is_the_one_already_in_use(self):
        self.assertTrue(EXERCISE_ID_SHAPE.match("hear-every-word-v1"))
        for bad in ("Land The Ending", "land the ending", "", "9lives", "-x"):
            self.assertIsNone(EXERCISE_ID_SHAPE.match(bad), bad)
            with self.assertRaises(CatalogueRefusal):
                self.save(_Db(), exercise_id=bad)

    # ── tags must mean something ─────────────────────────────────────────

    def test_a_tag_the_library_cannot_detect_is_refused(self):
        # `trailing_mumble` is named but has no detector. Tagging it would
        # match nothing, raise nothing, and route nothing.
        db = _Db()
        with self.assertRaises(CatalogueRefusal) as caught:
            self.save(db, acoustic_problem_tags=["trailing_mumble"])
        self.assertEqual(caught.exception.code, "TAG_NOT_DETECTED")
        self.assertIn("trailing_mumble", caught.exception.message)
        self.assertEqual(db.saved, [])

    def test_an_invented_tag_is_refused(self):
        with self.assertRaises(CatalogueRefusal):
            self.save(_Db(), acoustic_problem_tags=["mumbling"])

    def test_an_unavailable_library_skips_the_check_rather_than_failing(self):
        # Empty means "no library" — a pending migration or a failed read.
        # Refusing every exercise on that basis would be the worse reading.
        db = _Db(library=[])
        saved = self.save(db, acoustic_problem_tags=["anything_at_all"])
        self.assertEqual(saved["acoustic_problem_tags"], ["anything_at_all"])

    def test_tags_cannot_be_empty(self):
        for empty in ([], None, "rushing"):
            with self.assertRaises(CatalogueRefusal):
                self.save(_Db(), acoustic_problem_tags=empty)

    # ── the post: optional since 2026-09-23, migration 0353 ──────────────

    def test_an_exercise_no_longer_needs_a_post(self):
        """REVERSED 2026-09-23 (founder). This asserted that an exercise with
        no post is refused — the coupling kept on 2026-09-16, when the post WAS
        the explanation a learner read. The founder's decision is that the
        video and the one-line instruction stand on their own."""
        saved = self.save(_Db(), journal_post_id="")
        self.assertIsNone(saved["journal_post_id"])

    def test_and_it_can_go_live_without_one(self):
        # The whole point of the change: not "saved but never offered".
        db = _Db()
        self.assertTrue(self.save(db, journal_post_id="", active=True)["active"])

    def test_a_video_is_still_required_when_the_post_is_gone(self):
        # What the relaxed rule did NOT relax. An exercise with nothing to show
        # is not an exercise, and it is now the only asset standing.
        with self.assertRaises(CatalogueRefusal):
            self.save(_Db(), journal_post_id="", explanation_video_url="")

    def test_a_missing_post_is_a_404(self):
        with self.assertRaises(CatalogueRefusal) as caught:
            self.save(_Db(post_exists=False))
        self.assertEqual(caught.exception.status, 404)

    def test_it_cannot_go_live_on_a_draft(self):
        db = _Db(post_status="draft")
        with self.assertRaises(CatalogueRefusal) as caught:
            self.save(db, active=True)
        self.assertIn("publish the post", caught.exception.message)
        self.assertEqual(db.saved, [])

    def test_it_can_go_live_on_a_published_post(self):
        db = _Db(post_status="published")
        self.assertTrue(self.save(db, active=True)["active"])

    # ── the rest ─────────────────────────────────────────────────────────

    def test_a_video_is_required_and_must_be_a_real_address(self):
        for bad in ("", "not-a-url", "ftp://x/y", "   "):
            with self.assertRaises(CatalogueRefusal):
                self.save(_Db(), explanation_video_url=bad)

    def test_a_name_is_required(self):
        # The one piece of text that still blocks a save. Without it the
        # catalogue has a row nothing can refer to.
        with self.assertRaises(CatalogueRefusal):
            self.save(_Db(), title="  ")

    def test_the_words_are_optional(self):
        """Founder 2026-09-24, on the CMS lane's "The words" step: "that is
        not obligatory!"

        A video is required and always was, so what this allows is an exercise
        that DEMONSTRATES rather than describes — the shape the speaker's
        screen already takes, with the coach's recording first and the words
        underneath. Blank is stored as "" rather than NULL, so a later save
        that fills them in is an ordinary update."""
        for key in ("instruction", "introduction_copy"):
            saved = self.save(_Db(), **{key: "  "})
            self.assertEqual(saved[key], "")

    def test_confidence_patterns_default_to_all_three(self):
        saved = self.save(_Db())
        self.assertEqual(len(saved["supported_confidence_patterns"]), 3)

    def test_an_unknown_confidence_pattern_is_refused(self):
        with self.assertRaises(CatalogueRefusal):
            self.save(_Db(), supported_confidence_patterns=["very_confident"])

    def test_matching_criteria_and_exclusions_get_working_defaults(self):
        # The CMS should not have to know these exist to save an exercise.
        saved = self.save(_Db())
        self.assertTrue(saved["matching_criteria"]["requires_multiple_acoustic_signals"])
        self.assertTrue(saved["exclusions"]["exclude_noise"])

    def test_active_must_be_stated(self):
        for bad in (None, "yes", 1):
            with self.assertRaises(CatalogueRefusal):
                self.save(_Db(), active=bad)

    def test_junk_body_is_refused_not_crashed(self):
        for junk in (None, [], "x", 3):
            with self.assertRaises(CatalogueRefusal):
                save_exercise(_Db(), junk)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


class TheAvatarTick(unittest.TestCase):
    """Founder 2026-09-23. A coach marking a recording usable for a future
    avatar is recording something PERISHABLE — only the person in the room
    knows whether the shirt, angle and light matched, and no one can recover it
    from the file later. Nothing reads these fields yet, by decision."""

    def save(self, db, **over):
        return save_exercise(db, {**GOOD, **over})

    def test_unticked_by_default(self):
        saved = self.save(_Db())
        self.assertIs(saved["avatar_training_eligible"], False)
        self.assertIsNone(saved["avatar_setup_label"])

    def test_the_tick_needs_a_setup_label(self):
        # THE REASON THE FIELD EXISTS. A bare yes says this clip was shot
        # carefully; it cannot say two clips match each other, and matching is
        # the entire requirement of a training set.
        with self.assertRaises(CatalogueRefusal) as caught:
            self.save(_Db(), avatar_training_eligible=True)
        self.assertIn("setup", caught.exception.message)

    def test_a_blank_label_is_not_a_label(self):
        for blank in ("", "   ", "\t"):
            with self.assertRaises(CatalogueRefusal):
                self.save(_Db(), avatar_training_eligible=True,
                          avatar_setup_label=blank)

    def test_a_ticked_exercise_keeps_its_label(self):
        saved = self.save(_Db(), avatar_training_eligible=True,
                          avatar_setup_label="  desk-white-shirt-sept  ")
        self.assertIs(saved["avatar_training_eligible"], True)
        self.assertEqual(saved["avatar_setup_label"], "desk-white-shirt-sept")

    def test_unticking_keeps_the_label_rather_than_dropping_it(self):
        # An author who unticks and reticks should not retype it.
        saved = self.save(_Db(), avatar_training_eligible=False,
                          avatar_setup_label="desk-white-shirt-sept")
        self.assertIs(saved["avatar_training_eligible"], False)
        self.assertEqual(saved["avatar_setup_label"], "desk-white-shirt-sept")

    def test_the_tick_must_be_a_decision_not_a_number(self):
        # Same reason `active` is isinstance-checked: 1 == True in Python, so a
        # membership test would switch this on for a caller who sent a count.
        for junk in (1, 0, "yes", None if False else "true"):
            with self.assertRaises(CatalogueRefusal):
                self.save(_Db(), avatar_training_eligible=junk,
                          avatar_setup_label="desk-white-shirt-sept")

    def test_an_absurd_label_is_refused(self):
        with self.assertRaises(CatalogueRefusal):
            self.save(_Db(), avatar_training_eligible=True,
                      avatar_setup_label="x" * 200)

    def test_the_tick_is_independent_of_everything_else(self):
        # It rides with an exercise that has no post and is live, which is the
        # combination the founder actually described.
        saved = self.save(_Db(), journal_post_id="", active=True,
                          avatar_training_eligible=True,
                          avatar_setup_label="desk-white-shirt-sept")
        self.assertIsNone(saved["journal_post_id"])
        self.assertTrue(saved["active"])
        self.assertTrue(saved["avatar_training_eligible"])
