"""willab beta — user_audit assembly (UX Wave 3 BE-3 / S5).

The "audit" is the USER-FACING word (kept by founder decision); internally
it's ``user_audit`` to stay distinct from the B2B Tab-5 audit product. It is
ASSEMBLED FROM EXISTING DATA — each take's canonical exact-evidence
FeedbackItems plus its optional coach summary. There is no new generator,
model call, score, or second positive-moments library.

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
    """Gather delivered take feedback into one chronological audit.

    This is a take history, not a second collection of positive moments.
    Read-only; never raises (degrades to empty sections).
    """
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
    sessions: list[dict] = []
    for s in sessions_raw:
        # Only DELIVERED sessions carry coach insights — drafts/unsent skipped.
        if not s.get("results_published_at"):
            continue
        ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
        notes = []
        try:
            from services.feedback_repository import FeedbackRepository
            for item in FeedbackRepository(db).surfaced_items(
                str(s.get("id") or ""), published_only=True,
            ):
                notes.append({
                    "note": item.message,
                    "tag": item.family.value,
                    "when": item.application_guidance or "",
                    "examples": list(item.examples),
                })
        except Exception as error:
            logger.warning(
                "assemble_user_audit: feedback read failed take=%s err=%s",
                s.get("id"), error,
            )
        sessions.append({
            "session_id": s.get("id"),
            "topic": (ctx or {}).get("topic") or "",
            "created_at": s.get("created_at"),
            "overall_message": s.get("coach_overall_message") or "",
            "notes": notes,
        })

    return {
        "user_id": user_id,
        "recorded_seconds": recorded,
        "threshold_seconds": AUDIT_UNLOCK_SECONDS,
        "unlocked": recorded >= AUDIT_UNLOCK_SECONDS,
        "sessions": sessions,
    }


def _esc(s: Any) -> str:
    return _html.escape(str(s or ""))


def audit_email_subject() -> str:
    # STABLE (no counts/dates) — required for per-user mailbox threading
    # (fix-pack BE-3c): same subject on every send groups the thread.
    return "Your WillpowerLab coaching audit"


def send_user_audit_email(user_id: str, *, to_email: str, audit: dict | None = None) -> dict:
    """Render and send the assembled take-feedback audit to the student, with
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
    def _items(rows: list[dict]) -> str:
        if not rows:
            return '<p style="color:#666;margin:4px 0;">Nothing here yet.</p>'
        out = []
        for r in rows:
            note = _esc(r.get("note"))
            family = _esc(str(r.get("tag") or "").replace("_", " ").title())
            label = f'<div style="color:#666;font-size:12px;">{family}</div>' if family else ""
            out.append(
                f'<li style="margin:0 0 10px;">{label}<div>{note}</div></li>'
            )
        return '<ul style="padding-left:18px;margin:6px 0;">' + "".join(out) + "</ul>"

    sections = []
    for session in audit.get("sessions") or []:
        if not isinstance(session, dict):
            continue
        topic = _esc(session.get("topic") or "Presentation")
        overall = _esc(session.get("overall_message"))
        summary = (
            f'<p style="color:#555;margin:4px 0 8px;">{overall}</p>'
            if overall else ""
        )
        sections.append(
            f'<h2 style="font-size:16px;margin:18px 0 4px;">{topic}</h2>'
            f'{summary}{_items(session.get("notes") or [])}'
        )
    session_html = "".join(sections) or (
        '<p style="color:#666;margin:4px 0;">No delivered coach feedback yet.</p>'
    )

    return (
        '<div style="font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;'
        'max-width:600px;margin:0 auto;color:#1a1a1a;">'
        '<h1 style="font-size:20px;margin:0 0 4px;">Your WillpowerLab audit</h1>'
        '<p style="color:#666;margin:0 0 20px;">Your delivered coach feedback, '
        'organized by presentation and take.</p>'
        f'{session_html}'
        '<p style="font-size:13px;color:#666;margin:24px 0 0;">Keep going — record again '
        'whenever you\'re ready.</p>'
        '<p style="font-size:13px;color:#666;margin:8px 0 0;">— Team WillpowerLab</p>'
        '</div>'
    )
