"""
STORY    As a speaker, I want training copies made only while my training yes
         is active, so that withdrawing stops any new copy.
         (Critical path: consent.)
OUTCOME
  O1  With an active yes (and the corpus retention rule in force) a copy is
      made, stamped with the yes it was made under.
  O2  No copy without an active yes, and none after the yes is withdrawn.
  O3  A source is copied once: copying it again returns the same copy, and a
      changed source is refused rather than overwritten.
  O4  A copy's content never changes; only its purge state moves, forward.
  O5  The copies hold no foreign key to a product table (lineage by value),
      and browser roles reach neither the table nor the door.
PROVES   O1 -> test_an_active_yes_makes_a_copy
         O2 -> test_no_copy_without_an_active_yes
            -> test_no_copy_after_the_yes_is_withdrawn
         O3 -> test_a_source_is_copied_once
         O4 -> test_a_copy_never_changes_and_its_state_only_moves_forward
         O5 -> test_no_product_foreign_keys_and_no_browser_access
WHY      0375 (SPEC-training-corpus section 4, P3; invariant 4).

Runs on the released rehearsal lane after tests/test_training_consent_postgres.py,
which registers the test training policy (made here if it did not run).
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

from tests.test_training_consent_postgres import (
    TOGGLE_COPY,
    TOGGLE_SHA,
    TRAINING_POLICY,
    _action,
    _principal,
    _receipt,
)

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)


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


def test_no_copy_without_an_active_yes(db, active_rule, training_policy):
    stranger = _principal(db)
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_NO_ACTIVE_YES"):
        _record(db, _item(stranger, str(uuid.uuid4())))


def test_no_copy_after_the_yes_is_withdrawn(db, active_rule, yes):
    principal, grant = yes
    _one(db, """
        SELECT (public.record_mlc2_consent_withdrawal_v2(
            %s, %s, 'pooled_model_improvement', 'settings/training', 'test',
            '{"control": "training_toggle", "accepted": false}'::jsonb,
            now(), %s)).id""", (principal, grant, f"w-{uuid.uuid4()}"))
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_NO_ACTIVE_YES"):
        _record(db, _item(principal, grant))


def test_an_active_yes_makes_a_copy(db, active_rule, yes):
    principal, grant = yes
    copy = _record(db, _item(principal, grant))
    assert copy["state"] == "active"
    assert str(copy["training_grant_event_id"]) == grant
    assert copy["consent_state"]["active"] is True
    assert copy["content"] == {"text": "hello there"}


def test_a_source_is_copied_once(db, active_rule, yes):
    principal, grant = yes
    item = _item(principal, grant)
    first = _record(db, item)
    again = _record(db, item)
    assert again["id"] == first["id"]
    assert _one(db, "SELECT count(*) FROM public.training_corpus_items "
                    "WHERE training_grant_event_id = %s", (grant,)) == 1
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_SOURCE_CHANGED"):
        _record(db, {**item, "sha": "2" * 64})


def test_a_copy_never_changes_and_its_state_only_moves_forward(db, active_rule, yes):
    principal, grant = yes
    copy = _record(db, _item(principal, grant))["id"]
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_ITEM_IMMUTABLE"):
        _one(db, """UPDATE public.training_corpus_items
                       SET content = '{"text": "edited"}'::jsonb
                     WHERE id = %s RETURNING id""", (copy,))
    _one(db, "UPDATE public.training_corpus_items SET state = 'purge_pending' "
             "WHERE id = %s RETURNING id", (copy,))
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_STATE_CANNOT_GO_BACK"):
        _one(db, "UPDATE public.training_corpus_items SET state = 'active' "
                 "WHERE id = %s RETURNING id", (copy,))
    assert _one(db, "SELECT state FROM public.training_corpus_items WHERE id = %s",
                (copy,)) == "purge_pending"


def test_no_product_foreign_keys_and_no_browser_access(db):
    with db.cursor() as cur:
        cur.execute("""
            SELECT confrelid::regclass::text FROM pg_constraint
             WHERE conrelid = 'public.training_corpus_items'::regclass
               AND contype = 'f' ORDER BY 1""")
        targets = [r[0] for r in cur.fetchall()]
    # Only the consent and retention records it is governed by.
    assert targets == ["data_retention_rules", "ml_consent_events",
                       "owner_principals"]
    door = ("public.record_training_corpus_item_v1(uuid, uuid, text, text, "
            "text, text, text, text, jsonb, text, text, text, text)")
    for role in ("anon", "authenticated"):
        assert _one(db, "SELECT has_table_privilege(%s, "
                        "'public.training_corpus_items', 'SELECT')", (role,)) is False
        assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                    (role, door)) is False
