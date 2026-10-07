"""D-ML-3: the rewrite lane fills.

Contract 24f, 25, 27, 29b; ledger A059a / A066. The model's own clearer
versions (`moment_suggestions`, the replace kind) reached the Manager with no
`_manager_evidence` and no generator version, so V3 excluded every one
(`missing_evidence_metadata`) and the rewrite lane was one structural rule
plus a tentative fallback. Each clearer version now carries the weak read
that made the generator write it, named by a reason from a fixed, versioned
list, and the generator version this reader vouches for.

What does NOT change: V3 still anchors at most one rewrite per block read
weak, only where its words are this Take's (L2); a lane with nothing
defensible stays an honest `no_defensible_candidate` (contract 25); the
evidence never leaves the server (AC-9); and no user-facing word is added.
"""
from __future__ import annotations

import logging

from services.intervention_candidates import feedback_family_of
from services.take_feedback_manager import (
    exposure_snapshot,
    strip_internal_evidence,
    verbal_exclusion,
)
from services.take_feedback_policy_v3 import (
    NO_DEFENSIBLE_CANDIDATE,
    build_service_candidate_frame,
)
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory
from services.tracked_changes import (
    CLEARER_VERSION_GENERATOR_VERSION,
    CLEARER_VERSION_REASONS,
    CLEARER_VERSION_REASONS_VERSION,
)
from tests.test_verbal_lanes_take_document_n48_1 import (
    RECORDING,
    SERVED,
    SPOKEN,
    _block_of,
    _frame,
    _lane,
    _map,
    _placed_document,
    _snippets,
    _tracked,
)

CLEARER = "We give every learner one short daily task."


def _clearer(trigger: str = "unconfident", sid: str = "s1b",
             replacement: str = CLEARER) -> dict:
    """The served row for one model clearer version, as the read path
    builds it (`build_tracked_changes`, then the family)."""
    [row] = _tracked({"kind": "replace", "trigger": trigger,
                      "replacement_text": replacement,
                      "why": "model prose the client never renders"}, sid)
    row["feedback_family"] = feedback_family_of(row)
    return row


def _bare(row: dict) -> dict:
    """The same row as it reached the Manager before D-ML-3."""
    return {key: value for key, value in row.items()
            if key not in ("_manager_evidence", "suggestion_version")}


class TestAClearerVersionCarriesItsEvidence:
    def test_the_weak_read_a_reason_and_the_generator_version(self):
        row = _clearer("unconfident")
        assert row["feedback_family"] == "rewrite_clarity"
        assert row["suggestion_version"] == CLEARER_VERSION_GENERATOR_VERSION
        assert row["_manager_evidence"] == {
            "detector": "clearer_version", "read": "weak",
            "basis": "weak_delivery_read",
            "reasons_version": CLEARER_VERSION_REASONS_VERSION,
            "fallback": False}

    def test_every_reason_comes_from_the_fixed_list(self):
        for trigger, reason in CLEARER_VERSION_REASONS.items():
            row = _clearer(trigger)
            assert row["_manager_evidence"]["basis"] == reason
        assert set(CLEARER_VERSION_REASONS) == {
            "unconfident", "stickiness", "profanity"}

    def test_any_other_trigger_carries_nothing(self):
        for trigger in ("polish", "acoustic_swap", "something_new", ""):
            row = _clearer(trigger)
            assert "_manager_evidence" not in row
            assert "suggestion_version" not in row
            assert verbal_exclusion(row, _map())[0] == \
                "missing_evidence_metadata"

    def test_nothing_is_measured_that_was_not(self):
        # No specificity and no rank: a structural repair still outranks a
        # clearer version inside the same block.
        evidence = _clearer()["_manager_evidence"]
        assert "specificity" not in evidence
        assert "detector_rank" not in evidence

    def test_verbal_exclusion_now_admits_it(self):
        assert verbal_exclusion(_bare(_clearer()), _map())[0] == \
            "missing_evidence_metadata"
        reason, span = verbal_exclusion(_clearer(), _map())
        assert reason is None and span is not None

    def test_the_evidence_and_version_never_ride_the_payload(self):
        [visible] = strip_internal_evidence([_clearer()])
        assert not any(key.startswith("_manager") for key in visible)
        assert "suggestion_version" not in visible
        assert visible["proposed_text"] == CLEARER
        # No new words for the speaker: the same copy key as before.
        assert visible["why_key"] == "clarity"


class TestAWeakBlockWithAClearerVersionServesOne:
    def test_the_weak_block_carries_the_clearer_version(self):
        frame = _frame([_clearer()])
        weak = _block_of(frame, 1)
        assert weak["delivery_band"] == "delivery_signal_low"
        lane = _lane(frame, "rewrite_clarity")
        assert lane["anchors"] == [
            {"block_id": weak["block_id"], "candidate_id": "s1b"}]
        assert lane["outcome"] == "selected"

    def test_before_the_lane_was_an_honest_empty(self):
        frame = _frame([_bare(_clearer())])
        lane = _lane(frame, "rewrite_clarity")
        assert lane["anchors"] == []
        assert lane["outcome"] == NO_DEFENSIBLE_CANDIDATE
        [item] = lane["candidates"]
        assert item["exclusion_reason"] == "missing_evidence_metadata"

    def test_at_most_one_per_weak_block(self):
        rows = [_clearer(sid="s1a",
                         replacement="Our second idea is simple."),
                _clearer(sid="s1b")]
        frame = _frame(rows)
        anchors = _lane(frame, "rewrite_clarity")["anchors"]
        assert len(anchors) == 1
        assert anchors[0]["block_id"] == _block_of(frame, 1)["block_id"]

    def test_a_confident_block_carries_none(self):
        # Slide 2 reads confident: its follow-up is praise, never a rewrite.
        frame = _frame([_clearer(sid="s2b",
                                 replacement="Every group read better.")])
        assert _block_of(frame, 2)["delivery_band"] == "delivery_signal_high"
        lane = _lane(frame, "rewrite_clarity")
        assert lane["anchors"] == []
        assert lane["outcome"] == NO_DEFENSIBLE_CANDIDATE

    def test_the_service_serves_it_manager_gated(self):
        pool = exposure_snapshot([_clearer()])
        document = _placed_document(parts=True)
        frame = build_service_candidate_frame(
            take_document=document, snippets=_snippets(), suggestions={},
            feedback_candidates=pool, take_index=2,
            expected_recording_id=RECORDING, served_text=SERVED)
        inventory = prepare_v3_service_inventory(
            frame=frame, take_document=document, served_text=SERVED,
            feedback_candidates=pool)
        assert inventory is not None
        rewrites = [row for row in inventory["visible_rows"]
                    if row["feedback_family"] == "rewrite_clarity"]
        assert [row["proposed_text"] for row in rewrites] == [CLEARER]
        assert rewrites[0]["quote"] == SPOKEN[1][2]


def _share(caplog, rows) -> tuple[int, int]:
    """(weak blocks carrying a clearer version, weak blocks), read from the
    V3 lane log line."""
    caplog.clear()
    with caplog.at_level(logging.INFO,
                         logger="services.take_feedback_policy_v3"):
        _frame(rows)
    [line] = [r.getMessage() for r in caplog.records
              if r.getMessage().startswith("v3 lanes ")]
    # "v3 lanes take=T rewrite candidates=N selected=N weak_blocks=N ..."
    selected = int(line.split("selected=")[1].split()[0])
    weak = int(line.split("weak_blocks=")[1].split()[0])
    return selected, weak


def test_the_fixture_take_logs_the_share_before_and_after(caplog):
    clearer = [_clearer(sid="s1a", replacement="Our second idea is simple."),
               _clearer(sid="s1b")]
    before = _share(caplog, [_bare(row) for row in clearer])
    after = _share(caplog, clearer)
    logging.getLogger(__name__).info(
        "D-ML-3 fixture Take: weak blocks with a clearer version "
        "before=%d/%d after=%d/%d", *before, *after)
    assert before == (0, 1)
    assert after == (1, 1)


def test_an_honest_empty_lane_is_still_named():
    lane = _lane(_frame([]), "rewrite_clarity")
    assert lane["anchors"] == []
    assert lane["outcome"] == NO_DEFENSIBLE_CANDIDATE
    assert [row["reason"] for row in lane["blocks_without_note"]] == [
        NO_DEFENSIBLE_CANDIDATE]
