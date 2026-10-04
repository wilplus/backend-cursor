"""An accepted rewrite becomes a new version of its Paragraph (contract 29b,
clause 16; F1 Repair Plan Phase 4, P1-1).

The audit of 2026-10-03: "The card says the rewrite was accepted, but after
Take 1 the accepted words never reach the document or its History." These
pin the server-side write: the words come from the V3 freeze that served the
item, the one owner-edit writer stores them, and every refusal changes no
word and says why.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services import accepted_rewrite as ar

PARTS = [
    {"id": "p-1", "ord": 0, "text": "We start here.", "locked_at": None,
     "root_phrase": None},
    {"id": "p-2", "ord": 1, "text": "Um so the data is kind of clear.",
     "locked_at": None, "root_phrase": None},
]
SERVED = "We start here.\n\nUm so the data is kind of clear."


class _Ideal:
    def __init__(self, row):
        self.row = row

    def get_coach_arc_ideal_text(self, _arc):
        return self.row


class _Db:
    def __init__(self, *, parts=None, served=SERVED, edit=None,
                 item=True, cas_error=None):
        self.parts = [dict(p) for p in (PARTS if parts is None else parts)]
        self.ideal_text = _Ideal({"auto_text": served, "version": 2})
        self.edit = edit
        self.item = item
        self.cas_error = cas_error
        self.cas_calls: list[dict] = []

    def get_served_v3_rewrite(self, take, key):
        if not self.item:
            return None
        return {"source_ideal_part_id": "p-2",
                "generated_output": {"quote": "Um so the data is kind of clear.",
                                     "proposed_text": "The data is clear."}}

    def get_user_ideal_edit(self, _arc, _user):
        return self.edit

    def get_ideal_text_parts(self, _arc, _user, with_lock=False):
        return [dict(p) for p in self.parts]

    slide_words: list = []

    def get_slide_helper_words(self, _arc, _user):
        return self.slide_words

    def compare_and_set_user_ideal_edit(self, **kw):
        self.cas_calls.append(kw)
        if self.cas_error:
            raise RuntimeError(self.cas_error)
        return {"saved": True}


def _accept(db):
    with patch("services.ideal_text_core_snapshot.publish_for_arc") as publish:
        outcome = ar.accept_rewrite(db, arc_id="arc", owner_user_id="u",
                                    take_session_id="take", feedback_id="rw-1")
    return outcome, publish


class AcceptRewriteTests(unittest.TestCase):
    def test_the_served_words_replace_the_quote_in_their_paragraph(self):
        db = _Db()
        outcome, publish = _accept(db)
        self.assertEqual(outcome, ar.APPLIED)
        call = db.cas_calls[0]
        self.assertEqual(call["desired_user_text"],
                         "We start here.\n\nThe data is clear.")
        self.assertEqual(call["desired_parts_lineage"], [
            {"id": "p-1", "ord": 0, "text": "We start here."},
            {"id": "p-2", "ord": 1, "text": "The data is clear."}])
        self.assertEqual(call["source_document_version"], 2)
        publish.assert_called_once()

    def test_the_owner_edit_is_what_the_speaker_reads(self):
        parts = [dict(PARTS[0], text="We start right here."), PARTS[1]]
        edited = "We start right here.\n\nUm so the data is kind of clear."
        db = _Db(parts=parts, edit={"text": edited, "version": 2})
        outcome, _ = _accept(db)
        self.assertEqual(outcome, ar.APPLIED)
        self.assertEqual(db.cas_calls[0]["desired_user_text"],
                         "We start right here.\n\nThe data is clear.")

    def test_an_older_owner_edit_is_not_what_the_speaker_reads(self):
        db = _Db(edit={"text": "Something else.", "version": 1})
        self.assertEqual(_accept(db)[0], ar.APPLIED)

    def test_paragraphs_that_do_not_join_to_the_text_change_nothing(self):
        db = _Db(served="We start here.\n\nOther words.")
        self.assertEqual(_accept(db)[0], ar.STALE)
        self.assertEqual(db.cas_calls, [])

    def test_a_paragraph_with_helper_words_is_refused(self):
        parts = [PARTS[0], dict(PARTS[1], root_phrase="data is")]
        db = _Db(parts=parts)
        self.assertEqual(_accept(db)[0], ar.PROTECTED)
        self.assertEqual(db.cas_calls, [])

    def test_a_locked_paragraph_is_refused(self):
        parts = [PARTS[0], dict(PARTS[1], locked_at="t")]
        self.assertEqual(_accept(_Db(parts=parts))[0], ar.PROTECTED)

    def test_the_writer_refusing_a_protected_paragraph_is_protected(self):
        db = _Db(cas_error="IDEAL_TEXT_PART_REQUIRES_UNLOCK")
        self.assertEqual(_accept(db)[0], ar.PROTECTED)

    def test_a_retry_after_the_words_landed_is_already_applied(self):
        parts = [PARTS[0], dict(PARTS[1], text="The data is clear.")]
        db = _Db(parts=parts, served="We start here.\n\nThe data is clear.")
        self.assertEqual(_accept(db)[0], ar.ALREADY)
        self.assertEqual(db.cas_calls, [])

    def test_a_quote_gone_from_the_paragraph_is_stale(self):
        parts = [PARTS[0], dict(PARTS[1], text="Entirely new words.")]
        db = _Db(parts=parts, served="We start here.\n\nEntirely new words.")
        self.assertEqual(_accept(db)[0], ar.STALE)

    def test_an_item_the_freeze_never_served_is_not_found(self):
        db = _Db(item=False)
        self.assertEqual(_accept(db)[0], ar.NOT_FOUND)
        self.assertEqual(db.cas_calls, [])

    def test_a_writer_failure_never_raises(self):
        db = _Db(cas_error="boom")
        self.assertEqual(_accept(db)[0], ar.FAILED)

    def test_the_words_come_from_the_freeze_not_the_request(self):
        # The route passes only ids; there is no parameter for the words.
        import inspect
        params = inspect.signature(ar.accept_rewrite).parameters
        self.assertEqual(sorted(params), [
            "arc_id", "database", "feedback_id", "owner_user_id",
            "take_session_id"])


class TheRouteCallsIt(unittest.TestCase):
    def test_only_an_accepted_rewrite_writes(self):
        from pathlib import Path
        source = (Path(__file__).resolve().parents[1]
                  / "routes/v2/user_sessions.py").read_text()
        start = source.index("def v2_post_take_feedback_response(")
        body = source[start:start + 12000]
        self.assertIn("**text_update_for_answer(", body)

    def test_only_an_accepted_rewrite_writes_the_paragraph(self):
        with patch.object(ar, "accept_rewrite", return_value=ar.APPLIED) as acc:
            self.assertEqual(ar.text_update_for_answer(
                object(), {"feedback_family": "rewrite_clarity",
                           "response": "apply_suggestion", "feedback_id": "rw"},
                "a", "u", "t"),
                {"text_update": "applied"})
            for row in ({"feedback_family": "rewrite_clarity", "response": "keep_wording"},
                        {"feedback_family": "confident_voice", "response": "yes"},
                        {"feedback_family": "great_formulation", "response": "apply_suggestion"}):
                self.assertEqual(ar.text_update_for_answer(
                    object(), row, "a", "u", "t"), {})
            self.assertEqual(acc.call_count, 1)


if __name__ == "__main__":
    unittest.main()


class AuditTwentyTenFourTests(unittest.TestCase):
    """Close-out audit 2026-10-04: a replay never applies twice, an
    ambiguous quote is never guessed, Slide-saved words protect their
    Paragraph, and refusals are read by their code."""

    def test_a_replay_when_the_new_words_hold_the_quote_changes_nothing(self):
        rows = [{"id": "p-2", "ord": 0, "text": "Then we grew fast. Done."}]
        outcome, parts = ar.rewritten_parts(rows, "p-2", "we grew", "we grew fast")
        self.assertEqual((outcome, parts), (ar.ALREADY, None))

    def test_the_first_apply_when_the_new_words_hold_the_quote(self):
        rows = [{"id": "p-2", "ord": 0, "text": "Then we grew. Done."}]
        outcome, parts = ar.rewritten_parts(rows, "p-2", "we grew", "we grew fast")
        self.assertEqual(outcome, ar.APPLIED)
        self.assertEqual(parts[0]["text"], "Then we grew fast. Done.")

    def test_a_quote_found_twice_is_never_guessed(self):
        rows = [{"id": "p-2", "ord": 0, "text": "We grow. Revenue is up. We grow."}]
        outcome, parts = ar.rewritten_parts(rows, "p-2", "We grow.", "We keep growing.")
        self.assertEqual((outcome, parts), (ar.STALE, None))

    def test_slide_saved_helper_words_protect_the_paragraph(self):
        db = _Db()
        db.slide_words = [{"slide_index": 0, "phrase": "data is clear",
                           "source_part_id": "P-2"}]
        outcome, _ = _accept(db)
        self.assertEqual(outcome, ar.PROTECTED)
        self.assertEqual(db.cas_calls, [])

    def test_another_paragraphs_slide_words_do_not_protect_this_one(self):
        db = _Db()
        db.slide_words = [{"slide_index": 0, "phrase": "start",
                           "source_part_id": "p-1"}]
        outcome, _ = _accept(db)
        self.assertEqual(outcome, ar.APPLIED)

    def test_an_unrelated_stale_code_is_a_failure_not_stale(self):
        db = _Db(cas_error="MLC3_ENROLLMENT_AUTHORITY_STALE")
        outcome, _ = _accept(db)
        self.assertEqual(outcome, ar.FAILED)

    def test_the_document_source_stale_code_is_stale(self):
        db = _Db(cas_error="IDEAL_TEXT_DOCUMENT_SOURCE_STALE")
        outcome, _ = _accept(db)
        self.assertEqual(outcome, ar.STALE)

    def test_stray_whitespace_in_a_stored_paragraph_still_joins(self):
        parts = [dict(PARTS[0], text="We start here.  "), dict(PARTS[1])]
        outcome, _ = _accept(_Db(parts=parts))
        self.assertEqual(outcome, ar.APPLIED)
