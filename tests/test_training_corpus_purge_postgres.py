"""
STORY    As a speaker, I want my training copies erased when I withdraw or
         delete my account, so that nothing of mine stays in the training
         data. (Critical path: deletion and consent.)
OUTCOME
  O1  A withdrawal marks every copy of mine due, and nobody else's.
  O2  The erasure job deletes my due copies (audio only once its object is
      proven gone) and never an active copy of anyone.
  O3  Once a copy's audio is verified gone, the account purge marks it
      `purged`.
  O4  Account deletion takes my copies' audio and rows with it; the copies
      never stop it, and the only thing that may stop it for review is the
      record of my consent.
PROVES   O1 -> test_a_withdrawal_makes_that_persons_copies_due_and_nobody_elses
         O2 -> test_the_erasure_deletes_due_copies_and_never_an_active_one
         O3 -> test_a_verified_object_marks_the_copy_purged
         O4 -> test_account_erasure_reaches_the_copies
WHY      0376 (SPEC-training-corpus section 6, P4; founder locks C3, Q3).

Runs on the released rehearsal lane after the consent and corpus suites. The
orchestrator, the erasure job and its database helpers are the production
Python, driven through the SQL client of
tests/test_account_deletion_starts_postgres.py as service_role; only object
storage is faked.
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import pytest

from services import training_corpus
from services.data_purge import DataPurgeOrchestrator
from services.db import DatabaseService
from tests.test_account_deletion_starts_postgres import _Database
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


def test_a_withdrawal_makes_that_persons_copies_due_and_nobody_elses(db, ready):
    person = _person_with_copies(db, ready)
    bystander = _person_with_copies(db, ready)
    _withdraw(db, person)
    assert _state(db, person["text"]) == "purge_pending"
    assert _state(db, person["audio"]) == "purge_pending"
    assert _state(db, bystander["text"]) == "active"


class _CorpusDatabase(_Database):
    """The production helpers the erasure job calls, on the SQL client."""

    list_due_training_corpus_items = DatabaseService.list_due_training_corpus_items
    erase_training_corpus_item = DatabaseService.erase_training_corpus_item


def _exists(db, item):
    return _one(db, "SELECT count(*) FROM public.training_corpus_items "
                    "WHERE id = %s", (item,)) == 1


def test_the_erasure_deletes_due_copies_and_never_an_active_one(db, ready,
                                                                monkeypatch):
    person = _person_with_copies(db, ready)
    bystander = _person_with_copies(db, ready)
    _withdraw(db, person)
    database = _CorpusDatabase(db)
    gone = {"answer": False}
    monkeypatch.setattr(
        "services.lab_audio_storage.delete_verified_lab_audio_object",
        lambda key, **_: gone["answer"])

    # Storage cannot prove the audio gone: its copy stays due.
    assert training_corpus.purge_due_copies(person["principal"],
                                            database=database) == {
        "erased": 1, "failed": 1}
    assert not _exists(db, person["text"])
    assert _state(db, person["audio"]) == "purge_pending"

    gone["answer"] = True
    assert training_corpus.purge_due_copies(person["principal"],
                                            database=database) == {
        "erased": 1, "failed": 0}
    assert not _exists(db, person["audio"])

    # An active copy is never erased, even when asked for by id.
    assert database.erase_training_corpus_item(bystander["text"]) is False
    assert _state(db, bystander["text"]) == "active"


def test_a_verified_object_marks_the_copy_purged(db, ready):
    person = _person_with_copies(db, ready)
    request = _erasure_request(db, person)
    with db.cursor() as cur:
        cur.execute("""
            SELECT storage_provider, bucket, storage_key, object_sha256
              FROM public.training_corpus_items WHERE id = %s""",
            (person["audio"],))
        provider, bucket, key, sha = cur.fetchone()
    _one(db, """
        SELECT public.mark_phase1_storage_object_purged_v1(
            %s, 'training_corpus_items', %s, %s, %s, %s, %s)""",
        (request, person["audio"], provider, bucket, key, sha))
    assert _state(db, person["audio"]) == "purged"
    assert _state(db, person["text"]) == "active"


def _erasure_request(db, person):
    return str(_one(db, """
        INSERT INTO public.data_purge_requests (
            acquisition_principal_id, trigger_kind, idempotency_key)
        VALUES (%s, 'account_deletion', %s) RETURNING id""",
        (person["principal"], str(uuid.uuid4()))))


def test_account_erasure_reaches_the_copies(db, ready):
    person = _person_with_copies(db, ready)
    request = _erasure_request(db, person)

    result = DataPurgeOrchestrator(_Database(db)).freeze_inventory(request)

    assert _one(db, """
        SELECT count(*) FROM public.data_purge_targets
         WHERE purge_request_id = %s
           AND metadata->>'source_relation' = 'training_corpus_items'
           AND target_ref = %s""", (request, f"training-copy:{person['audio']}")) == 1
    # The rows go as a delete dependency.
    assert _one(db, """
        SELECT metadata->>'disposition' FROM public.data_purge_targets
         WHERE purge_request_id = %s
           AND metadata->>'relation' = 'training_corpus_items'""",
        (request,)) == "delete"
    # What stops it for review, if anything, is the consent record alone.
    stopped_on = set(_one(db, """
        SELECT coalesce(jsonb_agg(DISTINCT metadata->>'relation'), '[]'::jsonb)
          FROM public.data_purge_targets
         WHERE purge_request_id = %s AND state IN ('unknown', 'failed')""",
        (request,)))
    assert stopped_on <= {"ml_consent_events"}, stopped_on
    assert result["state"] == ("review_required" if stopped_on
                               else "in_progress"), result
