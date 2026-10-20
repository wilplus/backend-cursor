"""
STORY    As a speaker, I want my answer to any feedback item I was shown to be
         accepted, so that I never see "feedback item is not in this Take's
         frozen set" on an item I just saw. (Critical path: feedback -> next
         Take.)
OUTCOME
  O1  Every item of a Take frozen under V3 takes an answer, not only the first.
  O2  An item that was never served is refused.
  O3  A set without a Confident Voice item cannot be frozen.
  O4  A Take frozen under V2 keeps its V2 set: a V3 item is refused there,
      and freezing again does not replace the set (the claim is insert-once).
  O5  The record of what was shown takes a V3 selection of six items, and
      still refuses one without Confident Voice.
PROVES   O1 -> test_every_block_is_answerable_not_just_the_first
         O2 -> test_an_item_never_served_is_still_refused
         O3 -> test_a_set_without_confident_voice_is_refused
         O4 -> test_a_take_frozen_under_v2_refuses_a_v3_item
         O5 -> test_the_exposure_record_takes_a_v3_selection
WHY      #597: the founder's red bar under the Confident Voice question; no
         lane installed either function until then.

Runs on the freeze lane of scripts/rehearsal_tier.sh against the real
claim_ideal_text_feedback_set_v1 and record_take_feedback_response_v1. The
target must be a disposable local database whose name starts with
``willab_freeze_``.
"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg2
import psycopg2.errors
import pytest
from psycopg2.extras import Json

DSN = os.environ.get("TAKE_FEEDBACK_FREEZE_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable freeze rehearsal only"
)

OWNER_PRINCIPAL = "11111111-1111-1111-1111-111111111111"
OWNER_USER = "44444444-4444-4444-4444-444444444444"
RECORDING = "22222222-2222-2222-2222-222222222222"

# What V3 actually serves: one relative-best Confident Voice item per valid
# 75-word block (contract 24b), plus a rewrite on a block read weak (24f).
# Six items, five of one family — a shape V2's budget could never hold.
V3_SET = [
    {"id": "cv-block-0", "feedback_family": "confident_voice"},
    {"id": "cv-block-1", "feedback_family": "confident_voice"},
    {"id": "cv-block-2", "feedback_family": "confident_voice"},
    {"id": "cv-block-3", "feedback_family": "confident_voice"},
    {"id": "cv-block-4", "feedback_family": "confident_voice"},
    {"id": "rw-1", "feedback_family": "rewrite_clarity"},
]


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_freeze_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a non-local rehearsal host")
    connection = psycopg2.connect(DSN)
    connection.autocommit = True
    with connection.cursor() as cur:
        cur.execute(
            "INSERT INTO public.owner_principals(id) VALUES (%s) "
            "ON CONFLICT DO NOTHING", (OWNER_PRINCIPAL,))
        cur.execute(
            "INSERT INTO public.recordings(id) VALUES (%s) "
            "ON CONFLICT DO NOTHING", (RECORDING,))
    yield connection
    connection.close()


def take(db, arc_id: str, *, take_index: int = 1) -> str:
    """One spoken Take the owner may answer for."""
    session_id = str(uuid4())
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.v2_sessions(id, arc_id, owner_principal_id, "
            "user_id, recording_1_id, take_index, recording_kind) "
            "VALUES (%s,%s,%s,%s,%s,%s,'spoken')",
            (session_id, arc_id, OWNER_PRINCIPAL, OWNER_USER, RECORDING,
             take_index),
        )
    return session_id


def freeze(db, arc_id: str, session_id: str, keys: list[dict],
           *, take_index: int = 1) -> dict:
    with db.cursor() as cur:
        cur.execute(
            "SELECT public.claim_ideal_text_feedback_set_v1("
            "%s,%s,%s,%s,%s,%s)",
            (arc_id, OWNER_USER, session_id, take_index, take_index,
             Json(keys)),
        )
        return cur.fetchone()[0]


def answer(db, arc_id: str, session_id: str, feedback_id: str,
           family: str = "confident_voice", response: str = "yes") -> dict:
    with db.cursor() as cur:
        cur.execute(
            "SELECT public.record_take_feedback_response_v1("
            "%s,%s,%s,%s,%s,%s)",
            (arc_id, session_id, OWNER_USER, feedback_id, family, response),
        )
        return cur.fetchone()[0]


def test_every_block_is_answerable_not_just_the_first(db):
    """24b puts one item on EVERY valid block, and the speaker may answer any
    of them. A freeze that accepted only the first would be V2's budget wearing
    V3's clothes."""
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    freeze(db, arc, session_id, V3_SET)

    outcomes = [
        answer(db, arc, session_id, f"cv-block-{index}")["outcome"]
        for index in range(5)
    ]

    assert outcomes == ["saved"] * 5


def test_an_item_never_served_is_still_refused(db):
    """The membership check is the point of the freeze, not an obstacle to it.
    Answering a Candidate the Manager did not approve is what L2 forbids, and
    widening the shape must not widen that."""
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    freeze(db, arc, session_id, V3_SET)

    refused = answer(db, arc, session_id, "cv-block-99")

    assert refused["outcome"] == "not_member"


def test_a_set_without_confident_voice_is_refused(db):
    """The required evaluation cannot be silently replaced by a second rewrite.
    0347 widened the COUNT but kept this, and widening a budget is exactly when
    a guard like it gets dropped by accident."""
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)

    with pytest.raises(psycopg2.Error):
        freeze(db, arc, session_id, [
            {"id": "rw-1", "feedback_family": "rewrite_clarity"},
            {"id": "gf-1", "feedback_family": "great_formulation"},
        ])


# V2's budget: exactly one item of each of three families.
V2_SET = [
    {"id": "cv-1", "feedback_family": "confident_voice"},
    {"id": "rw-1", "feedback_family": "rewrite_clarity"},
    {"id": "gf-1", "feedback_family": "great_formulation"},
]


def test_a_take_frozen_under_v2_refuses_a_v3_item(db):
    """A Take frozen before the #591 stage move keeps the set it was served.
    Its own items still take an answer; a V3 block item does not, and a later
    V3 freeze cannot replace the set."""
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    freeze(db, arc, session_id, V2_SET)

    again = freeze(db, arc, session_id, V3_SET)

    assert again["selected_keys"] == V2_SET
    assert answer(db, arc, session_id, "cv-block-1")["outcome"] == "not_member"
    assert answer(db, arc, session_id, "cv-1")["outcome"] == "saved"


def _expose(db, arc_id: str, session_id: str, keys: list[dict]) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.take_feedback_exposure(arc_id, "
            "take_session_id, review_version, policy_version, candidate_set, "
            "selected_keys) VALUES (%s,%s,1,'feedback-v3',%s,%s)",
            (arc_id, session_id, Json(keys), Json(keys)),
        )


def test_the_exposure_record_takes_a_v3_selection(db):
    """0349: this table's CHECK was V2's exactly-three, and on 2026-09-21
    every V3 open logged 23514 here, so the record of what was shown behind
    the bookmarks did not exist."""
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    _expose(db, arc, session_id, V3_SET)
    with db.cursor() as cur:
        cur.execute(
            "SELECT jsonb_array_length(selected_keys) FROM "
            "public.take_feedback_exposure WHERE take_session_id = %s",
            (session_id,))
        assert cur.fetchone()[0] == 6

    other_arc = f"arc-{uuid4()}"
    other = take(db, other_arc)
    with pytest.raises(psycopg2.errors.CheckViolation):
        _expose(db, other_arc, other, V3_SET[5:])   # the rewrite alone
