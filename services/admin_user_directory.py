"""Bounded, admin-only directory of Supabase Auth users.

The route owns no user mutation. It exposes only the fields needed to review
accounts and open the existing token top-up tool: identity, access class, and
account timestamps. Token grants remain behind the separate idempotent grant
endpoint.

One list (founder 2026-10-27, N221): everyone still here. Two kinds of
people are left out. Someone whose account deletion is recorded and not
cancelled leaves it at once, though their data is deleted only after the
seven-day window. Once the deletion is done the sign-in record stays, emptied
(N218): that record and Supabase's own soft delete both carry ``deleted_at``,
which the Auth admin API returns, so neither is ever listed.
"""
from __future__ import annotations

import logging
from typing import Any

from services.db import db

logger = logging.getLogger(__name__)


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


def _is_deleted(user: dict) -> bool:
    return bool(user.get("deleted_at"))


def _being_deleted() -> set[str]:
    """The user ids of every live account deletion. An admin's deletion names
    the user in its key; the person's own names them through their principal.
    If this cannot be read, nobody is left out for it: the list shows
    everyone, as it did before."""
    from services.account_deletion import LIVE_STATES
    from services.admin_person import admin_delete_user
    try:
        rows = (db.client.table("account_deletion_requests")
                .select("acquisition_principal_id,idempotency_key")
                .in_("state", list(LIVE_STATES))
                .limit(MAX_SEARCH_USERS).execute().data or [])
        principals = sorted({str(row["acquisition_principal_id"]) for row in rows
                             if row.get("acquisition_principal_id")})
        owners = (db.client.table("owner_principals").select("id,user_id")
                  .in_("id", principals).execute().data or []) if principals else []
    except Exception as exc:  # noqa: BLE001 -- the list still loads
        logger.warning("admin/users: deletions not read: %s", type(exc).__name__)
        return set()
    user_of = {str(o["id"]): str(o["user_id"]) for o in owners if o.get("user_id")}
    found: set[str] = set()
    for row in rows:
        user_id = (admin_delete_user(str(row.get("idempotency_key") or ""))
                   or user_of.get(str(row.get("acquisition_principal_id"))))
        if user_id:
            found.add(user_id)
    return found


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
    """Return one stable page of the list, scanning Auth only when a search
    is asked for."""
    clean_limit = max(1, min(int(limit), MAX_PAGE_SIZE))
    clean_offset = max(0, int(offset))
    clean_search = str(search or "").strip().lower()[:200]
    left_out = _being_deleted()

    def in_view(user: dict) -> bool:
        if _is_deleted(user):
            return False
        return str(user.get("user_id") or "") not in left_out

    if clean_search:
        matches: list[dict] = []
        cursor = 0
        while cursor < MAX_SEARCH_USERS:
            page = _auth_page(limit=MAX_PAGE_SIZE, offset=cursor)
            matches.extend(user for user in page
                           if _matches(user, clean_search) and in_view(user))
            if len(page) < MAX_PAGE_SIZE:
                break
            cursor += MAX_PAGE_SIZE
        selected = matches[clean_offset : clean_offset + clean_limit]
        has_more = len(matches) > clean_offset + clean_limit
        next_offset = clean_offset + len(selected)
    else:
        page = _auth_page(limit=clean_limit, offset=clean_offset)
        selected = [user for user in page if in_view(user)]
        # GoTrue exposes page-based pagination rather than a stable total.
        # A full page may be the final page; one harmless empty follow-up is
        # preferable to fetching a differently-sized page and shifting the
        # offset calculation in db.v2_list_auth_users. The page is counted
        # before the people left out are taken out, so the next one starts
        # where this one ended.
        has_more = len(page) == clean_limit
        next_offset = clean_offset + len(page)

    admin_emails = _admin_emails()
    return {
        "users": [_public_user(user, admin_emails) for user in selected],
        "limit": clean_limit,
        "offset": clean_offset,
        "next_offset": next_offset,
        "has_more": has_more,
        "search": clean_search,
    }
