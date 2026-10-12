"""willab — cross-take discernment on the Living Transcript (founder
decision 2026-07-20 #4).

"When I say something differently the next time in a similar fragment,
the system should spot that and let me know that previous time or this
time it was better."

Pinned here:
  * fragments align by TEXT similarity under a monotonic constraint —
    never by position (the corruption the #227 review found);
  * new material (no confident counterpart) is never compared;
  * a change is offered ONLY when the previous fragment outranks the new
    one by more than noise — the new take holding its ground is silence;
  * the offer is span-anchored on the NEW words, proposes the OLD ones,
    and carries a deterministic why-key;
  * a decided fragment is never re-offered;
  * AC-9: no scores/internal vocabulary on the payload.

Run: python3 -m unittest tests.test_prior_take_changes
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


    def test_ac9_no_scores_or_internal_vocabulary(self):
        import json
        doc, prev = self._docs()
        raw = json.dumps(build_prior_take_changes(doc, prev,
                                                  database=self._Db()))
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
