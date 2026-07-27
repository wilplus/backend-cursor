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
_COLS = "id,text,image_url,images,status,created_at,sent_at"

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

def _bug_images(row: dict[str, Any]) -> list[str]:
    """The bug's images as a list — the new `images` array, else the legacy single
    `image_url`/`image` (rows created before multi-image). Drops falsy entries."""
    imgs = row.get("images")
    if isinstance(imgs, list) and imgs:
        return [x for x in imgs if x]
    single = row.get("image_url") or row.get("image")
    return [single] if single else []


def _row_out(row: dict[str, Any]) -> dict[str, Any]:
    """Shape a DB row for the API: `images` list + `image` (first, legacy)."""
    imgs = _bug_images(row)
    return {
        "id": row.get("id"),
        "text": row.get("text") or "",
        "image": imgs[0] if imgs else None,
        "images": imgs,
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


def create_bug(text: str, images: list[str] | None) -> int:
    """Insert one bug (text + zero or more images). Raises ValueError if both the
    text and the image list are empty. `image_url` is set to the first image for
    backward-compat with old single-image consumers."""
    text = (text or "").strip()
    imgs = [x for x in (images or []) if x]
    if not text and not imgs:
        raise ValueError("empty")
    res = (
        db.client.table(_TABLE)
        .insert({"text": text, "images": imgs, "image_url": imgs[0] if imgs else None})
        .execute()
    )
    row = res.data[0] if res.data else None
    if not row:
        raise RuntimeError("dev_bugs insert returned no row")
    return int(row["id"])


def delete_bug(bug_id: int) -> None:
    """Delete an OPEN bug. Shipped bugs are read-only history and are left alone."""
    db.client.table(_TABLE).delete().eq("id", bug_id).eq("status", "open").execute()


def update_bug(bug_id: int, text: str | None = None) -> dict | None:
    """Edit an OPEN bug's text. Shipped bugs are read-only. Returns the updated row
    (API shape) or None if no open bug matched / nothing to change. Does NOT
    regenerate the bug's task — edit the task in the tasks view for that."""
    if text is None:
        return None
    res = (
        db.client.table(_TABLE)
        .update({"text": text.strip()})
        .eq("id", bug_id)
        .eq("status", "open")
        .execute()
    )
    return _row_out(res.data[0]) if res.data else None


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


def _one_attachment(bug_id: Any, idx: int, url: str) -> dict[str, Any] | None:
    """One Resend attachment for a single image URL, or None.

    data: URL  -> decode base64 to bytes, pass as list[int] (Resend Python form).
    http(s) URL -> pass as `path`; Resend fetches it.
    """
    if not url:
        return None
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
            "filename": f"bug-{bug_id}-{idx}.{ext}",
            "content": list(raw),
            "content_type": mime,
        }
    if url.startswith("http://") or url.startswith("https://"):
        return {"filename": f"bug-{bug_id}-{idx}.jpg", "path": url}
    return None


def _image_parts(bug: dict[str, Any]) -> list[dict[str, Any]]:
    """One entry per usable image: {"src", "filename", "attachment"}.

    Single source of truth so the HTML digest and the attachment list can never
    drift — the whole point is that a screenshot renders UNDER the bug it belongs
    to. Inlining goes via `cid:` rather than a data: URI because Gmail (and most
    clients) strip data: URIs in <img>; a cid reference to an attachment is the
    only route that actually displays.
    """
    bug_id = bug.get("id")
    parts: list[dict[str, Any]] = []
    for i, url in enumerate(_bug_images(bug)):
        att = _one_attachment(bug_id, i, url)
        if not att:
            continue
        filename = att["filename"]
        if "content" in att:
            att = {**att, "content_id": filename}
            src = f"cid:{filename}"
        else:
            src = att.get("path")          # http(s)-hosted: reference it directly
        parts.append({"src": src, "filename": filename, "attachment": att})
    return parts


def _attachments_for(bug: dict[str, Any]) -> list[dict[str, Any]]:
    """All Resend attachments for a bug's images (0..N)."""
    return [p["attachment"] for p in _image_parts(bug)]


def _build_html(bugs: list[dict[str, Any]]) -> str:
    """Rich digest: one card per bug, its screenshots inline beneath it.

    The triage prompt stays verbatim in a monospace block (it's an instruction for
    the LLM, not prose). Each screenshot is captioned with its bug number and
    attachment filename, so even in a client that blocks inline images you can still
    tell which attachment belongs to which bug.
    """
    rng = f"{_fmt_day(bugs[0]['created_at'])} → {_fmt_day(bugs[-1]['created_at'])}" if bugs else "—"
    sans = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif")
    out = [
        f'<div style="font-family:{sans};color:#111214;line-height:1.5;'
        'max-width:680px;margin:0 auto;padding:4px;">',
        '<pre style="white-space:pre-wrap;word-break:break-word;'
        'font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;'
        'font-size:12px;line-height:1.5;color:#374151;background:#f5f5f7;'
        'border-radius:10px;padding:12px;margin:0 0 18px;">'
        + _html_escape(_CTX) + '</pre>',
        f'<div style="font-size:13px;font-weight:700;letter-spacing:.02em;'
        f'color:#6b7280;margin:0 0 10px;">BUGS (reported {_html_escape(rng)})</div>',
    ]
    for i, b in enumerate(bugs, start=1):
        text = _html_escape((b.get("text") or "").strip())
        out.append(
            '<div style="border:1px solid #e6e7ea;border-radius:12px;'
            'padding:14px 16px;margin:0 0 14px;">'
            f'<div style="font-size:11px;color:#9aa0aa;">{i}. '
            f'{_html_escape(_fmt_day(b["created_at"]))} · bug #{_html_escape(str(b.get("id")))}</div>'
            f'<div style="font-size:15px;margin-top:6px;white-space:pre-wrap;'
            f'word-break:break-word;">{text}</div>'
        )
        for n, p in enumerate(_image_parts(b), start=1):
            out.append(
                '<div style="margin-top:12px;">'
                f'<img src="{_html_escape(p["src"] or "")}" '
                f'alt="screenshot {n} of bug {b.get("id")}" '
                'style="max-width:100%;height:auto;border:1px solid #e6e7ea;'
                'border-radius:8px;display:block;">'
                '<div style="font-size:11px;color:#9aa0aa;margin-top:4px;">'
                f'screenshot {n} · bug #{_html_escape(str(b.get("id")))} · '
                f'{_html_escape(p["filename"])}</div>'
                '</div>'
            )
        out.append('</div>')
    out.append('</div>')
    return "".join(out)


def _build_body(bugs: list[dict[str, Any]]) -> str:
    rng = f"{_fmt_day(bugs[0]['created_at'])} → {_fmt_day(bugs[-1]['created_at'])}" if bugs else "—"
    lines = []
    for i, b in enumerate(bugs, start=1):
        n = len(_bug_images(b))
        shot = "" if n == 0 else ("  (screenshot attached)" if n == 1 else f"  ({n} screenshots attached)")
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
    html_body = _build_html(bugs)
    attachments = [a for b in bugs for a in _attachments_for(b)]

    def _send(atts):
        return send_email_resend(
            to=config.DEV_BUGS_TO,
            subject="dev-bugs",
            html=html_body,
            text=body,
            attachments=atts or None,
        )

    try:
        result = _send(attachments)
    except Exception:  # noqa: BLE001
        # `content_id` (the inline cid: route) is newer than the pinned Resend SDK
        # and only rides through because params are posted verbatim. If the provider
        # ever rejects it, retry once as plain attachments so the digest STILL goes
        # out — the per-bug captions name each file, so the mapping survives.
        logger.warning("dev-bugs: inline-image send failed, retrying as plain attachments",
                       exc_info=True)
        result = _send([{k: v for k, v in a.items() if k != "content_id"} for a in attachments])
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
