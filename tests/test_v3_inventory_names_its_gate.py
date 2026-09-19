"""Six fail-closed gates, one reason, and now a name for which one closed.

2026-09-19. A V3 stand-down reported to the client as
``source_snapshot_rpc_failed`` took four database queries and a live RPC call
to identify, because the reason named the CALL that failed and not the check
inside it. Fixing that moved the failure one step along, to
``service_inventory_unavailable`` — a single reason shared by six separate
``return None`` exits in ``prepare_v3_service_inventory``, every one of them
silent.

Fail-closed is correct and stays. Fail-silent is a missing log line, and it is
the reason a broken Confident Voice lane can sit in production for weeks
looking exactly like a lane with nothing to say.

``detail`` is log-only. AC-9: why a Take produced no Confident Voice item is
not something a user may be shown.
"""
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory


def _prepare(frame, document, candidates=()):
    detail: list[str] = []
    out = prepare_v3_service_inventory(
        frame=frame, take_document=document,
        feedback_candidates=candidates, detail=detail,
    )
    return out, detail


VALID_FRAME = {
    "policy_version": "take-feedback-policy-v3-serving-v1",
    "take_id": "take-1",
}
VALID_DOC = {"text": "some words", "take_session_id": "take-1"}


class TestTheGateNamesItself:
    def test_an_invalid_policy_frame(self):
        out, detail = _prepare({"policy_version": "nope"}, VALID_DOC)
        assert out is None
        assert detail == ["policy_frame_invalid"]

    def test_a_frame_whose_take_does_not_match_the_document(self):
        # The lineage check, which is the one that silently disagrees rather
        # than erroring — a mismatched take is a different recording.
        out, detail = _prepare(
            VALID_FRAME, {"text": "words", "take_session_id": "take-2"},
        )
        assert out is None
        assert detail == ["policy_frame_invalid"]

    def test_no_blocks(self):
        out, detail = _prepare({**VALID_FRAME, "blocks": []}, VALID_DOC)
        assert out is None
        assert detail == ["no_blocks_in_policy"]

    def test_blocks_that_are_not_a_list(self):
        out, detail = _prepare({**VALID_FRAME, "blocks": {}}, VALID_DOC)
        assert out is None
        assert detail == ["no_blocks_in_policy"]

    def test_a_rejected_confidence_block_carries_its_position(self):
        # The position is what makes the log actionable: with ten blocks,
        # "one of them was malformed" is not a finding.
        out, detail = _prepare(
            {**VALID_FRAME, "blocks": [{"block_id": "b1"}]}, VALID_DOC,
        )
        assert out is None
        assert detail == ["confidence_block_rejected:1"]


class TestItStaysOptional:
    def test_omitting_detail_changes_nothing(self):
        # One production caller passes it; the tests that predate this do not,
        # and a diagnostic that breaks its callers is not worth having.
        assert prepare_v3_service_inventory(
            frame={"policy_version": "nope"}, take_document=VALID_DOC,
            feedback_candidates=(),
        ) is None

    def test_a_gate_appends_exactly_one_entry(self):
        # Not a running log across calls: one decline, one cause.
        detail: list[str] = []
        for _ in range(3):
            detail.clear()
            prepare_v3_service_inventory(
                frame={"policy_version": "nope"}, take_document=VALID_DOC,
                feedback_candidates=(), detail=detail,
            )
            assert len(detail) == 1
