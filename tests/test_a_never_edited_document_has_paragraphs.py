"""
STORY    As a speaker who never edited my Ideal Text, I want my document to get
         paragraph identity when it is published, so that feedback and slides
         attach to my paragraphs and the screen is not empty.
OUTCOME
  O1  Publishing a never-edited document writes one part per paragraph, each
      with its own id, and the words are unchanged.
  O2  A second publish of the same document writes nothing; the ids stay.
  O3  A document that already has its own parts is never rewritten.
  O4  A document whose paragraphs cannot be proven gets no parts; the words
      are still published unchanged.
PROVES   O1 -> test_a_never_edited_document_gets_one_part_per_paragraph
         O2 -> test_a_second_publish_writes_nothing
         O3 -> test_a_document_with_its_own_parts_is_never_rewritten
         O4 -> test_an_unprovable_split_writes_no_parts
WHY      Production 2026-09-19: `parts=0 pieces=3` -- nothing ever minted
         identity, so V3 feedback and the slide join were dark.
"""
from __future__ import annotations

import unittest
import uuid
from unittest.mock import patch

FIRST = "The opening paragraph of the talk."
SECOND = "A second paragraph, on the very same slide."
SERVED = f"{FIRST}\n\n{SECOND}"


class _Database:
    """The two parts calls `build_snapshot` makes, and nothing else."""

    def __init__(self, rows=None):
        self.rows = list(rows or [])
        self.writes: list = []

    def get_ideal_text_parts(self, arc_id, user_id, *, with_lock=False):
        return list(self.rows)

    def replace_ideal_text_parts(self, arc_id, user_id, parts,
                                 revision_action=None):
        self.writes.append(parts)
        self.rows = [{**p, "locked_at": None, "iteration": 0} for p in parts]
        return True


def _snapshot(database, text=SERVED):
    """`build_snapshot` with everything but the parts lifecycle stubbed out."""
    from services import ideal_text_core_snapshot as mod
    # `type()` rather than a class body: a class body cannot close over
    # `text`, and binding it through the namespace keeps the stub honest.
    _Source = type("_Source", (), {"machine_text": text, "version": 1})
    _Live = type("_Live", (), {"text": text, "user_edited": False,
                               "status": "ready", "prior_edit": None})
    _Display = type("_Display", (), {"text": text, "enabled": False})

    class _Project:
        spoken_rows = [{"owner_principal_id": "owner", "project_id": "proj"}]
        latest_take_session_id = "take-1"
        title = "A talk"
        can_record_take = True
        presentation_ref = None
        slide_titles = []

    database.ideal_text = type(
        "_I", (), {"get_coach_arc_ideal_text": staticmethod(
            lambda arc: {"document": {}, "auto_text": text})})()
    with patch.object(mod, "resolve_ideal_text_source",
                      return_value=_Source()), \
        patch.object(mod, "resolve_live_text", return_value=_Live()), \
        patch.object(mod, "resolve_suggestion_display",
                     return_value=_Display()), \
        patch.object(mod, "resolve_project_read", return_value=_Project()):
        payload, _seed, _lineage = mod.build_snapshot(
            database, "arc-1", "user-1", sessions=[])
    return payload


def _ids(parts):
    return [str(p["id"]) for p in parts]


class ThePublishBoundaryMintsParagraphIdentity(unittest.TestCase):

    def test_a_never_edited_document_gets_one_part_per_paragraph(self):
        database = _Database(rows=[])
        payload = _snapshot(database)

        self.assertEqual(len(database.writes), 1)
        written = database.writes[0]
        self.assertEqual([p["text"] for p in written], [FIRST, SECOND])
        ids = _ids(written)
        self.assertEqual(len(set(ids)), 2)
        for part_id in ids:
            uuid.UUID(part_id)
        # The words are untouched, and the published parts carry the ids
        # that were stored, so feedback and slides can attach to them.
        self.assertEqual(payload["text"], SERVED)
        self.assertEqual(_ids(payload["parts"]), ids)

    def test_a_second_publish_writes_nothing(self):
        database = _Database(rows=[])
        first = _snapshot(database)
        second = _snapshot(database)

        self.assertEqual(len(database.writes), 1)
        self.assertEqual(_ids(second["parts"]), _ids(first["parts"]))
        self.assertEqual(second["text"], SERVED)

    def test_a_document_with_its_own_parts_is_never_rewritten(self):
        own = [
            {"id": str(uuid.uuid4()), "ord": 0, "text": FIRST,
             "locked_at": None, "iteration": 2},
            {"id": str(uuid.uuid4()), "ord": 1, "text": SECOND,
             "locked_at": None, "iteration": 2},
        ]
        database = _Database(rows=own)
        payload = _snapshot(database)

        self.assertEqual(database.writes, [])
        self.assertEqual(database.rows, own)
        self.assertEqual(payload["text"], SERVED)

    def test_an_unprovable_split_writes_no_parts(self):
        # Refused, never approximated: a wrong identity map would anchor
        # every later lock to the wrong words. Each case is one reason the
        # split cannot be proven to be the inverse of the join.
        from services.ideal_text_parts import MAX_DOCUMENT_CHARS, MAX_PARTS
        cases = {
            "an empty document": "   ",
            "a marker cut in half": "Says [[moment:a|b]]\n\nmore]]",
            "whitespace that does not join back": f"{FIRST}\n\n\n{SECOND}",
            "more paragraphs than a person arranges":
                "\n\n".join(["Line."] * (MAX_PARTS + 1)),
            "a document past the stored ceiling":
                "x" * (MAX_DOCUMENT_CHARS + 1),
        }
        for name, text in cases.items():
            with self.subTest(name):
                database = _Database(rows=[])
                payload = _snapshot(database, text=text)
                self.assertEqual(database.writes, [])
                if text.strip():
                    self.assertEqual(payload["text"], text)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
