"""
STORY    As a speaker whose only recording is a practice attempt, I want my
         deletion request to actually erase it, so that "delete my account"
         deletes everything, and nobody else can fold my recording into
         their erasure. (Deletion.)
OUTCOME
  O1  The freeze accepts my practice object (the request moves on, the
      target is pending), and marking it purged stamps deleted_at once.
  O2  Someone else's request cannot freeze my object.
  O3  Every target kind the orchestrator sends (FREEZE_TARGET_KINDS) is one
      the real freeze accepts; any other kind is filed unknown.
PROVES   O1 -> test_the_freeze_accepts_my_practice_object_and_the_mark_stamps_it
         O2 -> test_the_freeze_still_refuses_an_object_that_is_not_the_subjects
         O3 -> test_every_kind_the_orchestrator_sends_is_one_the_freeze_accepts
WHY      B-4 (audit 2026-09-22, 0354): the freeze and the mark raised
         SOURCE_INVALID for processing_practice_objects, so such a request sat
         at 'requested' forever with nothing erased. These cases EXECUTE the
         real functions on a disposable database (rehearsal tier, released lane).
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import pytest

from services.data_purge import FREEZE_TARGET_KINDS

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

RESOLVER = "phase1-purge-resolver-v4"


@pytest.fixture
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def _one(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return row[0] if row else None


@pytest.fixture
def subject(db):
    """One principal, one practice attempt, its stored object, one request.

    The smallest subject the finding is about: a speaker who recorded a
    practice attempt and nothing else, then asked to be erased.
    """
    principal = _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
    practice_id = _one(db, """
        INSERT INTO public.confident_voice_practice (
            id, owner_user_id, take_session_id)
        VALUES (gen_random_uuid(), gen_random_uuid(), gen_random_uuid())
        RETURNING id""")
    practice = _one(db, """
        INSERT INTO public.confident_voice_practice_attempt (id, practice_id)
        VALUES (gen_random_uuid(), %s) RETURNING id""", (practice_id,))
    key = f"confidence-practice/{uuid.uuid4()}/attempt.webm"
    sha = "b" * 64
    object_id = _one(db, """
        INSERT INTO public.processing_practice_objects (
            acquisition_principal_id, practice_attempt_id, storage_provider,
            bucket, object_key, byte_size, content_type, exact_bytes_sha256)
        VALUES (%s, %s, 'r2', 'practice-audio', %s, 4096, 'audio/webm', %s)
        RETURNING id""", (principal, practice, key, sha))
    request = _one(db, """
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s) RETURNING id""",
        (principal, str(uuid.uuid4())))
    return {
        "principal": principal, "object_id": object_id, "request": request,
        "bucket": "practice-audio", "key": key, "sha": sha,
        "target": {
            "target_kind": "r2_object",
            "target_ref": f"r2://practice-audio/{key}",
            "metadata": {
                "source_relation": "processing_practice_objects",
                "source_id": str(object_id), "provider": "r2",
                "bucket": "practice-audio", "key": key, "sha256": sha,
            },
        },
    }


def _freeze(db, request, graph, targets):
    return _one(db, """
        SELECT public.freeze_phase1_purge_inventory_v4(
            %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::text[])""",
        (request, RESOLVER, "f" * 64, json.dumps(graph), json.dumps(targets),
         "e" * 64, []))


def _graph(db, principal):
    return _one(db, "SELECT public.resolve_phase1_purge_subject_graph_v3(%s)", (principal,))


class TestThePurgeReachesAPracticeRecording:

    def test_the_freeze_accepts_my_practice_object_and_the_mark_stamps_it(self, db, subject):
        frozen = _freeze(db, subject["request"], _graph(db, subject["principal"]),
                         [subject["target"]])
        assert (frozen["state"], frozen["unknown_target_count"]) == ("in_progress", 0)
        assert _one(db, """
            SELECT state FROM public.data_purge_targets
             WHERE purge_request_id = %s AND target_ref = %s""",
            (subject["request"], subject["target"]["target_ref"])) == "pending"

        mark = """SELECT public.mark_phase1_storage_object_purged_v1(
                      %s, 'processing_practice_objects', %s, 'r2', %s, %s, %s)"""
        args = (subject["request"], subject["object_id"], subject["bucket"],
                subject["key"], subject["sha"])
        assert _one(db, mark, args)["deleted_at_recorded"] is True
        assert _one(db, "SELECT deleted_at IS NOT NULL FROM public.processing_practice_objects"
                        " WHERE id = %s", (subject["object_id"],)) is True
        with pytest.raises(psycopg2.errors.RaiseException, match="PURGE_OBJECT_METADATA_MISMATCH"):
            _one(db, mark, args)  # a second mark is a mismatch, not a silent no-op

    def test_the_freeze_still_refuses_an_object_that_is_not_the_subjects(self, db, subject):
        """Without this the fix would be a hole: anyone able to name an object
        id could have it frozen into someone else's erasure."""
        stranger = _one(db, """
            INSERT INTO public.owner_principals (id, user_id)
            VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
        other_request = _one(db, """
            INSERT INTO public.data_purge_requests (
                acquisition_principal_id, trigger_kind, idempotency_key)
            VALUES (%s, 'account_deletion', %s) RETURNING id""",
            (stranger, str(uuid.uuid4())))
        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _freeze(db, other_request, _graph(db, stranger), [subject["target"]])
        assert "PURGE_STORAGE_TARGET_GRAPH_MISMATCH" in str(raised.value)
        assert _one(db, "SELECT deleted_at FROM public.processing_practice_objects"
                        " WHERE id = %s", (subject["object_id"],)) is None

    def test_every_kind_the_orchestrator_sends_is_one_the_freeze_accepts(self, db, subject):
        """0362: the freeze files an unknown kind as `unknown`, and one unknown
        target stops the whole erasure."""
        graph = _graph(db, subject["principal"])

        def target(kind):
            code = f"kind_{kind}"
            return {"target_kind": kind, "target_ref": f"dependency:{code}",
                    "metadata": {"dependency_code": code, "relation": "some_table",
                                 "selector_column": "acquisition_principal_id",
                                 "locator_kind": "principal",
                                 "locator_values": graph["principal_ids"]}}

        frozen = _freeze(db, subject["request"], graph,
                         [target(k) for k in sorted(FREEZE_TARGET_KINDS)])
        assert (frozen["state"], frozen["unknown_target_count"]) == ("in_progress", 0)

        second = _one(db, """
            INSERT INTO public.data_purge_requests (
                acquisition_principal_id, trigger_kind, idempotency_key)
            VALUES (%s, 'account_deletion', %s) RETURNING id""",
            (subject["principal"], str(uuid.uuid4())))
        odd = _freeze(db, second, graph, [target("a_kind_sql_never_heard_of")])
        assert (odd["state"], odd["unknown_target_count"]) == ("review_required", 1)
