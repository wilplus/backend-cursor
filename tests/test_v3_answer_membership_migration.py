"""The answer gate must look in the freeze that actually served the item.

FOUNDER, 2026-09-20, with the Confident Voice question on screen and a red
bar under it: "feedback item is not in this Take's frozen set". He was
answering an item the product had just shown him.

TWO FREEZES, ONE READER. `_ChangesRun.execute` claims the V2 compatibility
set into `ideal_text_feedback_sets`, and THEN runs `_first_client_feedback`,
which replaces `self.changes` wholesale with V3's rows. Since the V3 cutover
(2026-09-18) those rows are what the user sees, and their ids live in
`feedback_v3_membership_items`. `record_take_feedback_response_v1` consulted
only the V2 set, so every answer to a V3-served item returned `not_member` —
the served policy and the answer gate disagreeing about what exists, every
time, since the day V3 started serving.

WHY THIS FILE IS A TEXT GUARD RATHER THAN AN EXECUTION TEST. The function
lives in SQL and the rehearsal lane does not carry it: the narrow recipe in
`tests/integration/confident_moment_rehearsal.sh` never applies
`add_atomic_take_feedback_response.sql`, so `record_take_feedback_response_v1`
and both response tables are absent from every rehearsal template. Running
the tier against this change would go green while testing none of it, which
is worse than not running it.

The behaviour WAS executed, against PostgreSQL 16, on a throwaway cluster
carrying the real DDL for all five tables. Both migrations applied, 0346
twice for idempotency, and every case below was observed:

    the founder's bug, against the CURRENT prod function      not_member
    the same answer, against 0346                             saved
    V2 take, V2 item (must be unchanged)                      saved
    V3 take, praise lane                                      saved
    V3 take, rewrite lane                                     saved
    V3 item the Manager did NOT select (L2)                   not_member
    an id in neither freeze                                   not_member
    right id, WRONG family                                    not_member
    one take's V3 item answered on another take               not_member
    replay / conflict / snippet provenance                    correct

What CANNOT be re-run on every commit is exactly what a later edit is most
likely to weaken, so the invariants that made those results correct are
asserted here against the file itself.
"""
from __future__ import annotations

from pathlib import Path

import pytest

MIGRATION = Path("migrations/answer_a_v3_item_against_the_freeze_that_served_it.sql")


@pytest.fixture(scope="module")
def sql() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def test_the_migration_is_registered_in_the_manifest():
    """An unregistered migration is a file, not a change. `MIGRATE_ON_BOOT=1`
    applies the manifest, so a fix that is not listed never runs."""
    manifest = Path("migrations/manifest.txt").read_text(encoding="utf-8")
    assert MIGRATION.name in manifest


def test_only_a_selected_v3_item_can_be_answered(sql: str):
    """L2, and the single most important line in the migration.

    `feedback_v3_membership_items` holds the WHOLE deliberation — eligible and
    excluded rows alike — and only the selected ones were ever shown. Dropping
    this predicate would make every Candidate the Manager considered
    answerable, which is precisely "surfaces a raw Candidate".

    It is also the easiest thing in the file to lose: the join reads perfectly
    well without it, and nothing at runtime would complain.
    """
    assert "AND i.selected" in sql


def test_the_v3_lookup_is_bound_to_this_take(sql: str):
    """Without this a candidate_key from ANY take would answer on any other —
    one recording's signal reused for another (L3)."""
    assert "m.take_id = p_take_session_id" in sql


def test_the_v3_lookup_matches_the_family_too(sql: str):
    """`feedback_id` alone is not an identity. The V2 branch has always
    matched id AND family; the V3 branch matches both for the same reason."""
    assert "i.candidate_key = p_feedback_id" in sql
    assert "i.feedback_family = p_feedback_family" in sql


def test_the_v2_set_is_consulted_first(sql: str):
    """This is what makes the change additive rather than a rewrite.

    A take whose item is in the V2 set takes the old path exactly as before
    and never reaches the new code, so no V2 take can regress. Reversing the
    order would put every existing take through new logic for no gain.
    """
    v2_at = sql.index("FROM public.ideal_text_feedback_sets")
    v3_at = sql.index("FROM public.feedback_v3_membership_items")
    assert v2_at < v3_at
    assert "IF member IS NULL" in sql[:v3_at]


def test_an_absent_v2_set_no_longer_short_circuits(sql: str):
    """0333 returned `not_member` the moment no V2 set existed.

    A take can legitimately have none: `_claim_or_filter` refuses the claim
    when `has_required_families` fails, and V3 then serves from the candidate
    pool regardless. Keeping that early return would leave exactly those takes
    unanswerable — verified on PostgreSQL, the "no V2 set" case saves.
    """
    assert "IF frozen_row.arc_id IS NULL THEN" not in sql


def test_the_v3_tables_are_guarded_rather_than_assumed(sql: str):
    """Migrations degrade gracefully here. An environment without the V3
    serving tables must answer "not a member", not raise."""
    assert "to_regclass('public.feedback_v3_membership_items')" in sql


def test_the_membership_row_is_locked_like_the_v2_row(sql: str):
    """The check and the insert are one transaction on purpose — 0308's note:
    there is deliberately no read/insert fallback "because it would recreate
    the first-click race this boundary removes". A V3 membership read without
    a lock puts that race back for exactly the takes this fix is for."""
    assert "FOR SHARE OF i, m" in sql


def test_the_provenance_record_names_the_freeze_that_authorised_it(sql: str):
    """`selected_keys` in the result becomes `input_provenance` on the human-
    decision stage record. Returning V2's unrelated three for a V3 answer
    would file it under a selection that never showed it."""
    assert "'source', 'feedback_v3_membership'" in sql
    assert "'policy_version', v3_policy" in sql


def test_the_snippet_still_comes_from_the_freeze_not_the_request(sql: str):
    """The request's snippet is only ever compared, never stored. Verified on
    PostgreSQL: a wrong snippet returns `provenance_mismatch`, and each saved
    row carried its own frozen snippet."""
    assert "member_snippet := NULLIF(member->>'snippet_id', '')" in sql
    assert "'provenance_mismatch'" in sql


def test_both_supabase_roles_are_named_in_the_revoke(sql: str):
    """Supabase grants `anon` and `authenticated` EXECUTE directly through
    `ALTER DEFAULT PRIVILEGES`, so a REVOKE FROM PUBLIC alone leaves both
    holding it on a SECURITY DEFINER function that reads another user's
    feedback."""
    assert "FROM PUBLIC, anon, authenticated" in sql
    assert "TO service_role" in sql


def test_the_typed_response_taxonomy_is_unchanged(sql: str):
    """This migration widens WHICH ITEMS may be answered. It must not widen
    what an answer may say — that taxonomy is a separate gate held by the
    table CHECK, and the two are required to agree."""
    for family, responses in (
        ("confident_voice", "'yes', 'in_between', 'no', 'not_sure', 'audio_unclear'"),
        ("rewrite_clarity", "'apply_suggestion', 'edit_myself', 'keep_wording'"),
        ("great_formulation", "'useful', 'not_useful', 'not_sure', 'acknowledged'"),
    ):
        assert family in sql
        assert responses in sql
