"""
STORY    As a speaker, I want Take 2 to rewrite only the slides I spoke and
         keep the others and my helper words, so that my Ideal Text is what I
         said last and nothing is lost.
OUTCOME
  O1  The slide I spoke in Take 2 is rebuilt from what I said; the slide I
      did not speak keeps its words.
  O2  My earlier edit is not carried over; it stays at its own version.
  O3  Each Paragraph keeps its id, and my locked helper words move to their
      slide.
  O4  The first Take on new slides (N257) writes the whole Ideal Text fresh
      from what I said, and my helper words move to the new slide with the
      same title; the others leave the page.
PROVES   O1 -> EveryTakeRewritesTheSlidesItSpoke::test_the_spoken_slide_is_rebuilt_and_the_other_is_kept
         O2 -> EveryTakeRewritesTheSlidesItSpoke::test_the_spoken_slide_is_rebuilt_and_the_other_is_kept
         O3 -> EveryTakeRewritesTheSlidesItSpoke::test_the_spoken_slide_is_rebuilt_and_the_other_is_kept
         O4 -> TheFirstTakeOnNewSlides::test_the_whole_text_is_fresh_and_helper_words_follow_the_title
WHY      Never-rule 5; founder 2026-09-25 (contracts 8-9); N257.
"""
from __future__ import annotations

import unittest

from services.take_review import (
    finalize_later_take_review,
)


class _ReviewDb:
    def __init__(self):
        self.session = {
            "id": "take-2",
            "arc_id": "arc-1",
            "user_id": "user-1",
            "take_index": 2,
            "recording_kind": "spoken",
            "paired_session_id": None,
        }
        self.ideal = {
            "arc_id": "arc-1",
            "version": 1,
            "auto_text": "Canonical words",
            "text": "Canonical words",
        }
        self.edit = {"text": "My exact words", "version": 1}
        self.snapshots = {}
        self.suggestions = {}

    def v2_get_session_by_id(self, session_id):
        return self.session if session_id == self.session["id"] else None

    def get_coach_arc_ideal_text(self, arc_id):
        return dict(self.ideal) if arc_id == "arc-1" else None

    @property
    def ideal_text(self):
        # audit Q-A2: production now calls database.ideal_text.<method>();
        # this fake implements those methods directly on itself.
        return self

    # The project's Takes, each with the deck it was said on (N257).
    sessions: list = []

    @property
    def takes(self):
        return self

    def get_arc_sessions(self, arc_id):
        return [dict(t) for t in self.sessions]

    def get_user_ideal_edit(self, arc_id, user_id):
        return dict(self.edit) if self.edit else None

    def get_moment_suggestions_by_arc(self, arc_id):
        return self.suggestions

    def finalize_ideal_text_take(
        self, arc_id, owner, session_id, index, moments,
        auto_text=None, document=None,
    ):
        # Mirrors finalize_ideal_text_take_v2: with rebuilt words the new
        # Take wins and the owner edit stays behind; without, v1 exactly.
        self.ideal["version"] = index
        if auto_text:
            self.ideal["auto_text"] = auto_text
            self.ideal["document"] = document
            text = auto_text
        else:
            if self.edit and self.edit["version"] == 1:
                self.edit["version"] = index
            text = self.edit["text"] if self.edit else self.ideal["auto_text"]
        self.snapshots[index] = {
            "arc_id": arc_id,
            "version": index,
            "text": text,
            "moments": moments,
        }
        return {
            "arc_id": arc_id,
            "take_session_id": session_id,
            "take_index": index,
            "version": index,
            "rebuilt": bool(auto_text),
            "text_confirmed": True,
        }

    # Paragraph identity and Slide helper words (take_rebuild).
    parts: list = []
    slide_rows: dict = {}

    def get_ideal_text_parts(self, arc_id, user_id, with_lock=False):
        return [dict(p) for p in self.parts]

    revisions: list = []

    def replace_ideal_text_parts(self, arc_id, user_id, parts,
                                 revision_action=None,
                                 revision_take_session_id=None,
                                 revision_review_version=None):
        # As production does: the helper-word columns carry by Paragraph id
        # across the rewrite (services.db._carried_root, contract 14), and a
        # revision is appended for each Paragraph whose words or lock changed
        # or that is new.
        from services.db import _carried_root
        previous = {str(p.get("id")): p for p in self.parts}
        if revision_action:
            for p in parts:
                before = previous.get(str(p.get("id")))
                if (before is None or before.get("text") != p.get("text")
                        or bool(before.get("locked_at"))
                        != bool(p.get("locked_at"))):
                    self.revisions = self.revisions + [{
                        "part_id": str(p.get("id")),
                        "action": revision_action, "text": p.get("text"),
                        "take_session_id": revision_take_session_id,
                        "review_version": revision_review_version}]
        self.parts = [
            {**dict(p), **_carried_root(previous.get(str(p.get("id"))),
                                        str(p.get("text") or ""))}
            for p in parts]
        return True

    def get_slide_helper_words(self, arc_id, user_id):
        return [dict(r, slide_index=k) for k, rows in self.slide_rows.items()
                for r in rows]

    def replace_slide_helper_words(self, arc_id, user_id, slide, rows):
        self.slide_rows = {**self.slide_rows, slide: list(rows)}
        return True

    def get_ideal_text_version(self, arc_id, version):
        return self.snapshots.get(version)


if __name__ == "__main__":
    unittest.main()


def _two_slide_document():
    text = "Slide one words.\n\nSlide two words."
    return text, {
        "pieces": [],
        "paragraphs": [
            {"slide_index": 0, "start": 0, "end": 16},
            {"slide_index": 1, "start": 18, "end": 34},
        ],
    }


class EveryTakeRewritesTheSlidesItSpoke(unittest.TestCase):
    """Contract 8-9 (founder 2026-09-25): Take 2 rebuilds the Slides it spoke
    from what was said, keeps the others, and supersedes the owner edit."""

    def _run(self, database, new_doc):
        from unittest import mock

        with mock.patch(
                "services.transcript_document.build_transcript_document",
                return_value=new_doc), \
                mock.patch(
                    "services.ideal_text_core_snapshot.publish_for_arc"):
            return finalize_later_take_review(
                database, arc_id="arc-1", owner_user_id="user-1",
                take_session_id="take-2", take_index=2)

    def test_the_spoken_slide_is_rebuilt_and_the_other_is_kept(self):
        database = _ReviewDb()
        old_text, old_doc = _two_slide_document()
        database.ideal.update(auto_text=old_text, text=old_text,
                              document=old_doc)
        database.parts = [
            {"id": "p-one", "ord": 0, "text": "Slide one words.",
             "locked_at": "2026-09-25T10:00:00Z",
             "root_phrase": "one words", "root_start": 6, "root_end": 15,
             "root_selected_at": "2026-09-25T10:00:00Z"},
            {"id": "p-two", "ord": 1, "text": "Slide two words."},
        ]
        new_text = "Take two says slide two differently."
        self._run(database, {
            "text": new_text, "pieces": [],
            "paragraphs": [{"slide_index": 1, "start": 0,
                            "end": len(new_text)}],
            "take_session_id": "take-2", "take_index": 2,
        })
        merged = "Slide one words.\n\n" + new_text
        self.assertEqual(database.ideal["auto_text"], merged)
        self.assertEqual(database.snapshots[2]["text"], merged)
        # Q5 A: the owner edit is not carried; it stays at its version.
        self.assertEqual(database.edit["version"], 1)
        # Identity: the untouched Paragraph keeps its id; slide two reuses
        # its old id for its new words.
        self.assertEqual([(p["id"], p["text"]) for p in database.parts],
                         [("p-one", "Slide one words."), ("p-two", new_text)])
        # Q12 A: the locked Paragraph-level helper words moved to the Slide.
        self.assertEqual(
            [r["phrase"] for r in database.slide_rows.get(0, [])],
            ["one words"])


class TheFirstTakeOnNewSlides(unittest.TestCase):
    """N257: a deck updated inside the project. Slide indexes of the old
    deck mean nothing on the new one, so nothing is merged by index."""

    _run = EveryTakeRewritesTheSlidesItSpoke._run

    def test_the_whole_text_is_fresh_and_helper_words_follow_the_title(self):
        database = _ReviewDb()
        old_text, old_doc = _two_slide_document()
        database.ideal.update(auto_text=old_text, text=old_text,
                              document=dict(old_doc, take_session_id="take-1"))
        database.parts = [
            {"id": "p-one", "ord": 0, "text": "Slide one words."},
            {"id": "p-two", "ord": 1, "text": "Slide two words."},
        ]
        database.sessions = [
            {"id": "take-1", "take_index": 1, "recording_kind": "spoken",
             "intake_context": {"slides": [
                 {"title": "Intro", "body": ""},
                 {"title": "Pricing", "body": ""}]}},
            {"id": "take-2", "take_index": 2, "recording_kind": "spoken",
             "intake_context": {"slides": [
                 {"title": "  pricing ", "body": "new"},
                 {"title": "Team", "body": "new"}]}},
        ]
        database.slide_rows = {
            0: [{"ord": 0, "phrase": "warm hello", "locked_at": "t"}],
            1: [{"ord": 0, "phrase": "one price", "locked_at": "t"}],
        }
        # Take 2 spoke only the new slide 0: a merge by index would have
        # kept the old slide 1's words beside it.
        new_text = "One price for all."
        self._run(database, {
            "text": new_text, "pieces": [],
            "paragraphs": [{"slide_index": 0, "start": 0,
                            "end": len(new_text)}],
            "take_session_id": "take-2", "take_index": 2,
        })
        self.assertEqual(database.ideal["auto_text"], new_text)
        self.assertEqual(database.snapshots[2]["text"], new_text)
        self.assertEqual([p["text"] for p in database.parts], [new_text])
        self.assertNotIn(database.parts[0]["id"], {"p-one", "p-two"})
        # "Pricing" moved from slide 1 to slide 0 (same title, trimmed and
        # case-insensitive) and its words with it; "Intro" is gone, and so
        # are its words from the page.
        self.assertEqual(
            {k: [r["phrase"] for r in rows]
             for k, rows in database.slide_rows.items() if rows},
            {0: ["one price"]})
