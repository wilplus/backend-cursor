"""
STORY    As a speaker, I want each Take 2 rewrite of my Ideal Text stored as a
         Paragraph revision tied to that Take, with my locked helper words
         still locked afterwards, so that every old version stays in my history.
OUTCOME
  O1  Never-5: a take_rewrite revision is kept beside the older ones and
      names its Take; the Ideal Text read points at it as the current one.
  O2  The Ideal Text read takes a Paragraph's lock from the Paragraph row, so
      a locked Paragraph stays locked after a Take rewrite and an unlocked one
      is not locked by an old 'lock' revision.
PROVES   O1 -> test_a_take_rewrite_is_kept_in_history_and_keeps_the_lock
         O2 -> test_a_take_rewrite_is_kept_in_history_and_keeps_the_lock
WHY      0416 (contract 14, 16): the core read used the newest revision as the
         lock, so Take 2 unlocked a locked Paragraph on the cold open.
         The Take-2 writer itself is proven in
         test_take_two_rewrites_an_edited_slide_postgres.py.
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


@pytest.fixture
def cur():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cursor:
            yield cursor
    finally:
        conn.rollback()
        conn.close()


def _speaker_with_a_published_take_two(cur) -> tuple[str, str, str]:
    """A project, its Take 2 and the published document head, all rolled back."""
    user, principal, project, take, snapshot = (str(uuid.uuid4()) for _ in range(5))
    cur.execute("INSERT INTO public.owner_principals(id, user_id) VALUES (%s, %s)",
                (principal, user))
    cur.execute("INSERT INTO public.projects(id, owner_principal_id, display_name) "
                "VALUES (%s, %s, 'Talk')", (project, principal))
    cur.execute("INSERT INTO public.v2_sessions(id, arc_id, user_id, take_index) "
                "VALUES (%s, %s, %s, 2)", (take, project, user))
    cur.execute(
        "INSERT INTO public.ideal_text_document_snapshots(id, arc_id, actor_id, "
        "acquisition_principal_id, project_id, source_take_session_id, version, "
        "source_generation, source_fingerprint_sha256, payload_sha256, payload) "
        "VALUES (%s, %s, %s, %s, %s, %s, 1, 1, %s, %s, '{}')",
        (snapshot, project, user, principal, project, take, "d" * 64, "e" * 64))
    cur.execute("INSERT INTO public.ideal_text_document_heads(arc_id, actor_id, "
                "snapshot_id) VALUES (%s, %s, %s)", (project, user, snapshot))
    return user, project, take


def _paragraph(cur, user, project, ord_, text, *, locked) -> str:
    part = str(uuid.uuid4())
    cur.execute("INSERT INTO public.ideal_text_part(id, arc_id, user_id, ord, text, "
                "locked_at) VALUES (%s, %s, %s, %s, %s, "
                "CASE WHEN %s THEN now() END)", (part, project, user, ord_, text, locked))
    return part


def _revision(cur, user, project, part, action, text, take=None) -> str:
    cur.execute(
        "INSERT INTO public.ideal_text_part_revision(arc_id, user_id, part_id, "
        "action, text, take_session_id, review_version) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
        (project, user, part, action, text, take, 2 if take else None))
    return str(cur.fetchone()[0])


def test_a_take_rewrite_is_kept_in_history_and_keeps_the_lock(cur):
    user, project, take = _speaker_with_a_published_take_two(cur)
    locked = _paragraph(cur, user, project, 0, "We launched in March.", locked=True)
    _revision(cur, user, project, locked, "lock", "We shipped it in March.")
    rewrite = _revision(cur, user, project, locked, "take_rewrite",
                        "We launched in March.", take)
    # Locked once, unlocked since: the row says open, the newest revision says lock.
    opened = _paragraph(cur, user, project, 1, "The plan held.", locked=False)
    _revision(cur, user, project, opened, "lock", "The plan held.")
    # The owner's text exists, written as replication would (its one writer
    # needs the MLC-3 rollout this lane does not mint); the read is under test.
    cur.execute("SET session_replication_role = replica")
    cur.execute("INSERT INTO public.user_arc_ideal_notes(arc_id, user_id, user_text, "
                "user_text_version, user_text_revision) VALUES (%s, %s, %s, 1, 1)",
                (project, user, "We launched in March.\n\nThe plan held."))
    cur.execute("SET session_replication_role = DEFAULT")

    # O1: the history keeps both versions, the newest naming Take 2.
    cur.execute("SELECT action, text, take_session_id::text FROM "
                "public.ideal_text_part_revision WHERE part_id = %s ORDER BY id",
                (locked,))
    assert cur.fetchall() == [("lock", "We shipped it in March.", None),
                              ("take_rewrite", "We launched in March.", take)]

    cur.execute("SELECT public.read_ideal_text_document_core_v2(%s, %s)", (project, user))
    parts = cur.fetchone()[0]["dynamic_overlay"]["owner_edit"]["parts"]
    assert [(p["id"], p["text"], p["locked"]) for p in parts] == [
        (locked, "We launched in March.", True),   # O2: the lock survives Take 2
        (opened, "The plan held.", False),         # O2: an old 'lock' is not the lock
    ]
    assert parts[0]["current_part_revision_id"] == rewrite
