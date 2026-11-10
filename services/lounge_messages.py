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
from datetime import datetime, timedelta, timezone
from typing import Any, Optional


# Closed sets — mirror the DB CHECK constraints in
# migrations/add_lounge_messages_table.sql.
VALID_ROLES = ("user", "bot", "system")
# "cadence" = Explore-Session multi-take guidance bubbles (Prompt A §4),
# bot-only + server-inserted; the FE never sends it. The AUTHORITATIVE DB
# CHECK mirror is the LATEST kind migration:
# migrations/the_lounge_holds_the_walk_steps.sql (pinned by
# test_lounge_kind_migration.py — adding a kind here without a new
# migration fails CI).
# "best_presentation_ready" = the durable "your best presentation is ready"
# card — fired ONLY when the arc has >=3 takes AND is coach-reviewed AND paid.
# "transcript_ready" = its unpaid/unreviewed transcript counterpart. Both are
# bot-only and server-inserted; the frontend never sends them.
# "feedback" (grey ×3) + "ideal_text" (purple ×1) = the delivery-layer
# bubbles (founder 2026-07-15), inserted server-side by the coach's
# "Save and Publish full analysis"; the FE opens the feedback page /
# ideal-text notebook from their metadata.
# "walk_step" = one step of a Take's review, posted by the app (founder
# lock 2026-10-12, moment and feedback chat, section 1): the walk is a lens
# over these messages. Metadata: take, step, author, answer; never a score.
VALID_KINDS = (
    "text", "joke", "status", "recording_summary", "insight", "cadence",
    "best_presentation_ready", "transcript_ready",
    "feedback", "ideal_text",
    "walk_step",
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


def stamp_after(*stamps: Any, gap_ms: int = 1) -> str:
    """Now, or ``gap_ms`` after the latest of ``stamps`` when that is later.

    The thread is ordered by ``client_created_at`` and the browser stamps
    its own rows with its own clock (the walk's steps, a typed turn), so a
    row the server writes after one of them takes the later of the two
    times: a reply never sorts above the turn it answers, nor a summary
    above the walk it closes, whatever either clock says. Pure."""
    now = datetime.now(timezone.utc)
    later = [t for t in (_parse_iso(s) for s in stamps) if t is not None]
    latest = max((t if t.tzinfo else t.replace(tzinfo=timezone.utc) for t in later),
                 default=None)
    if latest is not None and latest + timedelta(milliseconds=gap_ms) > now:
        now = latest + timedelta(milliseconds=gap_ms)
    return now.isoformat()


def thread_stamp(database: Any, user_id: Any) -> str:
    """The time for a row written now at the bottom of this speaker's
    thread: after its newest row (``stamp_after``). Best-effort: the
    server's own clock when the thread cannot be read."""
    try:
        rows = database.get_lounge_messages_page(str(user_id), limit=1) or []
    except Exception:  # noqa: BLE001 -- the row is written either way
        rows = []
    return stamp_after(*(r.get("client_created_at") for r in rows[:1]))


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


# ── Which chat a Lounge row shows in (N635) ─────────────────────────────
#
# For whoever has the ring row ``chat_builder``, the Lounge's rows are shown
# in three chats: what belongs to speaking only in the speaking chat (N590:
# the Take's rows, "Your feedback is ready.", the way into the Feedback
# walk, the plan's questions and its card, the feelings check, the line
# after the walk); the principles coaching in its own chat, "Principles"
# (the # notebook and what Will reads in it: the Sunday note, strengths,
# what is in your control, the sales step, your why, life goals; frontend
# docs/flows/principles.md); and the rest in Will's chat (the model, the
# chat's setup, what needs you). Nothing is stored differently: a row is placed by
# what it already carries. THIS IS THE ONE LIST; tests/test_lounge_place.py
# names every writer of the Lounge and fails on one this list does not place.

SPEAKING, PRINCIPLES, WILL = "speaking", "principles", "will"
PLACES = (SPEAKING, PRINCIPLES, WILL)

#: Kinds that only a Take makes: its readout, the walk's steps, the coach's
#: feedback and Ideal Text bubbles, the cadence after a Take.
SPEAKING_KINDS = frozenset({
    "recording_summary", "cadence", "walk_step", "feedback", "ideal_text",
    "best_presentation_ready", "transcript_ready", "status", "insight", "joke",
})
#: Metadata keys that tie a row to a Take or to the speaking plan: the
#: plan's rows and the way in (``plan``), anything about a Take or its
#: project, the feelings check, Will's question on a Take, the bridge and
#: the goodbye after a Take.
SPEAKING_KEYS = frozenset({
    "plan", "arc_id", "take_session_id", "session_id", "recording_id", "take_index",
    "first_take", "bridge", "next_take", "feedback_check", "will_question",
})
#: Offers made about a Take or the coach's feedback.
SPEAKING_OFFERS = frozenset({"joke", "feedback_check", "will_question", "whatsapp"})
#: Notes about the coach's feedback.
SPEAKING_NOTES = frozenset({"feedback_digest"})
#: The principles coaching (frontend docs/flows/principles.md): the offers
#: of the voice notebook, the Sunday note, life goals, the sales step, your
#: why and strengths, and the keys their rows carry.
PRINCIPLES_OFFERS = frozenset({
    "voice_notebook", "sunday_note", "life_goals", "life_goals_quarter", "life_goals_change",
    "sales_step", "your_why", "strengths",
})
PRINCIPLES_KEYS = frozenset({
    "sunday_note_id", "sunday_step", "sales_note", "life_goal_quarter", "life_goal_change",
    "strength_id", "strength_talk", "in_control", "your_why_ask", "your_why_answer", "held_note",
})


def place_of(row: dict) -> str:
    """"speaking", "principles" or "will" for one Lounge row (N635)."""
    if row.get("kind") in SPEAKING_KINDS:
        return SPEAKING
    meta = row.get("metadata")
    if not isinstance(meta, dict):
        return WILL
    if any(meta.get(k) not in (None, "", False) for k in SPEAKING_KEYS):
        return SPEAKING
    if meta.get("offer") in SPEAKING_OFFERS or meta.get("note") in SPEAKING_NOTES:
        return SPEAKING
    if meta.get("offer") in PRINCIPLES_OFFERS or any(meta.get(k) not in (None, "", False)
                                                     for k in PRINCIPLES_KEYS):
        return PRINCIPLES
    return WILL


def parse_place(raw: Optional[str]) -> Optional[str]:
    """``?place=``: "speaking", "principles", "will", or none (every row, as before)."""
    if raw is None or raw == "":
        return None
    if raw not in PLACES:
        raise LoungeValidationError("place: must be speaking, principles or will")
    return raw


#: Older pages read, at most, to fill one page of one place.
PLACE_ROUNDS = 5


def placed_page(fetch: Any, limit: int, before: Optional[str], place: Optional[str]) -> dict:
    """The GET page for one place (N635), or every row with no place. Each
    message says its ``place``. ``fetch(limit, before)`` reads DESC, up to
    ``limit + 1`` rows, as ``get_lounge_messages_page``. A place reads older
    pages until it has a page of its own (at most PLACE_ROUNDS reads);
    ``oldest_cursor`` then continues from the last row read, so the next
    page never reads a row twice."""
    if place is None:
        page = shape_lounge_page(fetch(limit, before), limit)
    else:
        kept: list[dict] = []
        cursor, more = before, False
        for _ in range(PLACE_ROUNDS):
            rows = fetch(limit, cursor) or []
            scanned = rows[:limit]
            more = len(rows) > limit
            for r in scanned:
                if place_of(r) == place:
                    kept.append(r)
            if scanned:
                cursor = scanned[-1].get("client_created_at")
            if len(kept) > limit or not more or not scanned:
                break
        page_desc = kept[:limit]
        if len(kept) > limit:
            more, cursor = True, page_desc[-1].get("client_created_at")
        page = {"messages": list(reversed(page_desc)), "has_more": more,
                "oldest_cursor": cursor if more else None}
    for m in page["messages"]:
        m["place"] = place_of(m)
    return page
