"""
Complete a homework session using only recording 1 (no post-recording questions, no recording 2).
The current web client path is recording_1 -> self-rating -> report.
Legacy `post_questions` handling remains only as a compatibility fallback for older sessions.
"""
import json
import logging
import time
import re
from datetime import datetime, timezone

from config import Config
from services.db import db
from services.openai_service import openai_service
from services.email_service import email_service
from services.metrics_v2 import compute_metrics_v2
from services.utils import utc_now_iso, score_01_from_recording_row

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
    # Re-read row so we never drop job-written scoring_debug / nested metrics on a stale snapshot.
    fresh = db.get_recording(str(recording_id), None) or recording
    existing = fresh.get("performance_metrics_v2") if isinstance(fresh.get("performance_metrics_v2"), dict) else {}
    scoring_debug = existing.get("scoring_debug") if isinstance(existing, dict) else None
    merged = dict(final["metrics"])
    if isinstance(scoring_debug, dict):
        merged["scoring_debug"] = scoring_debug
    db.update_recording(recording_id, {
        "performance_score_v2": final["performance_score"],
        "performance_metrics_v2": merged,
        "metric_labels_snapshot_v2": final["metric_labels_snapshot"],
    })


def _compute_score(session: dict, session_id: str, base_score_key: str, filler_count: int) -> float:
    """Final session score (0–1): same as the backend recording job score.

    Single-recording homework flow uses only this; we do not override with Sniper ``stage_score`` (often 0 or unset).
    """
    score = max(0.0, min(1.0, float(session.get(base_score_key) or 0)))
    score_source = "backend_" + base_score_key
    logger.info(
        "_compute_score: %s=%s → %.4f session_id=%s",
        base_score_key,
        session.get(base_score_key),
        score,
        session_id,
    )

    # Hard cap: any fillers → never 100%
    if int(filler_count) > 0 and score >= 1.0:
        score = 0.99

    logger.info(
        "_compute_score: final=%.4f source=%s session_id=%s",
        score,
        score_source,
        session_id,
    )
    return score


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _to_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _tokenize_for_overlap(text: str) -> set[str]:
    if not text:
        return set()
    words = re.findall(r"[a-zA-Z0-9']+", text.lower())
    return {w for w in words if len(w) >= 4}


def _score_ffmpeg_components(sniper_row: dict | None) -> tuple[float, dict]:
    """Build a deterministic 0..1 acoustic score from ffmpeg/sniper fields."""
    if not isinstance(sniper_row, dict):
        return 0.0, {"available": False}
    parts = []
    pause_ms = _to_float(sniper_row.get("pause_ms"))
    if pause_ms is not None:
        # Best around ~450ms average pause.
        pause_n = _clamp(1.0 - abs(pause_ms - 450.0) / 450.0, 0.0, 1.0)
        parts.append(pause_n)
    dynamic_db = _to_float(sniper_row.get("dynamic_db"))
    if dynamic_db is not None:
        # 14-20dB is generally expressive but stable.
        dyn_n = _clamp(1.0 - abs(dynamic_db - 17.0) / 10.0, 0.0, 1.0)
        parts.append(dyn_n)
    energy_ratio = _to_float(sniper_row.get("energy_ratio"))
    if energy_ratio is not None:
        # Penalize very low/high voiced-energy ratio.
        energy_n = _clamp(1.0 - abs(energy_ratio - 0.72) / 0.35, 0.0, 1.0)
        parts.append(energy_n)
    pitch_frames = _to_float(sniper_row.get("pitch_frame_count"))
    if pitch_frames is not None:
        # Confidence proxy: enough voiced pitch evidence.
        pitch_conf_n = _clamp(pitch_frames / 40.0, 0.0, 1.0)
        parts.append(pitch_conf_n)
    if not parts:
        return 0.0, {"available": False}
    score = sum(parts) / len(parts)
    return score, {
        "available": True,
        "pause_ms": pause_ms,
        "dynamic_db": dynamic_db,
        "energy_ratio": energy_ratio,
        "pitch_frame_count": pitch_frames,
        "normalized": round(score, 4),
    }


def _build_unified_score_payload(
    *,
    session: dict,
    session_id: str,
    user_id: str,
    recording: dict,
    transcript: str,
    context_short: str,
    filler_count: int,
) -> tuple[int, float, dict]:
    """Canonical scoring model used for display and storage."""
    base_01 = _to_float(session.get("score"))
    if base_01 is None or base_01 <= 0:
        recovered = score_01_from_recording_row(recording or {})
        if recovered is not None and recovered > 0:
            base_01 = float(recovered)
    if base_01 is None:
        base_01 = 0.0
    base_01 = _clamp(base_01, 0.0, 1.0)

    sniper = {}
    try:
        sniper = db.get_session_sniper_metrics(session_id) or {}
    except Exception:
        sniper = {}

    stage_raw = _to_float(sniper.get("stage_score"))
    stage_01 = None
    if stage_raw is not None:
        stage_01 = _clamp(stage_raw if stage_raw <= 1.0 else (stage_raw / 100.0), 0.0, 1.0)

    ffmpeg_01, ffmpeg_meta = _score_ffmpeg_components(sniper)

    transcript_tokens = _tokenize_for_overlap(transcript)
    context_tokens = _tokenize_for_overlap(context_short)
    context_01 = None
    if transcript_tokens and context_tokens:
        inter = len(transcript_tokens.intersection(context_tokens))
        denom = max(1, len(context_tokens))
        context_01 = _clamp(inter / denom, 0.0, 1.0)

    rating_raw = _to_float(sniper.get("student_rating_1_10"))
    step_01 = None
    if rating_raw is not None:
        # Legacy field name; value is currently 1-5 scale.
        step_01 = _clamp(rating_raw / 5.0, 0.0, 1.0)
    elif session.get("self_rating_submitted_at"):
        step_01 = 0.6

    weights = {
        "base": 0.45,
        "sniper": 0.20,
        "ffmpeg": 0.20,
        "context": 0.10,
        "step_following": 0.05,
    }
    components = {
        "base": {"available": True, "normalized": round(base_01, 4), "raw": round(base_01 * 100.0, 2)},
        "sniper": {"available": stage_01 is not None, "normalized": round(stage_01, 4) if stage_01 is not None else None, "raw": stage_raw},
        "ffmpeg": ffmpeg_meta,
        "context": {
            "available": context_01 is not None,
            "normalized": round(context_01, 4) if context_01 is not None else None,
            "context_tokens": len(context_tokens),
            "transcript_tokens": len(transcript_tokens),
        },
        "step_following": {"available": step_01 is not None, "normalized": round(step_01, 4) if step_01 is not None else None, "raw": rating_raw},
    }

    weighted_sum = 0.0
    weighted_total = 0.0
    values = {
        "base": base_01,
        "sniper": stage_01,
        "ffmpeg": ffmpeg_01 if ffmpeg_meta.get("available") else None,
        "context": context_01,
        "step_following": step_01,
    }
    for key, weight in weights.items():
        v = values.get(key)
        if v is None:
            continue
        weighted_sum += float(v) * weight
        weighted_total += weight

    score_01 = _clamp((weighted_sum / weighted_total) if weighted_total > 0 else base_01, 0.0, 1.0)
    score_100 = int(round(score_01 * 100.0))
    if int(filler_count or 0) > 0 and score_100 >= 100:
        score_100 = 99
        score_01 = min(score_01, 0.99)

    meta = {
        "version": 1,
        "weights": weights,
        "components": components,
        "canonical": {"score_for_display": score_100, "score_01": round(score_01, 4)},
        "computed_at": utc_now_iso(),
    }
    return score_100, round(score_01, 4), meta


def _run_optional_enrichment(
    session: dict,
    session_id: str,
    user_id: str,
    transcript: str,
    filler_count: int,
    filler_data: dict,
    score: float,
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
            history_scores = [float(r.get("score", 0) or 0) for r in (history_rows or [])]
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
        context_fit_01 = None
        try:
            session_latest = db.v2_get_session(session_id, user_id) or {}
            score_components = session_latest.get("score_components")
            if isinstance(score_components, dict):
                ctx_component = ((score_components.get("components") or {}).get("context") or {})
                raw_fit = ctx_component.get("normalized")
                if raw_fit is not None:
                    context_fit_01 = max(0.0, min(1.0, float(raw_fit)))
        except Exception:
            context_fit_01 = None
        coach_insight = openai_service.generate_coach_insight(
            context_short=context_short,
            transcript_excerpt=transcript_excerpt,
            filler_breakdown=filler_breakdown,
            filler_count=filler_count,
            performance_score=score,
            performance_history_scores=history_scores,
            speaker_profile_context=speaker_profile_context,
            self_rating_1_10=self_rating_1_10,
            live_ball_score_100=live_ball_score_100,
            context_fit_01=context_fit_01,
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

    ai_grade = None
    ai_comment = None
    try:
        latest = db.v2_get_session(session_id, user_id) or {}
        score_100 = latest.get("score_for_display")
        if score_100 is None:
            try:
                score_100 = int(round(float(score or 0) * 100.0))
            except (TypeError, ValueError):
                score_100 = None
        draft = openai_service.generate_admin_grade_comment_draft(
            context_short=context_short,
            coach_insight=coach_insight,
            score_for_display_100=score_100,
        )
        ai_grade = draft.get("grade")
        ai_comment = draft.get("comment")
    except Exception as gc_err:
        logger.warning("AI grade/comment draft generation failed: %s", gc_err)

    update_payload = {
        "question_1_analysis": r1.get("analysis") or "",
        "question_1_score": float(r1.get("score", 0)),
        "question_2_analysis": r2.get("analysis") or "",
        "question_2_score": float(r2.get("score", 0)),
        "question_3_analysis": r3.get("analysis") or "",
        "question_3_score": float(r3.get("score", 0)),
        "coach_insight": coach_insight or None,
    }
    if ai_grade is not None:
        update_payload["ai_draft_grade"] = ai_grade
    if ai_comment:
        update_payload["ai_draft_comment"] = ai_comment
    try:
        db.v2_update_session(session_id, user_id, update_payload)
    except Exception as upd_err:
        # Older DBs may not have ai_draft_* columns yet.
        if "ai_draft_" in str(upd_err):
            update_payload.pop("ai_draft_grade", None)
            update_payload.pop("ai_draft_comment", None)
            db.v2_update_session(session_id, user_id, update_payload)
        else:
            raise
    return coach_insight, r1, r2, r3


def _auto_create_copilot_draft(
    *,
    user_id: str,
    session_id: str,
    coach_insight: str,
    score_for_display_100: int | None,
    task_text: str,
    context_short: str,
):
    """Auto-create a Training Studio draft row with AI pre-fills after session completion.

    Called at the end of _complete_session_from_recording so the admin sees
    a fully pre-filled draft (grade, comment, email, task suggestion) in the
    Training Studio without needing a manual backfill.
    """
    # Read the latest session to get AI draft grade/comment from enrichment
    sess = db.v2_get_session(session_id, user_id) or {}
    ai_draft_grade = sess.get("ai_draft_grade")
    ai_draft_comment = (sess.get("ai_draft_comment") or "").strip() or None

    # If enrichment didn't generate them, create now
    if ai_draft_grade is None or not ai_draft_comment:
        try:
            gc = openai_service.generate_admin_grade_comment_draft(
                context_short=context_short,
                coach_insight=coach_insight,
                score_for_display_100=score_for_display_100,
            )
            if ai_draft_grade is None:
                ai_draft_grade = gc.get("grade")
            if not ai_draft_comment:
                ai_draft_comment = gc.get("comment")
        except Exception:
            pass

    # Get student profile for cohort grouping
    sp = db.get_sniper_profile(user_id) or {}
    profile = (
        (sp.get("coach_override_profile") or "").strip()
        or (sp.get("behavioral_profile") or "").strip()
        or "Unclassified"
    )
    try:
        raw_stage = sp.get("coach_override_stage") or sp.get("computed_stage")
        stage = int(raw_stage) if raw_stage is not None else 1
    except (TypeError, ValueError):
        stage = 1
    stage = max(1, min(5, stage))

    student_details = db.v2_get_student_details(user_id) or {}
    student_name = (student_details.get("name") or "").strip() or (db.get_user_email_from_auth(user_id) or "Student")
    base_task = (task_text or "Continue with your next speaking task.")[:8000]

    # Task suggestion first so email + video script reference the same "next homework".
    ai_task_suggestion = None
    try:
        ai_task_suggestion = openai_service.generate_next_task_suggestion(
            context_short=context_short,
            coach_insight=coach_insight,
            current_task_text=base_task,
            score_for_display_100=score_for_display_100,
            behavioral_profile=profile,
            stage=stage,
        )
    except Exception:
        pass

    display_task = (ai_task_suggestion or "").strip() or base_task
    display_task = display_task[:8000]

    ai_email_draft = None
    try:
        ai_email_draft = openai_service.generate_student_email_draft(
            student_name=student_name,
            coach_insight=coach_insight,
            score_for_display_100=score_for_display_100,
            grade=ai_draft_grade,
            comment=ai_draft_comment or "",
            task_text=display_task,
        )
    except Exception:
        pass

    ai_script_draft = None
    try:
        ai_script_draft = openai_service.generate_video_script_draft(
            student_name=student_name,
            coach_insight=coach_insight,
            task_text=display_task,
            score_for_display_100=score_for_display_100,
        )
    except Exception:
        pass

    draft_payload = {
        "state": "Draft",
        "ai_insight": coach_insight or None,
        "grade_draft": ai_draft_grade,
        "comment_draft": ai_draft_comment,
        "task_draft": display_task,
        "email_draft": ai_email_draft,
        "script_draft": ai_script_draft,
        "video_script": ai_script_draft,
        "ai_grade_draft": ai_draft_grade,
        "ai_comment_draft": ai_draft_comment,
        "ai_email_draft": ai_email_draft,
        "ai_task_suggestion": ai_task_suggestion or display_task,
        "ai_script_draft": ai_script_draft,
        "metadata": {
            "auto_created_at": utc_now_iso(),
            "session_id": session_id,
            "score_for_display": score_for_display_100,
        },
    }

    row = {
        "user_id": user_id,
        "session_id": session_id,
        "cohort_profile": profile,
        "cohort_stage": stage,
        "master_task_text": display_task,
        "ai_suggested_task_text": ai_task_suggestion or display_task,
        "ai_draft_message": ai_email_draft,
        "ai_draft_video_script": ai_script_draft,
        "draft_payload": draft_payload,
        "status": "pending",
        "updated_at": utc_now_iso(),
    }

    try:
        db.insert_admin_student_send_drafts([row])
    except Exception:
        row.pop("ai_suggested_task_text", None)
        row.pop("ai_draft_message", None)
        row.pop("ai_draft_video_script", None)
        db.insert_admin_student_send_drafts([row])
    logger.info("Auto-created copilot draft for user_id=%s session_id=%s profile=%s stage=%s",
                user_id, session_id, profile, stage)


def calculate_mechanical_score(stage_score, dynamic_db, filler_count) -> int:
    """Layer 1: pure deterministic mechanical score (0-100).

    Combines frontend sniper wheel (pace+flow), vocal dynamic range, and filler penalty.
    Zero AI involved — always produces a result even if OpenAI is down.
    """
    base = float(stage_score or 0)
    # Convert 0-1 to 0-100 if needed
    if base <= 1.0:
        base *= 100.0
    base = max(0.0, min(100.0, base))

    # Vocal variety modifier
    vocal_modifier = 0
    if dynamic_db is not None:
        try:
            ddb = float(dynamic_db)
            if ddb < 12:
                vocal_modifier = -10  # monotone/robotic penalty
            elif ddb > 20:
                vocal_modifier = 5    # high energy bonus
        except (TypeError, ValueError):
            pass

    # Filler penalty
    filler_penalty = int(filler_count or 0) * 3

    raw = base + vocal_modifier - filler_penalty
    return max(0, min(100, round(raw)))


def _compute_and_save_ai_task_score(
    session: dict,
    session_id: str,
    user_id: str,
    transcript: str,
    wpm: float,
    filler_count: int,
    filler_data: dict,
    legacy_score: float,
):
    """Dual-engine scoring: mechanical (pure math) + context (GPT task judge).

    - mechanical_score: stage_score + dynamic_db modifier - filler penalty (deterministic)
    - ai_task_score: GPT-4o-mini judges transcript against homework task text only
    Non-blocking — failures never affect the student-facing score.
    """
    # --- Layer 1: Mechanical Score (pure math, always computed) ---
    sniper = None
    try:
        sniper = db.get_session_sniper_metrics(session_id)
    except Exception:
        pass
    stage_score = sniper.get("stage_score") if sniper else None
    dynamic_db = sniper.get("dynamic_db") if sniper else None
    mech = calculate_mechanical_score(stage_score, dynamic_db, filler_count)
    try:
        db.v2_update_session(session_id, user_id, {"mechanical_score": mech})
        logger.info("mechanical_score: %d session_id=%s", mech, session_id)
    except Exception as mech_err:
        logger.warning("mechanical_score: DB save failed: %s", mech_err)

    # --- Layer 2: Context Score (GPT judges task completion — transcript only) ---
    student_tasks = db.v2_get_student_tasks(user_id)
    if not student_tasks:
        logger.info("ai_task_score: no student tasks, skipping context score session_id=%s", session_id)
        return
    task_description = " / ".join(t.get("text", "").strip() for t in student_tasks if t.get("text", "").strip())
    if not task_description:
        logger.info("ai_task_score: empty task texts, skipping session_id=%s", session_id)
        return

    # GPT only sees transcript + task — no acoustic metrics (pure semantic judgment)
    result = openai_service.generate_ai_task_score(
        task_description=task_description,
        transcript=transcript,
        metrics={},  # intentionally empty — acoustics handled by mechanical_score
    )

    ai_score = result.get("ai_task_score")
    justification = result.get("justification", "")

    if ai_score is not None:
        try:
            db.v2_update_session(session_id, user_id, {
                "ai_task_score": int(ai_score),
                "ai_scoring_justification": justification[:2000],
            })
        except Exception as save_err:
            logger.warning("ai_task_score: DB save failed: %s", save_err)
            return

    logger.info(
        "ai_task_score: context=%s mechanical=%d justification=%s session_id=%s",
        ai_score, mech, (justification[:80] + "...") if len(justification) > 80 else justification,
        session_id,
    )


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
    recording = db.get_recording_for_homework_session(recording_id, user_id, session)
    if not recording:
        logger.warning("_complete_session_from_recording: recording not found recording_id=%s", recording_id)
        return None
    # Latest row: job may have just written transcript + scoring_debug; avoid 0% score and empty transcript.
    recording = db.get_recording(str(recording_id), None) or recording

    session = dict(session)
    if float(session.get(base_score_key) or 0) <= 0:
        recovered = score_01_from_recording_row(recording)
        if recovered is not None and recovered > 0:
            session[base_score_key] = recovered
            logger.info(
                "_complete_session_from_recording: recovered %s=%.4f from recording scoring_debug session_id=%s",
                base_score_key,
                recovered,
                session_id,
            )

    transcript, wpm, filler_count, filler_data, final = _compute_recording_metrics(recording)
    _persist_recording_metrics(recording_id, recording, final)

    fresh_now = db.v2_get_session(session_id, user_id) or {}
    context_short = (fresh_now.get("context_short") or session.get("context_short") or "").strip()
    if not transcript.strip():
        logger.warning("_complete_session_from_recording: transcript missing, postponing completion session_id=%s", session_id)
        return None
    if not context_short:
        logger.warning("_complete_session_from_recording: context_short missing, postponing completion session_id=%s", session_id)
        return None
    sniper_now = {}
    try:
        sniper_now = db.get_session_sniper_metrics(session_id) or {}
    except Exception:
        sniper_now = {}
    if not isinstance(sniper_now, dict) or not any(
        sniper_now.get(k) is not None for k in ("stage_score", "pause_ms", "dynamic_db", "energy_ratio")
    ):
        logger.warning("_complete_session_from_recording: sniper/ffmpeg metrics missing, postponing completion session_id=%s", session_id)
        return None

    score_for_display_100, performance_score_end, score_components = _build_unified_score_payload(
        session={**session, **fresh_now},
        session_id=session_id,
        user_id=user_id,
        recording=recording,
        transcript=transcript,
        context_short=context_short,
        filler_count=filler_count,
    )

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
        "score": performance_score_end,
        "score_for_display": score_for_display_100,
        "score_ready_at": utc_now_iso(),
        "score_components": score_components,
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
            score=performance_score_end,
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
        score=performance_score_end,
    )

    try:
        db.v2_upsert_student_coaching_memory(user_id, session_id)
    except Exception as cm_err:
        logger.warning("Coaching memory upsert failed: %s", cm_err)

    # Keep student_profile progression/classification in sync with latest completed session.
    try:
        from services.student_profile_service import refresh_student_profile_state
        refresh_student_profile_state(user_id)
    except Exception as sp_err:
        logger.warning("Student profile refresh failed: %s", sp_err)

    # ── SHADOW MODE: AI Task Score (non-blocking, never affects student-facing score) ──
    try:
        _compute_and_save_ai_task_score(session, session_id, user_id, transcript, wpm, filler_count, filler_data, performance_score_end)
    except Exception as ai_err:
        logger.warning("AI task score (shadow) failed session_id=%s: %s", session_id, ai_err)

    # ── AUTO-CREATE COPILOT DRAFT ROW for Training Studio ──
    try:
        _auto_create_copilot_draft(
            user_id=user_id,
            session_id=session_id,
            coach_insight=coach_insight,
            score_for_display_100=score_for_display_100,
            task_text=(session.get("session_task_text") or session.get("warm_up_task_text") or "").strip(),
            context_short=(session.get("context_short") or "").strip(),
        )
    except Exception as draft_err:
        logger.warning("Auto copilot draft creation failed session_id=%s: %s", session_id, draft_err)

    result = {
        "report_text": report_text,
        "score": performance_score_end,
        # Backward compatibility for older clients.
        "performance_score_end": performance_score_end,
        "score_for_display": score_for_display_100,
        "score_components": score_components,
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
        base_score_key="score",
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
        base_score_key="score",
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
        rec = db.get_recording_for_homework_session(recording_1_id, user_id, session)
        # Start with session score; recover from recording job debug if session row never got score.
        performance_score_end = max(
            0.0,
            min(1.0, float(session.get("score") or 0)),
        )
        if performance_score_end <= 0:
            recovered = score_01_from_recording_row(rec or {})
            if recovered is not None and recovered > 0:
                performance_score_end = recovered
        logger.info(
            "minimal_complete_and_notify: backend score=%s → %.4f session_id=%s",
            session.get("score"), performance_score_end, session_id,
        )
        filler_data = rec.get("filler_words_count") if isinstance(rec, dict) else {}
        filler_count = int((filler_data or {}).get("total", 0)) if isinstance(filler_data, dict) else 0
        if int(filler_count) > 0 and performance_score_end >= 1.0:
            performance_score_end = 0.99
        fresh_now = db.v2_get_session(session_id, user_id) or {}
        v = fresh_now.get("score")
        if v is not None:
            try:
                performance_score_end = max(performance_score_end, float(v))
            except (TypeError, ValueError):
                pass
        performance_score_end = max(0.0, min(1.0, performance_score_end))
        score_for_display_100 = fresh_now.get("score_for_display")
        try:
            score_for_display_100 = int(score_for_display_100) if score_for_display_100 is not None else None
        except (TypeError, ValueError):
            score_for_display_100 = None
        if score_for_display_100 is None:
            score_for_display_100 = int(round(performance_score_end * 100.0))
        score_for_display_100 = max(0, min(100, int(score_for_display_100)))
        ai_grade = max(1, min(10, int(round(score_for_display_100 / 10.0))))
        ai_comment = (
            f"Current score is {score_for_display_100}/100. Keep refining pacing and clarity in your next task."
        )
        update_payload = {
            "post_answers": [],
            "report_id": report_row["id"] if report_row else None,
            "score": performance_score_end,
            "score_for_display": score_for_display_100,
            "score_ready_at": utc_now_iso(),
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
            "ai_draft_grade": ai_grade,
            "ai_draft_comment": ai_comment,
        }
        try:
            db.v2_update_session(session_id, user_id, update_payload)
        except Exception as upd_err:
            if "ai_draft_" in str(upd_err):
                update_payload.pop("ai_draft_grade", None)
                update_payload.pop("ai_draft_comment", None)
                db.v2_update_session(session_id, user_id, update_payload)
            else:
                raise
        try:
            db.v2_charge_homework_completion_credits_once(session_id, user_id, amount=5)
        except Exception as credit_err:
            logger.warning("Minimal completion credit charge failed session_id=%s: %s", session_id, credit_err)
        student_email = _resolve_student_email(preferred_student_email, user_id, context="minimal completion")
        try:
            coach_result = email_service.send_lesson_complete_to_admin(
                user_id, session_id, report_text,
                student_email=student_email or None,
                score=performance_score_end,
            )
            if coach_result.get("status") != "sent":
                logger.warning(
                    "Minimal-complete coach email not sent session_id=%s status=%s error=%s",
                    session_id, coach_result.get("status"), coach_result.get("error"),
                )
        except Exception as mail_err:
            logger.warning("Minimal-complete coach email failed: %s", mail_err)

        try:
            from services.student_profile_service import refresh_student_profile_state
            refresh_student_profile_state(user_id)
        except Exception:
            pass

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
    score_end = float(session.get("score") or 0.0)
    report_text = _session_report_text(session)
    try:
        result = email_service.send_lesson_complete_to_student(
            to_email=student_email,
            frontend_url=config.FRONTEND_URL,
            score=score_end,
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
