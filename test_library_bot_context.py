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

# Stub supabase + services.db so master_doc_rag imports without the
# supabase/openai venv — in setUpModule, NOT at import time. A stub
# left in sys.modules at import time leaks into sibling test modules:
# test_homework_regressions decides at import time whether the real
# services.db is importable, and a leaked stub makes it run against
# the fake instead of skipping. tearDownModule restores the state.
_ORIG_SERVICES_DB = None
_ORIG_SUPABASE = None


def setUpModule():
    global _ORIG_SERVICES_DB, _ORIG_SUPABASE
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    _ORIG_SUPABASE = sys.modules.get("supabase")
    sys.modules["supabase"] = MagicMock()
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)
    if _ORIG_SUPABASE is not None:
        sys.modules["supabase"] = _ORIG_SUPABASE
    else:
        sys.modules.pop("supabase", None)


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
        # replay-only: the bot may not author its own coaching/critique
        self.assertIn("only replay what the coach actually wrote", out)
        # deflection covers the common drift questions, not just "improving"
        self.assertIn("what should I work on", out)

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

    # ── BE-3 (Q-BOT): two-anchor metrics + anti-trajectory carve-out ──

    def test_renders_two_anchors_with_metrics(self):
        out = self._render([
            {"tag": "strong", "note": "best open", "session_id": "s1",
             "created_at": "2026-06-06T10:00:00",
             "snippet_ref": {"features": {
                 "speech_rate": 145, "mean_pause": 400,
                 "loudness_range": 12, "f0_mean": 165}}},
            {"tag": "to_work_on", "note": "rushed close", "session_id": "s1",
             "created_at": "2026-06-06T10:00:00",
             "snippet_ref": {"features": {"speech_rate": 190, "mean_pause": 100}}},
        ])
        self.assertIn("TWO ANCHORS", out)
        self.assertIn('Best (coach marked "strong")', out)
        self.assertIn("To work on", out)
        self.assertIn("145 wpm", out)
        self.assertIn("0.4s", out)        # mean_pause 400ms → 0.4s (ms→s)
        self.assertIn("best open", out)

    def test_anchors_scoped_to_most_recent_session(self):
        out = self._render([
            {"tag": "strong", "note": "old", "session_id": "s_old",
             "created_at": "2026-06-01T10:00:00",
             "snippet_ref": {"features": {"speech_rate": 100}}},
            {"tag": "strong", "note": "new", "session_id": "s_new",
             "created_at": "2026-06-06T10:00:00",
             "snippet_ref": {"features": {"speech_rate": 150}}},
        ])
        # anchor metric comes from the NEWEST session only
        self.assertIn("150 wpm", out)
        self.assertNotIn("100 wpm", out)

    def test_anchors_are_only_two_no_series(self):
        entries = [
            {"tag": "strong", "note": f"n{i}", "session_id": "s1",
             "created_at": "2026-06-06T10:00:00",
             "snippet_ref": {"features": {"speech_rate": 140 + i}}}
            for i in range(6)
        ]
        out = self._render(entries)
        self.assertEqual(out.count("• Best"), 1)        # one anchor, not a series
        self.assertNotIn("• To work on", out)            # no to_work_on present
        # metrics live ONLY in the anchor block, never in the notes list
        notes_section = out.split("TWO ANCHORS")[0]
        self.assertNotIn("wpm", notes_section)

    def test_guardrail_carve_out_and_tone(self):
        out = self._render([{"tag": "strong", "note": "x", "session_id": "s1",
                             "snippet_ref": {}}])
        self.assertIn("ONLY those two", out)             # carve-out scope
        self.assertIn("Do not allow the user to gamify", out)  # exact tone, verbatim
        self.assertIn("current strengths and blockers", out)



class MasterDocConstructGuardTests(unittest.TestCase):
    """B1 / AC-9 — the bot must never reintroduce the retired scoring
    construct. The blocklist enforcement moved from prose to CODE
    (master_doc_rag._CONSTRUCT_RE, covered by test_master_doc_output_guards)
    so it can't be crowded out of the prompt under attention pressure; the
    prompt keeps only the positive Readout framing. Deterministic (no LLM);
    the runtime probe lives in tests/evals/master_doc_probe.py."""

    def test_master_document_has_no_retired_construct(self):
        from services.master_doc_rag import MASTER_DOCUMENT
        low = MASTER_DOCUMENT.lower()
        for token in ("threat", "charisma", "t:c", "challenge ratio", "kpi"):
            self.assertNotIn(
                token, low,
                f"retired construct '{token}' is back in the Master Document",
            )

    def test_system_prompt_steers_to_readout_not_score(self):
        """The forbidden jargon is no longer PRIMED into the prompt itself;
        the prompt's remaining duty is the positive framing (describe the
        Readout, never a score/ratio/classifier). The blocklist is enforced
        in code."""
        import re
        from services.master_doc_rag import _SYSTEM_PROMPT, _CONSTRUCT_RE
        # collapse the multi-space artifacts from string-literal wrapping
        flat = re.sub(r"\s+", " ", _SYSTEM_PROMPT.lower())
        self.assertIn("readout", flat)
        self.assertIn("never present a score, ratio, or classifier", flat)
        # the retired construct's name is no longer seeded INTO the prompt
        self.assertNotIn("threat:challenge", flat)
        # and the blocklist guarantee is enforced in code
        self.assertTrue(_CONSTRUCT_RE.search("your Threat:Challenge ratio"))


if __name__ == "__main__":
    unittest.main()
