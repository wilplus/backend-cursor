"""F4: the bundled-era erasure, executed on a disposable database.

migrations/pending/erase_bundled_era_corpus.sql is never in the manifest; it
is applied by hand once the founder authorises it and counsel has reviewed
the prepared list. These cases apply it to the rehearsal database, against
stand-in corpus tables carrying the same retired-write guard production has,
and pin what makes it safe to run once:

  * preview counts, and the consent records are named as kept;
  * prepare snapshots exact rows by primary key and every stored-object
    reference, under a hash;
  * apply refuses: a wrong hash, no founder reference, no counsel reference,
    no record of external copies, any listed object without an outcome, and
    a snapshot whose rows changed since it was prepared;
  * apply deletes exactly the snapshot past the guard — and the guard is on
    again afterwards;
  * browser roles call nothing; service_role reaches only the preview and the
    storage script's two doors.
"""
from __future__ import annotations

import json
import os
import pathlib

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)
PENDING = (pathlib.Path(__file__).resolve().parents[1]
           / "migrations" / "pending" / "erase_bundled_era_corpus.sql")


@pytest.fixture(scope="module")
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    with conn.cursor() as cur:
        # Stand-ins with the retired-write guard production puts on the corpus.
        cur.execute("""
            CREATE TABLE IF NOT EXISTS public.training_labels (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                audio_path TEXT, label_key TEXT);
            CREATE TABLE IF NOT EXISTS public.model_versions (
                id BIGSERIAL PRIMARY KEY, artifact_key TEXT);
            CREATE TABLE IF NOT EXISTS public.user_consents (
                user_id UUID NOT NULL, terms_version TEXT NOT NULL);
        """)
        for table in ("training_labels", "model_versions"):
            cur.execute(f"""
                DROP TRIGGER IF EXISTS {table}_retired_write_guard ON public.{table};
                CREATE TRIGGER {table}_retired_write_guard
                BEFORE INSERT OR UPDATE OR DELETE ON public.{table}
                FOR EACH ROW EXECUTE FUNCTION public.reject_retired_direction_write_v1();
            """)
        cur.execute(PENDING.read_text(encoding="utf-8"))
        cur.execute(PENDING.read_text(encoding="utf-8"))  # applied twice: idempotent
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
def corpus(db):
    """Fresh stand-in rows, written past the guard the way old code wrote them."""
    with db.cursor() as cur:
        cur.execute("TRUNCATE public.bundled_era_erasure_objects, "
                    "public.bundled_era_erasure_snapshots, public.training_labels, "
                    "public.model_versions, public.user_consents")
        cur.execute("ALTER TABLE public.training_labels DISABLE TRIGGER training_labels_retired_write_guard")
        cur.execute("ALTER TABLE public.model_versions DISABLE TRIGGER model_versions_retired_write_guard")
        cur.execute("""
            INSERT INTO public.training_labels (audio_path, label_key) VALUES
              ('audio_recordings/a.webm', 'lbl'), ('audio_recordings/b.webm', NULL),
              (NULL, NULL)""")
        cur.execute("INSERT INTO public.model_versions (artifact_key) VALUES ('models/m1.bin')")
        cur.execute("ALTER TABLE public.training_labels ENABLE TRIGGER training_labels_retired_write_guard")
        cur.execute("ALTER TABLE public.model_versions ENABLE TRIGGER model_versions_retired_write_guard")
        cur.execute("""
            INSERT INTO public.user_consents VALUES
              (gen_random_uuid(), '1.2'), (gen_random_uuid(), '1.2'),
              (gen_random_uuid(), '3.1')""")
    return db


def _prepare(db):
    return _one(db, "SELECT public.prepare_bundled_era_erasure_v1()")


def _record_all(db, snapshot):
    refs = _one(db, "SELECT public.bundled_era_erasure_storage_refs_v1(%s)", (snapshot,))
    for ref in refs:
        _one(db, "SELECT public.record_bundled_era_object_v1(%s, %s, 'deleted', 'test')",
             (snapshot, ref))
    return refs


def _apply(db, snapshot, sha, founder="F4-2026-09-25", counsel="counsel-memo-1",
           external='[{"provider": "openai", "action": "none found"}]'):
    return _one(db, """
        SELECT public.apply_bundled_era_erasure_v1(%s, %s, %s, %s, %s::jsonb)""",
        (snapshot, sha, founder, counsel, external))


def test_preview_counts_and_names_what_is_kept(corpus):
    preview = _one(corpus, "SELECT public.preview_bundled_era_erasure_v1()")
    assert preview["erase_rows"]["training_labels"] == 3
    assert preview["erase_rows"]["model_versions"] == 1
    assert {"terms_version": "1.2", "people": 2} in preview["terms_acceptances"]
    assert preview["kept"] == ["user_consents", "ml_consent_events"]


def test_prepare_lists_exact_rows_and_every_stored_reference(corpus):
    prepared = _prepare(corpus)
    assert prepared["rows"] == {"training_labels": 3, "model_versions": 1}
    refs = _one(corpus, "SELECT public.bundled_era_erasure_storage_refs_v1(%s)",
                (prepared["snapshot_id"],))
    # label_key is a *key* column too: listed, and the storage script decides.
    assert refs == sorted(["audio_recordings/a.webm", "audio_recordings/b.webm",
                           "lbl", "models/m1.bin"])


@pytest.mark.parametrize("override, code", [
    ({"sha": "0" * 64}, "BUNDLED_ERA_SNAPSHOT_HASH_MISMATCH"),
    ({"founder": ""}, "BUNDLED_ERA_FOUNDER_AUTHORIZATION_REQUIRED"),
    ({"counsel": " "}, "BUNDLED_ERA_COUNSEL_REVIEW_REQUIRED"),
    ({"external": "{}"}, "BUNDLED_ERA_EXTERNAL_COPIES_RECORD_REQUIRED"),
])
def test_apply_refuses_without_each_approval(corpus, override, code):
    prepared = _prepare(corpus)
    _record_all(corpus, prepared["snapshot_id"])
    args = {"sha": prepared["sha256"], **override}
    sha = args.pop("sha")
    with pytest.raises(psycopg2.Error, match=code):
        _apply(corpus, prepared["snapshot_id"], sha, **args)
    assert _one(corpus, "SELECT count(*) FROM public.training_labels") == 3


def test_apply_refuses_while_a_file_has_no_recorded_outcome(corpus):
    prepared = _prepare(corpus)
    _one(corpus, "SELECT public.record_bundled_era_object_v1(%s, 'lbl', 'not_ours', 'id')",
         (prepared["snapshot_id"],))
    with pytest.raises(psycopg2.Error, match="BUNDLED_ERA_OBJECTS_NOT_RESOLVED:3"):
        _apply(corpus, prepared["snapshot_id"], prepared["sha256"])


def test_apply_refuses_a_snapshot_whose_rows_changed(corpus):
    prepared = _prepare(corpus)
    _record_all(corpus, prepared["snapshot_id"])
    with corpus.cursor() as cur:
        cur.execute("ALTER TABLE public.model_versions DISABLE TRIGGER model_versions_retired_write_guard")
        cur.execute("DELETE FROM public.model_versions")
        cur.execute("ALTER TABLE public.model_versions ENABLE TRIGGER model_versions_retired_write_guard")
    with pytest.raises(psycopg2.Error, match="BUNDLED_ERA_ROWS_CHANGED_SINCE_PREPARE:model_versions"):
        _apply(corpus, prepared["snapshot_id"], prepared["sha256"])
    assert _one(corpus, "SELECT count(*) FROM public.training_labels") == 3


def test_apply_deletes_exactly_the_snapshot_and_the_guard_is_back(corpus):
    prepared = _prepare(corpus)
    _record_all(corpus, prepared["snapshot_id"])
    with corpus.cursor() as cur:  # a row written after prepare is not in it
        cur.execute("ALTER TABLE public.training_labels DISABLE TRIGGER training_labels_retired_write_guard")
        cur.execute("INSERT INTO public.training_labels (label_key) VALUES ('late')")
        cur.execute("ALTER TABLE public.training_labels ENABLE TRIGGER training_labels_retired_write_guard")

    result = _apply(corpus, prepared["snapshot_id"], prepared["sha256"])

    assert result["deleted_rows"] == {"training_labels": 3, "model_versions": 1}
    assert _one(corpus, "SELECT count(*) FROM public.training_labels") == 1
    assert _one(corpus, "SELECT count(*) FROM public.user_consents") == 3
    with pytest.raises(psycopg2.Error, match="RETIRED_DIRECTION_PIPELINE_WRITE_FORBIDDEN"):
        _one(corpus, "DELETE FROM public.training_labels RETURNING 1")
    with pytest.raises(psycopg2.Error, match="BUNDLED_ERA_SNAPSHOT_ALREADY_APPLIED"):
        _apply(corpus, prepared["snapshot_id"], prepared["sha256"])
    applied = _one(corpus, """
        SELECT jsonb_build_object('founder', founder_authorization_ref,
                                  'counsel', counsel_review_ref)
          FROM public.bundled_era_erasure_snapshots WHERE id = %s""",
        (prepared["snapshot_id"],))
    assert applied == {"founder": "F4-2026-09-25", "counsel": "counsel-memo-1"}


def test_who_may_call_what(corpus):
    prepared = _prepare(corpus)
    snapshot = prepared["snapshot_id"]
    with corpus.cursor() as cur:
        for role in ("anon", "authenticated", "service_role"):
            for call, args in (
                ("SELECT public.prepare_bundled_era_erasure_v1()", ()),
                ("SELECT public.apply_bundled_era_erasure_v1(%s, %s, 'f', 'c', '[]'::jsonb)",
                 (snapshot, prepared["sha256"])),
            ):
                cur.execute(f"SET ROLE {role}")
                try:
                    with pytest.raises(psycopg2.Error, match="permission denied"):
                        cur.execute(call, args)
                finally:
                    cur.execute("RESET ROLE")
        for role in ("anon", "authenticated"):
            cur.execute(f"SET ROLE {role}")
            try:
                with pytest.raises(psycopg2.Error, match="permission denied"):
                    cur.execute("SELECT public.preview_bundled_era_erasure_v1()")
            finally:
                cur.execute("RESET ROLE")
        cur.execute("SET ROLE service_role")
        try:
            cur.execute("SELECT public.preview_bundled_era_erasure_v1()")
            cur.execute("SELECT public.bundled_era_erasure_storage_refs_v1(%s)", (snapshot,))
            cur.execute("SELECT public.record_bundled_era_object_v1(%s, 'lbl', 'not_ours', 'x')",
                        (snapshot,))
        finally:
            cur.execute("RESET ROLE")
    assert json.loads(json.dumps(prepared))["rows"]["training_labels"] == 3
