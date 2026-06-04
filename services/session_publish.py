"""Auto-publish flow for sessions that don't go through admin review.

Today the only caller is the coaching trial-recording flow — the
user re-records a 30s answer after the coaching chat and expects
feedback within minutes, not after an admin review. The admin
publish endpoint (``v2_internal_publish_session_results``) stays
as-is for the standard onboarding/path flow; this module is a
focused parallel that mirrors only the steps the trial flow needs.

What we mirror from the admin publish:
  1. Generate AI drafts for any extracted snippets that don't
     already have one — without these the admin_comment column
     would stay NULL and the user-facing /results page would
     filter out every card.
  2. Promote ai_draft_admin_comment → admin_comment so the
     snippets render.
  3. Flip ``status`` to "completed".
  4. Stamp ``results_published_at`` so the BFF queries surface
     the session.
  5. Compute + persist ``charisma_profile`` so the dashboard
     renders the radar/heatmap on first load.
  6. Send the standard PostSessionResultsEmail.

What we deliberately skip:
  - ``record_snippet_publish_annotations`` — no admin in the loop,
    so there's no (admin_final, ai_draft) pair to capture as an
    RLHF event. The auto-promoted draft IS the final; that's the
    signal we'd want to capture later anyway, but a dedicated
    event type (``auto_promoted``) is a separate piece of work.

Every step is best-effort: a failure logs + continues so the
user always reaches /results with something rather than getting
stuck on the coaching screen with no feedback.
"""
from __future__ import annotations

import logging
from typing import Any

from services.db import db


logger = logging.getLogger(__name__)


def finalize_session_pending_admin_review(
    session_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Hand a freshly-recorded non-onboarding session to the admin
    review queue.

    Called at the tail of every audio-bearing flow that ISN'T
    onboarding: coaching trial recordings, contextual chat
    recordings, future ad-hoc sessions. The shared "infinite loop"
    contract is that admin reviews every session before the user
    sees results — so we DON'T stamp ``results_published_at`` and
    we DON'T send the user-facing email. Instead:

      1. Compute global metrics + B6 KPI so the admin Pending
         Review surface has scores to render.
      2. Generate AI admin_comment drafts for any new snippet
         missing one (so the admin opens the row to a pre-filled
         suggestion they can keep, edit, or replace).
      3. Set status to "pending_admin_review" so the admin UI
         picks the session up (and so /user/results/<id>'s
         status derivation returns 'processing' until publish).
      4. Send the standard admin notification email so the admin
         knows there's something new to look at.

    Failure-isolated throughout: a missing draft or a flaky email
    never blocks the rest. Returns a structured dict the caller
    can log for observability.
    """
    result: dict[str, Any] = {
        "ok": False,
        "global_metrics_computed": False,
        "kpi_narrative_written": False,
        "predictions_generated": False,
        "drafts_generated": 0,
        "status_set": False,
        "admin_email_status": None,
        "snippet_count": 0,
    }

    # ── Step 1: global metrics + B6 KPI.
    try:
        from services.session_metrics import compute_session_global_metrics
        metrics = compute_session_global_metrics(session_id)
        result["global_metrics_computed"] = metrics is not None
    except Exception as e:
        logger.warning(
            "finalize_pending_review: global metrics compute failed "
            "sid=%s err=%s", session_id, e,
        )

    # ── Step 1.5: LLM-generated session_kpi_narrative.
    # Writes to v2_sessions.ai_task_alignment_comment so the
    # charisma_profile dashboard (which reads that column as its
    # top-level narrative) has a coach-toned paragraph to render
    # the moment the admin publishes. Best-effort — a missing
    # narrative falls back to the learner-mirror / spec line in
    # the dashboard's narrative builder.
    try:
        from services.session_kpi_narrative import (
            generate_session_kpi_narrative,
        )
        narrative = generate_session_kpi_narrative(session_id)
        result["kpi_narrative_written"] = bool(narrative)
    except Exception as e:
        logger.warning(
            "finalize_pending_review: kpi narrative compute failed "
            "sid=%s err=%s", session_id, e,
        )

    # ── Step 1.6: Pre-generate admin-facing session predictions.
    # Writes ai_predicted_session_comment + ai_predicted_next_question
    # on the session row so the admin opens the user-detail page
    # to a pre-filled draft they can accept or edit. The (predicted,
    # final) pair becomes one row in admin_annotations_log on
    # Publish. Best-effort; missing predictions just means the
    # admin types the comment from scratch like before.
    try:
        from services.session_predictions import (
            generate_session_predictions,
        )
        predictions = generate_session_predictions(session_id)
        result["predictions_generated"] = predictions is not None
    except Exception as e:
        logger.warning(
            "finalize_pending_review: predictions compute failed "
            "sid=%s err=%s", session_id, e,
        )

    # ── Step 1.7: next-session icebreaker — DORMANT (willab v1.2).
    # Generation un-wired in the Phase-5 clearance. The
    # next_session_icebreaker_* columns + admin read/regenerate
    # endpoints remain (inert) for a possible later Lounge
    # warm-opener, but nothing generates an icebreaker here anymore.
    result["icebreaker_generated"] = False

    # ── Step 2: pre-fill admin_comment drafts.
    try:
        drafts = _ensure_drafts(session_id)
        # _ensure_drafts logs internally; this counter is best-effort.
        result["drafts_generated"] = drafts if isinstance(drafts, int) else 0
    except Exception as e:
        logger.warning(
            "finalize_pending_review: draft generation failed sid=%s err=%s",
            session_id, e,
        )

    # Snapshot snippet count for downstream (admin email body, log).
    try:
        snippets = db.get_snippets_by_session(session_id) or []
        result["snippet_count"] = len(snippets)
    except Exception:
        pass

    # ── Step 3: status flip. The admin UI's Pending Review listing
    # keys on this string; the /user/results/<id> BFF derives
    # 'processing' from "results_published_at IS NULL" so the user
    # stays on the waiting screen regardless of the exact status.
    try:
        db.v2_update_session_status_unscoped(session_id, "pending_admin_review")
        result["status_set"] = True
    except Exception as e:
        logger.warning(
            "finalize_pending_review: status flip failed sid=%s err=%s",
            session_id, e,
        )

    # ── Step 4: admin notification email.
    result["admin_email_status"] = _send_admin_notification(
        session_id=session_id,
        user_id=user_id,
        snippet_count=result["snippet_count"],
    )

    result["ok"] = True
    return result


def auto_publish_trial_session(
    session_id: str,
    user_id: str,
) -> dict[str, Any]:
    """Run the full auto-publish + notify pipeline for a trial session.

    Returns a structured dict so the caller can log / surface what
    happened::

        {
          "ok":              bool,
          "step_failed":     str | None,   # first step that failed, if any
          "promoted_drafts": int,
          "published":       bool,
          "email_status":    str | None,   # 'sent' | 'skipped' | 'render_failed' | 'send_failed' | 'no_email'
          "snippet_count":   int,
          "skipped_reason":  str | None,   # e.g. 'no_snippets', 'no_owner', 'no_email'
        }
    """
    result: dict[str, Any] = {
        "ok": False,
        "step_failed": None,
        "promoted_drafts": 0,
        "published": False,
        "email_status": None,
        "admin_email_status": None,
        "learner_profile_recomputed": False,
        "global_metrics_computed": False,
        "snippet_count": 0,
        "skipped_reason": None,
    }

    # ── Step 0: Compute session-level global metrics + B6 KPI.
    # The charisma_profile builder reads session.global_wpm /
    # global_fillers / global_dynamic_db / kpi_score — without
    # these, the trinity inputs all degrade to neutral 0.5 and the
    # dashboard renders a flat radar. Running the aggregator here
    # (same one the admin compute-metrics endpoint uses) means the
    # trial finalize produces the same shape of dashboard the
    # onboarding finalize does.
    try:
        from services.session_metrics import compute_session_global_metrics
        metrics = compute_session_global_metrics(session_id)
        result["global_metrics_computed"] = metrics is not None
    except Exception as e:
        logger.warning(
            "auto_publish_trial: global metrics compute failed sid=%s err=%s",
            session_id, e,
        )

    # ── Step 0.5: LLM-generated session narrative.
    # Same rationale as finalize_session_pending_admin_review —
    # populates ai_task_alignment_comment so the charisma_profile
    # dashboard renders a real paragraph instead of the spec
    # fallback line. Best-effort; failure leaves the column empty.
    try:
        from services.session_kpi_narrative import (
            generate_session_kpi_narrative,
        )
        generate_session_kpi_narrative(session_id)
    except Exception as e:
        logger.warning(
            "auto_publish_trial: kpi narrative compute failed "
            "sid=%s err=%s", session_id, e,
        )

    # ── Step 0.6: next-session icebreaker — DORMANT (willab v1.2).
    # Generation un-wired in the Phase-5 clearance (see the Step 1.7
    # note in finalize_session_pending_admin_review).

    # ── Step 1: AI-draft generation for any missing drafts.
    # extract_recording_snippets runs upstream of us; depending on
    # how the recording-1 job is configured it may or may not have
    # already produced ai_draft_admin_comment. We call into the
    # generator for any snippet that has a transcript but no draft
    # so promotion below has something to copy.
    try:
        _ensure_drafts(session_id)
    except Exception as e:
        logger.warning(
            "auto_publish_trial: draft generation failed sid=%s err=%s",
            session_id, e,
        )

    # ── Step 2: Promote drafts → admin_comment.
    try:
        promoted = db.promote_ai_drafts_to_admin_comments(session_id)
        result["promoted_drafts"] = promoted
    except Exception as e:
        logger.warning(
            "auto_publish_trial: promote failed sid=%s err=%s",
            session_id, e,
        )

    # Count published-able snippets (admin_comment now populated).
    snippet_count = 0
    try:
        snippets = db.get_snippets_with_comments_by_session(session_id) or []
        snippet_count = len(snippets)
        result["snippet_count"] = snippet_count
    except Exception as e:
        logger.warning(
            "auto_publish_trial: snippet count failed sid=%s err=%s",
            session_id, e,
        )

    if snippet_count == 0:
        # No commented snippets means the /results page would render
        # an empty journey card. Don't email the user in that case —
        # they'd open the email and find nothing. The session row
        # still exists; admin can revisit it manually.
        result["step_failed"] = "no_snippets"
        result["skipped_reason"] = "no_snippets"
        logger.info(
            "auto_publish_trial: no commented snippets, skipping publish "
            "sid=%s", session_id,
        )
        return result

    # ── Step 3: Flip session status to completed.
    try:
        db.v2_update_session_status_unscoped(session_id, "completed")
    except Exception as e:
        logger.warning(
            "auto_publish_trial: status flip failed sid=%s err=%s",
            session_id, e,
        )

    # ── Step 4: Stamp results_published_at (the gate the BFF
    # queries filter on).
    try:
        published = db.v2_publish_session_results(session_id)
        result["published"] = bool(published)
    except Exception as e:
        logger.warning(
            "auto_publish_trial: results_published_at stamp failed sid=%s err=%s",
            session_id, e,
        )

    # ── Step 5: Compute + persist charisma profile.
    try:
        from services.charisma_profile import (
            compute_and_persist_charisma_profile,
        )
        compute_and_persist_charisma_profile(
            session_id=session_id, user_id=str(user_id),
        )
    except Exception as e:
        logger.warning(
            "auto_publish_trial: charisma profile compute failed "
            "sid=%s err=%s", session_id, e,
        )

    # ── Step 6: Look up email + name, then send the standard
    # PostSessionResultsEmail. We resolve email from Supabase auth
    # exactly the way the admin publish endpoint does so failure
    # modes (no email, unsubscribed) get the same treatment.
    email_status, skipped_reason = _send_results_email(
        session_id=session_id,
        user_id=user_id,
        snippet_count=snippet_count,
    )
    result["email_status"] = email_status
    if skipped_reason and not result["skipped_reason"]:
        result["skipped_reason"] = skipped_reason

    # ── Step 7: Recompute the inferred learner profile.
    # Coaching-attempt writes already trigger this (see
    # coaching_outcomes._recompute_learner_profile), but coaching
    # trials don't always produce an attempt row — the user's
    # 30s re-performance can land entirely on the v2_session path.
    # Folding the recompute in here means the user's longitudinal
    # context updates after every finalized session, whatever path
    # produced it. Best-effort: a missing/empty profile is logged
    # and ignored.
    try:
        _recompute_learner_profile_for_user(user_id)
        result["learner_profile_recomputed"] = True
    except Exception as e:
        logger.warning(
            "auto_publish_trial: learner profile recompute failed "
            "uid=%s err=%s", user_id, e,
        )

    # ── Step 8: Admin notification email.
    # Mirrors the homework-complete admin notification — the coach
    # / admin gets a heads-up that a new session is ready to
    # review. Gated by SEND_EMAILS + ADMIN_EMAIL like every other
    # admin notification path; no-op when either is unset so dev
    # environments don't spam.
    admin_email_status = _send_admin_notification(
        session_id=session_id,
        user_id=user_id,
        snippet_count=snippet_count,
    )
    result["admin_email_status"] = admin_email_status

    result["ok"] = True
    return result


# ── Internals ──────────────────────────────────────────────────────


def _ensure_drafts(session_id: str) -> None:
    """For every snippet in the session that has a transcript but no
    ai_draft_admin_comment, fire the existing draft generator.

    No-op for snippets that already have a draft. Bounded by the
    number of snippets in the session (typically 1-5 for a trial).
    """
    try:
        rows = (
            db.client.table("charisma_snippets")
            .select("id, transcript, ai_draft_admin_comment")
            .eq("session_id", session_id)
            .execute()
            .data
            or []
        )
    except Exception as e:
        logger.warning(
            "auto_publish_trial: snippet listing for drafts failed "
            "sid=%s err=%s", session_id, e,
        )
        return

    from services.snippet_drafts import generate_charisma_draft_for_snippet

    for row in rows:
        if (row.get("ai_draft_admin_comment") or "").strip():
            continue
        if not (row.get("transcript") or "").strip():
            continue
        try:
            generate_charisma_draft_for_snippet(row["id"])
        except Exception as e:
            # Per-snippet failure is non-fatal — we'll just skip that
            # snippet on the promotion step.
            logger.warning(
                "auto_publish_trial: draft gen failed sn=%s err=%s",
                row["id"], e,
            )


def _send_results_email(
    *,
    session_id: str,
    user_id: str,
    snippet_count: int,
) -> tuple[str, str | None]:
    """Resolve user + send the standard results email.

    Returns (status, skipped_reason). status is one of:
        'sent', 'skipped', 'render_failed', 'send_failed', 'no_email'.
    skipped_reason is the unsubscribe / error code from the email
    service when status != 'sent', or 'no_email' when the auth
    lookup didn't yield an address.
    """
    user_email = _fetch_user_email(user_id)
    if not user_email:
        return "no_email", "no_email"

    first_name: str | None = None
    try:
        details = db.v2_get_student_details(user_id) or {}
        full_name = (details.get("name") or "").strip()
        if full_name:
            first_name = full_name.split()[0]
    except Exception as e:
        logger.warning(
            "auto_publish_trial: name lookup failed uid=%s err=%s",
            user_id, e,
        )

    top_theme: str | None = None
    try:
        sess = db.v2_get_session_by_id(session_id) or {}
        top_theme = (sess.get("stickiness_top_topic") or "").strip() or None
    except Exception:
        pass

    try:
        from services.post_session_results_email import (
            send_publish_results_email,
        )
        send_result = send_publish_results_email(
            user_id=str(user_id),
            user_email=user_email,
            user_first_name=first_name,
            snippet_count=snippet_count,
            top_theme=top_theme,
            session_id=session_id,
        )
        status = send_result.get("status") or "unknown"
        reason = send_result.get("reason") or send_result.get("error")
        return status, (reason if status != "sent" else None)
    except Exception as e:
        logger.warning(
            "auto_publish_trial: email send failed sid=%s err=%s",
            session_id, e,
        )
        return "send_failed", str(e)


def _recompute_learner_profile_for_user(user_id: str) -> None:
    """Refresh ``inferred_learner_profile`` from the user's recent
    coaching attempts.

    Mirrors ``coaching_outcomes._recompute_learner_profile`` —
    duplicated rather than imported to avoid pulling the
    coaching_outcomes module just for one helper. The compute is
    deterministic, cheap, and idempotent: writing None when the
    user has no analysable attempts clears any stale blob.
    """
    from services.learner_profile import (
        ATTEMPTS_WINDOW,
        compute_learner_profile,
    )
    attempts = db.list_recent_coaching_attempts_for_user(
        user_id, limit=ATTEMPTS_WINDOW,
    )
    profile = compute_learner_profile(attempts)
    db.set_user_inferred_learner_profile(user_id, profile)


def _send_admin_notification(
    *,
    session_id: str,
    user_id: str,
    snippet_count: int,
) -> str:
    """Email the coach/admin that a session was auto-published.

    Reuses ``email_service.send_lesson_complete_to_admin`` — same
    template as the homework-complete notification — so admins
    see a consistent "student finished a thing, click to review"
    signal regardless of which session type produced it.

    Returns the result.status from the email service ('sent',
    'pending', 'failed') or 'skipped' when we couldn't resolve
    the student's email (we don't block on that — the admin
    notification is informational, not transactional).
    """
    try:
        from services.email_service import email_service

        student_email = _fetch_user_email(user_id)
        student_name = ""
        try:
            details = db.v2_get_student_details(user_id) or {}
            student_name = (details.get("name") or "").strip()
        except Exception:
            pass

        report_preview = ""
        try:
            sess = db.v2_get_session_by_id(session_id) or {}
            report_preview = (sess.get("ai_task_alignment_comment") or "").strip()
            score_raw = sess.get("kpi_score")
        except Exception:
            score_raw = None
        # KPI on the row is 0..100; the admin helper expects 0..1.
        score = None
        if isinstance(score_raw, (int, float)):
            score = float(score_raw) / 100.0

        send_result = email_service.send_lesson_complete_to_admin(
            user_id=str(user_id),
            session_id=session_id,
            report_preview=report_preview,
            student_email=student_email,
            score=score,
            student_name=student_name,
        )
        status = (send_result or {}).get("status") or "unknown"
        logger.info(
            "auto_publish_trial: admin notification sid=%s status=%s snippets=%d",
            session_id, status, snippet_count,
        )
        return status
    except Exception as e:
        logger.warning(
            "auto_publish_trial: admin notification failed sid=%s err=%s",
            session_id, e,
        )
        return "failed"


def _fetch_user_email(user_id: str) -> str | None:
    """Pull the user's email from Supabase auth. Returns None on any
    failure — caller decides whether that's fatal."""
    try:
        import httpx
        from config import Config
        headers = {
            "Authorization": f"Bearer {Config.SUPABASE_SERVICE_ROLE_KEY}",
            "apikey": Config.SUPABASE_SERVICE_ROLE_KEY,
        }
        url = (
            f"{Config.SUPABASE_URL.rstrip('/')}"
            f"/auth/v1/admin/users/{user_id}"
        )
        resp = httpx.get(url, headers=headers, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json() or {}
        email = (data.get("email") or "").strip()
        return email or None
    except Exception as e:
        logger.warning(
            "auto_publish_trial: auth fetch failed uid=%s err=%s",
            user_id, e,
        )
        return None
