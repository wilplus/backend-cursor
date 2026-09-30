"""A pair remembers the yes, executed on a disposable database (0405).
Founder 2026-09-30, L1, L2, L5. Pins:
  * the refresh marks a pair releasable only under an active training-only
    yes (or a surface outside counsel's list), and back to not releasable
    after a withdrawal;
  * a withdrawal voids the release that carried the pair and returns the
    pair to waiting; the release keeps its manifest as history;
  * a pair leaves once: marking refuses a pair that is not releasable or
    already released, and an unknown release;
  * every new table has RLS on and reaches no browser role.
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

TABLES = ("pair_releases", "pair_release_owners")
ALL = ["praise_line", "clearer_version", "exercise_script"]


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


@pytest.fixture(scope="module")
def policy(db):
    """The active training-only policy: the consent suite's when it ran
    first, else one of our own (the database allows one at a time)."""
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
    processing = _one(db, "SELECT version FROM public.processing_policy_versions ORDER BY created_at LIMIT 1")
    copy = "Use my recordings to help improve WillpowerLab for everyone."
    sha = hashlib.sha256(copy.encode()).hexdigest()
    _one(db, """
        SELECT public.configure_mlc2_training_consent_policy_v1(
            'training-approval-pairs', %s, %s, 'training-only-pairs-v1', 'terms-t', 'privacy-t',
            'founder+counsel', now(), ARRAY['PL'], 'evidence/training.pdf',
            %s, %s, now() - interval '1 minute')""",
        (sha, copy, "e" * 64, processing))
    return {"version": "training-only-pairs-v1", "sha": sha}


def _principal(db):
    processing = _one(db, "SELECT version FROM public.processing_policy_versions ORDER BY created_at LIMIT 1")
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


def _pair(db, principal, surface="praise_line"):
    return str(_one(db, """
        INSERT INTO public.feedback_pairs (surface, draft_text, final_text, coach_id,
                                           owner_principal_id, request_id)
        VALUES (%s, 'the draft', 'the final', 'coach-1', %s, gen_random_uuid()) RETURNING id""",
        (surface, principal)))


def _pair_state(db, pair_id):
    return _row(db, "SELECT consent_state, releasable, release_id, exported_at, consent_grant_event_id "
                    "FROM public.feedback_pairs WHERE id = %s", (pair_id,))


def _refresh(db, required=ALL):
    return _one(db, "SELECT public.refresh_feedback_pair_consent_v1(%s::text[])", (required,))


def _release(db, surface="praise_line"):
    return str(_one(db, """
        INSERT INTO public.pair_releases (release_version, surface, week_start, item_count, storage_bucket,
            storage_key, manifest, manifest_sha256, file_sha256, signature, signing_key_id)
        VALUES ('pair-release-v1', %s, %s, 1, 'b', %s, '{}'::jsonb, repeat('a', 64), repeat('b', 64), 'sig', 'k1')
        RETURNING id""",
        (surface, f"2000-01-{uuid.uuid4().int % 28 + 1:02d}", f"pair-releases/{surface}/{uuid.uuid4()}/pairs.jsonl")))


def test_a_pair_is_releasable_only_under_an_active_yes(db, policy):
    principal = _principal(db)
    pair = _pair(db, principal)
    _refresh(db)
    state = _pair_state(db, pair)
    assert (state["consent_state"], state["releasable"]) == ("no", False)
    grant = _grant(db, principal, policy)
    _refresh(db)
    state = _pair_state(db, pair)
    assert (state["consent_state"], state["releasable"]) == ("yes", True)
    assert str(state["consent_grant_event_id"]) == grant
    _withdraw(db, principal, grant)
    _refresh(db)
    state = _pair_state(db, pair)
    assert (state["consent_state"], state["releasable"]) == ("no", False)


def test_a_surface_outside_counsels_list_needs_no_yes_and_no_principal_is_unknown(db, policy):
    principal = _principal(db)
    needed = _pair(db, principal, "exercise_script")
    free = _pair(db, principal, "clearer_version")
    _refresh(db, ["exercise_script"])
    assert _pair_state(db, free)["consent_state"] == "not_needed"
    assert _pair_state(db, free)["releasable"] is True
    assert _pair_state(db, needed)["consent_state"] == "no"
    orphan = str(_one(db, """
        INSERT INTO public.feedback_pairs (surface, draft_text, final_text, coach_id, exercise_id)
        VALUES ('praise_line', 'd', 'f', 'coach-1', 'ex-1') RETURNING id"""))
    _refresh(db)
    assert (_pair_state(db, orphan)["consent_state"], _pair_state(db, orphan)["releasable"]) == ("unknown", False)


def test_a_withdrawal_voids_the_release_and_returns_the_pair_to_waiting(db, policy):
    principal = _principal(db)
    grant = _grant(db, principal, policy)
    pair = _pair(db, principal)
    _refresh(db)
    release = _release(db)
    _exec(db, "INSERT INTO public.pair_release_owners (release_id, owner_principal_id) VALUES (%s, %s)",
          (release, principal))
    marked = _one(db, "SELECT public.mark_feedback_pairs_released_v1(%s, %s::uuid[])", (release, [pair]))
    assert marked == 1
    state = _pair_state(db, pair)
    assert str(state["release_id"]) == release and state["exported_at"] is not None
    # Once: a released pair cannot be marked again.
    with pytest.raises(psycopg2.Error) as refused:
        _one(db, "SELECT public.mark_feedback_pairs_released_v1(%s, %s::uuid[])", (release, [pair]))
    assert "PAIR_RELEASE_PAIRS_NOT_RELEASABLE" in str(refused.value)
    _withdraw(db, principal, grant)
    out = _refresh(db)
    assert out["voided_releases"] >= 1
    voided = _row(db, "SELECT voided_at, voided_reason, purged_at, manifest_sha256 FROM public.pair_releases WHERE id = %s", (release,))
    assert voided["voided_at"] is not None and voided["voided_reason"] == "consent_withdrawn"
    assert voided["purged_at"] is None and voided["manifest_sha256"] == "a" * 64
    state = _pair_state(db, pair)
    assert state["release_id"] is None and state["exported_at"] is None and state["releasable"] is False


def test_marking_refuses_an_unknown_release_and_an_unreleasable_pair(db, policy):
    principal = _principal(db)
    pair = _pair(db, principal)
    _refresh(db)
    release = _release(db)
    with pytest.raises(psycopg2.Error) as refused:
        _one(db, "SELECT public.mark_feedback_pairs_released_v1(%s, %s::uuid[])", (release, [pair]))
    assert "PAIR_RELEASE_PAIRS_NOT_RELEASABLE" in str(refused.value)
    with pytest.raises(psycopg2.Error) as unknown:
        _one(db, "SELECT public.mark_feedback_pairs_released_v1(%s, %s::uuid[])", (str(uuid.uuid4()), [pair]))
    assert "PAIR_RELEASE_UNKNOWN" in str(unknown.value)


def test_every_new_table_has_rls_and_no_browser_grant(db):
    for table in TABLES:
        got = _row(db, "SELECT relrowsecurity FROM pg_class WHERE oid = %s::regclass", (f"public.{table}",))
        assert got and got["relrowsecurity"] is True, table
        grants = _row(db, "SELECT count(*) AS n FROM information_schema.role_table_grants "
                          "WHERE table_schema = 'public' AND table_name = %s AND grantee IN ('anon', 'authenticated')",
                      (table,))
        assert grants["n"] == 0, table
    for fn in ("refresh_feedback_pair_consent_v1", "mark_feedback_pairs_released_v1"):
        anon = _one(db, "SELECT has_function_privilege('anon', %s, 'EXECUTE')",
                    (f"public.{fn}({'text[]' if fn.startswith('refresh') else 'uuid, uuid[]'})",))
        assert anon is False, fn
