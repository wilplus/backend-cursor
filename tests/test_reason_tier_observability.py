"""24j card 2 — the reason-tier log, and the fence it must not cross.

`services/reasonable_confidence.py` derives `reason_tier` from true entailment
only for the LLM-budget subset; everything else gets word overlap and is
marked `degraded`. Word overlap is precisely the "keyword matching" the
product does not want to be, so the SHARE of verdicts that came from it is the
number that decides whether `REASONABLE_CONFIDENCE_ENABLED` can be turned on.
Nothing recorded it until now.

These cases hold two things at once:

  * the counts are right, including the distinction between "we did not look"
    (unmeasured) and "you said nothing of the point" ("not"), which
    `reason_tier` is careful to keep separate and a counter could easily
    collapse; and
  * AC-9 — the observation is a SIDE EFFECT ONLY. Tier names and `degraded`
    are verdicts about what the words did. They reach a server log and
    nothing else: the function returns None and leaves its input untouched,
    so it cannot become a payload key by accident later.
"""
from __future__ import annotations

import copy
import logging

from services.f1_observability import observe_reason_tiers


def _block(block_id: str, tier, degraded=False, *, selected=True):
    """One block whose selected candidate carries `tier`/`degraded`."""
    candidate = {
        "candidate_id": f"c:{block_id}",
        "reason_tier": tier,
        "reason_degraded": degraded,
    }
    return {
        "block_id": block_id,
        "selected_candidate_id": f"c:{block_id}" if selected else None,
        "confidence_candidates": [candidate],
    }


def _logged(caplog) -> str:
    lines = [r.getMessage() for r in caplog.records
             if r.getMessage().startswith("f1.reason_tiers")]
    assert len(lines) == 1, f"expected exactly one line, got {lines}"
    return lines[0]


class TestItCountsWhatActuallyWon:

    def test_each_tier_is_counted_on_the_selected_candidate(self, caplog):
        blocks = [
            _block("b1", "covered"),
            _block("b2", "partial"),
            _block("b3", "not"),
            _block("b4", "covered"),
        ]
        with caplog.at_level(logging.INFO, logger="services.f1_observability"):
            observe_reason_tiers("take-1", 2, blocks)

        line = _logged(caplog)
        assert "covered=2" in line
        assert "partial=1" in line
        assert "not=1" in line
        assert "selected=4" in line
        assert "blocks=4" in line

    def test_unmeasured_is_not_collapsed_into_not(self, caplog):
        """`reason_tier` returns None for a piece with no usable slide read —
        "we did not look". Counting that as "not" would invent a judgement,
        which is the one thing the reason layer is built not to do."""
        blocks = [_block("b1", None), _block("b2", "not")]
        with caplog.at_level(logging.INFO, logger="services.f1_observability"):
            observe_reason_tiers("take-1", 1, blocks)

        line = _logged(caplog)
        assert "unmeasured=1" in line
        assert "not=1" in line

    def test_degraded_counts_separately_from_the_tier(self, caplog):
        """A degraded verdict still HAS a tier — it is the coarse read of the
        same thing, not a fourth tier. It must be counted on both axes."""
        blocks = [
            _block("b1", "covered", degraded=True),
            _block("b2", "covered", degraded=False),
        ]
        with caplog.at_level(logging.INFO, logger="services.f1_observability"):
            observe_reason_tiers("take-1", 3, blocks)

        line = _logged(caplog)
        assert "covered=2" in line
        assert "degraded=1" in line

    def test_a_block_with_no_selection_is_counted_but_not_scored(self, caplog):
        """An empty block is a real outcome (no eligible clip lineage), so it
        shows in `blocks` but must not inflate any tier."""
        blocks = [_block("b1", "covered"), _block("b2", None, selected=False)]
        with caplog.at_level(logging.INFO, logger="services.f1_observability"):
            observe_reason_tiers("take-1", 1, blocks)

        line = _logged(caplog)
        assert "blocks=2" in line
        assert "selected=1" in line
        assert "unmeasured=0" in line

    def test_a_dangling_selection_id_scores_nothing(self, caplog):
        """`selected_candidate_id` naming a candidate that is not in the list
        is a bug upstream, not a verdict. It must not be guessed at."""
        block = _block("b1", "covered")
        block["selected_candidate_id"] = "c:missing"
        with caplog.at_level(logging.INFO, logger="services.f1_observability"):
            observe_reason_tiers("take-1", 1, [block])

        line = _logged(caplog)
        assert "selected=0" in line
        assert "covered=0" in line


class TestItIsObservationOnly:
    """AC-9 and the live loop: this may never change what a caller returns."""

    def test_it_returns_none(self):
        assert observe_reason_tiers("t", 1, [_block("b1", "covered")]) is None

    def test_it_does_not_mutate_the_blocks(self):
        """If it never writes, a tier name cannot ride out on the frame."""
        blocks = [_block("b1", "covered", degraded=True), _block("b2", None)]
        before = copy.deepcopy(blocks)
        observe_reason_tiers("take-1", 1, blocks)
        assert blocks == before

    def test_garbage_never_raises(self):
        """The policy's hot path must not fail because observability did."""
        for bad in (None, "not a list", 17, [None], ["x"], [{}],
                    [{"selected_candidate_id": "c", "confidence_candidates": 3}]):
            assert observe_reason_tiers("t", 1, bad) is None

    def test_a_weird_tier_name_lands_in_unmeasured(self, caplog):
        """An unknown tier must not raise a KeyError inside the hot path, and
        must not be silently counted as a real verdict either."""
        with caplog.at_level(logging.INFO, logger="services.f1_observability"):
            observe_reason_tiers("t", 1, [_block("b1", "brand_new_tier")])

        line = _logged(caplog)
        assert "unmeasured=1" in line
