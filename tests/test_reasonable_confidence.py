"""The reason layer (24j) — sequenced, never blended, and never emptying a block.

Every line here is a clause of 24j made executable. The two that matter most
are the last two: the flag off must leave the served order byte-for-byte
unchanged, and an unmeasured candidate must sort last rather than be excluded,
because excluding could empty a block and 24b says every valid block yields
exactly one item.
"""
from __future__ import annotations

import ast
import importlib
import pathlib
from unittest.mock import patch

import config
from services.reasonable_confidence import (
    TIERS,
    UNMEASURED_RANK,
    enabled,
    ordering_rank,
    reason_tier,
    tier_rank,
)
from services.take_feedback_policy_v3 import _confidence_rank


def _layer(on: bool):
    """Turn the reason layer on or off for one block.

    Patches the resolved `Config` attribute rather than `os.environ`, because
    every attribute on that class resolves once at import — setting the
    variable inside a test would change nothing at all, which is the kind of
    test that passes while proving the opposite of its name.

    THE CLASS IS LOOKED UP AT CALL TIME, and that is not fussiness. Four other
    modules in this suite reload `config`, which builds a NEW class object; a
    module-level `from config import Config` here would hold the pre-reload
    one, and `enabled()` — which imports inside the function — would read the
    post-reload one. These tests passed alone and failed in the full run for
    exactly that reason. If you touch this helper, run the whole tier, not
    this file.
    """
    return patch.object(
        importlib.import_module("config").Config,
        "REASONABLE_CONFIDENCE_ENABLED", on,
    )


def _metrics(composite, degraded=False):
    return {"slide_stickiness": {"composite": composite,
                                 "on_slide": bool(composite and composite >= 0.5),
                                 "degraded": degraded}}


class TestTheVerdictIsAlreadyCategorical:
    """`on_slide_score` returns max(_STRENGTH), so the stored composite IS one
    of the three verdicts. Reading it back needs no threshold — which is why
    this change adds no tunable number anywhere."""

    def test_the_three_verdicts_round_trip(self):
        assert reason_tier(_metrics(1.0)) == ("covered", False)
        assert reason_tier(_metrics(0.5)) == ("partial", False)
        assert reason_tier(_metrics(0.0)) == ("not", False)

    def test_a_missing_read_is_an_absence_not_a_zero(self):
        # "we did not look" and "you said nothing of the point" are different
        # facts, and only one of them is a judgement.
        assert reason_tier({}) == (None, False)
        assert reason_tier({"slide_stickiness": {}}) == (None, False)
        assert reason_tier({"slide_stickiness": {"composite": None}}) == (None, False)
        assert reason_tier(None) == (None, False)

    def test_a_bool_is_not_a_composite(self):
        # `True` is an int in Python and would read as "covered" unguarded.
        assert reason_tier(_metrics(True)) == (None, False)

    def test_a_word_overlap_verdict_is_carried_as_degraded(self):
        # It still orders — a coarse read beats no read — but nothing
        # downstream may mistake it for the measured kind.
        assert reason_tier(_metrics(1.0, degraded=True)) == ("covered", True)


class TestTheTierIsTheOrdering:
    def test_stronger_verdicts_sort_first(self):
        assert tier_rank("covered") < tier_rank("partial") < tier_rank("not")

    def test_an_unmeasured_candidate_sorts_last_but_is_never_excluded(self):
        # THE 24b GUARANTEE. Excluding could empty a block; sorting last means
        # an unmeasured moment can never beat a measured one, which was the
        # actual point of the rule.
        assert tier_rank(None) == UNMEASURED_RANK
        assert tier_rank(None) > tier_rank("not")
        assert UNMEASURED_RANK == len(TIERS)

    def test_an_unknown_name_sorts_with_the_unmeasured(self):
        assert tier_rank("nonsense") == UNMEASURED_RANK


class TestTheFlagIsATrueRollback:
    def test_off_by_default(self):
        # Asserted on the DEFAULT, not on the running process: a box that
        # happens to have the variable set must not be able to turn this
        # assertion green or red.
        assert config._env_flag("REASONABLE_CONFIDENCE_ENABLED", "0") is False
        with _layer(False):
            assert enabled() is False

    def test_the_flag_is_one_name_read_in_one_place(self):
        # CONFIG-FIRST is only checkable when there is one place the code reads
        # from (audit Q-A5), and this flag decides a SELECTION that is then
        # frozen with the Take — web and worker disagreeing would freeze one
        # order and serve the other, invisibly, both answers well-formed.
        # Read from the AST, not the text, for the reason the fence itself
        # gives: a docstring that MENTIONS `os.getenv` must neither trip the
        # check nor dodge it. (This module's docstring mentions it, and the
        # first cut of this test went red on its own explanation.)
        tree = ast.parse(
            pathlib.Path("services/reasonable_confidence.py").read_text())
        reads = [
            node for node in ast.walk(tree)
            if isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name) and node.value.id == "os"
            and node.attr in ("environ", "getenv")
        ]
        assert reads == []
        assert "REASONABLE_CONFIDENCE_ENABLED = _env_flag(" in \
            pathlib.Path("config.py").read_text()

    def test_off_gives_every_candidate_the_same_leading_key(self):
        # Byte-for-byte unchanged ordering until it is turned on deliberately.
        with _layer(False):
            assert ordering_rank({"reason_tier": "covered"}) == 0
            assert ordering_rank({"reason_tier": "not"}) == 0
            assert ordering_rank({}) == 0

    def test_on_reads_the_tier(self):
        with _layer(True):
            assert ordering_rank({"reason_tier": "covered"}) == 0
            assert ordering_rank({"reason_tier": "partial"}) == 1
            assert ordering_rank({"reason_tier": "not"}) == 2
            assert ordering_rank({}) == UNMEASURED_RANK


def _cand(cid, score, tier):
    return {"candidate_id": cid, "machine_score": score,
            "reason_tier": tier, "ordinal": 0}


class TestSequencedNotBlended:
    """The product consequence, on the example that settled the design: a
    fluently delivered tangent must not beat a plainer moment that landed the
    slide's point."""

    TANGENT = _cand("tangent", 0.72, "not")
    WORKHORSE = _cand("workhorse", 0.21, "covered")

    def test_today_the_tangent_wins_on_voice_alone(self):
        with _layer(False):
            best = min([self.TANGENT, self.WORKHORSE], key=_confidence_rank)
            assert best["candidate_id"] == "tangent"

    def test_with_the_reason_layer_the_point_wins(self):
        with _layer(True):
            best = min([self.TANGENT, self.WORKHORSE], key=_confidence_rank)
            assert best["candidate_id"] == "workhorse"

    def test_the_voice_still_decides_inside_a_tier(self):
        # The delivery read is not demoted — it orders every candidate that
        # made the same verdict, which is the whole of "sequenced".
        quiet = _cand("quiet", 0.10, "covered")
        loud = _cand("loud", 0.80, "covered")
        with _layer(True):
            assert min([quiet, loud], key=_confidence_rank)["candidate_id"] == "loud"

    def test_a_block_of_nothing_on_point_still_yields_a_winner(self):
        # 24b. The bottom tier is never empty, so the block is never empty.
        nothing = [_cand("a", 0.10, "not"), _cand("b", 0.60, "not")]
        with _layer(True):
            assert min(nothing, key=_confidence_rank)["candidate_id"] == "b"

    def test_an_unmeasured_candidate_never_beats_a_measured_one(self):
        unmeasured = _cand("unmeasured", 0.95, None)
        measured = _cand("measured", 0.05, "not")
        with _layer(True):
            best = min([unmeasured, measured], key=_confidence_rank)
            assert best["candidate_id"] == "measured"

    def test_but_an_all_unmeasured_block_still_yields_one(self):
        rows = [_cand("a", 0.10, None), _cand("b", 0.60, None)]
        with _layer(True):
            assert min(rows, key=_confidence_rank)["candidate_id"] == "b"
