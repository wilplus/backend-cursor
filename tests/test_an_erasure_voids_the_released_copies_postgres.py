"""An erasure voids the released copies, executed (0454; door 2, the erasure
promise of N48.4 Q14 A and Q17 A; PLF-T2, PLF-T3, L3).

Run on the released rehearsal lane through the thin SQL client of
tests/test_account_deletion_starts_postgres.py, as service_role, so the
production Python (the two deletion services, the completion run, the
release sweep, the export's release-time decision) meets the real
functions. Stand-ins, each named: Supabase's default table grants to
service_role on the pair tables, the Takes and the projects (production has
them; this schema has no Supabase), the take-purge suite's retention rules
and production columns, a pair stamped releasable at write as
services/pair_consent.stamp does, and object storage faked. Pins:

  * a project deletion REQUEST voids a release holding one of the project's
    pairs before any purge exists, with 'project_erasure_requested': every
    pair the release held goes back to waiting, a release holding none of
    them is untouched, and the export's decision lets the other owners'
    pairs leave again but never the project's;
  * an account deletion REQUEST does the same for the person's pairs, with
    'owner_erasure_requested', and finds a release by its owner list even
    when no pair points at it;
  * the void holds until a cancel, and stays a void after it;
  * a pair released after the request is voided when the purge request is
    made, by the system's start and by the operator's confirm;
  * the completion run voids before its purge deletes the pairs, and its
    sweep deletes the objects: nothing waits for the weekly job;
  * requests made before 0454 get what their request would have done.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import psycopg2
import pytest

from services.deletion_completion import run_due_deletions
from services.pair_release_eligibility import decide
from services.project_deletion import ProjectDeletionService
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

MIGRATION = (Path(__file__).resolve().parents[1] / "migrations"
             / "an_erasure_voids_the_released_copies.sql").read_text()
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


def _project(db, principal: str) -> tuple[str, str]:
    """A project of the person's with one Take: (project, take)."""
    user_id = _one(db, "SELECT user_id::text FROM public.owner_principals "
                       "WHERE id = %s", (principal,))
    project = str(_one(db, """
        INSERT INTO public.projects (id, owner_principal_id, display_name)
        VALUES (gen_random_uuid(), %s, 'Q4 pitch') RETURNING id""", (principal,)))
    take = str(_one(db, """
        INSERT INTO public.v2_sessions (
            id, user_id, owner_principal_id, project_id, arc_id, take_index)
        VALUES (gen_random_uuid(), %s, %s, %s, %s, 1) RETURNING id""",
        (user_id, principal, project, project)))
    return project, take


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


def test_a_project_deletion_request_voids_a_release_holding_one_of_its_pairs(db):
    _grants(db)
    owner, _ = window._yes(db)
    other, _ = window._yes(db)
    project, take = _project(db, owner)
    _kept, kept_take = _project(db, owner)
    mine = _pair(db, owner, take)
    elsewhere = _pair(db, owner, kept_take)
    theirs = _pair(db, other)
    _refresh(db)
    assert all(_pair_state(db, p)["releasable"] for p in (mine, elsewhere, theirs))
    holding = _release(db, [mine, theirs], [owner, other])
    untouched = _release(db, [elsewhere], [owner])

    ProjectDeletionService(_Database(db)).request(owner, project, f"k-{uuid.uuid4()}")

    assert _purges(db, owner) == 0                       # before any purge
    assert _release_state(db, holding) == {
        "voided_reason": "project_erasure_requested", "voided": True, "purged": False}
    assert _release_state(db, untouched) == {
        "voided_reason": None, "voided": False, "purged": False}
    assert _pair_state(db, mine) == WAITING
    assert _pair_state(db, theirs) == WAITING
    assert _pair_state(db, elsewhere)["release_id"] == untouched
    # The next export: the other owner's pair leaves again, the project's never.
    assert _would_leave(db, [mine, theirs]) == {theirs}


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


def test_the_void_holds_until_a_cancel_and_stays_a_void_after_it(db):
    _grants(db)
    owner, _ = window._yes(db)
    project, take = _project(db, owner)
    pair = _pair(db, owner, take)
    _refresh(db)
    release = _release(db, [pair], [owner])
    projects = ProjectDeletionService(_Database(db))
    projects.request(owner, project, f"k-{uuid.uuid4()}")
    later = _pair(db, owner, take)            # a coach answers during the window
    _stamped_releasable(db, later)
    _refresh(db)

    assert _would_leave(db, [pair, later]) == set()
    assert _release_state(db, release)["voided_reason"] == "project_erasure_requested"

    projects.cancel(owner, project)

    assert _would_leave(db, [pair, later]) == {pair, later}
    assert _pair_state(db, pair) == WAITING
    assert _release_state(db, release)["voided_reason"] == "project_erasure_requested"


def test_a_pair_released_after_the_request_is_voided_when_the_purge_request_is_made(db):
    _grants(db)
    projects = ProjectDeletionService(_Database(db))
    for confirm in ("system", "operator"):
        owner, _ = window._yes(db)
        project, take = _project(db, owner)
        request = window._due_project_request(db, owner, project)
        pair = _pair(db, owner, take)
        _stamped_releasable(db, pair)
        release = _release(db, [pair], [owner])   # left before any void ran

        if confirm == "system":
            projects.start_due(request)
        else:
            projects.confirm(request, str(uuid.uuid4()))

        assert _purges(db, owner) == 1, confirm
        assert _release_state(db, release)["voided_reason"] == (
            "project_erasure_requested"), confirm
        assert _pair_state(db, pair) == WAITING, confirm
        assert _would_leave(db, [pair]) == set(), confirm


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
    # Asked for before 0454 and long due: no void ran, and the run takes it
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


def test_a_dry_run_sweeps_nothing(db):
    _grants(db)
    person, _ = window._yes(db)
    pair = _pair(db, person)
    _refresh(db)
    release = _release(db, [pair], [person])
    window._service(db).request_account_deletion(
        person, idempotency_key=f"account-deletion:{uuid.uuid4()}")
    bucket = _Bucket()

    report = run_due_deletions(_Ledger(db), execute=False, release_storage=bucket)

    assert "release_sweep" not in report and bucket.deleted == []
    assert _release_state(db, release) == {
        "voided_reason": "owner_erasure_requested", "voided": True, "purged": False}


# ── Before 0454, and the doors ────────────────────────────────────────────


def test_requests_made_before_0454_get_what_their_request_would_have_done(db):
    _grants(db)
    owner, _ = window._yes(db)
    person, _ = window._yes(db)
    project, take = _project(db, owner)
    project_pair, person_pair = _pair(db, owner, take), _pair(db, person)
    _refresh(db)
    project_release = _release(db, [project_pair], [owner])
    person_release = _release(db, [person_pair], [person])
    # Written as 0422 left them: neither request voided anything.
    _one(db, """
        INSERT INTO public.project_deletion_requests (
            acquisition_principal_id, project_id, due_at, idempotency_key)
        VALUES (%s, %s, now() + interval '7 days', %s) RETURNING id""",
        (owner, project, f"k-{uuid.uuid4()}"))
    _one(db, """
        INSERT INTO public.account_deletion_requests (
            acquisition_principal_id, completes_after, idempotency_key, reason_code)
        VALUES (%s, now() + interval '7 days', %s, 'ACCOUNT_DELETION') RETURNING id""",
        (person, f"k-{uuid.uuid4()}"))
    assert not _release_state(db, project_release)["voided"]
    assert not _release_state(db, person_release)["voided"]
    catch_up = MIGRATION[MIGRATION.rindex("DO $$"):MIGRATION.rindex("COMMIT;")]

    with db.cursor() as cur:
        cur.execute(catch_up)

    assert _release_state(db, project_release)["voided_reason"] == "project_erasure_requested"
    assert _release_state(db, person_release)["voided_reason"] == "owner_erasure_requested"
    assert _pair_state(db, project_pair) == WAITING
    assert _pair_state(db, person_pair) == OUT
    voided_at = _one(db, "SELECT voided_at FROM public.pair_releases WHERE id = %s",
                     (project_release,))
    with db.cursor() as cur:
        cur.execute(catch_up)                  # twice is once
    assert _one(db, "SELECT voided_at FROM public.pair_releases WHERE id = %s",
                (project_release,)) == voided_at


def test_the_void_takes_only_its_two_reasons_and_no_browser_reaches_it(db):
    with pytest.raises(psycopg2.Error, match="PAIR_RELEASE_VOID_REASON_INVALID"):
        _one(db, "SELECT public.void_pair_releases_v1(ARRAY[]::uuid[], "
                 "'consent_withdrawn')")
    for fn in ("void_pair_releases_v1(uuid[], text)",
               "void_project_pair_releases_v1(uuid)",
               "stop_phase1_learning_v1(uuid)",
               "request_project_deletion_v1(uuid, uuid, text)",
               "start_due_project_deletion_v1(uuid)",
               "confirm_project_deletion_v1(uuid, uuid)"):
        for role in ("anon", "authenticated"):
            assert _one(db, "SELECT has_function_privilege(%s, %s, 'EXECUTE')",
                        (role, f"public.{fn}")) is False, (role, fn)
        assert _one(db, "SELECT has_function_privilege('service_role', %s, 'EXECUTE')",
                    (f"public.{fn}",)) is True, fn
