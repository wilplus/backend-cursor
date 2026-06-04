"""Unit tests for services.strong_sides_library (design §7 / §3.11).

Covers build_library_rows (the pure join of insights_payload coach
notes onto snippet raw data) + ingest_session_library's best-effort
DB-miss paths (mocked).

Run: python3 -m unittest test_strong_sides_library
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# Stub services.db so the module imports without a live client.
_stub_db = types.ModuleType("services.db")
_stub_db.db = MagicMock()
sys.modules.setdefault("services.db", _stub_db)


class BuildRowsTests(unittest.TestCase):

    def _build(self, insights, snippets):
        from services.strong_sides_library import build_library_rows
        return build_library_rows(
            user_id="u1", session_id="sess1",
            insights_payload=insights, snippets=snippets,
        )

    SNIPPETS = [
        {"id": "a", "transcript": "the demo moment",
         "metrics": {"wpm": 150, "f0_mean": 165.0},
         "audio_segment_path": "https://x/parent.webm",
         "start_offset_ms": 0, "duration_ms": 8000},
        {"id": "b", "transcript": "the pricing moment",
         "metrics": {"wpm": 120},
         "audio_segment_path": "https://x/parent.webm",
         "start_offset_ms": 8000, "duration_ms": 6000},
    ]

    def test_joins_note_to_snippet_data(self):
        rows = self._build(
            {"snippet_notes": [
                {"snippet_id": "a", "note": "Strongest 8 seconds.", "tag": "strong"},
            ]},
            self.SNIPPETS,
        )
        self.assertEqual(len(rows), 1)
        r = rows[0]
        self.assertEqual(r["user_id"], "u1")
        self.assertEqual(r["session_id"], "sess1")
        self.assertEqual(r["snippet_id"], "a")
        self.assertEqual(r["note"], "Strongest 8 seconds.")
        self.assertEqual(r["tag"], "strong")
        self.assertEqual(r["snippet_ref"]["transcript"], "the demo moment")
        self.assertEqual(r["snippet_ref"]["features"]["speech_rate"], 150)
        self.assertEqual(r["snippet_ref"]["audio_ref"], "https://x/parent.webm")

    def test_only_tagged_notes_with_found_snippets(self):
        rows = self._build(
            {"snippet_notes": [
                {"snippet_id": "a", "note": "keep", "tag": "strong"},
                {"snippet_id": "ghost", "note": "missing snippet", "tag": "strong"},
            ]},
            self.SNIPPETS,
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["snippet_id"], "a")

    def test_skips_invalid_tag_or_empty_note(self):
        rows = self._build(
            {"snippet_notes": [
                {"snippet_id": "a", "note": "", "tag": "strong"},
                {"snippet_id": "b", "note": "ok", "tag": "bogus"},
            ]},
            self.SNIPPETS,
        )
        self.assertEqual(rows, [])

    def test_no_insights_payload(self):
        self.assertEqual(self._build(None, self.SNIPPETS), [])
        self.assertEqual(self._build({}, self.SNIPPETS), [])
        self.assertEqual(self._build({"snippet_notes": []}, self.SNIPPETS), [])

    def test_both_tags_ingested(self):
        rows = self._build(
            {"snippet_notes": [
                {"snippet_id": "a", "note": "good", "tag": "strong"},
                {"snippet_id": "b", "note": "work on this", "tag": "to_work_on"},
            ]},
            self.SNIPPETS,
        )
        self.assertEqual({r["tag"] for r in rows}, {"strong", "to_work_on"})


class IngestTests(unittest.TestCase):

    def test_no_insights_returns_zero(self):
        from services import strong_sides_library as mod
        from services.db import db
        with patch.object(db, "v2_get_session_by_id",
                          return_value={"id": "s", "insights_payload": None}):
            self.assertEqual(mod.ingest_session_library("s", "u1"), 0)

    def test_missing_user_or_session_returns_zero(self):
        from services import strong_sides_library as mod
        self.assertEqual(mod.ingest_session_library("", "u1"), 0)
        self.assertEqual(mod.ingest_session_library("s", ""), 0)

    def test_happy_path_calls_upsert(self):
        from services import strong_sides_library as mod
        from services.db import db
        with patch.object(
            db, "v2_get_session_by_id",
            return_value={
                "id": "s",
                "insights_payload": {"snippet_notes": [
                    {"snippet_id": "a", "note": "good", "tag": "strong"},
                ]},
            },
        ), patch.object(
            db, "get_snippets_by_session",
            return_value=[{"id": "a", "transcript": "x", "metrics": {}}],
        ), patch.object(
            db, "upsert_strong_sides_library", return_value=1,
        ) as mock_upsert:
            n = mod.ingest_session_library("s", "u1")
        self.assertEqual(n, 1)
        mock_upsert.assert_called_once()

    def test_db_failure_returns_zero(self):
        from services import strong_sides_library as mod
        from services.db import db
        with patch.object(db, "v2_get_session_by_id",
                          side_effect=Exception("db down")):
            self.assertEqual(mod.ingest_session_library("s", "u1"), 0)


if __name__ == "__main__":
    unittest.main()
