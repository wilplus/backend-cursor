"""The training yes is its own act (0373, SPEC-training-corpus §3, P2).

Run on the released rehearsal lane. Pins the design's invariants that P2 owns
(SPEC §10):

  1. a grant under a bundled_v1 policy never makes the reader say yes;
  2. the grant writes exactly one purpose row and refuses a bundled or
     non-training policy;
  3. withdrawing training leaves the bundled grant (and its coaching
     purpose) untouched;
  8. a Phase-1 receipt can never be pooled-learning eligible;
  9. the grant refuses a person with no receipt for the policy version that
     introduced training.

Plus: the yes must be the training toggle's own act, the reader answers "no"
for everyone until a training policy exists, and browser roles call nothing.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

TOGGLE_COPY = "Use my recordings to help improve WillpowerLab for everyone."
TOGGLE_SHA = hashlib.sha256(TOGGLE_COPY.encode()).hexdigest()
TRAINING_POLICY = "training-only-test-v1"


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


def _row(db, sql, args=()):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        row = cur.fetchone()
        return dict(row) if row else None


def _status(db, principal):
    return _one(db, "SELECT public.get_mlc2_training_consent_status_v2(%s)",
                (principal,))


@pytest.fixture(scope="module")
def processing_version(db):
    return _one(db, """
        SELECT version FROM public.processing_policy_versions
         ORDER BY created_at LIMIT 1""")


@pytest.fixture(scope="module")
def training_policy(db, processing_version):
    assert processing_version, "the released lane carries a processing policy"
    return _one(db, """
        SELECT public.configure_mlc2_training_consent_policy_v1(
            'training-approval-test', %s, %s, %s, 'terms-t', 'privacy-t',
            'founder+counsel', now(), ARRAY['PL'], 'evidence/training.pdf',
            %s, %s, now() - interval '1 minute')""",
        (TOGGLE_SHA, TOGGLE_COPY, TRAINING_POLICY, "e" * 64,
         processing_version))


def _principal(db):
    return _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")


def _receipt(db, principal, processing_version):
    _one(db, """
        INSERT INTO public.processing_authorization_receipts (
            acquisition_principal_id, policy_id, idempotency_key,
            explicit_action, age_18_attested, country_of_residence, locale,
            client_version, accepted_at, evidence_sha256)
        SELECT %s, id, %s, 'agree_and_continue', true, 'PL', 'en-GB', 'test',
               now(), %s
          FROM public.processing_policy_versions WHERE version = %s
        RETURNING id""",
        (principal, f"r-{uuid.uuid4()}", "a" * 64, processing_version))


def _action(**over):
    action = {"accepted": True, "control": "training_toggle",
              "copy_sha256": TOGGLE_SHA}
    action.update(over)
    return json.dumps(action)


def _grant(db, principal, *, policy=TRAINING_POLICY, action=None, key=None):
    return _row(db, """
        SELECT * FROM public.record_mlc2_training_consent_grant_v2(
            %s, %s, 'PL', 'terms-t', 'privacy-t', 'settings/training',
            'test', %s::jsonb, now() - interval '1 second', %s)""",
        (principal, policy, action or _action(), key or f"g-{uuid.uuid4()}"))


def _withdraw(db, principal, grant_id, purpose="pooled_model_improvement"):
    return _row(db, """
        SELECT * FROM public.record_mlc2_consent_withdrawal_v2(
            %s, %s, %s, 'settings/training', 'test',
            '{"control": "training_toggle", "accepted": false}'::jsonb,
            now(), %s)""",
        (principal, grant_id, purpose, f"w-{uuid.uuid4()}"))


@pytest.fixture
def consented(db, training_policy, processing_version):
    principal = _principal(db)
    _receipt(db, principal, processing_version)
    return principal


def test_nobody_has_a_training_yes_by_default(db):
    assert _status(db, _principal(db)) == {"active": False}


def test_the_grant_records_exactly_one_purpose_without_article_9(db, consented):
    event = _grant(db, consented)
    purposes = _row(db, """
        SELECT count(*) AS n, min(purpose) AS purpose,
               bool_and(article_9_basis IS NULL) AS no_art9
          FROM public.ml_consent_event_purposes WHERE consent_event_id = %s""",
        (event["id"],))
    assert purposes == {"n": 1, "purpose": "pooled_model_improvement", "no_art9": True}
    status = _status(db, consented)
    assert status["active"] is True
    assert status["grant_event_id"] == str(event["id"])


def test_a_replay_returns_the_same_grant(db, consented):
    key = f"g-{uuid.uuid4()}"
    first = _grant(db, consented, key=key)
    assert _grant(db, consented, key=key)["id"] == first["id"]


@pytest.mark.parametrize("override, code", [
    ({"control": "signup"}, "TRAINING_CONSENT_NOT_ITS_OWN_ACT"),
    ({"control": None}, "TRAINING_CONSENT_NOT_ITS_OWN_ACT"),
    ({"accepted": False}, "TRAINING_CONSENT_NOT_ITS_OWN_ACT"),
    ({"copy_sha256": "0" * 64}, "TRAINING_CONSENT_DOES_NOT_MATCH_APPROVAL"),
])
def test_only_the_toggle_s_own_yes_counts(db, consented, override, code):
    with pytest.raises(psycopg2.Error, match=code):
        _grant(db, consented, action=_action(**override))
    assert _status(db, consented)["active"] is False


def test_no_receipt_for_the_training_policy_version_no_grant(db, training_policy):
    with pytest.raises(psycopg2.Error, match="TRAINING_CONSENT_NEEDS_POLICY_RECEIPT"):
        _grant(db, _principal(db))


def test_a_bundled_policy_can_never_carry_a_training_grant(db, consented):
    bundled = _bundled_policy(db)
    with pytest.raises(psycopg2.Error, match="TRAINING_POLICY_NOT_TRAINING_ONLY"):
        _grant(db, consented, policy=bundled)


def _bundled_policy(db):
    """A bundled_v1 policy, as the bundled era had (inserted directly: the
    v1 configure refuses while the training policy is active)."""
    version = f"bundled-test-{uuid.uuid4()}"
    approval = _one(db, """
        INSERT INTO public.ml_product_legal_approvals (
            approval_reference, approved_copy_sha256, onboarding_copy,
            consent_policy_version, terms_version, privacy_policy_version,
            approving_authority, approved_at, jurisdictions, article_6_basis,
            article_9_treatment, evidence_object_key, evidence_sha256)
        VALUES (%s, %s, 'bundled copy', %s, 'terms-b', 'privacy-b', 'x',
                now(), ARRAY['PL'], '6(1)(a)', 'not_applicable', 'k', %s)
        RETURNING id""",
        (f"appr-{version}", "b" * 64, version, "c" * 64))
    _one(db, """
        INSERT INTO public.ml_consent_policies (
            version, product_legal_approval_id, required_for_service,
            bundled_ui, active_from)
        VALUES (%s, %s, true, true, now() - interval '1 hour') RETURNING version""",
        (version, approval))
    return version


def test_a_bundled_era_yes_is_never_a_training_yes(db, training_policy):
    principal = _principal(db)
    bundled = _bundled_policy(db)
    _one(db, """
        SELECT (public.record_mlc2_consent_grant_v1(
            %s, %s, 'PL', 'terms-b', 'privacy-b', 'signup', 'test',
            %s::jsonb, now() - interval '1 second', false, %s)).id""",
        (principal, bundled, json.dumps({"accepted": True, "copy_sha256": "b" * 64}),
         f"b-{uuid.uuid4()}"))
    # The bundled grant carries pooled_model_improvement — and still counts
    # for nothing (C2).
    assert _status(db, principal) == {"active": False}


def test_withdrawing_training_leaves_the_bundled_grant_alone(db, consented):
    bundled = _bundled_policy(db)
    bundled_grant = _one(db, """
        SELECT (public.record_mlc2_consent_grant_v1(
            %s, %s, 'PL', 'terms-b', 'privacy-b', 'signup', 'test',
            %s::jsonb, now() - interval '1 second', false, %s)).id""",
        (consented, bundled, json.dumps({"accepted": True, "copy_sha256": "b" * 64}),
         f"b-{uuid.uuid4()}"))
    training = _grant(db, consented)

    withdrawal = _withdraw(db, consented, training["id"])

    assert withdrawal["supersedes_event_id"] == training["id"]
    assert [r for r in _all(db, """
        SELECT purpose FROM public.ml_consent_event_purposes
         WHERE consent_event_id = %s""", (withdrawal["id"],))] == [
        ("pooled_model_improvement",)]
    status = _status(db, consented)
    assert status["active"] is False and status["withdrawn"] is True
    assert _one(db, """
        SELECT count(*) FROM public.ml_consent_events
         WHERE supersedes_event_id = %s""", (bundled_grant,)) == 0
    # The bundled grant cannot be withdrawn through the training path.
    with pytest.raises(psycopg2.Error, match="TRAINING_GRANT_NOT_FOUND"):
        _withdraw(db, consented, bundled_grant)


def _all(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


def test_a_new_yes_after_a_withdrawal_counts_again(db, consented):
    first = _grant(db, consented)
    _withdraw(db, consented, first["id"])
    assert _status(db, consented)["active"] is False
    second = _grant(db, consented)
    assert _status(db, consented)["grant_event_id"] == str(second["id"])


def test_only_the_training_purpose_can_be_withdrawn_here(db, consented):
    grant = _grant(db, consented)
    with pytest.raises(psycopg2.Error, match="WITHDRAWAL_PURPOSE_NOT_SUPPORTED"):
        _withdraw(db, consented, grant["id"], purpose="personalized_coaching")


def test_the_scope_rule_holds_for_both_kinds_of_policy(db):
    approval = _one(db, """
        SELECT product_legal_approval_id FROM public.ml_consent_policies
         WHERE version = %s""", (TRAINING_POLICY,))
    for required, bundled, scope, requires in (
        (False, True, "bundled_v1", None),
        (True, False, "bundled_v1", None),
        (True, True, "training_only", "x"),
        (False, False, "training_only", None),
        (True, True, "bundled_v1", "x"),
    ):
        with pytest.raises(psycopg2.Error, match="ml_consent_policy_grant_scope_check"):
            _one(db, """
                INSERT INTO public.ml_consent_policies (
                    version, product_legal_approval_id, required_for_service,
                    bundled_ui, grant_scope, requires_processing_policy_version,
                    active_from)
                VALUES (%s, %s, %s, %s, %s, %s, now()) RETURNING version""",
                (f"bad-{uuid.uuid4()}", approval, required, bundled, scope, requires))


def test_a_receipt_is_never_pooled_learning_eligible(db, processing_version):
    principal = _principal(db)
    with pytest.raises(psycopg2.Error, match="pooled_learning_eligible"):
        _one(db, """
            INSERT INTO public.processing_authorization_receipts (
                acquisition_principal_id, policy_id, idempotency_key,
                explicit_action, age_18_attested, country_of_residence, locale,
                client_version, accepted_at, evidence_sha256,
                pooled_learning_eligible)
            SELECT %s, id, 'k', 'agree_and_continue', true, 'PL', 'en-GB',
                   'test', now(), %s, true
              FROM public.processing_policy_versions WHERE version = %s
            RETURNING id""", (principal, "a" * 64, processing_version))


def test_configure_refuses_a_copy_that_does_not_hash(db, processing_version):
    with pytest.raises(psycopg2.Error, match="TRAINING_POLICY_COPY_HASH_DOES_NOT_VERIFY"):
        _one(db, """
            SELECT public.configure_mlc2_training_consent_policy_v1(
                'x', %s, 'other words', 'v-x', 't', 'p', 'a', now(),
                ARRAY['PL'], 'k', %s, %s, now())""",
            (TOGGLE_SHA, "e" * 64, processing_version))


def test_browser_roles_call_nothing(db, consented):
    calls = (
        ("SELECT public.get_mlc2_training_consent_status_v2(%s)", (consented,)),
        ("SELECT public.record_mlc2_training_consent_grant_v2(%s, %s, 'PL', 't', 'p', "
         "'r', 'c', '{}'::jsonb, now(), 'k')", (consented, TRAINING_POLICY)),
        ("SELECT public.record_mlc2_consent_withdrawal_v2(%s, %s, "
         "'pooled_model_improvement', 'r', 'c', '{}'::jsonb, now(), 'k')",
         (consented, str(uuid.uuid4()))),
    )
    with db.cursor() as cur:
        for role in ("anon", "authenticated"):
            for sql, args in calls:
                cur.execute(f"SET ROLE {role}")
                try:
                    with pytest.raises(psycopg2.Error, match="permission denied"):
                        cur.execute(sql, args)
                finally:
                    cur.execute("RESET ROLE")
        cur.execute("SET ROLE service_role")
        try:
            cur.execute(*calls[0])
        finally:
            cur.execute("RESET ROLE")
