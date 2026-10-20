"""
STORY    As a speaker, I want my Ideal Text document never rebuilt by a later
         Take, so that my accepted words stay put.
OUTCOME
  O1  Assembling after Take 2 on a project that already has a document does
      not rebuild, replace or re-version the stored document.
PROVES   O1 -> test_take_two_does_not_rebuild_the_stored_document
WHY      CLAUDE.md rule 5 and N48.3 Q13 A: Take 1 creates the canonical Ideal
         Text; later Takes only produce feedback.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

ARC = "arc-1"
TAKE_ONE_WORDS = "The words the speaker accepted after Take 1."


class _Database:
    """A project whose document already exists; every write is recorded."""

    def __init__(self):
        self.stored = {"auto_text": TAKE_ONE_WORDS, "text": TAKE_ONE_WORDS,
                       "version": 1}
        self.writes: list = []
        self.ideal_text = self
        self.takes = self

    def get_coach_arc_ideal_text(self, arc_id):
        return dict(self.stored)

    def get_arc_sessions(self, arc_id):
        return [
            {"id": f"s{i}", "arc_id": ARC, "take_index": i,
             "recording_kind": "spoken"} for i in (1, 2)]

    def v2_get_session_by_id(self, session_id):
        return {"id": session_id, "arc_id": ARC, "take_index": 2,
                "recording_kind": "spoken"}

    def persist_auto_ideal_text(self, arc_id, text, **kwargs):
        self.writes.append(("persist_auto_ideal_text", text, kwargs))
        self.stored = {**self.stored, "auto_text": text, "text": text}
        return True

    def upsert_ideal_text_version(self, *args, **kwargs):
        self.writes.append(("upsert_ideal_text_version", args, kwargs))


class AnExistingDocumentIsNeverRebuilt(unittest.TestCase):

    def test_take_two_does_not_rebuild_the_stored_document(self):
        import services.ideal_text_block as mod
        database = _Database()
        rebuilt = {"text": "Take 2 said something else entirely.",
                   "key_moments": [], "polish": [], "ready": True,
                   "document": {"pieces": [], "paragraphs": []}}

        with patch.object(mod, "assemble_transcript_document",
                          return_value=rebuilt) as assemble:
            ok = mod.maybe_assemble_ideal_text(
                ARC, database=database, require_target=False,
                source_session_id="s2")

        self.assertTrue(ok)
        self.assertEqual(database.writes, [])
        assemble.assert_not_called()
        self.assertEqual(
            database.get_coach_arc_ideal_text(ARC)["auto_text"],
            TAKE_ONE_WORDS)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
