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
  RULE 4  "Not sure" is retained as rater uncertainty and routes a third
          person, but can never settle confidence ground truth. Audio unclear
          is a technical non-response and no confidence vote at all.

Pure, no DB. Run: python3 -m unittest test_label_quorum
"""
from __future__ import annotations

import unittest
from pathlib import Path

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
        self.assertEqual(lq.machine_proposal(snip("neutral")), "in_between")
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

    def test_blind_coach_and_blind_peer_share_one_human_quorum(self):
        # Provenance remains distinct on the rows, but both are independent
        # blind human judgments and therefore belong to the same panel.
        res = lq.resolve([
            _row("in_between", lane="coach", rater="coach-a"),
            _row("in_between", lane="game_peer", rater="peer-b"),
        ])
        self.assertEqual(res["status"], lq.QUORUM)
        self.assertEqual(res["value"], "in_between")
        self.assertEqual(res["n_responses"], 2)
        self.assertEqual(res["n_lane_excluded"], 0)

    def test_contextual_and_import_lanes_cannot_join_the_blind_panel(self):
        res = lq.resolve([
            _row("yes", lane="game_peer", rater="peer-a"),
            _row("yes", lane="bootstrap", rater="import-b"),
            _row("yes", lane="contextual_coach", rater="coach-c"),
        ])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertEqual(res["n_responses"], 1)
        self.assertEqual(res["n_lane_excluded"], 2)

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
        # An IDK ('neutral' — "ambiguous to judge", founder 2026-08-14) has
        # not disagreed with anything; it is the DEFINITE mismatch that
        # carries the active-learning information.
        res = lq.resolve([_row("not_sure")])
        self.assertEqual(res["status"], lq.SINGLETON)
        self.assertFalse(lq.machine_disagrees(res, "yes"))

    def test_a_machine_neutral_cannot_be_definitely_contradicted(self):
        # The machine's own ambiguous read is not a definite opinion — a
        # lone human 'yes' against it routes as an ordinary singleton, not
        # as rule 3's model-miss-or-rater-miss alarm.
        res = lq.resolve([_row("yes")])
        self.assertFalse(lq.machine_disagrees(res, "in_between"))
        self.assertEqual(lq.routing_priority(res, "in_between"), lq.P_SINGLETON)


class TestRule4NotSureRoutesButNeverSettles(unittest.TestCase):
    """IDK is auditable routing evidence, never a confidence label."""

    def test_case_b_one_definite_plus_one_idk_needs_a_third(self):
        res = lq.resolve([_row("yes"), _row("not_sure", rater="b")])
        self.assertEqual(res["status"], lq.NEEDS_THIRD)
        self.assertFalse(res["settled"])
        self.assertIsNone(res["value"])
        self.assertTrue(res["needs_rater"])
        self.assertEqual(res["next_rater_ordinal"], 3)
        self.assertEqual(lq.routing_priority(res), lq.P_NEEDS_THIRD)

    def test_two_idks_also_require_a_third(self):
        res = lq.resolve([_row("not_sure", rater="a"),
                          _row("not_sure", rater="b")])
        self.assertEqual(res["status"], lq.NEEDS_THIRD)
        self.assertIsNone(res["value"])
        self.assertFalse(res["settled"])
        self.assertFalse(res["gold_eligible"])
        self.assertTrue(res["needs_rater"])
        self.assertEqual(res["next_rater_ordinal"], 3)

    def test_not_sure_never_becomes_the_settled_value(self):
        res = lq.resolve([_row("not_sure", rater="a"),
                          _row("not_sure", rater="b"),
                          _row("not_sure", rater="c")])
        self.assertEqual(res["status"], lq.UNRESOLVED)
        self.assertIsNone(res["value"])
        self.assertFalse(res["gold_eligible"])

    def test_idk_is_counted_not_dropped(self):
        res = lq.resolve([_row("yes"), _row("not_sure", rater="b")])
        self.assertEqual(res["n_responses"], 2)
        self.assertEqual(res["n_idk"], 1)
        self.assertEqual(res["n_definite"], 1)

    def test_not_sure_is_the_v2_idk(self):
        res = lq.resolve([_row("neutral", rater="a"),
                          _row("neutral", rater="b")])
        self.assertEqual(res["status"], lq.NEEDS_THIRD)
        self.assertEqual(res["n_idk"], 2)

        current = lq.resolve([_row("not_sure", rater="a"),
                              _row("not_sure", rater="b")])
        self.assertEqual(current["status"], lq.NEEDS_THIRD)
        self.assertEqual(current["n_idk"], 2)

    def test_in_between_can_reach_its_own_quorum(self):
        res = lq.resolve([_row("in_between", rater="a"),
                          _row("in_between", rater="b")])
        self.assertEqual(res["status"], lq.QUORUM)
        self.assertEqual(res["value"], "in_between")

    def test_one_unclear_audio_routes_once_to_a_fresh_rater(self):
        # The ruling's other half: an unrateable row is a failure of the
        # ARTIFACT ("I can't hear the clip"), not a reading of the voice.
        # It contributes no confidence answer, but it does trigger one retry.
        res = lq.resolve([_row("audio_unclear", rater="a")])
        self.assertEqual(res["status"], lq.AUDIO_RETRY)
        self.assertEqual(res["n_responses"], 0)
        self.assertEqual(res["n_audio_unclear"], 1)
        self.assertTrue(res["needs_rater"])
        self.assertEqual(res["next_rater_ordinal"], 2)
        self.assertFalse(res["gold_eligible"])

    def test_two_independent_unclear_reports_quarantine_the_clip(self):
        # The explicit v2 answer and legacy flag are the same technical
        # signal. Two independent reports stop routing and keep the artifact
        # out of all training/evaluation sets.
        res = lq.resolve([_row("audio_unclear", rater="a"),
                          _row(None, unrateable=True, rater="b")])
        self.assertEqual(res["status"], lq.AUDIO_QUARANTINED)
        self.assertEqual(res["n_responses"], 0)
        self.assertEqual(res["n_audio_unclear"], 2)
        self.assertFalse(res["needs_rater"])
        self.assertIsNone(res["next_rater_ordinal"])
        self.assertFalse(res["gold_eligible"])
        self.assertFalse(res["eval_eligible"])
        self.assertFalse(res["weak_supervision_only"])

    def test_unclear_flag_voids_a_value_and_is_counted_only_once(self):
        # The flag voids even a definite value on the same row — the rater
        # said the audio itself was unjudgeable.
        res = lq.resolve([_row("audio_unclear", unrateable=True)])
        self.assertEqual(res["status"], lq.AUDIO_RETRY)
        self.assertEqual(res["n_audio_unclear"], 1)

    def test_non_panel_and_self_report_unclear_do_not_quarantine(self):
        res = lq.resolve([
            _row("audio_unclear", rater="owner", self_report=True),
            _row("audio_unclear", rater="import", lane="bootstrap"),
        ])
        self.assertEqual(res["status"], lq.UNRATED)
        self.assertEqual(res["n_audio_unclear"], 0)
        self.assertEqual(res["n_self_report"], 1)
        self.assertEqual(res["n_lane_excluded"], 1)

    def test_idk_can_be_outvoted(self):
        res = lq.resolve([_row("yes", rater="a"), _row("yes", rater="b"),
                          _row("not_sure", rater="c")])
        self.assertEqual(res["status"], lq.QUORUM)
        self.assertEqual(res["value"], "yes")

    def test_idk_majority_after_three_is_quarantined_not_gold(self):
        res = lq.resolve([_row("yes", rater="a"),
                          _row("not_sure", rater="b"),
                          _row("not_sure", rater="c")])
        self.assertEqual(res["status"], lq.UNRESOLVED)
        self.assertFalse(res["needs_rater"])
        self.assertIsNone(res["next_rater_ordinal"])


class TestTheOneRule(unittest.TestCase):
    """The truth table itself — the four cases fall out of one rule, and the
    SQL view (migrations/add_label_quorum_ledger.sql) computes the same one."""

    def test_truth_table(self):
        cases = [
            ([], lq.UNRATED, None),
            ([_row("yes")], lq.SINGLETON, None),
            ([_row("not_sure")], lq.SINGLETON, None),
            # A first technical report routes exactly one retry.
            ([_row(None, unrateable=True)], lq.AUDIO_RETRY, None),
            # A second independent report quarantines the artifact.
            ([_row(None, unrateable=True, rater="a"),
              _row("audio_unclear", rater="b")],
             lq.AUDIO_QUARANTINED, None),
            ([_row("yes", rater="a"), _row("yes", rater="b")],
             lq.QUORUM, "yes"),
            ([_row("no", rater="a"), _row("no", rater="b")], lq.QUORUM, "no"),
            ([_row("not_sure", rater="a"), _row("not_sure", rater="b")],
             lq.NEEDS_THIRD, None),
            ([_row("yes"), _row("not_sure", rater="b")],
             lq.NEEDS_THIRD, None),
            ([_row("yes", rater="a"), _row("no", rater="b")],
             lq.NEEDS_THIRD, None),
            ([_row("yes", rater="a"), _row("no", rater="b"),
              _row("not_sure", rater="c")], lq.UNRESOLVED, None),
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
        for status in (lq.UNRATED, lq.SINGLETON, lq.NEEDS_THIRD,
                       lq.UNRESOLVED, lq.AUDIO_RETRY,
                       lq.AUDIO_QUARANTINED):
            self.assertNotIn(status, lq.SETTLED_STATUSES)
        self.assertEqual(lq.SETTLED_STATUSES, (lq.QUORUM,))

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
                                       _row("not_sure", rater="b")])},
            {"snippet_id": "s-agrees",
             "resolution": lq.resolve([_row("yes")]),
             "machine_value": "yes"},
            {"snippet_id": "s-disagrees",
             "resolution": lq.resolve([_row("no")]),
             "machine_value": "yes"},
            {"snippet_id": "s-audio-retry",
             "resolution": lq.resolve([_row("audio_unclear")])},
            {"snippet_id": "s-audio-quarantined",
             "resolution": lq.resolve([
                 _row("audio_unclear", rater="a"),
                 _row("audio_unclear", rater="b"),
             ])},
        ]
        ordered = [it["snippet_id"] for it in lq.rating_queue(items)]
        self.assertEqual(
            ordered, ["s-disagrees", "s-third", "s-audio-retry",
                      "s-agrees", "s-unrated"])
        self.assertNotIn("s-settled", ordered)
        self.assertNotIn("s-audio-quarantined", ordered)

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


class TestRaterSubmissionAccess(unittest.TestCase):
    """Assignment remains fresh across an unclear-audio retry."""

    def test_first_unclear_rater_cannot_retry_their_own_clip(self):
        rows = [_row("audio_unclear", rater="rater-a")]
        mine = lq.rater_submission_access(rows, "rater-a")
        self.assertFalse(mine["allowed"])
        self.assertEqual(mine["outcome"], "fresh_rater_required")

        fresh = lq.rater_submission_access(rows, "rater-b")
        self.assertTrue(fresh["allowed"])
        self.assertEqual(fresh["outcome"], "new")
        self.assertEqual(fresh["resolution"]["status"], lq.AUDIO_RETRY)

    def test_two_unclear_reports_close_the_artifact_for_everyone(self):
        rows = [
            _row("audio_unclear", rater="rater-a"),
            _row("audio_unclear", rater="rater-b"),
        ]
        for rater in ("rater-a", "rater-b", "rater-c"):
            access = lq.rater_submission_access(rows, rater)
            self.assertFalse(access["allowed"])
            self.assertEqual(access["outcome"], "audio_quarantined")

    def test_fresh_rater_cannot_add_a_vote_after_resolution(self):
        rows = [_row("yes", rater="a"), _row("yes", rater="b")]
        access = lq.rater_submission_access(rows, "c")
        self.assertFalse(access["allowed"])
        self.assertEqual(access["outcome"], "closed")

    def test_existing_perceptual_rater_keeps_revision_policy(self):
        rows = [_row("no", rater="a")]
        access = lq.rater_submission_access(rows, "a")
        self.assertTrue(access["allowed"])
        self.assertEqual(access["outcome"], "update")


class TestCorpusLedger(unittest.TestCase):
    """The dial: rows are not ground truth, settled snippets are."""

    def test_gold_counts_only_settled_snippets(self):
        resolutions = [
            lq.resolve([_row("yes", rater="a"), _row("yes", rater="b")]),
            lq.resolve([_row("neutral", rater="a"),
                        _row("neutral", rater="b"),
                        _row("neutral", rater="c")]),
            lq.resolve([_row("yes")]),
            lq.resolve([_row("yes"), _row("no", rater="b")]),
            lq.resolve([_row("yes", self_report=True)]),
            lq.resolve([_row("audio_unclear", rater="a")]),
            lq.resolve([_row("audio_unclear", rater="a"),
                        _row("audio_unclear", rater="b")]),
        ]
        led = lq.corpus_ledger(resolutions)
        self.assertEqual(led["snippets"], 7)
        self.assertEqual(led["gold"], 1)
        self.assertEqual(led["unresolved"], 1)
        self.assertEqual(led["weak"], 1)
        self.assertEqual(led["blocked"], 1)
        self.assertEqual(led["self_reports_excluded"], 1)
        self.assertEqual(led["audio_retry"], 1)
        self.assertEqual(led["audio_quarantined"], 1)
        self.assertEqual(led["gold_share"], 0.143)
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

class TestFences(unittest.TestCase):
    """AC-9 and BLIND COACH, at the module's edges."""

    def test_no_user_facing_copy_in_the_module(self):
        # Every string this module produces is a machine-facing status. A
        # sentence here would be product copy shipped without founder
        # sign-off (LIVE LOOP) and a verdict shown to a user (AC-9).
        for token in (lq.UNRATED, lq.SINGLETON, lq.NEEDS_THIRD,
                      lq.UNRESOLVED, lq.AUDIO_RETRY,
                      lq.AUDIO_QUARANTINED, lq.QUORUM):
            self.assertRegex(token, r"^[a-z_]+$")

    def test_resolution_carries_no_machine_read(self):
        # I1: whatever a caller does with a resolution, it cannot leak a
        # score, band or proposal into a rating payload — there is none in it.
        res = lq.resolve([_row("yes")])
        for banned in ("machine_value", "score", "band", "probe_score"):
            self.assertNotIn(banned, res)


class TestSqlMirror(unittest.TestCase):
    """The persisted ledger must expose the same technical-audio states."""

    def test_v2_view_mirrors_retry_and_quarantine(self):
        sql = (Path(__file__).parent / "migrations" /
               "version_confidence_rating_instrument_v2.sql").read_text()
        for token in ("audio_retry", "audio_quarantined",
                      "n_audio_unclear", "value = 'audio_unclear'"):
            self.assertIn(token, sql)


if __name__ == "__main__":
    unittest.main()
