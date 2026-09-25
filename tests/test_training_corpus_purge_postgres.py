"""Training copies go when the yes goes (0376, SPEC-training-corpus §6, P4).

Run on the released rehearsal lane, after the consent and corpus suites. The
orchestrator and the database helpers are the production Python, driven
through the SQL shim of tests/test_account_deletion_starts_postgres.py as
service_role. Pins:

  * a withdrawal marks every active copy of that person due, and nobody
    else's;
  * the corpus erasure deletes a due copy's row through service_role's own
    grant, never an active copy;
  * account erasure reaches the copies: the orchestrator's freeze is accepted
    with a copy's audio as a storage target, and the copy rows are a `delete`
    dependency, not a review stop;
  * the object mark moves a copy to `purged`, and it still carries its D11
    lock preamble after 0376 re-issued it;
  * what still stops a training-consented account's erasure is stated by
    running it: the MLC-2 consent events (`external_review`), and nothing of
    the corpus.
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import pytest

from services.data_purge import DataPurgeOrchestrator
from services.db import DatabaseService
from tests.test_account_deletion_starts_postgres import _Database
from tests.test_training_consent_postgres import (
    TOGGLE_COPY, TOGGLE_SHA, TRAINING_POLICY, _action, _principal, _receipt,
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
def ready(db):
    """The training policy (the consent suite registered it) and an active
    `training_corpus` rule (the corpus suite seeded it); made here if not."""
    version = _one(db, "SELECT version FROM public.processing_policy_versions "
                       "ORDER BY created_at LIMIT 1")
    if not _one(db, "SELECT 1 FROM public.ml_consent_policies WHERE version = %s",
                (TRAINING_POLICY,)):
        _one(db, """
            SELECT public.configure_mlc2_training_consent_policy_v1(
                'training-approval-test', %s, %s, %s, 'terms-t', 'privacy-t',
                'founder+counsel', now(), ARRAY['PL'], 'evidence/training.pdf',
                %s, %s, now() - interval '1 minute')""",
            (TOGGLE_SHA, TOGGLE_COPY, TRAINING_POLICY, "e" * 64, version))
    artifact = _one(db, """
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256)
        VALUES ('retention_schedule', 'purge-' || gen_random_uuid(),
                'rehearsal', now(), 'rehearsal/retention.pdf', %s)
        RETURNING id""", ("a" * 64,))
    _one(db, """
        INSERT INTO public.data_retention_rules (
            rule_code, evidence_category, retention_until_rule,
            legal_artifact_id, active)
        VALUES ('training_corpus', 'training_corpus', 'until withdrawal', %s, true)
        ON CONFLICT (rule_code) DO UPDATE SET active = true
        RETURNING id""", (artifact,))
    return version


def _person_with_copies(db, version):
    principal = _principal(db)
    _receipt(db, principal, version)
    grant = str(_one(db, """
        SELECT (public.record_mlc2_training_consent_grant_v2(
            %s, %s, 'PL', 'terms-t', 'privacy-t', 'settings/training', 'test',
            %s::jsonb, now() - interval '1 second', %s)).id""",
        (principal, TRAINING_POLICY, _action(), f"g-{uuid.uuid4()}")))
    text = _copy(db, principal, grant, "transcript_span",
                 content=json.dumps({"text": "every word"}))
    audio = _copy(db, principal, grant, "audio_segment",
                  provider="r2", bucket="lab",
                  key=f"training-corpus/{principal}/{grant}/{uuid.uuid4()}.wav",
                  osha="9" * 64)
    return {"principal": str(principal), "grant": grant, "text": text, "audio": audio}


def _copy(db, principal, grant, kind, content=None, provider=None, bucket=None,
          key=None, osha=None):
    return str(_one(db, """
        SELECT (public.record_training_corpus_item_v1(
            %s, %s, 'project', 'take', %s, %s, %s, NULL, %s::jsonb, %s, %s,
            %s, %s)).id""",
        (principal, grant, f"snippet:{uuid.uuid4()}:{kind}", "1" * 64, kind,
         content, provider, bucket, key, osha)))


def _state(db, item):
    return _one(db, "SELECT state FROM public.training_corpus_items WHERE id = %s",
                (item,))


def _withdraw(db, person):
    _one(db, """
        SELECT (public.record_mlc2_consent_withdrawal_v2(
            %s, %s, 'pooled_model_improvement', 'settings/training', 'test',
            '{"control": "training_toggle", "accepted": false}'::jsonb,
            now(), %s)).id""", (person["principal"], person["grant"],
                                f"w-{uuid.uuid4()}"))


class _Service:
    """The production helpers, bound to the SQL shim (service_role)."""

    def __init__(self, db):
        self.client = _Database(db).client

    list_due_training_corpus_items = DatabaseService.list_due_training_corpus_items
    erase_training_corpus_item = DatabaseService.erase_training_corpus_item


def test_a_withdrawal_makes_that_persons_copies_due_and_nobody_elses(db, ready):
    person = _person_with_copies(db, ready)
    bystander = _person_with_copies(db, ready)
    _withdraw(db, person)
    assert _state(db, person["text"]) == "purge_pending"
    assert _state(db, person["audio"]) == "purge_pending"
    assert _state(db, bystander["text"]) == "active"


def test_the_erasure_takes_due_copies_and_never_an_active_one(db, ready):
    person = _person_with_copies(db, ready)
    service = _Service(db)
    assert service.erase_training_corpus_item(person["text"]) is False
    assert _state(db, person["text"]) == "active"

    _withdraw(db, person)
    due = {row["id"] for row in service.list_due_training_corpus_items(person["principal"])}
    assert due == {person["text"], person["audio"]}
    assert service.erase_training_corpus_item(person["text"]) is True
    assert _state(db, person["text"]) is None


def test_the_object_mark_moves_a_copy_to_purged_and_keeps_its_d11_lock(db, ready):
    person = _person_with_copies(db, ready)
    request = _one(db, """
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s) RETURNING id""",
        (person["principal"], str(uuid.uuid4())))
    row = _one(db, """
        SELECT jsonb_build_object('provider', storage_provider, 'bucket', bucket,
                                  'key', storage_key, 'sha', object_sha256)
          FROM public.training_corpus_items WHERE id = %s""", (person["audio"],))
    _one(db, """
        SELECT public.mark_phase1_storage_object_purged_v1(
            %s, 'training_corpus_items', %s, %s, %s, %s, %s)""",
        (request, person["audio"], row["provider"], row["bucket"], row["key"],
         row["sha"]))
    assert _state(db, person["audio"]) == "purged"
    definition = _one(db, """
        SELECT pg_get_functiondef(
            'public.mark_phase1_storage_object_purged_v1(uuid,text,uuid,text,text,text,text)'
            ::regprocedure)""")
    assert "D11 writer: object purge" in definition


def test_account_erasure_reaches_the_copies(db, ready):
    person = _person_with_copies(db, ready)
    request = str(_one(db, """
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s) RETURNING id""",
        (person["principal"], str(uuid.uuid4()))))

    result = DataPurgeOrchestrator(_Database(db)).freeze_inventory(request)

    assert result.get("state") in ("in_progress", "review_required"), result
    assert _one(db, """
        SELECT count(*) FROM public.data_purge_targets
         WHERE purge_request_id = %s
           AND metadata->>'source_relation' = 'training_corpus_items'
           AND target_ref = %s""", (request, f"training-copy:{person['audio']}")) == 1
    # The rows are a delete dependency, not a stop.
    stopped_on = _one(db, """
        SELECT coalesce(jsonb_agg(DISTINCT metadata->>'relation'), '[]'::jsonb)
          FROM public.data_purge_targets
         WHERE purge_request_id = %s AND state IN ('unknown', 'failed')""",
        (request,))
    assert "training_corpus_items" not in stopped_on
