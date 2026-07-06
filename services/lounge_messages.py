"""willab beta — Lounge thread persistence helpers (BE contract §3.15).

Pure validation + page-shaping for the two Lounge endpoints. Kept
dependency-free (stdlib only — no services.db import) so it unit-tests
without a supabase client. The route layer (routes/v2_routes.py) owns
auth + wiring; db.py owns the queries; this owns the contract shape.

Contract recap (§3.15 / Appendix A):
  GET  /v2/user/lounge/messages?limit=50&before=<iso8601>
       → { messages[] ASC, has_more, oldest_cursor }
  POST /v2/user/lounge/messages
       body { messages: [{ client_id, role, kind, body, metadata?,
              client_created_at }] }
       → { messages: [...persisted] }   idempotent on (user_id, client_id)

Invariants this module enforces (BE contract §5.11):
  * role/kind are closed sets (mirrors the DB CHECK constraints).
  * client_id is a UUID (the idempotency/dedup key).
  * client_created_at is a real timestamp (the ordering key that must
    survive the unsigned→signed merge).
  * batch size is bounded (§7.9 — the merge can't replay an unbounded
    localStorage thread in one shot; FE chunks).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional


# Closed sets — mirror the DB CHECK constraints in
# migrations/add_lounge_messages_table.sql.
VALID_ROLES = ("user", "bot", "system")
# "cadence" = Explore-Session multi-take guidance bubbles (Prompt A §4),
# bot-only + server-inserted; the FE never sends it. The AUTHORITATIVE DB
# CHECK mirror is the LATEST kind migration:
# migrations/add_transcript_ready_lounge_kind.sql.
# "best_presentation_ready" = the durable "your best presentation is ready"
# card — fired ONLY when the arc has >=3 takes AND is coach-reviewed AND paid.
# "transcript_ready" = its unpaid/unreviewed counterpart (transcript text +
# strong sides). Both bot-only, server-inserted; the FE never sends them.
VALID_KINDS = (
    "text", "joke", "status", "recording_summary", "insight", "cadence",
    "best_presentation_ready", "transcript_ready",
)

# §7.9 — bound the merge batch. A long unsigned session can produce a
# big localStorage thread; the FE chunks the replay into batches of at
# most this many. Server-rejects oversize so a client can't dump an
# unbounded payload in one request.
MAX_BATCH = 200

# Page sizes for the GET. Default 50 (§7.5 — WhatsApp-like initial
# load); hard ceiling so a client can't request the whole thread.
DEFAULT_PAGE = 50
MAX_PAGE = 200

# Generous body cap — Lounge bubbles are chat text + (local Web Speech)
# transcripts, which can run long, but not unbounded.
MAX_BODY_LEN = 16_000


class LoungeValidationError(ValueError):
    """Validation error with an FE-renderable message. The route
    catches and 422s with the message verbatim (matches the
    INVALID_INPUT pattern across v2_routes.py)."""


def _is_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError, TypeError):
        return False


def _parse_iso(value: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp tolerantly (accepts trailing 'Z').
    Returns the datetime on success, None on failure. We keep the
    caller's original string for storage — this is validation only."""
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    # datetime.fromisoformat pre-3.11 doesn't accept 'Z'; normalise.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def validate_lounge_batch(body: Any) -> list[dict]:
    """Validate a POST batch, returning the cleaned message list.

    Each returned row carries exactly: client_id, role, kind, body,
    metadata, client_created_at — ready for db.insert_lounge_messages
    to stamp user_id onto.

    Raises LoungeValidationError on:
      - body not a dict / messages not a non-empty list
      - batch over MAX_BATCH (FE must chunk)
      - any row: bad client_id (non-UUID), role/kind not in the closed
        set, body not a string / over cap, metadata not object|null,
        client_created_at missing/unparseable
    """
    if not isinstance(body, dict):
        raise LoungeValidationError("Body must be a JSON object")

    msgs = body.get("messages")
    if not isinstance(msgs, list) or not msgs:
        raise LoungeValidationError("messages: must be a non-empty array")
    if len(msgs) > MAX_BATCH:
        raise LoungeValidationError(
            f"messages: at most {MAX_BATCH} per batch — chunk the merge"
        )

    cleaned: list[dict] = []
    for i, m in enumerate(msgs):
        if not isinstance(m, dict):
            raise LoungeValidationError(f"messages[{i}]: must be an object")

        client_id = m.get("client_id")
        if not _is_uuid(client_id):
            raise LoungeValidationError(
                f"messages[{i}].client_id: must be a UUID"
            )

        role = m.get("role")
        if role not in VALID_ROLES:
            raise LoungeValidationError(
                f"messages[{i}].role: must be one of {', '.join(VALID_ROLES)}"
            )

        kind = m.get("kind")
        if kind not in VALID_KINDS:
            raise LoungeValidationError(
                f"messages[{i}].kind: must be one of {', '.join(VALID_KINDS)}"
            )

        raw_body = m.get("body", "")
        if raw_body is None:
            raw_body = ""
        if not isinstance(raw_body, str):
            raise LoungeValidationError(
                f"messages[{i}].body: must be a string"
            )
        if len(raw_body) > MAX_BODY_LEN:
            raise LoungeValidationError(
                f"messages[{i}].body: must be {MAX_BODY_LEN} characters or fewer"
            )

        metadata = m.get("metadata")
        if metadata is not None and not isinstance(metadata, dict):
            raise LoungeValidationError(
                f"messages[{i}].metadata: must be an object or null"
            )

        cca = m.get("client_created_at")
        if _parse_iso(cca) is None:
            raise LoungeValidationError(
                f"messages[{i}].client_created_at: must be an ISO-8601 timestamp"
            )

        cleaned.append({
            "client_id":         client_id,
            "role":              role,
            "kind":              kind,
            "body":              raw_body,
            "metadata":          metadata,
            "client_created_at": cca,
        })

    return cleaned


def parse_limit(raw: Any) -> int:
    """Clamp the GET ?limit= to [1, MAX_PAGE], default DEFAULT_PAGE.
    Non-numeric silently falls back to the default (non-blocking)."""
    if raw is None:
        return DEFAULT_PAGE
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_PAGE
    return max(1, min(n, MAX_PAGE))


def validate_before_cursor(raw: Any) -> Optional[str]:
    """Validate the GET ?before= cursor. Returns the original string
    (for the DB comparison) or None when absent. Raises on a present-
    but-unparseable cursor so a malformed page request fails loudly
    rather than silently returning the whole thread."""
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    if _parse_iso(raw) is None:
        raise LoungeValidationError(
            "before: must be an ISO-8601 timestamp cursor"
        )
    return raw.strip() if isinstance(raw, str) else raw


def shape_lounge_page(rows_desc: list[dict], limit: int) -> dict:
    """Shape a DESC-ordered fetch of up to ``limit + 1`` rows into the
    GET response contract.

    The DB fetches newest-first (DESC) with one extra row to detect
    whether older messages exist. This function:
      - sets has_more = (we got more than `limit`)
      - trims to `limit`
      - reverses to ASC (the FE renders bottom-to-top, oldest first
        within the page)
      - sets oldest_cursor = the oldest returned row's client_created_at
        when has_more (pass as ?before= for the next older page), else
        null

    Pure function — unit-tested directly, no DB.
    """
    has_more = len(rows_desc) > limit
    page_desc = rows_desc[:limit]
    messages_asc = list(reversed(page_desc))

    oldest_cursor = None
    if has_more and messages_asc:
        oldest_cursor = messages_asc[0].get("client_created_at")

    return {
        "messages":      messages_asc,
        "has_more":      has_more,
        "oldest_cursor": oldest_cursor,
    }
