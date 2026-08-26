"""Bounded, admin-only directory of Supabase Auth users.

The route owns no user mutation. It exposes only the fields needed to review
accounts and open the existing token top-up tool: identity, access class, and
account timestamps. Token grants remain behind the separate idempotent grant
endpoint.
"""
from __future__ import annotations

from typing import Any

from services.db import db


MAX_PAGE_SIZE = 100
MAX_SEARCH_USERS = 2_000


class AdminUserDirectoryError(RuntimeError):
    """The auth or admin directory could not be read safely."""


def _admin_emails() -> set[str]:
    try:
        result = (
            db.client.table("admin_users")
            .select("email,is_active")
            .eq("is_active", True)
            .execute()
        )
    except Exception as exc:
        raise AdminUserDirectoryError("admin access could not be read") from exc
    return {
        str(row.get("email") or "").strip().lower()
        for row in (result.data or [])
        if row.get("email") and row.get("is_active") is not False
    }


def _auth_page(*, limit: int, offset: int) -> list[dict]:
    users = db.v2_list_auth_users(limit=limit, offset=offset)
    if users is None:
        raise AdminUserDirectoryError("auth users could not be read")
    return users


def _matches(user: dict, search: str) -> bool:
    if not search:
        return True
    haystack = " ".join(
        str(user.get(field) or "") for field in ("email", "name", "user_id")
    ).lower()
    return search in haystack


def _public_user(user: dict, admin_emails: set[str]) -> dict[str, Any]:
    user_id = str(user.get("user_id") or "")
    email = user.get("email")
    return {
        "user_id": user_id,
        "email": email,
        "name": user.get("name"),
        "created_at": user.get("created_at"),
        "last_sign_in_at": user.get("last_sign_in_at"),
        "email_confirmed_at": user.get("email_confirmed_at"),
        "is_admin": str(email or "").strip().lower() in admin_emails,
    }


def list_users(*, limit: int = 50, offset: int = 0, search: str = "") -> dict:
    """Return one stable page, scanning Auth only when a search is supplied."""
    clean_limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    clean_offset = max(0, int(offset))
    clean_search = str(search or "").strip().lower()[:200]

    if clean_search:
        matches: list[dict] = []
        cursor = 0
        while cursor < MAX_SEARCH_USERS:
            page = _auth_page(limit=MAX_PAGE_SIZE, offset=cursor)
            matches.extend(user for user in page if _matches(user, clean_search))
            if len(page) < MAX_PAGE_SIZE:
                break
            cursor += MAX_PAGE_SIZE
        selected = matches[clean_offset : clean_offset + clean_limit]
        has_more = len(matches) > clean_offset + clean_limit
    else:
        selected = _auth_page(limit=clean_limit, offset=clean_offset)
        # GoTrue exposes page-based pagination rather than a stable total.
        # A full page may be the final page; one harmless empty follow-up is
        # preferable to fetching a differently-sized page and shifting the
        # offset calculation in db.v2_list_auth_users.
        has_more = len(selected) == clean_limit

    admin_emails = _admin_emails()
    return {
        "users": [_public_user(user, admin_emails) for user in selected],
        "limit": clean_limit,
        "offset": clean_offset,
        "has_more": has_more,
        "search": clean_search,
    }
