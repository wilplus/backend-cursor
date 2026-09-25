"""Training copies are copies (0375, SPEC-training-corpus §4, P3).

Run on the released rehearsal lane, after tests/test_training_consent_postgres.py
has registered the test training policy. Pins:

  * SPEC §10 invariant 4: no column of training_corpus_items is a foreign key
    to a product table;
  * the one door refuses without an active training yes, without an active
    `training_corpus` retention rule, and after a withdrawal;
  * a copy is recorded once per (grant, kind, source), and a changed source
    is refused rather than overwritten;
  * shape: audio needs its object, a coach label needs the coach provenance,
    source material carries none;
  * the content never changes; only the purge state moves, and only forward;
  * browser roles reach nothing.
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

from tests.test_training_consent_postgres import (
    TOGGLE_COPY, TOGGLE_SHA, TRAINING_POLICY, _action, _principal, _receipt,
)

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

PRODUCT_TABLES = {"v2_sessions", "projects", "takes", "recording_attempts",
                  "snippets", "charisma_snippets", "ml_consent_snapshots"}


@pytest.fixture(scope="module")
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


@pytest.fixture(scope="module")
def processing_version(db):
    return _one(db, "SELECT version FROM public.processing_policy_versions "
                    "ORDER BY created_at LIMIT 1")


@pytest.fixture(scope="module")
def training_policy(db, processing_version):
    # Registered by the consent suite, which runs first in this lane; the
    # function refuses a second registration with a different start.
    if _one(db, "SELECT version FROM public.ml_consent_policies WHERE version = %s",
            (TRAINING_POLICY,)):
        return TRAINING_POLICY
    return _one(db, """
        SELECT public.configure_mlc2_training_consent_policy_v1(
            'training-approval-test', %s, %s, %s, 'terms-t', 'privacy-t',
            'founder+counsel', now(), ARRAY['PL'], 'evidence/training.pdf',
            %s, %s, now() - interval '1 minute')""",
        (TOGGLE_SHA, TOGGLE_COPY, TRAINING_POLICY, "e" * 64, processing_version))


def _grant(db, principal):
    return str(_one(db, """
        SELECT (public.record_mlc2_training_consent_grant_v2(
            %s, %s, 'PL', 'terms-t', 'privacy-t', 'settings/training', 'test',
            %s::jsonb, now() - interval '1 second', %s)).id""",
        (principal, TRAINING_POLICY, _action(), f"g-{uuid.uuid4()}")))


def _artifact(db):
    return _one(db, """
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256)
        VALUES ('retention_schedule', 'corpus-' || gen_random_uuid(),
                'rehearsal', now(), 'rehearsal/retention.pdf', %s)
        RETURNING id""", ("a" * 64,))


@pytest.fixture(scope="module")
def active_rule(db):
    return _one(db, """
        INSERT INTO public.data_retention_rules (
            rule_code, evidence_category, retention_until_rule,
            legal_artifact_id, active)
        VALUES ('training_corpus', 'training_corpus',
                'until the training yes is withdrawn or the account is erased',
                %s, true)
        ON CONFLICT (rule_code) DO UPDATE SET active = true
        RETURNING id""", (_artifact(db),))


@pytest.fixture
def yes(db, training_policy, processing_version):
    principal = _principal(db)
    _receipt(db, principal, processing_version)
    return principal, _grant(db, principal)


def _item(principal, grant, **over):
    item = {
        "p": principal, "g": grant, "project": str(uuid.uuid4()),
        "take": str(uuid.uuid4()), "ref": f"snippet:{uuid.uuid4()}:transcript",
        "sha": "1" * 64, "kind": "transcript_span", "prov": None,
        "content": json.dumps({"text": "hello there"}), "provider": None,
        "bucket": None, "key": None, "osha": None,
    }
    item.update(over)
    return item


def _record(db, item):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT * FROM public.record_training_corpus_item_v1(
                %(p)s, %(g)s, %(project)s, %(take)s, %(ref)s, %(sha)s,
                %(kind)s, %(prov)s, %(content)s::jsonb, %(provider)s,
                %(bucket)s, %(key)s, %(osha)s)""", item)
        return dict(cur.fetchone())


def test_no_column_is_a_foreign_key_to_a_product_table(db):
    referenced = {row for (row,) in _all(db, """
        SELECT confrelid::regclass::text FROM pg_constraint
         WHERE conrelid = 'public.training_corpus_items'::regclass
           AND contype = 'f'""")}
    assert referenced == {"owner_principals", "ml_consent_events",
                          "data_retention_rules"}
    assert not referenced & PRODUCT_TABLES


def _all(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def test_no_copy_without_an_active_retention_rule(db, yes):
    principal, grant = yes
    conn = psycopg2.connect(DSN)
    try:
        with conn.cursor() as cur:  # one transaction, rolled back
            cur.execute("""
                UPDATE public.data_retention_rules SET active = false
                 WHERE rule_code = 'training_corpus'""")
            with pytest.raises(psycopg2.Error,
                               match="TRAINING_CORPUS_RETENTION_RULE_INACTIVE"):
                _record(conn, _item(principal, grant))
    finally:
        conn.rollback()
        conn.close()


def test_no_copy_without_an_active_yes(db, active_rule, training_policy):
    stranger = _principal(db)
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_NO_ACTIVE_YES"):
        _record(db, _item(stranger, str(uuid.uuid4())))


def test_no_copy_under_a_grant_that_is_not_the_current_one(db, active_rule, yes):
    principal, _ = yes
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_NO_ACTIVE_YES"):
        _record(db, _item(principal, str(uuid.uuid4())))


def test_a_copy_is_recorded_once_and_its_source_cannot_change(db, active_rule, yes):
    principal, grant = yes
    item = _item(principal, grant)
    first = _record(db, item)
    assert first["state"] == "active"
    assert first["consent_state"]["active"] is True
    assert first["retention_rule_id"] == active_rule
    assert _record(db, item)["id"] == first["id"]
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_SOURCE_CHANGED"):
        _record(db, dict(item, sha="2" * 64))


def test_no_copy_after_the_yes_is_withdrawn(db, active_rule, yes):
    principal, grant = yes
    _one(db, """
        SELECT (public.record_mlc2_consent_withdrawal_v2(
            %s, %s, 'pooled_model_improvement', 'settings/training', 'test',
            '{"control": "training_toggle", "accepted": false}'::jsonb,
            now(), %s)).id""", (principal, grant, f"w-{uuid.uuid4()}"))
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_NO_ACTIVE_YES"):
        _record(db, _item(principal, grant))


@pytest.mark.parametrize("over", [
    # Audio without its object.
    {"kind": "audio_segment", "content": None},
    # Audio outside the corpus prefix.
    {"kind": "audio_segment", "content": None, "provider": "r2", "bucket": "b",
     "key": "willab_lab/x.wav", "osha": "3" * 64},
    # A label that is not the coach's.
    {"kind": "coach_label", "prov": "owner_routing",
     "content": json.dumps({"value": "yes"})},
    # Source material claiming a label provenance.
    {"prov": "machine"},
])
def test_the_shape_of_each_kind_is_enforced(db, active_rule, yes, over):
    principal, grant = yes
    with pytest.raises(psycopg2.Error):
        _record(db, _item(principal, grant, **over))


def test_audio_and_coach_label_copies_are_accepted(db, active_rule, yes):
    principal, grant = yes
    audio = _record(db, _item(
        principal, grant, kind="audio_segment", content=None,
        ref=f"snippet:{uuid.uuid4()}:audio", provider="r2", bucket="lab",
        key=f"training-corpus/{principal}/{grant}/clip.wav", osha="4" * 64))
    assert audio["storage_key"].startswith("training-corpus/")
    label = _record(db, _item(
        principal, grant, kind="coach_label", prov="coach",
        ref=f"snippet:{uuid.uuid4()}:coach_label:yes",
        content=json.dumps({"value": "yes", "rater_role": "coach"})))
    assert label["label_provenance"] == "coach"


def test_content_never_changes_and_state_only_moves_forward(db, active_rule, yes):
    principal, grant = yes
    row = _record(db, _item(principal, grant))
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_ITEM_IMMUTABLE"):
        _one(db, "UPDATE public.training_corpus_items SET source_ref = 'x' "
                 "WHERE id = %s RETURNING 1", (row["id"],))
    _one(db, "UPDATE public.training_corpus_items SET state = 'purged' "
             "WHERE id = %s RETURNING 1", (row["id"],))
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_STATE_CANNOT_GO_BACK"):
        _one(db, "UPDATE public.training_corpus_items SET state = 'active' "
                 "WHERE id = %s RETURNING 1", (row["id"],))


def test_browser_roles_reach_nothing(db, yes):
    principal, grant = yes
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            for sql, args in (
                ("SELECT 1 FROM public.training_corpus_items LIMIT 1", ()),
                ("SELECT public.record_training_corpus_item_v1(%s, %s, 'p', 't', "
                 "'r', %s, 'transcript_span', NULL, '{\"text\": \"x\"}'::jsonb, "
                 "NULL, NULL, NULL, NULL)", (principal, grant, "1" * 64)),
            ):
                cur.execute(f"SET ROLE {role}")
                try:
                    with pytest.raises(psycopg2.Error, match="permission denied"):
                        cur.execute(sql, args)
                finally:
                    cur.execute("RESET ROLE")
        cur.execute("SET ROLE service_role")
        try:
            with pytest.raises(psycopg2.Error, match="permission denied"):
                cur.execute("INSERT INTO public.training_corpus_items "
                            "(source_ref) VALUES ('x')")
        finally:
            cur.execute("RESET ROLE")
