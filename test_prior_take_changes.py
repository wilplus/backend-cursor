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

Run: python3 -m unittest test_prior_take_changes
"""
from __future__ import annotations

import unittest

from services.prior_take_changes import (
    WHY_KEYS,
    align_fragments,
    build_prior_take_changes,
    why_key,
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


class AlignmentTests(unittest.TestCase):
    def test_same_thing_said_differently_aligns(self):
        new = [_p("n1", "We grew because the team kept showing up.", 2)]
        old = [_p("o1", "We grew because the team stayed relentless.", 1)]
        pairs = align_fragments(new, old)
        self.assertEqual(len(pairs), 1)
        self.assertEqual((pairs[0][0]["snippet_id"],
                          pairs[0][1]["snippet_id"]), ("n1", "o1"))

    def test_new_material_is_not_compared(self):
        new = [_p("n1", "An entirely different point about pricing.", 2)]
        old = [_p("o1", "We grew because the team stayed relentless.", 1)]
        self.assertEqual(align_fragments(new, old), [])

    def test_alignment_is_monotonic_not_positional(self):
        # Take 2 INSERTS a new opening — every fragment shifts one slot.
        # Text matching must still pair the right counterparts.
        new = [_p("n0", "A brand new opening line about the market.", 2),
               _p("n1", "We started small in a tiny room.", 2),
               _p("n2", "Then we shipped the first version fast.", 2)]
        old = [_p("o1", "We started small in a small room.", 1),
               _p("o2", "Then we shipped the first version quickly.", 1)]
        pairs = align_fragments(new, old)
        self.assertEqual([(a["snippet_id"], b["snippet_id"])
                          for a, b, _ in pairs],
                         [("n1", "o1"), ("n2", "o2")])

    def test_one_old_fragment_is_claimed_once(self):
        new = [_p("n1", "We started small in a tiny room.", 2),
               _p("n2", "We started small in a tiny room.", 2)]
        old = [_p("o1", "We started small in a small room.", 1)]
        pairs = align_fragments(new, old)
        self.assertEqual(len(pairs), 1)

    def test_empty_inputs(self):
        self.assertEqual(align_fragments([], []), [])
        self.assertEqual(align_fragments(None, [_p("o", "x")]), [])


class WhyKeyTests(unittest.TestCase):
    def _c(self, **m):
        return {"metrics": m, "slide_stickiness": m.get("slide_stickiness")}

    def test_energy_named_when_it_leads(self):
        self.assertEqual(
            why_key(self._c(f0_sd=10.0, pause_ratio=10.0),
                    self._c(f0_sd=15.0, pause_ratio=10.1)), "energy")

    def test_steadiness_named_when_it_leads(self):
        self.assertEqual(
            why_key(self._c(f0_sd=10.0, pause_ratio=10.0),
                    self._c(f0_sd=10.1, pause_ratio=14.0)), "steadiness")

    def test_coverage_named_when_it_leads(self):
        new = {"metrics": {"f0_sd": 10.0}, "slide_stickiness": 0.4}
        old = {"metrics": {"f0_sd": 10.1}, "slide_stickiness": 0.9}
        self.assertEqual(why_key(new, old), "coverage")

    def test_no_clear_lead_is_overall(self):
        self.assertEqual(
            why_key(self._c(f0_sd=10.0), self._c(f0_sd=10.4)), "overall")
        self.assertEqual(why_key({}, {}), "overall")

    def test_key_is_always_in_the_closed_set(self):
        self.assertIn(why_key({}, {}), WHY_KEYS)


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

    def test_only_the_fragment_the_old_take_won_is_offered(self):
        doc, prev = self._docs()
        out = build_prior_take_changes(doc, prev, database=self._Db())
        self.assertEqual(len(out), 1)
        c = out[0]
        self.assertEqual(c["snippet_id"], "o1")        # decide on the old
        self.assertEqual(c["replaces_snippet_id"], "n1")
        self.assertEqual(c["source"], "prior_take")
        self.assertEqual(c["kind"], "replace")
        self.assertEqual(c["quote"], "We started small in a tiny room.")
        self.assertEqual(c["proposed_text"],
                         "We started small in a cramped room.")
        self.assertEqual(c["take_index"], 1)           # the version badge
        self.assertIn(c["why_key"], WHY_KEYS)
        # The reason rides `why_key` (`why` is null on a prior_take
        # change) — the FE reads why_key first (contract 2026-07-21).
        self.assertIsNone(c["why"])
        # Carries the CURRENT take's session so the FE render-gate
        # (snippet+session) does not drop it.
        self.assertEqual(c["take_session_id"], "sess-new")

    def test_span_slices_back_to_the_quote(self):
        doc, prev = self._docs()
        c = build_prior_take_changes(doc, prev, database=self._Db())[0]
        self.assertEqual(self.DOC[c["span"]["start"]:c["span"]["end"]],
                         c["quote"])

    def test_decided_fragment_is_never_reoffered(self):
        doc, prev = self._docs()
        out = build_prior_take_changes(doc, prev, database=self._Db(),
                                       decided_ids=["o1"])
        self.assertEqual(out, [])

    def test_identical_wording_offers_nothing(self):
        doc = _doc("Same words exactly here.",
                   [("n1", "Same words exactly here.", 2)])
        prev = {"pieces": [_p("o1", "Same words exactly here.", 1)]}
        self.assertEqual(
            build_prior_take_changes(doc, prev, database=self._Db()), [])

    def test_missing_quote_in_document_drops_the_change(self):
        # The piece's carried span no longer slices back to its text (the
        # words were baked/edited away) — never re-point.
        doc = {"text": "A document that lost the fragment.",
               "pieces": [_p("n1", "We started small in a tiny room.", 2,
                             start=0, end=32)]}
        prev = {"pieces": [_p("o1", "We started small in a cramped room.", 1)]}
        self.assertEqual(
            build_prior_take_changes(doc, prev, database=self._Db()), [])

    def test_unmeasured_pieces_never_produce_offers(self):
        # Past the per-take LLM budget a piece has no overall_score.
        # Treating that as 0 handed out blanket "your previous take said
        # it better" offers (review finding) — both sides must be
        # measured or there is no comparison to make.
        class _Unscored(self._Db):
            ROWS = {k: {"metrics": {"f0_sd": 10.0}}
                    for k in ("n1", "n2", "o1", "o2")}
        doc, prev = self._docs()
        self.assertEqual(
            build_prior_take_changes(doc, prev, database=_Unscored()), [])

    def test_ac9_no_scores_or_internal_vocabulary(self):
        import json
        doc, prev = self._docs()
        raw = json.dumps(build_prior_take_changes(doc, prev,
                                                  database=self._Db()))
        for banned in ("overall_score", "power_score", "_score", "f0_sd",
                       "activation", "charisma", "threat", "stickiness"):
            self.assertNotIn(banned, raw)

    def test_degrades_on_bad_inputs(self):
        self.assertEqual(build_prior_take_changes(None, None,
                                                  database=self._Db()), [])
        doc, prev = self._docs()
        self.assertEqual(
            build_prior_take_changes(doc, prev, database=object()), [])


try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
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
            with patch.dict("os.environ",
                            {"LIVING_TRANSCRIPT_ENABLED":
                             "1" if flag else "0"}), \
                 patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(owned, [])), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={"version": 3}), \
                 patch.object(v2.db, "upsert_ideal_decision",
                              return_value=True) as m_led:
                out = v2.v2_explore_decide_prior_take.__wrapped__(self.ARC)
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

    def test_accept_without_proposal_400s(self):
        _, status, m_led = self._post({
            "action": "accept", "snippet_id": "o1", "quote": "x"})
        self.assertEqual(status, 400)
        m_led.assert_not_called()

    def test_bad_action_and_missing_fields_400(self):
        for bad in ({"action": "maybe", "snippet_id": "o1", "quote": "x"},
                    {"action": "keep", "quote": "x"},
                    {"action": "keep", "snippet_id": "o1"}):
            _, status, _ = self._post(bad)
            self.assertEqual(status, 400)

    def test_flag_off_and_unowned_404(self):
        _, status, _ = self._post({"action": "keep", "snippet_id": "o1",
                                   "quote": "x"}, flag=False)
        self.assertEqual(status, 404)
        _, status, _ = self._post({"action": "keep", "snippet_id": "o1",
                                   "quote": "x"}, owned=False)
        self.assertEqual(status, 404)


class BakeRoundTripTests(unittest.TestCase):
    """The loop that makes the founder's math work: accept → the ledger
    row → the NEXT document carries the previous wording, permanently."""

    def test_accepted_prior_wording_bakes_into_the_next_document(self):
        from services.ideal_decision_ledger import (
            bake_piece, normalize_phrase,
        )
        quote = "We started small in a tiny room."
        row = {"kind": "replace", "target_phrase": normalize_phrase(quote),
               "display_phrase": quote,
               "replacement_text": "We started small in a cramped room.",
               "decision": "approved", "source": "prior_take"}
        doc = f"{quote} Then we shipped it fast."
        self.assertEqual(
            bake_piece(doc, [row]),
            "We started small in a cramped room. Then we shipped it fast.")


if __name__ == "__main__":
    unittest.main()
