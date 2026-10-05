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

from hashlib import sha256

import pytest

from services.ideal_text_parts import bind_pieces_to_parts
from services.take_feedback_policy_v3 import build_service_candidate_frame
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

@pytest.mark.xfail(strict=True, reason=(
    "24b defect on f43aa885: the frame selects the unprovable clip and "
    "the serve path then drops it, leaving the block empty"))
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


@pytest.mark.xfail(strict=True, reason=(
    "24b defect on f43aa885: the frame selects the unprovable clip and "
    "the serve path then drops it, leaving the block empty"))
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
