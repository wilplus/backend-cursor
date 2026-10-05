"""Contract 24b: a block's Confident Voice item is one the serve path can prove.

THE DEFECT (audit, 2026-10-05). The frame chose each block's item by rank
alone, and only afterwards did the serve path try to prove that item's
Paragraph and served span (`take_feedback_policy_v3_service._row_rejection`).
A winner it could not prove was dropped there, and the block came out EMPTY,
although a lower-ranked clip in the same block could have been served. On the
base commit (f43aa885) the two tests that open the 24b section below fail
exactly that way: slide 1's block selects the unprovable clip, the serve path
rejects it with `piece_has_no_part_id`, and only slide 0 serves an item.

THE TAKE BELOW IS PRODUCTION'S SHAPE, bound by the live binding
(`bind_pieces_to_parts`), nothing hand-fitted. Slide 1 holds two Paragraphs.
Its strongest clip was rewritten in the Ideal Text, so the relocation routes
it to the whole slide region, which straddles both Paragraphs: no Paragraph
is provable for it, and the binding (rightly) guesses none. A weaker clip on
the same slide survives verbatim inside the second Paragraph and is provable.
"""
from __future__ import annotations

import json
from hashlib import sha256

import pytest

import services.take_feedback_policy_v3 as policy
import services.take_feedback_policy_v3_service as service
from services.ideal_text_parts import bind_pieces_to_parts
from services.take_feedback_policy_v3 import (
    UNSERVABLE_PARAGRAPH,
    UNSERVABLE_SPAN,
    build_service_candidate_frame,
    build_shadow_frame,
    unservable,
)
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory

OWNER = "9f4e75b8-268b-468d-9111-000000000002"
USER = "22222222-3333-4444-8555-666666666667"
PROJECT = "11111111-2222-4333-8444-555555555556"
TAKE = "8875d24c-a7c6-4881-88eb-e46fcb3b4178"
RECORDING = "44444444-5555-4666-8777-888888888889"
SNAPSHOT = "33333333-4444-4555-8666-777777777778"
MEMBERSHIP = "55555555-6666-4777-8888-999999999990"

S0A = "a0000000-0000-4000-8000-0000000000a0"
S0B = "a0000000-0000-4000-8000-0000000000b0"
S1A = "a0000000-0000-4000-8000-0000000000a1"
S1B = "a0000000-0000-4000-8000-0000000000b1"

P0 = "b0000000-0000-4000-8000-000000000000"
P1 = "b0000000-0000-4000-8000-000000000001"
P2 = "b0000000-0000-4000-8000-000000000002"

# ── The Ideal Text on screen: one Paragraph on slide 0, two on slide 1 ──
SLIDE_0 = ("Our team started this project after visiting classrooms. "
           "Every one of them was missing the same simple thing.")
SLIDE_1_FIRST = "What matters most is how we listen before we teach."
SLIDE_1_SECOND = "So each lesson now starts with one short question."

# ── What was said: (snippet, slide, words, delivery score) ──
SPOKEN = [
    (S0A, 0, "Our team started this project after visiting classrooms.", 0.5),
    (S0B, 0, "Every one of them was missing the same simple thing.", 0.2),
    # The block's BEST clip. Rewritten in the Ideal Text: not one run of
    # these words is on screen, so its Paragraph cannot be proven.
    (S1A, 1, "honestly what matters most to us is the way we listen to "
             "every student before we teach", 0.8),
    # A WEAKER clip in the same block, verbatim inside SLIDE_1_SECOND.
    (S1B, 1, "each lesson now starts with one short question.", 0.3),
]


def ideal(second: str = SLIDE_1_SECOND) -> tuple[str, list, dict]:
    """The served text, its Paragraphs and its slide regions."""
    served = "\n\n".join([SLIDE_0, SLIDE_1_FIRST, second])
    parts = [
        {"id": P0, "text": SLIDE_0, "ord": 0},
        {"id": P1, "text": SLIDE_1_FIRST, "ord": 1},
        {"id": P2, "text": second, "ord": 2},
    ]
    return served, parts, {0: (0, len(SLIDE_0)),
                           1: (len(SLIDE_0) + 2, len(served))}


SERVED, PARTS, REGIONS = ideal()


def _transcript_document() -> dict:
    """The shape `build_transcript_document` returns (no `part_id`)."""
    text, pieces, paragraphs = "", [], []
    for index, (sid, slide, words, _score) in enumerate(SPOKEN):
        if index:
            text += " " if SPOKEN[index - 1][1] == slide else "\n\n"
        start = len(text)
        text += words
        pieces.append({
            "snippet_id": sid, "recording_id": RECORDING,
            "audio_ref": "https://audio.invalid/take.webm",
            "take_session_id": TAKE, "take_index": 1,
            "start": start, "end": len(text), "text": words,
            "slide_index": slide,
            "start_offset_ms": 1000 * index, "duration_ms": 900,
        })
    for slide in (0, 1):
        own = [p for p in pieces if p["slide_index"] == slide]
        paragraphs.append({
            "slide_index": slide, "snippet_id": own[0]["snippet_id"],
            "take_session_id": TAKE, "take_index": 1,
            "start": own[0]["start"], "end": own[-1]["end"],
        })
    return {"text": text, "take_session_id": TAKE, "take_index": 1,
            "pieces": pieces, "paragraphs": paragraphs}


def bound_document(second: str = SLIDE_1_SECOND) -> dict:
    """The transcript after the live path attaches Paragraph identity."""
    served, parts, regions = ideal(second)
    return bind_pieces_to_parts(
        _transcript_document(), served_text=served,
        slide_regions=regions, parts=parts,
    )


def with_piece(document: dict, snippet_id: str, **changes) -> dict:
    """``document`` with one piece's fields changed (None removes one)."""
    pieces = []
    for piece in document["pieces"]:
        if piece["snippet_id"] == snippet_id:
            piece = {**piece, **changes}
            piece = {k: v for k, v in piece.items() if v is not None}
        pieces.append(piece)
    return {**document, "pieces": pieces}


def snippets(scores: dict | None = None) -> list[dict]:
    return [{
        "id": sid, "session_id": TAKE, "recording_id": RECORDING,
        "start_offset_ms": 1000 * index, "duration_ms": 900,
        "metrics": {"voice_confidence": {
            "version": "voice-confidence-universal-v3",
            "score": (scores or {}).get(sid, score),
        }},
    } for index, (sid, _slide, _words, score) in enumerate(SPOKEN)]


def candidate_id(snippet_id: str) -> str:
    return f"relative-confidence:{TAKE}:{snippet_id}"


def frame_inputs(document=None, *, served=SERVED, scores=None,
                 frozen=frozenset()) -> dict:
    return {
        "take_document": document if document is not None else bound_document(),
        "snippets": snippets(scores), "suggestions": {},
        "feedback_candidates": [], "take_index": 1,
        "expected_recording_id": RECORDING, "served_text": served,
        "frozen_candidate_ids": frozen,
    }


def service_frame(document=None, **options):
    return build_service_candidate_frame(**frame_inputs(document, **options))


def inventory_for(frame, document=None, *, served=SERVED, detail=None):
    return prepare_v3_service_inventory(
        frame=frame,
        take_document=document if document is not None else bound_document(),
        served_text=served, feedback_candidates=[], detail=detail,
    )


def visible_by_block(inventory) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in inventory["visible_rows"]:
        if row["feedback_family"] == "confident_voice":
            out.setdefault(row["block_id"], []).append(row["snippet_id"])
    return out


def candidate(frame: dict, snippet_id: str) -> dict:
    return next(row for block in frame["blocks"]
                for row in block["confidence_candidates"]
                if row["snippet_id"] == snippet_id)


# ── The shape is what the docstring says it is ──────────────────────────────

def test_the_binding_proves_the_weaker_clip_and_not_the_stronger_one():
    pieces = {p["snippet_id"]: p for p in bound_document()["pieces"]}
    # Slide 0 has one Paragraph: proven by the slide alone.
    assert pieces[S0A]["part_id"] == P0 and pieces[S0B]["part_id"] == P0
    # The rewritten clip was routed to the whole slide region, which
    # straddles both of slide 1's Paragraphs: no Paragraph is provable.
    assert "part_id" not in pieces[S1A]
    assert (pieces[S1A]["served_start"], pieces[S1A]["served_end"]) == REGIONS[1]
    # The verbatim clip sits inside the second Paragraph.
    assert pieces[S1B]["part_id"] == P2
    start, end = pieces[S1B]["served_start"], pieces[S1B]["served_end"]
    assert SERVED[start:end] == SPOKEN[3][2]


# ── 24b: the block's item is the best one the serve path can prove ─────────

def test_a_block_whose_best_clip_is_unprovable_serves_its_best_provable_one():
    frame = service_frame()
    slide_0, slide_1 = frame["blocks"]
    assert slide_0["selected_candidate_id"] == candidate_id(S0A)
    assert slide_1["selected_candidate_id"] == candidate_id(S1B)
    inventory = inventory_for(frame)
    assert inventory is not None
    # One Confident Voice item per valid block, and no block left empty.
    assert visible_by_block(inventory) == {
        slide_0["block_id"]: [S0A],
        slide_1["block_id"]: [S1B],
    }


class _Database:
    """The live path's writes, each succeeding; the snapshot is the screen."""

    def __init__(self) -> None:
        self.client = self
        self.bundle = None
        self.membership_payload = None
        self._rpc_data: dict = {}

    def rpc(self, _name, _payload):
        self._rpc_data = {
            "snapshot_contract_version":
                "feedback-v3-candidate-source-snapshot-v1",
            "document_snapshot_id": SNAPSHOT,
            "source_generation": 1,
            "surface": SERVED,
            "surface_sha256": sha256(SERVED.encode("utf-8")).hexdigest(),
        }
        return self

    def execute(self):
        data = self._rpc_data

        class _Result:
            pass

        result = _Result()
        result.data = data  # type: ignore[attr-defined]
        return result

    def ensure_service_enrollment(self, **_payload):
        return None

    def record_feedback_v3_service_candidate_set(self, bundle):
        self.bundle = bundle
        return {"candidate_set_id": bundle["candidate_set_id"]}

    def freeze_feedback_v3_service_membership(self, payload):
        self.membership_payload = payload
        return {"id": MEMBERSHIP, "content_identity_sha256": "c" * 64}


def run_chain(database=None, *, frozen=frozenset()):
    from services.mlc3_first_client_feedback import (
        prepare_first_client_feedback,
    )
    return prepare_first_client_feedback(
        database=database if database is not None else _Database(),
        session={"id": TAKE, "user_id": USER, "owner_principal_id": OWNER,
                 "project_id": PROJECT, "recording_id": RECORDING,
                 "take_index": 1},
        take_document=bound_document(), served_text=SERVED,
        snippets=snippets(), suggestions={}, feedback_candidates=[],
        owner_user_id=USER, frozen_candidate_ids=frozen,
    )


@pytest.fixture
def service_on(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)


def test_the_live_chain_serves_an_item_on_every_valid_block(service_on):
    database = _Database()
    rows = run_chain(database)
    assert isinstance(rows, list)
    assert sorted(row["snippet_id"] for row in rows) == sorted([S0A, S1B])
    # Frozen with the item it serves: the provable clip is the selected
    # membership item; the unprovable one never reaches the membership.
    items = {item["snippet_id"]: item
             for item in database.membership_payload["p_items"]}
    assert items[S1B]["selected"] is True
    assert S1A not in items


# ── What selection passes over is a typed exclusion, never dropped ─────────

def test_the_passed_over_clip_is_excluded_with_its_typed_reason():
    frame = service_frame()
    slide_1 = frame["blocks"][1]
    passed = candidate(frame, S1A)
    assert passed["eligibility"] == "excluded"
    assert passed["exclusion_reason"] == UNSERVABLE_PARAGRAPH
    assert {"candidate_kind": "confidence_clip", "snippet_id": S1A,
            "reason": UNSERVABLE_PARAGRAPH,
            "block_id": slide_1["block_id"]} in frame["excluded_candidates"]
    # Still in the block's inventory, with its clip lineage intact.
    assert passed in slide_1["confidence_candidates"]
    assert passed["clip_identity"]["snippet_id"] == S1A
    # The served item's own language, as for any winner.
    assert slide_1["selection_reason"] == "relatively_strongest_measured"


def test_a_clip_with_a_paragraph_but_no_served_span_is_unservable_span():
    document = with_piece(bound_document(), S1B,
                          served_start=None, served_end=None)
    frame = service_frame(document)
    assert candidate(frame, S1B)["exclusion_reason"] == UNSERVABLE_SPAN
    # The best clip's reason names the empty block (`_slide_coverage`
    # reports it for the uncovered Slide).
    assert frame["blocks"][1]["selected_candidate_id"] is None
    assert frame["blocks"][1]["selection_reason"] == UNSERVABLE_PARAGRAPH


# ── Nothing provable: the block stays empty, and says why ──────────────────

def test_a_block_with_nothing_provable_stays_empty_with_its_typed_reason():
    rewritten = "Every lesson opens with a single short question."
    document = bound_document(rewritten)
    served, _parts, _regions = ideal(rewritten)
    frame = service_frame(document, served=served)
    slide_0, slide_1 = frame["blocks"]
    assert slide_1["selected_candidate_id"] is None
    assert slide_1["selection_reason"] == UNSERVABLE_PARAGRAPH
    for snippet_id in (S1A, S1B):
        row = candidate(frame, snippet_id)
        assert (row["eligibility"], row["exclusion_reason"]) == (
            "excluded", UNSERVABLE_PARAGRAPH)
    # Nothing invented to fill it: no read, no route, and the Slide is
    # reported uncovered for that reason (24c: a target, never a floor).
    assert slide_1["delivery_band"] is None
    assert slide_1["practice_prompt"] is False
    assert frame["coverage"]["covered_slide_indexes"] == [0]
    assert frame["coverage"]["uncovered"] == [{
        "slide_index": 1, "block_count": 1,
        "reasons": [UNSERVABLE_PARAGRAPH]}]
    # The other block still serves.
    inventory = inventory_for(frame, document, served=served)
    assert visible_by_block(inventory) == {slide_0["block_id"]: [S0A]}


# ── ONE predicate: the frame and the serve path cannot disagree ────────────

BOUND_S1B = {p["snippet_id"]: p for p in bound_document()["pieces"]}[S1B]

S1B_VARIANTS = {
    "provable": {},
    "no_paragraph": {"part_id": None},
    "no_served_span": {"served_start": None, "served_end": None},
    "past_the_served_text": {"served_end": len(SERVED) + 5},
    "empty_span": {"served_end": BOUND_S1B["served_start"]},
    "not_an_offset": {"served_start": str(BOUND_S1B["served_start"])},
}


@pytest.mark.parametrize("variant", sorted(S1B_VARIANTS))
def test_selection_and_the_serve_path_agree_clip_by_clip(variant):
    document = with_piece(bound_document(), S1B, **S1B_VARIANTS[variant])
    frame = service_frame(document)
    row = candidate(frame, S1B)
    piece = next(p for p in document["pieces"] if p["snippet_id"] == S1B)
    verdict = unservable(piece.get("part_id"), row["target_span"], SERVED)

    detail: list[str] = []
    inventory = inventory_for(frame, document, detail=detail)
    served = S1B in visible_by_block(inventory or {"visible_rows": []}).get(
        frame["blocks"][1]["block_id"], [])
    selected = frame["blocks"][1]["selected_candidate_id"] == candidate_id(S1B)

    # The block selects the clip exactly when the serve path serves it.
    assert selected == served == (verdict is None)
    if verdict is not None:
        # The frame records the predicate's type; the serve path logs its
        # exact condition, as it always has.
        assert row["exclusion_reason"] == verdict.reason
        assert verdict.detail in detail


def test_the_serve_path_calls_the_very_predicate_selection_calls():
    assert service.unservable is policy.unservable
    assert service.span_rejection is policy.span_rejection
    # No second copy of the served-span rule is left behind to drift.
    assert not hasattr(service, "_served_span_rejection")
    assert not hasattr(service, "_span_rejection")


def test_the_predicate_names_each_condition():
    span = {"start": 0, "end": 5}
    assert unservable("p", span, "words here") is None
    assert unservable(None, span, "words here") == (
        UNSERVABLE_PARAGRAPH, "piece_has_no_part_id")
    assert unservable("p", None, "words here") == (
        UNSERVABLE_SPAN, "piece_has_no_served_span")
    assert unservable("p", {"start": 0, "end": 50}, "words here") == (
        UNSERVABLE_SPAN, "served_span_past_document_end:50>10")
    assert unservable("p", {"start": 3, "end": 3}, "words here") == (
        UNSERVABLE_SPAN, "served_span_inverted:3..3")
    assert unservable("p", {"start": "0", "end": 5}, "words here") == (
        UNSERVABLE_SPAN, "served_span_bounds_not_integers")
    # No served text proves no served span.
    assert unservable("p", span, None) == (
        UNSERVABLE_SPAN, "served_span_past_document_end:5>0")


# ── When the best clip is provable, NOTHING changes ────────────────────────

def _old_rule_winners(frame: dict) -> list:
    """The selection as it was before 24b, re-derived independently from
    the frame's own candidates: the best-ranked eligible one, by rank."""
    return [
        min((row for row in block["confidence_candidates"]
             if row["eligibility"] == "eligible"),
            key=policy._confidence_rank, default={}).get("candidate_id")
        for block in frame["blocks"]
    ]


def _existing_service_fixtures():
    """The V3 suite's service-shaped fixtures, as their own files build them."""
    from tests import test_mlc3_first_client_feedback as mlc3
    from tests import test_v3_end_to_end_production_shape as e2e
    from tests import test_verbal_lanes_take_document_n48_1 as n48

    _session, document, snips = mlc3._source()
    yield "mlc3._source", {
        "take_document": document, "snippets": snips, "suggestions": {},
        "feedback_candidates": [], "take_index": 1,
        "expected_recording_id": mlc3.RECORDING,
        "served_text": document["text"]}
    yield "e2e._bound_document", {
        "take_document": e2e._bound_document(), "snippets": e2e._snippets(),
        "suggestions": {}, "feedback_candidates": [], "take_index": 1,
        "expected_recording_id": e2e.RECORDING, "served_text": e2e.IDEAL}
    for frozen in (frozenset(), frozenset({"structural-repair"})):
        yield f"n48_1._placed_document(parts=True) frozen={sorted(frozen)}", {
            "take_document": n48._placed_document(parts=True),
            "snippets": n48._snippets(), "suggestions": {},
            "feedback_candidates": [n48._praise(), n48._rewrite()],
            "take_index": 2, "expected_recording_id": n48.RECORDING,
            "served_text": n48.SERVED, "frozen_candidate_ids": frozen}
    # This file's Take, with slide 1's provable clip now its best: the
    # unprovable clip ranked below it is never in contention, so it is not
    # re-judged and its record stays exactly as it was.
    yield "this file, provable best above an unprovable clip", frame_inputs(
        bound_document(), scores={S1B: 0.9})


@pytest.mark.parametrize(
    "name,inputs", list(_existing_service_fixtures()),
    ids=[name for name, _ in _existing_service_fixtures()])
def test_with_a_provable_best_the_frame_is_byte_identical(name, inputs):
    rank_only = build_shadow_frame(**inputs)
    servable = build_shadow_frame(**inputs, select_servable=True)
    assert servable is not None
    # Non-vacuous: every block has a winner, and the serve path can prove it.
    pieces = {p["snippet_id"]: p for p in inputs["take_document"]["pieces"]}
    for block in servable["blocks"]:
        winner = next(row for row in block["confidence_candidates"]
                      if row["candidate_id"] == block["selected_candidate_id"])
        assert unservable(pieces[winner["snippet_id"]].get("part_id"),
                          winner["target_span"], inputs["served_text"]) is None
    # Same selected ids as the pre-24b rule ...
    assert [row["candidate_id"] for row in servable["selected_confidence"]] \
        == _old_rule_winners(servable) == _old_rule_winners(rank_only)
    # ... and the same frame, to the byte: nothing was passed over.
    assert servable == rank_only
    assert servable["frame_hash"] == rank_only["frame_hash"]


# ── A frozen Take does not change ──────────────────────────────────────────

def test_a_frozen_take_does_not_take_a_fallback_its_freeze_does_not_hold():
    # Frozen before 24b: its set holds the rows it served, slide 0's only.
    frozen = service_frame(frozen=frozenset({candidate_id(S0A)}))
    rank_only = build_shadow_frame(**frame_inputs())
    assert frozen["blocks"] == rank_only["blocks"]
    assert frozen["selected_confidence"] == rank_only["selected_confidence"]
    assert frozen["excluded_candidates"] == rank_only["excluded_candidates"]
    assert frozen["blocks"][1]["selected_candidate_id"] == candidate_id(S1A)


def test_a_fallback_chosen_before_the_freeze_is_chosen_again():
    frozen = service_frame(
        frozen=frozenset({candidate_id(S0A), candidate_id(S1B)}))
    assert frozen == service_frame()


def test_a_take_frozen_before_24b_rebuilds_the_bundle_it_froze(
        service_on, monkeypatch):
    # The read that froze it, on the rule before 24b: rank alone.
    before = _Database()
    with monkeypatch.context() as patch:
        patch.setattr(policy, "_servability", lambda *_args: None)
        served_then = run_chain(before)
    assert [row["snippet_id"] for row in served_then] == [S0A]
    # Every later read, with its frozen set: the same candidate set and the
    # same membership, so the database replays the freeze instead of
    # refusing a second one for this snapshot (and with it every answer).
    after = _Database()
    served_now = run_chain(after, frozen=frozenset(
        row["id"] for row in served_then))
    assert after.bundle["candidate_set_id"] == before.bundle["candidate_set_id"]
    assert after.membership_payload == before.membership_payload
    assert [row["snippet_id"] for row in served_now] == [S0A]


def test_a_take_frozen_after_24b_rebuilds_its_bundle_on_every_read(service_on):
    first = _Database()
    rows = run_chain(first)
    again = _Database()
    run_chain(again, frozen=frozenset(row["id"] for row in rows))
    assert again.bundle["candidate_set_id"] == first.bundle["candidate_set_id"]
    assert again.membership_payload == first.membership_payload


# ── The dark frame is untouched ─────────────────────────────────────────────

def test_the_dark_frame_still_selects_by_rank_alone():
    # Its document is never bound to Paragraphs, so it does not judge what
    # it cannot know: the same choices, no servability exclusions.
    for document in (bound_document(), _transcript_document()):
        dark = build_shadow_frame(**frame_inputs(document))
        assert [b["selected_candidate_id"] for b in dark["blocks"]] == [
            candidate_id(S0A), candidate_id(S1A)]
        assert not any(row["reason"] in (UNSERVABLE_PARAGRAPH, UNSERVABLE_SPAN)
                       for row in dark["excluded_candidates"])


# ── The budget, the read and AC-9 ───────────────────────────────────────────

def test_never_more_than_one_item_per_block():
    for frame in (service_frame(),
                  service_frame(frozen=frozenset({candidate_id(S0A)}))):
        block_ids = [row["block_id"] for row in frame["selected_confidence"]]
        assert len(block_ids) == len(set(block_ids)) <= len(frame["blocks"])
        inventory = inventory_for(frame)
        assert all(len(rows) == 1
                   for rows in visible_by_block(inventory).values())


def test_the_block_is_read_by_the_item_it_serves():
    # The fallback is weak where the unprovable best was strong: the bar,
    # the practise prompt and the tentative language follow what is served.
    frame = service_frame(scores={S1B: -0.3})
    slide_1 = frame["blocks"][1]
    assert slide_1["selected_candidate_id"] == candidate_id(S1B)
    assert slide_1["delivery_band"] == "delivery_signal_mid_low"
    row = next(r for r in inventory_for(frame)["visible_rows"]
               if r["snippet_id"] == S1B)
    assert (row["bookmark_tier"], row["practice_prompt"], row["tentative"]) \
        == ("weak", True, True)


def test_the_served_fallback_carries_nothing_a_winner_does_not():
    inventory = inventory_for(service_frame())
    rows = {row["snippet_id"]: row for row in inventory["visible_rows"]}
    assert set(rows[S1B]) == set(rows[S0A])
    serialized = json.dumps(inventory["visible_rows"])
    assert "unservable" not in serialized
    for row in inventory["visible_rows"]:
        for key in ("candidate_score", "reason_tier", "eligibility",
                    "exclusion_reason", "selection_reason", "delivery_band"):
            assert key not in row
