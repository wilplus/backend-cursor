"""Database-bound checks for the freeze the speaker's answer is judged against.

THE PATH THIS COVERS HAD NO COVERAGE AT ALL (#597). Two functions decide
whether a speaker's judgement is accepted: ``claim_ideal_text_feedback_set_v1``
freezes what was served, and ``record_take_feedback_response_v1`` checks an
answer against that freeze. Neither was installed by any rehearsal lane, so the
tier ran green while testing none of it — and three merges in a row argued about
this path from reading alone, one of which (#592) shipped a regression worse
than the bug it fixed.

The founder's symptom was a red bar under the Confident Voice question reading
"feedback item is not in this Take's frozen set", on an item the product had
just shown him. These tests pin both halves of that story on a real PostgreSQL:
a Take frozen under V3 accepts its answer, and a Take frozen under V2 before
the #591 stage move refuses one — permanently, because the claim is insert-once.

The target must be a disposable local database whose name starts with
``willab_freeze_``. Nothing here writes media or activates any service.
"""

from __future__ import annotations

import os
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest

DSN = os.environ.get("TAKE_FEEDBACK_FREEZE_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable freeze rehearsal only"
)

OWNER_PRINCIPAL = "11111111-1111-1111-1111-111111111111"
OWNER_USER = "44444444-4444-4444-4444-444444444444"
RECORDING = "22222222-2222-2222-2222-222222222222"

# What V3 actually serves: one relative-best Confident Voice item per valid
# 75-word block (contract 24b), plus at most one rewrite for the whole Take
# (24f). Six items, five of one family — a shape V2's budget could never hold.
V3_SET = [
    {"id": "cv-block-0", "feedback_family": "confident_voice"},
    {"id": "cv-block-1", "feedback_family": "confident_voice"},
    {"id": "cv-block-2", "feedback_family": "confident_voice"},
    {"id": "cv-block-3", "feedback_family": "confident_voice"},
    {"id": "cv-block-4", "feedback_family": "confident_voice"},
    {"id": "rw-1", "feedback_family": "rewrite_clarity"},
]

# V2's budget: exactly one item from each of three families (24h). Retained as
# superseded history, and never a silent substitute.
V2_SET = [
    {"id": "v2-cv", "feedback_family": "confident_voice"},
    {"id": "v2-rw", "feedback_family": "rewrite_clarity"},
    {"id": "v2-gf", "feedback_family": "great_formulation"},
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


def ids(frozen: dict) -> list[str]:
    return [str(key.get("id")) for key in frozen["selected_keys"]]


def test_a_v3_shaped_set_can_be_frozen_at_all(db):
    """Five Confident Voice items and a rewrite. V2's CHECK allowed exactly
    three, one per family, so before 0347 this claim could not be written —
    and a claim that fails blanks the whole bookmark surface."""
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)

    frozen = freeze(db, arc, session_id, V3_SET)

    assert ids(frozen) == [key["id"] for key in V3_SET]


def test_the_speaker_s_judgement_is_accepted_on_a_v3_take(db):
    """THE FOUNDER'S QUESTION, ANSWERED: "will it accept the judgment or not
    from now on?" On a Take frozen after #591 moved the claim below V3's
    selection, yes."""
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    freeze(db, arc, session_id, V3_SET)

    saved = answer(db, arc, session_id, "cv-block-3")

    assert saved["outcome"] == "saved"
    assert saved["row"]["feedback_id"] == "cv-block-3"
    assert saved["row"]["response"] == "yes"
    # The answer lands in the owner-routing lane and nowhere else (L3).
    assert saved["row"]["provenance"] == "user_self_report"


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


def test_a_take_frozen_under_v2_refuses_the_item_v3_showed(db):
    """THE FOUNDER'S RED BAR, REPRODUCED. Every Take opened before #591 froze
    V2's three keys while `_first_client_feedback` had already replaced the
    served rows with V3's. The two sets share no identity, so the answer to an
    item the product had just displayed comes back not_member."""
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    freeze(db, arc, session_id, V2_SET)

    refused = answer(db, arc, session_id, "cv-block-3")

    assert refused["outcome"] == "not_member"
    assert ids(refused) == ["v2-cv", "v2-rw", "v2-gf"]


def test_those_takes_cannot_be_repaired_by_freezing_again(db):
    """INSERT-ONCE IS DELIBERATE and this pins it. A second claim returns the
    set that already exists rather than replacing it, so a Take frozen under V2
    stays unanswerable for good. That is the honest cost of the stage move, and
    it is bounded: it can only ever affect Takes opened before #591 shipped.

    It is also the reason a re-test must use a NEW Take. Re-opening an old one
    and tapping again reproduces the old refusal no matter what the code does.
    """
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    freeze(db, arc, session_id, V2_SET)

    reclaimed = freeze(db, arc, session_id, V3_SET)

    assert ids(reclaimed) == ["v2-cv", "v2-rw", "v2-gf"]
    assert answer(db, arc, session_id, "cv-block-3")["outcome"] == "not_member"


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


def test_the_first_answer_stands_and_a_contradicting_one_conflicts(db):
    """A speaker who taps twice has one opinion, not two — and the SECOND tap
    does not overwrite the first. The route has no read-then-insert fallback
    precisely so this stays one transaction and cannot race.

    `conflict` rather than a silent overwrite matters for provenance: the owner
    routing signal recorded against a recording is the one the speaker gave
    when they heard it, and a later disagreement is a new fact about a later
    moment, not a correction of that one (L3)."""
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    freeze(db, arc, session_id, V3_SET)

    first = answer(db, arc, session_id, "cv-block-0", response="yes")
    repeat = answer(db, arc, session_id, "cv-block-0", response="yes")
    contradiction = answer(db, arc, session_id, "cv-block-0", response="no")

    assert first["outcome"] == "saved"
    assert repeat["outcome"] == "replayed"
    assert contradiction["outcome"] == "conflict"
    with db.cursor() as cur:
        cur.execute(
            "SELECT response FROM public.take_feedback_self_report "
            "WHERE take_session_id = %s AND feedback_id = %s",
            (session_id, "cv-block-0"),
        )
        rows = cur.fetchall()
    assert rows == [("yes",)]


# ---------------------------------------------------------------------------
#  THE EXPOSURE RECORD (0349). Beside the frozen selection sits the record of
#  the complete ranking that was shown, `take_feedback_exposure`. Its inline
#  CHECK was V2's exactly-three, the third copy of that rule and the one
#  nobody listed: on 2026-09-21, minutes after the bookmarks came back,
#  every V3 open logged 23514 on this table and the audit of what was ranked
#  behind the bookmarks did not exist.
# ---------------------------------------------------------------------------

def exposure(db, arc_id: str, session_id: str, keys: list[dict],
             *, review_version: int = 1) -> None:
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.take_feedback_exposure("
            "arc_id, take_session_id, review_version, policy_version, "
            "candidate_set, selected_keys) VALUES (%s,%s,%s,%s,%s,%s)",
            (arc_id, session_id, review_version, "take-feedback-policy-v3",
             Json([dict(key, selected=True) for key in keys]), Json(keys)),
        )


def exposures(db, session_id: str) -> int:
    with db.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM public.take_feedback_exposure "
            "WHERE take_session_id = %s", (session_id,))
        return int(cur.fetchone()[0])


def test_the_exposure_record_takes_a_v3_selection(db):
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    exposure(db, arc, session_id, V3_SET)
    assert exposures(db, session_id) == 1


def test_the_exposure_record_still_takes_v2s_three(db):
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    exposure(db, arc, session_id, [
        {"id": "cv", "feedback_family": "confident_voice"},
        {"id": "rw", "feedback_family": "rewrite_clarity"},
        {"id": "gf", "feedback_family": "great_formulation"},
    ])
    assert exposures(db, session_id) == 1


def test_an_exposure_without_confident_voice_is_refused(db):
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    with pytest.raises(psycopg2.errors.CheckViolation):
        exposure(db, arc, session_id, [
            {"id": "rw", "feedback_family": "rewrite_clarity"},
            {"id": "gf", "feedback_family": "great_formulation"},
        ])
    assert exposures(db, session_id) == 0


def test_the_exposure_ceiling_is_the_frozen_set_s_ceiling(db):
    arc = f"arc-{uuid4()}"
    session_id = take(db, arc)
    with pytest.raises(psycopg2.errors.CheckViolation):
        exposure(db, arc, session_id, [
            {"id": f"cv-{n}", "feedback_family": "confident_voice"}
            for n in range(65)
        ])
    assert exposures(db, session_id) == 0
