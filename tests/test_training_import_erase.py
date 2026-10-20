"""
STORY    As the founder, I want to erase a training import completely, so
         that its audio and everything made from it are gone and no
         speaker's session is touched.
OUTCOME
  O1  Erasing an import deletes its audio and every row it or its review
      wrote; another session's rows stay.
  O2  A session that is not an import is refused, with nothing deleted.
PROVES   O1 -> EraseTrainingImport::test_the_import_goes_and_nothing_else_does
         O2 -> EraseTrainingImport::test_a_speakers_session_is_refused_untouched
WHY      Founder 2026-10-19.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services.training_import_erase import EraseRefused, erase_training_import

SID = "22222222-2222-4222-8222-222222222222"
OTHER = "44444444-4444-4444-8444-444444444444"
ARC = "55555555-5555-4555-8555-555555555555"


class _Query:
    def __init__(self, tables, name):
        self.tables, self.name = tables, name
        self.filters, self.op = [], "select"

    def select(self, *_):
        return self

    def delete(self):
        self.op = "delete"
        return self

    def update(self, values):
        self.op, self.values = "update", values
        return self

    def eq(self, column, value):
        self.filters.append((column, {value}))
        return self

    def in_(self, column, values):
        self.filters.append((column, set(values)))
        return self

    def limit(self, _):
        return self

    def _match(self, row):
        return all(row.get(c) in v for c, v in self.filters)

    def execute(self):
        if self.name not in self.tables:
            raise RuntimeError('relation does not exist (42P01)')
        rows = self.tables[self.name]
        hit = [r for r in rows if self._match(r)]
        if self.op == "delete":
            self.tables[self.name] = [r for r in rows if not self._match(r)]
        if self.op == "update":
            for row in hit:
                row.update(self.values)
        return SimpleNamespace(data=hit)


class _Client:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _Query(self.tables, name)


def _database(source="training_import"):
    tables = {
        "v2_sessions": [
            {"id": SID, "source": source, "arc_id": ARC},
            {"id": OTHER, "source": "interview", "arc_id": "other-arc"}],
        "recordings": [
            {"id": "rec-1", "session_v2_id": SID,
             "storage_path": f"willab_lab/{SID}/import_ab.mp3"},
            {"id": "rec-2", "session_v2_id": OTHER,
             "storage_path": f"willab_lab/{OTHER}/take.webm"}],
        # Production's names: the snippet table was renamed to `snippets`
        # (SNIPPETS_TABLE=snippets) and `charisma_snippets` no longer exists.
        "snippets": [
            {"id": "s1", "session_id": SID}, {"id": "s9", "session_id": OTHER}],
        "confidence_labels": [
            {"snippet_id": "s1"}, {"snippet_id": "s9"}],
        "star_verdicts": [{"session_id": SID}, {"session_id": OTHER}],
        "candidate_windows": [{"recording_id": "rec-1"}],
        "ideal_text_blocks": [{"arc_id": ARC}, {"arc_id": "other-arc"}],
    }
    client = _Client(tables)

    def get(sid):
        return next((r for r in tables["v2_sessions"] if r["id"] == sid), None)

    return SimpleNamespace(client=client, v2_get_session_by_id=get), tables


class EraseTrainingImport(unittest.TestCase):

    def test_the_import_goes_and_nothing_else_does(self):
        database, tables = _database()
        with patch("services.training_import_erase.SNIPPETS_TABLE", "snippets"), \
                patch("services.training_import_erase._erase_audio") as audio:
            result = erase_training_import(database, SID)
        audio.assert_called_once_with([f"willab_lab/{SID}/import_ab.mp3"])
        self.assertTrue(result["erased"])
        self.assertEqual(tables["v2_sessions"], [
            {"id": OTHER, "source": "interview", "arc_id": "other-arc"}])
        self.assertEqual([r["id"] for r in tables["recordings"]], ["rec-2"])
        self.assertEqual(tables["snippets"], [{"id": "s9", "session_id": OTHER}])
        self.assertEqual(tables["confidence_labels"], [{"snippet_id": "s9"}])
        self.assertEqual(tables["star_verdicts"], [{"session_id": OTHER}])
        self.assertEqual(tables["candidate_windows"], [])
        self.assertEqual(tables["ideal_text_blocks"], [{"arc_id": "other-arc"}])

    def test_a_speakers_session_is_refused_untouched(self):
        database, tables = _database(source="interview")
        before = {k: list(v) for k, v in tables.items()}
        with patch("services.training_import_erase._erase_audio") as audio, \
                self.assertRaises(EraseRefused) as refused:
            erase_training_import(database, SID)
        self.assertEqual(refused.exception.code, "NOT_AN_IMPORT")
        audio.assert_not_called()
        self.assertEqual(tables, before)


if __name__ == "__main__":
    unittest.main()
