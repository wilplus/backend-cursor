"""
STORY    As a speaker, I want training use of my recordings to depend only on
         my own training switch, so that an old bundled sign-up yes never
         counts and withdrawing is clean. (Critical path: consent.)
OUTCOME
  O1  Nobody is on by default.
  O2  Turning the training switch on (with my processing receipt) makes my
      training yes active, with exactly one purpose row.
  O3  A bundled-era yes never counts as a training yes.
  O4  A yes not given on the training switch itself is refused.
  O5  Without a processing receipt the yes is refused and nothing is active.
  O6  Withdrawing training ends the yes and leaves the bundled grant alone;
      the bundled grant cannot be withdrawn through the training path.
  O7  Browser roles cannot call the grant, the withdrawal or the reader.
PROVES   O1 -> test_nobody_has_a_training_yes_by_default
         O2 -> test_the_training_switch_turns_the_yes_on
         O3 -> test_a_bundled_era_yes_is_never_a_training_yes
         O4 -> test_a_yes_from_anywhere_but_the_switch_is_refused
         O5 -> test_no_receipt_no_yes
         O6 -> test_withdrawing_training_leaves_the_bundled_grant_alone
         O7 -> test_browser_roles_call_nothing
WHY      0373 (SPEC-training-corpus section 3, P2); founder N2, N10.6.

Runs on the released rehearsal lane against the real functions, after the
suites that seed a processing policy. It registers the test training policy
that tests/test_training_corpus_postgres.py and
tests/test_training_corpus_purge_postgres.py then use.
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
    # Registered once; a second registration with a new start is refused, so
    # a re-run against a kept cluster reuses it.
    if _one(db, "SELECT version FROM public.ml_consent_policies WHERE version = %s",
            (TRAINING_POLICY,)):
        return TRAINING_POLICY
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


def test_the_training_switch_turns_the_yes_on(db, consented):
    grant = _grant(db, consented)

    status = _status(db, consented)
    assert status["active"] is True
    assert status["grant_event_id"] == str(grant["id"])
    assert _all(db, """
        SELECT purpose FROM public.ml_consent_event_purposes
         WHERE consent_event_id = %s""", (grant["id"],)) == [
        ("pooled_model_improvement",)]


def test_a_yes_from_anywhere_but_the_switch_is_refused(db, consented):
    with pytest.raises(psycopg2.Error, match="TRAINING_CONSENT_NOT_ITS_OWN_ACT"):
        _grant(db, consented, action=_action(control="signup"))
    assert _status(db, consented) == {"active": False}


def test_no_receipt_no_yes(db, training_policy):
    principal = _principal(db)
    with pytest.raises(psycopg2.Error,
                       match="TRAINING_CONSENT_NEEDS_POLICY_RECEIPT"):
        _grant(db, principal)
    assert _status(db, principal) == {"active": False}


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


def test_browser_roles_call_nothing(db):
    functions = [
        "public.record_mlc2_training_consent_grant_v2(uuid, text, text, text, "
        "text, text, text, jsonb, timestamptz, text)",
        "public.record_mlc2_consent_withdrawal_v2(uuid, uuid, text, text, "
        "text, jsonb, timestamptz, text)",
        "public.get_mlc2_training_consent_status_v2(uuid)",
    ]
    for fn in functions:
        for role in ("anon", "authenticated"):
            assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, fn)) is False, (role, fn)
        assert _one(db, "SELECT has_function_privilege('service_role', %s, "
                        "'EXECUTE')", (fn,)) is True, fn
