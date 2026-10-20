"""
STORY    As a speaker, I want my training yes or no kept separate from my
         processing consent, so that saying yes to one never ticks, blocks
         or undoes the other.
OUTCOME
  O1  With a training policy active beside a bundled one, the bundled status
      reader still answers, on the bundled policy.
  O2  The bundled grant writer refuses the training policy.
  O3  The processing receipt refuses training as a tick; other ticks record.
PROVES   O1 -> test_the_bundled_status_reader_ignores_the_training_policy
         O2 -> test_the_bundled_grant_writer_refuses_the_training_policy
         O3 -> test_the_receipt_never_records_training_as_a_tick
WHY      0377 (P5 packet section 4, items 1-2). Runs on the released
         rehearsal lane; every case is one rolled-back transaction.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

REQUIRED = ("recording_voice_processing", "transcription_feedback")
TOGGLE_COPY = "Use my practice text and my coach's notes on it to train the models."
TOGGLE_SHA = hashlib.sha256(TOGGLE_COPY.encode()).hexdigest()


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


def _one(cur, sql, args=()):
    cur.execute(sql, args)
    row = cur.fetchone()
    return row[0] if row else None


def _raises(cur, code, sql, args=()):
    cur.execute("SAVEPOINT expect_refusal")
    with pytest.raises(psycopg2.Error) as caught:
        cur.execute(sql, args)
    cur.execute("ROLLBACK TO SAVEPOINT expect_refusal")
    assert code in str(caught.value), str(caught.value)


def _principal(cur):
    return _one(cur, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")


def _policy_offering_training_as_a_tick(cur):
    """A processing policy with training as an optional purpose.

    Only possible here because this transaction relaxes the registry row that
    keeps training phase2; it is rolled back with everything else.
    """
    for purpose in (*REQUIRED, "coach_review", "pooled_model_improvement"):
        cur.execute("""
            UPDATE public.processing_purpose_registry SET
                phase = 'phase1', operational = true,
                authorizes_processing = true,
                capability_version = COALESCE(capability_version, 'iso-v1'),
                reviewed_at = COALESCE(reviewed_at, now()),
                retention_control_version =
                    COALESCE(retention_control_version, 'ret-iso-v1'),
                deletion_control_version =
                    COALESCE(deletion_control_version, 'del-iso-v1'),
                rights_control_version =
                    COALESCE(rights_control_version, 'rights-iso-v1')
             WHERE id = %s""", (purpose,))
    cur.execute("""
        UPDATE public.processing_policy_versions
           SET status = 'retired', retired_at = now()
         WHERE status = 'active'""")
    artifacts = [
        _one(cur, """
            INSERT INTO public.processing_legal_artifacts (
                artifact_kind, version, approving_authority, approved_at,
                object_key, sha256, metadata)
            VALUES (%s, %s, 'test', now(), 'k',
                    encode(extensions.digest(%s, 'sha256'), 'hex'), '{}'::jsonb)
            RETURNING id""", (kind, f"iso-{uuid.uuid4()}", str(uuid.uuid4())))
        for kind in ("product_legal_approval", "power_score_classification",
                     "article_50_assessment")
    ]
    version = f"phase1-training-tick-{uuid.uuid4()}"
    policy_id = _one(cur, """
        INSERT INTO public.processing_policy_versions (
            version, status, product_legal_artifact_id,
            power_score_classification_artifact_id, article50_artifact_id,
            terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256,
            allowed_countries, activated_at, created_by)
        VALUES (%s, 'active', %s, %s, %s,
            't1', 'terms', encode(extensions.digest('terms','sha256'),'hex'),
            'p1', 'privacy', encode(extensions.digest('privacy','sha256'),'hex'),
            'a1', 'notice', encode(extensions.digest('notice','sha256'),'hex'),
            'agree', encode(extensions.digest('agree','sha256'),'hex'),
            ARRAY['pl'], now() - interval '1 minute', 'isolation-test')
        RETURNING id""", (version, *artifacts))
    for purpose, required, basis in (
        *((p, True, "contract") for p in REQUIRED),
        ("coach_review", False, "consent"),
        ("pooled_model_improvement", False, "consent"),
    ):
        cur.execute("""
            INSERT INTO public.processing_policy_purposes (
                policy_id, purpose_id, lawful_basis_code,
                required_for_core_service)
            VALUES (%s, %s, %s, %s)""", (policy_id, purpose, basis, required))
    return version


def _accept(cur, version, ticks):
    return _one(cur, """
        SELECT public.accept_phase1_processing_authorization_v2(
            %s, %s,
            encode(extensions.digest('terms','sha256'),'hex'),
            encode(extensions.digest('privacy','sha256'),'hex'),
            encode(extensions.digest('notice','sha256'),'hex'),
            encode(extensions.digest('agree','sha256'),'hex'),
            'agree_and_continue', true, 'PL', 'en-GB', 'test', now(), %s,
            %s::text[])""",
        (_principal(cur), version, f"k-{uuid.uuid4()}", ticks))


def test_the_receipt_never_records_training_as_a_tick(cur):
    version = _policy_offering_training_as_a_tick(cur)
    _raises(cur, "TRAINING_IS_NOT_A_RECEIPT_CHOICE", """
        SELECT public.accept_phase1_processing_authorization_v2(
            %s, %s,
            encode(extensions.digest('terms','sha256'),'hex'),
            encode(extensions.digest('privacy','sha256'),'hex'),
            encode(extensions.digest('notice','sha256'),'hex'),
            encode(extensions.digest('agree','sha256'),'hex'),
            'agree_and_continue', true, 'PL', 'en-GB', 'test', now(), %s,
            ARRAY['coach_review', 'pooled_model_improvement'])""",
        (_principal(cur), version, f"k-{uuid.uuid4()}"))
    # Every other tick is still recorded exactly as before.
    accepted = _accept(cur, version, ["coach_review"])
    assert accepted["optional_purposes_recorded"] == ["coach_review"]


_ACTIVE = ("active_from <= now() AND (retired_at IS NULL OR retired_at > now())")


def _training_policy_version(cur):
    """The active training-only policy (the lane allows one at a time)."""
    live = _one(cur, "SELECT version FROM public.ml_consent_policies "
                     f"WHERE grant_scope = 'training_only' AND {_ACTIVE} "
                     "ORDER BY active_from DESC LIMIT 1")
    if live:
        return live
    processing = _one(cur, "SELECT version FROM public.processing_policy_versions "
                           "ORDER BY created_at LIMIT 1")
    if not processing:
        processing = f"phase1-0377-{uuid.uuid4()}"
        digest = hashlib.sha256(b"rehearsal").hexdigest()
        cur.execute("""
            INSERT INTO public.processing_policy_versions (
                version, status, terms_version, terms_copy, terms_copy_sha256,
                privacy_version, privacy_copy, privacy_copy_sha256,
                ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
                agreement_copy, agreement_copy_sha256, allowed_countries,
                created_by)
            VALUES (%s, 'draft', 't', 'terms', %s, 'p', 'privacy', %s, 'a',
                    'notice', %s, 'agree', %s, ARRAY['pl'], 'rehearsal-0377')""",
            (processing, digest, digest, digest, digest))
    _one(cur, """
        SELECT public.configure_mlc2_training_consent_policy_v1(
            'training-approval-0377', %s, %s, 'training-only-0377-v1',
            'terms-t', 'privacy-t', 'founder+counsel', now(), ARRAY['PL'],
            'evidence/training.pdf', %s, %s, now() - interval '1 minute')""",
        (TOGGLE_SHA, TOGGLE_COPY, "e" * 64, processing))
    return "training-only-0377-v1"


def _bundled_policy_version(cur):
    """Exactly one active bundled policy, inserted directly (the v1 configure
    refuses while a training policy is active). Earlier suites in the lane
    leave bundled policies behind; they are retired inside this rolled-back
    transaction, past the append-only guard, so the reader sees one."""
    cur.execute("SET LOCAL session_replication_role = replica")
    cur.execute("UPDATE public.ml_consent_policies "
                "SET retired_at = now() - interval '1 second' "
                f"WHERE grant_scope = 'bundled_v1' AND {_ACTIVE}")
    cur.execute("SET LOCAL session_replication_role = origin")
    version = f"bundled-0377-{uuid.uuid4()}"
    approval = _one(cur, """
        INSERT INTO public.ml_product_legal_approvals (
            approval_reference, approved_copy_sha256, onboarding_copy,
            consent_policy_version, terms_version, privacy_policy_version,
            approving_authority, approved_at, jurisdictions, article_6_basis,
            article_9_treatment, evidence_object_key, evidence_sha256)
        VALUES (%s, %s, 'bundled copy', %s, 'terms-b', 'privacy-b', 'x',
                now() - interval '2 days', ARRAY['PL'], '6(1)(a)',
                'not_applicable', 'k', %s)
        RETURNING id""", (f"appr-{version}", "b" * 64, version, "c" * 64))
    cur.execute("""
        INSERT INTO public.ml_consent_policies (
            version, product_legal_approval_id, required_for_service,
            bundled_ui, active_from)
        VALUES (%s, %s, true, true, now() - interval '2 days')""",
        (version, approval))
    return version


def test_the_bundled_status_reader_ignores_the_training_policy(cur):
    _training_policy_version(cur)
    bundled = _bundled_policy_version(cur)
    status = _one(cur, "SELECT public.get_mlc2_principal_consent_status_v1(%s)",
                  (_principal(cur),))
    assert status["configured"] is True
    assert status["consent_policy_version"] == bundled
    assert status["granted"] is False


def test_the_bundled_grant_writer_refuses_the_training_policy(cur):
    training = _training_policy_version(cur)
    _raises(cur, "TRAINING_POLICY_NEEDS_THE_TRAINING_WRITER", """
        SELECT * FROM public.record_mlc2_consent_grant_v1(
            %s, %s, 'PL', 'terms-t', 'privacy-t', '/v2/user/mlc2-consent',
            'test', %s::jsonb, now() - interval '1 second', false, %s)""",
        (_principal(cur), training,
         json.dumps({"accepted": True, "copy_sha256": TOGGLE_SHA}),
         f"bundled-{uuid.uuid4()}"))
