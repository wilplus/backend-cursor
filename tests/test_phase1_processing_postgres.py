"""Authorization evidence binds to the principal that acquired the audio.

B-2 and B-3 (major), ML provenance audit 2026-09-22.

Phase-1 lineage rests on one claim: the principal named on a permit is the
principal that acquired the recording. Two functions let that claim be false.

  * B-2 — `issue_phase1_provider_permit_v1` read the authorization of
    `p_acquisition_principal_id` and then inserted `p_source_take_id` /
    `p_source_recording_id` verbatim, with nothing anywhere saying those
    coordinates were that principal's to name. The auditor minted a permit
    for one guest's recording under another principal's receipt.
  * B-3 — `resolve_phase1_acquisition_principal_v1` returned a claim's SOURCE
    only when that source already held a receipt, and otherwise returned the
    TARGET. A guest who recorded while the gate was off holds no receipt by
    construction, so after signing up their recordings resolved to the new
    account principal, whose receipt was signed later for an acquisition that
    had already happened.

These cases EXECUTE the real functions against a disposable PostgreSQL lane.
The whole finding is about what a function does and does not refuse, and the
suite that was supposed to cover this path
(`test_phase1_processing_rehearsal_contract.py`) only asserts substrings of a
.sql file that nothing runs — which is why neither defect was caught.
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


def _claim(db, source, target, user_id):
    _one(db, """
        INSERT INTO public.owner_claim_events (
            source_owner_principal_id, target_owner_principal_id,
            claimed_user_id, claim_proof_hash, idempotency_key,
            source_created_at)
        VALUES (%s, %s, %s, %s, %s, now()) RETURNING id""",
        (source, target, user_id, "a" * 64, f"claim-{uuid.uuid4()}"))


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

    def test_a_take_claimed_into_the_acquirer_is_still_its_own(
            self, db, policy):
        """No attempt row — every recording acquired while the gate was off.

        `claim_guest_owner` rewrites `v2_sessions.owner_principal_id`, so the
        acquirer of such a Take is either its current owner or a principal
        claimed into it. Both must pass, or signing up would cut a speaker off
        from their own recordings.
        """
        guest, account = _principal(db, guest=True), _principal(db)
        user_id = _one(db, "SELECT user_id::text FROM public.owner_principals"
                           " WHERE id = %s", (account,))
        _accept(db, policy, guest)
        _accept(db, policy, account)
        take = _one(db, """
            INSERT INTO public.v2_sessions (
                id, arc_id, user_id, take_index, owner_principal_id)
            VALUES (gen_random_uuid(), gen_random_uuid(),
                    gen_random_uuid(), 1, %s)
            RETURNING id""", (account,))
        _claim(db, guest, account, user_id)

        assert _permit(db, account, take, None)["operation_kind"] == \
            "transcription"
        assert _permit(db, guest, take, None)["operation_kind"] == \
            "transcription"

    def test_a_third_principal_cannot_name_that_take(self, db, policy):
        """The other half of the case above: the claim chain is the whole
        allowance, not a door held open for anyone."""
        owner, stranger = _principal(db, guest=True), _principal(db, guest=True)
        _accept(db, policy, owner)
        _accept(db, policy, stranger)
        take = _one(db, """
            INSERT INTO public.v2_sessions (
                id, arc_id, user_id, take_index, owner_principal_id)
            VALUES (gen_random_uuid(), gen_random_uuid(),
                    gen_random_uuid(), 1, %s)
            RETURNING id""", (owner,))

        with pytest.raises(psycopg2.errors.RaiseException) as raised:
            _permit(db, stranger, take, None)
        assert MISMATCH in str(raised.value)

    def test_a_take_we_cannot_place_is_left_alone(self, db, policy):
        """Absence of evidence is not evidence of theft.

        A source coordinate with no attempt row and no session row proves
        nothing either way, and refusing on it would take the live loop down
        for a data gap this function did not create.
        """
        principal = _principal(db, guest=True)
        _accept(db, policy, principal)

        assert _permit(db, principal, str(uuid.uuid4()), None)[
            "operation_kind"] == "transcription"


class TestTheAcquirerIsFrozenAtAcquisition:
    """B-3. A later receipt cannot stand in for an earlier acquisition."""

    def test_claimed_guest_without_receipt_cannot_be_authorized_by_target(
            self, db, policy):
        """The named regression test for B-3.

        The guest holds no receipt — the state of every guest who recorded
        while the gate was off. Before this change the resolver skipped them
        for exactly that reason and returned the account principal, so the
        account's later receipt was read as authority for the guest's earlier
        acquisition.
        """
        guest, account = _principal(db, guest=True), _principal(db)
        user_id = _one(db, "SELECT user_id::text FROM public.owner_principals"
                           " WHERE id = %s", (account,))
        _claim(db, guest, account, user_id)
        _accept(db, policy, account)

        assert _one(db, """
            SELECT public.resolve_phase1_acquisition_principal_v1(%s, %s)""",
            (account, user_id)) == guest, (
            "the account principal was named as the acquirer of the guest's "
            "recording")

    def test_a_source_that_holds_a_receipt_still_wins(self, db, policy):
        """Receipt existence survives as a preference, not a filter.

        This is the behaviour the old WHERE clause produced, and it has to be
        unchanged: where several guests were claimed into one account, the one
        that accepted the policy is still the answer.
        """
        early, late = _principal(db, guest=True), _principal(db, guest=True)
        account = _principal(db)
        user_id = _one(db, "SELECT user_id::text FROM public.owner_principals"
                           " WHERE id = %s", (account,))
        _accept(db, policy, early)
        _claim(db, early, account, user_id)
        _claim(db, late, account, user_id)

        assert _one(db, """
            SELECT public.resolve_phase1_acquisition_principal_v1(%s, %s)""",
            (account, user_id)) == early

    def test_an_account_that_was_never_claimed_resolves_to_itself(
            self, db, policy):
        """No claim event, no indirection."""
        account = _principal(db)
        user_id = _one(db, "SELECT user_id::text FROM public.owner_principals"
                           " WHERE id = %s", (account,))

        assert _one(db, """
            SELECT public.resolve_phase1_acquisition_principal_v1(%s, %s)""",
            (account, user_id)) == account
