from services.project_ownership import (
    issue_guest_owner,
    parse_guest_owner_token,
    verify_guest_owner,
)


def test_guest_claim_migration_transfers_the_complete_take_graph():
    from pathlib import Path

    sql = (Path(__file__).parent / "migrations" /
           "add_canonical_project_ownership.sql").read_text()
    claim = sql.split("CREATE OR REPLACE FUNCTION public.claim_guest_owner", 1)[1]
    claim = claim.split("CREATE OR REPLACE FUNCTION public.bind_project_take", 1)[0]

    assert "UPDATE public.projects" in claim
    assert "UPDATE public.v2_sessions" in claim
    assert "SET owner_principal_id = existing.id," in claim
    assert "user_id = p_user_id" in claim
    assert "UPDATE public.recording_1" in claim
    assert "UPDATE public.charisma_snippets" in claim
    assert "UPDATE public.moment_suggestions" in claim


def test_canonical_migration_preserves_historical_guest_funnel_storage():
    """Retiring the shaky-voice UI must never erase guest evidence or schema."""
    sql = open(
        "migrations/add_canonical_project_ownership.sql",
        encoding="utf-8",
    ).read().lower()
    forbidden = (
        "drop table if exists public.funnel_config",
        "drop table if exists funnel_config",
        "drop column if exists guest_claimed_at",
        "drop column if exists guest_session_id",
        "delete from public.v2_sessions",
    )
    assert all(fragment not in sql for fragment in forbidden)


def test_guest_owner_token_is_verifiable_and_not_the_stored_secret():
    issued = issue_guest_owner()
    principal_id, supplied_hash = parse_guest_owner_token(issued.token)
    assert principal_id == issued.principal_id
    assert supplied_hash == issued.secret_hash
    assert issued.secret_hash not in issued.token
    assert verify_guest_owner(issued.token, {
        "id": issued.principal_id,
        "user_id": None,
        "guest_secret_hash": issued.secret_hash,
    }) == issued.principal_id


def test_claimed_or_wrong_guest_owner_is_rejected():
    issued = issue_guest_owner()
    assert verify_guest_owner(issued.token, {
        "id": issued.principal_id,
        "user_id": "permanent-user",
        "guest_secret_hash": None,
    }) is None
    other = issue_guest_owner()
    assert verify_guest_owner(issued.token, {
        "id": issued.principal_id,
        "user_id": None,
        "guest_secret_hash": other.secret_hash,
    }) is None
