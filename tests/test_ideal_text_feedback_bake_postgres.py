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

The third writer is not the speaker at all (0428). The stored block carries
what the coach made of each bookmark's request (``_annotate_coach_answers``):
the request's status, the exercise the coach shared as the moment's practice,
and the coach's words and video. Those land in ``exercise_coach_requests``,
which the rule never read, so a coach's share made after the speaker's last
answer stayed off the page until the speaker answered something else. The
lane applies the released request chain (0385, 0397, 0402, 0403, 0408), so
the coach here answers and shares through the real writers.

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
# The moment the coach is asked about, and the coach. Any text ids: the
# request names its take and snippet by text, as released.
SNIPPET = "60000000-0000-4000-8000-000000000001"
COACH = "70000000-0000-4000-8000-000000000001"

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
        cursor.execute("DELETE FROM public.exercise_coach_requests")


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


def _other_arc_take(db) -> str:
    """A spoken take of some other project, for the per-arc checks."""
    take = str(uuid4())
    with db.cursor() as cursor:
        cursor.execute(
            "INSERT INTO public.v2_sessions(id,user_id,owner_principal_id,"
            "project_id,arc_id,take_index,analysis_state,recording_kind) "
            "VALUES(%s,%s,%s,%s,%s,1,'ready','spoken')",
            (take, ACTOR, PRINCIPAL, PROJECT, str(uuid4())))
    return take


def _raise_request(db, take: str = TAKE) -> str:
    """The moment's coach request, raised the way the open and the judgement
    raise it (0408's writer, insert-once). Returns its id."""
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT (public.request_exercise_from_coach_v3("
            "%s,%s,%s,'nothing_targets_it','error','open',NULL,"
            "ARRAY['pace'],'{}'::jsonb)).id",
            (ACTOR, take, SNIPPET))
        return str(cursor.fetchone()[0])


def _coach_answers(db, request_id: str, resolution: str, *, share: bool,
                   exercise_id=None, answer_text=None) -> None:
    """The coach's one answer to a request, and the share when asked for,
    through the released writer (0403). Repeating the same answer with
    ``share`` is how a coach shares an answer given earlier."""
    with db.cursor() as cursor:
        cursor.execute(
            "SELECT public.resolve_exercise_coach_request_v2("
            "%s,%s,%s,%s,%s,%s,%s)",
            (request_id, COACH, resolution, exercise_id,
             1 if exercise_id else None, share, answer_text))


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
    other_take = _other_arc_take(db)
    with db.cursor() as cursor:
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


# ── what the coach made of a bookmark (0428) ──────────────────────────────
#
# A coach's answer and share write `exercise_coach_requests` and nothing the
# speaker writes, so every case below served the block from before the
# coach until 0428 named that table in the rule.


def test_a_coach_share_after_the_bake_retires_it(db):
    """THE DEFECT. The coach chose an exercise before the bake and shared it
    after. The stored block still carried the open request ("your coach is
    working on it") and no exercise, and served it until the speaker happened
    to answer something else."""
    _clean(db)
    snapshot = _publish(db)
    request = _raise_request(db)
    _coach_answers(db, request, "exercise_chosen", share=False,
                   exercise_id="ex-coach-1")
    _write(db, snapshot)
    assert _read(db, snapshot) is not None, "fresh until the share"
    _coach_answers(db, request, "exercise_chosen", share=True,
                   exercise_id="ex-coach-1")
    assert _read(db, snapshot) is None


def test_a_coach_answer_in_words_shared_after_the_bake_retires_it(db):
    """The words, and the video with them, ride `coach_answer` once shared
    (0402, 0403). Answered and shared in one call."""
    _clean(db)
    snapshot = _publish(db)
    request = _raise_request(db)
    _write(db, snapshot)
    _coach_answers(db, request, "line_written", share=True,
                   answer_text="You held the pause and landed the point.")
    assert _read(db, snapshot) is None


def test_a_coach_answer_without_a_share_retires_it(db):
    """Nothing reaches the speaker unshared, but the request the block
    carries moves from open to answered, and that is on the page too."""
    _clean(db)
    snapshot = _publish(db)
    request = _raise_request(db)
    _write(db, snapshot)
    _coach_answers(db, request, "no_safe_match", share=False)
    assert _read(db, snapshot) is None


def test_a_request_raised_after_the_bake_retires_it(db):
    """Raised at the open (F1) or at the judgement: the open request rides
    the bookmark as the coach's promise, so its arrival changes the block."""
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    _raise_request(db)
    assert _read(db, snapshot) is None


def test_a_coach_share_during_the_computation_retires_the_bake(db):
    """0351's window holds for the coach as for the speaker: a share
    committed while the Manager ran was never seen by it."""
    _clean(db)
    snapshot = _publish(db)
    request = _raise_request(db)
    _coach_answers(db, request, "exercise_chosen", share=True,
                   exercise_id="ex-coach-1")
    _write(db, snapshot, computed_over_ms=60_000)
    assert _read(db, snapshot) is None


def test_a_coach_share_before_the_bake_leaves_it_fresh(db):
    """The flip side: a request raised, answered and shared before the
    computation began is already in the block, and the bake serves."""
    _clean(db)
    snapshot = _publish(db)
    request = _raise_request(db)
    _coach_answers(db, request, "exercise_chosen", share=True,
                   exercise_id="ex-coach-1")
    _write(db, snapshot)
    assert _read(db, snapshot) is not None


def test_another_arc_s_coach_share_leaves_this_bake_alone(db):
    """Per arc, like every other branch of the rule: a coach answering on
    one project costs no other project its fast open."""
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    request = _raise_request(db, take=_other_arc_take(db))
    _coach_answers(db, request, "line_written", share=True,
                   answer_text="Steady and clear.")
    assert _read(db, snapshot) is not None


def test_a_coach_share_is_never_taken_back(db):
    """WHY THE RULE HAS NO REVOCATION TIME. The database refuses to unset a
    share (0385's guard), so there is no withdrawal for the rule to miss. If
    that ever changes, this fails first, and the rule must learn the time of
    the withdrawal before the change ships."""
    _clean(db)
    request = _raise_request(db)
    _coach_answers(db, request, "exercise_chosen", share=True,
                   exercise_id="ex-coach-1")
    with db.cursor() as cursor:
        with pytest.raises(psycopg2.errors.RaiseException) as caught:
            cursor.execute(
                "UPDATE public.exercise_coach_requests SET shared_at = NULL "
                "WHERE id = %s", (request,))
    assert "ALREADY_SHARED" in str(caught.value)


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
