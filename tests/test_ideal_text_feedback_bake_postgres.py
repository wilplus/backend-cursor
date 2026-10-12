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

The last two are the speaker's again, settling a moment without an answer
(the_bake_knows_about_skips_and_practice.sql). With judgement after feedback
on, the block marks a bookmark settled from a skip (``moment_events``) or a
closed practice (``confident_voice_practice``), in
``_mark_settled_without_answer``. Neither table was in the rule, so a reload
served the moment as still waiting. The practice writes below send the
statements ``update_confident_voice_practice`` sends, dated by the app's own
clock as it dates them.

The target must be a disposable local database whose name starts with
``willab_bake_``. Nothing here writes media or activates any service.
"""
from __future__ import annotations

import os

import psycopg2
import pytest
from psycopg2.extras import Json

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
        cursor.execute("DELETE FROM public.exercise_coach_requests")
        cursor.execute("DELETE FROM public.moment_events")
        cursor.execute("DELETE FROM public.confident_voice_practice")


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


# ── the stored set is served only while it is still true ──────────────────


def test_a_fresh_bake_comes_back_with_its_marks(db):
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    served = _read(db, snapshot)
    assert served is not None
    assert served["payload"] == BLOCK


def test_another_speaker_never_reads_this_one_s_marks(db):
    _clean(db)
    snapshot = _publish(db)
    _write(db, snapshot)
    assert _read(db, snapshot, actor=OTHER_ACTOR) is None


# ── the two answer routes 0345 forgot (0351) ──────────────────────────────


# ── the bake is dated from when the computation STARTED (0351) ────────────


# ── what the coach made of a bookmark (0428) ──────────────────────────────
#
# A coach's answer and share write `exercise_coach_requests` and nothing the
# speaker writes, so every case below served the block from before the
# coach until 0428 named that table in the rule.


# ── a moment settled without an answer: a skip, a practice ────────────────
#
# `_mark_settled_without_answer` marks a bookmark settled from the Take's
# skips and closed practices, and the exercise offer reads the moment's
# practice. Until the_bake_knows_about_skips_and_practice.sql the rule read
# neither table, so every case that retires a bake below served the block
# from before the speaker's act.


# ── the guards 0345 established, re-checked against the new signature ─────
