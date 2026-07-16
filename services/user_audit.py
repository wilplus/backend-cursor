"""willab beta — user_audit assembly (UX Wave 3 BE-3 / S5).

The "audit" is the USER-FACING word (kept by founder decision); internally
it's ``user_audit`` to stay distinct from the B2B Tab-5 audit product. It is
ASSEMBLED FROM EXISTING DATA — the coach's per-session insights
(v2_sessions.insights_payload) + the user's strong_sides_library. There is
NO new generator, no model call, no new score: it just gathers what a human
coach already wrote into one historical document — the user's strong sides
and the moments to work on.

Availability follows the recording-progress unlock (>= AUDIT_UNLOCK_SECONDS
cumulative recorded seconds, S2). The coach panel downloads it (structured)
and can manually trigger an email of it to the user.

Pure-ish: only touches services.db (lazy import), so it unit-tests with a
db stub. No PII is added beyond what the coach authored.
"""
from __future__ import annotations

import html as _html
import logging
from typing import Any

logger = logging.getLogger(__name__)

# 10 minutes cumulative recording unlocks the first audit (S2 threshold).
AUDIT_UNLOCK_SECONDS = 600


def assemble_user_audit(user_id: str) -> dict:
    """Gather the user's delivered insights + library into one structured
    audit. Read-only; never raises (degrades to empty sections)."""
    from services.db import db

    recorded = 0
    try:
        recorded = int(db.v2_get_cumulative_recorded_seconds(user_id) or 0)
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("assemble_user_audit: recorded-secs failed user=%s err=%s", user_id, e)

    try:
        sessions_raw = db.v2_list_user_lab_sessions(user_id) or []
    except Exception:
        sessions_raw = []
    try:
        library = db.get_strong_sides_library(user_id) or []
    except Exception:
        library = []

    sessions: list[dict] = []
    for s in sessions_raw:
        # Only DELIVERED sessions carry coach insights — drafts/unsent skipped.
        if not s.get("results_published_at"):
            continue
        ip = s.get("insights_payload") if isinstance(s.get("insights_payload"), dict) else {}
        ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
        notes = []
        for n in (ip.get("snippet_notes") or []):
            if not isinstance(n, dict):
                continue
            notes.append({
                "note": n.get("note") or "",
                "tag": n.get("tag"),
                "when": n.get("when") or n.get("when_context") or "",
                "examples": [e for e in (n.get("examples") or []) if isinstance(e, str)],
            })
        sessions.append({
            "session_id": s.get("id"),
            "topic": (ctx or {}).get("topic") or "",
            "created_at": s.get("created_at"),
            "overall_message": (ip or {}).get("overall_message") or "",
            "notes": notes,
        })

    strong_sides: list[dict] = []
    for e in library:
        if not isinstance(e, dict):
            continue
        ref = e.get("snippet_ref") if isinstance(e.get("snippet_ref"), dict) else {}
        strong_sides.append({
            "note": e.get("note") or "",
            "tag": e.get("tag"),
            "transcript": (ref or {}).get("transcript") or "",
            "session_id": e.get("session_id"),
            "created_at": e.get("created_at"),
        })

    return {
        "user_id": user_id,
        "recorded_seconds": recorded,
        "threshold_seconds": AUDIT_UNLOCK_SECONDS,
        "unlocked": recorded >= AUDIT_UNLOCK_SECONDS,
        "sessions": sessions,
        "strong_sides": strong_sides,
    }


def _esc(s: Any) -> str:
    return _html.escape(str(s or ""))


def audit_email_subject() -> str:
    # STABLE (no counts/dates) — required for per-user mailbox threading
    # (fix-pack BE-3c): same subject on every send groups the thread.
    return "Your WillpowerLab audit — your strong sides so far"


def send_user_audit_email(user_id: str, *, to_email: str, audit: dict | None = None) -> dict:
    """Render + send the assembled strong-sides audit to the student, with
    the per-user threading headers (fix-pack BE-3c) so repeat audits stack
    into the SAME mail-client conversation as the other coach→user mails.

    Raises on send failure (same contract as ``send_email_resend``) — the
    coach route catches and maps to a 500.

    NOTE: the coach trigger route (``/v2/coach/students/<id>/audit/send``
    in routes/v2_routes.py) still inlines subject+html+send WITHOUT the
    threading headers; v2_routes.py is frozen during the BE-3a PR, so
    switching that call site to this helper is a one-line follow-up once
    that PR lands.
    """
    from services.email_service import send_email_resend
    from services.email_threading import user_thread_headers

    if audit is None:
        audit = assemble_user_audit(user_id)
    return send_email_resend(
        to=to_email,
        subject=audit_email_subject(),
        html=render_user_audit_html(audit),
        headers=user_thread_headers(user_id) or None,
    )


def render_user_audit_html(audit: dict) -> str:
    """Minimal branded HTML for the manual coach send. Functional, not the
    F-2 main-page redesign (that's FE-owned per Flag 2); safe to restyle
    later without touching the assembly."""
    strong = [s for s in (audit.get("strong_sides") or []) if (s.get("tag") == "strong")]
    work = [s for s in (audit.get("strong_sides") or []) if (s.get("tag") == "to_work_on")]

    def _items(rows: list[dict]) -> str:
        if not rows:
            return '<p style="color:#666;margin:4px 0;">Nothing here yet.</p>'
        out = []
        for r in rows:
            note = _esc(r.get("note"))
            tx = _esc(r.get("transcript"))
            quote = f'<div style="color:#555;font-style:italic;margin:2px 0 0;">“{tx}”</div>' if tx else ""
            out.append(
                f'<li style="margin:0 0 10px;"><div>{note}</div>{quote}</li>'
            )
        return '<ul style="padding-left:18px;margin:6px 0;">' + "".join(out) + "</ul>"

    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:600px;margin:0 auto;color:#1a1a1a;">'
        '<h1 style="font-size:20px;margin:0 0 4px;">Your WillpowerLab audit</h1>'
        '<p style="color:#666;margin:0 0 20px;">The first historical document of your '
        'journey as a public speaker — your strong sides and the moments to work on, '
        'gathered from your coach\'s notes.</p>'
        '<h2 style="font-size:16px;margin:18px 0 4px;">Your strong sides</h2>'
        f'{_items(strong)}'
        '<h2 style="font-size:16px;margin:18px 0 4px;">Moments to work on</h2>'
        f'{_items(work)}'
        '<p style="font-size:13px;color:#666;margin:24px 0 0;">Keep going — record again '
        'whenever you\'re ready.</p>'
        '<p style="font-size:13px;color:#666;margin:8px 0 0;">— Team WillpowerLab</p>'
        '</div>'
    )
