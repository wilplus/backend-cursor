"""A subject with a practice recording can actually be erased.

B-4 (major), audit 2026-09-22.

`services/data_purge.py` has emitted storage targets carrying
`source_relation = 'processing_practice_objects'` since migration 0334 gave
practice audio its own registry. Neither function that consumes them knew the
relation existed:

  * `freeze_phase1_purge_inventory_v4` accepted `processing_audio_objects` and
    `processing_orphan_objects`, and its `ELSE` raised
    `PURGE_STORAGE_TARGET_SOURCE_INVALID`;
  * `mark_phase1_storage_object_purged_v1` had the same two branches and
    raised `PURGE_OBJECT_SOURCE_INVALID`.

So for a subject whose only stored audio is a practice recording the request
was written, the freeze refused, and the row sat at `requested` for ever with
nothing erased. Not a partial deletion — no deletion, and a record saying one
had been asked for. The table was always ready: 0334 gave it `deleted_at`,
commented "stamped by the purge once the object is gone from storage, mirrors
the sibling tables". Only the two functions were never told.

These cases EXECUTE the real functions rather than reading their text. The
whole finding is that a function refuses something, and only calling it can
show that it no longer does. The target must be a disposable local database.
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import pytest

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


class TestThePurgeReachesAPracticeRecording:

    def test_the_freeze_takes_a_practice_object_into_the_manifest(self, db, subject):
        """Before 0353 this raised PURGE_STORAGE_TARGET_SOURCE_INVALID and the
        erasure never started."""
        graph = _one(db, "SELECT public.resolve_phase1_purge_subject_graph_v2(%s)",
                     (subject["principal"],))
        result = _one(db, """
            SELECT public.freeze_phase1_purge_inventory_v4(
                %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::text[])""",
            (subject["request"], RESOLVER, "f" * 64, json.dumps(graph),
             json.dumps([subject["target"]]), "e" * 64, []))

        assert result["state"] == "in_progress", (
            "the freeze left the request short of in_progress: %r" % (result,))
        assert result["unknown_target_count"] == 0, (
            "the practice object was classified as an unknown target")
        assert _one(db, """
            SELECT state FROM public.data_purge_targets
             WHERE purge_request_id = %s
               AND metadata->>'source_id' = %s""",
            (subject["request"], str(subject["object_id"]))) == "pending", (
            "the practice object never reached the frozen manifest")

    def test_the_freeze_still_refuses_an_object_that_is_not_the_subjects(self, db, subject):
        """The new branch verifies ownership exactly as its two siblings do.

        Without this the fix would be a hole: anyone able to name an object id
        could have it frozen into someone else's erasure.
        """
        stranger = _one(db, """
            INSERT INTO public.owner_principals (id, user_id)
            VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
        other_request = _one(db, """
            INSERT INTO public.data_purge_requests (
                acquisition_principal_id, trigger_kind, idempotency_key)
            VALUES (%s, 'account_deletion', %s) RETURNING id""",
            (stranger, str(uuid.uuid4())))
        graph = _one(db, "SELECT public.resolve_phase1_purge_subject_graph_v2(%s)",
                     (stranger,))

        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _one(db, """
                SELECT public.freeze_phase1_purge_inventory_v4(
                    %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::text[])""",
                (other_request, RESOLVER, "f" * 64, json.dumps(graph),
                 json.dumps([subject["target"]]), "e" * 64, []))
        assert "PURGE_STORAGE_TARGET_GRAPH_MISMATCH" in str(raised.value)

    def test_the_mark_stamps_the_practice_row_deleted(self, db, subject):
        """Before 0353 this raised PURGE_OBJECT_SOURCE_INVALID, so even a
        storage delete that had succeeded could not be recorded."""
        result = _one(db, """
            SELECT public.mark_phase1_storage_object_purged_v1(
                %s, 'processing_practice_objects', %s, 'r2', %s, %s, %s)""",
            (subject["request"], subject["object_id"], subject["bucket"],
             subject["key"], subject["sha"]))

        assert result["deleted_at_recorded"] is True
        assert _one(db, """
            SELECT deleted_at IS NOT NULL
              FROM public.processing_practice_objects WHERE id = %s""",
            (subject["object_id"],)) is True, (
            "the object was reported purged but the row was never stamped")

    def test_the_mark_refuses_a_second_stamp_on_the_same_object(self, db, subject):
        """`deleted_at IS NULL` guards the UPDATE for the same reason the
        orphan branch guards on status: a second mark for an object already
        erased is a mismatch to be surfaced, not a silent no-op."""
        _one(db, """
            SELECT public.mark_phase1_storage_object_purged_v1(
                %s, 'processing_practice_objects', %s, 'r2', %s, %s, %s)""",
            (subject["request"], subject["object_id"], subject["bucket"],
             subject["key"], subject["sha"]))

        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _one(db, """
                SELECT public.mark_phase1_storage_object_purged_v1(
                    %s, 'processing_practice_objects', %s, 'r2', %s, %s, %s)""",
                (subject["request"], subject["object_id"], subject["bucket"],
                 subject["key"], subject["sha"]))
        assert "PURGE_OBJECT_METADATA_MISMATCH" in str(raised.value)

    def test_an_unknown_relation_is_still_refused_by_both(self, db, subject):
        """0353 adds one relation; it does not open the door."""
        graph = _one(db, "SELECT public.resolve_phase1_purge_subject_graph_v2(%s)",
                     (subject["principal"],))
        invented = json.loads(json.dumps(subject["target"]))
        invented["metadata"]["source_relation"] = "processing_invented_objects"

        with pytest.raises(psycopg2.errors.RaiseException) as freeze_raised:
            _one(db, """
                SELECT public.freeze_phase1_purge_inventory_v4(
                    %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s::text[])""",
                (subject["request"], RESOLVER, "f" * 64, json.dumps(graph),
                 json.dumps([invented]), "e" * 64, []))
        assert "PURGE_STORAGE_TARGET_SOURCE_INVALID" in str(freeze_raised.value)

        with pytest.raises(psycopg2.errors.RaiseException) as mark_raised:
            _one(db, """
                SELECT public.mark_phase1_storage_object_purged_v1(
                    %s, 'processing_invented_objects', %s, 'r2', %s, %s, %s)""",
                (subject["request"], subject["object_id"], subject["bucket"],
                 subject["key"], subject["sha"]))
        assert "PURGE_OBJECT_SOURCE_INVALID" in str(mark_raised.value)
