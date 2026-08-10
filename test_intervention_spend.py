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
                                     intervention_type=None):
        self.rows[(arc_id, take_session_id, change_key)] = {
            "decision": decision, "lane": lane,
            "intervention_type": intervention_type,
        }
        return True

    def delete_intervention_decision(self, *, arc_id, take_session_id,
                                     change_key):
        self.rows.pop((arc_id, take_session_id, change_key), None)
        return True

    def count_intervention_decisions(self, arc_id, take_session_id):
        return len([1 for (a, t, _k) in self.rows
                    if a == arc_id and t == take_session_id])


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


if __name__ == "__main__":
    unittest.main()
