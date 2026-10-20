"""
STORY    As a speaker who asks to delete my account or a project, I want any
         training release holding my pairs voided at once and its files
         deleted when the erasure completes, so that my data stops leaving
         the moment I ask.
OUTCOME
  O1  An account deletion request voids, before anything is erased, every
      release holding my pairs, even one found only by its owner list.
  O2  Other speakers' pairs from those releases may leave again; mine
      never do; releases without my pairs are untouched.
  O3  When a project deletion completes, the run voids the release before
      deleting my pairs and deletes the release's files from storage.
PROVES   O1, O2 -> test_an_account_deletion_request_voids_a_release_holding_one_of_its_pairs
         O3 -> test_the_completion_run_voids_before_its_purge_and_sweeps_the_copies
WHY      Door 2; erasure promise N48.4 Q14 A, Q17 A (migration 0456).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from services.deletion_completion import run_due_deletions
from services.pair_release_eligibility import decide
from tests import test_a_deletion_completes_after_seven_days_postgres as window
from tests import test_account_deletion_starts_postgres as base

DSN = base.DSN
_Database = base._Database
_one = base._one
_row = window._row
db = base.db
fake_storage = window.fake_storage

pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

BUCKET = "pair-release-bucket"


class _Ledger(base._Database):
    """The SQL client, plus the reads services/db.py gives the release sweep
    and the export's release-time decision, run as service_role like every
    other call here."""

    def list_voided_unpurged_pair_releases(self) -> list[dict]:
        return self.client.fetch("""
            SELECT id::text, surface, storage_bucket, storage_key, voided_at
              FROM public.pair_releases
             WHERE voided_at IS NOT NULL AND purged_at IS NULL LIMIT 500""", ())

    def mark_pair_release_purged(self, release_id: str) -> None:
        self.client.fetch("""
            UPDATE public.pair_releases SET purged_at = now()
             WHERE id = %s RETURNING id""", (release_id,))

    def list_active_training_grants(self, principal_ids: list[str]) -> list[dict]:
        return self.client.fetch("""
            SELECT id::text AS id,
                   acquisition_principal_id::text AS acquisition_principal_id,
                   consent_policy_version
              FROM public.training_consent_active_grants
             WHERE acquisition_principal_id::text = ANY(%s)""", (list(principal_ids),))

    def phase1_learning_stopped(self, principal_id: str) -> bool:
        return self.client.fetch(
            "SELECT public.phase1_learning_stopped_v1(%s::uuid) AS stopped",
            (principal_id,))[0]["stopped"]

    def list_take_projects(self, take_ids: list[str]) -> dict[str, str]:
        rows = self.client.fetch("""
            SELECT id::text AS id, COALESCE(project_id::text, '') AS project_id
              FROM public.v2_sessions WHERE id::text = ANY(%s)""", (list(take_ids),))
        return {row["id"]: row["project_id"] for row in rows}


class _Bucket:
    """The release bucket's delete, faked: what the sweep asked to remove."""

    def __init__(self) -> None:
        self.deleted: list[tuple[str, str]] = []

    def delete(self, bucket: str, key: str) -> None:
        self.deleted.append((bucket, key))


def _grants(db) -> None:
    """Supabase grants service_role every privilege on public tables by
    default; this schema has none. Only on tables no migration revokes from
    service_role: the three pair tables (the purge deletes a Take's pairs,
    the sweep reads and marks releases), and the Takes and projects the
    export's decision reads (the take-purge suite grants the same two)."""
    with db.cursor() as cur:
        cur.execute("""
            GRANT SELECT, INSERT, UPDATE, DELETE ON
                public.feedback_pairs, public.pair_releases,
                public.pair_release_owners, public.v2_sessions, public.projects
            TO service_role""")


def _week() -> str:
    """A week no sibling module draws (0405's from 3000, 0422's 3100-3899):
    pair_releases is UNIQUE (surface, week_start)."""
    return str(date(8500, 1, 1) + timedelta(days=uuid.uuid4().int % 500_000))


def _pair(db, principal: str, take: str | None = None) -> str:
    return str(_one(db, """
        INSERT INTO public.feedback_pairs (surface, draft_text, final_text,
            coach_id, owner_principal_id, take_session_id, request_id)
        VALUES ('praise_line', 'the draft', 'the final', 'coach-1', %s, %s,
                gen_random_uuid()) RETURNING id""", (principal, take)))


def _stamped_releasable(db, pair: str) -> None:
    """As services/pair_consent.stamp writes a new pair under a yes: it reads
    the person, never the project."""
    _one(db, "UPDATE public.feedback_pairs SET releasable = true WHERE id = %s "
             "RETURNING id", (pair,))


def _refresh(db) -> dict:
    return _one(db, "SELECT public.refresh_feedback_pair_consent_v1(%s::text[])",
                (window.SURFACES,))


def _release(db, pairs: list[str], owners: list[str], *, marked: bool = True) -> str:
    """One release as export_surface writes it: the row, its owner list, then
    its pairs marked under it. ``marked=False``: the export failed between."""
    release = str(_one(db, """
        INSERT INTO public.pair_releases (release_version, surface, week_start,
            item_count, storage_bucket, storage_key, manifest, manifest_sha256,
            file_sha256, signature, signing_key_id)
        VALUES ('pair-release-v1', 'praise_line', %s::date, %s, %s, %s,
                '{}'::jsonb, repeat('a', 64), repeat('b', 64), 'sig', 'k1')
        RETURNING id""",
        (_week(), len(pairs), BUCKET,
         f"pair-releases/praise_line/{uuid.uuid4()}/pairs.jsonl")))
    for owner in sorted(set(owners)):
        _one(db, "INSERT INTO public.pair_release_owners (release_id, "
                 "owner_principal_id) VALUES (%s, %s) RETURNING release_id",
             (release, owner))
    if marked:
        assert _one(db, "SELECT public.mark_feedback_pairs_released_v1(%s, %s::uuid[])",
                    (release, pairs)) == len(pairs)
    return release


def _pair_state(db, pair: str) -> dict:
    return _row(db, """
        SELECT releasable, release_id::text AS release_id, exported_at
          FROM public.feedback_pairs WHERE id = %s""", (pair,))


def _release_state(db, release: str) -> dict:
    return _row(db, """
        SELECT voided_reason, voided_at IS NOT NULL AS voided,
               purged_at IS NOT NULL AS purged
          FROM public.pair_releases WHERE id = %s""", (release,))


def _purges(db, principal: str) -> int:
    return _one(db, "SELECT count(*) FROM public.data_purge_requests "
                    "WHERE acquisition_principal_id = %s", (principal,))


def _would_leave(db, pairs: list[str]) -> set[str]:
    """The pairs the export's release-time decision would let leave now
    (services/pair_release_eligibility.py), read as the export reads them."""
    rows = [_row(db, """
        SELECT id::text AS id, surface, draft_text, final_text, final_kind,
               owner_principal_id::text AS owner_principal_id, take_session_id
          FROM public.feedback_pairs WHERE id = %s""", (pair,)) for pair in pairs]
    decision = decide(_Ledger(db), rows, surface="praise_line",
                      required_surfaces=window.SURFACES,
                      now=datetime.now(timezone.utc))
    return {str(pair["id"]) for pair in decision["eligible"]}


WAITING = {"releasable": True, "release_id": None, "exported_at": None}
OUT = {"releasable": False, "release_id": None, "exported_at": None}


# ── At the request ────────────────────────────────────────────────────────


def test_an_account_deletion_request_voids_a_release_holding_one_of_its_pairs(db):
    _grants(db)
    person, _ = window._yes(db)
    other, _ = window._yes(db)
    third, _ = window._yes(db)
    mine, unshipped = _pair(db, person), _pair(db, person)
    theirs, apart = _pair(db, other), _pair(db, third)
    _refresh(db)
    holding = _release(db, [mine, theirs], [person, other])
    # An export that failed between writing its owner list and marking its
    # pairs: no pair points at the release, its owner list names the person.
    orphan = _release(db, [unshipped], [person], marked=False)
    untouched = _release(db, [apart], [third])

    window._service(db).request_account_deletion(
        person, idempotency_key=f"account-deletion:{uuid.uuid4()}",
        reason_code="ACCOUNT_DELETION")

    assert _purges(db, person) == 0                      # before any purge
    for release in (holding, orphan):
        assert _release_state(db, release) == {
            "voided_reason": "owner_erasure_requested", "voided": True, "purged": False}
    assert _release_state(db, untouched)["voided"] is False
    assert _pair_state(db, mine) == OUT
    assert _pair_state(db, theirs) == WAITING
    assert _pair_state(db, apart)["release_id"] == untouched
    assert _would_leave(db, [mine, theirs]) == {theirs}


# ── The void holds ────────────────────────────────────────────────────────


# ── The purge and the sweep ───────────────────────────────────────────────


def test_the_completion_run_voids_before_its_purge_and_sweeps_the_copies(db, fake_storage):
    window._purge_ready(db)
    _grants(db)
    subject = window._speaker(db)
    principal = subject["principal"]
    pair = _pair(db, principal, subject["take"])
    _stamped_releasable(db, pair)
    release = _release(db, [pair], [principal])
    key = _one(db, "SELECT storage_key FROM public.pair_releases WHERE id = %s",
               (release,))
    # Asked for before 0456 and long due: no void ran, and the run takes it
    # before anything another module left due.
    request = str(_one(db, """
        INSERT INTO public.project_deletion_requests (
            acquisition_principal_id, project_id, requested_at, due_at,
            idempotency_key)
        VALUES (%s, %s, now() - interval '400 days', now() - interval '393 days', %s)
        RETURNING id""", (principal, subject["project"], f"due-{uuid.uuid4()}")))
    bucket = _Bucket()

    report = run_due_deletions(_Ledger(db), execute=True, limit=20,
                               release_storage=bucket)

    assert window._mine(report, request)["result"] == "completed", report
    assert _one(db, "SELECT count(*) FROM public.feedback_pairs WHERE id = %s",
                (pair,)) == 0
    assert _release_state(db, release) == {
        "voided_reason": "project_erasure_requested", "voided": True, "purged": True}
    assert {(BUCKET, key), (BUCKET, key.replace("pairs.jsonl", "manifest.json"))} <= set(
        bucket.deleted)
    assert report["release_sweep"]["purged"] >= 1
    assert report["release_sweep"]["failed"] == []


# ── Before 0456, and the doors ────────────────────────────────────────────
