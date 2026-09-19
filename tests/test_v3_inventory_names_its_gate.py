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

    def test_an_unreadable_block_carries_its_position(self):
        # The position is what makes the log actionable: with ten blocks,
        # "one of them was malformed" is not a finding.
        #
        # EXCLUDED, NOT FATAL (founder 2026-09-19). This block contributes
        # nothing and the pass carries on; the Take then declines only
        # because nothing provable survived it, which is a different and
        # honest reason.
        out, detail = _prepare(
            {**VALID_FRAME, "blocks": [{"block_id": "b1"}]}, VALID_DOC,
        )
        assert out is None
        assert detail[:2] == [
            "block_slide_index_not_an_int:None",
            "confidence_block_excluded:1",
        ]
        assert detail[-1].startswith("inventory_incomplete:")


class TestTheChainReadsInsideOut:
    """The condition, then where it was, then which gate it closed.

    `detail=confidence_block_rejected:1` located a block and then stopped
    being useful, because the check under it has ten conditions sharing two
    silent exits. Production needed a second round trip to get past it, which
    is the cost this whole mechanism exists to avoid.
    """

    def test_a_malformed_candidate_names_the_condition_and_its_position(self):
        out, detail = _prepare(
            {**VALID_FRAME, "blocks": [
                {"block_id": "b1", "slide_index": 0,
                 "confidence_candidates": [{}]},
            ]},
            VALID_DOC,
        )
        assert out is None
        assert detail[:2] == ["no_candidate_id", "excluded_candidate:1"]
        # ONE UNPROVABLE ROW NO LONGER SILENCES THE TAKE (founder
        # 2026-09-19). It used to read `at_candidate:1;
        # confidence_block_rejected:1` and abort the whole inventory, so a
        # single Paragraph that could not be placed cost every other slide
        # its item. The row is still never served -- the safety property is
        # untouched -- and the Take declines here only because this was the
        # ONLY candidate, leaving nothing provable behind.
        assert detail[-1].startswith("inventory_incomplete:")
        assert not any(d.startswith("confidence_block_rejected") for d in detail)

    def test_a_provable_row_survives_an_unprovable_one_beside_it(self):
        # The whole point of the change, asserted where it can fail: a block
        # holding one bad candidate and one good one must still yield the
        # good one rather than nothing at all.
        document = {
            **VALID_DOC,
            "pieces": [{
                "snippet_id": "s1", "part_id": "p1",
                "recording_id": "rec-A", "start_offset_ms": 0,
                "duration_ms": 1000,
            }],
        }
        good = {
            "candidate_id": "c-good", "snippet_id": "s1",
            "eligibility": "eligible",
            "document_span": {"start": 0, "end": 4},
            "clip_identity": {
                "recording_id": "rec-A", "start_offset_ms": 0,
                "duration_ms": 1000,
            },
        }
        out, detail = _prepare(
            {**VALID_FRAME,
             "selected_confidence": [
                 {"candidate_id": "c-good", "block_id": "b1"},
             ],
             "blocks": [
                 {"block_id": "b1", "slide_index": 0,
                  "confidence_candidates": [{}, good]},
             ]},
            document,
        )
        assert "no_candidate_id" in detail
        assert "excluded_candidate:1" in detail
        # The good row reached the inventory rather than dying beside it.
        assert out is not None
        assert [row["id"] for row in out["visible_rows"]] == ["c-good"]

    def test_a_snippet_the_document_does_not_have(self):
        # The likeliest real fault: a candidate cites a snippet id that is not
        # among the document's pieces, so its lineage can never be checked.
        out, detail = _prepare(
            {**VALID_FRAME, "blocks": [
                {"block_id": "b1", "slide_index": 0, "confidence_candidates": [
                    {"candidate_id": "c1", "snippet_id": "missing-snippet"},
                ]},
            ]},
            VALID_DOC,
        )
        assert out is None
        assert detail[0] == "snippet_not_in_document:missing-snippet"

    def test_a_lineage_mismatch_carries_both_sides(self):
        # A mismatch is only actionable if the log says what disagreed with
        # what. One value alone cannot be compared to anything.
        document = {
            **VALID_DOC,
            "pieces": [{
                "snippet_id": "s1", "part_id": "p1",
                "recording_id": "rec-A", "start_offset_ms": 0,
                "duration_ms": 1000,
            }],
        }
        out, detail = _prepare(
            {**VALID_FRAME, "blocks": [
                {"block_id": "b1", "slide_index": 0, "confidence_candidates": [
                    {
                        "candidate_id": "c1", "snippet_id": "s1",
                        "eligibility": "eligible",
                        "document_span": {"start": 0, "end": 4},
                        "clip_identity": {
                            "recording_id": "rec-B", "start_offset_ms": 0,
                            "duration_ms": 1000,
                        },
                    },
                ]},
            ]},
            document,
        )
        assert out is None
        assert detail[0] == (
            "recording_id_mismatch:piece='rec-A',clip='rec-B'"
        )

    def test_an_empty_block_is_named_but_is_not_itself_a_rejection(self):
        # A partition that produced no candidate at all is a different fault
        # from one whose candidate was malformed, and downstream they look
        # identical. It is reported without failing the block.
        out, detail = _prepare(
            {**VALID_FRAME, "blocks": [{"block_id": "b1", "slide_index": 0}]},
            VALID_DOC,
        )
        assert out is None  # still fails later, on the verbal lanes
        assert "block_has_no_candidates:b1" in detail
        assert not any(d.startswith("confidence_block_rejected") for d in detail)


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
