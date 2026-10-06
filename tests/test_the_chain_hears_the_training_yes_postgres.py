"""0430 on the released lane: the confidence chain hears the training yes.

Founder 2026-10-05 (decisions log N48.5 Q27 A): one consent authority, the
training yes; bundled-era yeses count for nothing (N2, N10.6). Executed
against the real functions:

  * the ring row's consent door says yes only for an active training yes
    with a bound speaker, never for a bundled grant, never after a
    withdrawal; the personalised-practice branch is 0394's text;
  * the canonical promotion freezes a TRAINING snapshot and refuses a
    bundled-only owner, rolling the Take promotion back with it (the
    application then promotes plainly: take_lifecycle);
  * the training switch's yes binds the speaker in the same transaction, a
    refused yes binds nobody, and a principal is never rebound;
  * readiness counts the training yes, and browser roles call nothing new;
  * F-8: a check of a chain object or of a door 2 release appends one
    verification row, the database decides whether it verified, and the
    rows are never rewritten.

Every write happens inside a transaction that is rolled back. The target
must be a disposable local database whose name starts with
``willab_confident_moment_``.
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, timedelta

import psycopg2
import psycopg2.errors
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

TOGGLE_COPY = "Use my practice text and my coach's notes on it to train the models."
TOGGLE_SHA = hashlib.sha256(TOGGLE_COPY.encode()).hexdigest()
MANIFEST = {
    "source_schema_version": "confidence-source-audio-v1",
    "audio": {
        "object_store": "cloudflare_r2",
        "bucket": "mlc2-rehearsal",
        "object_key": "confidence/0430-source.webm",
        "sha256": "8" * 64,
        "byte_size": 4096,
        "content_type": "audio/webm",
    },
}
NEW_FUNCTIONS = (
    "create_mlc2_training_consent_snapshot_v1(uuid,uuid,uuid,uuid)",
    "bind_mlc2_training_speaker_v1(uuid,text,text,text,text)",
    "accept_mlc2_training_consent_v1(uuid,text,text,text,text,text,text,"
    "jsonb,timestamptz,text,text,text,text,text)",
    "get_mlc2_blind_coach_ratings_v1(uuid,uuid[])",
    # F-3
    "get_mlc2_speaker_splits_v1(uuid[],text)",
    # F-8
    "record_mlc2_object_verification_v1(text,text,text,bigint,text,text)",
    "list_mlc2_objects_due_verification_v1(integer)",
    "record_pair_release_verification_v1(uuid,text,text,bigint,boolean,text,"
    "text)",
)


@pytest.fixture(scope="module")
def conn():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    if not parsed.get("host", "").startswith(
        ("/tmp/willab-", "/private/tmp/willab-")
    ):
        raise RuntimeError("Refusing a database outside the rehearsal socket")
    connection = psycopg2.connect(DSN)
    connection.autocommit = False
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def cur(conn):
    """One rolled-back transaction per test."""
    cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        yield cursor
    finally:
        conn.rollback()
        cursor.close()


def _one(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    if row is None:
        return None
    return list(row.values())[0]


def _row(cur, sql, params=()):
    cur.execute(sql, params)
    row = cur.fetchone()
    return dict(row) if row else None


def _raises(cur, code, sql, params=()):
    cur.execute("SAVEPOINT expected_refusal")
    with pytest.raises(psycopg2.Error) as refused:
        cur.execute(sql, params)
    cur.execute("ROLLBACK TO SAVEPOINT expected_refusal")
    assert code in str(refused.value), str(refused.value)


def _principal(cur):
    return str(_one(cur, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id"""))


def _processing_version(cur):
    """A processing policy version a training policy can require. The lane
    carries one once the earlier suites ran; alone, this suite writes a
    draft one inside its own rolled-back transaction (C1 matches the
    receipt's version exactly, whatever its status)."""
    version = _one(cur, """
        SELECT version FROM public.processing_policy_versions
         ORDER BY created_at LIMIT 1""")
    if version:
        return version
    version = f"phase1-0430-{uuid.uuid4()}"
    digest = hashlib.sha256(b"rehearsal").hexdigest()
    cur.execute("""
        INSERT INTO public.processing_policy_versions (
            version, status, terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256, allowed_countries,
            created_by)
        VALUES (%s, 'draft', 't', 'terms', %s, 'p', 'privacy', %s, 'a',
                'notice', %s, 'agree', %s, ARRAY['pl'], 'rehearsal-0430')""",
        (version, digest, digest, digest, digest))
    return version


def _training_policy(cur):
    """The active training-only policy: the consent suite's when it ran
    first, else one of our own (the database allows one at a time)."""
    live = _row(cur, """
        SELECT policy.version, approval.approved_copy_sha256 AS sha,
               approval.terms_version AS terms,
               approval.privacy_policy_version AS privacy,
               policy.requires_processing_policy_version AS processing
          FROM public.ml_consent_policies policy
          JOIN public.ml_product_legal_approvals approval
            ON approval.id = policy.product_legal_approval_id
         WHERE policy.grant_scope = 'training_only'
           AND policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
         ORDER BY policy.active_from DESC LIMIT 1""")
    if live:
        return live
    processing = _processing_version(cur)
    _one(cur, """
        SELECT public.configure_mlc2_training_consent_policy_v1(
            'training-approval-0430', %s, %s, 'training-only-0430-v1',
            'terms-t', 'privacy-t', 'founder+counsel', now(), ARRAY['PL'],
            'evidence/training.pdf', %s, %s, now() - interval '1 minute')""",
        (TOGGLE_SHA, TOGGLE_COPY, "e" * 64, processing))
    return {"version": "training-only-0430-v1", "sha": TOGGLE_SHA,
            "terms": "terms-t", "privacy": "privacy-t",
            "processing": processing}


def _receipt(cur, principal, processing):
    _one(cur, """
        INSERT INTO public.processing_authorization_receipts (
            acquisition_principal_id, policy_id, idempotency_key,
            explicit_action, age_18_attested, country_of_residence, locale,
            client_version, accepted_at, evidence_sha256)
        SELECT %s, id, %s, 'agree_and_continue', true, 'PL', 'en-GB', 'test',
               now(), %s
          FROM public.processing_policy_versions WHERE version = %s
        RETURNING id""",
        (principal, f"r-{uuid.uuid4()}", "a" * 64, processing))


def _action(policy):
    return json.dumps({"accepted": True, "control": "training_toggle",
                       "copy_sha256": policy["sha"]})


def _yes(cur, principal, policy):
    """A training yes through the only training writer (0373/0412)."""
    _receipt(cur, principal, policy["processing"])
    row = _row(cur, """
        SELECT * FROM public.record_mlc2_training_consent_grant_v2(
            %s, %s, 'PL', %s, %s, 'settings/training', 'test', %s::jsonb,
            now() - interval '1 second', %s)""",
        (principal, policy["version"], policy["terms"], policy["privacy"],
         _action(policy), f"g-{uuid.uuid4()}"))
    return str(row["id"])


def _withdraw(cur, principal, grant_id):
    _row(cur, """
        SELECT * FROM public.record_mlc2_consent_withdrawal_v2(
            %s, %s, 'pooled_model_improvement', 'settings/training', 'test',
            '{"control": "training_toggle", "accepted": false}'::jsonb,
            now(), %s)""", (principal, grant_id, f"w-{uuid.uuid4()}"))


def _hash():
    return hashlib.sha256(uuid.uuid4().bytes).hexdigest()


def _bind(cur, principal, identity=None):
    _one(cur, """
        SELECT public.register_ml_speaker_principal_v1(
            %s, %s, 'speaker-resolution-v1', 'initial', %s, 'rehearsal',
            'speaker-sha256-80-10-10-v1')""",
        (principal, identity or _hash(), _hash()))


def _bundled_grant(cur, principal):
    """A bundled-era two-purpose grant, as the retired route recorded it
    (inserted directly: the v1 configure refuses while a training policy
    is active)."""
    version = f"bundled-0430-{uuid.uuid4()}"
    sha = "b" * 64
    approval = _one(cur, """
        INSERT INTO public.ml_product_legal_approvals (
            approval_reference, approved_copy_sha256, onboarding_copy,
            consent_policy_version, terms_version, privacy_policy_version,
            approving_authority, approved_at, jurisdictions, article_6_basis,
            article_9_treatment, evidence_object_key, evidence_sha256)
        VALUES (%s, %s, 'bundled copy', %s, 'terms-b', 'privacy-b', 'x',
                now() - interval '2 days', ARRAY['PL'], '6(1)(a)',
                'not_applicable', 'k', %s)
        RETURNING id""", (f"appr-{version}", sha, version, "c" * 64))
    _one(cur, """
        INSERT INTO public.ml_consent_policies (
            version, product_legal_approval_id, required_for_service,
            bundled_ui, active_from)
        VALUES (%s, %s, true, true, now() - interval '2 days')
        RETURNING version""", (version, approval))
    return str(_row(cur, """
        SELECT * FROM public.record_mlc2_consent_grant_v1(
            %s, %s, 'PL', 'terms-b', 'privacy-b', '/v2/user/mlc2-consent',
            'test', %s::jsonb, now() - interval '1 day', false, %s)""",
        (principal, version,
         json.dumps({"accepted": True, "copy_sha256": sha}),
         f"bundled-{uuid.uuid4()}"))["id"]), version


def _current(cur, principal):
    return _one(cur, "SELECT public.ring_consent_is_current_v1(%s, "
                     "'pooled_model_improvement')", (principal,))


def _set_ring(cur, principal, ring):
    _one(cur, "SELECT public.set_principal_ring_v1(%s::uuid, %s, NULL, 'test')",
         (principal, ring))


# ── One consent authority ─────────────────────────────────────────────────

class TestOneConsentAuthority:
    def test_a_training_yes_with_a_bound_speaker_is_current(self, cur):
        principal = _principal(cur)
        _yes(cur, principal, _training_policy(cur))
        _bind(cur, principal)
        assert _current(cur, principal) is True

    def test_a_training_yes_without_a_speaker_is_not_current(self, cur):
        principal = _principal(cur)
        _yes(cur, principal, _training_policy(cur))
        assert _current(cur, principal) is False

    def test_a_bundled_grant_counts_for_nothing(self, cur):
        principal = _principal(cur)
        grant, _version = _bundled_grant(cur, principal)
        _bind(cur, principal)
        # The bundled grant is on record, two purposes and all, and a
        # speaker is bound: under 0394 that was the whole of "current".
        assert _one(cur, "SELECT count(*) FROM public.ml_consent_event_purposes "
                         "WHERE consent_event_id = %s", (grant,)) == 2
        assert _current(cur, principal) is False

    def test_a_withdrawn_yes_is_not_current(self, cur):
        principal = _principal(cur)
        grant = _yes(cur, principal, _training_policy(cur))
        _bind(cur, principal)
        assert _current(cur, principal) is True
        _withdraw(cur, principal, grant)
        assert _current(cur, principal) is False

    def test_the_ring_row_is_on_at_ring_5_with_the_yes_and_off_below(self, cur):
        principal = _principal(cur)
        _yes(cur, principal, _training_policy(cur))
        _bind(cur, principal)
        _set_ring(cur, principal, 4)
        assert _one(cur, "SELECT public.feature_is_on_v1("
                         "'confidence_learning_writes', %s::uuid)",
                    (principal,)) is False
        _set_ring(cur, principal, 5)
        assert _one(cur, "SELECT public.feature_is_on_v1("
                         "'confidence_learning_writes', %s::uuid)",
                    (principal,)) is True

    def test_ring_5_without_the_yes_stays_off(self, cur):
        principal = _principal(cur)
        _bind(cur, principal)
        _set_ring(cur, principal, 5)
        assert _one(cur, "SELECT public.feature_is_on_v1("
                         "'confidence_learning_writes', %s::uuid)",
                    (principal,)) is False

    def test_the_personalised_practice_branch_is_0394s_text(self, cur):
        definition = _one(cur, "SELECT pg_get_functiondef(to_regprocedure("
                               "'public.ring_consent_is_current_v1(uuid,text)'))")
        branch = definition[definition.index("'personalised_practice'"):
                            definition.index("ELSIF p_purpose")]
        assert "to_regproc('public.get_phase1_consent_choices_v1(uuid)')" in branch
        assert "get_mlc2_principal_consent_status_v1" not in definition
        assert "to_regprocedure('public.get_mlc2_training_consent_status_v2(uuid)')" \
            in definition

    def test_the_phase2_policy_exists_only_as_a_training_policy(self, cur):
        _training_policy(cur)
        assert _one(cur, "SELECT public.ring_consent_policy_exists_v1("
                         "'pooled_model_improvement')") is True
        # Retire every training policy inside this rolled-back transaction:
        # a bundled policy alone no longer makes the Phase-2 "yes" available.
        _bundled_grant(cur, _principal(cur))
        cur.execute("ALTER TABLE public.ml_consent_policies "
                    "DISABLE TRIGGER ml_consent_policies_append_only")
        cur.execute("UPDATE public.ml_consent_policies SET retired_at = now() "
                    "WHERE grant_scope = 'training_only' AND retired_at IS NULL")
        assert _one(cur, "SELECT public.ring_consent_policy_exists_v1("
                         "'pooled_model_improvement')") is False


# ── The snapshot comes from the training yes ──────────────────────────────

def _attempt(cur, owner):
    project, attempt, recording = (str(uuid.uuid4()) for _ in range(3))
    tag = uuid.uuid4().hex[:8]
    cur.execute("INSERT INTO public.projects (id, owner_principal_id, display_name) "
                "VALUES (%s, %s, %s)", (project, owner, "0430"))
    cur.execute("INSERT INTO public.recordings (id) VALUES (%s)", (recording,))
    cur.execute(
        "INSERT INTO public.v2_sessions (id, user_id, owner_principal_id, project_id, arc_id, "
        "take_index, analysis_state, recording_kind, recording_1_id) "
        "VALUES (%s, %s, %s, %s, %s, 1, 'ready', 'spoken', %s)",
        (attempt, str(uuid.uuid4()), owner, project, f"arc-0430-{tag}", recording))
    cur.execute(
        "INSERT INTO public.recording_attempts (id, owner_principal_id, project_id, "
        "upload_idempotency_key, recording_id, storage_bucket, storage_key, recording_kind, status) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'spoken', 'processing')",
        (attempt, owner, project, f"upload-0430-{tag}", recording,
         MANIFEST["audio"]["bucket"], MANIFEST["audio"]["object_key"]))
    return attempt, project


def _promote(cur, attempt):
    return _one(cur, """
        SELECT public.promote_recording_attempt_with_mlc2_confidence_v1(
            %s, %s, NULL, 1, %s, %s, %s, %s)""",
        (attempt, "5" * 64, "6" * 64, "7" * 64, f"promotion-0430-{attempt}",
         psycopg2.extras.Json(MANIFEST)))


class TestTheSnapshotComesFromTheTrainingYes:
    def test_the_snapshot_names_the_training_grant_and_never_coaching(self, cur):
        owner = _principal(cur)
        grant = _yes(cur, owner, _training_policy(cur))
        attempt, project = _attempt(cur, owner)
        snapshot = _row(cur, "SELECT * FROM public.create_mlc2_training_consent_"
                             "snapshot_v1(%s, %s, NULL, %s)", (owner, attempt, project))
        assert str(snapshot["grant_event_id"]) == grant
        assert snapshot["retention_state"] == "eligible"
        state = snapshot["purpose_state"]
        assert state["pooled_model_improvement"]["authorized"] is True
        assert state["pooled_model_improvement"]["grant_scope"] == "training_only"
        assert state["pooled_model_improvement"]["article_9_basis"] is None
        assert state["personalized_coaching"]["authorized"] is False
        again = _row(cur, "SELECT * FROM public.create_mlc2_training_consent_"
                          "snapshot_v1(%s, %s, NULL, %s)", (owner, attempt, project))
        assert again["id"] == snapshot["id"]

    def test_no_yes_no_snapshot(self, cur):
        owner = _principal(cur)
        _bundled_grant(cur, owner)
        attempt, project = _attempt(cur, owner)
        _raises(cur, "no active training yes",
                "SELECT public.create_mlc2_training_consent_snapshot_v1(%s, %s, NULL, %s)",
                (owner, attempt, project))

    def test_someone_elses_attempt_is_refused(self, cur):
        owner, stranger = _principal(cur), _principal(cur)
        _yes(cur, stranger, _training_policy(cur))
        attempt, project = _attempt(cur, owner)
        _raises(cur, "does not belong to acquisition principal",
                "SELECT public.create_mlc2_training_consent_snapshot_v1(%s, %s, NULL, %s)",
                (stranger, attempt, project))


# ── The canonical promotion reads only the training snapshot ──────────────

class TestThePromotion:
    def test_a_training_yes_promotes_canonically(self, cur):
        owner = _principal(cur)
        grant = _yes(cur, owner, _training_policy(cur))
        _bind(cur, owner)
        attempt, _project = _attempt(cur, owner)
        promotion = _promote(cur, attempt)
        assert promotion["take_id"] and promotion["producer_replayed"] is False
        receipt = _row(cur, "SELECT consent_snapshot_id FROM "
                            "public.ml_confidence_producer_receipts WHERE take_id = %s",
                       (attempt,))
        snapshot = _row(cur, "SELECT grant_event_id, consent_policy_version "
                             "FROM public.ml_consent_snapshots WHERE id = %s",
                        (receipt["consent_snapshot_id"],))
        assert str(snapshot["grant_event_id"]) == grant
        assert _one(cur, "SELECT grant_scope FROM public.ml_consent_policies "
                         "WHERE version = %s", (snapshot["consent_policy_version"],)) \
            == "training_only"

    def test_a_bundled_grant_alone_is_refused_and_the_take_rolls_back(self, cur):
        owner = _principal(cur)
        _bundled_grant(cur, owner)
        _bind(cur, owner)
        attempt, _project = _attempt(cur, owner)
        _raises(cur, "no active training yes",
                "SELECT public.promote_recording_attempt_with_mlc2_confidence_v1("
                "%s, %s, NULL, 1, %s, %s, %s, %s)",
                (attempt, "5" * 64, "6" * 64, "7" * 64, f"p-{attempt}",
                 psycopg2.extras.Json(MANIFEST)))
        assert _one(cur, "SELECT count(*) FROM public.takes WHERE id = %s",
                    (attempt,)) == 0

    def test_a_pre_made_bundled_snapshot_is_not_honoured(self, cur):
        owner = _principal(cur)
        _bundled_grant(cur, owner)
        _bind(cur, owner)
        attempt, _project = _attempt(cur, owner)
        bundled = _row(cur, "SELECT * FROM public.create_mlc2_consent_snapshot_v1("
                            "%s, %s, NULL, NULL)", (owner, attempt))
        grant = _yes(cur, owner, _training_policy(cur))
        _promote(cur, attempt)
        receipt = _row(cur, "SELECT consent_snapshot_id FROM "
                            "public.ml_confidence_producer_receipts WHERE take_id = %s",
                       (attempt,))
        assert receipt["consent_snapshot_id"] != bundled["id"]
        assert str(_one(cur, "SELECT grant_event_id FROM public.ml_consent_snapshots "
                             "WHERE id = %s", (receipt["consent_snapshot_id"],))) == grant

    def test_a_withdrawn_yes_is_refused(self, cur):
        owner = _principal(cur)
        grant = _yes(cur, owner, _training_policy(cur))
        _bind(cur, owner)
        _withdraw(cur, owner, grant)
        attempt, _project = _attempt(cur, owner)
        _raises(cur, "no active training yes",
                "SELECT public.promote_recording_attempt_with_mlc2_confidence_v1("
                "%s, %s, NULL, 1, %s, %s, %s, %s)",
                (attempt, "5" * 64, "6" * 64, "7" * 64, f"p-{attempt}",
                 psycopg2.extras.Json(MANIFEST)))

    def test_an_unbound_speaker_is_still_refused(self, cur):
        owner = _principal(cur)
        _yes(cur, owner, _training_policy(cur))
        attempt, _project = _attempt(cur, owner)
        _raises(cur, "requires a resolved speaker",
                "SELECT public.promote_recording_attempt_with_mlc2_confidence_v1("
                "%s, %s, NULL, 1, %s, %s, %s, %s)",
                (attempt, "5" * 64, "6" * 64, "7" * 64, f"p-{attempt}",
                 psycopg2.extras.Json(MANIFEST)))


# ── The speaker is bound through the training yes (F-3) ───────────────────

def _accept(cur, principal, policy, *, identity=None, action=None, key=None):
    return _one(cur, """
        SELECT public.accept_mlc2_training_consent_v1(
            %s, %s, 'PL/EU', %s, %s, '/v2/user/training-consent', 'test',
            %s::jsonb, now() - interval '1 second', %s,
            %s, 'supabase-auth-sub-v1', %s, 'authenticated-training-consent-v1')""",
        (principal, policy["version"], policy["terms"], policy["privacy"],
         action or _action(policy), key or f"a-{uuid.uuid4()}",
         identity or _hash(), _hash()))


class TestTheSpeakerIsBoundThroughTheYes:
    def test_the_yes_binds_the_speaker_and_assigns_its_split(self, cur):
        principal = _principal(cur)
        policy = _training_policy(cur)
        _receipt(cur, principal, policy["processing"])
        accepted = _accept(cur, principal, policy)
        assert accepted["accepted"] is True and accepted["speaker_bound"] is True
        binding = _row(cur, "SELECT speaker_id, binding_kind FROM "
                            "public.ml_speaker_principals WHERE acquisition_principal_id = %s",
                       (principal,))
        assert str(binding["speaker_id"]) == accepted["speaker_id"]
        assert binding["binding_kind"] == "verified_account_link"
        assert _one(cur, "SELECT split FROM public.ml_speaker_split_assignments "
                         "WHERE speaker_id = %s AND split_policy_version = "
                         "'speaker-sha256-80-10-10-v1'", (binding["speaker_id"],)) \
            in ("train", "validation", "test")
        assert _current(cur, principal) is True

    def test_a_refused_yes_binds_nobody(self, cur):
        principal = _principal(cur)  # no processing receipt: C1 refuses
        policy = _training_policy(cur)
        _raises(cur, "TRAINING_CONSENT_NEEDS_POLICY_RECEIPT",
                """SELECT public.accept_mlc2_training_consent_v1(
                    %s, %s, 'PL/EU', %s, %s, '/v2/user/training-consent', 'test',
                    %s::jsonb, now() - interval '1 second', %s,
                    %s, 'supabase-auth-sub-v1', %s, 'authenticated-training-consent-v1')""",
                (principal, policy["version"], policy["terms"], policy["privacy"],
                 _action(policy), f"a-{uuid.uuid4()}", _hash(), _hash()))
        assert _one(cur, "SELECT count(*) FROM public.ml_speaker_principals "
                         "WHERE acquisition_principal_id = %s", (principal,)) == 0

    def test_a_yes_on_another_control_is_refused_and_binds_nobody(self, cur):
        principal = _principal(cur)
        policy = _training_policy(cur)
        _receipt(cur, principal, policy["processing"])
        signup = json.dumps({"accepted": True, "control": "signup",
                             "copy_sha256": policy["sha"]})
        _raises(cur, "TRAINING_CONSENT_NOT_ITS_OWN_ACT",
                """SELECT public.accept_mlc2_training_consent_v1(
                    %s, %s, 'PL/EU', %s, %s, '/v2/user/training-consent', 'test',
                    %s::jsonb, now() - interval '1 second', %s,
                    %s, 'supabase-auth-sub-v1', %s, 'authenticated-training-consent-v1')""",
                (principal, policy["version"], policy["terms"], policy["privacy"],
                 signup, f"a-{uuid.uuid4()}", _hash(), _hash()))
        assert _one(cur, "SELECT count(*) FROM public.ml_speaker_principals "
                         "WHERE acquisition_principal_id = %s", (principal,)) == 0

    def test_an_existing_binding_is_kept_and_never_refuses_the_yes(self, cur):
        principal = _principal(cur)
        first_identity = _hash()
        _bind(cur, principal, identity=first_identity)
        speaker = _one(cur, "SELECT speaker_id FROM public.ml_speaker_principals "
                            "WHERE acquisition_principal_id = %s", (principal,))
        policy = _training_policy(cur)
        _receipt(cur, principal, policy["processing"])
        accepted = _accept(cur, principal, policy, identity=_hash())
        assert accepted["speaker_id"] == str(speaker)
        assert _one(cur, "SELECT count(*) FROM public.ml_speaker_principals "
                         "WHERE acquisition_principal_id = %s", (principal,)) == 1

    def test_binding_without_a_yes_writes_nothing(self, cur):
        principal = _principal(cur)
        bound = _row(cur, """
            SELECT * FROM public.bind_mlc2_training_speaker_v1(
                %s, %s, 'supabase-auth-sub-v1', %s, 'authenticated-training-consent-v1')""",
            (principal, _hash(), _hash()))
        assert bound is None or bound.get("id") is None
        assert _one(cur, "SELECT count(*) FROM public.ml_speaker_principals "
                         "WHERE acquisition_principal_id = %s", (principal,)) == 0

    def test_a_yes_given_before_this_migration_is_bound_once_later(self, cur):
        principal = _principal(cur)
        _yes(cur, principal, _training_policy(cur))
        identity = _hash()
        first = _row(cur, """
            SELECT * FROM public.bind_mlc2_training_speaker_v1(
                %s, %s, 'supabase-auth-sub-v1', %s, 'authenticated-training-consent-v1')""",
            (principal, identity, _hash()))
        second = _row(cur, """
            SELECT * FROM public.bind_mlc2_training_speaker_v1(
                %s, %s, 'supabase-auth-sub-v1', %s, 'authenticated-training-consent-v1')""",
            (principal, identity, _hash()))
        assert first["id"] and first["id"] == second["id"]
        assert _current(cur, principal) is True


# ── Readiness counts the training yes ─────────────────────────────────────

class TestTheDoorsReadTheSpeakersSplit:
    def _splits(self, cur, principals, policy="speaker-sha256-80-10-10-v1"):
        cur.execute("SELECT * FROM public.get_mlc2_speaker_splits_v1(%s::uuid[], %s)",
                    (principals, policy))
        return {str(row["acquisition_principal_id"]): row["split"] for row in cur.fetchall()}

    def test_a_bound_speaker_has_its_one_assignment(self, cur):
        bound, unbound = _principal(cur), _principal(cur)
        _bind(cur, bound)
        assigned = _one(cur, """
            SELECT assignment.split FROM public.ml_speaker_principals binding
              JOIN public.ml_speaker_split_assignments assignment
                ON assignment.speaker_id = binding.speaker_id
             WHERE binding.acquisition_principal_id = %s
               AND assignment.split_policy_version = 'speaker-sha256-80-10-10-v1'""",
                       (bound,))
        assert assigned in ("train", "validation", "test")
        assert self._splits(cur, [bound, unbound]) == {bound: assigned}

    def test_two_principals_of_one_person_read_one_split(self, cur):
        identity = _hash()
        first, second = _principal(cur), _principal(cur)
        _bind(cur, first, identity)
        _bind(cur, second, identity)
        splits = self._splits(cur, [first, second])
        assert set(splits) == {first, second} and len(set(splits.values())) == 1

    def test_another_policy_or_nobody_reads_nothing(self, cur):
        bound = _principal(cur)
        _bind(cur, bound)
        assert self._splits(cur, [bound], "another-policy-v9") == {}
        assert self._splits(cur, []) == {}
        cur.execute("SELECT * FROM public.get_mlc2_speaker_splits_v1(NULL, "
                    "'speaker-sha256-80-10-10-v1')")
        assert cur.fetchall() == []


class TestReadiness:
    def test_the_ring_readiness_counts_the_yes_and_the_unbound_yes(self, cur):
        before = _one(cur, "SELECT public.get_ring_confidence_readiness_v1()")
        bound, unbound = _principal(cur), _principal(cur)
        policy = _training_policy(cur)
        for principal in (bound, unbound):
            _yes(cur, principal, policy)
            _set_ring(cur, principal, 5)
        _bind(cur, bound)
        after = _one(cur, "SELECT public.get_ring_confidence_readiness_v1()")
        assert after["eligible_training_consent_grant_count"] == \
            before["eligible_training_consent_grant_count"] + 1
        assert after["eligible_training_yes_without_speaker_count"] == \
            before["eligible_training_yes_without_speaker_count"] + 1
        assert after["tables_present"]["training"] is True
        assert "eligible_bundled_consent_grant_count" in after

    def test_the_canary_readiness_counts_the_training_policy(self, cur):
        _training_policy(cur)
        health = _one(cur, "SELECT public.get_mlc2_confidence_canary_readiness_v1(NULL::uuid)")
        assert health["active_training_consent_policy_count"] >= 1
        assert health["valid_active_training_consent_policy_count"] >= 1
        for key in ("dataset_creation_enabled", "training_enabled", "promotion_enabled"):
            assert health[key] is False


# ── Grants ────────────────────────────────────────────────────────────────

class TestBrowserRolesCallNothingNew:
    @pytest.mark.parametrize("signature", NEW_FUNCTIONS)
    def test_only_the_service_role_may_execute(self, cur, signature):
        for role, allowed in (("anon", False), ("authenticated", False),
                              ("service_role", True)):
            assert _one(cur, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, f"public.{signature}")) is allowed, (role, signature)


# ── F-8: every download or release check appends a verification ───────────

BUCKET = "mlc2-rehearsal"
VERIFIER = "rehearsal-verifier-0430"


def _artifact(cur, *, sha="9" * 64, size=4096, status="eligible"):
    """A chain object as the frame finalizer writes it (inserted directly:
    the finalizer needs a whole frame), for a speaker bound by the yes."""
    owner = _principal(cur)
    _yes(cur, owner, _training_policy(cur))
    _bind(cur, owner)
    attempt, project = _attempt(cur, owner)
    snapshot = _row(cur, "SELECT * FROM public.create_mlc2_training_consent_"
                         "snapshot_v1(%s, %s, NULL, %s)", (owner, attempt, project))
    speaker = _one(cur, "SELECT speaker_id FROM public.ml_speaker_principals "
                        "WHERE acquisition_principal_id = %s", (owner,))
    key = f"confidence/0430-{uuid.uuid4()}.webm"
    artifact = _one(cur, """
        INSERT INTO public.ml_object_artifacts (
            acquisition_principal_id, speaker_id, consent_snapshot_id,
            object_store, bucket, object_key, sha256, byte_size, content_type,
            artifact_kind, retention_status, created_by)
        VALUES (%s, %s, %s, 'cloudflare_r2', %s, %s, %s, %s, 'audio/webm',
                'audio', %s, 'rehearsal-0430')
        RETURNING id""", (owner, speaker, snapshot["id"], BUCKET, key, sha, size,
                          status))
    return {"id": str(artifact), "key": key, "owner": owner, "project": project}


def _check(cur, key, sha="9" * 64, size=4096, *, bucket=BUCKET,
           method="scheduled_check_sha256"):
    return _one(cur, """
        SELECT public.record_mlc2_object_verification_v1(%s, %s, %s, %s, %s, %s)""",
        (bucket, key, sha, size, method, VERIFIER))


def _checks_of(cur, artifact_id):
    cur.execute("""SELECT verified, observed_sha256, observed_byte_size,
                          verification_method, verifier_version
                     FROM public.ml_object_verifications
                    WHERE object_artifact_id = %s ORDER BY verified_at, id""",
                (artifact_id,))
    return [dict(row) for row in cur.fetchall()]


def _unverified(cur):
    return _one(cur, "SELECT public.get_mlc2_foundation_health_v1()")[
        "unverified_object_count"]


def _due(cur, limit=100):
    cur.execute("SELECT * FROM public.list_mlc2_objects_due_verification_v1(%s)",
                (limit,))
    return [dict(row) for row in cur.fetchall()]


def _purged_source(cur, owner, project, key):
    """The recording behind a chain object, as a purge leaves it: the
    processing object row stays, its deleted_at set."""
    policy = _one(cur, "SELECT id FROM public.processing_policy_versions "
                       "WHERE version = %s", (_processing_version(cur),))
    receipt = _one(cur, """
        INSERT INTO public.processing_authorization_receipts (
            acquisition_principal_id, policy_id, idempotency_key,
            explicit_action, age_18_attested, country_of_residence, locale,
            client_version, accepted_at, evidence_sha256)
        VALUES (%s, %s, %s, 'agree_and_continue', true, 'PL', 'en',
                'rehearsal', now(), repeat('5', 64))
        RETURNING id""", (owner, policy, str(uuid.uuid4())))
    attempt = str(uuid.uuid4())
    snapshot = _one(cur, """
        INSERT INTO public.processing_authorization_snapshots (
            acquisition_principal_id, receipt_id, policy_id, purpose_id,
            operation_kind, source_recording_id, authority_evidence_sha256)
        VALUES (%s, %s, %s, 'recording_voice_processing', 'recording_upload',
                %s, repeat('6', 64))
        RETURNING id""", (owner, receipt, policy, attempt))
    _one(cur, """
        INSERT INTO public.processing_recording_attempts (
            id, acquisition_principal_id, project_id, recording_id,
            upload_idempotency_key, authorization_snapshot_id)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
         (attempt, owner, project, attempt, str(uuid.uuid4()), snapshot))
    _one(cur, """
        INSERT INTO public.processing_audio_objects (
            acquisition_principal_id, recording_attempt_id, storage_provider,
            bucket, object_key, byte_size, content_type, exact_bytes_sha256,
            verified_at, verification_method, deleted_at)
        VALUES (%s, %s, 'r2', %s, %s, 4096, 'audio/webm', repeat('9', 64),
                now(), 'read_after_write_sha256', now())
        RETURNING id""", (owner, attempt, BUCKET, key))


class TestAChainObjectCheckIsAppended:
    def test_a_matching_download_is_verified_and_appended(self, cur):
        artifact = _artifact(cur)
        before = _unverified(cur)
        result = _check(cur, artifact["key"], method="download_sha256")
        assert result["verified"] is True
        assert result["object_artifact_id"] == artifact["id"]
        assert _checks_of(cur, artifact["id"]) == [{
            "verified": True, "observed_sha256": "9" * 64,
            "observed_byte_size": 4096, "verification_method": "download_sha256",
            "verifier_version": VERIFIER}]
        assert _unverified(cur) == before - 1

    def test_changed_bytes_are_recorded_unverified_and_every_check_is_a_row(self, cur):
        artifact = _artifact(cur)
        assert _check(cur, artifact["key"], sha="a" * 64)["verified"] is False
        assert _check(cur, artifact["key"], size=4095)["verified"] is False
        assert _check(cur, artifact["key"])["verified"] is True
        # One transaction: the three rows share verified_at, so compare the
        # set of verdicts and observations, not an order.
        rows = _checks_of(cur, artifact["id"])
        assert sorted((c["verified"], c["observed_sha256"], c["observed_byte_size"])
                      for c in rows) == [
            (False, "9" * 64, 4095), (False, "a" * 64, 4096), (True, "9" * 64, 4096)]

    def test_a_key_that_is_no_chain_object_writes_nothing(self, cur):
        artifact = _artifact(cur)
        assert _check(cur, f"confidence/0430-{uuid.uuid4()}.webm") is None
        assert _check(cur, artifact["key"], bucket="another-bucket") is None
        assert _checks_of(cur, artifact["id"]) == []

    def test_a_malformed_observation_is_refused(self, cur):
        artifact = _artifact(cur)
        _raises(cur, "MLC2_OBJECT_VERIFICATION_METHOD_INVALID",
                "SELECT public.record_mlc2_object_verification_v1(%s, %s, %s, 1, "
                "'trust_me', 'v')", (BUCKET, artifact["key"], "9" * 64))
        _raises(cur, "MLC2_OBJECT_VERIFICATION_OBSERVATION_INVALID",
                "SELECT public.record_mlc2_object_verification_v1(%s, %s, %s, 1, "
                "'download_sha256', 'v')", (BUCKET, artifact["key"], "9" * 63))
        _raises(cur, "MLC2_OBJECT_VERIFICATION_OBSERVATION_INVALID",
                "SELECT public.record_mlc2_object_verification_v1(%s, %s, %s, 1, "
                "'download_sha256', 'v')", (BUCKET, artifact["key"], "A" * 64))
        _raises(cur, "MLC2_OBJECT_VERIFICATION_VERIFIER_INVALID",
                "SELECT public.record_mlc2_object_verification_v1(%s, %s, %s, 1, "
                "'download_sha256', ' ')", (BUCKET, artifact["key"], "9" * 64))
        assert _checks_of(cur, artifact["id"]) == []

    def test_a_check_is_never_rewritten(self, cur):
        artifact = _artifact(cur)
        _check(cur, artifact["key"], sha="a" * 64)
        _raises(cur, "append-only",
                "UPDATE public.ml_object_verifications SET verified = true "
                "WHERE object_artifact_id = %s", (artifact["id"],))
        _raises(cur, "append-only",
                "DELETE FROM public.ml_object_verifications "
                "WHERE object_artifact_id = %s", (artifact["id"],))


class TestTheWeeklyWorkList:
    def test_the_never_checked_come_first_then_the_longest_unchecked(self, cur):
        checked, fresh = _artifact(cur), _artifact(cur)
        _check(cur, checked["key"])
        order = [row["object_artifact_id"] for row in _due(cur)]
        assert str(fresh["id"]) in map(str, order)
        assert [str(i) for i in order].index(fresh["id"]) < \
            [str(i) for i in order].index(checked["id"])
        row = next(r for r in _due(cur) if str(r["object_artifact_id"]) == fresh["id"])
        assert set(row) == {"object_artifact_id", "bucket", "object_key",
                            "last_checked_at"}
        assert row["last_checked_at"] is None and row["object_key"] == fresh["key"]

    def test_the_list_is_capped(self, cur):
        _artifact(cur)
        _artifact(cur)
        assert len(_due(cur, 1)) == 1
        assert _due(cur, 0) == []
        assert len(_due(cur, 100000)) <= 100

    def test_an_invalidated_object_or_a_purged_recording_is_not_downloaded(self, cur):
        invalid = _artifact(cur, status="invalidated")
        purged = _artifact(cur)
        _purged_source(cur, purged["owner"], purged["project"], purged["key"])
        listed = {str(r["object_artifact_id"]) for r in _due(cur)}
        assert invalid["id"] not in listed and purged["id"] not in listed


def _release(cur, *, file_sha="1" * 64, manifest_sha="2" * 64):
    week = date(2100, 1, 4) + timedelta(weeks=uuid.uuid4().int % 5000)
    return str(_one(cur, """
        INSERT INTO public.pair_releases (
            release_version, surface, week_start, item_count, storage_bucket,
            storage_key, manifest, manifest_sha256, file_sha256, signature,
            signing_key_id)
        VALUES ('pair-release-v1', 'praise_line', %s, 1, 'pair-release-bucket',
                %s, '{}'::jsonb, %s, %s, 'signature', 'pair-release-key-1')
        RETURNING id""", (week, f"pair-releases/praise_line/{week}/pairs.jsonl",
                          manifest_sha, file_sha)))


def _release_check(cur, release, role, sha, signature_valid=None, *,
                   method="scheduled_check_sha256"):
    return _one(cur, """
        SELECT public.record_pair_release_verification_v1(%s, %s, %s, 10, %s, %s, %s)""",
        (release, role, sha, signature_valid, method, VERIFIER))


class TestAReleaseCheckIsAppended:
    def test_the_file_is_checked_against_its_hash(self, cur):
        release = _release(cur)
        assert _release_check(cur, release, "file", "1" * 64)["verified"] is True
        assert _release_check(cur, release, "file", "3" * 64)["verified"] is False

    def test_the_manifest_needs_its_hash_and_its_signature(self, cur):
        release = _release(cur)
        assert _release_check(cur, release, "manifest", "2" * 64, True)["verified"] is True
        assert _release_check(cur, release, "manifest", "2" * 64, False)["verified"] is False
        assert _release_check(cur, release, "manifest", "3" * 64, True)["verified"] is False
        assert _one(cur, "SELECT count(*) FROM public.pair_release_verifications "
                         "WHERE release_id = %s", (release,)) == 3

    def test_a_read_after_write_is_its_own_method(self, cur):
        release = _release(cur)
        _release_check(cur, release, "file", "1" * 64, method="read_after_write_sha256")
        assert _one(cur, "SELECT verification_method FROM "
                         "public.pair_release_verifications WHERE release_id = %s",
                    (release,)) == "read_after_write_sha256"

    def test_malformed_checks_are_refused(self, cur):
        release = _release(cur)
        _raises(cur, "PAIR_RELEASE_UNKNOWN",
                "SELECT public.record_pair_release_verification_v1(%s, 'file', %s, 1, "
                "NULL, 'scheduled_check_sha256', 'v')", (str(uuid.uuid4()), "1" * 64))
        _raises(cur, "PAIR_RELEASE_VERIFICATION_SIGNATURE_STATE_INVALID",
                "SELECT public.record_pair_release_verification_v1(%s, 'manifest', %s, "
                "1, NULL, 'scheduled_check_sha256', 'v')", (release, "2" * 64))
        _raises(cur, "PAIR_RELEASE_VERIFICATION_SIGNATURE_STATE_INVALID",
                "SELECT public.record_pair_release_verification_v1(%s, 'file', %s, 1, "
                "true, 'scheduled_check_sha256', 'v')", (release, "1" * 64))
        _raises(cur, "PAIR_RELEASE_VERIFICATION_ROLE_INVALID",
                "SELECT public.record_pair_release_verification_v1(%s, 'audio', %s, 1, "
                "NULL, 'scheduled_check_sha256', 'v')", (release, "1" * 64))
        _raises(cur, "PAIR_RELEASE_VERIFICATION_METHOD_INVALID",
                "SELECT public.record_pair_release_verification_v1(%s, 'file', %s, 1, "
                "NULL, 'trust_me', 'v')", (release, "1" * 64))

    def test_a_check_is_never_rewritten_and_holds_its_release(self, cur):
        release = _release(cur)
        _release_check(cur, release, "file", "3" * 64)
        _raises(cur, "append-only",
                "UPDATE public.pair_release_verifications SET verified = true "
                "WHERE release_id = %s", (release,))
        _raises(cur, "append-only",
                "DELETE FROM public.pair_release_verifications WHERE release_id = %s",
                (release,))
        _raises(cur, "violates foreign key constraint",
                "DELETE FROM public.pair_releases WHERE id = %s", (release,))

    def test_the_ledger_is_server_only(self, cur):
        assert _one(cur, "SELECT relrowsecurity FROM pg_class WHERE oid = "
                         "'public.pair_release_verifications'::regclass") is True
        for role in ("anon", "authenticated"):
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
                assert _one(cur, "SELECT has_table_privilege(%s, "
                                 "'public.pair_release_verifications', %s)",
                            (role, privilege)) is False, (role, privilege)
        assert _one(cur, "SELECT has_table_privilege('service_role', "
                         "'public.pair_release_verifications', 'SELECT')") is True
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert _one(cur, "SELECT has_table_privilege('service_role', "
                             "'public.pair_release_verifications', %s)",
                        (privilege,)) is False, privilege
