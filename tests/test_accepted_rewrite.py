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
    door_calls: list = []
    root_clears: list = []

    def get_slide_helper_words(self, _arc, _user):
        return self.slide_words

    def get_ideal_text_document_core(self, _arc, _user):
        # The core pairs each Paragraph with its piece; both are on Slide 0.
        return {"payload": {"parts": [{"id": "p-1"}, {"id": "p-2"}],
                            "pieces": [{"slide_index": 0}, {"slide_index": 0}]}}

    def replace_slide_helper_words(self, _arc, _user, slide, rows):
        self.slide_words = [dict(r, slide_index=slide) for r in rows]
        return True

    def set_ideal_text_part_root(self, **kw):
        self.root_clears = [*self.root_clears, kw]
        return True

    def accept_rewrite_into_part(self, **kw):
        self.door_calls = [*self.door_calls, kw]
        if self.cas_error:
            raise RuntimeError(self.cas_error)
        return {"saved": True}

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


if __name__ == "__main__":
    unittest.main()


class HelperWordsMayPointIntoHistory(unittest.TestCase):
    """Founder 2026-10-05: "it is possible that helper words are attached to
    the words that are not visible - but exist only in the history; that
    should be the logic of it." Accept on a Paragraph with helper words or a
    lock writes the new words, keeps the lock and keeps the helper words."""

    def test_in_text_helper_words_move_to_the_slide_row_before_the_write(self):
        parts = [PARTS[0], dict(PARTS[1], root_phrase="the data",
                                locked_at="t")]
        db = _Db(parts=parts)
        outcome, _ = _accept(db)
        self.assertEqual(outcome, ar.APPLIED)
        # Carried, locked, on the Paragraph's own Slide row.
        self.assertEqual([(r["phrase"], r["source_part_id"], bool(r["locked_at"]))
                          for r in db.slide_words],
                         [("the data", "p-2", True)])
        # The in-text span is cleared: the words now point at the earlier
        # version, which stays in History.
        self.assertEqual(db.root_clears, [{"arc_id": "arc", "user_id": "u",
                                           "part_id": "p-2", "phrase": None,
                                           "start": None, "end": None}])
        # The write goes through the one door, naming the Paragraph.
        self.assertEqual(db.cas_calls, [])
        call = db.door_calls[0]
        self.assertEqual(call["part_id"], "p-2")
        self.assertEqual(call["desired_user_text"],
                         "We start here.\n\nThe data is clear.")
