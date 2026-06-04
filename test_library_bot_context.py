"""Unit tests for the Lounge bot's library context (§3.12).

Covers _render_library_block (the pure render of the user's strong-
sides library into the bot's system prompt) + the librarian guardrail.
master_doc_rag imports services.will_voice (pure) + services.db lazily,
so a db stub keeps it import-safe in the lean env.

Run: python3 -m unittest test_library_bot_context
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

# Stub heavy deps so master_doc_rag imports without supabase/openai.
sys.modules.setdefault("supabase", MagicMock())
_stub_db = types.ModuleType("services.db")
_stub_db.db = MagicMock()
sys.modules.setdefault("services.db", _stub_db)


class RenderLibraryBlockTests(unittest.TestCase):

    def _render(self, entries):
        from services.master_doc_rag import _render_library_block
        return _render_library_block(entries)

    def test_empty_returns_empty_string(self):
        self.assertEqual(self._render(None), "")
        self.assertEqual(self._render([]), "")

    def test_renders_note_and_tag_and_transcript(self):
        out = self._render([{
            "tag": "strong",
            "note": "Strongest 8 seconds — do more of this.",
            "snippet_ref": {"transcript": "and that's when I realized the whole thing"},
        }])
        self.assertIn("strong", out)
        self.assertIn("Strongest 8 seconds", out)
        self.assertIn("that's when I realized", out)

    def test_to_work_on_label(self):
        out = self._render([{
            "tag": "to_work_on", "note": "Watch the drop-off.",
            "snippet_ref": {"transcript": "the numbers part"},
        }])
        self.assertIn("to work on", out)

    def test_includes_librarian_guardrail(self):
        out = self._render([{"tag": "strong", "note": "x", "snippet_ref": {}}])
        # the guardrail's anti-synthesis instruction must be present
        self.assertIn("LIBRARIAN", out)
        self.assertIn("trajectory", out.lower())
        self.assertIn("am I improving", out)

    def test_skips_empty_notes(self):
        out = self._render([
            {"tag": "strong", "note": "   ", "snippet_ref": {}},
            {"tag": "strong", "note": "real note", "snippet_ref": {}},
        ])
        self.assertIn("real note", out)
        # only one bullet rendered
        self.assertEqual(out.count("coach noted:"), 1)

    def test_all_empty_notes_returns_empty(self):
        out = self._render([
            {"tag": "strong", "note": "", "snippet_ref": {}},
            {"tag": "to_work_on", "note": "   ", "snippet_ref": {}},
        ])
        self.assertEqual(out, "")

    def test_caps_at_20_entries(self):
        entries = [
            {"tag": "strong", "note": f"note {i}", "snippet_ref": {}}
            for i in range(30)
        ]
        out = self._render(entries)
        self.assertEqual(out.count("coach noted:"), 20)

    def test_long_transcript_truncated(self):
        out = self._render([{
            "tag": "strong", "note": "n",
            "snippet_ref": {"transcript": "x" * 400},
        }])
        self.assertIn("…", out)

    def test_missing_snippet_ref_ok(self):
        out = self._render([{"tag": "strong", "note": "no ref here"}])
        self.assertIn("no ref here", out)

    def test_non_dict_entries_skipped(self):
        out = self._render(["garbage", {"tag": "strong", "note": "keep", "snippet_ref": {}}])
        self.assertIn("keep", out)


if __name__ == "__main__":
    unittest.main()
