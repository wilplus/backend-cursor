"""
Complete a homework session using only recording 1 (no post-recording questions, no recording 2).
The current web client path is recording_1 -> self-rating -> report.
Legacy `post_questions` handling remains only as a compatibility fallback for older sessions.
"""
import json
import logging
import time
from datetime import datetime, timezone

from config import Config
from services.db import db
from services.openai_service import openai_service
from services.email_service import email_service
from services.metrics_v2 import compute_metrics_v2
from services.utils import utc_now_iso

logger = logging.getLogger(__name__)
config = Config()

STATUS_COMPLETED = "completed"

COACH_FEEDBACK_MESSAGE = (
    "Your coach has 24 hours to analyse your homework and send a feedback on your email!"
)

MINIMAL_REPORT_FALLBACK = (
    "**Report**\n\nHomework recording was submitted. Full report could not be generated. "
    "Your coach has 24 hours to review and send you feedback."
)


def _normalize_email(value) -> str:
    email = (str(value).strip() if value is not None else "")
    return email.lower() if "@" in email else ""


def _resolve_student_email(preferred_email: str | None, user_id: str, *, context: str = "") -> str:
    """Return the best available student email, logging a warning on mismatch."""
    token_email = _normalize_email(preferred_email)
    auth_email = _normalize_email(db.get_user_email_from_auth(user_id))
    if token_email and auth_email and token_email != auth_email:
        logger.warning(
            "Email mismatch%s user_id=%s token_email=%s auth_email=%s",
            f" on {context}" if context else "",
            user_id,
            token_email,
            auth_email,
        )
    return token_email or auth_email


def _resolve_student_name(user_id: str, student_email: str) -> str:
    """Return the user's full display name from auth metadata, falling back to the
    part of the email before the @, or an empty string."""
    try:
        user = db.get_user_by_id(user_id)
        raw_meta = (user or {}).get("user_metadata") or {}
        name = (raw_meta.get("full_name") or raw_meta.get("name") or "").strip()
        if name:
            return name
    except Exception:
        pass
    if student_email and "@" in student_email:
        return student_email.split("@")[0]
    return ""


def _session_report_text(session: dict) -> str:
    """Return the first non-empty report text found in the session row."""
    for key in ("report_text", "report_preview", "report"):
        val = (session.get(key) or "").strip()
        if val:
            return val
    return ""


def _first_n_sentences(text: str, n: int = 2) -> str:
    import re
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:n])


def _build_session_report(
    transcript: str,
    wpm: float,
    filler_count: int,
    metrics: dict,
) -> str:
    """Build a report for any recording: excerpt, metrics, and coach message."""
    lines = []
    lines.append("**Your recording**")
    lines.append("")
    excerpt = _first_n_sentences(transcript, 2)
    lines.append(excerpt or "(No transcript available.)")
    lines.append("")
    lines.append("**Metrics**")
    pace = metrics.get("pace", {})
    lines.append(f"- Pace: {wpm:.0f} words per minute" + (f" — {pace.get('explanation', '')}" if pace.get("explanation") else ""))
    fillers = metrics.get("fillers", {})
    lines.append(f"- Filler words: {filler_count}" + (f" — {fillers.get('explanation', '')}" if fillers.get("explanation") else ""))
    strength = metrics.get("strength", {})
    strength_expl = strength.get("explanation") or (f"Loudness {strength.get('raw')}" if strength.get("raw") is not None else "Loudness (pending)")
    lines.append(f"- Strength: {strength_expl}")
    lines.append("")
    lines.append(COACH_FEEDBACK_MESSAGE)
    return "\n".join(lines)


def _compute_recording_metrics(recording: dict) -> tuple[str, float, int, dict, dict]:
    """Extract transcript/wpm/filler/metrics from a recording row. Returns (transcript, wpm, filler_count, filler_data, final)."""
    transcript = recording.get("transcription_text") or ""
    wpm = float(recording.get("words_per_minute") or 0)
    filler_data = recording.get("filler_words_count") or {}
    filler_count = int(filler_data.get("total", 0)) if isinstance(filler_data, dict) else 0
    strength_raw = None
    if isinstance(recording.get("performance_metrics_v2"), dict):
        strength_raw = recording["performance_metrics_v2"].get("strength", {}).get("raw")
    metric_defs = db.v2_get_metric_definitions()
    final = compute_metrics_v2(
        wpm=wpm,
        strength_raw=strength_raw,
        filler_count=filler_count,
        emotion_achieved=False,
        transcript=transcript,
        keywords=[],
        metric_definitions=metric_defs,
    )
    return transcript, wpm, filler_count, filler_data, final


def _persist_recording_metrics(recording_id: str, recording: dict, final: dict) -> None:
    """Merge new metrics with any existing scoring_debug and update the recording row."""
    existing = recording.get("performance_metrics_v2") if isinstance(recording.get("performance_metrics_v2"), dict) else {}
    scoring_debug = existing.get("scoring_debug") if isinstance(existing, dict) else None
    merged = dict(final["metrics"])
    if isinstance(scoring_debug, dict):
        merged["scoring_debug"] = scoring_debug
    db.update_recording(recording_id, {
        "performance_score_v2": final["performance_score"],
        "performance_metrics_v2": merged,
        "metric_labels_snapshot_v2": final["metric_labels_snapshot"],
    })


def _compute_performance_score_end(session: dict, session_id: str, base_score_key: str, filler_count: int) -> float:
    """Clamp performance score; prefer Sniper stage score when available; penalise filler words."""
    performance_score_end = max(0.0, min(1.0, float(session.get(base_score_key) or 0)))
    try:
        sniper = db.get_session_sniper_metrics(session_id)
        if sniper and sniper.get("stage_score") is not None:
            raw = float(sniper["stage_score"])
            performance_score_end = max(0.0, min(1.0, raw / 100.0 if raw > 1.0 else raw))
    except Exception as sniper_err:
        logger.debug("No sniper metrics for session %s: %s", session_id, sniper_err)
    if int(filler_count) > 0 and performance_score_end >= 1.0:
        performance_score_end = 0.99
    return performance_score_end


def _run_optional_enrichment(
    session: dict,
    session_id: str,
    user_id: str,
    transcript: str,
    filler_count: int,
    filler_data: dict,
    performance_score_end: float,
) -> tuple[str, dict, dict, dict]:
    """Run coach insight + custom question analysis (non-blocking). Returns (coach_insight, r1, r2, r3)."""
    coach_insight = ""
    try:
        context_short = (session.get("context_short") or "").strip()
        filler_breakdown = dict(filler_data.get("breakdown", {})) if isinstance(filler_data, dict) else {}
        transcript_excerpt = (transcript or "")[:300]
        history_scores = []
        try:
            history_rows = db.v2_get_performance_history(user_id, limit=3)
            history_scores = [float(r.get("performance_score_end") or 0) for r in (history_rows or [])]
        except Exception as hist_err:
            logger.debug("Coach insight history unavailable session_id=%s: %s", session_id, hist_err)
        speaker_profile_context = ""
        try:
            speaker_profile = db.v2_get_speaker_profile(user_id) or {}
            speaker_profile_context = (speaker_profile.get("coach_notes") or "").strip()
        except Exception:
            pass
        session_sniper = {}
        try:
            session_sniper = db.get_session_sniper_metrics(session_id) or {}
        except Exception:
            pass
        self_rating_1_10 = session_sniper.get("student_rating_1_10")
        live_ball_score_100 = None
        stage_raw = session_sniper.get("stage_score")
        if stage_raw is not None:
            try:
                stage_raw_f = float(stage_raw)
                live_ball_score_100 = round(stage_raw_f if stage_raw_f > 1 else stage_raw_f * 100)
            except (TypeError, ValueError):
                pass
        try:
            self_rating_1_10 = int(self_rating_1_10) if self_rating_1_10 is not None else None
        except (TypeError, ValueError):
            self_rating_1_10 = None
        coach_insight = openai_service.generate_coach_insight(
            context_short=context_short,
            transcript_excerpt=transcript_excerpt,
            filler_breakdown=filler_breakdown,
            filler_count=filler_count,
            performance_score=performance_score_end,
            performance_history_scores=history_scores,
            speaker_profile_context=speaker_profile_context,
            self_rating_1_10=self_rating_1_10,
            live_ball_score_100=live_ball_score_100,
        )
        db.v2_update_session(session_id, user_id, {"coach_insight": coach_insight or None})
    except Exception as ci_err:
        logger.warning("Coach insight generation failed: %s", ci_err)

    r1 = r2 = r3 = {"analysis": "", "score": 0}
    q1 = (session.get("session_metric_question_1") or "").strip()
    q2 = (session.get("session_metric_question_2") or "").strip()
    q3 = (session.get("session_metric_question_3") or "").strip()
    if q1 or q2 or q3:
        try:
            custom_results = openai_service.analyze_custom_questions(transcript, [q1, q2, q3])
            r1, r2, r3 = (custom_results + [{"analysis": "", "score": 0}] * 3)[:3]
        except Exception as cq_err:
            logger.warning("Custom questions analysis failed: %s", cq_err)

    db.v2_update_session(session_id, user_id, {
        "question_1_analysis": r1.get("analysis") or "",
        "question_1_score": float(r1.get("score", 0)),
        "question_2_analysis": r2.get("analysis") or "",
        "question_2_score": float(r2.get("score", 0)),
        "question_3_analysis": r3.get("analysis") or "",
        "question_3_score": float(r3.get("score", 0)),
        "coach_insight": coach_insight or None,
    })
    return coach_insight, r1, r2, r3


def _complete_session_from_recording(
    session: dict,
    session_id: str,
    user_id: str,
    recording_id: str,
    base_score_key: str,
    preferred_student_email: str | None,
    recording_count: int,
) -> dict:
    """
    Shared completion core: compute metrics, build report, mark session completed,
    send coach email, run optional enrichment. Used by both recording-1 and recording-2 paths.
    Returns the result dict.
    """
    recording = db.get_recording(recording_id, user_id)
    if not recording:
        logger.warning("_complete_session_from_recording: recording not found recording_id=%s", recording_id)
        return None

    transcript, wpm, filler_count, filler_data, final = _compute_recording_metrics(recording)
    _persist_recording_metrics(recording_id, recording, final)

    performance_score_end = _compute_performance_score_end(session, session_id, base_score_key, filler_count)
    report_text = _build_session_report(transcript=transcript, wpm=wpm, filler_count=filler_count, metrics=final["metrics"])

    try:
        db.v2_append_context_long_entry(session_id, user_id, report_text)
    except Exception as ctx_err:
        logger.warning("_complete_session_from_recording: context_long append failed (non-blocking): %s", ctx_err)
    primary_recording_id = recording_id if recording_count == 1 else (recording_id or session.get("recording_1_id"))
    report_row = db.v2_create_report(session_id, primary_recording_id, report_text)

    completed_at_iso = utc_now_iso()
    post_answers = session.get("post_answers") if isinstance(session.get("post_answers"), list) else []

    db.v2_update_session(session_id, user_id, {
        "post_answers": post_answers,
        "report_id": report_row["id"] if report_row else None,
        "performance_score_end": performance_score_end,
        "status": STATUS_COMPLETED,
        "completed_at": completed_at_iso,
        "question_1_analysis": "",
        "question_1_score": 0,
        "question_2_analysis": "",
        "question_2_score": 0,
        "question_3_analysis": "",
        "question_3_score": 0,
        "coach_insight": None,
    })

    try:
        db.v2_charge_homework_completion_credits_once(session_id, user_id, amount=5)
    except Exception as credit_err:
        logger.warning("Homework completion credit charge failed session_id=%s: %s", session_id, credit_err)

    student_email = _resolve_student_email(preferred_student_email, user_id, context="completion")
    try:
        coach_result = email_service.send_lesson_complete_to_admin(
            user_id, session_id, report_text,
            student_email=student_email or None,
            performance_score_end=performance_score_end,
            student_name=_resolve_student_name(user_id, student_email) if student_email else "",
        )
        if coach_result.get("status") != "sent":
            logger.warning(
                "Coach completion email not sent session_id=%s status=%s error=%s",
                session_id, coach_result.get("status"), coach_result.get("error"),
            )
    except Exception as mail_err:
        logger.warning("Lesson-complete coach email failed: %s", mail_err)

    coach_insight, r1, r2, r3 = _run_optional_enrichment(
        session=session,
        session_id=session_id,
        user_id=user_id,
        transcript=transcript,
        filler_count=filler_count,
        filler_data=filler_data,
        performance_score_end=performance_score_end,
    )

    try:
        db.v2_upsert_student_coaching_memory(user_id, session_id)
    except Exception as cm_err:
        logger.warning("Coaching memory upsert failed: %s", cm_err)

    result = {
        "report_text": report_text,
        "performance_score_end": performance_score_end,
        "recording_count": recording_count,
        "performance_metrics": final["metrics"],
        "question_1_analysis": r1.get("analysis") or "",
        "question_1_score": float(r1.get("score", 0)),
        "question_2_analysis": r2.get("analysis") or "",
        "question_2_score": float(r2.get("score", 0)),
        "question_3_analysis": r3.get("analysis") or "",
        "question_3_score": float(r3.get("score", 0)),
        "completed_at_iso": completed_at_iso,
    }
    if recording_count == 1:
        result["performance_score_1"] = performance_score_end
    else:
        result["performance_score_2"] = float(session.get("performance_score_2") or 0)
    return result


def complete_session_recording_1_only(
    session_id: str,
    user_id: str,
    allow_task_block: bool = False,
    preferred_student_email: str | None = None,
):
    """
    Load session and recording_1; compute metrics, generate report, mark session completed. No recording_2.
    Session must be in completing_from_recording_1, legacy post_questions, or (if allow_task_block) task_block.
    Returns dict with report payload or None if not run.
    """
    session = db.v2_get_session(session_id, user_id)
    status = session.get("status") if session else None
    allowed = ("completing_from_recording_1", "post_questions", "task_block") if allow_task_block else ("completing_from_recording_1", "post_questions")
    if not session or status not in allowed:
        return None
    if status == "task_block":
        db.v2_update_session(session_id, user_id, {"status": "completing_from_recording_1"})
        session = db.v2_get_session(session_id, user_id)
    recording_1_id = session.get("recording_1_id")
    if not recording_1_id:
        logger.warning("complete_session_recording_1_only: no recording_1_id session_id=%s", session_id)
        return None

    result = _complete_session_from_recording(
        session=session,
        session_id=session_id,
        user_id=user_id,
        recording_id=recording_1_id,
        base_score_key="performance_score_1",
        preferred_student_email=preferred_student_email,
        recording_count=1,
    )
    if result is not None:
        logger.info("complete_session_recording_1_only: done session_id=%s", session_id)
    return result


def complete_session_recording_2_only(
    session_id: str,
    user_id: str,
    preferred_student_email: str | None = None,
):
    """
    Load session and recording_2; compute final metrics, generate report, mark session completed.
    Session must be in completing_from_recording_2 or final_task_ready.
    Returns dict with report payload or None if not run.
    """
    session = db.v2_get_session(session_id, user_id)
    status = session.get("status") if session else None
    allowed = ("completing_from_recording_2", "final_task_ready")
    if not session or status not in allowed:
        logger.warning("complete_session_recording_2_only: skipped session_id=%s status=%s", session_id, status)
        return None
    if status == "final_task_ready":
        db.v2_update_session(session_id, user_id, {"status": "completing_from_recording_2"})
        session = db.v2_get_session(session_id, user_id)
    recording_2_id = session.get("recording_2_id")
    if not recording_2_id:
        logger.warning("complete_session_recording_2_only: no recording_2_id session_id=%s", session_id)
        return None

    result = _complete_session_from_recording(
        session=session,
        session_id=session_id,
        user_id=user_id,
        recording_id=recording_2_id,
        base_score_key="performance_score_2",
        preferred_student_email=preferred_student_email,
        recording_count=2,
    )
    if result is not None:
        logger.info("complete_session_recording_2_only: done session_id=%s", session_id)
    return result


def minimal_complete_and_notify(
    session_id: str,
    user_id: str,
    preferred_student_email: str | None = None,
) -> bool:
    """
    Fallback: mark session completed with a minimal report and send coach email.
    Use when complete_session_recording_1_only fails so the coach is still notified.
    Returns True if session was marked completed and email sent (or attempted).
    """
    try:
        session = db.v2_get_session(session_id, user_id)
        if not session or session.get("status") == STATUS_COMPLETED:
            return False
        recording_1_id = session.get("recording_1_id")
        if not recording_1_id:
            return False
        report_text = MINIMAL_REPORT_FALLBACK
        db.v2_append_context_long_entry(session_id, user_id, report_text)
        report_row = db.v2_create_report(session_id, recording_1_id, report_text)
        completed_at_iso = utc_now_iso()
        performance_score_end = max(0.0, min(1.0, float(session.get("performance_score_1") or 0)))
        rec = db.get_recording(recording_1_id, user_id)
        filler_data = rec.get("filler_words_count") if isinstance(rec, dict) else {}
        filler_count = int((filler_data or {}).get("total", 0)) if isinstance(filler_data, dict) else 0
        try:
            sniper = db.get_session_sniper_metrics(session_id)
            if sniper and sniper.get("stage_score") is not None:
                raw = float(sniper["stage_score"])
                performance_score_end = max(0.0, min(1.0, raw / 100.0 if raw > 1.0 else raw))
        except Exception:
            pass
        if int(filler_count) > 0 and performance_score_end >= 1.0:
            performance_score_end = 0.99
        db.v2_update_session(session_id, user_id, {
            "post_answers": [],
            "report_id": report_row["id"] if report_row else None,
            "performance_score_end": performance_score_end,
            "status": STATUS_COMPLETED,
            "completed_at": completed_at_iso,
            "recording_1_processing_status": "completed",
            "question_1_analysis": "",
            "question_1_score": 0,
            "question_2_analysis": "",
            "question_2_score": 0,
            "question_3_analysis": "",
            "question_3_score": 0,
            "coach_insight": None,
        })
        try:
            db.v2_charge_homework_completion_credits_once(session_id, user_id, amount=5)
        except Exception as credit_err:
            logger.warning("Minimal completion credit charge failed session_id=%s: %s", session_id, credit_err)
        student_email = _resolve_student_email(preferred_student_email, user_id, context="minimal completion")
        try:
            coach_result = email_service.send_lesson_complete_to_admin(
                user_id, session_id, report_text,
                student_email=student_email or None,
                performance_score_end=performance_score_end,
            )
            if coach_result.get("status") != "sent":
                logger.warning(
                    "Minimal-complete coach email not sent session_id=%s status=%s error=%s",
                    session_id, coach_result.get("status"), coach_result.get("error"),
                )
        except Exception as mail_err:
            logger.warning("Minimal-complete coach email failed: %s", mail_err)

        logger.info("minimal_complete_and_notify: done session_id=%s", session_id)
        return True
    except Exception as e:
        logger.exception("minimal_complete_and_notify failed: %s", e)
        return False


def ensure_student_completion_email(
    session_id: str,
    user_id: str,
    preferred_student_email: str | None = None,
) -> bool:
    """Send student completion email once per session (dedup by student_completion_email_sent_at)."""
    session = db.v2_get_session(session_id, user_id)
    if not session or session.get("status") != STATUS_COMPLETED:
        return False
    if session.get("student_completion_email_sent_at"):
        return True
    student_email = _resolve_student_email(preferred_student_email, user_id, context="student completion email")
    if not student_email:
        try:
            db.v2_update_session(session_id, user_id, {"student_completion_email_last_error": "NO_EMAIL"})
        except Exception:
            pass
        logger.warning("ensure_student_completion_email: no email for user_id=%s session_id=%s", user_id, session_id)
        return False
    score_end = float(session.get("performance_score_end") or 0.0)
    report_text = _session_report_text(session)
    try:
        result = email_service.send_lesson_complete_to_student(
            to_email=student_email,
            frontend_url=config.FRONTEND_URL,
            performance_score_end=score_end,
            report_preview=report_text,
            student_name=_resolve_student_name(user_id, student_email),
            session_id=session_id,
        )
        if result.get("status") == "sent":
            try:
                db.v2_update_session(session_id, user_id, {
                    "student_completion_email_sent_at": utc_now_iso(),
                    "student_completion_email_last_error": None,
                })
            except Exception:
                pass
            return True
        err = (result.get("error") or result.get("status") or "EMAIL_FAILED")
        try:
            db.v2_update_session(session_id, user_id, {"student_completion_email_last_error": str(err)[:800]})
        except Exception:
            pass
        logger.warning(
            "ensure_student_completion_email: failed session_id=%s to=%s status=%s error=%s",
            session_id, student_email, result.get("status"), result.get("error"),
        )
        return False
    except Exception as e:
        try:
            db.v2_update_session(session_id, user_id, {"student_completion_email_last_error": str(e)[:800]})
        except Exception:
            pass
        logger.warning("ensure_student_completion_email exception session_id=%s: %s", session_id, e)
        return False
