"""
STORY    As a speaker who asks to delete my account, I want my processing to
         stop at once, seven days to change my mind, and everything erased
         after that, so that deletion is real and only briefly reversible.
OUTCOME
  O1  The request blocks me at once, cancels running jobs and permits,
      takes my coached pairs out of training, deletes nothing yet, and ends
      seven days later; asking twice is one request.
  O2  I can cancel inside the seven days and the block lifts; asking again
      later starts a new request.
  O3  After the seven days the run erases my data, marks the request done
      with proof, and never does it twice.
  O4  A dry run only reports what is due and writes nothing.
  O5  Once it is done, my sign-in is gone: no email, no phone, no password,
      no linked sign-in, no live session, and I cannot sign in; what the
      policy says survives (the proof of my agreement, my training choice) is
      still there, and nobody else's sign-in is touched. An account deleted
      before this was fixed loses its sign-in on the next run.
PROVES   O1 -> test_a_request_blocks_at_once_deletes_nothing_and_waits_seven_days
         O2 -> test_the_requester_cancels_inside_the_window_and_the_block_lifts
         O3 -> test_the_run_completes_a_due_deletion_on_verified_evidence
         O4 -> test_a_dry_run_reads_what_is_due_and_writes_nothing
         O5 -> test_a_completed_deletion_leaves_no_way_to_sign_in_and_keeps_what_survives
               test_an_account_deleted_before_the_fix_loses_its_sign_in_on_the_next_run
WHY      Founder 2026-10-05, N48.4 Q14 A, Q17 A, Q19 A (migration 0422);
         Privacy 3.8 sections 7 and 9 and N95 (migration 0497).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta

import psycopg2
import psycopg2.extras
import pytest

from services.deletion_completion import run_due_deletions
from services.processing_authorization import (
    ProcessingAuthorizationService,
)
from tests import test_account_deletion_starts_postgres as base
from tests import test_project_purge_postgres as project_purge
from tests import test_take_purge_postgres as takes

DSN = base.DSN
_Database = base._Database
_one = base._one
db = base.db
fake_storage = takes.fake_storage

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

SURFACES = ["praise_line", "clearer_version", "exercise_script"]


def _row(db, sql, args=()):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        got = cur.fetchone()
        return dict(got) if got else None


def _service(db) -> ProcessingAuthorizationService:
    return ProcessingAuthorizationService(_Database(db), mode="off")


def _active_policy(db) -> str:
    """The active processing policy; one of our own only when none is."""
    live = _one(db, """
        SELECT id::text FROM public.processing_policy_versions
         WHERE status = 'active' AND activated_at <= now()
           AND (retired_at IS NULL OR retired_at > now())""")
    if live:
        return live
    artifacts = [_one(db, """
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256, metadata)
        VALUES (%s, %s, 'test', now(), 'k', repeat('c', 64), '{}'::jsonb)
        RETURNING id""", (kind, f"window-{uuid.uuid4()}"))
        for kind in ("product_legal_approval", "power_score_classification",
                     "article_50_assessment")]
    return str(_one(db, """
        INSERT INTO public.processing_policy_versions (
            version, status, product_legal_artifact_id,
            power_score_classification_artifact_id, article50_artifact_id,
            terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256,
            allowed_countries, activated_at, created_by)
        VALUES (%s, 'active', %s, %s, %s,
            't1', 'terms', repeat('1', 64), 'p1', 'privacy', repeat('2', 64),
            'a1', 'notice', repeat('3', 64), 'agree', repeat('4', 64),
            ARRAY['pl'], now() - interval '1 minute', 'deletion-window-test')
        RETURNING id""", (f"window-{uuid.uuid4()}", *artifacts)))


def _speaker(db, *, accepted: bool = False, jobs: bool = False) -> dict:
    """One person, one project, one accepted Take with stored audio and an
    issued permit; with ``jobs``, a pending processing job too. No deletion
    request. (A purge cannot yet delete phase1_processing_jobs as
    service_role: 0310 revoked it. Today the job events, external_review
    under N14.3, stop such a purge before it deletes anything.)"""
    user_id = str(uuid.uuid4())
    principal = str(_one(db, """
        INSERT INTO public.owner_principals (id, user_id)
        VALUES (gen_random_uuid(), %s) RETURNING id""", (user_id,)))
    project = str(_one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'Q3 pitch') RETURNING id""", (principal,)))
    take = str(_one(db, """
        INSERT INTO public.v2_sessions (
            id, user_id, owner_principal_id, project_id, arc_id, take_index)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, 1) RETURNING id""",
        (user_id, principal, project, project)))
    policy = _active_policy(db) if accepted else str(_one(db, """
        INSERT INTO public.processing_policy_versions (
            id, version, status, terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256, allowed_countries,
            created_by)
        VALUES (gen_random_uuid(), 'window-' || gen_random_uuid(), 'draft',
                'terms-v1', 'terms', repeat('1', 64), 'privacy-v1', 'privacy',
                repeat('2', 64), 'ai-v1', 'ai', repeat('3', 64), 'agreement',
                repeat('4', 64), ARRAY['PL'], 'rehearsal')
        RETURNING id"""))
    receipt = _one(db, """
        INSERT INTO public.processing_authorization_receipts (
            id, acquisition_principal_id, policy_id, idempotency_key,
            explicit_action, age_18_attested, country_of_residence, locale,
            client_version, accepted_at, evidence_sha256)
        VALUES (gen_random_uuid(), %s, %s, %s, 'agree_and_continue', true,
                'PL', 'en', 'rehearsal', now(), repeat('5', 64))
        RETURNING id""", (principal, policy, str(uuid.uuid4())))
    attempt = str(uuid.uuid4())
    snapshot = _one(db, """
        INSERT INTO public.processing_authorization_snapshots (
            id, acquisition_principal_id, receipt_id, policy_id, purpose_id,
            operation_kind, source_recording_id, authority_evidence_sha256)
        VALUES (gen_random_uuid(), %s, %s, %s, 'recording_voice_processing',
                'recording_upload', %s, repeat('6', 64))
        RETURNING id""", (principal, receipt, policy, attempt))
    _one(db, """
        INSERT INTO public.processing_recording_attempts (
            id, acquisition_principal_id, project_id, recording_id,
            upload_idempotency_key, authorization_snapshot_id)
        VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
        (attempt, principal, project, attempt, str(uuid.uuid4()), snapshot))
    key = f"{principal}/{take}.wav"
    _one(db, """
        INSERT INTO public.processing_audio_objects (
            acquisition_principal_id, recording_attempt_id, storage_provider,
            bucket, object_key, byte_size, content_type, exact_bytes_sha256,
            verified_at, verification_method)
        VALUES (%s, %s, 'r2', 'take-audio', %s, 21, 'audio/wav',
                repeat('7', 64), now(), 'read_after_write_sha256')
        RETURNING id""", (principal, attempt, key))
    job = _one(db, """
        INSERT INTO public.phase1_processing_jobs (
            acquisition_principal_id, recording_attempt_id,
            authorization_snapshot_id, job_kind)
        VALUES (%s, %s, %s, 'recording_transcription_ranking_feedback')
        RETURNING id""", (principal, attempt, snapshot)) if jobs else None
    permit = _one(db, """
        INSERT INTO public.processing_provider_permits (
            acquisition_principal_id, authorization_snapshot_id, provider,
            operation_kind, pseudonymous_subject_ref, minimum_data_manifest,
            expires_at, idempotency_key)
        VALUES (%s, %s, 'openai', 'transcription', 'p', '{}'::jsonb,
                now() + interval '15 minutes', %s)
        RETURNING id""", (principal, snapshot, str(uuid.uuid4())))
    return {"principal": principal, "user_id": user_id, "project": project,
            "take": take, "audio_key": ("take-audio", key), "job": str(job),
            "permit": str(permit)}


def _purge_ready(db) -> None:
    """The take-purge suite's two stand-ins (every retention rule active,
    the production columns its fixtures lack). training_labels is the
    bundled-era suite's stand-in, which runs earlier in the lane; created
    here only when this module runs alone."""
    with db.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS public.training_labels (
                           id UUID PRIMARY KEY DEFAULT gen_random_uuid())""")
    project_purge._production_columns(db)   # takes' columns + paragraphs.project_id
    takes._seed_every_retention_rule(db)


def _due_account_request(db, principal: str) -> str:
    """A request whose seven days are over: written as it would stand a
    week on (the guard keeps the window itself from ever being edited)."""
    return str(_one(db, """
        INSERT INTO public.account_deletion_requests (
            acquisition_principal_id, requested_at, completes_after,
            idempotency_key, reason_code)
        VALUES (%s, now() - interval '8 days', now() - interval '1 day', %s,
                'ACCOUNT_DELETION')
        RETURNING id""", (principal, f"due-{uuid.uuid4()}")))


def _status_code(db, principal: str) -> str:
    return _one(db, "SELECT public.get_phase1_processing_authorization_v1(%s)->>'code'",
                (principal,))


def _mine(report: dict, request_id: str) -> dict:
    found = [o for o in report["outcomes"] if o["request_id"] == request_id]
    assert len(found) == 1, report
    return found[0]


def _run(db, **kw) -> dict:
    return run_due_deletions(_Database(db), execute=kw.pop("execute", True),
                             limit=kw.pop("limit", 20), **kw)


# ── The window ────────────────────────────────────────────────────────────


def test_a_request_blocks_at_once_deletes_nothing_and_waits_seven_days(db):
    subject = _speaker(db, accepted=True, jobs=True)
    principal = subject["principal"]
    pair = _one(db, """
        INSERT INTO public.feedback_pairs (surface, draft_text, final_text,
            coach_id, owner_principal_id, request_id, releasable)
        VALUES ('praise_line', 'the draft', 'the final', 'coach-1', %s,
                gen_random_uuid(), true) RETURNING id""", (principal,))
    assert _status_code(db, principal) == "PROCESSING_AUTHORIZED"

    view = _service(db).request_account_deletion(
        principal, idempotency_key=f"account-deletion:{uuid.uuid4()}",
        reason_code="ACCOUNT_DELETION")

    assert (view["kind"], view["state"], view["cancellable"]) == (
        "account", "pending", True)
    assert view["purge_id"] == view["request_id"]
    assert _one(db, """
        SELECT completes_after - requested_at FROM public.account_deletion_requests
         WHERE id = %s""", (view["request_id"],)) == timedelta(days=7)
    status = _one(db, "SELECT public.get_phase1_processing_authorization_v1(%s)",
                  (principal,))
    assert (status["authorized"], status["code"], status["reacceptance_required"]) == (
        False, "PROCESSING_SERVICE_BLOCKED", False)
    assert _row(db, "SELECT status, last_error_code FROM public.phase1_processing_jobs "
                    "WHERE id = %s", (subject["job"],)) == {
        "status": "cancelled", "last_error_code": "PROCESSING_AUTHORITY_ENDED"}
    assert _one(db, "SELECT status FROM public.processing_provider_permits WHERE id = %s",
                (subject["permit"],)) == "cancelled"
    assert _one(db, "SELECT releasable FROM public.feedback_pairs WHERE id = %s",
                (pair,)) is False
    assert _one(db, "SELECT public.phase1_learning_stopped_v1(%s)", (principal,)) is True
    # Nothing is deleted while the window runs: no purge exists at all.
    assert _one(db, "SELECT count(*) FROM public.data_purge_requests "
                    "WHERE acquisition_principal_id = %s", (principal,)) == 0
    assert _one(db, "SELECT display_name FROM public.projects WHERE id = %s",
                (subject["project"],)) == "Q3 pitch"
    # A double tap with a new key is the same request.
    again = _service(db).request_account_deletion(
        principal, idempotency_key=f"account-deletion:{uuid.uuid4()}")
    assert again["request_id"] == view["request_id"]


def test_the_requester_cancels_inside_the_window_and_the_block_lifts(db):
    principal = _speaker(db, accepted=True)["principal"]
    service = _service(db)
    view = service.request_account_deletion(principal, idempotency_key="k-cancel-1")
    assert _status_code(db, principal) == "PROCESSING_SERVICE_BLOCKED"

    cancelled = service.cancel_account_deletion(principal, view["purge_id"])

    assert (cancelled["state"], cancelled["cancellable"]) == ("cancelled", False)
    assert cancelled["cancelled_at"] is not None
    assert _status_code(db, principal) == "PROCESSING_AUTHORIZED"
    assert _one(db, "SELECT public.phase1_learning_stopped_v1(%s)", (principal,)) is False
    assert service.pending_deletion(principal) is None
    # Twice is the same answer; asking again later is a new request.
    assert service.cancel_account_deletion(principal, view["purge_id"])["state"] == "cancelled"
    fresh = service.request_account_deletion(principal, idempotency_key="k-cancel-2")
    assert fresh["request_id"] != view["request_id"] and fresh["state"] == "pending"


# ── The completion run ────────────────────────────────────────────────────


def test_the_run_completes_a_due_deletion_on_verified_evidence(db, fake_storage):
    _purge_ready(db)
    subject = _speaker(db)
    request = _due_account_request(db, subject["principal"])

    outcome = _mine(_run(db), request)

    assert outcome["result"] == "completed", outcome
    done = _row(db, "SELECT * FROM public.account_deletion_requests WHERE id = %s",
                (request,))
    assert done["state"] == "done" and done["completed_at"] is not None
    assert done["completion_evidence_sha256"] == _one(db, """
        SELECT evidence_sha256 FROM public.data_purge_events
         WHERE purge_request_id = %s AND event_kind = 'completed'""",
        (done["purge_request_id"],))
    assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                (done["purge_request_id"],)) == "done"
    assert subject["audio_key"] in fake_storage
    assert _one(db, "SELECT display_name FROM public.projects WHERE id = %s",
                (subject["project"],)) == ""
    # Still blocked, and the app reads why.
    assert _status_code(db, subject["principal"]) == "PROCESSING_SERVICE_BLOCKED"
    view = _service(db).pending_deletion(subject["principal"])
    assert (view["request_id"], view["state"], view["cancellable"]) == (
        request, "done", False)
    # Safe to run again: nothing of this request is touched twice.
    again = _run(db)
    assert all(o["request_id"] != request for o in again["outcomes"])
    assert _one(db, """
        SELECT count(*) FROM public.data_purge_events
         WHERE purge_request_id = %s AND event_kind = 'completed'""",
        (done["purge_request_id"],)) == 1


def test_a_dry_run_reads_what_is_due_and_writes_nothing(db):
    principal = _speaker(db)["principal"]
    request = _due_account_request(db, principal)
    lease = _row(db, "SELECT holder, lease_until FROM public.deletion_completion_lease")

    outcome = _mine(_run(db, execute=False), request)

    assert outcome["result"] == "would_start"
    assert _one(db, "SELECT state FROM public.account_deletion_requests WHERE id = %s",
                (request,)) == "pending"
    assert _one(db, "SELECT count(*) FROM public.data_purge_requests "
                    "WHERE acquisition_principal_id = %s", (principal,)) == 0
    assert _row(db, "SELECT holder, lease_until FROM public.deletion_completion_lease") == lease


# ── The sign-in goes with the account ─────────────────────────────────────

# What Privacy 3.8 section 9 says survives: the proof that recordings were
# processed with agreement, the training choice, and the person they name.
_SURVIVING = {
    "owner_principals": "SELECT count(*) FROM public.owner_principals WHERE id = %s",
    "authorization_receipts": "SELECT count(*) FROM public.processing_authorization_receipts "
                              "WHERE acquisition_principal_id = %s",
    "authorization_snapshots": "SELECT count(*) FROM public.processing_authorization_snapshots "
                               "WHERE acquisition_principal_id = %s",
    "recording_attempts": "SELECT count(*) FROM public.processing_recording_attempts "
                          "WHERE acquisition_principal_id = %s",
    "audio_metadata": "SELECT count(*) FROM public.processing_audio_objects "
                      "WHERE acquisition_principal_id = %s",
    "provider_permits": "SELECT count(*) FROM public.processing_provider_permits "
                        "WHERE acquisition_principal_id = %s",
    "training_choice": "SELECT count(*) FROM public.ml_consent_events "
                       "WHERE acquisition_principal_id = %s",
}
# Every row Supabase Auth keeps for one person.
_AUTH_TABLES = {
    "users": "id = %s", "identities": "user_id = %s", "sessions": "user_id = %s",
    "refresh_tokens": "user_id = %s::text", "one_time_tokens": "user_id = %s",
    "flow_state": "user_id = %s", "mfa_factors": "user_id = %s",
}


def _signs_in(db, user_id: str, email: str, phone: str) -> None:
    """An account as Supabase Auth keeps it: signed up with WhatsApp, then
    an email with a password and Google added; signed in on a phone, with a
    code still out, a Google sign-in half done and an SMS second factor."""
    with db.cursor() as cur:
        cur.execute("""
            INSERT INTO auth.users (
                id, aud, role, email, phone, encrypted_password,
                email_confirmed_at, phone_confirmed_at, confirmation_token,
                recovery_token, email_change_token_new, email_change,
                raw_app_meta_data, raw_user_meta_data, created_at, updated_at)
            VALUES (%s, 'authenticated', 'authenticated', %s, %s,
                    '$2a$10$abcdefghijklmnopqrstuv', now(), now(), '',
                    'recovery-token', '', '',
                    '{"provider": "phone", "providers": ["phone", "email", "google"]}',
                    %s::jsonb, now(), now())""",
            (user_id, email, phone, json.dumps({
                "full_name": "Ada Speaker", "email": email,
                "avatar_url": "https://example.com/ada.png"})))
        cur.execute("""
            INSERT INTO auth.identities (provider_id, user_id, identity_data, provider)
            VALUES (%s, %s, %s::jsonb, 'phone'), (%s, %s, %s::jsonb, 'google')""",
            (user_id, user_id, json.dumps({"sub": user_id, "phone": phone}),
             f"google-{user_id}", user_id, json.dumps({
                 "sub": f"google-{user_id}", "email": email,
                 "full_name": "Ada Speaker"})))
        session = str(uuid.uuid4())
        cur.execute("""
            INSERT INTO auth.sessions (id, user_id, user_agent, ip)
            VALUES (%s, %s, 'Mozilla/5.0 (iPhone)', '203.0.113.7')""",
            (session, user_id))
        cur.execute("""
            INSERT INTO auth.refresh_tokens (token, user_id, revoked, session_id)
            VALUES (%s, %s, false, %s), (%s, %s, false, NULL)""",
            (f"rt-{uuid.uuid4()}", user_id, session, f"rt-{uuid.uuid4()}", user_id))
        cur.execute("""
            INSERT INTO auth.one_time_tokens (id, user_id, token_type, token_hash, relates_to)
            VALUES (gen_random_uuid(), %s, 'recovery_token', 'hash', %s)""",
            (user_id, email))
        cur.execute("""
            INSERT INTO auth.flow_state (id, user_id, provider_type,
                provider_access_token, authentication_method)
            VALUES (gen_random_uuid(), %s, 'google', 'google-access', 'oauth')""",
            (user_id,))
        cur.execute("""
            INSERT INTO auth.mfa_factors (id, user_id, friendly_name, factor_type,
                status, created_at, updated_at, phone)
            VALUES (gen_random_uuid(), %s, 'Ada''s phone', 'phone', 'verified',
                    now(), now(), %s)""",
            (user_id, phone))


def _counts(db, queries: dict, key: str) -> dict:
    return {name: _one(db, sql, (key,)) for name, sql in queries.items()}


def _auth_rows(db, user_id: str) -> dict:
    """Every Supabase Auth row of one person, as JSON text."""
    return {table: _one(db, f"""
        SELECT coalesce(jsonb_agg(to_jsonb(r) ORDER BY to_jsonb(r)::text), '[]')::text
          FROM auth.{table} r WHERE {where}""", (user_id,))
        for table, where in _AUTH_TABLES.items()}


def _a_deleted_account_keeps_no_sign_in(db, user_id: str, email: str,
                                        phone: str) -> None:
    """The auth record keeps its id and nothing to sign in with or be known
    by; neither the email nor the phone is anywhere in it."""
    auth = _row(db, "SELECT * FROM auth.users WHERE id = %s", (user_id,))
    assert auth is not None
    assert (auth["email"], auth["phone"], auth["encrypted_password"]) == (None, None, None)
    assert (auth["email_change"], auth["phone_change"], auth["recovery_token"]) == ("", "", "")
    assert auth["raw_user_meta_data"] == {}
    assert auth["raw_app_meta_data"] == {"provider": "phone",
                                         "providers": ["phone", "email", "google"]}
    assert auth["banned_until"].year == 9999 and auth["deleted_at"] is not None
    # No Google or phone sign-in finds the user; every session has ended and
    # every refresh token is revoked.
    assert _one(db, """
        SELECT count(*) FROM auth.identities
         WHERE user_id = %s AND (identity_data <> '{}' OR provider_id <> id::text)""",
        (user_id,)) == 0
    assert _one(db, """
        SELECT count(*) FROM auth.sessions
         WHERE user_id = %s AND (not_after > now() OR user_agent IS NOT NULL
                                 OR ip IS NOT NULL)""", (user_id,)) == 0
    assert _one(db, """
        SELECT count(*) FROM auth.refresh_tokens
         WHERE user_id = %s::text AND revoked IS NOT TRUE""", (user_id,)) == 0
    assert _one(db, """
        SELECT count(*) FROM auth.mfa_factors
         WHERE user_id = %s AND (status <> 'unverified' OR friendly_name <> '')""",
        (user_id,)) == 0
    rows = _auth_rows(db, user_id)
    assert not any(email in text or phone in text for text in rows.values()), rows
    assert "google-access" not in rows["flow_state"]


def test_a_completed_deletion_leaves_no_way_to_sign_in_and_keeps_what_survives(
        db, fake_storage):
    _purge_ready(db)
    subject = _speaker(db)
    user_id, principal = subject["user_id"], subject["principal"]
    _yes(db, principal)
    marker = uuid.uuid4().hex[:10]
    email, phone = f"ada-{marker}@example.com", f"48{int(marker, 16) % 10**9:09d}"
    _signs_in(db, user_id, email, phone)
    bystander = str(uuid.uuid4())
    _signs_in(db, bystander, f"other-{marker}@example.com", f"49{int(marker, 16) % 10**9:09d}")
    theirs = _auth_rows(db, bystander)
    kept = _counts(db, _SURVIVING, principal)
    assert all(kept.values()), kept
    request = _due_account_request(db, principal)

    outcome = _mine(_run(db), request)

    assert outcome["result"] == "completed", outcome
    assert _one(db, "SELECT state FROM public.account_deletion_requests WHERE id = %s",
                (request,)) == "done"
    _a_deleted_account_keeps_no_sign_in(db, user_id, email, phone)
    # What the policy says survives is all still there, naming the same person.
    assert _counts(db, _SURVIVING, principal) == kept
    assert _one(db, "SELECT user_id::text FROM public.owner_principals WHERE id = %s",
                (principal,)) == user_id
    # Nobody else's sign-in is touched.
    assert _auth_rows(db, bystander) == theirs


def test_an_account_deleted_before_the_fix_loses_its_sign_in_on_the_next_run(
        db, fake_storage):
    _purge_ready(db)
    subject = _speaker(db)
    request = _due_account_request(db, subject["principal"])
    assert _mine(_run(db), request)["result"] == "completed"
    # As a deletion finished before 0497 left it: done, the sign-in intact.
    marker = uuid.uuid4().hex[:10]
    email, phone = f"bo-{marker}@example.com", f"47{int(marker, 16) % 10**9:09d}"
    _signs_in(db, subject["user_id"], email, phone)
    before = _auth_rows(db, subject["user_id"])

    assert _mine(_run(db, execute=False), request)["result"] == "would_erase_sign_in"
    assert _auth_rows(db, subject["user_id"]) == before

    assert _mine(_run(db), request)["result"] == "sign_in_erased"
    _a_deleted_account_keeps_no_sign_in(db, subject["user_id"], email, phone)
    assert all(o["request_id"] != request for o in _run(db)["outcomes"])


# ── A project keeps the same window ───────────────────────────────────────


# ── Termination stops learning ────────────────────────────────────────────


def _training_policy(db) -> dict:
    _active_policy(db)  # a processing policy exists, as the consent suite leaves one
    live = _row(db, """
        SELECT policy.version, approval.approved_copy_sha256 AS sha
          FROM public.ml_consent_policies policy
          JOIN public.ml_product_legal_approvals approval
            ON approval.id = policy.product_legal_approval_id
         WHERE policy.grant_scope = 'training_only'
           AND policy.active_from <= now()
           AND (policy.retired_at IS NULL OR policy.retired_at > now())
         ORDER BY policy.active_from DESC LIMIT 1""")
    if live:
        return live
    processing = _one(db, "SELECT version FROM public.processing_policy_versions "
                          "ORDER BY created_at LIMIT 1")
    copy = "Use my recordings to help improve WillpowerLab for everyone."
    sha = hashlib.sha256(copy.encode()).hexdigest()
    _one(db, """
        SELECT public.configure_mlc2_training_consent_policy_v1(
            'training-approval-window', %s, %s, 'training-only-window-v1',
            'terms-t', 'privacy-t', 'founder+counsel', now(), ARRAY['PL'],
            'evidence/training.pdf', %s, %s, now() - interval '1 minute')""",
        (sha, copy, "e" * 64, processing))
    return {"version": "training-only-window-v1", "sha": sha}


def _yes(db, principal: str | None = None) -> tuple[str, str]:
    """A person (new, or the one given) with a receipt and an active
    training yes."""
    policy = _training_policy(db)
    processing = _one(db, "SELECT version FROM public.processing_policy_versions "
                          "ORDER BY created_at LIMIT 1")
    principal = principal or str(_one(
        db, "INSERT INTO public.owner_principals (id, user_id) "
            "VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id"))
    _one(db, """
        INSERT INTO public.processing_authorization_receipts (
            acquisition_principal_id, policy_id, idempotency_key, explicit_action,
            age_18_attested, country_of_residence, locale, client_version,
            accepted_at, evidence_sha256)
        SELECT %s, id, %s, 'agree_and_continue', true, 'PL', 'en-GB', 'test',
               now(), repeat('a', 64)
          FROM public.processing_policy_versions WHERE version = %s RETURNING id""",
        (principal, f"r-{uuid.uuid4()}", processing))
    action = json.dumps({"accepted": True, "control": "training_toggle",
                         "copy_sha256": policy["sha"]})
    grant = _row(db, """
        SELECT * FROM public.record_mlc2_training_consent_grant_v2(
            %s, %s, 'PL', 'terms-t', 'privacy-t', 'settings/training', 'test',
            %s::jsonb, now() - interval '1 second', %s)""",
        (principal, policy["version"], action, f"g-{uuid.uuid4()}"))
    return principal, str(grant.get("id") or list(grant.values())[0])


# ── Before 0422, and what the app reads ───────────────────────────────────
