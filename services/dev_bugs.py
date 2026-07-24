"""dev-bugs — internal founder-only bug collector (dev.willpowerlab.com).

Self-contained feature module. DB access reuses the existing Supabase client
(``services.db.db.client``) and email reuses the existing Resend wrapper
(``services.email_service.send_email_resend``) — no new frameworks or providers,
and no methods added to the giant shared ``DatabaseService`` (keeps blast radius
to this file + the one additive ``attachments`` kwarg on the mailer).

Routes live in ``routes/dev_bugs.py``. Table: ``dev_bugs`` (see
``migrations/add_dev_bugs.sql``).

The digest email body is an LLM-ready triage prompt: a fixed backlog-context
preamble followed by the numbered bug list. The founder pastes it straight into
a coding agent. This is an internal prompt to the founder — not user-facing
product copy — so it is not under the master-doc construct fence.
"""
from __future__ import annotations

import base64
import logging
import re
from datetime import datetime
from html import escape as _html_escape
from typing import Any

from config import Config
from services.db import db
from services.email_service import send_email_resend

logger = logging.getLogger(__name__)
config = Config()

_TABLE = "dev_bugs"
_COLS = "id,text,image_url,status,created_at,sent_at"

# Backlog context prepended to every digest so each ticket stays aligned to the
# themes/epics. Verbatim from the founder brief (2026-07 dev-bugs collector).
_CTX = """You are my product-backlog triage assistant for WillpowerLab.
Turn each raw bug below into a context-rich, coding-agent-ready ticket. For EACH bug:
1) THEME FIT — check it against the themes/epics below. Name the Theme + Epic it fits. If it fits nothing, say "No clear fit" and suggest the closest epic (or propose a new one).
2) Write it as:
   - Epic: <one of the epics below, or a proposed one>
   - User story: As a <role>, I want <outcome>, so that <benefit>.
   - Task(s): concrete technical steps a coding agent can execute.
   - Type: Bug (unless it's really a Chore or Tech-debt — say so).
3) Priority: assign P1/P2/P3 with one line of reasoning.
Then OUTPUT the full list ordered MOST important → LEAST important, each ticket self-contained so I can paste it straight to my coding agent.

=== BACKLOG CONTEXT (keep every ticket aligned to this) ===
THEMES
T1 — People get fast human feedback on how they speak, for ~$5 each
T2 — Build the model-ready annotation asset (1,000 coach annotations)
T3 — Automate the coach's judgment (shadow model)
T4 — Trust, compliance & reliability

EPICS
1.1 The versioning engine works
1.2 Ideal-Text & Recording UX
1.3 Setup & Context Inputs
1.4 Onboarding
1.5 Arc Validation
2.1 Audio-only Annotation Mode
2.2 Annotation Labeling Schema
2.3 Coach Workflow Enhancements
2.4 Content Safety / Threat-Language Signal
2.5 Context-Generation Engine
3.1 Shadow Model — Breakthrough Detection
3.2 Progressive Shortening Intelligence
3.3 Simulation Depth
4.1 Legal & Consent (GDPR)
4.2 Measurement & Instrumentation
4.3 Release & Reliability"""


# ─────────────────────────── read / write ───────────────────────────

def _row_out(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a DB row for the API: expose image_url as `image`."""
    return {
        "id": row.get("id"),
        "text": row.get("text") or "",
        "image": row.get("image_url"),
        "status": row.get("status"),
        "created_at": row.get("created_at"),
        "sent_at": row.get("sent_at"),
    }


def list_bugs() -> dict[str, list[dict[str, Any]]]:
    """All bugs split into open (newest first) and shipped (newest sent first)."""
    res = (
        db.client.table(_TABLE)
        .select(_COLS)
        .order("created_at", desc=True)
        .execute()
    )
    rows = res.data or []
    open_bugs = [_row_out(r) for r in rows if r.get("status") == "open"]
    shipped = [_row_out(r) for r in rows if r.get("status") == "shipped"]
    return {"open": open_bugs, "shipped": shipped}


def create_bug(text: str, image: str | None) -> int:
    """Insert one bug. Raises ValueError if both text and image are empty."""
    text = (text or "").strip()
    image = image or None
    if not text and not image:
        raise ValueError("empty")
    res = (
        db.client.table(_TABLE)
        .insert({"text": text, "image_url": image})
        .execute()
    )
    row = res.data[0] if res.data else None
    if not row:
        raise RuntimeError("dev_bugs insert returned no row")
    return int(row["id"])


def delete_bug(bug_id: int) -> None:
    """Delete an OPEN bug. Shipped bugs are read-only history and are left alone."""
    db.client.table(_TABLE).delete().eq("id", bug_id).eq("status", "open").execute()


# ─────────────────────────── send digest ───────────────────────────

def _fmt_day(ts: Any) -> str:
    """'2026-07-16T..' -> '16 Jul' (en-GB day+month); best-effort."""
    if not ts:
        return "—"
    try:
        s = str(ts).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        return f"{dt.day} {dt.strftime('%b')}"
    except Exception:
        return str(ts)[:10]


_DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;,]+)?(?:;base64)?,(?P<payload>.*)$", re.DOTALL)
_MIME_EXT = {"image/jpeg": "jpg", "image/jpg": "jpg", "image/png": "png",
             "image/gif": "gif", "image/webp": "webp"}


def _attachment_for(bug: dict[str, Any]) -> dict[str, Any] | None:
    """Build a Resend attachment dict for a bug's image, or None.

    data: URL  -> decode base64 to bytes, pass as list[int] (Resend Python form).
    http(s) URL -> pass as `path`; Resend fetches it.
    """
    url = bug.get("image_url")
    if not url:
        return None
    bug_id = bug.get("id")
    if url.startswith("data:"):
        m = _DATA_URL_RE.match(url)
        if not m:
            return None
        mime = (m.group("mime") or "image/jpeg").strip() or "image/jpeg"
        try:
            raw = base64.b64decode(m.group("payload"), validate=False)
        except Exception:
            logger.warning("dev-bugs: could not decode image for bug %s", bug_id)
            return None
        ext = _MIME_EXT.get(mime, "jpg")
        return {
            "filename": f"bug-{bug_id}.{ext}",
            "content": list(raw),
            "content_type": mime,
        }
    if url.startswith("http://") or url.startswith("https://"):
        return {"filename": f"bug-{bug_id}.jpg", "path": url}
    return None


def _build_body(bugs: list[dict[str, Any]]) -> str:
    rng = f"{_fmt_day(bugs[0]['created_at'])} → {_fmt_day(bugs[-1]['created_at'])}" if bugs else "—"
    lines = []
    for i, b in enumerate(bugs, start=1):
        shot = "  (screenshot attached)" if b.get("image_url") else ""
        text = (b.get("text") or "").strip()
        lines.append(f"{i}. [{_fmt_day(b['created_at'])}] {text}{shot}")
    return f"{_CTX}\n\n=== BUGS (reported {rng}) ===\n" + "\n".join(lines)


def send_open_bugs() -> int:
    """Email all OPEN bugs to DEV_BUGS_TO, then mark them shipped.

    Returns the number of bugs sent. 0 open bugs is a no-op (no email).
    Raises RuntimeError if the email did not actually go out (e.g. SEND_EMAILS
    is false or the provider errored) so bugs are NOT marked shipped — the next
    run still has them.
    """
    res = (
        db.client.table(_TABLE)
        .select(_COLS)
        .eq("status", "open")
        .order("created_at", desc=False)
        .execute()
    )
    bugs = res.data or []
    if not bugs:
        return 0

    body = _build_body(bugs)
    html_body = (
        "<pre style=\"white-space:pre-wrap;word-break:break-word;"
        "font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;"
        "font-size:13px;line-height:1.5;\">" + _html_escape(body) + "</pre>"
    )
    attachments = [a for a in (_attachment_for(b) for b in bugs) if a]

    result = send_email_resend(
        to=config.DEV_BUGS_TO,
        subject="dev-bugs",
        html=html_body,
        text=body,
        attachments=attachments or None,
    )
    if not result.get("sent"):
        # SEND_EMAILS off, or provider returned non-sent. Do NOT mark shipped.
        raise RuntimeError(
            f"dev-bugs digest not sent (check SEND_EMAILS / RESEND_API_KEY): {result}"
        )

    ids = [b["id"] for b in bugs]
    db.client.table(_TABLE).update(
        {"status": "shipped", "sent_at": "now()"}
    ).in_("id", ids).execute()
    logger.info("dev-bugs: emailed %d bug(s) to %s and marked shipped", len(ids), config.DEV_BUGS_TO)
    return len(ids)
