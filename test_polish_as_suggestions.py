"""willab — polish-as-suggestions (founder 2026-07-18).

The founder's realisation: the ideal text silently REPLACED the speaker's
words with the compose LLM's light polish, so the user never saw a
suggestion to approve — the opposite of the intended "raw words → suggested
changes → user approves". This lane serves the VERBATIM words and offers
each polish as an approvable grey star (kind 'replace', trigger 'polish';
Approve folds verbatim→edited via the existing serve fold). More L1-faithful.

Pinned here (all behind POLISH_AS_SUGGESTIONS_ENABLED):
  * compose exposes verbatim + a `polished` flag;
  * assemble serves VERBATIM under the flag, anchors polished picks, and
    returns the polish diffs; flag OFF = today's composed text + bolding;
  * maybe_assemble persists polish as suggestions, never displacing an
    acoustic/structural star, refreshing only a prior polish;
  * the served replace suggestion carries `trigger`.

Run: python3 -m unittest test_polish_as_suggestions
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

import services.ideal_text_block as itb

ARC = "a1"
SNIP = "aaaa1111-aaaa-1111-aaaa-111111111111"
SESS = "bbbb2222-bbbb-2222-bbbb-222222222222"


def _bp(edited, verbatim, polished, *, snip=SNIP):
    return {"ready": True, "slides": [{
        "snippet_id": snip, "session_id": SESS,
        "text": edited, "verbatim": verbatim, "polished": polished,
        "breakthrough": False, "key_phrases": [],
    }]}


class AssembleVerbatimTests(unittest.TestCase):
    def _assemble(self, bp, *, flag):
        with patch("services.best_presentation.build_best_presentation",
                   return_value=bp), \
             patch.object(itb, "_polish_as_suggestions_enabled",
                          return_value=flag):
            return itb.assemble_ideal_text_block(ARC, database=object())

    def test_flag_on_serves_verbatim_and_collects_polish(self):
        out = self._assemble(
            _bp("It is not about winning, it is about growth.",
                "it's not about winning it's about growing", True),
            flag=True)
        # the SPEAKER's words are served, not the polish
        self.assertIn("growing", out["text"])
        self.assertNotIn("about growth", out["text"])
        self.assertIn(f"[[moment:{SNIP}|{SESS}]]", out["text"])   # anchored
        self.assertEqual(len(out["polish"]), 1)
        self.assertEqual(out["polish"][0]["snippet_id"], SNIP)
        self.assertEqual(out["polish"][0]["edited"],
                         "It is not about winning, it is about growth.")

    def test_flag_off_is_todays_composed_text(self):
        out = self._assemble(
            _bp("Polished version.", "raw version", True), flag=False)
        self.assertIn("Polished version.", out["text"])
        self.assertEqual(out["polish"], [])

    def test_unpolished_pick_no_star_no_polish(self):
        out = self._assemble(
            _bp("same words", "same words", False), flag=True)
        self.assertNotIn("[[moment:", out["text"])
        self.assertEqual(out["polish"], [])

    def test_whitespace_only_diff_is_not_a_polish(self):
        # `polished` False (compose already trims) → no star even on the flag
        out = self._assemble(
            _bp("  hello world  ", "hello world", False), flag=True)
        self.assertEqual(out["polish"], [])


class PolishPersistTests(unittest.TestCase):
    class _Db:
        def __init__(self, existing=None):
            self.existing = existing or {}
            self.upserts = []

        def get_arc_sessions(self, a):
            return [{"id": "s1", "user_id": "u1", "recording_kind": "spoken",
                     "paired_session_id": None}]

        def get_moment_suggestions_by_arc(self, a):
            return self.existing

        def persist_auto_ideal_text(self, a, t, *, take_count=None,
                                    document=None):
            return True

        def upsert_moment_suggestion(self, snip, arc, kind, repl, why, trig, **_kw):
            self.upserts.append((snip, kind, repl, trig))
            return True

    def _run(self, db, polish):
        auto = {"text": "the served text", "key_moments": [], "polish": polish,
                "ready": True}
        with patch.object(itb, "_polish_as_suggestions_enabled",
                          return_value=True), \
             patch.object(itb, "assemble_ideal_text_block",
                          return_value=auto), \
             patch("services.best_presentation.spoken_arc_sessions",
                   return_value=[{"id": "s1"}]), \
             patch("services.best_presentation.TAKES_TARGET", 1):
            return itb.maybe_assemble_ideal_text(
                ARC, database=db, require_target=False)

    def test_persists_polish_as_replace_trigger_polish(self):
        db = self._Db()
        self._run(db, [{"snippet_id": SNIP, "edited": "the polished line"}])
        self.assertEqual(
            db.upserts,
            [(SNIP, "replace", "the polished line", "polish")])

    def test_never_displaces_an_acoustic_star(self):
        db = self._Db(existing={SNIP: {"trigger": "threat", "kind": "replace"}})
        self._run(db, [{"snippet_id": SNIP, "edited": "polished"}])
        self.assertEqual(db.upserts, [])   # threat star kept

    def test_refreshes_a_prior_polish(self):
        db = self._Db(existing={SNIP: {"trigger": "polish", "kind": "replace"}})
        self._run(db, [{"snippet_id": SNIP, "edited": "re-polished"}])
        self.assertEqual(db.upserts,
                         [(SNIP, "replace", "re-polished", "polish")])

    def test_empty_edit_skipped(self):
        db = self._Db()
        self._run(db, [{"snippet_id": SNIP, "edited": "   "}])
        self.assertEqual(db.upserts, [])

    def test_flag_off_persists_no_polish(self):
        db = self._Db()
        auto = {"text": "x", "key_moments": [],
                "polish": [{"snippet_id": SNIP, "edited": "y"}], "ready": True}
        with patch.object(itb, "_polish_as_suggestions_enabled",
                          return_value=False), \
             patch.object(itb, "assemble_ideal_text_block",
                          return_value=auto), \
             patch("services.best_presentation.spoken_arc_sessions",
                   return_value=[{"id": "s1"}]), \
             patch("services.best_presentation.TAKES_TARGET", 1):
            itb.maybe_assemble_ideal_text(ARC, database=db,
                                          require_target=False)
        self.assertEqual(db.upserts, [])


if __name__ == "__main__":
    unittest.main()
