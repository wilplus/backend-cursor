"""A receipt can record a yes the person was free to withhold.

P11's prerequisite, built on the founder's 2026-09-23 decision to land it
before republishing the policy.

`accept_phase1_processing_authorization_v1` writes receipt purpose rows only
`WHERE pp.required_for_core_service`, so a purpose someone could decline left
no evidence at all — and for `coach_review`, whose lawful basis IS consent,
that is the absence of the lawful basis rather than a gap in the paperwork.
Meanwhile `resolve_mlc3_dual_purpose_receipt_v2` gates the whole MLC-3 service
on the receipt naming two such purposes. The only way the product worked was
if they were compulsory, which is the bundling doc 01 §3 calls invalid.

These cases run the real function against a released-lane policy that carries
one required purpose and one optional one, which is the shape the republished
policy will have. The point of each is the same: what ends up in the receipt
must be exactly what the person was asked and said, and nothing else.
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

POLICY = "phase1-optional-consent-v1"
OPTIONAL = "coach_review"
REQUIRED = ("recording_voice_processing", "transcription_feedback")


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


def _rows(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchall()


@pytest.fixture(scope="module")
def policy(db):
    """A policy shaped like the republished one: core required, coach optional.

    Built directly rather than through `register_phase1_policy_v1`, because
    that writer refuses an optional purpose today — which is the whole reason
    this function had to exist first. The rows are the ones it would write.
    """
    # Both accept functions refuse a policy whose REQUIRED purposes are not
    # operational, and the registry rows only become so when
    # `register_phase1_policy_v1` runs. This module sorts before the suite
    # that calls it, so it makes them operational itself — with every field
    # `processing_purpose_operational_invariant` demands, not the subset that
    # happens to be enough today. BEFORE the reuse check below, so a lane that
    # already carries this policy still gets the guarantee.
    for purpose in (*REQUIRED, OPTIONAL):
        _one(db, """
            UPDATE public.processing_purpose_registry SET
                phase = 'phase1', operational = true,
                authorizes_processing = true,
                capability_version = COALESCE(capability_version, 'opt-v1'),
                reviewed_at = COALESCE(reviewed_at, now()),
                retention_control_version =
                    COALESCE(retention_control_version, 'ret-opt-v1'),
                deletion_control_version =
                    COALESCE(deletion_control_version, 'del-opt-v1'),
                rights_control_version =
                    COALESCE(rights_control_version, 'rights-opt-v1')
             WHERE id = %s RETURNING id""", (purpose,))

    existing = _one(db, """
        SELECT id::text FROM public.processing_policy_versions
         WHERE version = %s""", (POLICY,))
    if existing:
        _one(db, """
            UPDATE public.processing_policy_versions
               SET status = 'retired', retired_at = now()
             WHERE status = 'active' AND version <> %s RETURNING id""",
            (POLICY,))
        _one(db, """
            UPDATE public.processing_policy_versions
               SET status = 'active', retired_at = NULL,
                   activated_at = COALESCE(activated_at, now())
             WHERE version = %s RETURNING id""", (POLICY,))
        return _hashes(db, existing)

    # `processing_one_active_policy_idx` allows exactly one active policy, and
    # the retired check wants the timestamp. This module runs last of the ones
    # that need a policy, so nothing downstream is left without one.
    _one(db, """
        UPDATE public.processing_policy_versions
           SET status = 'retired', retired_at = now()
         WHERE status = 'active' RETURNING id""")

    # An active policy needs all THREE artifacts, not one:
    # `processing_policy_approved_check`.
    artifacts = {}
    for kind in ("product_legal_approval", "power_score_classification",
                 "article_50_assessment"):
        artifacts[kind] = _one(db, """
            INSERT INTO public.processing_legal_artifacts (
                artifact_kind, version, approving_authority, approved_at,
                object_key, sha256, metadata)
            VALUES (%s, %s, 'test', now(), 'k',
                    encode(extensions.digest(%s, 'sha256'), 'hex'),
                    '{}'::jsonb)
            RETURNING id""",
            (kind, f"opt-{uuid.uuid4()}", str(uuid.uuid4())))

    policy_id = _one(db, """
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
            ARRAY['pl'], now() - interval '1 minute', 'optional-consent-test')
        RETURNING id""", (POLICY, artifacts["product_legal_approval"],
                          artifacts["power_score_classification"],
                          artifacts["article_50_assessment"]))

    for purpose in REQUIRED:
        _one(db, """
            INSERT INTO public.processing_policy_purposes (
                policy_id, purpose_id, lawful_basis_code,
                required_for_core_service)
            VALUES (%s, %s, 'contract', true) RETURNING policy_id""",
            (policy_id, purpose))
    _one(db, """
        INSERT INTO public.processing_policy_purposes (
            policy_id, purpose_id, lawful_basis_code,
            required_for_core_service)
        VALUES (%s, %s, 'consent', false) RETURNING policy_id""",
        (policy_id, OPTIONAL))
    return _hashes(db, policy_id)


def _hashes(db, policy_id):
    with db.cursor() as cur:
        cur.execute("""
            SELECT terms_copy_sha256, privacy_copy_sha256,
                   ai_notice_copy_sha256, agreement_copy_sha256
              FROM public.processing_policy_versions WHERE id = %s""",
            (policy_id,))
        row = cur.fetchone()
    return {"id": policy_id, "terms": row[0], "privacy": row[1],
            "ai": row[2], "agree": row[3]}


@pytest.fixture
def principal(db):
    return _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")


def _accept(db, policy, principal, optional, *, key=None, version="v2"):
    fn = f"public.accept_phase1_processing_authorization_{version}"
    args = [principal, POLICY, policy["terms"], policy["privacy"],
            policy["ai"], policy["agree"], "agree_and_continue", True, "PL",
            "en-GB", "test", "2026-09-23T10:00:00Z", key or f"k-{uuid.uuid4()}"]
    if version == "v2":
        return _one(db, f"""
            SELECT {fn}(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::text[])""",
            (*args, optional))
    return _one(db, f"""
        SELECT {fn}(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", tuple(args))


def _receipt_purposes(db, principal):
    return sorted(r[0] for r in _rows(db, """
        SELECT rp.purpose_id
          FROM public.processing_authorization_receipt_purposes rp
          JOIN public.processing_authorization_receipts r ON r.id = rp.receipt_id
         WHERE r.acquisition_principal_id = %s""", (principal,)))


class TestTheDefectItself:

    def test_v1_cannot_record_the_optional_purpose(self, db, policy, principal):
        """The trap, on the real schema. v1 has no parameter for a choice, so
        the optional purpose is simply absent from the receipt — and the
        MLC-3 gate that requires it can never resolve."""
        _accept(db, policy, principal, None, version="v1")

        assert _receipt_purposes(db, principal) == sorted(REQUIRED)
        assert OPTIONAL not in _receipt_purposes(db, principal)


class TestV2RecordsExactlyWhatWasChosen:

    def test_a_chosen_optional_purpose_reaches_the_receipt(
            self, db, policy, principal):
        """The named regression test. This is what the whole change is for."""
        result = _accept(db, policy, principal, [OPTIONAL])

        assert result["authorized"] is True
        assert result["optional_purposes_recorded"] == [OPTIONAL]
        assert _receipt_purposes(db, principal) == sorted((*REQUIRED, OPTIONAL))

    def test_declining_leaves_the_person_authorized_for_the_core(
            self, db, policy, principal):
        """Someone who says no to coach review can still record. If this
        fails, the change has rebuilt the bundling in a new place."""
        result = _accept(db, policy, principal, [])

        assert result["authorized"] is True
        assert result["optional_purposes_recorded"] == []
        assert _receipt_purposes(db, principal) == sorted(REQUIRED)

    def test_an_empty_array_behaves_exactly_like_v1(self, db, policy, principal):
        other = _one(db, """
            INSERT INTO public.owner_principals (id, user_id)
            VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")
        _accept(db, policy, principal, [])
        _accept(db, policy, other, None, version="v1")

        assert _receipt_purposes(db, principal) == _receipt_purposes(db, other)


class TestItRefusesRatherThanQuietlyDropping:

    def test_a_purpose_not_in_this_policy_is_refused(self, db, policy, principal):
        """Ignoring it would write a receipt recording less than the screen
        asked the person about."""
        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _accept(db, policy, principal, ["individual_learning_profile"])
        assert "PROCESSING_OPTIONAL_PURPOSE_INVALID" in str(raised.value)

        assert _receipt_purposes(db, principal) == []

    def test_a_required_purpose_cannot_be_passed_as_a_choice(
            self, db, policy, principal):
        """It is already in the receipt. Accepting it here would let a caller
        present a compulsory term as though it had been optional."""
        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _accept(db, policy, principal, [REQUIRED[0]])
        assert "PROCESSING_OPTIONAL_PURPOSE_INVALID" in str(raised.value)


class TestTheEvidenceCoversTheChoice:

    def test_replaying_a_key_with_a_different_choice_conflicts(
            self, db, policy, principal):
        """Without the choices in the evidence hash the second call would hash
        identically, pass as a silent no-op, and leave a receipt attesting to
        a decision the person did not make that time."""
        key = f"k-{uuid.uuid4()}"
        _accept(db, policy, principal, [OPTIONAL], key=key)

        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _accept(db, policy, principal, [], key=key)
        assert "IDEMPOTENCY_CONFLICT" in str(raised.value)

    def test_the_same_choice_replays_cleanly(self, db, policy, principal):
        key = f"k-{uuid.uuid4()}"
        first = _accept(db, policy, principal, [OPTIONAL], key=key)
        replay = _accept(db, policy, principal, [OPTIONAL], key=key)

        assert first["receipt_id"] == replay["receipt_id"]

    def test_order_and_duplicates_do_not_change_the_evidence(
            self, db, policy, principal):
        """The order a client sent them in is not a fact about consent."""
        key = f"k-{uuid.uuid4()}"
        _accept(db, policy, principal, [OPTIONAL], key=key)
        replay = _accept(db, policy, principal, [OPTIONAL, OPTIONAL, "  "],
                         key=key)

        assert replay["optional_purposes_recorded"] == [OPTIONAL]
