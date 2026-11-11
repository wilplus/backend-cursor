"""Block and Report in the chats between people (founder, the Claude Code
chat, 4 November 2026, N466; Apple's rule 1.2 for apps where people message
each other). Tables: ``chat_members.blocked_spans`` and ``chat_reports``
(migration a_person_can_block_and_report_someone_in_a_chat).

  * ``block`` / ``unblock``: a member blocks the other person in their chat,
    or stops. A block is a span on the member's own row, ``{"from", "to"}``,
    the open one in force. While it is open, the other person's messages and
    answers do not reach the member and no push goes to them; what was sent
    inside any span never reaches them, also after Unblock (N466 item 2).
    The other person is not told: their own chat reads as before.
  * ``report``: the last five messages in the chat, as the reporter sees
    them, are kept with who reported whom and whether they also blocked
    (N466 item 3), and reach the founder: an email to ADMIN_EMAIL and a row
    in the CEO panel (``reports``, ``handled``). The founder reads every
    report within a day (N466 item 4).
  * ``unheard`` and ``blocking``: what services/chats.py asks when it lists,
    reads and pushes. Read best-effort: a block that cannot be read hides
    nothing, so the chats never fail on it.

No provider call and no recording: nothing here passes the
processing-authorization path. Deleted with either account: a report's
members' rows cascade (services/data_purge_registry.py).
"""
from __future__ import annotations

import html
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

MEMBERS, MESSAGES, REPORTS, AUDIO = "chat_members", "chat_messages", "chat_reports", "chat_message_audio"
#: The report keeps the chat's last five messages (N466 item 3).
REPORTED_MESSAGES = 5
#: The founder's list shows this many reports, the newest first.
_MAX_REPORTS = 200
#: How much of one message a report keeps.
_MAX_TEXT = 2000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _when(value: Any) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def spans_of(row: Optional[dict]) -> list[tuple[datetime, Optional[datetime]]]:
    """A member row's blocks, oldest first; a span with an unreadable start is
    skipped, one with an unreadable end is open."""
    out: list[tuple[datetime, Optional[datetime]]] = []
    for span in (row or {}).get("blocked_spans") or []:
        if not isinstance(span, dict):
            continue
        start = _when(span.get("from"))
        if start is not None:
            out.append((start, _when(span.get("to"))))
    return out


def blocking(row: Optional[dict]) -> bool:
    """Has this member blocked the other person, now?"""
    spans = spans_of(row)
    return bool(spans) and spans[-1][1] is None


def spans_by_member(database: Any, member_ids: list[str]) -> dict[str, list]:
    """The blocks of these member rows, by id. Best-effort: on any failure,
    no blocks (nothing is hidden, nothing fails)."""
    ids = [m for m in member_ids if m]
    if not ids:
        return {}
    try:
        rows = database.client.table(MEMBERS).select("id,blocked_spans").in_("id", ids).execute().data or []
    except Exception as e:  # noqa: BLE001 -- the chats work without blocks
        logger.warning("chats: blocks not read: %s", e)
        return {}
    return {str(r["id"]): r.get("blocked_spans") or [] for r in rows}


def unheard(me: str, spans: list) -> Callable[[dict], bool]:
    """For member ``me`` with these blocks: does a message never reach them?
    One the other person sent inside a span (N466 item 2). Their own
    messages always do."""
    windows = spans_of({"blocked_spans": spans})

    def hidden(row: dict) -> bool:
        if not windows or str(row.get("author_member_id")) == me:
            return False
        sent = _when(row.get("created_at"))
        return sent is not None and any(sent >= start and (end is None or sent < end)
                                        for start, end in windows)
    return hidden


# ── Block and Unblock ────────────────────────────────────────────────────

def _member(database: Any, user_id: Any, thread_id: Any) -> dict:
    """The caller's row in a person's chat, or the chats' own 404."""
    from services import chats
    me = chats.member(database, user_id, thread_id)
    rows = (database.client.table(MEMBERS).select("id,thread_id,blocked_spans")
            .eq("id", str(me["id"])).limit(1).execute().data or [])
    return rows[0] if rows else {**me, "blocked_spans": []}


def _write_spans(database: Any, me: dict, spans: list[dict]) -> None:
    database.client.table(MEMBERS).update({"blocked_spans": spans}).eq("id", str(me["id"])).execute()


def _spans_list(row: dict) -> list[dict]:
    return [dict(s) for s in (row.get("blocked_spans") or []) if isinstance(s, dict)]


def _block(database: Any, me: dict) -> None:
    if blocking(me):
        return
    _write_spans(database, me, _spans_list(me) + [{"from": _now().isoformat(), "to": None}])


def block(database: Any, user_id: Any, thread_id: Any) -> dict:
    """POST /v2/chats/<id>/block: {"blocked": true}. Blocking twice is one block."""
    _block(database, _member(database, user_id, thread_id))
    return {"blocked": True}


def unblock(database: Any, user_id: Any, thread_id: Any) -> dict:
    """DELETE /v2/chats/<id>/block: {"blocked": false}. The span closes; what
    was sent inside it stays unheard."""
    me = _member(database, user_id, thread_id)
    if blocking(me):
        spans = _spans_list(me)
        spans[-1]["to"] = _now().isoformat()
        _write_spans(database, me, spans)
    return {"blocked": False}


# ── Report ───────────────────────────────────────────────────────────────

def _members(database: Any, thread: str) -> dict:
    rows = (database.client.table(MEMBERS).select("id,display_name").eq("thread_id", thread)
            .execute().data or [])
    return {str(r["id"]): r for r in rows}


def _last_five(database: Any, thread: str, me: dict, names: dict) -> list[dict]:
    """The chat's last five messages as the reporter sees them, oldest first:
    author, kind, text and a voice note's words."""
    from services.chats import _held  # an answer still in its 5 seconds
    rows = (database.client.table(MESSAGES).select("id,author_member_id,kind,body,meta,created_at")
            .eq("thread_id", thread).order("created_at", desc=True).limit(50).execute().data or [])
    hidden = unheard(str(me["id"]), me.get("blocked_spans") or [])
    from services.take_door import mine_only  # a Take tagged for its speaker only
    shown = [r for r in rows if not _held(r) and not hidden(r)
             and not mine_only(r, str(me["id"]))][:REPORTED_MESSAGES]
    words: dict[str, str] = {}
    voices = [str(r["id"]) for r in shown if r.get("kind") == "voice"]
    if voices:
        try:
            words = {str(a["message_id"]): a.get("words") or ""
                     for a in (database.client.table(AUDIO).select("message_id,words")
                               .eq("thread_id", thread).in_("message_id", voices).execute().data or [])}
        except Exception as e:  # noqa: BLE001 -- the report keeps the rest
            logger.warning("chats: a report's voice words not read: %s", e)
    out = []
    for r in reversed(shown):
        said = words.get(str(r["id"])) or ""
        out.append({"author": str((names.get(str(r["author_member_id"])) or {}).get("display_name") or ""),
                    "kind": r.get("kind"), "body": str(r.get("body") or "")[:_MAX_TEXT],
                    "words": said[:_MAX_TEXT] or None, "created_at": r.get("created_at")})
    return out


def report(database: Any, user_id: Any, thread_id: Any, body: Any) -> dict:
    """POST /v2/chats/<id>/report {"block": bool}: {"reported": true,
    "blocked": bool}. The founder hears of it at once."""
    me = _member(database, user_id, thread_id)
    thread = str(me["thread_id"])
    members = _members(database, thread)
    other = next((m for mid, m in members.items() if mid != str(me["id"])), None)
    if not other:
        from services.chats import ChatsError
        raise ChatsError("NOT_FOUND", "Not found.", 404)
    also_block = bool((body or {}).get("block")) if isinstance(body, dict) else False
    saved = (database.client.table(REPORTS).insert({
        "thread_id": thread, "reporter_member_id": str(me["id"]),
        "reported_member_id": str(other["id"]), "blocked": also_block,
        "messages": _last_five(database, thread, me, members)}).execute().data or [])
    if also_block:
        _block(database, me)
    if saved:
        _tell_founder(saved[0], members)
    return {"reported": True, "blocked": also_block or blocking(me)}


def _tell_founder(row: dict, members: dict) -> None:
    """An email to the founder's address; the CEO panel lists it either way.
    Never fails the report."""
    try:
        from config import Config
        from services.email_service import send_email_resend
        config = Config()
        if not getattr(config, "SEND_EMAILS", False):
            logger.info("chats: report %s kept; email off (SEND_EMAILS)", row.get("id"))
            return
        shown = _shown(row, members)
        lines = [f"{shown['reporter']} reported {shown['reported']}"
                 + (" and blocked them." if shown["blocked"] else "."), ""]
        for m in shown["messages"]:
            said = m.get("words") or m.get("body") or f"({m.get('kind')})"
            lines.append(f"{m.get('author')}: {said}")
        lines += ["", "Read it within a day, in the CEO panel."]
        text = "\n".join(lines)
        send_email_resend(to=config.ADMIN_EMAIL, subject=f"A report in the chats: {shown['reported']}",
                          html="<br>".join(html.escape(line) for line in lines), text=text)
    except Exception as e:  # noqa: BLE001 -- the report is kept either way
        logger.warning("chats: the founder's report email not sent: %s", e)


# ── The founder's list (CEO panel) ───────────────────────────────────────

def _shown(row: dict, members: dict) -> dict:
    def name(member_id: Any) -> str:
        return str((members.get(str(member_id)) or {}).get("display_name") or "Someone")
    return {"id": str(row["id"]), "created_at": row.get("created_at"),
            "reporter": name(row.get("reporter_member_id")),
            "reported": name(row.get("reported_member_id")),
            "blocked": bool(row.get("blocked")), "handled_at": row.get("handled_at"),
            "messages": list(row.get("messages") or [])}


def reports(database: Any) -> dict:
    """GET /v2/admin/chat-reports: {"reports": [...]}, the newest first."""
    rows = (database.client.table(REPORTS)
            .select("id,thread_id,reporter_member_id,reported_member_id,blocked,messages,created_at,handled_at")
            .order("created_at", desc=True).limit(_MAX_REPORTS).execute().data or [])
    ids = sorted({str(r[k]) for r in rows for k in ("reporter_member_id", "reported_member_id")})
    members = ({str(m["id"]): m for m in (database.client.table(MEMBERS).select("id,display_name")
                                          .in_("id", ids).execute().data or [])} if ids else {})
    return {"reports": [_shown(r, members) for r in rows]}


def handled(database: Any, report_id: Any) -> dict:
    """POST /v2/admin/chat-reports/<id>/handled: {"handled_at": iso}."""
    from services.chats import ChatsError, _uuid
    rid = _uuid(report_id)
    if not rid:
        raise ChatsError("NOT_FOUND", "Not found.", 404)
    at = _now().isoformat()
    rows = database.client.table(REPORTS).update({"handled_at": at}).eq("id", rid).execute().data or []
    if not rows:
        raise ChatsError("NOT_FOUND", "Not found.", 404)
    return {"handled_at": at}
