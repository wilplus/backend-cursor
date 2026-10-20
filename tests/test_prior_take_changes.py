"""
STORY    As a speaker, I want to be told when I said a passage better in an
         earlier take, and to accept or keep it, so that my Ideal Text keeps
         my best wording.
OUTCOME
  O1  Fragments align by text, not position; an offer is made only where
      the old fragment clearly beats the new one, anchored on the NEW words
      and proposing the OLD ones; the new take holding its ground is silence.
  O2  A fragment the speaker already decided is never offered again.
  O3  The offer carries no score or internal vocabulary (Never-1).
  O4  Accept writes an approved bake row; keep writes a dismissal with no
      replacement (Never-5: the text changes only on the speaker's yes).
PROVES   O1 -> test_only_the_old_fragment_that_beats_the_new_is_offered
         O2 -> test_only_the_old_fragment_that_beats_the_new_is_offered
         O3 -> test_ac9_no_scores_or_internal_vocabulary
         O4 -> test_accept_writes_an_approved_bake_row,
               test_keep_writes_a_dismissal_with_no_replacement
WHY      Founder decision 2026-07-20 #4 (cross-take discernment).
"""
from __future__ import annotations

import unittest

from config import Config
from services.prior_take_changes import (
    build_prior_take_changes,
)


def _p(sid, text, take=1, start=None, end=None):
    """A document piece. Pieces carry their CHARACTER SPAN — the anchor
    contract; build_prior_take_changes anchors on it, never on a text
    search (the mis-anchor defect the review found)."""
    out = {"snippet_id": sid, "text": text, "take_index": take}
    if start is not None:
        out["start"] = start
        out["end"] = end if end is not None else start + len(text)
    return out


def _doc(text, specs, take_session_id="sess-new"):
    """Build a document whose pieces carry spans located in `text`."""
    pieces, cursor = [], 0
    for sid, frag, take in specs:
        i = text.index(frag, cursor)
        pc = _p(sid, frag, take, start=i, end=i + len(frag))
        pc["take_session_id"] = take_session_id
        pieces.append(pc)
        cursor = i + len(frag)
    return {"text": text, "pieces": pieces}


class BuildChangesTests(unittest.TestCase):
    DOC = ("We started small in a tiny room. "
           "Then we shipped the first version fast.")

    class _Db:
        """Snippet metrics: the OLD first fragment is stronger, the new
        second fragment is stronger."""

        ROWS = {
            "n1": {"metrics": {"overall_score": 0.40, "f0_sd": 8.0}},
            "o1": {"metrics": {"overall_score": 0.80, "f0_sd": 14.0}},
            "n2": {"metrics": {"overall_score": 0.90, "f0_sd": 14.0}},
            "o2": {"metrics": {"overall_score": 0.35, "f0_sd": 8.0}},
        }

        def get_snippet_by_id(self, sid):
            return self.ROWS.get(str(sid))

    def _docs(self):
        doc = _doc(self.DOC, [
            ("n1", "We started small in a tiny room.", 2),
            ("n2", "Then we shipped the first version fast.", 2)])
        prev = {"text": "", "pieces": [
            _p("o1", "We started small in a cramped room.", 1),
            _p("o2", "Then we shipped the first version quickly.", 1)]}
        return doc, prev

    def test_only_the_old_fragment_that_beats_the_new_is_offered(self):
        doc, prev = self._docs()
        # An unrelated, strong opening in the old take: aligning by position
        # would pair it with n1. Aligning by text never compares it.
        prev["pieces"].insert(0, _p("o0", "Good morning to every one of you here today.", 1))
        database = self._Db()
        database.ROWS = {**database.ROWS,
                         "o0": {"metrics": {"overall_score": 0.99, "f0_sd": 20.0}}}
        [offer] = build_prior_take_changes(doc, prev, database=database)
        self.assertEqual((offer["snippet_id"], offer["replaces_snippet_id"]), ("o1", "n1"))
        self.assertEqual(offer["kind"], "replace")
        self.assertEqual(offer["quote"], "We started small in a tiny room.")
        self.assertEqual(self.DOC[offer["span"]["start"]:offer["span"]["end"]],
                         offer["quote"])
        self.assertEqual(offer["proposed_text"], "We started small in a cramped room.")
        self.assertTrue(offer["why_key"])
        # Once decided, never offered again.
        self.assertEqual(build_prior_take_changes(
            doc, prev, database=database, decided_ids=["o1"]), [])

    def test_ac9_no_scores_or_internal_vocabulary(self):
        import json
        doc, prev = self._docs()
        offers = build_prior_take_changes(doc, prev, database=self._Db())
        self.assertEqual(len(offers), 1)
        self.assertEqual(offers[0]["proposed_text"], "We started small in a cramped room.")
        raw = json.dumps(offers)
        for banned in ("overall_score", "power_score", "_score", "f0_sd",
                       "activation", "charisma", "threat", "stickiness"):
            self.assertNotIn(banned, raw)


try:
    from flask import Flask, request

    from routes.v2 import explore_ideal_text as v2_explore_ideal_text
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DecideEndpointTests(unittest.TestCase):
    """Accept BAKES the previous wording forward through the ledger;
    keep remembers the offer as dismissed. Both are phrase-keyed, so the
    decision survives the ranker re-picking across takes."""

    ARC = "a1"

    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, body, *, flag=True, owned=True):
        from unittest.mock import patch
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", bool(flag)), \
                 patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(owned, [])), \
                 patch.object(db.ideal_text, "get_coach_arc_ideal_text",
                              return_value={"version": 3}), \
                 patch.object(db, "upsert_ideal_decision",
                              return_value=True) as m_led:
                out = v2_explore_ideal_text.v2_explore_decide_prior_take.__wrapped__(self.ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_led

    def test_accept_writes_an_approved_bake_row(self):
        body, status, m_led = self._post({
            "action": "accept", "snippet_id": "o1",
            "quote": "We started small in a tiny room.",
            "proposed_text": "We started small in a cramped room."})
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        kw = m_led.call_args.kwargs
        self.assertEqual(kw["decision"], "approved")
        self.assertEqual(kw["source"], "prior_take")
        self.assertEqual(kw["target_phrase"],
                         "we started small in a tiny room.")
        self.assertEqual(kw["replacement_text"],
                         "We started small in a cramped room.")
        self.assertEqual(kw["snippet_id"], "o1")
        self.assertEqual(kw["version"], 3)

    def test_keep_writes_a_dismissal_with_no_replacement(self):
        _, status, m_led = self._post({
            "action": "keep", "snippet_id": "o1",
            "quote": "We started small in a tiny room."})
        self.assertEqual(status, 200)
        kw = m_led.call_args.kwargs
        self.assertEqual(kw["decision"], "dismissed")
        self.assertIsNone(kw["replacement_text"])


if __name__ == "__main__":
    unittest.main()
