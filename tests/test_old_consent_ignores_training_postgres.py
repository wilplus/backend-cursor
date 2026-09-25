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

TOGGLE_COPY = "Old-code isolation test: training switch copy."
TOGGLE_SHA = hashlib.sha256(TOGGLE_COPY.encode()).hexdigest()
BUNDLED_COPY = "Old-code isolation test: bundled copy."
BUNDLED_SHA = hashlib.sha256(BUNDLED_COPY.encode()).hexdigest()
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


def _processing_version(cur):
    return _one(cur, """
        SELECT version FROM public.processing_policy_versions
         ORDER BY created_at LIMIT 1""")


def _training_policy(cur):
    """The active training policy, registering one if the lane has none."""
    existing = _one(cur, """
        SELECT version FROM public.ml_consent_policies
         WHERE grant_scope = 'training_only' AND active_from <= now()
           AND (retired_at IS NULL OR retired_at > now())""")
    if existing:
        return existing
    version = f"training-isolation-{uuid.uuid4()}"
    _one(cur, """
        SELECT public.configure_mlc2_training_consent_policy_v1(
            %s, %s, %s, %s, 'terms-t', 'privacy-t', 'founder+counsel', now(),
            ARRAY['PL'], 'evidence/training.pdf', %s, %s,
            now() - interval '1 minute')""",
        (f"training-isolation-{uuid.uuid4()}", TOGGLE_SHA, TOGGLE_COPY,
         version, "e" * 64, _processing_version(cur)))
    return version


def _bundled_policy(cur):
    """Exactly one active bundled policy, registered here.

    The shared lane already holds bundled policies from other modules, and
    policies are append-only. So, inside this rolled-back transaction only
    (the precedent is tests/test_bundled_era_erasure_postgres.py), the
    append-only trigger is lifted to retire them, and one is registered
    through configure_v1 beside the active training policy.
    """
    cur.execute("ALTER TABLE public.ml_consent_policies "
                "DISABLE TRIGGER ml_consent_policies_append_only")
    cur.execute("""
        UPDATE public.ml_consent_policies SET retired_at = now()
         WHERE grant_scope = 'bundled_v1' AND active_from < now()
           AND (retired_at IS NULL OR retired_at > now())""")
    cur.execute("ALTER TABLE public.ml_consent_policies "
                "ENABLE TRIGGER ml_consent_policies_append_only")
    version = f"bundled-isolation-{uuid.uuid4()}"
    _one(cur, """
        SELECT public.configure_mlc2_consent_policy_v1(
            %s, %s, %s, %s, 'terms-b', 'privacy-b', 'founder', now(),
            ARRAY['PL'], 'not_applicable', 'evidence/bundled.pdf', %s, now())""",
        (f"bundled-isolation-{uuid.uuid4()}", BUNDLED_SHA, BUNDLED_COPY,
         version, "b" * 64))
    return version


@pytest.fixture
def both(cur):
    training = _training_policy(cur)
    return {"training": training, "bundled": _bundled_policy(cur)}


def test_a_bundled_policy_registers_beside_an_active_training_one(cur, both):
    # configure_v1 refused this before 0377: "another bundled MLC-2 consent
    # policy is active", counting the training policy.
    assert _one(cur, """
        SELECT grant_scope FROM public.ml_consent_policies WHERE version = %s""",
        (both["bundled"],)) == "bundled_v1"


def test_the_bundled_status_reader_reads_only_the_bundled_policy(cur, both):
    status = _one(cur, "SELECT public.get_mlc2_principal_consent_status_v1(%s)",
                  (_principal(cur),))
    assert status["configured"] is True
    assert status["consent_policy_version"] == both["bundled"]
    assert status["granted"] is False


def test_the_canary_counts_only_bundled_policies(cur, both):
    readiness = _one(cur,
                     "SELECT public.get_mlc2_confidence_canary_readiness_v1(NULL)")
    assert readiness["active_consent_policy_count"] == 1
    assert readiness["valid_active_consent_policy_count"] == 1


def test_the_bundled_grant_writer_refuses_the_training_policy(cur, both):
    _raises(cur, "TRAINING_POLICY_NEEDS_THE_TRAINING_WRITER", """
        SELECT public.record_mlc2_consent_grant_v1(
            %s, %s, 'PL', 'terms-t', 'privacy-t', 'settings', 'test',
            %s::jsonb, now(), false, %s)""",
        (_principal(cur), both["training"],
         json.dumps({"accepted": True, "copy_sha256": TOGGLE_SHA}),
         f"g-{uuid.uuid4()}"))


def test_the_bundled_withdrawal_refuses_a_training_grant(cur, both):
    principal = _principal(cur)
    _one(cur, """
        INSERT INTO public.processing_authorization_receipts (
            acquisition_principal_id, policy_id, idempotency_key,
            explicit_action, age_18_attested, country_of_residence, locale,
            client_version, accepted_at, evidence_sha256)
        SELECT %s, id, %s, 'agree_and_continue', true, 'PL', 'en-GB', 'test',
               now(), %s
          FROM public.processing_policy_versions WHERE version = %s
        RETURNING id""",
        (principal, f"r-{uuid.uuid4()}", "a" * 64,
         _one(cur, """
             SELECT requires_processing_policy_version
               FROM public.ml_consent_policies WHERE version = %s""",
              (both["training"],))))
    copy_sha = _one(cur, """
        SELECT approval.approved_copy_sha256
          FROM public.ml_consent_policies policy
          JOIN public.ml_product_legal_approvals approval
            ON approval.id = policy.product_legal_approval_id
         WHERE policy.version = %s""", (both["training"],))
    grant_id = _one(cur, """
        SELECT id FROM public.record_mlc2_training_consent_grant_v2(
            %s, %s, 'PL', 'terms-t', 'privacy-t', 'settings/training', 'test',
            %s::jsonb, now() - interval '1 second', %s)""",
        (principal, both["training"],
         json.dumps({"accepted": True, "control": "training_toggle",
                     "copy_sha256": copy_sha}),
         f"g-{uuid.uuid4()}"))
    _raises(cur, "TRAINING_WITHDRAWAL_NEEDS_THE_TRAINING_WRITER", """
        SELECT public.record_mlc2_consent_withdrawal_v1(
            %s, %s, 'settings', 'test', '{"accepted": false}'::jsonb, now(),
            %s)""", (principal, grant_id, f"w-{uuid.uuid4()}"))
    status = _one(cur, "SELECT public.get_mlc2_training_consent_status_v2(%s)",
                  (principal,))
    assert status["active"] is True


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


def test_the_receipt_writer_keeps_its_d11_preamble(cur):
    definition = _one(cur, """
        SELECT pg_get_functiondef(to_regprocedure(
            'public.accept_phase1_processing_authorization_v2(uuid,text,text,'
            'text,text,text,text,boolean,text,text,text,timestamptz,text,'
            'text[])'))""")
    assert "D11 writer: authorization receipt" in definition
    assert definition.count("TRAINING_IS_NOT_A_RECEIPT_CHOICE") == 1
    assert definition.index("D11 writer: authorization receipt") < \
        definition.index("TRAINING_IS_NOT_A_RECEIPT_CHOICE")
