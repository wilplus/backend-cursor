"""Strict ownership for authenticated and pre-signup projects."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass


GUEST_OWNER_HEADER = "X-Willab-Guest-Owner"


@dataclass(frozen=True)
class GuestOwnerCredential:
    principal_id: str
    token: str
    secret_hash: str


def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()


def issue_guest_owner() -> GuestOwnerCredential:
    principal_id = str(uuid.uuid4())
    secret = secrets.token_urlsafe(32)
    return GuestOwnerCredential(
        principal_id=principal_id,
        token=f"{principal_id}.{secret}",
        secret_hash=_hash_secret(secret),
    )


def parse_guest_owner_token(token: str | None) -> tuple[str, str] | None:
    raw = str(token or "").strip()
    if not raw or "." not in raw:
        return None
    principal_id, secret = raw.split(".", 1)
    try:
        principal_id = str(uuid.UUID(principal_id))
    except (TypeError, ValueError):
        return None
    if len(secret) < 32:
        return None
    return principal_id, _hash_secret(secret)


def verify_guest_owner(token: str | None, stored: dict | None) -> str | None:
    parsed = parse_guest_owner_token(token)
    if not parsed or not stored or stored.get("user_id"):
        return None
    principal_id, supplied_hash = parsed
    stored_id = str(stored.get("id") or "")
    stored_hash = str(stored.get("guest_secret_hash") or "")
    if principal_id != stored_id or not stored_hash:
        return None
    return principal_id if hmac.compare_digest(supplied_hash, stored_hash) else None

