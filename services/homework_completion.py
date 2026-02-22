"""
Complete a homework session using only recording 1 (no step 2, no recording 2).
Used when the student has no focus tasks: job sets status to completing_from_recording_1,
then when the job finishes it calls this to generate report and mark completed.
"""
import logging
from datetime import datetime, timezone

from services.db import db
from services.openai_service import openai_service
from services.email_service import email_service
from services.metrics_v2 import compute_metrics_v2

logger = logging.getLogger(__name__)

STATUS_COMPLETED = "completed"


def complete_session_recording_1_only(session_id: str, user_id: str) -> None:
    """
    Load session (must be in completing_from_recording_1) and recording_1;
    compute metrics, generate report, mark session completed. No recording_2.
    """
    session = db.v2_get_session(session_id, user_id)
    if not session or session.get("status") != "completing_from_recording_1":
        return
    recording_1_id = session.get("recording_1_id")
    if not recording_1_id:
        logger.warning("complete_session_recording_1_only: no recording_1_id session_id=%s", session_id)
        return
    recording = db.get_recording(recording_1_id, user_id)
    if not recording:
        logger.warning("complete_session_recording_1_only: recording not found recording_id=%s", recording_1_id)
        return

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
    context_short = (session.get("context_short") or "").strip()
    report_text = f"Your performance score: {performance_score_end:.0%}. "
    try:
        report_text = openai_service.generate_final_report(
            transcript=transcript[:500],
            pre_answers=[],
            post_answers=[],
            wpm=wpm,
            filler_count=filler_count,
            filler_breakdown={},
            user_id=user_id,
            admin_context=db.get_user_admin_context(user_id),
            recording_id=recording_1_id,
            homework_context_short=context_short or None,
            homework_metric_answers=None,
            homework_performance_score_1=performance_score_1,
            homework_performance_score_2=performance_score_1,
            homework_metric_1_name="pacing",
            homework_metric_2_name="vocal strength",
        ) or report_text
    except Exception as e:
        logger.warning("Homework report (recording-1 only) failed: %s", e)
        report_text += "Details: pace, strength, fillers."

    db.v2_append_context_long_entry(session_id, user_id, report_text)
    report_row = db.v2_create_report(session_id, recording_1_id, report_text)

    q1 = (session.get("session_metric_question_1") or "").strip()
    q2 = (session.get("session_metric_question_2") or "").strip()
    q3 = (session.get("session_metric_question_3") or "").strip()
    custom_results = openai_service.analyze_custom_questions(transcript, [q1, q2, q3])
    r1, r2, r3 = (custom_results + [{"analysis": "", "score": 0}] * 3)[:3]
    completed_at_iso = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    db.v2_update_session(session_id, user_id, {
        "post_answers": [],
        "report_id": report_row["id"] if report_row else None,
        "performance_score_end": performance_score_end,
        "status": STATUS_COMPLETED,
        "completed_at": completed_at_iso,
        "question_1_analysis": r1.get("analysis") or "",
        "question_1_score": float(r1.get("score", 0)),
        "question_2_analysis": r2.get("analysis") or "",
        "question_2_score": float(r2.get("score", 0)),
        "question_3_analysis": r3.get("analysis") or "",
        "question_3_score": float(r3.get("score", 0)),
    })
    try:
        db.v2_upsert_student_coaching_memory(user_id, session_id)
    except Exception as cm_err:
        logger.warning("Coaching memory upsert failed: %s", cm_err)

    try:
        student_email = db.get_user_email_from_auth(user_id)
        email_service.send_lesson_complete_to_admin(
            user_id, session_id, report_text,
            student_email=student_email,
            performance_score_end=performance_score_end,
        )
    except Exception as mail_err:
        logger.warning("Lesson-complete email failed: %s", mail_err)

    logger.info("complete_session_recording_1_only: done session_id=%s", session_id)
