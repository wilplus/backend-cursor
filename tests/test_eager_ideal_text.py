"""
STORY    As a speaker, I want my Ideal Text built from my Take as soon as it
         is processed, never saved from an empty assembly and never rebuilt
         over the document I already have, so that record -> Ideal Text ->
         next Take always ends in a real Ideal Text (Never-3, Never-5).
OUTCOME
  O1  A Take with no document yet: the assembled text is persisted, with
      the version = the source Take's number and the piece provenance.
  O2  An empty assembly persists nothing and reports failure.
  O3  A Project that already has a document is left alone: nothing is
      assembled or persisted (a later Take never overwrites my words).
PROVES   O1 -> test_a_ready_assembly_is_persisted_as_the_takes_version
         O2 -> test_not_ready_assembly_never_persists
         O3 -> test_an_existing_document_is_never_rebuilt
WHY      services.ideal_text_block.maybe_assemble_ideal_text, called by the
         analysis worker after every spoken Take (founder 2026-07-15 eager
         assembly; 2026-08-05 version = Take count; Option A 2026-09-22).
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import services.ideal_text_block as mod

ARC = "a1"


def _spoken(i):
    return {"id": f"s{i}", "user_id": "u1", "arc_id": ARC, "take_index": i,
            "created_at": f"2026-07-1{i}T10:00:00Z",
            "recording_kind": "spoken", "paired_session_id": None}


class _Db:
    """The reads and the one write maybe_assemble_ideal_text makes."""

    def __init__(self, sessions, existing_row=None):
        self.sessions = sessions
        self.existing_row = existing_row
        self.persisted: list = []
        self.takes = self
        self.ideal_text = self

    def get_arc_sessions(self, _arc):
        return self.sessions

    def v2_get_session_by_id(self, sid):
        return next((s for s in self.sessions if s["id"] == sid), None)

    def get_coach_arc_ideal_text(self, _arc):
        return self.existing_row

    def persist_auto_ideal_text(self, arc, text, *, take_count=None, document=None):
        self.persisted.append({"arc": arc, "text": text, "take_count": take_count,
                               "document": document})
        return True


class EagerAssemblyTests(unittest.TestCase):
    def _run(self, db, auto, *, source="s2"):
        with patch.object(mod, "assemble_transcript_document",
                          return_value=auto) as assemble, \
                patch.object(mod, "_snapshot_version"), \
                patch("services.ideal_text_core_snapshot.publish_for_arc"):
            ok = mod.maybe_assemble_ideal_text(
                ARC, database=db, require_target=False, source_session_id=source)
        return ok, assemble

    def test_a_ready_assembly_is_persisted_as_the_takes_version(self):
        # Take 3 already exists, but Take 2 is the one being processed: the
        # version is the source Take's number, not the arc's count.
        db = _Db([_spoken(1), _spoken(2), _spoken(3)])
        document = {"pieces": [{"slide_index": 0, "text": "Hello."}]}
        ok, assemble = self._run(db, {"text": "  Hello.  ", "document": document,
                                      "ready": True})
        self.assertTrue(ok)
        self.assertEqual(assemble.call_args.kwargs["session_id"], "s2")
        self.assertEqual(db.persisted, [{"arc": ARC, "text": "Hello.",
                                         "take_count": 2, "document": document}])

    def test_not_ready_assembly_never_persists(self):
        db = _Db([_spoken(1), _spoken(2)])
        ok, _ = self._run(db, {"text": "", "key_moments": [], "ready": False})
        self.assertFalse(ok)
        self.assertEqual(db.persisted, [])

    def test_an_existing_document_is_never_rebuilt(self):
        db = _Db([_spoken(1), _spoken(2)], existing_row={"text": "My own words."})
        ok, assemble = self._run(db, {"text": "Newer machine words.", "ready": True})
        self.assertTrue(ok)
        assemble.assert_not_called()
        self.assertEqual(db.persisted, [])


if __name__ == "__main__":
    unittest.main()
