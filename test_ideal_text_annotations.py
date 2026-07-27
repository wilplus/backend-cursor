"""willab — per-sentence ideal-text correction capture (founder 2026-07-27,
learning-pipeline item 3). services/ideal_text_annotations.py.

WHAT THIS PINS DOWN:
  * sentence splitting that survives the block's real shape — paragraphs,
    ellipses, closing quotes;
  * marker honesty: a marker-only coach edit (bolding, moment anchors,
    orange accents) reads as NO text change, because both sides are stripped
    identically — the corpus must never learn "add ** around words";
  * run-level pairing: a coach merging two sentences into one emits ONE pair
    (the merge is the lesson), never misaligned 1:1 forcing;
  * the emission contract — changed pairs as ideal_text_sentence rows, an
    untouched verify as ONE approved_as_is block row, an EMPTY machine draft
    as NOTHING (diffing against "" would brand the whole block coach-written);
  * best-effort: a db failure returns 0 and never raises (LIVE LOOP).

Run: python3 -m unittest test_ideal_text_annotations
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


class SplitSentencesTests(unittest.TestCase):

    def test_basic_split(self):
        from services.ideal_text_annotations import split_sentences
        self.assertEqual(
            split_sentences("One here. Two here! Three here?"),
            ["One here.", "Two here!", "Three here?"])

    def test_ellipsis_is_a_terminal(self):
        from services.ideal_text_annotations import split_sentences
        self.assertEqual(split_sentences("It faded… Then it came back."),
                         ["It faded…", "Then it came back."])

    def test_terminal_inside_quote_splits_after_the_quote(self):
        from services.ideal_text_annotations import split_sentences
        out = split_sentences('He said "go." Then he left.')
        self.assertEqual(out, ['He said "go."', "Then he left."])

    def test_paragraphs_are_hard_boundaries(self):
        from services.ideal_text_annotations import split_sentences
        out = split_sentences("No terminal here\n\nBut this ends. And more.")
        self.assertEqual(out, ["No terminal here", "But this ends.",
                               "And more."])

    def test_empty_and_junk(self):
        from services.ideal_text_annotations import split_sentences
        self.assertEqual(split_sentences(""), [])
        self.assertEqual(split_sentences(None), [])
        self.assertEqual(split_sentences("   \n\n  "), [])


class StripForDiffTests(unittest.TestCase):

    def test_rich_markers_removed(self):
        from services.ideal_text_annotations import strip_for_diff
        self.assertEqual(
            strip_for_diff("A **bold** and __under__ and {{orange:hot}} word."),
            "A bold and under and hot word.")

    def test_moment_wrappers_removed_inner_kept(self):
        from services.ideal_text_annotations import strip_for_diff
        text = ("Start [[moment:12345678-aaaa-bbbb-cccc-121212121212|"
                "87654321-aaaa-bbbb-cccc-212121212121]]the key line"
                "[[/moment]] end.")
        self.assertEqual(strip_for_diff(text), "Start the key line end.")

    def test_italic_and_urls_untouched(self):
        """// collides with URLs (sanitize_markers documents this) — the
        stripper must never mangle https://."""
        from services.ideal_text_annotations import strip_for_diff
        self.assertEqual(strip_for_diff("See https://x.com //really//."),
                         "See https://x.com //really//.")

    def test_non_string(self):
        from services.ideal_text_annotations import strip_for_diff
        self.assertEqual(strip_for_diff(None), "")
        self.assertEqual(strip_for_diff(42), "")


class SentencePairsTests(unittest.TestCase):

    def test_identical_yields_nothing(self):
        from services.ideal_text_annotations import sentence_pairs
        self.assertEqual(
            sentence_pairs("A line here. Another one.",
                           "A line here. Another one."), [])

    def test_case_and_whitespace_only_yields_nothing(self):
        from services.ideal_text_annotations import sentence_pairs
        self.assertEqual(
            sentence_pairs("A line here.  Another one.",
                           "a LINE here. another one."), [])

    def test_marker_only_edit_yields_nothing(self):
        """The coach bolded a phrase and wrapped a moment — no wording
        change, so no pair. This is the honesty invariant."""
        from services.ideal_text_annotations import sentence_pairs
        draft = "The key phrase lands here. And this follows."
        final = ("The **key phrase** lands here. "
                 "[[moment:12345678-aaaa-bbbb-cccc-121212121212|"
                 "87654321-aaaa-bbbb-cccc-212121212121]]And this follows."
                 "[[/moment]]")
        self.assertEqual(sentence_pairs(draft, final), [])

    def test_single_replacement(self):
        from services.ideal_text_annotations import sentence_pairs
        pairs = sentence_pairs(
            "Keep this one. Fix this sentence. Keep that one.",
            "Keep this one. This sentence is fixed. Keep that one.")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["op"], "replace")
        self.assertEqual(pairs[0]["draft"], "Fix this sentence.")
        self.assertEqual(pairs[0]["final"], "This sentence is fixed.")

    def test_insert_and_delete(self):
        from services.ideal_text_annotations import sentence_pairs
        ins = sentence_pairs("First. Last.", "First. Added middle. Last.")
        self.assertEqual([p["op"] for p in ins], ["insert"])
        self.assertEqual(ins[0]["draft"], "")
        self.assertEqual(ins[0]["final"], "Added middle.")
        dele = sentence_pairs("First. Cut me. Last.", "First. Last.")
        self.assertEqual([p["op"] for p in dele], ["delete"])
        self.assertEqual(dele[0]["final"], "")

    def test_merge_emits_one_pair(self):
        from services.ideal_text_annotations import sentence_pairs
        pairs = sentence_pairs(
            "Anchor stays. It was short. It was choppy.",
            "Anchor stays. It was short and choppy.")
        self.assertEqual(len(pairs), 1)
        self.assertEqual(pairs[0]["draft"], "It was short. It was choppy.")
        self.assertEqual(pairs[0]["final"], "It was short and choppy.")

    def test_both_empty(self):
        from services.ideal_text_annotations import sentence_pairs
        self.assertEqual(sentence_pairs("", ""), [])
        self.assertEqual(sentence_pairs(None, None), [])

    def test_reflow_only_edit_yields_nothing(self):
        """A moved paragraph break re-splits the same words into different
        sentence lists — the joined content is identical, so no pair (and
        downstream, the approved_as_is endorsement survives). Review
        finding: this used to emit an identical-text 'correction'."""
        from services.ideal_text_annotations import sentence_pairs
        self.assertEqual(
            sentence_pairs("Hello world\nGood day.", "Hello world Good day."),
            [])

    def test_orphan_moment_closer_is_stripped(self):
        """The coach deleted a moment OPENER mid-edit, leaving the bare
        [[/moment]] closer — it must not survive into corpus text (review
        finding: strip_moment_markers only handles matched spans and bare
        openers)."""
        from services.ideal_text_annotations import strip_for_diff
        self.assertEqual(strip_for_diff("Line one.[[/moment]] Line two."),
                         "Line one. Line two.")


class DraftStalenessTests(unittest.TestCase):
    """The false-correction guard (review finding, HIGH): a machine draft
    refreshed AFTER the coach's last edit must not be diffed against that
    older coach text."""

    def test_machine_owned_is_never_stale(self):
        from services.ideal_text_annotations import draft_is_stale
        self.assertFalse(draft_is_stale(
            "2026-07-28T10:00:00+00:00", None, coach_owned=False))

    def test_coach_edit_after_refresh_is_fresh(self):
        from services.ideal_text_annotations import draft_is_stale
        self.assertFalse(draft_is_stale(
            "2026-07-28T10:00:00+00:00", "2026-07-28T11:00:00+00:00",
            coach_owned=True))

    def test_refresh_after_coach_edit_is_stale(self):
        from services.ideal_text_annotations import draft_is_stale
        self.assertTrue(draft_is_stale(
            "2026-07-28T11:00:00+00:00", "2026-07-28T10:00:00+00:00",
            coach_owned=True))

    def test_unparseable_timestamps_fail_closed(self):
        from services.ideal_text_annotations import draft_is_stale
        self.assertTrue(draft_is_stale("garbage", "2026-07-28T10:00:00+00:00",
                                       coach_owned=True))
        self.assertTrue(draft_is_stale("2026-07-28T10:00:00+00:00", None,
                                       coach_owned=True))

    def test_no_machine_refresh_recorded_is_fresh(self):
        from services.ideal_text_annotations import draft_is_stale
        self.assertFalse(draft_is_stale(None, "2026-07-28T10:00:00+00:00",
                                        coach_owned=True))


class EmitTests(unittest.TestCase):

    _ARC = "12345678-aaaa-bbbb-cccc-121212121212"

    def _emit(self, draft, final, db=None, owner="student-1"):
        from services.ideal_text_annotations import emit_ideal_text_annotations
        db = db if db is not None else MagicMock()
        n = emit_ideal_text_annotations(
            db, arc_id=self._ARC, owner_user_id=owner,
            coach_user_id="coach-1", draft_text=draft, final_text=final)
        return n, db

    def test_untouched_verify_is_one_block_endorsement(self):
        n, db = self._emit("The whole text. As the machine wrote it.",
                           "The whole text. As the machine wrote it.")
        self.assertEqual(n, 1)
        kwargs = db.create_admin_annotation_event.call_args.kwargs
        self.assertEqual(kwargs["field_name"], "ideal_text_block")
        self.assertEqual(kwargs["section_type"], "ideal_text")
        self.assertEqual(kwargs["reason_chip"], "approved_as_is")
        self.assertEqual(kwargs["user_id"], "student-1")
        self.assertEqual(kwargs["created_by"], "coach-1")
        self.assertEqual(kwargs["draft_id"], self._ARC)

    def test_changed_sentences_emit_pairs(self):
        n, db = self._emit(
            "Keep one. Change this. Keep two.",
            "Keep one. This got changed. Keep two.")
        self.assertEqual(n, 1)
        kwargs = db.create_admin_annotation_event.call_args.kwargs
        self.assertEqual(kwargs["field_name"], "ideal_text_sentence")
        self.assertIsNone(kwargs["reason_chip"])
        self.assertEqual(kwargs["ai_original_text"], "Change this.")
        self.assertEqual(kwargs["coach_final_text"], "This got changed.")

    def test_insert_has_null_draft_side(self):
        n, db = self._emit("First. Last.", "First. New middle. Last.")
        kwargs = db.create_admin_annotation_event.call_args.kwargs
        self.assertIsNone(kwargs["ai_original_text"])
        self.assertEqual(kwargs["coach_final_text"], "New middle.")

    def test_empty_machine_draft_emits_nothing(self):
        """Legacy rows (pre auto-copy migration) have no auto_text. Diffing
        against "" would mark the coach as having written the whole block —
        exactly the false signal this module must not produce."""
        n, db = self._emit("", "The coach text. It is long.")
        self.assertEqual(n, 0)
        db.create_admin_annotation_event.assert_not_called()

    def test_no_owner_emits_nothing(self):
        n, db = self._emit("A. B.", "A. C.", owner=None)
        self.assertEqual(n, 0)
        db.create_admin_annotation_event.assert_not_called()

    def test_cap_bounds_a_pathological_rewrite(self):
        from services.ideal_text_annotations import _MAX_PAIRS
        draft = " ".join(
            f"Sentence number {i} says alpha." for i in range(300))
        final = " ".join(
            (f"Sentence number {i} says alpha." if i % 2 == 0
             else f"Sentence number {i} says beta.") for i in range(300))
        n, db = self._emit(draft, final)
        self.assertEqual(n, _MAX_PAIRS)
        self.assertEqual(db.create_admin_annotation_event.call_count,
                         _MAX_PAIRS)

    def test_db_failure_returns_zero_never_raises(self):
        db = MagicMock()
        db.create_admin_annotation_event.side_effect = RuntimeError("down")
        n, _ = self._emit("A one. B two.", "A one. C three.", db=db)
        self.assertEqual(n, 0)

    def test_stale_draft_emits_nothing(self):
        """Coach verified v1, a new take refreshed the machine draft, coach
        re-verifies: diffing the v2 draft against v1-era coach text would
        blame machine drift on the coach — emission must skip (review
        finding, HIGH)."""
        from services.ideal_text_annotations import emit_ideal_text_annotations
        db = MagicMock()
        n = emit_ideal_text_annotations(
            db, arc_id=self._ARC, owner_user_id="u", coach_user_id="c",
            draft_text="The refreshed machine draft. It changed a lot.",
            final_text="The coach text from before. It reads well.",
            auto_updated_at="2026-07-28T12:00:00+00:00",
            coach_updated_at="2026-07-28T09:00:00+00:00",
            coach_owned=True)
        self.assertEqual(n, 0)
        db.create_admin_annotation_event.assert_not_called()

    def test_fresh_coach_edit_still_emits(self):
        from services.ideal_text_annotations import emit_ideal_text_annotations
        db = MagicMock()
        n = emit_ideal_text_annotations(
            db, arc_id=self._ARC, owner_user_id="u", coach_user_id="c",
            draft_text="Keep one. Change this. Keep two.",
            final_text="Keep one. This got changed. Keep two.",
            auto_updated_at="2026-07-28T09:00:00+00:00",
            coach_updated_at="2026-07-28T12:00:00+00:00",
            coach_owned=True)
        self.assertEqual(n, 1)

    def test_reflow_only_verify_is_an_endorsement(self):
        """Reflow changes sentence lists but not content — the emission must
        land on the approved_as_is block branch, not a fake pair."""
        n, db = self._emit("Hello world\nGood day.", "Hello world Good day.")
        self.assertEqual(n, 1)
        kwargs = db.create_admin_annotation_event.call_args.kwargs
        self.assertEqual(kwargs["field_name"], "ideal_text_block")
        self.assertEqual(kwargs["reason_chip"], "approved_as_is")

    def test_non_uuid_arc_id_drops_draft_id_only(self):
        from services.ideal_text_annotations import emit_ideal_text_annotations
        db = MagicMock()
        n = emit_ideal_text_annotations(
            db, arc_id="not-a-uuid", owner_user_id="u", coach_user_id="c",
            draft_text="Same text here.", final_text="Same text here.")
        self.assertEqual(n, 1)
        self.assertIsNone(db.create_admin_annotation_event
                          .call_args.kwargs["draft_id"])


if __name__ == "__main__":
    unittest.main()
