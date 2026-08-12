"""The take's intervention budget ledger — spend/unspend/count + the take
resolver. Founder 2026-08-10: decided offers keep their slots; a revert
returns one (SPEC R4 — absence of a row means undecided).

Run: python3 -m unittest test_intervention_spend
"""
import unittest

from services import intervention_spend as sp


class _FakeDb:
    def __init__(self):
        self.rows = {}

    def record_intervention_decision(self, *, arc_id, take_session_id,
                                     change_key, decision, lane=None,
                                     intervention_type=None, quote=None,
                                     proposed_text=None, why_key=None):
        self.rows[(arc_id, take_session_id, change_key)] = {
            "decision": decision, "lane": lane,
            "intervention_type": intervention_type,
            "quote": quote, "proposed_text": proposed_text,
            "why_key": why_key,
        }
        return True

    def delete_intervention_decision(self, *, arc_id, take_session_id,
                                     change_key):
        self.rows.pop((arc_id, take_session_id, change_key), None)
        return True

    def count_intervention_decisions(self, arc_id, take_session_id):
        # Mirrors the real counter's slice-2 rule: lane:style rows ride
        # OUTSIDE the ≤3 budget and never count.
        return len([1 for (a, t, _k), row in self.rows.items()
                    if a == arc_id and t == take_session_id
                    and row.get("lane") != "lane:style"])

    def list_style_intervention_decisions(self, arc_id, take_session_id):
        # The complement: the rows the two readers above throw away. Two
        # budgets, two reads, neither charging the other.
        return [row for (a, t, _k), row in self.rows.items()
                if a == arc_id and t == take_session_id
                and row.get("lane") == "lane:style"]


def _take(i, sid=None, kind=None, paired=None):
    return {"id": sid or f"s{i}", "take_index": i,
            "recording_kind": kind, "paired_session_id": paired}


class TestLatestSpokenTakeSid(unittest.TestCase):

    def test_latest_take_index_wins(self):
        rows = [_take(1), _take(3), _take(2)]
        self.assertEqual(sp.latest_spoken_take_sid(rows), "s3")

    def test_read_rows_and_paired_rows_are_not_takes(self):
        rows = [_take(1), _take(9, kind="read"),
                _take(8, paired="other")]
        self.assertEqual(sp.latest_spoken_take_sid(rows), "s1")

    def test_no_takes_is_the_empty_epoch_not_a_crash(self):
        self.assertEqual(sp.latest_spoken_take_sid([]), "")
        self.assertEqual(sp.latest_spoken_take_sid(None), "")


class TestSpendUnspendCount(unittest.TestCase):

    def setUp(self):
        self.db = _FakeDb()
        self.sessions = [_take(1), _take(2)]

    def test_a_style_lane_decision_never_spends_a_slot(self):
        """Slice 2 (founder 2026-08-11, ruling 4: 'Outside'): a post-lock
        style decision lands in the ledger — the learning loop wants every
        explicit decision — but spent_count excludes it, so the ≤3 budget
        is untouched by styling."""
        sp.spend(self.db, "a1", self.sessions,
                 change_key="star:document_bold:s9",
              decision="approved", lane="lane:style",
              intervention_type="EMPHASISE")
        self.assertEqual(sp.spent_count(self.db, "a1", "s2"), 0)
        # …while the row itself exists, texts and all.
        self.assertEqual(len(self.db.rows), 1)
        sp.spend(self.db, "a1", self.sessions, change_key="prior_take:x",
              decision="approved", lane="lane:prior_take",
              intervention_type="REWRITE", quote="said this",
              proposed_text="say that", why_key="energy")
        self.assertEqual(sp.spent_count(self.db, "a1", "s2"), 1)
        row = self.db.rows[("a1", "s2", "prior_take:x")]
        self.assertEqual(row["quote"], "said this")
        self.assertEqual(row["proposed_text"], "say that")
        self.assertEqual(row["why_key"], "energy")

    def test_spend_then_count(self):
        sp.spend(self.db, "a1", self.sessions, change_key="star:x:1",
                 decision="approved", intervention_type="EMPHASISE")
        sp.spend(self.db, "a1", self.sessions, change_key="prior_take:y",
                 decision="disregarded", lane="lane:prior_take",
                 intervention_type="REWRITE")
        self.assertEqual(sp.spent_count(self.db, "a1", "s2"), 2)

    def test_a_retap_never_double_spends(self):
        for _ in range(3):
            sp.spend(self.db, "a1", self.sessions,
                     change_key="block:4:s2", decision="approved")
        self.assertEqual(sp.spent_count(self.db, "a1", "s2"), 1)

    def test_a_revert_returns_the_slot(self):
        sp.spend(self.db, "a1", self.sessions, change_key="star:x:1",
                 decision="approved")
        self.assertEqual(sp.spent_count(self.db, "a1", "s2"), 1)
        sp.unspend(self.db, "a1", self.sessions, change_key="star:x:1")
        self.assertEqual(sp.spent_count(self.db, "a1", "s2"), 0)

    def test_another_take_is_another_epoch(self):
        sp.spend(self.db, "a1", self.sessions, change_key="star:x:1",
                 decision="approved")
        self.assertEqual(sp.spent_count(self.db, "a1", "s3"), 0)

    def test_count_failure_degrades_to_zero_not_silence(self):
        class _Broken:
            def count_intervention_decisions(self, *a):
                raise RuntimeError("boom")
        self.assertEqual(sp.spent_count(_Broken(), "a1", "s2"), 0)


class TestTheStyleLedger(unittest.TestCase):
    """The style lane's OWN budget (founder 2026-08-12): ≤3 per take, ≤2
    per slide. Cumulative, so it needs a ledger — and that ledger is the
    exact rows `spent_count` and `spent_by_paragraph` exclude. Two budgets
    reading one table, neither charging the other."""

    DOC = "First slide words.\n\nSecond slide words.\n\nThird slide words."

    def setUp(self):
        self.db = _FakeDb()
        self.sessions = [_take(1), _take(2)]

    def _style(self, key, quote):
        sp.spend(self.db, "a1", self.sessions, change_key=key,
                 decision="approved", lane="lane:style",
                 intervention_type="EMPHASISE", quote=quote)

    def test_style_slots_are_counted_and_placed(self):
        self._style("s:1", "First slide")
        self._style("s:2", "Third slide")
        out = sp.style_spend(self.db, "a1", "s2", self.DOC)
        self.assertEqual(out["count"], 2)
        self.assertEqual(out["by_paragraph"], {0: 1, 2: 1})

    def test_the_two_budgets_do_not_charge_each_other(self):
        self._style("s:1", "First slide")
        sp.spend(self.db, "a1", self.sessions, change_key="prior_take:x",
                 decision="approved", quote="Second slide")
        # The budgeted counter ignores the style row…
        self.assertEqual(sp.spent_count(self.db, "a1", "s2"), 1)
        # …and the style counter ignores the budgeted one.
        self.assertEqual(sp.style_spend(self.db, "a1", "s2",
                                        self.DOC)["count"], 1)

    def test_an_unplaceable_quote_still_spends_the_TAKE_s_slot(self):
        """A slot spent on words since baked away is still spent — but it
        is charged to no slide, the same drop-never-guess rule
        `spent_by_paragraph` follows, pointed the safe way."""
        self._style("s:1", "words that are no longer anywhere")
        out = sp.style_spend(self.db, "a1", "s2", self.DOC)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["by_paragraph"], {})

    def test_no_served_text_counts_the_take_and_places_nothing(self):
        self._style("s:1", "First slide")
        for junk in (None, "", 42):
            out = sp.style_spend(self.db, "a1", "s2", junk)
            self.assertEqual(out["count"], 1)
            self.assertEqual(out["by_paragraph"], {})

    def test_another_take_is_another_epoch(self):
        self._style("s:1", "First slide")
        self.assertEqual(sp.style_spend(self.db, "a1", "s3",
                                        self.DOC)["count"], 0)

    def test_a_read_failure_degrades_to_zero_not_silence(self):
        class _Broken:
            def list_style_intervention_decisions(self, *a):
                raise RuntimeError("boom")
        self.assertEqual(sp.style_spend(_Broken(), "a1", "s2", self.DOC),
                         {"count": 0, "by_paragraph": {}})
        self.assertEqual(sp.style_spend(self.db, "", "s2", self.DOC),
                         {"count": 0, "by_paragraph": {}})


if __name__ == "__main__":
    unittest.main()
