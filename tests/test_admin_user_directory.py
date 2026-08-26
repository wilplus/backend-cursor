import pytest

from services import admin_user_directory
from tests.fakes import FakeSupabaseClient, swap_attr


def _user(user_id: str, email: str, name: str | None = None) -> dict:
    return {
        "user_id": user_id,
        "email": email,
        "name": name,
        "created_at": "2026-08-01T10:00:00Z",
        "last_sign_in_at": "2026-08-25T09:00:00Z",
        "email_confirmed_at": "2026-08-01T10:01:00Z",
    }


def test_list_users_returns_bounded_fields_and_marks_active_admin_by_email():
    client = FakeSupabaseClient({
        "admin_users": [{"email": "founder@example.com", "is_active": True}],
    })
    auth_users = [
        _user("u1", "founder@example.com", "Founder"),
        _user("u2", "member@example.com", "Member"),
    ]

    with swap_attr(admin_user_directory.db, "client", client), swap_attr(
        admin_user_directory.db,
        "v2_list_auth_users",
        lambda limit, offset: auth_users[offset : offset + limit],
    ):
        result = admin_user_directory.list_users(limit=2)

    assert result["has_more"] is True
    assert result["users"] == [
        {**auth_users[0], "is_admin": True},
        {**auth_users[1], "is_admin": False},
    ]
    assert set(result["users"][0]) == {
        "user_id",
        "email",
        "name",
        "created_at",
        "last_sign_in_at",
        "email_confirmed_at",
        "is_admin",
    }


def test_search_scans_auth_pages_before_paginating_matches():
    client = FakeSupabaseClient({"admin_users": []})
    auth_users = [
        _user(f"u{index}", f"person{index}@example.com", f"Person {index}")
        for index in range(105)
    ]
    auth_users[102] = _user("target", "voice@example.com", "Voice Researcher")
    calls: list[tuple[int, int]] = []

    def list_auth_users(limit: int, offset: int) -> list[dict]:
        calls.append((limit, offset))
        return auth_users[offset : offset + limit]

    with swap_attr(admin_user_directory.db, "client", client), swap_attr(
        admin_user_directory.db, "v2_list_auth_users", list_auth_users
    ):
        result = admin_user_directory.list_users(search="VOICE", limit=10)

    assert calls == [(100, 0), (100, 100)]
    assert [row["user_id"] for row in result["users"]] == ["target"]
    assert result["search"] == "voice"
    assert result["has_more"] is False


def test_auth_directory_failure_is_fail_closed():
    client = FakeSupabaseClient({"admin_users": []})
    with swap_attr(admin_user_directory.db, "client", client), swap_attr(
        admin_user_directory.db, "v2_list_auth_users", lambda **_: None
    ):
        with pytest.raises(
            admin_user_directory.AdminUserDirectoryError,
            match="auth users could not be read",
        ):
            admin_user_directory.list_users()
