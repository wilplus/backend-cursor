"""The old consent code ignores the training yes (0377, P5 packet §4 items 1-2).

Run on the released rehearsal lane. Every case runs in one transaction that is
rolled back, so the policies it registers, and the registry row it relaxes,
never reach another module.

The first five cases fail without 0377. With a training policy active beside a
bundled one:

  * the bundled status reader raised "count must equal one";
  * a bundled policy could not be registered;
  * the canary readiness counted two policies;
  * the bundled grant writer recorded a two-purpose yes on the training policy;
  * the bundled withdrawal turned training off without making copies due.

The last case is the second wall for the day the training purpose is allowed
into a processing policy: the receipt writer still refuses it as a tick, and
keeps 0366's D11 preamble.
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

REQUIRED = ("recording_voice_processing", "transcription_feedback")


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
