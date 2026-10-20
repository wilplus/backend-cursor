"""
STORY    As a speaker who withdrew my training "yes", I want a half-finished
         export that held my pair voided and cleaned up, so that my data
         never leaves in a broken release.
OUTCOME
  O1  When an export's last step is refused because a pair is no longer
      allowed, the release is voided as "export_failed" and queued for
      file cleanup.
  O2  Pairs of speakers who still say yes wait and leave in a later week's
      release.
  O3  The weekly consent refresh keeps the "export_failed" reason.
PROVES   O1, O2, O3 ->
             test_a_mark_that_refuses_leaves_a_release_only_this_void_reaches
WHY      Door 2, ML-9 (migration 0455).
"""
from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, timedelta

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

ALL = ["praise_line", "clearer_version", "exercise_script"]
VOID = "SELECT public.void_failed_pair_release_v1(%s)"
MARK = "SELECT public.mark_feedback_pairs_released_v1(%s, %s::uuid[])"


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
        got = cur.fetchone()
        return dict(got) if got else None


def _exec(db, sql, args=()):
    with db.cursor() as cur:
        cur.execute(sql, args)


def _processing_version(db):
    """The lane's processing policy version, or one of our own when this
    suite runs alone: configure_mlc2_training_consent_policy_v1 refuses a
    version processing_policy_versions does not hold, and the receipts
    below name it. An active policy needs its three legal artifacts
    (processing_policy_approved_check)."""
    found = _one(db, "SELECT version FROM public.processing_policy_versions ORDER BY created_at LIMIT 1")
    if found:
        return found
    artifacts = [_one(db, """
        INSERT INTO public.processing_legal_artifacts (
            artifact_kind, version, approving_authority, approved_at, object_key, sha256, metadata)
        VALUES (%s, %s, 'test', now(), 'k', encode(extensions.digest(%s, 'sha256'), 'hex'), '{}'::jsonb)
        RETURNING id""", (kind, f"failed-export-{uuid.uuid4()}", str(uuid.uuid4())))
        for kind in ("product_legal_approval", "power_score_classification", "article_50_assessment")]
    return _one(db, """
        INSERT INTO public.processing_policy_versions (
            version, status, product_legal_artifact_id,
            power_score_classification_artifact_id, article50_artifact_id,
            terms_version, terms_copy, terms_copy_sha256,
            privacy_version, privacy_copy, privacy_copy_sha256,
            ai_notice_version, ai_notice_copy, ai_notice_copy_sha256,
            agreement_copy, agreement_copy_sha256,
            allowed_countries, activated_at, created_by)
        VALUES ('processing-failed-export-v1', 'active', %s, %s, %s,
            't1', 'terms', encode(extensions.digest('terms','sha256'),'hex'),
            'p1', 'privacy', encode(extensions.digest('privacy','sha256'),'hex'),
            'a1', 'notice', encode(extensions.digest('notice','sha256'),'hex'),
            'agree', encode(extensions.digest('agree','sha256'),'hex'),
            ARRAY['pl'], now() - interval '1 minute', 'failed-export-test')
        RETURNING version""", tuple(artifacts))


@pytest.fixture(scope="module")
def policy(db):
    """The active training-only policy: another suite's when it ran first,
    else one of our own (the database allows one at a time)."""
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
    processing = _processing_version(db)
    copy = "Use my recordings to help improve WillpowerLab for everyone."
    sha = hashlib.sha256(copy.encode()).hexdigest()
    _one(db, """
        SELECT public.configure_mlc2_training_consent_policy_v1(
            'training-approval-failed-export', %s, %s, 'training-only-failed-export-v1',
            'terms-t', 'privacy-t', 'founder+counsel', now(), ARRAY['PL'],
            'evidence/training.pdf', %s, %s, now() - interval '1 minute')""",
        (sha, copy, "e" * 64, processing))
    return {"version": "training-only-failed-export-v1", "sha": sha}


def _principal(db):
    processing = _processing_version(db)
    principal = _one(db, "INSERT INTO public.owner_principals (id, user_id) VALUES (gen_random_uuid(), gen_random_uuid()) RETURNING id")
    _one(db, """
        INSERT INTO public.processing_authorization_receipts (
            acquisition_principal_id, policy_id, idempotency_key, explicit_action, age_18_attested,
            country_of_residence, locale, client_version, accepted_at, evidence_sha256)
        SELECT %s, id, %s, 'agree_and_continue', true, 'PL', 'en-GB', 'test', now(), %s
          FROM public.processing_policy_versions WHERE version = %s RETURNING id""",
        (principal, f"r-{uuid.uuid4()}", "a" * 64, processing))
    return str(principal)


def _grant(db, principal, policy):
    action = json.dumps({"accepted": True, "control": "training_toggle", "copy_sha256": policy["sha"]})
    row = _row(db, """
        SELECT * FROM public.record_mlc2_training_consent_grant_v2(
            %s, %s, 'PL', 'terms-t', 'privacy-t', 'settings/training', 'test', %s::jsonb,
            now() - interval '1 second', %s)""",
        (principal, policy["version"], action, f"g-{uuid.uuid4()}"))
    return str(row["id"]) if row and row.get("id") else str(list(row.values())[0])


def _withdraw(db, principal, grant_id):
    _row(db, """
        SELECT * FROM public.record_mlc2_consent_withdrawal_v2(
            %s, %s, 'pooled_model_improvement', 'settings/training', 'test',
            '{"control": "training_toggle", "accepted": false}'::jsonb, now(), %s)""",
        (principal, grant_id, f"w-{uuid.uuid4()}"))


def _pair(db, principal):
    return str(_one(db, """
        INSERT INTO public.feedback_pairs (surface, draft_text, final_text, coach_id,
                                           owner_principal_id, request_id)
        VALUES ('praise_line', 'the draft', 'the final', 'coach-1', %s, gen_random_uuid())
        RETURNING id""", (principal,)))


def _pair_state(db, pair_id):
    return _row(db, "SELECT releasable, release_id, exported_at "
                    "FROM public.feedback_pairs WHERE id = %s", (pair_id,))


def _refresh(db):
    return _one(db, "SELECT public.refresh_feedback_pair_consent_v1(%s::text[])", (ALL,))


def _week():
    """A week no other release in this database holds (pair_releases is
    UNIQUE (surface, week_start)). The sibling suites draw from 1900-2064,
    2100-2195, 3000-8475 and 3100-3899; this range is 2200-2884."""
    return str(date(2200, 1, 1) + timedelta(days=uuid.uuid4().int % 250_000))


def _release(db, week=None):
    return str(_one(db, """
        INSERT INTO public.pair_releases (release_version, surface, week_start, item_count,
            storage_bucket, storage_key, manifest, manifest_sha256, file_sha256, signature,
            signing_key_id)
        VALUES ('pair-release-v1', 'praise_line', %s, 2, 'b', %s, '{}'::jsonb, repeat('a', 64),
                repeat('b', 64), 'sig', 'k1')
        RETURNING id""",
        (week or _week(), f"pair-releases/praise_line/{uuid.uuid4()}/pairs.jsonl")))


def _release_state(db, release):
    return _row(db, "SELECT voided_at, voided_reason, purged_at FROM public.pair_releases "
                    "WHERE id = %s", (release,))


def _in_the_sweep(db, release):
    """services/db.py list_voided_unpurged_pair_releases: voided, not purged."""
    return bool(_one(db, "SELECT count(*) FROM public.pair_releases WHERE id = %s "
                         "AND voided_at IS NOT NULL AND purged_at IS NULL", (release,)))


def _pointing_at(db, release):
    return _one(db, "SELECT count(*) FROM public.feedback_pairs WHERE release_id = %s",
                (release,))


def test_a_mark_that_refuses_leaves_a_release_only_this_void_reaches(db, policy):
    stays, leaves = _principal(db), _principal(db)
    _grant(db, stays, policy)
    leaving_grant = _grant(db, leaves, policy)
    kept, gone = _pair(db, stays), _pair(db, leaves)
    _refresh(db)
    assert _pair_state(db, kept)["releasable"] and _pair_state(db, gone)["releasable"]
    # The export wrote its row and owners; then one owner withdrew.
    release = _release(db)
    for owner in (stays, leaves):
        _exec(db, "INSERT INTO public.pair_release_owners (release_id, owner_principal_id) "
                  "VALUES (%s, %s)", (release, owner))
    _withdraw(db, leaves, leaving_grant)
    _refresh(db)
    assert _pair_state(db, gone)["releasable"] is False
    with pytest.raises(psycopg2.Error) as refused:
        _one(db, MARK, (release, [kept, gone]))
    assert "PAIR_RELEASE_PAIRS_NOT_RELEASABLE" in str(refused.value)
    # The gap: no pair points at the release, so the refresh never voids it.
    assert _pointing_at(db, release) == 0
    _refresh(db)
    assert _release_state(db, release)["voided_at"] is None
    assert not _in_the_sweep(db, release)

    assert _one(db, VOID, (release,)) is True
    state = _release_state(db, release)
    assert state["voided_at"] is not None and state["voided_reason"] == "export_failed"
    assert state["purged_at"] is None and _in_the_sweep(db, release)
    # The pair still releasable waits and leaves under a later week's release.
    assert _pair_state(db, kept) == {"releasable": True, "release_id": None, "exported_at": None}
    later = _release(db)
    assert _one(db, MARK, (later, [kept])) == 1
    # The refresh voids only live releases: the reason stands.
    _refresh(db)
    assert _release_state(db, release)["voided_reason"] == "export_failed"
    assert _release_state(db, later)["voided_at"] is None
