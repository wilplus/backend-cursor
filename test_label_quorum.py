"""The label ledger's four rules, enforced instead of documented
(services/label_quorum.py — founder 2026-08-11).

Each rule exists because a specific way of poisoning the ground-truth corpus
is easy to reach by accident. What each test class defends:

  RULE 1  A machine prediction that counts as a vote makes every later
          agreement number CIRCULAR — the model grading its own homework and
          reporting the result as human consensus. Unrecoverable after the
          fact, because nothing on the row says which votes were really the
          model's.
  RULE 2  A self-report counted as a peer means "two people agreed" can be
          one person agreeing with themselves. The speaker knows what they
          intended; that is the one judgment not independent of the thing
          judged.
  RULE 3  A singleton in the gold set is one opinion presented as truth; a
          singleton in the EVAL set is worse — the score is then measured
          against a coin flip and looks like a finding.
  RULE 4  Dropping "I don't know" throws away the only class that can teach a
          detector to admit uncertainty, and silently reports the remaining
          agreement as if the abstainers had never looked.

Pure, no DB. Run: python3 -m unittest test_label_quorum
"""
from __future__ import annotations

import unittest

from services import label_quorum as lq


def _row(value=None, *, lane="game_peer", unrateable=False,
         self_report=False, state_id="confidence", rater="r"):
    return {
        "value": value, "lane": lane, "unrateable": unrateable,
        "self_report": self_report, "state_id": state_id, "rater_id": rater,
    }


class TestRule1MachineIsARouter(unittest.TestCase):
    """The machine selects which clip gets rated; it never holds a vote."""

    def test_resolve_takes_no_machine_argument(self):
        # The strongest form of the rule: a proposal cannot influence a
        # resolution it cannot be passed to. If this ever starts accepting a
        # machine value, rule 1 has become a matter of discipline again.
        with self.assertRaises(TypeError):
            lq.resolve([], machine_value="yes")  # type: ignore[call-arg]

    def test_no_machine_lane_exists(self):
        self.assertEqual(lq.QUORUM_LANES, ("coach", "game_peer"))
        self.assertEqual(lq.MACHINE_VOTES, 0)

    def test_one_human_plus_a_machine_proposal_is_still_a_singleton(self):
        res = lq.resolve([_row("yes")])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertFalse(res["settled"])
        # ...and it stays a singleton however loudly the machine agrees.
        self.assertEqual(lq.routing_priority(res, "yes"), lq.P_SINGLETON)
        self.assertEqual(res["machine_votes"], 0)

    def test_unknown_lanes_are_excluded_not_defaulted_in(self):
        # A lane added later (a machine lane, most dangerously) must be
        # admitted to QUORUM_LANES on purpose, never inherited.
        res = lq.resolve([_row("yes"), _row("yes", lane="model_shadow")])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertEqual(res["n_lane_excluded"], 1)

    def test_bootstrap_is_not_a_panel_member(self):
        res = lq.resolve([_row("yes", lane="bootstrap"),
                          _row("yes", lane="bootstrap")])
        self.assertEqual(res["status"], lq.UNRATED)
        self.assertEqual(res["n_lane_excluded"], 2)

    def test_machine_proposal_maps_bands_to_the_ternary(self):
        def snip(band):
            return {"metrics": {"voice_confidence": {"band": band}}}
        self.assertEqual(lq.machine_proposal(snip("confident")), "yes")
        self.assertEqual(lq.machine_proposal(snip("close_to_confident")), "yes")
        self.assertEqual(lq.machine_proposal(snip("neutral")), "neutral")
        self.assertEqual(lq.machine_proposal(snip("unconfident")), "no")
        self.assertEqual(lq.machine_proposal(snip("doubtful")), "no")

    def test_unmeasurable_snippet_proposes_nothing(self):
        # An honest absence, never a fake 'neutral' — a fabricated proposal
        # would make the routing look informed when it is guessing.
        self.assertIsNone(lq.machine_proposal({}))
        self.assertIsNone(lq.machine_proposal({"metrics": {}}))
        self.assertIsNone(lq.machine_proposal(None))
        self.assertIsNone(lq.machine_proposal(
            {"metrics": {"voice_confidence": {"band": None}}}))


class TestRule2OwnerIsNotAPeer(unittest.TestCase):
    """A self-report is calibration signal, never one of the two votes."""

    def test_two_self_reports_are_not_a_quorum(self):
        res = lq.resolve([_row("yes", self_report=True, rater="a"),
                          _row("yes", self_report=True, rater="b")])
        self.assertEqual(res["status"], lq.UNRATED)
        self.assertEqual(res["n_self_report"], 2)
        self.assertFalse(res["gold_eligible"])

    def test_self_report_plus_one_peer_is_a_singleton_not_a_quorum(self):
        # The failure this rule exists to stop: "two people agreed" that is
        # really one person agreeing with themselves.
        res = lq.resolve([_row("yes", self_report=True),
                          _row("yes", lane="game_peer")])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertEqual(res["n_responses"], 1)
        self.assertEqual(res["n_self_report"], 1)

    def test_self_report_on_the_coach_lane_is_still_excluded(self):
        # The whole reason the flag exists rather than a lane check: lane
        # records the SURFACE, the flag records whose clip it was.
        res = lq.resolve([_row("yes", lane="coach", self_report=True),
                          _row("yes", lane="coach")])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertEqual(res["n_self_report"], 1)

    def test_pre_migration_rows_fall_back_to_the_lane(self):
        # Rows written before add_label_quorum_ledger.sql carry no flag. They
        # must still be excluded — a migration lag must not let self-reports
        # into the quorum.
        legacy = {"value": "yes", "lane": "game_owner", "unrateable": False}
        self.assertTrue(lq.is_self_report(legacy))
        res = lq.resolve([legacy, _row("yes")])
        self.assertEqual(res["status"], lq.SINGLETON)

    def test_rating_someone_elses_clip_counts_in_full(self):
        # Same person, different clip: a valid 2nd peer.
        res = lq.resolve([_row("yes", rater="a"), _row("yes", rater="b")])
        self.assertEqual(res["status"], lq.QUORUM)
        self.assertEqual(res["value"], "yes")
        self.assertTrue(res["gold_eligible"])

    def test_own_recordings_are_served_first(self):
        self.assertEqual(lq.serving_rank(True), 0)
        self.assertEqual(lq.serving_rank(False), 1)
        clips = [("theirs", False), ("mine", True), ("theirs2", False)]
        order = sorted(clips, key=lambda c: (lq.serving_rank(c[1]), c[0]))
        self.assertEqual([c[0] for c in order], ["mine", "theirs", "theirs2"])


class TestRule3Singleton(unittest.TestCase):
    """One rating is weak supervision — never gold, never evaluation."""

    def test_singleton_is_never_gold_and_never_eval(self):
        res = lq.resolve([_row("yes")])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertFalse(res["gold_eligible"])
        self.assertFalse(res["eval_eligible"])
        self.assertTrue(res["weak_supervision_only"])
        self.assertTrue(res["needs_rater"])

    def test_singleton_has_no_settled_value(self):
        # Returning the lone answer as the label is the fabricated-ground-
        # truth failure the whole module exists to prevent.
        self.assertIsNone(lq.resolve([_row("no")])["value"])

    def test_disagreement_with_the_machine_routes_first(self):
        res = lq.resolve([_row("no")])
        self.assertTrue(lq.machine_disagrees(res, "yes"))
        self.assertEqual(lq.routing_priority(res, "yes"),
                         lq.P_SINGLETON_DISAGREES)
        # ...and it outranks every other queue state.
        self.assertGreater(lq.P_SINGLETON_DISAGREES, lq.P_NEEDS_THIRD)
        self.assertGreater(lq.P_NEEDS_THIRD, lq.P_SINGLETON)
        self.assertGreater(lq.P_SINGLETON, lq.P_UNRATED)

    def test_agreement_with_the_machine_does_not(self):
        res = lq.resolve([_row("yes")])
        self.assertFalse(lq.machine_disagrees(res, "yes"))
        self.assertEqual(lq.routing_priority(res, "yes"), lq.P_SINGLETON)

    def test_a_silent_machine_is_not_a_disagreement(self):
        res = lq.resolve([_row("yes")])
        for silent in (None, "", "unknown"):
            self.assertFalse(lq.machine_disagrees(res, silent))
            self.assertEqual(lq.routing_priority(res, silent), lq.P_SINGLETON)

    def test_an_idk_singleton_does_not_contradict_the_machine(self):
        # A rater who could not judge has not disagreed with anything; it is
        # the DEFINITE mismatch that carries the active-learning information.
        res = lq.resolve([_row(None, unrateable=True)])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertFalse(lq.machine_disagrees(res, "yes"))


class TestRule4IdkIsAResponse(unittest.TestCase):
    """IDK is counted like any other answer — both founder cases."""

    def test_case_b_one_definite_plus_one_idk_needs_a_third(self):
        res = lq.resolve([_row("yes"), _row(None, unrateable=True)])
        self.assertEqual(res["status"], lq.NEEDS_THIRD)
        self.assertFalse(res["settled"])
        self.assertIsNone(res["value"])
        self.assertTrue(res["needs_rater"])
        self.assertEqual(res["next_rater_ordinal"], 3)
        self.assertEqual(lq.routing_priority(res), lq.P_NEEDS_THIRD)

    def test_case_c_two_idks_settle_as_perceptually_ambiguous(self):
        res = lq.resolve([_row(None, unrateable=True, rater="a"),
                          _row(None, unrateable=True, rater="b")])
        self.assertEqual(res["status"], lq.PERCEPTUALLY_AMBIGUOUS)
        self.assertEqual(res["value"], lq.AMBIGUOUS_LABEL)
        self.assertTrue(res["settled"])
        self.assertTrue(res["gold_eligible"])
        self.assertTrue(res["eval_eligible"])
        self.assertFalse(res["needs_rater"])
        self.assertEqual(lq.routing_priority(res), lq.P_SETTLED)

    def test_the_ambiguous_label_is_not_a_rateable_value(self):
        # It is a statement about the MOMENT. Letting it into the answer
        # domain would make it storable as one rater's response.
        self.assertNotIn(lq.AMBIGUOUS_LABEL, lq.VALUES)

    def test_idk_is_counted_not_dropped(self):
        res = lq.resolve([_row("yes"), _row(None, unrateable=True)])
        self.assertEqual(res["n_responses"], 2)
        self.assertEqual(res["n_idk"], 1)
        self.assertEqual(res["n_definite"], 1)

    def test_neutral_stays_a_definite_answer(self):
        # 'neutral' reads the moment as middling — a judgment, not an
        # abstention. Two of them are a quorum ON 'neutral', not ambiguity.
        res = lq.resolve([_row("neutral", rater="a"),
                          _row("neutral", rater="b")])
        self.assertEqual(res["status"], lq.QUORUM)
        self.assertEqual(res["value"], "neutral")
        self.assertEqual(res["n_idk"], 0)

    def test_idk_can_be_outvoted(self):
        res = lq.resolve([_row("yes", rater="a"), _row("yes", rater="b"),
                          _row(None, unrateable=True, rater="c")])
        self.assertEqual(res["status"], lq.QUORUM)
        self.assertEqual(res["value"], "yes")

    def test_idk_can_win_the_mode(self):
        res = lq.resolve([_row("yes", rater="a"),
                          _row(None, unrateable=True, rater="b"),
                          _row(None, unrateable=True, rater="c")])
        self.assertEqual(res["status"], lq.PERCEPTUALLY_AMBIGUOUS)


class TestTheOneRule(unittest.TestCase):
    """The truth table itself — the four cases fall out of one rule, and the
    SQL view (migrations/add_label_quorum_ledger.sql) computes the same one."""

    def test_truth_table(self):
        cases = [
            ([], lq.UNRATED, None),
            ([_row("yes")], lq.SINGLETON, None),
            ([_row(None, unrateable=True)], lq.SINGLETON, None),
            ([_row("yes", rater="a"), _row("yes", rater="b")],
             lq.QUORUM, "yes"),
            ([_row("no", rater="a"), _row("no", rater="b")], lq.QUORUM, "no"),
            ([_row(None, unrateable=True, rater="a"),
              _row(None, unrateable=True, rater="b")],
             lq.PERCEPTUALLY_AMBIGUOUS, lq.AMBIGUOUS_LABEL),
            ([_row("yes"), _row(None, unrateable=True, rater="b")],
             lq.NEEDS_THIRD, None),
            ([_row("yes", rater="a"), _row("no", rater="b")],
             lq.NEEDS_THIRD, None),
            ([_row("yes", rater="a"), _row("no", rater="b"),
              _row("neutral", rater="c")], lq.NEEDS_THIRD, None),
        ]
        for rows, status, value in cases:
            with self.subTest(status=status, n=len(rows)):
                res = lq.resolve(rows)
                self.assertEqual(res["status"], status)
                self.assertEqual(res["value"], value)

    def test_two_conflicting_definites_route_to_a_third(self):
        # FLAGGED ASSUMPTION (decisions log §J6.2): the founder specified
        # 1-definite-plus-1-IDK and not yes-vs-no. Treated the same — two
        # humans who disagree have not reached a quorum, and booking the
        # coin flip as ground truth is the worse error.
        res = lq.resolve([_row("yes", rater="a"), _row("no", rater="b")])
        self.assertEqual(res["status"], lq.NEEDS_THIRD)
        self.assertIsNone(res["value"])

    def test_quorum_is_exactly_two(self):
        self.assertEqual(lq.QUORUM_N, 2)

    def test_settled_statuses_are_the_only_gold(self):
        for status in (lq.UNRATED, lq.SINGLETON, lq.NEEDS_THIRD):
            self.assertNotIn(status, lq.SETTLED_STATUSES)
        self.assertEqual(lq.SETTLED_STATUSES,
                         (lq.QUORUM, lq.PERCEPTUALLY_AMBIGUOUS))

    def test_a_state_id_filter_does_not_blend_constructs(self):
        rows = [_row("yes", rater="a"),
                _row("yes", rater="b", state_id="authority")]
        self.assertEqual(lq.resolve(rows, state_id="confidence")["status"],
                         lq.SINGLETON)

    def test_malformed_input_never_raises(self):
        for junk in (None, "rows", 7, [None, "x", 3], [{}], [{"value": "maybe"}]):
            self.assertEqual(lq.resolve(junk)["status"], lq.UNRATED)


class TestRatingQueue(unittest.TestCase):
    """Routing order — the only place the machine's proposal is read."""

    def test_most_informative_first_and_settled_clips_leave(self):
        items = [
            {"snippet_id": "s-unrated", "resolution": lq.resolve([])},
            {"snippet_id": "s-settled",
             "resolution": lq.resolve([_row("yes", rater="a"),
                                       _row("yes", rater="b")])},
            {"snippet_id": "s-third",
             "resolution": lq.resolve([_row("yes"),
                                       _row(None, unrateable=True,
                                            rater="b")])},
            {"snippet_id": "s-agrees",
             "resolution": lq.resolve([_row("yes")]),
             "machine_value": "yes"},
            {"snippet_id": "s-disagrees",
             "resolution": lq.resolve([_row("no")]),
             "machine_value": "yes"},
        ]
        ordered = [it["snippet_id"] for it in lq.rating_queue(items)]
        self.assertEqual(
            ordered, ["s-disagrees", "s-third", "s-agrees", "s-unrated"])
        self.assertNotIn("s-settled", ordered)

    def test_ties_break_deterministically(self):
        items = [{"snippet_id": sid, "resolution": lq.resolve([])}
                 for sid in ("c", "a", "b")]
        first = [it["snippet_id"] for it in lq.rating_queue(items)]
        self.assertEqual(first, ["a", "b", "c"])
        self.assertEqual(
            first, [it["snippet_id"] for it in lq.rating_queue(items[::-1])])

    def test_queue_survives_junk(self):
        self.assertEqual(lq.rating_queue(None), [])
        self.assertEqual(lq.rating_queue(["x", None, {}]), [])


class TestCorpusLedger(unittest.TestCase):
    """The dial: rows are not ground truth, settled snippets are."""

    def test_gold_counts_only_settled_snippets(self):
        resolutions = [
            lq.resolve([_row("yes", rater="a"), _row("yes", rater="b")]),
            lq.resolve([_row(None, unrateable=True, rater="a"),
                        _row(None, unrateable=True, rater="b")]),
            lq.resolve([_row("yes")]),
            lq.resolve([_row("yes"), _row("no", rater="b")]),
            lq.resolve([_row("yes", self_report=True)]),
        ]
        led = lq.corpus_ledger(resolutions)
        self.assertEqual(led["snippets"], 5)
        self.assertEqual(led["gold"], 2)
        self.assertEqual(led["ambiguous"], 1)
        self.assertEqual(led["weak"], 1)
        self.assertEqual(led["blocked"], 1)
        self.assertEqual(led["self_reports_excluded"], 1)
        self.assertEqual(led["gold_share"], 0.4)
        # Rule 1 reported, not asserted: non-zero here means the corpus is
        # circular and no agreement number computed off it can be trusted.
        self.assertEqual(led["machine_votes"], 0)

    def test_empty_ledger_has_no_fabricated_share(self):
        led = lq.corpus_ledger([])
        self.assertEqual(led["snippets"], 0)
        self.assertIsNone(led["gold_share"])


class TestTheWriter(unittest.TestCase):
    """db.upsert_state_rating — the two stamps land in their own columns.

    The rules are only as good as the row: a resolver that excludes
    self-reports is worthless if nothing marks them, and rule 1's "separate
    column, never blended" is a property of the WRITE, not of the reader.
    """

    def _payload(self, **kw):
        import sys as _sys
        import types as _types
        _orig = _sys.modules.get("supabase")
        if _orig is None:
            m = _types.ModuleType("supabase")
            m.create_client = lambda *a, **k: None
            m.Client = object
            _sys.modules["supabase"] = m
        try:
            from services.db import DatabaseService
        finally:
            if _orig is None:
                _sys.modules.pop("supabase", None)
        cap: dict = {}

        class _T:
            def upsert(self, payload, **_kw):
                cap.setdefault("payload", dict(payload))
                return self

            def insert(self, *_a, **_kw):
                return self

            def select(self, *_a, **_kw):
                return self

            def eq(self, *_a, **_kw):
                return self

            def is_(self, *_a, **_kw):
                return self

            def order(self, *_a, **_kw):
                return self

            def limit(self, *_a, **_kw):
                return self

            def execute(self):
                return _types.SimpleNamespace(data=[])

        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _types.SimpleNamespace(table=lambda name: _T())
        svc.upsert_state_rating(
            snippet_id="s1",
            row={"state_id": "confidence", "value": "yes",
                 "unrateable": False, "question_id": "confidence",
                 "question_version": "conf-q-v1", "saw_model_output": False,
                 "latency_ms": None, "note": None},
            rater_id="r1", session_id="sess-1", lane="game_peer", **kw)
        return cap.get("payload", {})

    def test_self_report_is_always_written(self):
        # Never omitted: an unstamped row falls back to the lane downstream,
        # which is right for the game and wrong for every other surface.
        self.assertIs(self._payload()["self_report"], False)
        self.assertIs(self._payload(self_report=True)["self_report"], True)

    def test_machine_value_is_its_own_column(self):
        payload = self._payload(machine_value="no")
        self.assertEqual(payload["machine_value"], "no")
        # Rule 1: the human answer is untouched by the proposal.
        self.assertEqual(payload["value"], "yes")
        self.assertIs(payload["confident"], True)
        # I1 stays auditable on the same row.
        self.assertIs(payload["saw_model_output"], False)

    def test_a_silent_machine_writes_no_proposal(self):
        for silent in (None, "", "unknown", "ambiguous"):
            self.assertNotIn("machine_value", self._payload(
                machine_value=silent))

    def test_the_settled_ambiguous_label_can_never_be_one_raters_answer(self):
        # 'ambiguous' is a statement about the MOMENT, derived from two
        # abstentions. It must not be storable as a proposal or an answer.
        self.assertNotIn("machine_value",
                         self._payload(machine_value=lq.AMBIGUOUS_LABEL))


class TestFences(unittest.TestCase):
    """AC-9 and BLIND COACH, at the module's edges."""

    def test_no_user_facing_copy_in_the_module(self):
        # Every string this module produces is a machine-facing status. A
        # sentence here would be product copy shipped without founder
        # sign-off (LIVE LOOP) and a verdict shown to a user (AC-9).
        for token in (lq.UNRATED, lq.SINGLETON, lq.NEEDS_THIRD, lq.QUORUM,
                      lq.PERCEPTUALLY_AMBIGUOUS, lq.AMBIGUOUS_LABEL):
            self.assertRegex(token, r"^[a-z_]+$")

    def test_resolution_carries_no_machine_read(self):
        # I1: whatever a caller does with a resolution, it cannot leak a
        # score, band or proposal into a rating payload — there is none in it.
        res = lq.resolve([_row("yes")])
        for banned in ("machine_value", "score", "band", "probe_score"):
            self.assertNotIn(banned, res)


if __name__ == "__main__":
    unittest.main()
