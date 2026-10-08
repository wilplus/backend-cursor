"""A deletion completes by itself after seven days (0422; founder 2026-10-05,
decisions log N48.4 Q14 A, Q17 A, Q19 A; PLF-T2, PLF-T3, PLF-T4, L5).

Run on the released rehearsal lane through the thin SQL client of
tests/test_account_deletion_starts_postgres.py, as service_role, so the
Python production runs (the authority service, the completion run, the
orchestrators) meets the real functions. The two named stand-ins of
tests/test_take_purge_postgres.py apply: every retention rule seeded active,
and object storage faked. Pins:

  * the window: completes_after is the request + 7 days; the person is
    blocked at once, in-flight jobs and permits are cancelled, their pairs
    leave the releasable pool, and nothing is deleted;
  * the cancel: only the requester, only inside the window, never once the
    purge started; it lifts the block;
  * the run: a due request is started, purged and marked done on verified
    evidence; a purge that meets rows no rule decides (N14.3's
    ideal_text_part_revision) deletes nothing, waits for a person and is not
    retried; a dry run writes nothing; one run at a time;
  * a project deletion keeps the same window and completes the same way;
  * a termination stops learning: pairs, the weekly refresh, training copies;
  * requests made before 0422 are carried over, never cancellable;
  * the status read the app gets.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import timedelta
from pathlib import Path

import psycopg2
import psycopg2.extras
import pytest

from services.account_deletion import AccountDeletionService
from services.deletion_completion import run_due_deletions, review_queue
from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)
from services.project_deletion import ProjectDeletionError, ProjectDeletionService
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

MIGRATION = (Path(__file__).resolve().parents[1] / "migrations"
             / "a_deletion_completes_after_seven_days.sql").read_text()
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


def _due_project_request(db, principal: str, project: str) -> str:
    return str(_one(db, """
        INSERT INTO public.project_deletion_requests (
            acquisition_principal_id, project_id, requested_at, due_at,
            idempotency_key)
        VALUES (%s, %s, now() - interval '8 days', now() - interval '1 day', %s)
        RETURNING id""", (principal, project, f"due-{uuid.uuid4()}")))


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


def test_a_cancel_is_refused_for_another_person_after_the_window_and_once_started(db):
    service = _service(db)
    owner = _speaker(db)["principal"]
    stranger = _speaker(db)["principal"]
    view = service.request_account_deletion(owner, idempotency_key="k-refuse")
    with pytest.raises(ProcessingAuthorizationError) as other:
        service.cancel_account_deletion(stranger, view["purge_id"])
    assert (other.value.code, other.value.status) == ("ACCOUNT_DELETION_NOT_FOUND", 404)
    # The window cannot be started early...
    with pytest.raises(psycopg2.Error, match="ACCOUNT_DELETION_WINDOW_OPEN"):
        _one(db, "SELECT (public.start_due_account_deletion_v1(%s)).state",
             (view["purge_id"],))

    late = _speaker(db)["principal"]
    due = _due_account_request(db, late)
    with pytest.raises(ProcessingAuthorizationError) as closed:
        service.cancel_account_deletion(late, due)
    assert (closed.value.code, closed.value.status) == (
        "ACCOUNT_DELETION_WINDOW_CLOSED", 409)
    # ...and once it has started, the deletion is past cancelling.
    assert _one(db, "SELECT (public.start_due_account_deletion_v1(%s)).state",
                (due,)) == "started"
    with pytest.raises(ProcessingAuthorizationError) as started:
        service.cancel_account_deletion(late, due)
    assert (started.value.code, started.value.status) == (
        "ACCOUNT_DELETION_ALREADY_STARTED", 409)
    # Starting is idempotent: one purge request, one permanent block.
    _one(db, "SELECT (public.start_due_account_deletion_v1(%s)).state", (due,))
    assert _one(db, "SELECT count(*) FROM public.data_purge_requests "
                    "WHERE acquisition_principal_id = %s", (late,)) == 1
    assert _one(db, "SELECT count(*) FROM public.processing_service_blocks "
                    "WHERE acquisition_principal_id = %s", (late,)) == 1


def test_a_request_never_changes_its_window_or_goes_back(db):
    principal = _speaker(db)["principal"]
    view = _service(db).request_account_deletion(principal, idempotency_key="k-guard")
    for statement in (
        "UPDATE public.account_deletion_requests SET completes_after = now() WHERE id = %s",
        "UPDATE public.account_deletion_requests SET state = 'done' WHERE id = %s",
    ):
        with pytest.raises(psycopg2.Error, match="ACCOUNT_DELETION_"):
            _one(db, statement + " RETURNING id", (view["purge_id"],))
    with pytest.raises(psycopg2.Error, match="ACCOUNT_DELETION_REQUEST_IMMUTABLE"):
        _one(db, "DELETE FROM public.account_deletion_requests WHERE id = %s RETURNING id",
             (view["purge_id"],))


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


def test_a_purge_meeting_rows_no_rule_decides_waits_for_a_person(db, fake_storage):
    """N14.3: ideal_text_part_revision is external_review. The purge stops
    before the first deletion and the request waits for a person."""
    _purge_ready(db)
    subject = _speaker(db)
    revision = _one(db, """
        INSERT INTO public.ideal_text_part_revision (arc_id, user_id, part_id,
            action, text)
        VALUES (%s, %s, gen_random_uuid(), 'user_edit', 'my own words')
        RETURNING id""", (subject["project"], subject["user_id"]))
    request = _due_account_request(db, subject["principal"])

    outcome = _mine(_run(db), request)

    assert outcome["result"] == "left_for_a_person", outcome
    assert "dependency:ideal_part_revision" in {r["target_ref"] for r in outcome["reasons"]}
    row = _row(db, "SELECT state, purge_request_id FROM public.account_deletion_requests "
                   "WHERE id = %s", (request,))
    assert row["state"] == "started"
    assert _one(db, "SELECT state FROM public.data_purge_requests WHERE id = %s",
                (row["purge_request_id"],)) == "review_required"
    # Nothing past the refusal: the words, the project and the audio stay.
    assert _one(db, "SELECT text FROM public.ideal_text_part_revision WHERE id = %s",
                (revision,)) == "my own words"
    assert _one(db, "SELECT display_name FROM public.projects WHERE id = %s",
                (subject["project"],)) == "Q3 pitch"
    assert subject["audio_key"] not in fake_storage
    # Not retried; listed for a person on every run and in the admin read.
    again = _run(db)
    assert all(o["request_id"] != request for o in again["outcomes"])
    assert request in {item["request_id"] for item in again["left_for_a_person"]}
    queue = review_queue(_Database(db))
    assert request in {item["request_id"] for item in queue["left_for_a_person"]}


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


def test_one_run_at_a_time(db):
    def claim(holder):
        return _one(db, "SELECT public.claim_deletion_completion_lease_v1(%s, 60)",
                    (holder,))

    def release(holder):
        return _one(db, "SELECT public.release_deletion_completion_lease_v1(%s)",
                    (holder,))

    try:
        assert claim("run-a") is True
        assert claim("run-b") is False
        assert claim("run-a") is True          # the holder renews
        report = _run(db)                      # a third run is turned away
        assert report.get("skipped") == "LEASE_HELD" and report["outcomes"] == []
        assert release("run-b") is False
        assert release("run-a") is True
        assert claim("run-b") is True
    finally:
        release("run-a")
        release("run-b")


# ── A project keeps the same window ───────────────────────────────────────


def test_a_project_deletion_keeps_its_window_and_completes_by_itself(db, fake_storage):
    _purge_ready(db)
    subject = _speaker(db)
    principal = subject["principal"]
    kept = str(_one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'Board update') RETURNING id""", (principal,)))
    projects = ProjectDeletionService(_Database(db))

    opened = projects.request(principal, kept, f"k-{uuid.uuid4()}")
    from services.project_deletion import public_view
    view = public_view(opened)
    assert (view["kind"], view["state"], view["cancellable"]) == ("project", "pending", True)
    assert view["completes_after"] == view["due_at"]
    with pytest.raises(psycopg2.Error, match="PROJECT_DELETION_WINDOW_OPEN"):
        _one(db, "SELECT (public.start_due_project_deletion_v1(%s)).state", (opened["id"],))
    assert projects.cancel(principal, kept)["state"] == "cancelled"

    due = _due_project_request(db, principal, subject["project"])
    with pytest.raises(ProjectDeletionError) as closed:
        projects.cancel(principal, subject["project"])
    assert (closed.value.code, closed.value.status) == (
        "PROJECT_DELETION_WINDOW_CLOSED", 409)

    outcome = _mine(_run(db), due)

    assert outcome["result"] == "completed", outcome
    assert _row(db, "SELECT state, confirmed_by FROM public.project_deletion_requests "
                    "WHERE id = %s", (due,)) == {"state": "done", "confirmed_by": None}
    assert _one(db, "SELECT display_name FROM public.projects WHERE id = %s",
                (subject["project"],)) == ""
    assert subject["audio_key"] in fake_storage
    assert _one(db, "SELECT display_name FROM public.projects WHERE id = %s",
                (kept,)) == "Board update"
    # A project deletion never blocks the person.
    assert _one(db, "SELECT public.phase1_learning_stopped_v1(%s)", (principal,)) is False


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


def _yes(db) -> tuple[str, str]:
    """A person with a receipt and an active training yes."""
    policy = _training_policy(db)
    processing = _one(db, "SELECT version FROM public.processing_policy_versions "
                          "ORDER BY created_at LIMIT 1")
    principal = str(_one(db, "INSERT INTO public.owner_principals (id, user_id) "
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


def _released_pair(db, principal: str) -> tuple[str, str]:
    pair = str(_one(db, """
        INSERT INTO public.feedback_pairs (surface, draft_text, final_text,
            coach_id, owner_principal_id, request_id)
        VALUES ('praise_line', 'the draft', 'the final', 'coach-1', %s,
                gen_random_uuid()) RETURNING id""", (principal,)))
    _one(db, "SELECT public.refresh_feedback_pair_consent_v1(%s::text[])", (SURFACES,))
    assert _one(db, "SELECT releasable FROM public.feedback_pairs WHERE id = %s",
                (pair,)) is True
    week = f"{3100 + uuid.uuid4().int % 800}-01-0{1 + uuid.uuid4().int % 9}"
    release = str(_one(db, """
        INSERT INTO public.pair_releases (release_version, surface, week_start,
            item_count, storage_bucket, storage_key, manifest, manifest_sha256,
            file_sha256, signature, signing_key_id)
        VALUES ('pair-release-v1', 'praise_line', %s::date, 1, 'b', %s, '{}'::jsonb,
                repeat('a', 64), repeat('b', 64), 'sig', 'k1')
        RETURNING id""", (week, f"pair-releases/praise_line/{uuid.uuid4()}/p.jsonl")))
    assert _one(db, "SELECT public.mark_feedback_pairs_released_v1(%s, %s::uuid[])",
                (release, [pair])) == 1
    return pair, release


def _copy(db, principal: str, grant: str):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("""
            SELECT id FROM public.record_training_corpus_item_v1(
                %s, %s, %s, %s, %s, repeat('1', 64), 'transcript_span', NULL,
                '{"text": "hello there"}'::jsonb, NULL, NULL, NULL, NULL)""",
            (principal, grant, str(uuid.uuid4()), str(uuid.uuid4()),
             f"snippet:{uuid.uuid4()}:transcript"))
        return cur.fetchone()


def _corpus_rule(db) -> None:
    artifact = _one(db, """
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at,
            object_key, sha256)
        VALUES ('retention_schedule', 'window-' || gen_random_uuid(),
                'rehearsal', now(), 'rehearsal/retention.pdf', repeat('a', 64))
        RETURNING id""")
    _one(db, """
        INSERT INTO public.data_retention_rules (
            rule_code, evidence_category, retention_until_rule,
            legal_artifact_id, active)
        VALUES ('training_corpus', 'training_corpus', 'until withdrawn', %s, true)
        ON CONFLICT (rule_code) DO UPDATE SET active = true RETURNING id""",
        (artifact,))


def test_a_termination_stops_learning_at_once_and_at_every_refresh(db):
    _corpus_rule(db)
    principal, grant = _yes(db)
    pair, release = _released_pair(db, principal)
    assert _copy(db, principal, grant) is not None      # copies flow before

    _one(db, """
        SELECT public.request_phase1_purge_v1(%s, 'service_termination', %s,
                                              'SERVICE_TERMINATION')""",
         (principal, f"term-{uuid.uuid4()}"))

    assert _one(db, "SELECT releasable FROM public.feedback_pairs WHERE id = %s",
                (pair,)) is False
    _one(db, "SELECT public.refresh_feedback_pair_consent_v1(%s::text[])", (SURFACES,))
    state = _row(db, "SELECT consent_state, releasable, release_id FROM "
                     "public.feedback_pairs WHERE id = %s", (pair,))
    # The ledger is read as it is (L3): the yes stands, the pair goes nowhere.
    assert state == {"consent_state": "yes", "releasable": False, "release_id": None}
    # 0456: voided at the request itself, before this refresh (which, until
    # 0456, voided it as 'owner_service_ended').
    assert _row(db, "SELECT voided_reason, purged_at FROM public.pair_releases "
                    "WHERE id = %s", (release,)) == {
        "voided_reason": "owner_erasure_requested", "purged_at": None}
    with pytest.raises(psycopg2.Error, match="TRAINING_CORPUS_SERVICE_ENDING"):
        _copy(db, principal, grant)


def test_an_account_deletion_stops_learning_until_it_is_cancelled(db):
    principal, _grant = _yes(db)
    pair = str(_one(db, """
        INSERT INTO public.feedback_pairs (surface, draft_text, final_text,
            coach_id, owner_principal_id, request_id)
        VALUES ('clearer_version', 'the draft', 'the final', 'coach-1', %s,
                gen_random_uuid()) RETURNING id""", (principal,)))
    view = _service(db).request_account_deletion(principal, idempotency_key="k-learn")
    _one(db, "SELECT public.refresh_feedback_pair_consent_v1(%s::text[])", (SURFACES,))
    assert _one(db, "SELECT releasable FROM public.feedback_pairs WHERE id = %s",
                (pair,)) is False

    _service(db).cancel_account_deletion(principal, view["purge_id"])
    _one(db, "SELECT public.refresh_feedback_pair_consent_v1(%s::text[])", (SURFACES,))

    assert _one(db, "SELECT releasable FROM public.feedback_pairs WHERE id = %s",
                (pair,)) is True


# ── Before 0422, and what the app reads ───────────────────────────────────


def test_a_request_made_before_0422_is_carried_over_and_never_cancellable(db):
    principal = _speaker(db)["principal"]
    legacy = _one(db, """
        SELECT (public.request_phase1_purge_v1(%s, 'account_deletion', %s,
                'ACCOUNT_DELETION'))->>'purge_request_id'""",
        (principal, f"account-deletion:{uuid.uuid4()}"))
    carry = MIGRATION[MIGRATION.index("INSERT INTO public.account_deletion_requests (\n    id,"):
                      MIGRATION.rindex("COMMIT;")]
    with db.cursor() as cur:
        cur.execute("BEGIN")
        try:
            cur.execute(carry)
            cur.execute("""
                SELECT state, purge_request_id::text, completes_after - requested_at
                  FROM public.account_deletion_requests WHERE id = %s""", (legacy,))
            state, purge, window = cur.fetchone()
            cur.execute("SAVEPOINT refused")
            with pytest.raises(psycopg2.Error, match="ACCOUNT_DELETION_ALREADY_STARTED"):
                cur.execute("SELECT public.cancel_phase1_account_deletion_v1(%s, %s)",
                            (principal, legacy))
            cur.execute("ROLLBACK TO SAVEPOINT refused")
            cur.execute("SELECT count(*) FROM public.account_deletion_requests "
                        "WHERE id = %s", (legacy,))
            assert cur.fetchone()[0] == 1
        finally:
            cur.execute("ROLLBACK")
    assert (state, purge, window) == ("started", legacy, timedelta(days=7))


def test_the_status_read_carries_the_pending_deletion(db):
    principal = _speaker(db)["principal"]
    service = _service(db)
    assert service.pending_deletion(principal) is None
    view = service.request_account_deletion(principal, idempotency_key="k-status")

    pending = service.pending_deletion(principal)

    assert set(pending) == {
        "purge_id", "request_id", "id", "kind", "trigger_kind", "project_id",
        "state", "requested_at", "completes_after", "cancellable",
        "cancelled_at", "completed_at"}
    assert (pending["purge_id"], pending["kind"], pending["state"],
            pending["cancellable"]) == (view["purge_id"], "account", "pending", True)
    assert service.deletion_status(principal, view["purge_id"])["state"] == "pending"
    assert service.deletion_status(_speaker(db)["principal"], view["purge_id"]) is None
    assert AccountDeletionService(_Database(db)).find(principal, "not-a-uuid") is None


def test_browser_roles_reach_none_of_it(db):
    for table in ("account_deletion_requests", "deletion_completion_lease"):
        assert _one(db, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass",
                    (f"public.{table}",)) is True
        for role in ("anon", "authenticated"):
            assert _one(db, "SELECT has_table_privilege(%s, %s, 'SELECT')",
                        (role, f"public.{table}")) is False
        assert _one(db, "SELECT has_table_privilege('service_role', %s, 'UPDATE')",
                    (f"public.{table}",)) is False
    for fn in ("request_phase1_account_deletion_v1(uuid, text, text)",
               "cancel_phase1_account_deletion_v1(uuid, uuid)",
               "start_due_account_deletion_v1(uuid)",
               "complete_phase1_account_deletion_v1(uuid)",
               "start_due_project_deletion_v1(uuid)",
               "phase1_learning_stopped_v1(uuid)",
               "stop_phase1_learning_v1(uuid)",
               "claim_deletion_completion_lease_v1(text, integer)",
               "release_deletion_completion_lease_v1(text)"):
        for role in ("anon", "authenticated"):
            assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, f"public.{fn}")) is False, (role, fn)
        assert _one(db, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')",
                    (f"public.{fn}",)) is True, fn
