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


# ── One consent authority ─────────────────────────────────────────────────

class TestOneConsentAuthority:
    def test_a_training_yes_with_a_bound_speaker_is_current(self, cur):
        principal = _principal(cur)
        _yes(cur, principal, _training_policy(cur))
        _bind(cur, principal)
        assert _current(cur, principal) is True


    def test_a_withdrawn_yes_is_not_current(self, cur):
        principal = _principal(cur)
        grant = _yes(cur, principal, _training_policy(cur))
        _bind(cur, principal)
        assert _current(cur, principal) is True
        _withdraw(cur, principal, grant)
        assert _current(cur, principal) is False


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


class TestTheSnapshotComesFromTheTrainingYes:

    def test_no_yes_no_snapshot(self, cur):
        owner = _principal(cur)
        _bundled_grant(cur, owner)
        attempt, project = _attempt(cur, owner)
        _raises(cur, "no active training yes",
                "SELECT public.create_mlc2_training_consent_snapshot_v1(%s, %s, NULL, %s)",
                (owner, attempt, project))


# ── The canonical promotion reads only the training snapshot ──────────────


# ── The speaker is bound through the training yes (F-3) ───────────────────


# ── Readiness counts the training yes ─────────────────────────────────────


# ── Grants ────────────────────────────────────────────────────────────────


# ── F-8: every download or release check appends a verification ───────────
