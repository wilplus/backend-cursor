"""Database-bound checks for the rule that decides whether a stored bookmark
set is still true.

THIS PATH HAD NO LANE AT ALL. 0345 stored the Manager's block against a
published snapshot and refused it again whenever the arc's *mutable feedback
surface* had been written since. That rule named two writers, and both of the
routes a speaker actually answers a bookmark through were missing from it:
``take_feedback_self_report`` (the legacy route every non-canary account uses)
and ``feedback_v3_owner_responses`` (the service route). The stored block
carries each item's answered status, so a bake that outlived an answer put a
judged bookmark back on the page after a reload — the founder's "sometimes
they do appear but then a while later they are gone".

The second rule here is the one that cannot be seen by reading: the bake is
dated from when its computation STARTED, not when the row was written. The
Manager measurably takes 4 to 40 seconds, and an answer committed inside that
window was never seen by it. Dated at the write, such a bake reads as fresh.

The target must be a disposable local database whose name starts with
``willab_bake_``. Nothing here writes media or activates any service.
"""
from __future__ import annotations

import os
from uuid import uuid4

import psycopg2
from psycopg2.extras import Json
import pytest

DSN = os.environ.get("IDEAL_TEXT_FEEDBACK_BAKE_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable bake rehearsal only"
)

# Laid down by tests/integration/ideal_text_core_snapshot_prerequisites.sql.
ARC = "50000000-0000-4000-8000-000000000001"
ACTOR = "10000000-0000-4000-8000-000000000001"
OTHER_ACTOR = "10000000-0000-4000-8000-000000000002"
PRINCIPAL = "20000000-0000-4000-8000-000000000001"
PROJECT = "30000000-0000-4000-8000-000000000001"
TAKE = "40000000-0000-4000-8000-000000000001"

BLOCK = {"changes": [{"id": "cand-1", "source": "confident_voice"}],
         "style_changes": []}


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_bake_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a non-local rehearsal host")
    connection = psycopg2.connect(DSN)
    connection.autocommit = True
    try:
        yield connection
    finally:
        connection.close()


def _clean(db):
    with db.cursor() as cursor:
        cursor.execute("DELETE FROM public.ideal_text_feedback_bakes")
        cursor.execute("DELETE FROM public.feedback_v3_owner_responses")
        cursor.execute("DELETE FROM public.feedback_v3_memberships")
        cursor.execute("DELETE FROM public.take_feedback_self_report")
        cursor.execute("DELETE FROM public.user_suggestion_feedback")
        cursor.execute("DELETE FROM public.intervention_decisions")


def _publish(db, version: int = 1) -> str:
    """One published document for this arc, and its snapshot id.

    The generation is read rather than assumed: publishing is fenced on the
    arc's CURRENT generation, which every write to the document's sources
    advances by trigger.
    """
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.ideal_text_document_generations(arc_id) "
            "VALUES(%s) ON CONFLICT (arc_id) DO NOTHING", (ARC,))
        cursor.execute(
            "SELECT generation FROM public.ideal_text_document_generations "
            "WHERE arc_id=%s", (ARC,))
        generation = int(cursor.fetchone()[0])
        cursor.execute(
            "SELECT public.publish_ideal_text_document_snapshot_v1("
            "%s,%s,%s,%s,%s,%s,%s,%s,"
            "jsonb_build_object("
            " 'arc_id',%s,'version',%s,'status','unverified','title','Test',"
            " 'updated_at',NULL,'latest_take_session_id',%s,"
            " 'take_count',1,'can_record_take',true,'text','Exact text.',"
            " 'presentation_ref',NULL,'slide_titles','[]'::jsonb,"
            " 'pieces','[]'::jsonb,'parts','null'::jsonb,'user_edited',false),"
            "'{}'::jsonb)",
            (ARC, ACTOR, PRINCIPAL, PROJECT, TAKE, version,
             generation, f"{version:064x}", ARC, version, TAKE),
        )
        published = cursor.fetchone()[0]
    return str(published["id"])


def _write(db, snapshot_id: str, *, block=None, computed_over_ms=None):
    with db.cursor() as cursor:
        if computed_over_ms is None:
            cursor.execute(
                "SELECT public.write_ideal_text_feedback_bake_v1(%s,%s,%s,%s)",
                (ARC, ACTOR, snapshot_id, Json(block or BLOCK)))
        else:
            cursor.execute(
                "SELECT public.write_ideal_text_feedback_bake_v1("
                "%s,%s,%s,%s,%s)",
                (ARC, ACTOR, snapshot_id, Json(block or BLOCK),
                 computed_over_ms))
        return cursor.fetchone()[0]


def _read(db, snapshot_id: str, actor: str = ACTOR):
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT public.read_ideal_text_feedback_bake_v1(%s,%s,%s)",
            (ARC, actor, snapshot_id))
        return cursor.fetchone()[0]


def _membership(db) -> str:
    membership_id = str(uuid4())
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.feedback_v3_memberships(id,take_id) "
            "VALUES(%s,%s)", (membership_id, TAKE))
    return membership_id


# ── the stored set is served only while it is still true ──────────────────


def test_a_fresh_bake_comes_back_with_its_marks(db):
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    served = _read(db, snapshot)
    assert served is not None
    assert served["payload"] == BLOCK


def test_another_document_never_serves_this_one_s_marks(db):
    """The snapshot id IS the document's identity: a new Take republishes,
    and its bake is simply absent until made."""
    _clean(db)
    first = _publish(db, version=1)
    _write(db, first)
    second = _publish(db, version=2)
    assert _read(db, second) is None


def test_another_speaker_never_reads_this_one_s_marks(db):
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    assert _read(db, snapshot, actor=OTHER_ACTOR) is None


# ── the two answer routes 0345 forgot (0351) ──────────────────────────────


def test_a_legacy_answer_retires_the_stored_set(db):
    """The route every non-canary account answers through.

    Without this the reload after an answer served the block as it was
    BEFORE the answer, and the bookmark the speaker had just judged came
    back looking untouched.
    """
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.take_feedback_self_report("
            "arc_id,take_session_id,owner_user_id,feedback_id,"
            "feedback_family,response) "
            "VALUES(%s,%s,%s,'cand-1','confident_voice','yes')",
            (ARC, TAKE, ACTOR))
    assert _read(db, snapshot) is None


def test_a_service_answer_retires_the_stored_set(db):
    """The V3 service route, reached through a membership whose take names
    the arc. Same defect, one join further away."""
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    membership = _membership(db)
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.feedback_v3_owner_responses("
            "membership_id,candidate_id,owner_user_id,response) "
            "VALUES(%s,%s,%s,'confident_yes')",
            (membership, str(uuid4()), ACTOR))
    assert _read(db, snapshot) is None


def test_another_arc_s_answer_leaves_this_bake_alone(db):
    """Coarse is not indiscriminate. The rule is per-arc, so a speaker
    answering on one project must not cost another project its fast open."""
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    other_take = str(uuid4())
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.v2_sessions(id,user_id,owner_principal_id,"
            "project_id,arc_id,take_index,analysis_state,recording_kind) "
            "VALUES(%s,%s,%s,%s,%s,1,'ready','spoken')",
            (other_take, ACTOR, PRINCIPAL, PROJECT, str(uuid4())))
        cursor.execute(
            "INSERT INTO public.take_feedback_self_report("
            "arc_id,take_session_id,owner_user_id,feedback_id,"
            "feedback_family,response) "
            "VALUES(%s,%s,%s,'cand-9','confident_voice','yes')",
            (str(uuid4()), other_take, ACTOR))
    assert _read(db, snapshot) is not None


def test_the_writers_0345_already_knew_still_retire_it(db):
    """The rule was widened, not replaced."""
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.intervention_decisions("
            "arc_id,take_session_id,change_key,decision) "
            "VALUES(%s,%s,'k','approved')", (ARC, TAKE))
    assert _read(db, snapshot) is None


# ── the bake is dated from when the computation STARTED (0351) ────────────


def test_an_answer_during_the_computation_retires_the_bake(db):
    """THE WINDOW IS THE WHOLE POINT.

    The Manager takes 4 to 40 seconds. An answer committed while it ran was
    never seen by it, so the block it produces is already out of date the
    moment it is stored. Dated at the write, that block reads as fresher
    than the answer and is served — putting a judged bookmark back on the
    page. Dated from the start of its own window, it is correctly refused.
    """
    _clean(db)
    snapshot = _publish(db)
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.take_feedback_self_report("
            "arc_id,take_session_id,owner_user_id,feedback_id,"
            "feedback_family,response) "
            "VALUES(%s,%s,%s,'cand-1','confident_voice','yes')",
            (ARC, TAKE, ACTOR))
    # The write lands after the answer, but the computation behind it began
    # a full minute earlier — before the answer existed.
    _write(db, snapshot, computed_over_ms=60_000)
    assert _read(db, snapshot) is None


def test_a_computation_that_finished_before_the_answer_still_serves(db):
    """The flip side, so the window cannot simply be made infinite: a bake
    whose whole window predates every answer is fresh and is served."""
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot, computed_over_ms=5_000)
    assert _read(db, snapshot) is not None


def test_the_window_moves_the_row_s_own_timestamp(db):
    """Not an incidental behaviour — the stored `baked_at` IS the claim
    being made about what the block saw."""
    _clean(db)
    snapshot = _publish(db)
    written = _write(db, snapshot, computed_over_ms=30_000)
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT extract(epoch FROM clock_timestamp() - baked_at) "
            "FROM public.ideal_text_feedback_bakes "
            "WHERE arc_id=%s AND actor_id=%s", (ARC, ACTOR))
        age_seconds = float(cursor.fetchone()[0])
    assert written is not None
    assert age_seconds >= 30


def test_a_caller_that_sends_no_window_still_writes(db):
    """The four-argument call is gone, but a container that has not yet
    learned to pass the window must still store — dated at the write, which
    is 0345's behaviour exactly."""
    _clean(db)
    snapshot = _publish(db)
    assert _write(db, snapshot) is not None
    assert _read(db, snapshot) is not None


def test_a_nonsense_window_is_not_allowed_to_move_the_row_backwards(db):
    """A negative duration is meaningless and must not date a bake into the
    future, where nothing could ever invalidate it."""
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot, computed_over_ms=-60_000)
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT baked_at <= clock_timestamp() "
            "FROM public.ideal_text_feedback_bakes "
            "WHERE arc_id=%s AND actor_id=%s", (ARC, ACTOR))
        assert cursor.fetchone()[0] is True


# ── the guards 0345 established, re-checked against the new signature ─────


def test_a_bake_may_not_point_at_another_speaker_s_document(db):
    _clean(db)
    snapshot = _publish(db)
    with db.cursor() as cursor:
        with pytest.raises(psycopg2.errors.RaiseException) as caught:
            cursor.execute(
                "SELECT public.write_ideal_text_feedback_bake_v1("
                "%s,%s,%s,%s,%s)",
                (ARC, OTHER_ACTOR, snapshot, Json(BLOCK), 0))
    assert "SNAPSHOT_NOT_OWNED" in str(caught.value)


def test_the_door_is_closed_to_the_browser_roles(db):
    """SECURITY DEFINER over another speaker's feedback. A dropped and
    recreated function starts life granted to PUBLIC, so this is the check
    that the re-grant in 0351 actually ran."""
    with db.cursor() as cursor:
        for role in ("anon", "authenticated"):
            cursor.execute(
                "SELECT has_function_privilege(%s,"
                "'public.write_ideal_text_feedback_bake_v1"
                "(text,text,uuid,jsonb,integer)','EXECUTE')", (role,))
            assert cursor.fetchone()[0] is False
            cursor.execute(
                "SELECT has_function_privilege(%s,"
                "'public.ideal_text_feedback_surface_touched_at_v1(text)',"
                "'EXECUTE')", (role,))
            assert cursor.fetchone()[0] is False
        cursor.execute(
            "SELECT has_function_privilege('service_role',"
            "'public.write_ideal_text_feedback_bake_v1"
            "(text,text,uuid,jsonb,integer)','EXECUTE')")
        assert cursor.fetchone()[0] is True


def test_the_old_four_argument_writer_is_gone(db):
    """Two candidates accepting the same four parameter names is a PostgREST
    ambiguity error, not a fallback — so the old one is dropped, not kept."""
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT count(*) FROM pg_proc "
            "WHERE proname = 'write_ideal_text_feedback_bake_v1'")
        assert cursor.fetchone()[0] == 1
