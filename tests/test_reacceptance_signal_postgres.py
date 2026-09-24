"""The status can tell a first-timer from someone whose Terms moved.

P10, decisions P10.1-P10.4 locked 2026-09-23.

`get_phase1_processing_authorization_v1` looks up the receipt for the ACTIVE
policy. A receipt against an older policy does not match, so it answers
PROCESSING_AUTHORIZATION_REQUIRED — the same answer it gives someone who has
never accepted anything. The acceptance gate therefore could only ever show
the first-time screen, to both.

That bites the moment counsel returns revised Terms: every existing speaker
goes stale at once, and every one of them meets a screen written for a
stranger.

These cases build the second policy and check the answer for each kind of
person. The `authorized` and `code` fields are asserted unchanged throughout,
because the whole claim of this migration is that it adds a signal without
moving a decision.
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

OLD = "phase1-reaccept-old"
NEW = "phase1-reaccept-new"
PURPOSE = "recording_voice_processing"


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


def _artifacts(db):
    out = {}
    for kind in ("product_legal_approval", "power_score_classification",
                 "article_50_assessment"):
        out[kind] = _one(db, """
            INSERT INTO public.processing_legal_artifacts (
                artifact_kind, version, approving_authority, approved_at,
                object_key, sha256, metadata)
            VALUES (%s, %s, 'test', now(), 'k',
                    encode(extensions.digest(%s,'sha256'),'hex'), '{}'::jsonb)
            RETURNING id""", (kind, f"ra-{uuid.uuid4()}", str(uuid.uuid4())))
    return out


def _policy(db, version, *, active):
    art = _artifacts(db)
    policy_id = _one(db, """
        INSERT INTO public.processing_policy_versions (
            version, status, product_legal_artifact_id,
            power_score_classification_artifact_id, article50_artifact_id,
            terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256,
            allowed_countries, activated_at, retired_at, created_by)
        VALUES (%s, %s, %s, %s, %s,
            %s, %s, encode(extensions.digest(%s,'sha256'),'hex'),
            %s, %s, encode(extensions.digest(%s,'sha256'),'hex'),
            %s, %s, encode(extensions.digest(%s,'sha256'),'hex'),
            %s, encode(extensions.digest(%s,'sha256'),'hex'),
            ARRAY['pl'], now() - interval '1 minute',
            CASE WHEN %s THEN NULL ELSE now() END, 'p10-test')
        RETURNING id""",
        (version, "active" if active else "retired",
         art["product_legal_approval"], art["power_score_classification"],
         art["article_50_assessment"],
         f"t-{version}", f"terms {version}", f"terms {version}",
         f"p-{version}", f"privacy {version}", f"privacy {version}",
         f"a-{version}", f"notice {version}", f"notice {version}",
         f"agree {version}", f"agree {version}",
         active))
    _one(db, """
        INSERT INTO public.processing_policy_purposes (
            policy_id, purpose_id, lawful_basis_code, required_for_core_service)
        VALUES (%s, %s, 'contract', true) RETURNING policy_id""",
        (policy_id, PURPOSE))
    return policy_id


@pytest.fixture(scope="module")
def policies(db):
    """One retired policy and one active one — a Terms change, in other words."""
    _one(db, """
        UPDATE public.processing_purpose_registry SET
            phase = 'phase1', operational = true, authorizes_processing = true,
            capability_version = COALESCE(capability_version, 'ra-v1'),
            reviewed_at = COALESCE(reviewed_at, now()),
            retention_control_version =
                COALESCE(retention_control_version, 'ret-ra-v1'),
            deletion_control_version =
                COALESCE(deletion_control_version, 'del-ra-v1'),
            rights_control_version =
                COALESCE(rights_control_version, 'rights-ra-v1')
         WHERE id = %s RETURNING id""", (PURPOSE,))
    _one(db, """
        UPDATE public.processing_policy_versions
           SET status = 'retired', retired_at = now()
         WHERE status = 'active' RETURNING id""")

    old = _one(db, "SELECT id::text FROM public.processing_policy_versions"
                   " WHERE version = %s", (OLD,)) or _policy(db, OLD, active=False)
    new = _one(db, "SELECT id::text FROM public.processing_policy_versions"
                   " WHERE version = %s", (NEW,)) or _policy(db, NEW, active=True)
    _one(db, """
        UPDATE public.processing_policy_versions
           SET status = 'active', retired_at = NULL
         WHERE id = %s RETURNING id""", (new,))
    return {"old": old, "new": new}


@pytest.fixture
def principal(db):
    return _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")


def _receipt(db, principal, policy_id):
    return _one(db, """
        INSERT INTO public.processing_authorization_receipts (
            acquisition_principal_id, policy_id, idempotency_key,
            explicit_action, age_18_attested, country_of_residence, locale,
            client_version, accepted_at, evidence_sha256,
            pooled_learning_eligible)
        VALUES (%s, %s, %s, 'agree_and_continue', true, 'pl', 'en-GB', 'test',
                now(), encode(extensions.digest(%s,'sha256'),'hex'), false)
        RETURNING id""", (principal, policy_id, f"k-{uuid.uuid4()}",
                          str(uuid.uuid4())))


def _status(db, principal):
    return _one(db, "SELECT public.get_phase1_processing_authorization_v1(%s)",
                (principal,))


class TestTheTwoPeopleAreNowDistinguishable:

    def test_someone_who_never_accepted_is_not_a_reacceptance(
            self, db, policies, principal):
        """A first-time visitor must meet the first-time screen."""
        status = _status(db, principal)

        assert status["authorized"] is False
        assert status["code"] == "PROCESSING_AUTHORIZATION_REQUIRED"
        assert status["reacceptance_required"] is False
        assert status["accepted_policy_version"] is None

    def test_someone_whose_terms_moved_is_flagged(self, db, policies, principal):
        """The named regression test for P10. Before this, indistinguishable
        from the case above."""
        _receipt(db, principal, policies["old"])

        status = _status(db, principal)

        assert status["reacceptance_required"] is True
        assert status["accepted_policy_version"] == OLD, (
            "the screen cannot say WHICH document moved"
        )
        # The decision itself is unchanged — that is the whole claim.
        assert status["authorized"] is False
        assert status["code"] == "PROCESSING_AUTHORIZATION_REQUIRED"

    def test_accepting_the_current_policy_clears_it(
            self, db, policies, principal):
        _receipt(db, principal, policies["old"])
        _receipt(db, principal, policies["new"])

        status = _status(db, principal)

        assert status["authorized"] is True
        assert status["code"] == "PROCESSING_AUTHORIZED"
        assert status["reacceptance_required"] is False


class TestItMovesNoDecision:

    def test_a_blocked_principal_is_not_asked_to_reaccept(
            self, db, policies, principal):
        """Someone under a service block is not being asked for anything. The
        block governs, and offering them a re-acceptance screen would be an
        invitation to a door that stays shut."""
        _receipt(db, principal, policies["old"])
        _one(db, """
            INSERT INTO public.processing_service_blocks (
                acquisition_principal_id, block_kind, reason_code,
                effective_at)
            VALUES (%s, 'restriction', 'test', now() - interval '1 minute')
            RETURNING id""",
            (principal,))

        status = _status(db, principal)

        assert status["code"] == "PROCESSING_SERVICE_BLOCKED"
        assert status["authorized"] is False
        assert status["reacceptance_required"] is False

    def test_the_authorized_answer_is_untouched(self, db, policies, principal):
        """Every field an existing caller reads still reads the same."""
        _receipt(db, principal, policies["new"])

        status = _status(db, principal)

        assert status["authorized"] is True
        assert status["policy_version"] == NEW
        assert status["policy_available"] is True
        assert status["pooled_learning_eligible"] is False
        assert status["receipt_id"]
