"""
STORY    As a speaker, I want a permit to send my recording to a provider to be
         issued only under my own consent, and my consent status read
         correctly in one call, so that no one else's consent can authorize
         processing of my voice.
OUTCOME
  O1  The person who recorded can still get a permit for their own recording.
  O2  Someone else naming my recording is refused, and nothing is written for
      them.
  O3  The one-call status read gives exactly the same answer as the old
      three-step read (signed-up account, guest without consent, guest who
      later signed up), and answers nothing rather than guess.
  O4  Only the server itself may call the status read, never a browser.
PROVES   O1 -> TestAPermitNamesOnlyItsOwnSource::test_the_acquiring_principal_can_still_mint_its_own_permit
         O2 -> TestAPermitNamesOnlyItsOwnSource::test_permit_rejects_foreign_source_recording
         O3 -> TestTheStatusReadsInOneTrip::test_an_authorized_account_reads_the_same_status,
               TestTheStatusReadsInOneTrip::test_an_unauthorized_guest_reads_the_same_status,
               TestTheStatusReadsInOneTrip::test_a_claimed_guest_resolves_through_the_one_resolver,
               TestTheStatusReadsInOneTrip::test_it_answers_nothing_rather_than_guess
         O4 -> TestTheStatusReadsInOneTrip::test_only_the_service_role_may_call_it
WHY      ML provenance audit 2026-09-22 (B-2, B-3): a permit could be minted
         for one guest's recording under another person's consent.
"""
from __future__ import annotations

import json
import os
import uuid

import psycopg2
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

POLICY = "phase1-binding-v1"
MISMATCH = "PROCESSING_SOURCE_PRINCIPAL_MISMATCH"


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
def policy(db):
    """An active Phase-1 policy and the four copy hashes an accept must echo.

    Receipts cannot exist without one, and both functions under test read
    through a receipt, so this is the smallest world in which either defect
    can be reproduced at all.

    An already-active policy is REUSED rather than replaced. Two things make
    that the only safe shape here: `processing_purpose_registry` freezes a
    purpose's control versions once it is operational, so a second registration
    that invents its own raises PURPOSE_CONTROL_VERSION_CONFLICT; and
    `activate_phase1_policy_v1` retires whatever was active, which would pull
    the policy out from under any suite sharing this lane. The tests care that
    a receipt can exist, not which policy it names.
    """
    active = None
    with db.cursor() as cur:
        cur.execute("""
            SELECT version, terms_copy_sha256, privacy_copy_sha256,
                   ai_notice_copy_sha256, agreement_copy_sha256,
                   upper(allowed_countries[1])
              FROM public.processing_policy_versions
             WHERE status = 'active' LIMIT 1""")
        active = cur.fetchone()
    if active:
        return {"version": active[0], "terms": active[1],
                "privacy": active[2], "ai": active[3], "agreement": active[4],
                "country": active[5]}

    hashes = {"version": POLICY, "country": "PL"}
    for name, copy in (
        ("terms", "Terms binding"), ("privacy", "Privacy binding"),
        ("ai", "AI notice binding"),
        ("agreement", "I am 18+ and accept the binding policy."),
    ):
        hashes[name] = _one(
            db, "SELECT encode(extensions.digest(%s, 'sha256'), 'hex')", (copy,)
        )
    artifact = {
        "approving_authority": "rehearsal-only",
        "approved_at": "2026-09-22T10:00:00Z", "metadata": {},
    }
    # The registry's own control versions, not invented ones: a purpose that
    # is already operational will not accept a different answer.
    _one(db, """
        SELECT public.register_phase1_policy_v1(
            %s::jsonb, %s::jsonb, %s::jsonb, %s::jsonb,
            (SELECT jsonb_agg(jsonb_build_object(
                 'purpose_id', id, 'lawful_basis_code', 'rehearsal-only',
                 'required_for_core_service', true,
                 'capability_version',
                     COALESCE(capability_version, 'phase1-b1'),
                 'reviewed_at',
                     COALESCE(reviewed_at, '2026-09-22T10:00:00Z'::timestamptz),
                 'retention_control_version',
                     COALESCE(retention_control_version, 'ret-b1'),
                 'deletion_control_version',
                     COALESCE(deletion_control_version, 'del-b1'),
                 'rights_control_version',
                     COALESCE(rights_control_version, 'rights-b1')
             ) ORDER BY id) FROM public.processing_purpose_registry
              WHERE phase = 'phase1'),
            'binding-rehearsal')""",
        (json.dumps({
            "version": POLICY,
            "terms_version": "terms-b1", "terms_copy": "Terms binding",
            "terms_copy_sha256": hashes["terms"],
            "privacy_version": "privacy-b1", "privacy_copy": "Privacy binding",
            "privacy_copy_sha256": hashes["privacy"],
            "ai_notice_version": "ai-b1",
            "ai_notice_copy": "AI notice binding",
            "ai_notice_copy_sha256": hashes["ai"],
            "agreement_copy": "I am 18+ and accept the binding policy.",
            "agreement_copy_sha256": hashes["agreement"],
            "allowed_countries": ["pl", "fr"],
         }),
         json.dumps({**artifact, "artifact_kind": "product_legal_approval",
                     "version": "legal-b1", "object_key": "r/legal-b1",
                     "sha256": "1" * 64}),
         json.dumps({**artifact, "artifact_kind": "power_score_classification",
                     "version": "power-b1", "object_key": "r/power-b1",
                     "sha256": "2" * 64,
                     "metadata": {"biometric_identification": False,
                                  "sex_gender_inference": False,
                                  "emotion_intention_inference": False,
                                  "pipeline_version":
                                      "voice-confidence-universal-v3"}}),
         json.dumps({**artifact, "artifact_kind": "article_50_assessment",
                     "version": "article50-b1",
                     "object_key": "r/article50-b1", "sha256": "3" * 64})))
    _one(db, "SELECT public.activate_phase1_policy_v1(%s, %s, %s)",
         (POLICY, "binding-rehearsal", "c" * 64))
    return hashes


def _principal(db, *, guest=False):
    if guest:
        return _one(db, """
            INSERT INTO public.owner_principals (id, guest_secret_hash)
            VALUES (gen_random_uuid(), encode(
                extensions.digest(gen_random_uuid()::text, 'sha256'), 'hex'))
            RETURNING id""")
    return _one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id""")


def _accept(db, hashes, principal):
    return _one(db, """
        SELECT public.accept_phase1_processing_authorization_v1(
            %s, %s, %s, %s, %s, %s, 'agree_and_continue', true, %s,
            'en-GB', 'binding-client', '2026-09-22T10:05:00Z', %s)""",
        (principal, hashes["version"], hashes["terms"],
         hashes["privacy"], hashes["ai"], hashes["agreement"],
         hashes["country"], f"accept-{uuid.uuid4()}"))


def _intake(db, principal):
    """A real acquisition: attempt row, audio object, processing job."""
    project = _one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'binding') RETURNING id""", (principal,))
    attempt, recording = str(uuid.uuid4()), str(uuid.uuid4())
    _one(db, """
        SELECT public.finalize_phase1_recording_intake_v1(
            %s, %s, %s, %s, %s, 'r2', 'lab-audio', %s, 4096, 'audio/webm',
            %s, 'read_after_write_sha256')""",
        (attempt, principal, project, recording, f"upload-{uuid.uuid4()}",
         f"takes/{recording}.webm",
         _one(db, "SELECT encode(extensions.digest(%s, 'sha256'), 'hex')",
              (recording,))))
    return {"project": project, "attempt": attempt, "recording": recording}


def _permit(db, principal, take, recording, *, key=None):
    return _one(db, """
        SELECT public.issue_phase1_provider_permit_v1(
            %s, %s, %s, 'openai', 'transcription', %s, %s::jsonb, %s, 900)""",
        (principal, take, recording, "e" * 64,
         json.dumps({"content": ["audio_bytes"],
                     "purpose": "transcription_feedback"}),
         key or f"permit-{uuid.uuid4()}"))


class TestAPermitNamesOnlyItsOwnSource:
    """B-2. The function now says whose recording it was handed."""

    def test_the_acquiring_principal_can_still_mint_its_own_permit(
            self, db, policy):
        """First, that the check is not a blanket refusal.

        Without this case a fix that raised on everything would look green.
        """
        p1 = _principal(db, guest=True)
        _accept(db, policy, p1)
        source = _intake(db, p1)

        result = _permit(db, p1, source["attempt"], source["recording"])

        assert result["operation_kind"] == "transcription"
        assert _one(db, """
            SELECT acquisition_principal_id::text
              FROM public.processing_authorization_snapshots
             WHERE source_recording_id = %s""", (source["recording"],)) == p1

    def test_permit_rejects_foreign_source_recording(self, db, policy):
        """The named regression test for B-2.

        Reproduces the auditor's experiment: P2 holds its own receipt and
        names P1's recording. Before this change it succeeded, and
        `processing_authorization_snapshots` then held two rows for that one
        recording naming different principals — with nothing downstream able
        to say which was the truth.
        """
        p1, p2 = _principal(db, guest=True), _principal(db, guest=True)
        _accept(db, policy, p1)
        _accept(db, policy, p2)
        source = _intake(db, p1)

        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _permit(db, p2, source["attempt"], source["recording"])
        assert MISMATCH in str(raised.value)

        assert _one(db, """
            SELECT count(*) FROM public.processing_authorization_snapshots
             WHERE source_recording_id = %s
               AND acquisition_principal_id = %s""",
            (source["recording"], p2)) == 0, (
            "a snapshot for another principal's recording was written anyway")


class TestTheStatusReadsInOneTrip:
    """0473. `read_phase1_processing_status_v1` answers, in one call, exactly
    what the owner lookup, the resolver and the status function answer in
    three — and nothing when it cannot do the whole job."""

    @staticmethod
    def _user_principal(db):
        with db.cursor() as cur:
            cur.execute("""
                INSERT INTO public.owner_principals (id, user_id)
                VALUES (gen_random_uuid(), gen_random_uuid())
                RETURNING id::text, user_id::text""")
            return cur.fetchone()

    @staticmethod
    def _two_steps(db, owner, user_id):
        acquirer = _one(db, """
            SELECT public.resolve_phase1_acquisition_principal_v1(%s, %s)::text
            """, (owner, user_id))
        return acquirer, _one(db, """
            SELECT public.get_phase1_processing_authorization_v1(%s)""",
            (acquirer,))

    @staticmethod
    def _one_trip(db, user_id=None, owner=None):
        return _one(db, """
            SELECT public.read_phase1_processing_status_v1(%s, %s)""",
            (user_id, owner))

    def test_an_authorized_account_reads_the_same_status(self, db, policy):
        principal, user_id = self._user_principal(db)
        _accept(db, policy, principal)

        acquirer, status = self._two_steps(db, principal, user_id)
        assert status["code"] == "PROCESSING_AUTHORIZED"
        assert self._one_trip(db, user_id=user_id) == {
            "acquisition_principal_id": acquirer, "status": status}

    def test_an_unauthorized_guest_reads_the_same_status(self, db, policy):
        guest = _principal(db, guest=True)

        acquirer, status = self._two_steps(db, guest, None)
        assert status["code"] == "PROCESSING_AUTHORIZATION_REQUIRED"
        assert self._one_trip(db, owner=guest) == {
            "acquisition_principal_id": acquirer, "status": status}

    def test_a_claimed_guest_resolves_through_the_one_resolver(
            self, db, policy):
        """The guest accepted and recorded, then signed up: the resolver
        (0355, 0414) names the GUEST as the acquirer. The one-trip read must
        say the same, and read the guest's status, not the account's."""
        guest = _principal(db, guest=True)
        _accept(db, policy, guest)
        _intake(db, guest)
        account, user_id = self._user_principal(db)
        _one(db, """
            INSERT INTO public.owner_claim_events (
                source_owner_principal_id, target_owner_principal_id,
                claimed_user_id, claim_proof_hash, idempotency_key,
                source_created_at)
            VALUES (%s, %s, %s, repeat('c', 64), %s, now() - interval '1 hour')
            RETURNING id""", (guest, account, user_id, f"claim-{uuid.uuid4()}"))

        acquirer, status = self._two_steps(db, account, user_id)
        assert acquirer == guest
        assert status["code"] == "PROCESSING_AUTHORIZED"
        assert self._one_trip(db, user_id=user_id) == {
            "acquisition_principal_id": guest, "status": status}

    def test_it_answers_nothing_rather_than_guess(self, db, policy):
        """No owner principal yet (the application creates one), an account
        id offered as a guest, or no argument at all: null, so the
        application takes the path it takes today."""
        nothing = {"acquisition_principal_id": None, "status": None}
        account, _ = self._user_principal(db)
        assert self._one_trip(db, user_id=str(uuid.uuid4())) == nothing
        assert self._one_trip(db, owner=account) == nothing
        assert self._one_trip(db) == nothing

    def test_only_the_service_role_may_call_it(self, db):
        signature = "public.read_phase1_processing_status_v1(uuid,uuid)"
        with db.cursor() as cur:
            cur.execute("""
                SELECT has_function_privilege('service_role', %s, 'EXECUTE'),
                       has_function_privilege('anon', %s, 'EXECUTE'),
                       has_function_privilege('authenticated', %s, 'EXECUTE')
                """, (signature, signature, signature))
            assert cur.fetchone() == (True, False, False)
