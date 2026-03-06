"""
Complete a homework session using only recording 1 (no step 2, no recording 2).
Used when the student has no focus tasks: job sets status to completing_from_recording_1,
then when the job finishes it calls this to generate report and mark completed.
"""
import json
import logging
import re
import time
from datetime import datetime, timezone

from services.db import db

_DEBUG_LOG_PATH = "/Users/arturwillonski/Documents/backend-cursor/.cursor/debug.log"


def _completion_debug_log(message: str, data: dict, hypothesis_id: str):
    try:
        line = json.dumps({"location": "homework_completion.py", "message": message, "data": data, "timestamp": int(time.time() * 1000), "hypothesisId": hypothesis_id}) + "\n"
        with open(_DEBUG_LOG_PATH, "a") as f:
            f.write(line)
    except Exception:
        pass
from services.openai_service import openai_service
from services.email_service import email_service
from services.metrics_v2 import compute_metrics_v2

logger = logging.getLogger(__name__)

STATUS_COMPLETED = "completed"

COACH_FEEDBACK_MESSAGE = (
    "Your coach has 24 hours to analyse your homework and send a feedback on your email!"
)

MINIMAL_REPORT_FALLBACK = (
    "**Report**\n\nHomework recording was submitted. Full report could not be generated. "
    "Your coach has 24 hours to review and send you feedback."
)


def _first_n_sentences(text: str, n: int = 2) -> str:
    """Return at most n sentences from text (split on . ! ?)."""
    if not (text or "").strip():
        return ""
    # Split on sentence-ending punctuation, keep delimiters
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(parts[:n]).strip() if parts else text.strip()[:200]


def _build_report_recording_1_only(
    transcript: str,
    wpm: float,
    filler_count: int,
    metrics: dict,
) -> str:
    """Build a fixed report for recording-1-only flow: max 2 sentences from transcript, filler count, pace & strength, coach message."""
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


def complete_session_recording_1_only(session_id: str, user_id: str, allow_task_block: bool = False):
    """
    Load session and recording_1; compute metrics, generate report, mark session completed. No recording_2.
    Session must be in completing_from_recording_1, post_questions, or (if allow_task_block) task_block.
    When status is post_questions, session.post_answers (from POST post-answers) are kept; otherwise [].
    Returns dict with report payload (report_text, performance_score_end, ...) or None if not run.
    """
    session = db.v2_get_session(session_id, user_id)
    status = session.get("status") if session else None
    allowed = ("completing_from_recording_1", "post_questions", "task_block") if allow_task_block else ("completing_from_recording_1", "post_questions")
    in_allowed = status in allowed if status else False
    # #region agent log
    _completion_debug_log("complete_session_recording_1_only entry", {"session_id": session_id, "status": status, "in_allowed": in_allowed}, "H8")
    # #endregion
    if not session or status not in allowed:
        # #region agent log
        _completion_debug_log("complete_session_recording_1_only return None: no session or status not allowed", {"session_id": session_id, "status": status}, "H8")
        # #endregion
        return None
    if status == "task_block":
        db.v2_update_session(session_id, user_id, {"status": "completing_from_recording_1"})
        session = db.v2_get_session(session_id, user_id)
    recording_1_id = session.get("recording_1_id")
    if not recording_1_id:
        # #region agent log
        _completion_debug_log("complete_session_recording_1_only return None: no recording_1_id", {"session_id": session_id}, "H8")
        # #endregion
        logger.warning("complete_session_recording_1_only: no recording_1_id session_id=%s", session_id)
        return None
    recording = db.get_recording(recording_1_id, user_id)
    if not recording:
        # #region agent log
        _completion_debug_log("complete_session_recording_1_only return None: recording not found", {"session_id": session_id, "recording_1_id": recording_1_id}, "H8")
        # #endregion
        logger.warning("complete_session_recording_1_only: recording not found recording_id=%s", recording_1_id)
        return None

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
    db.update_recording(recording_1_id, {
        "performance_score_v2": final["performance_score"],
        "performance_metrics_v2": final["metrics"],
        "metric_labels_snapshot_v2": final["metric_labels_snapshot"],
    })

    performance_score_1 = float(session.get("performance_score_1") or 0)
    performance_score_end = max(0.0, min(1.0, performance_score_1))
    # Prefer Sniper (Voice Alignment) as the single performance score when available
    try:
        sniper = db.get_session_sniper_metrics(session_id)
        if sniper and sniper.get("stage_score") is not None:
            raw = float(sniper["stage_score"])
            performance_score_end = max(0.0, min(1.0, raw / 100.0 if raw > 1.0 else raw))
    except Exception as sniper_err:
        logger.debug("No sniper metrics for session %s: %s", session_id, sniper_err)
    report_text = _build_report_recording_1_only(
        transcript=transcript,
        wpm=wpm,
        filler_count=filler_count,
        metrics=final["metrics"],
    )

    db.v2_append_context_long_entry(session_id, user_id, report_text)
    report_row = db.v2_create_report(session_id, recording_1_id, report_text)

    completed_at_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    # Keep existing post_answers when coming from post_questions step; otherwise [].
    post_answers = session.get("post_answers") if isinstance(session.get("post_answers"), list) else []

    # Mark session completed and send coach email immediately so the report is "delivered"
    # even if optional OpenAI steps (custom questions, coach_insight) fail or are slow.
    # #region agent log
    _completion_debug_log("complete_session_recording_1_only: updating session to completed", {"session_id": session_id}, "H8")
    # #endregion
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
        student_email = db.get_user_email_from_auth(user_id)
        email_service.send_lesson_complete_to_admin(
            user_id, session_id, report_text,
            student_email=student_email,
            performance_score_end=performance_score_end,
        )
    except Exception as mail_err:
        logger.warning("Lesson-complete email failed: %s", mail_err)

    # Optional: enrich with custom question analysis and coach insight (non-blocking).
    # Session is already completed and coach already notified.
    r1 = r2 = r3 = {"analysis": "", "score": 0}
    q1 = (session.get("session_metric_question_1") or "").strip()
    q2 = (session.get("session_metric_question_2") or "").strip()
    q3 = (session.get("session_metric_question_3") or "").strip()
    try:
        custom_results = openai_service.analyze_custom_questions(transcript, [q1, q2, q3])
        r1, r2, r3 = (custom_results + [{"analysis": "", "score": 0}] * 3)[:3]
    except Exception as cq_err:
        logger.warning("Custom questions analysis failed: %s", cq_err)

    coach_insight = ""
    try:
        context_short = (session.get("context_short") or "").strip()
        filler_breakdown = dict(filler_data.get("breakdown", {})) if isinstance(filler_data, dict) else {}
        history_rows = db.v2_get_performance_history(user_id, limit=5)
        history_scores = [float(r.get("performance_score_end") or 0) for r in history_rows]
        transcript_excerpt = (transcript or "")[:600]
        coach_insight = openai_service.generate_coach_insight(
            context_short=context_short,
            transcript_excerpt=transcript_excerpt,
            filler_breakdown=filler_breakdown,
            filler_count=filler_count,
            performance_score=performance_score_end,
            performance_history_scores=history_scores,
        )
    except Exception as ci_err:
        logger.warning("Coach insight generation failed: %s", ci_err)

    db.v2_update_session(session_id, user_id, {
        "question_1_analysis": r1.get("analysis") or "",
        "question_1_score": float(r1.get("score", 0)),
        "question_2_analysis": r2.get("analysis") or "",
        "question_2_score": float(r2.get("score", 0)),
        "question_3_analysis": r3.get("analysis") or "",
        "question_3_score": float(r3.get("score", 0)),
        "coach_insight": coach_insight or None,
    })

    try:
        db.v2_upsert_student_coaching_memory(user_id, session_id)
    except Exception as cm_err:
        logger.warning("Coaching memory upsert failed: %s", cm_err)

    logger.info("complete_session_recording_1_only: done session_id=%s", session_id)
    return {
        "report_text": report_text,
        "performance_score_end": performance_score_end,
        "performance_score_1": performance_score_end,
        "recording_count": 1,
        "performance_metrics": final["metrics"],
        "question_1_analysis": r1.get("analysis") or "",
        "question_1_score": float(r1.get("score", 0)),
        "question_2_analysis": r2.get("analysis") or "",
        "question_2_score": float(r2.get("score", 0)),
        "question_3_analysis": r3.get("analysis") or "",
        "question_3_score": float(r3.get("score", 0)),
        "completed_at_iso": completed_at_iso,
    }


def minimal_complete_and_notify(session_id: str, user_id: str) -> bool:
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
        completed_at_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        performance_score_end = max(0.0, min(1.0, float(session.get("performance_score_1") or 0)))
        try:
            sniper = db.get_session_sniper_metrics(session_id)
            if sniper and sniper.get("stage_score") is not None:
                raw = float(sniper["stage_score"])
                performance_score_end = max(0.0, min(1.0, raw / 100.0 if raw > 1.0 else raw))
        except Exception:
            pass
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
            student_email = db.get_user_email_from_auth(user_id)
            email_service.send_lesson_complete_to_admin(
                user_id, session_id, report_text,
                student_email=student_email,
                performance_score_end=performance_score_end,
            )
        except Exception as mail_err:
            logger.warning("Minimal-complete: lesson-complete email failed: %s", mail_err)
        logger.info("minimal_complete_and_notify: done session_id=%s", session_id)
        return True
    except Exception as e:
        logger.exception("minimal_complete_and_notify failed: %s", e)
        return False
