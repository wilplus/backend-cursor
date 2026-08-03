"""
V2 routes: admin CRUD + the willab learner flow (Lab/Readout/Insights,
Lounge, Library, profile). All /v2/admin/* require auth + admin.
(The legacy homework student flow was removed in the Phase-5 clearance.)
"""
from flask import request, jsonify, make_response
from config import Config
from auth import require_auth, optional_auth
from routes.admin import require_admin, is_admin, require_admin_or_coach, is_coach
from services.db import db
from services.email_service import email_service
from services.copilot_video_pipeline import (
    build_feedback_video_storage_path,
    build_script_manifest,
    fetch_override_video_bytes,
    generate_video_from_script,
    parse_bool,
    parse_reference_tags,
    resolve_script_mode,
)
from services.stress_snippet_service import (
    STRESS_SNIPPET_CLIP_SEC_DEFAULT,
    STRESS_SNIPPET_CLIP_SEC_MAX,
    STRESS_SNIPPET_CLIP_SEC_MIN,
    generate_stress_snippets_for_recording,
)
from services.charisma_snippet_service import (
    CHARISMA_SNIPPET_CLIP_SEC_DEFAULT,
    CHARISMA_SNIPPET_CLIP_SEC_MAX,
    CHARISMA_SNIPPET_CLIP_SEC_MIN,
    generate_charisma_snippets_for_recording,
)
from services.coach_video_storage import (
    coach_media_public_url,
    coach_videos_use_r2,
    guess_video_content_type,
    presigned_get_coach_object,
    presigned_put_coach_object,
    put_coach_object_bytes,
    get_coach_object_bytes,
    r2_bucket_name,
)
import logging
import sentry_sdk
import json
import time
import hashlib
import random
import mimetypes
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from werkzeug.utils import secure_filename
from io import BytesIO
from typing import Any

from services.draft_delivery import (
    auto_approve_payload_for_send,
    infer_delivery_lifecycle,
    log_rlhf_auto_accept_events,
)

# ── Domain modules (god-file split, phase 1) ────────────────────────────────
# `v2_bp` now lives in routes/v2/blueprint.py so the domain modules below can
# register routes on it without importing THIS module (which would be a
# cycle). Same blueprint object, same name "v2" → endpoint names and the URL
# map are byte-identical to before the split.
#
# Importing routes.v2.lab_recording is what REGISTERS its routes, so it has to
# happen here (app.py imports this module) and before the blueprint is
# registered on the app — Flask rejects late route additions.
#
# The `from ... import` lines are re-exports, not decoration: helpers that
# moved out are still reached as routes.v2_routes.<name> by the test suite.
from routes.v2.blueprint import v2_bp
from routes.v2.common import (  # noqa: F401 — re-exported for import compat
    _COACH_PSEUDONYM_SALT,
    _LAB_MAX_AUDIO_MB,
    _PRESENTATION_MAX_MB,
    _VIDEO_UPLOAD_EXTS,
    _async_analysis_enabled,
    _client_ip_from_request,
    _is_valid_uuid,
    _pipeline_queue_enabled,
    _resolve_snippet_audio_url,
)
from routes.v2.arcs import (  # noqa: F401 — re-exported for import compat
    _arc_audit_paid,
    _continue_deck_arc,
    _continue_topic_arc,
    _presentation_id_from_slides,
    _reassemble_after_decision,
    _spoken_takes_and_reads,
)
from routes.v2.lab_recording import (  # noqa: F401 — re-exported for import compat
    _parse_lab_vocabulary,
    _recording_flow_tags,
    v2_lab_create_recording,
    v2_lab_presentation_extract,
)
from routes.v2.user_sessions import (  # noqa: F401 — re-exported for import compat
    _SUGGESTION_ACTIONS,
    _SUGGESTION_TARGETS,
    _TRANSCRIPT_EDIT_MAX_LEN,
    _build_user_session_status,
    _derive_session_status,
    _document_phrase_for,
    _hard_delete_session_for_user,
    _metrics_ready,
    _user_presentation_groups,
    _user_presentation_sessions_all,
    v2_user_delete_presentation,
    v2_user_delete_session,
    v2_user_delete_take,
    v2_user_get_library,
    v2_user_get_results,
    v2_user_get_session_intake_context,
    v2_user_get_session_readout,
    v2_user_get_strengths,
    v2_user_list_readouts,
    v2_user_list_trainings,
    v2_user_put_session_intake_context,
    v2_user_put_transcript_edit,
    v2_user_sessions_current,
    v2_user_snippet_label,
    v2_user_suggestion_feedback,
)
from routes.v2.user_chat import (  # noqa: F401 — re-exported for import compat
    _CONTEXTUAL_INTENTS,
    _INTERVIEW_QUESTIONS_FALLBACK,
    _INTERVIEW_SYSTEM_PROMPT,
    _SELF_RATING_RE,
    _SELF_RATING_TEXT_MAX,
    _SELF_RATING_WORD_MAP,
    _augment_interview_prompt_with_profile,
    _best_self_rating,
    _build_few_shot_block,
    _build_longitudinal_context_block,
    _build_master_score_block,
    _first_self_rating,
    _generate_llm_question,
    _parse_self_rating_from_text,
    v2_user_chat_first_question,
    v2_user_coaching_self_rating,
)
from routes.v2.user_account import (  # noqa: F401 — re-exported for import compat
    _CONSENT_FIELDS_FE,
    _PROFILE_GOAL_MAX_LEN,
    _shape_consent_response,
    v2_user_consent,
    v2_user_game_sessions,
    v2_user_get_audits,
    v2_user_get_credits,
    v2_user_get_profile,
    v2_user_get_sharing_consent,
    v2_user_kpi_timeline,
    v2_user_last_setup,
    v2_user_put_sharing_consent,
    v2_user_recording_progress,
    v2_user_set_profile,
)
from routes.v2.lounge import (  # noqa: F401 — re-exported for import compat
    v2_user_lounge_messages_delete,
    v2_user_lounge_messages_get,
    v2_user_lounge_messages_post,
)
from routes.v2.coach import (  # noqa: F401 — re-exported for import compat
    _COACH_PSEUDONYM_ADJ,
    _COACH_PSEUDONYM_ANIMAL,
    _coach_pseudonym,
    _coach_session_state,
    _coach_state_for,
    _coach_state_map,
    _int_or,
    _resolve_audio_refs,
    _save_coach_snippet_lanes,
    _snippet_owner_map,
    v2_coach_annotation_upload,
    v2_coach_approve_ideal_text,
    v2_coach_arc_best_presentation,
    v2_coach_arc_review_state,
    v2_coach_arc_stars,
    v2_coach_archive_training_import,
    v2_coach_audit_data,
    v2_coach_confidence_queue,
    v2_coach_create_audit,
    v2_coach_get_ideal_text,
    v2_coach_get_session,
    v2_coach_list_training_imports,
    v2_coach_publish_analysis,
    v2_coach_put_confidence_label,
    v2_coach_put_ideal_text,
    v2_coach_put_moment_reference,
    v2_coach_put_say_it_stronger,
    v2_coach_put_star_text,
    v2_coach_put_star_verdict,
    v2_coach_queue,
    v2_coach_restore_training_import,
    v2_coach_save_feedback,
    v2_coach_save_snippet,
    v2_coach_session_recut,
    v2_coach_session_video,
    v2_coach_slide_alignment,
    v2_coach_snippet_breakthrough_video,
    v2_coach_student_audit,
    v2_coach_student_audit_send,
    v2_coach_student_detail,
    v2_coach_students,
    v2_coach_training_import,
    v2_coach_training_import_status,
    v2_coach_verify_ideal_text,
)

logger = logging.getLogger(__name__)
config = Config()


_IMPORT_ALLOWED_EXTENSIONS = {".mp3", ".wav", ".webm", ".m4a", ".ogg", ".flac"}
# `student` is sent by some Training Studio uploads (Student recordings tab); stored in source_metadata only.
def _admin_import_validate_audio_file(file_storage):
    if file_storage is None or not (getattr(file_storage, "filename", "") or "").strip():
        raise ValueError("audio_file is required")
    original_name = secure_filename(file_storage.filename or "")
    ext = os.path.splitext(original_name)[1].lower()
    if ext not in _IMPORT_ALLOWED_EXTENSIONS:
        raise ValueError("unsupported audio format")
    return original_name, ext


# ---------- Admin ----------
@v2_bp.route("/admin/health", methods=["GET"])
@require_admin
def v2_admin_health():
    """Debug: verify admin routes are reachable. Returns 200 if token is valid and admin."""
    return jsonify({"status": "ok", "message": "Admin API reachable"}), 200


# In-process rate limiter: (ip_or_global) -> [unix_timestamps].
# Lost on restart, which is fine — these are anti-abuse caps, not auth.
_guest_funnel_rate_limit: dict = {}
_GUEST_FUNNEL_GLOBAL_KEY = "__global__"


def _guest_funnel_rate_limit_check(client_ip: str) -> tuple[bool, str]:
    """Return (allowed, reason). Sliding 1-hour window per IP and global."""
    import time as _time
    now = _time.time()
    window_start = now - 3600.0
    per_ip_cap = int(getattr(config, "GUEST_FUNNEL_RATE_LIMIT_PER_IP_PER_HOUR", 5) or 5)
    global_cap = int(getattr(config, "GUEST_FUNNEL_RATE_LIMIT_GLOBAL_PER_HOUR", 200) or 200)
    # Trim the IP bucket
    bucket = [t for t in _guest_funnel_rate_limit.get(client_ip, []) if t >= window_start]
    if len(bucket) >= per_ip_cap:
        _guest_funnel_rate_limit[client_ip] = bucket
        return False, "per_ip"
    # Trim the global bucket
    g_bucket = [t for t in _guest_funnel_rate_limit.get(_GUEST_FUNNEL_GLOBAL_KEY, []) if t >= window_start]
    if len(g_bucket) >= global_cap:
        _guest_funnel_rate_limit[_GUEST_FUNNEL_GLOBAL_KEY] = g_bucket
        return False, "global"
    bucket.append(now)
    g_bucket.append(now)
    _guest_funnel_rate_limit[client_ip] = bucket
    _guest_funnel_rate_limit[_GUEST_FUNNEL_GLOBAL_KEY] = g_bucket
    return True, ""


@v2_bp.route("/public/shaky-voice/upload", methods=["POST"])
def v2_public_shaky_voice_upload():
    """Anonymous upload for the Curiosity Gate funnel.

    Stores audio in `guest_funnel/<guest_session_id>/...` and creates an
    unclaimed v2_sessions row. The analysis pipeline is NOT enqueued here —
    it fires only on POST /claim after the user signs in. This keeps paid
    compute (Whisper / OpenAI) off the anonymous surface.
    """
    if not getattr(config, "GUEST_FUNNEL_ENABLED", False):
        return jsonify({"code": "GUEST_FUNNEL_DISABLED", "error": "Guest funnel is disabled"}), 503

    try:
        client_ip = _client_ip_from_request()
        allowed, reason = _guest_funnel_rate_limit_check(client_ip)
        if not allowed:
            logger.info("guest_funnel: rate limited ip=%s reason=%s", client_ip, reason)
            return jsonify({
                "code": "RATE_LIMITED",
                "error": "Too many trial uploads — please wait a few minutes and try again.",
            }), 429

        if "audio_file" not in request.files:
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": "audio_file is required"}), 400
        audio_file = request.files.get("audio_file")
        try:
            original_name, ext = _admin_import_validate_audio_file(audio_file)
        except ValueError as ve:
            msg = str(ve)
            if msg == "unsupported audio format":
                return jsonify({"code": "UNSUPPORTED_AUDIO_FORMAT", "error": "unsupported audio format"}), 415
            return jsonify({"code": "AUDIO_FILE_REQUIRED", "error": msg}), 400

        max_mb_raw = getattr(config, "GUEST_FUNNEL_MAX_AUDIO_SIZE_MB", 5)
        max_mb = int(max_mb_raw) if max_mb_raw is not None else 5
        max_bytes = max_mb * 1024 * 1024
        cl = request.content_length or 0
        if cl and cl > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"audio_file exceeds {max_mb}MB limit"}), 413
        file_bytes = audio_file.read()
        if not file_bytes:
            return jsonify({"code": "INVALID_MULTIPART", "error": "audio_file is empty"}), 400
        if len(file_bytes) > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE", "error": f"audio_file exceeds {max_mb}MB limit"}), 413

        guest_session_id = str(uuid.uuid4())
        recording_id = str(uuid.uuid4())
        storage_path = f"guest_funnel/{guest_session_id}/recording_{uuid.uuid4().hex}{ext}"
        content_type = (audio_file.mimetype or mimetypes.guess_type(original_name)[0] or "application/octet-stream").strip()
        if content_type in ("True", "False"):
            content_type = "application/octet-stream"

        # Cold-start funnel: upload via services.audio_storage so the
        # bytes land in the same bucket extract_recording_snippets reads
        # from. Otherwise the cold-start admin view shows "No interview
        # turns recorded" because the snippet-extraction reader can't
        # find the audio.
        try:
            from services.audio_storage import put_audio_bytes
            put_audio_bytes(storage_path, file_bytes, content_type=content_type)
        except Exception as upload_err:
            logger.warning("guest_funnel: storage upload failed ip=%s: %s", client_ip, upload_err, exc_info=True)
            return jsonify({"code": "UPLOAD_FAILED", "error": "Failed to store uploaded audio"}), 500

        duration_raw = (request.form or {}).get("duration_seconds")
        try:
            duration_seconds = float(duration_raw) if duration_raw not in (None, "") else None
        except (TypeError, ValueError):
            duration_seconds = None

        # ORDER MATTERS: recordings.session_v2_id has FK -> v2_sessions(id), so the
        # session row must exist BEFORE the recording row. We then update the
        # session to set recording_1_id once the recording row exists.
        try:
            db.v2_create_guest_session(guest_session_id)
        except Exception as session_err:
            logger.warning("guest_funnel: v2_create_guest_session failed: %s", session_err, exc_info=True)
            return jsonify({"code": "SESSION_CREATE_FAILED", "error": "Failed to create guest session"}), 500

        recording_payload = {
            "id": recording_id,
            "user_id": None,
            "session_id": None,
            "session_v2_id": guest_session_id,
            "storage_path": storage_path,
            "audio_url": "",
            "duration": 0,
            "recording_origin": "guest_funnel",
        }
        if duration_seconds is not None:
            recording_payload["duration_seconds"] = duration_seconds

        try:
            db.create_recording(recording_payload)
        except Exception as create_err:
            err_low = str(create_err).lower()
            if "recording_origin" in err_low or "pgrst204" in err_low:
                fallback = {k: v for k, v in recording_payload.items() if k != "recording_origin"}
                try:
                    db.create_recording(fallback)
                except Exception as e2:
                    logger.warning("guest_funnel: create_recording failed: %s", e2, exc_info=True)
                    return jsonify({"code": "RECORDING_CREATE_FAILED", "error": "Failed to create recording"}), 500
            else:
                logger.warning("guest_funnel: create_recording failed: %s", create_err, exc_info=True)
                return jsonify({"code": "RECORDING_CREATE_FAILED", "error": "Failed to create recording"}), 500

        try:
            db.v2_set_guest_session_recording(guest_session_id, recording_id)
        except Exception as link_err:
            # Non-fatal: the recording row already carries session_v2_id, so the
            # claim path can still find it. Log and continue.
            logger.warning("guest_funnel: link recording_1_id failed (non-fatal): %s", link_err)

        logger.info(
            "guest_funnel: upload ok ip=%s guest_session_id=%s storage_path=%s bytes=%d",
            client_ip, guest_session_id, storage_path, len(file_bytes),
        )
        return jsonify({
            "status": "ok",
            "guest_session_id": guest_session_id,
        }), 201

    except Exception as e:
        logger.error("guest_funnel: upload failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Upload failed"}), 500


############################################################################
# Multi-Turn Interview endpoints
############################################################################


from services.skills import (
    get_skill as _get_skill,
    resolve_for_snippet as _skill_for_snippet,
)


# ---------------------------------------------------------------------------
# Cold-start onboarding (turns 1-4) — REMOVED IN PHASE 18.
#
# Per docs/ARCHITECTURE_SINGLE_SOURCE_OF_TRUTH.md, the frontend now
# owns turns 1-4 entirely as hardcoded ONBOARDING_MESSAGES strings.
# The backend's scripted EBCP path (the long _EBCP_BASELINE_SYSTEM_
# PROMPT, the _EBCP_FALLBACKS dict, and _generate_ebcp_question) was
# deleted to eliminate duplicate ownership. /v2/public/interview/
# next-question now refuses turn_number <= 4 with 400 TURN_OWNED_BY_
# FRONTEND so a confused client surfaces the violation immediately
# instead of silently regressing into "backend owns turn 1 again".
# ---------------------------------------------------------------------------


def _generate_snippet_follow_up_question(
    snippet_type: str,
    transcript: str,
    admin_comment: str,
) -> str | None:
    """Generate a single follow-up question for the Infinite Retention Loop.

    Called when an admin labels/comments on a snippet. The question is stored
    on the snippet row so it can be served instantly when the user later clicks
    the snippet — no latency at click time.

    snippet_type: "charisma" | "stress" | "unlabeled"
    transcript:   Whisper transcript of the snippet audio.
    admin_comment: Coach's text note on the snippet.

    Returns the generated question string, or None on failure.
    """
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return None

        if snippet_type == "charisma":
            system_prompt = (
                "You are a charisma coaching assistant. "
                "An admin coach has flagged this audio snippet as a HIGH-CHARISMA moment "
                "and left a comment about it. Your task is to write a response that:\n"
                "1. Opens with ONE brief warm acknowledgment of this specific moment (1 sentence)\n"
                "2. Follows with ONE powerful question that helps the user deconstruct WHY they "
                "felt so confident and how they can deliberately replicate that energy "
                "(e.g. in cold calls, presentations, or negotiations)\n"
                "The question must be:\n"
                "- Specific to the transcript content (reference what they actually said)\n"
                "- High-energy and motivating in tone\n"
                "- Focused on replicability (how to trigger this state on demand)\n"
                "- No longer than 2 sentences\n"
                "FORMATTING RULE: Separate your acknowledgment from your question using the exact "
                "delimiter `|||`. "
                "Example: `That energy you described is magnetic! ||| What specific conditions were "
                "present that day that let you access that state so easily?`\n"
                "Return ONLY these two parts separated by `|||`, nothing else."
            )
        elif snippet_type == "stress":
            system_prompt = (
                "You are a performance coaching assistant. "
                "An admin coach has flagged this audio snippet as a HIGH-STRESS or VOCAL-STRAIN moment "
                "and left a comment. Your task is to write a response that:\n"
                "1. Opens with ONE brief empathetic acknowledgment of this specific moment (1 sentence)\n"
                "2. Follows with ONE targeted question that addresses the cognitive load or emotional "
                "trigger that caused the vocal stress spike\n"
                "The question must be:\n"
                "- Specific to what the speaker was saying in the transcript\n"
                "- Empathetic but direct (not dismissive)\n"
                "- Focused on uncovering the root cause of that specific stress moment\n"
                "- No longer than 2 sentences\n"
                "FORMATTING RULE: Separate your acknowledgment from your question using the exact "
                "delimiter `|||`. "
                "Example: `That moment sounds genuinely tough. ||| What was running through your mind "
                "right before your voice shifted?`\n"
                "Return ONLY these two parts separated by `|||`, nothing else."
            )
        else:
            # unlabeled or unknown — generic deepening question
            system_prompt = (
                "You are a voice coaching assistant. "
                "Based on this audio transcript and the coach's comment, write a response that:\n"
                "1. Opens with ONE brief acknowledgment of the moment (1 sentence)\n"
                "2. Follows with ONE insightful question to help the speaker reflect on it\n"
                "FORMATTING RULE: Separate your acknowledgment from your question using the exact "
                "delimiter `|||`. "
                "Return ONLY these two parts separated by `|||`, nothing else."
            )

        user_content = (
            f"Transcript: \"{transcript}\"\n"
            f"Coach comment: \"{admin_comment}\""
        )

        response = service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=120,
            temperature=0.7,
        )
        question = response.choices[0].message.content.strip()
        if question.startswith('"') and question.endswith('"'):
            question = question[1:-1]
        return question if question else None

    except Exception as e:
        logger.warning("_generate_snippet_follow_up_question failed: %s", e)
        return None


def _build_user_raw_snippet_list(
    session_id: str,
    *,
    include_admin_fields: bool,
) -> list[dict]:
    """Build the per-snippet raw-block array consumed by both the
    signed-in /sessions/<id>/summary and the anonymous
    /public/interview/<gsid>/raw-results endpoints.

    Always included (raw, no interpretation):
      snippet_id, audio_url (presigned), duration_ms, transcript,
      question_tone, acoustic stats block, classifier_stress_probability,
      created_at

    Gated on ``include_admin_fields`` (i.e., session is published):
      admin_comment, coach_label, follow_up_question

    Ordering depends on phase (mirrors the include_admin_fields gate):

      PRE-PUBLISH / ANONYMOUS (include_admin_fields=False):
        Chronological — snippets in the order they were collected
        during the session. The raw view is the user's honest
        replay of "what just happened"; resorting it before any
        human interpretation would imply judgment we haven't made
        yet.

      POST-PUBLISH (include_admin_fields=True):
        Bucket by question_tone and sort by intensity:
          - charisma bucket first, ASC by classifier_stress_probability
            (lower stress = more characteristically charismatic)
          - stress bucket next, DESC by classifier_stress_probability
            (higher stress = more stressful)
          - other/untagged trails chronological
        Snippets missing the classifier output tail each bucket.
        The intensity sort IS the curated narrative — and it's
        only earned once a human has reviewed.

    The raw block payload shape is identical for both phases; only
    the ordering changes. FE renders one card component either way.
    """
    snippets = db.get_snippets_by_session(session_id) or []

    rendered: list[dict] = []
    for s in snippets:
        # Skip un-extracted candidates; we only show real snippets.
        # storage_path is the proxy: an extracted snippet has its
        # audio bytes anchored; a placeholder row may not.
        if not (s.get("storage_path") or s.get("audio_url")):
            continue

        metrics = s.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}

        row: dict[str, Any] = {
            "snippet_id":    s.get("id"),
            "audio_url":     _resolve_snippet_audio_url(s),
            "duration_ms":   s.get("duration_ms"),
            "transcript":    (
                s.get("transcript")
                or s.get("transcription_text")
                or ""
            ),
            "question_tone": (s.get("question_tone") or "").lower() or None,
            "acoustic": {
                "wpm":             metrics.get("wpm") or s.get("wpm"),
                "fillers":         metrics.get("fillers") or s.get("fillers"),
                "pause_ms":        metrics.get("pause_ms") or s.get("pause_ms"),
                "pitch_center_hz": metrics.get("pitch_center_hz")
                                  or metrics.get("pitch_center")
                                  or s.get("pitch_center_hz"),
                "dynamic_db":      metrics.get("dynamic_db") or s.get("dynamic_db"),
                "energy":          metrics.get("energy") or s.get("energy"),
            },
            "classifier_stress_probability": (
                s.get("classifier_stress_probability")
            ),
            "created_at":    s.get("created_at"),
        }

        if include_admin_fields:
            row["admin_comment"]      = s.get("admin_comment")
            row["coach_label"]        = (s.get("coach_label") or "").lower() or None
            row["follow_up_question"] = s.get("follow_up_question")

        rendered.append(row)

    # Phase-aware ordering: chronological pre-publish (DB order
    # already is start_offset_ms ASC), intensity-sorted post-publish.
    # See docstring above for the rationale.
    if include_admin_fields:
        return _sort_raw_snippets_by_intensity(rendered)
    return rendered


def _sort_raw_snippets_by_intensity(rendered: list[dict]) -> list[dict]:
    """Bucket by ``question_tone`` and sort each bucket by intensity.

    Ordering rules (single source of truth — used by both signed-in
    and anonymous endpoints):

      1. CHARISMA bucket first, sorted by classifier_stress_probability
         ASCENDING (lower stress signal = more charismatic delivery).
      2. STRESS bucket next, sorted by classifier_stress_probability
         DESCENDING (higher stress signal = more stressful delivery).
      3. Untagged / other-tone snippets last, in original (chronological)
         order — defensive against legacy rows or future tones.

    Snippets missing the classifier output (NULL probability) sort
    to the tail of their bucket so visible "best" snippets are always
    the ones with actual measured intensity, not the ones we couldn't
    score.
    """
    # Sentinel for snippets missing the classifier output. Used as
    # the secondary sort key so untyped probs fall to the END of
    # each bucket regardless of which direction we're sorting.
    _UNSCORED = float("inf")

    def _intensity(row: dict) -> float:
        p = row.get("classifier_stress_probability")
        return float(p) if isinstance(p, (int, float)) else _UNSCORED

    charisma_bucket = [r for r in rendered if r.get("question_tone") == "charisma"]
    stress_bucket   = [r for r in rendered if r.get("question_tone") == "stress"]
    other_bucket    = [
        r for r in rendered
        if r.get("question_tone") not in ("charisma", "stress")
    ]

    # CHARISMA: ascending by stress prob (lower = better) — but
    # unscored rows still trail. The compound key (is_unscored, value)
    # forces unscored to the end regardless of asc/desc direction.
    charisma_bucket.sort(
        key=lambda r: (_intensity(r) is _UNSCORED, _intensity(r)),
    )
    # STRESS: descending by stress prob (higher = more stressful).
    # Negate the value so unscored (inf) flips to -inf and the
    # primary key sorts naturally; unscored still tail via the
    # is_unscored boolean.
    stress_bucket.sort(
        key=lambda r: (_intensity(r) is _UNSCORED, -_intensity(r)),
    )

    return charisma_bucket + stress_bucket + other_bucket


def _format_duration(duration_ms: int | None) -> str:
    """Format a duration in ms as M:SS for the timeline UI (e.g. 12000 -> '0:12')."""
    if not duration_ms or duration_ms < 0:
        return "0:00"
    total_seconds = int(duration_ms // 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _snippet_to_journey_card(snippet: dict) -> dict:
    """Map a charisma_snippets row into the `Snippet` shape the
    /results Voice-Journey page expects (lib/results/types.ts).

    The page's existing typed interface is the contract; we transform once
    here on the backend so the frontend can drop its mock without inventing
    a translation layer.
    """
    coach_label = (snippet.get("coach_label") or "").lower()
    snippet_type = "charisma" if coach_label == "charisma" else "stress"

    badge_label = (
        "Charisma Moment" if snippet_type == "charisma" else "Stress Pattern"
    )
    cta_label = (
        "Understand your charisma"
        if snippet_type == "charisma"
        else "Work on this stress"
    )

    # Build the metrics list — we omit any metric whose value is null so
    # the UI accordion doesn't render empty rows.
    metrics_src = snippet.get("metrics") or {}
    raw_metrics = [
        ("WPM", metrics_src.get("wpm"), lambda v: f"{int(v)}"),
        ("Pitch", metrics_src.get("pitch_center"), lambda v: f"{int(v)} Hz"),
        ("Pause", metrics_src.get("pause_ms"), lambda v: f"{(v / 1000):.1f}s"),
        ("Energy", metrics_src.get("energy"), lambda v: f"{int(v * 100)}%"),
        ("Fillers", metrics_src.get("fillers"), lambda v: f"{int(v)}"),
        ("Dynamic dB", metrics_src.get("dynamic_db"), lambda v: f"{int(v)}"),
    ]
    metrics: list[dict] = []
    for label, value, fmt in raw_metrics:
        if value is None:
            continue
        try:
            metrics.append({"label": label, "value": fmt(value)})
        except Exception:
            # Defensive — never let a formatting error blank out a snippet.
            continue

    return {
        "id": str(snippet.get("id")),
        "type": snippet_type,
        "duration": _format_duration(snippet.get("duration_ms")),
        "badgeLabel": badge_label,
        "insight": snippet.get("admin_comment") or "",
        "ctaLabel": cta_label,
        "metrics": metrics,
        "audioUrl": snippet.get("audio_url"),
    }


# ─────────────────────────────────────────────────────────────────────
# Coaching loop — micro-coaching session on a single snippet
#
# v1: stress intent only, two technical stages (awareness → trial) with
# the reframe baked into the awareness prompt. The flow:
#
#   /v2/coaching/start
#     POST { snippet_id }
#     → reads charisma_snippets row, validates ownership + admin_comment,
#       creates coaching_sessions row, returns the admin_comment as the
#       awareness "first bubble" so the frontend can render it instantly.
#
#   /v2/coaching/turn
#     POST { coaching_id, user_message }
#     → looks up the active skill via services.skills.get_skill(intent),
#       calls the LLM with that skill's awareness_system_prompt, parses
#       the structured JSON (validation_bubble / challenge_bubble /
#       advance) and advances stage to 'trial' when advance is true.
#
#   /v2/coaching/trial-recording
#     POST multipart audio_file + coaching_id
#     → uploads audio, creates v2_session + recording rows, runs the
#       existing extract_recording_snippets pipeline, marks the
#       coaching_session 'complete' and binds trial_session_id.
# ─────────────────────────────────────────────────────────────────────


def _system_prompt_for_intent(intent: str) -> str:
    """Pick the awareness-stage system prompt for a given coaching intent.

    Phase 7 — the prompts themselves moved to services/skills/. This
    function is a thin shim over the registry kept around so existing
    call sites don't have to change; new code should call
    ``services.skills.get_skill(intent).awareness_system_prompt``
    directly. The fallback path (unknown intent) lands on the stress
    skill, matching pre-refactor behaviour.
    """
    skill = _get_skill(intent) or _get_skill("stress")
    return skill.awareness_system_prompt if skill else ""


def _augment_coaching_system_prompt(base_prompt: str, user_id: str) -> str:
    """Append the long-term user profile to a coaching system prompt.

    Three sources of personalisation, stacked top-to-bottom in the
    system prompt:
      - user_settings.custom_llm_instructions — free-text instructions
        the admin set in Admin Tab 3 ("Global LLM Instructions"). Goes
        verbatim into the prompt so the admin's wording is preserved.
      - student profile.behavioral_profile — the user's classified
        learner type (e.g. Stressor, Racer, Freezer) from the
        behavioural-profile classifier.
      - Phase 3: user_settings.inferred_learner_profile — AI-inferred
        traits derived from coaching_attempts aggregates (weakest
        component, score trend, self-rating gap, etc.). Flag-gated by
        LEARNER_PROFILE_INJECTION_ENABLED and additionally gated by
        sample-size threshold in services/learner_profile.py.

    Any of these can be absent. When all three are silent we return
    the base prompt unchanged — no [USER LONG-TERM PROFILE] block.

    Failure modes are swallowed: a DB read miss returns the base
    prompt rather than blocking the coaching turn. Personalisation is
    additive — the awareness loop must keep running even when the
    profile is unreadable.
    """
    admin_instructions: str = ""

    settings: dict = {}
    try:
        settings = db.get_user_settings(user_id) or {}
        admin_instructions = (settings.get("custom_llm_instructions") or "").strip()
    except Exception as e:
        logger.warning("coaching/turn: settings load failed user=%s: %s", user_id, e)

    # Old-subsystem personalisation removed in the excision: the sniper
    # learner-type and the learner_profile inferred-insights block no
    # longer inject here. Admin custom instructions remain.

    if not admin_instructions:
        return base_prompt

    lines: list[str] = ["[USER LONG-TERM PROFILE]"]
    if admin_instructions:
        lines.append(f"Custom Coaching Instructions: {admin_instructions}")
    lines.append("")
    lines.append(
        "CRITICAL: You must adhere to these custom instructions and "
        "tailor your feedback to this learner type."
    )

    return f"{base_prompt}\n\n" + "\n".join(lines)


def _coach_intent_for_snippet(snippet: dict) -> str:
    """Map a snippet's coach_label to a coaching intent.

    Phase 7 — thin shim over services.skills.resolve_for_snippet.
    Kept under the old name so existing call sites in this module
    keep working; new code should import resolve_for_snippet
    directly from the skills package.
    """
    return _skill_for_snippet(snippet)


@v2_bp.route("/internal/whisper-health", methods=["GET"])
def v2_internal_whisper_health():
    """Diagnostic: does the running process actually have OPENAI_API_KEY?

    Hit this from a browser or curl. The response tells us deterministically
    whether the OpenAI client can be constructed at runtime AND whether a
    real API call to OpenAI succeeds — without needing to trigger a real
    recording or sift through Railway logs.

    Auth: intentionally none — leaks no secret material; only metadata
    (length, first 7 chars masked, model count) about whether the integration
    is wired up.
    """
    try:
        from services.openai_service import OpenAIService
        svc = OpenAIService()
        key = (config.OPENAI_API_KEY or "")

        # Live API reachability check — list models. Cheap call (one
        # request, ~100ms), proves the key is valid AND the network can
        # reach api.openai.com from this Railway container.
        api_reachable = False
        api_error: str | None = None
        api_model_count = 0
        if svc.client:
            try:
                models = svc.client.models.list()
                api_reachable = True
                # `data` is a list of Model objects on the response
                api_model_count = len(getattr(models, "data", []) or [])
            except Exception as call_err:
                api_error = f"{type(call_err).__name__}: {call_err}"

        # Also verify which git commit this process is running. Helps
        # confirm Railway has picked up the latest deploy (e.g. the
        # explicit transcription log in e7271b8). Read from RAILWAY_GIT_COMMIT_SHA
        # (Railway-injected) or fall back to RAILWAY_DEPLOYMENT_ID.
        git_sha = (
            os.environ.get("RAILWAY_GIT_COMMIT_SHA")
            or os.environ.get("RAILWAY_DEPLOYMENT_ID")
            or None
        )

        return jsonify({
            "client_initialized": svc.client is not None,
            "api_key_present": bool(key),
            "api_key_length": len(key),
            "api_key_prefix": (key[:7] + "...") if key else None,
            "api_reachable": api_reachable,
            "api_error": api_error,
            "api_model_count": api_model_count,
            "git_sha": git_sha,
            # Echo back which env vars are actually visible at runtime so we
            # can spot Railway-scoped misses (preview vs production env).
            "env_visible": {
                "OPENAI_API_KEY": bool(os.environ.get("OPENAI_API_KEY")),
                "GUEST_FUNNEL_ENABLED": os.environ.get("GUEST_FUNNEL_ENABLED"),
                "BACKEND_URL_INTERNAL": bool(os.environ.get("BACKEND_URL_INTERNAL")),
                "R2_PUBLIC_BASE_URL": bool(os.environ.get("R2_PUBLIC_BASE_URL")),
            },
        }), 200
    except Exception as e:
        logger.error("whisper-health failed: %s", e, exc_info=True)
        return jsonify({"error": str(e)}), 500


@v2_bp.route("/coaching/start", methods=["POST"])
@require_auth
def v2_coaching_start():
    """Open a micro-coaching session on one snippet.

    Body: { "snippet_id": "<uuid>" }

    Validates the user owns the snippet and that the admin has left a
    comment (no comment ⇒ nothing to coach about). Creates a
    coaching_sessions row in the awareness stage.

    Response (200):
        {
            "coaching_id": str,
            "intent": "stress" | "charisma",
            "awareness_message": str,   # admin_comment, served verbatim
            "source_snippet": {
                "id": str, "transcript": str | None, "audio_url": str | None,
                "duration_ms": int | None
            }
        }
    """
    try:
        body = request.get_json(silent=True) or {}
        snippet_id = (body.get("snippet_id") or "").strip()
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "snippet_id must be a UUID"}), 400

        user_id = request.user_id
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "Snippet not found or not yours.",
            }), 404

        admin_comment = (snippet.get("admin_comment") or "").strip()
        if not admin_comment:
            return jsonify({
                "code": "SNIPPET_NOT_COACHABLE",
                "error": "This snippet has no coach comment yet — nothing to coach on.",
            }), 422

        intent = _coach_intent_for_snippet(snippet)
        # Both 'stress' and 'charisma' intents are now live; the prompt
        # router in v2_coaching_turn picks the right system prompt.
        coaching = db.create_coaching_session(user_id, snippet_id, intent)
        if not coaching:
            return jsonify({"code": "V2_ERROR", "error": "Failed to start coaching"}), 500

        return jsonify({
            "coaching_id": str(coaching.get("id")),
            "intent": intent,
            "awareness_message": admin_comment,
            "source_snippet": {
                "id": str(snippet.get("id")),
                "transcript": snippet.get("transcript"),
                "audio_url": snippet.get("audio_url"),
                "duration_ms": snippet.get("duration_ms"),
            },
        }), 200

    except Exception as e:
        logger.error("coaching/start failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to start coaching"}), 500


@v2_bp.route("/coaching/<coaching_id>", methods=["GET"])
@require_auth
def v2_coaching_get(coaching_id):
    """Re-hydrate a coaching session — survive reloads of /coach/[id].

    Returns the same shape as /coaching/start except with current_stage
    and trial_session_id reflecting any progress already made.

    404 GET semantics: NOT_FOUND covers both "doesn't exist" and "owned
    by someone else" so we don't leak coaching id existence.
    """
    try:
        if not _is_valid_uuid(coaching_id):
            return jsonify({"code": "INVALID_INPUT", "error": "coaching_id must be a UUID"}), 400
        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({
                "code": "COACHING_NOT_FOUND",
                "error": "Coaching session not found.",
            }), 404
        snippet = db.get_snippet_by_id(coaching.get("source_snippet_id"), user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "Source snippet missing.",
            }), 404
        return jsonify({
            "coaching_id": str(coaching.get("id")),
            "intent": coaching.get("intent"),
            "current_stage": coaching.get("current_stage"),
            "awareness_message": (snippet.get("admin_comment") or "").strip(),
            "source_snippet": {
                "id": str(snippet.get("id")),
                "transcript": snippet.get("transcript"),
                "audio_url": snippet.get("audio_url"),
                "duration_ms": snippet.get("duration_ms"),
            },
            "trial_session_id": coaching.get("trial_session_id"),
        }), 200
    except Exception as e:
        logger.error("coaching/<id> failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load coaching"}), 500


@v2_bp.route("/coaching/turn", methods=["POST"])
@require_auth
def v2_coaching_turn():
    """Run one LLM turn of the awareness stage.

    LIVE — drives the /coach/<id> coach-invite deep-link (FE seam-7a):
    src/app/coach/[coachingId]/page.tsx → /api/coaching/turn → here. Do
    NOT excise in a dead-route sweep; it has no inbound link from the main
    nav but is reached by direct URL, so a reference search comes up empty.


    Body: { "coaching_id": "<uuid>", "user_message": "..." }

    Loads the coaching session + source snippet, builds the awareness
    prompt with admin_comment / transcript / user_message context, calls
    GPT, parses the `|||` + `[ADVANCE]` shape, and advances to the trial
    stage when [ADVANCE] is present.

    Response (200):
        {
            "bubbles": [str, str],   # second may be empty if model
                                     # forgot the delimiter
            "advance": bool,
            "next_stage": "awareness" | "trial" | "complete"
        }
    """
    try:
        body = request.get_json(silent=True) or {}
        coaching_id = (body.get("coaching_id") or "").strip()
        user_message = (body.get("user_message") or "").strip()

        if not _is_valid_uuid(coaching_id):
            return jsonify({"code": "INVALID_INPUT", "error": "coaching_id must be a UUID"}), 400
        if not user_message:
            return jsonify({"code": "INVALID_INPUT", "error": "user_message is required"}), 400

        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({"code": "COACHING_NOT_FOUND", "error": "Coaching session not found"}), 404
        if coaching.get("current_stage") == "complete":
            return jsonify({
                "code": "COACHING_COMPLETE",
                "error": "This coaching loop is already complete.",
            }), 409

        snippet = db.get_snippet_by_id(coaching.get("source_snippet_id"), user_id=user_id)
        if not snippet:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Source snippet missing"}), 404

        intent = coaching.get("intent") or "stress"
        base_system_prompt = _system_prompt_for_intent(intent)

        # ── Long-term profile injection ─────────────────────────────
        # Pulls the admin-set custom_llm_instructions (Admin Tab 3) +
        # the user's behavioral_profile classification (e.g. Stressor,
        # Racer, Freezer). When either is present, we append a
        # [USER LONG-TERM PROFILE] block to the system prompt so the
        # coaching turn adapts to who this specific user is rather
        # than coaching every learner identically.
        system_prompt = _augment_coaching_system_prompt(base_system_prompt, user_id)

        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return jsonify({"code": "LLM_UNAVAILABLE", "error": "Coaching LLM is not configured"}), 503

        admin_comment = (snippet.get("admin_comment") or "").strip()
        user_transcript = (snippet.get("transcript") or "").strip()

        user_content = (
            f'admin_comment: "{admin_comment}"\n'
            f'user_transcript: "{user_transcript}"\n'
            f'user_first_reply: "{user_message}"'
        )

        # Persist the user side of the exchange before calling the LLM.
        # If the LLM call fails downstream we still want admins to see
        # what the user actually said. Best-effort — append never blocks
        # the response if the JSONB column hasn't been migrated yet.
        try:
            db.append_coaching_message(coaching_id, "user", user_message)
        except Exception as msg_err:
            logger.warning("coaching/turn user-msg append failed: %s", msg_err)

        # Phase 0 — structured output. The model returns a strict
        # JSON object {validation_bubble, challenge_bubble, advance}
        # so the prior |||  + [ADVANCE] string-parsing dance is gone.
        # System prompt still tells the model what each field means;
        # the schema enforces shape, the prompt enforces semantics.
        from services.llm_schemas import (
            AWARENESS_TURN_SCHEMA,
            response_format as _response_format,
        )
        structured_prompt = (
            f"{system_prompt}\n\n"
            "RESPONSE SHAPE — return JSON only with exactly these keys:\n"
            "  validation_bubble — 1-2 sentence acknowledgment of the user's reply.\n"
            "  challenge_bubble  — the mic-on instruction telling them what to do next.\n"
            "  advance           — true when the user is ready to record the trial.\n"
        )

        try:
            response = service.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": structured_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.6,
                max_tokens=240,
                response_format=_response_format(AWARENESS_TURN_SCHEMA),
            )
            raw = response.choices[0].message.content or ""
        except Exception as llm_err:
            logger.error("coaching/turn LLM call failed: %s", llm_err, exc_info=True)
            return jsonify({
                "code": "LLM_ERROR",
                "error": "Coach is unavailable. Please try again in a moment.",
            }), 502

        # Schema enforces the shape — only failure left is a transport
        # blip that returns malformed text. We log + fall back below.
        bubble_1 = ""
        bubble_2 = ""
        advance = False
        try:
            parsed = json.loads(raw) if raw else {}
            bubble_1 = (parsed.get("validation_bubble") or "").strip()
            bubble_2 = (parsed.get("challenge_bubble") or "").strip()
            advance = bool(parsed.get("advance"))
        except (json.JSONDecodeError, ValueError, AttributeError) as parse_err:
            logger.warning(
                "coaching/turn: structured output not parseable: %r err=%s",
                raw[:300], parse_err,
            )

        if not bubble_1 and not bubble_2:
            # Total LLM failure — return a graceful fallback instead of
            # an empty payload so the user always sees something. The
            # bubbles come from the skill registry so a degraded
            # response stays tonally consistent with the active skill.
            fallback_skill = _get_skill(intent) or _get_skill("stress")
            if fallback_skill is not None:
                bubble_1 = fallback_skill.fallback_validation_bubble
                bubble_2 = fallback_skill.fallback_challenge_bubble
            advance = True

        # Persist the AI side of the exchange. Both bubbles together so
        # the admin transcript reads as one assistant message rather
        # than two synthetic ones — the `||| / [ADVANCE]` is an LLM
        # output detail, not a semantic separation.
        try:
            ai_content_parts = [b for b in (bubble_1, bubble_2) if b]
            db.append_coaching_message(
                coaching_id,
                "assistant",
                " ||| ".join(ai_content_parts),
                extra={
                    "bubbles": [bubble_1, bubble_2],
                    "advance": advance,
                    "raw_llm_output": raw,
                },
            )
        except Exception as msg_err:
            logger.warning("coaching/turn assistant-msg append failed: %s", msg_err)

        next_stage = "trial" if advance else coaching.get("current_stage", "awareness")
        if advance and coaching.get("current_stage") != "trial":
            db.update_coaching_stage(coaching_id, "trial")

        return jsonify({
            "bubbles": [bubble_1, bubble_2],
            "advance": advance,
            "next_stage": next_stage,
        }), 200

    except Exception as e:
        logger.error("coaching/turn failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Coaching turn failed"}), 500


@v2_bp.route("/coaching/state-machine/turn", methods=["POST"])
@require_auth
def v2_coaching_state_machine_turn():
    """One turn of the 5-step coaching state machine.

    Parallel to ``/v2/coaching/turn`` (which runs the older
    awareness→trial loop). Doesn't touch the existing flow — the
    frontend opts in by hitting this endpoint instead.

    Body::

        {
          "coaching_id": "<uuid>",   // existing coaching_sessions row
          "user_message": "..."       // optional on the very first
                                      // call (STEP 1 has no user
                                      // message yet — the AI opens)
        }

    Response (200) — mirrors the structured-output schema verbatim
    plus an ``ai_message_id`` placeholder the frontend can ignore::

        {
          "narration":    str,
          "step":         1..5,
          "triggers":     [str, ...],
          "end":          bool,
          "current_question_position": 1..5 | null,  // Director's
                                                      // Script position
          "snippet_player":   { snippet_id } | omitted,
          "label_buttons":    { snippet_id, yes_label, no_label } | omitted,
          "acoustic_targets": { target_wpm, ... } | omitted
        }

    Persists each turn to ``coaching_sessions.messages`` so the
    admin transcript view replays the full chat. The state itself
    is implicit in the conversation history — we hand the LLM the
    full prior turns and it follows the protocol from the system
    prompt.
    """
    try:
        body = request.get_json(silent=True) or {}
        coaching_id = (body.get("coaching_id") or "").strip()
        user_message = (body.get("user_message") or "").strip()
        # Optional language hint for STEP 1 (which has no prior
        # user message to infer language from). Accept either key
        # so the frontend BFF doesn't have to be picky. Plain
        # display name ("Polish", "English") or ISO code — the
        # prompt builder hands it to the LLM verbatim.
        user_language_hint = (
            body.get("user_language")
            or body.get("user_language_hint")
            or body.get("language")
            or ""
        ).strip() or None

        if not _is_valid_uuid(coaching_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "coaching_id must be a UUID",
            }), 400

        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({
                "code": "COACHING_NOT_FOUND",
                "error": "Coaching session not found",
            }), 404
        if coaching.get("current_stage") == "complete":
            return jsonify({
                "code": "COACHING_COMPLETE",
                "error": "This coaching loop is already complete.",
            }), 409

        snippet = db.get_snippet_by_id(
            coaching.get("source_snippet_id"), user_id=user_id,
        )
        if not snippet:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "Source snippet missing",
            }), 404

        # Acoustic targets are computed against the snippet's parent
        # session — its global metrics are the user's baseline for
        # this conversation. Falls through to None targets when the
        # session row hasn't been finalized yet (the prompt builder
        # drops missing lines).
        parent_session: dict = {}
        if snippet.get("session_id"):
            try:
                parent_session = db.v2_get_session_by_id(
                    snippet.get("session_id"),
                ) or {}
            except Exception as e:
                logger.warning(
                    "coaching/state-machine: parent session load failed sid=%s err=%s",
                    snippet.get("session_id"), e,
                )

        from services.coaching_state_machine import (
            compute_acoustic_targets,
            build_state_machine_system_prompt,
            STATE_MACHINE_RESPONSE_SCHEMA,
            parse_state_machine_response,
        )
        targets = compute_acoustic_targets(
            global_wpm=parent_session.get("global_wpm"),
            global_fillers=parent_session.get("global_fillers"),
            global_dynamic_db=parent_session.get("global_dynamic_db"),
            session_duration_ms=parent_session.get("duration_ms"),
        )

        # Director's Script — admin-edited array wins; fall through
        # to AI-pre-generated draft; empty list if neither exists
        # (the prompt handles the empty case by skipping straight
        # from STEP 2 to STEP 8).
        director_script_questions = (
            parent_session.get("final_human_next_questions")
            or parent_session.get("ai_predicted_next_questions")
            or []
        )
        if not isinstance(director_script_questions, list):
            director_script_questions = []

        # First-name + org-context are nice-to-haves; missing both
        # is fine, the prompt builder degrades gracefully.
        first_name: str | None = None
        try:
            details = db.v2_get_student_details(user_id) or {}
            full_name = (details.get("name") or "").strip()
            if full_name:
                first_name = full_name.split()[0]
        except Exception:
            pass

        # Admin's private notes about this user become a don't-ask
        # block at the end of the system prompt. Best-effort read —
        # a DB hiccup just means the block is missing, not a 500.
        admin_dont_ask_notes: str | None = None
        try:
            _settings = db.get_user_settings(user_id) or {}
            admin_dont_ask_notes = (
                _settings.get("private_admin_notes") or None
            )
        except Exception as e:
            logger.warning(
                "coaching/state-machine: private_admin_notes load "
                "failed user=%s: %s", user_id, e,
            )

        system_prompt = build_state_machine_system_prompt(
            snippet=snippet,
            acoustic_targets=targets,
            director_script_questions=director_script_questions,
            user_first_name=first_name,
            user_org_context=None,
            user_language_hint=user_language_hint,
            coaching_id=coaching_id,
            admin_dont_ask_notes=admin_dont_ask_notes,
        )

        # Build the LLM's view of the conversation. The system
        # prompt encodes the protocol; the message history tells
        # the model which step we're on.
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
        ]
        prior = coaching.get("messages") or []
        if isinstance(prior, list):
            for m in prior:
                role = (m.get("role") or "").strip()
                content = (m.get("content") or "").strip()
                # 'trial_audio' rows aren't part of the state-machine
                # exchange — they're recordings dropped into the
                # legacy awareness flow. Filter them out so the LLM
                # doesn't see binary placeholders.
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # On the very first call (no user_message and no prior
        # messages) we still ask the LLM for STEP 1 — the system
        # prompt instructs it to open without waiting for input.
        if user_message:
            messages.append({"role": "user", "content": user_message})

        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return jsonify({
                "code": "LLM_UNAVAILABLE",
                "error": "Coach LLM not configured",
            }), 503

        try:
            response = service.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
                max_tokens=600,
                response_format={
                    "type": "json_schema",
                    "json_schema": STATE_MACHINE_RESPONSE_SCHEMA,
                },
            )
            raw = response.choices[0].message.content or ""
        except Exception as llm_err:
            logger.error(
                "coaching/state-machine: LLM call failed: %s",
                llm_err, exc_info=True,
            )
            return jsonify({
                "code": "LLM_ERROR",
                "error": "Coach is unavailable. Please try again.",
            }), 502

        parsed = parse_state_machine_response(raw)
        if parsed is None:
            return jsonify({
                "code": "LLM_PARSE_ERROR",
                "error": (
                    "Coach response was malformed. Please send again."
                ),
            }), 502

        # Persist user side first so the admin transcript reads
        # chronologically even if assistant persist fails downstream.
        if user_message:
            try:
                db.append_coaching_message(
                    coaching_id, "user", user_message,
                )
            except Exception as msg_err:
                logger.warning(
                    "coaching/state-machine: user msg append failed: %s",
                    msg_err,
                )

        try:
            db.append_coaching_message(
                coaching_id,
                "assistant",
                parsed.get("narration") or "",
                extra={
                    "step": parsed.get("step"),
                    "current_question_position": parsed.get(
                        "current_question_position"
                    ),
                    "triggers": parsed.get("triggers") or [],
                    "end": bool(parsed.get("end")),
                    "snippet_player": parsed.get("snippet_player"),
                    "label_buttons": parsed.get("label_buttons"),
                    "acoustic_targets": parsed.get("acoustic_targets"),
                    "raw_llm_output": raw,
                },
            )
        except Exception as msg_err:
            logger.warning(
                "coaching/state-machine: assistant msg append failed: %s",
                msg_err,
            )

        # When the LLM flags end=true on STEP 8, advance the
        # coaching_session to 'complete' so subsequent POSTs return
        # COACHING_COMPLETE. Best-effort; the chat already showed
        # the closing card by this point.
        if parsed.get("end") and coaching.get("current_stage") != "complete":
            try:
                db.update_coaching_stage(coaching_id, "complete")
            except Exception as stage_err:
                logger.warning(
                    "coaching/state-machine: stage advance failed: %s",
                    stage_err,
                )

        return jsonify(parsed), 200

    except Exception as e:
        logger.error(
            "coaching/state-machine/turn failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "State machine turn failed",
        }), 500


@v2_bp.route("/chat/session-state", methods=["GET"])
@require_auth
def v2_chat_session_state():
    """Drive the /chat route's UI state for a returning user.

    The frontend killed the /results page; /chat is now the
    single destination after onboarding. This endpoint tells it
    what mode to render in.

    State machine::

        NO_SESSION     — user has no v2_sessions row at all (fresh
                          signup, never recorded). Frontend should
                          route them into the onboarding interview.

        PENDING_COACH  — latest session exists but
                          results_published_at IS NULL (admin
                          hasn't reviewed + published yet).
                          Frontend renders the waiting / FAQ chat;
                          POST /v2/chat/query is fully usable
                          against the Master Document in this
                          state.

        REVIEW_LOOP    — latest session has been published. Payload
                          includes the snippets + admin_comments
                          so the frontend can drop straight into
                          the snippet-review chat without a second
                          round-trip to /v2/user/results/<id>.

    Response (200)::

        {
          "state": "NO_SESSION" | "PENDING_COACH" | "REVIEW_LOOP",
          "session_id": "<uuid>" | null,
          "created_at": "<iso8601>" | null,
          "results_published_at": "<iso8601>" | null,

          // present iff state == "REVIEW_LOOP"
          "snippets":         [ ... full snippet objects, see below ],
          // kpi_score + charisma_profile removed (AC-9 — classifier/
          // appraisal data is never serialized to the user).
          "ai_summary":       string | null
        }

    Each REVIEW_LOOP snippet matches the shape /user/results/<id>
    returns so the frontend can reuse its existing renderer
    without a second translation layer.

    Why a separate endpoint when /user/sessions/current exists:
    /sessions/current emits the legacy 5-status vocabulary
    (no_session / processing / pending_review / completed /
    error). The frontend's /chat router wants the new
    3-state vocabulary explicitly + the snippet payload inline.
    We could overload /sessions/current, but doing that risks
    breaking the homework + admin routing surfaces that read
    its current shape. A dedicated endpoint is cheaper.
    """
    try:
        user_id = request.user_id
        session = db.v2_get_latest_session_for_user(user_id)

        if not session:
            return jsonify({
                "state": "NO_SESSION",
                "session_id": None,
                "created_at": None,
                "results_published_at": None,
            }), 200

        session_id = str(session.get("id"))
        published_at = session.get("results_published_at")
        base = {
            "session_id": session_id,
            "created_at": session.get("created_at"),
            "results_published_at": published_at,
        }

        if not published_at:
            # Admin hasn't clicked Publish yet. The /v2/chat/query
            # endpoint is the right surface for the user to ask
            # questions while they wait — same Master-Document
            # grounding, no special-casing needed here.
            return jsonify({"state": "PENDING_COACH", **base}), 200

        # REVIEW_LOOP — load published snippets in the same shape
        # /user/results/<id> uses, so the frontend renderer is
        # reusable. We resolve audio URLs the same way too: the
        # admin Files tab, the /results page, and this endpoint all
        # serve the same playable URL.
        try:
            raw_snippets = db.v2_get_results_snippets_for_session(
                session_id, user_id,
            ) or []
        except Exception as snip_err:
            logger.warning(
                "chat/session-state: snippet load failed sid=%s err=%s",
                session_id, snip_err,
            )
            raw_snippets = []

        snippets = [
            {
                "id": s.get("id"),
                "snippet_type": s.get("snippet_type"),
                "admin_comment": s.get("admin_comment"),
                "audio_url": _resolve_snippet_audio_url(s),
                "transcript": s.get("transcript"),
                "turn_number": s.get("turn_number"),
                "question_text": s.get("question_text"),
                "question_tone": s.get("question_tone"),
                "start_offset_ms": s.get("start_offset_ms") or 0,
                "duration_ms": s.get("duration_ms"),
                "metrics": {
                    "wpm": s.get("wpm"),
                    "fillers": s.get("fillers"),
                    "pause_ms": s.get("pause_ms"),
                    "dynamic_db": s.get("dynamic_db"),
                    "pitch_center": s.get("pitch_center"),
                    "energy": s.get("energy"),
                },
            }
            for s in raw_snippets
        ]

        # Phase 18.x split-sinks Option A — ai_summary surfaces the
        # immutable AI draft so admin edits don't leak to the user.
        return jsonify({
            "state": "REVIEW_LOOP",
            **base,
            "snippets": snippets,
            "ai_summary": (
                session.get("session_kpi_narrative_ai_draft")
                or session.get("ai_task_alignment_comment")
            ),
        }), 200

    except Exception as e:
        logger.error(
            "chat/session-state failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to evaluate session state",
        }), 500


def _persist_chat_turn(
    user_id, question, answer, *, suggested_action=None, bubbles=None,
    intent=None, user_client_id=None, user_created_at=None,
):
    """BE-owned persistence of one Lounge chat turn (founder #2 — bubbles must
    never disappear). Writes the user message + the bot reply to lounge_messages
    so the thread survives reload + relogin on ANY device, rather than relying on
    a best-effort FE append that can silently fail or race the auth token.

    Idempotent: client_ids are deterministic (uuid5), so re-posting the same turn
    is a no-op (UNIQUE(user_id, client_id)). The user-turn id prefers the FE's
    own client_id (so it de-dupes with the FE's optimistic local copy + preserves
    merge ordering); the bot-turn id derives from it → exactly one bot row per
    user turn. The bot row carries suggested_action + bubbles in metadata so the
    FE reconstructs the contextual chip (trainings / strong_sides / audit) on
    rehydrate — the chip that was vanishing on relogin. Mirrors the existing
    server-insert pattern (publish 'insights ready' card, session cadence).

    Returns the bot row's client_id (so the FE can de-dupe its optimistic
    bubble) or None on failure. Best-effort — never raises to the route.
    """
    from datetime import datetime as _dt, timezone as _tz

    q = (question or "").strip()
    a = (answer or "").strip()
    if not user_id or not a:
        return None

    def _is_uuid(v):
        try:
            uuid.UUID(str(v))
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    # User-turn id: prefer the FE's own (dedupe + merge order); else derive
    # deterministically from the text so an identical re-post stays a no-op.
    if user_client_id and _is_uuid(user_client_id):
        u_id = str(user_client_id)
    else:
        u_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL, f"willab-chat-user:{user_id}:{q}"))
    # Bot-turn id derives from the user-turn id → one bot row per user turn.
    b_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"willab-chat-bot:{u_id}"))

    now_iso = _dt.now(_tz.utc).isoformat()
    u_ts = (user_created_at if isinstance(user_created_at, str)
            and user_created_at.strip() else now_iso)

    rows = []
    if q:
        rows.append({
            "client_id": u_id, "role": "user", "kind": "text",
            "body": q, "metadata": None, "client_created_at": u_ts,
        })
    meta = {"intent": intent}
    if suggested_action:
        meta["suggested_action"] = suggested_action
    if bubbles:
        meta["bubbles"] = bubbles
    rows.append({
        "client_id": b_id, "role": "bot", "kind": "text",
        "body": a, "metadata": meta, "client_created_at": now_iso,
    })

    try:
        db.insert_lounge_messages(str(user_id), rows)
        return b_id
    except Exception as e:
        logger.warning(
            "chat/query: persist turn failed user=%s: %s", user_id, e)
        return None


@v2_bp.route("/chat/query", methods=["POST"])
@optional_auth
def v2_chat_query():
    """Unified chat orchestrator for the /chat page.

    Powers the post-signup single-thread chat surface. The LLM
    runs under services.master_doc_rag with the verbatim Master
    Document as its only source of truth, plus capability-boundary
    + upload-intent rules. Returns structured output the frontend
    uses to drive UI state (showing/hiding the upload dropzone).

    Body::

        {
          "question": "what is this?",
          "history":  [                          // optional
            { "role": "user",      "content": "..." },
            { "role": "assistant", "content": "..." }
          ],
          // #2 — BE-owned thread persistence (signed-in only). Opt-in: when
          // persist=true, the user + bot turns are written to lounge_messages
          // server-side so they survive reload + relogin (no race-prone FE
          // append). client_id = the user message's FE id (idempotency +
          // dedupe with the FE's optimistic copy); client_created_at = its
          // FE timestamp (ordering). All optional; ignored when signed out.
          "persist":           bool,             // optional, default false
          "client_id":         "uuid",           // optional (user msg id)
          "client_created_at": "iso8601"         // optional (user msg ts)
        }

    Responses::

        200 {
              "answer":         str,    # the chat bubble text
              "bubbles":        [str],  # pre-split chat bubbles (FE #157)
              "show_record_ui": bool,   # per-turn record affordance
                                         # toggle (RULE I) — in-app mic
              "suggested_action": str | None,  # the one contextual button
              "debug":          {...},  # model + history_used / error
              # present only when persist=true + signed in:
              "persisted":         bool,   # bot turn written server-side
              "persisted_client_id": str   # the bot row's client_id (FE dedupe)
            }
        400 INVALID_INPUT — question missing or not a string
        500 V2_ERROR

    show_record_ui semantics:
      • show_record_ui — TRUE on the turn where the user expressed
        intent to RECORD in-app via the chat's mic ("can I record
        here?", "let me just record it", etc.). RULE I.
      • Per-turn signal — frontend must NOT cache it across turns;
        each answer carries the current state.
      • (show_upload_ui was removed — uploads are off and FE seam-7b
        cleared the field; upload intent still redirects to record
        per RULE G, just without a flag.)

    Why @optional_auth: the willab Lounge is an unsigned-home
    (design §3) — the Lounge bot / librarian must answer without a
    session. Signed-in requests carry request.user_id (so the
    strong-sides library + admin notes layer in); anonymous requests
    get request.user_id=None and the general bot (no per-user reads/
    writes, no DSP attribution). NEVER 401s — signed-out chat works.

    ─────────────────────────────────────────────────────────────────
    Phase Stress-Contrast (BE-3) — dual-mode body parsing
    ─────────────────────────────────────────────────────────────────
    This endpoint additively supports a ``multipart/form-data`` body
    when the frontend captures audio alongside the typed/dictated
    question. Path A (text → LLM) is unchanged. Path B (audio → DSP)
    fires asynchronously via ``casual_voice_analytics`` and never
    blocks the HTTP response.

    Multipart fields (all when Path B applies):
      - question:              str (required; same semantics as JSON)
      - history:               JSON-stringified list (optional)
      - audio_file:            webm/opus blob (required for Path B)
      - transcript_source:     "web_speech" | "server_whisper"
                                (default "web_speech")
      - audio_duration_sec:    float hint (optional)

    JSON callers (the existing path) keep the exact same request
    and response shape — no regression.
    """
    try:
        # ── Body parsing — branch on content-type so existing JSON
        # callers keep working unchanged (compatibility contract C1
        # from BE-3 prompt). Multipart adds the audio side without
        # touching the JSON code path.
        content_type = (request.content_type or "").lower()
        is_multipart = "multipart/form-data" in content_type

        audio_bytes: bytes | None = None
        transcript_source = "web_speech"
        audio_duration_sec: float = 0.0

        # #2 — BE-owned thread persistence (signed-in only; FE opt-in). The FE
        # sends persist=true plus the user message's client_id/client_created_at
        # so this turn (user + bot) is written to lounge_messages server-side and
        # survives reload + relogin on any device — instead of the race-prone
        # best-effort FE append that was dropping bubbles + chips.
        persist_thread = False
        user_client_id: str | None = None
        user_created_at: str | None = None

        if is_multipart:
            question = (request.form.get("question") or "").strip()
            history_raw = request.form.get("history")
            history: list | None = None
            if history_raw:
                try:
                    import json as _json
                    parsed = _json.loads(history_raw)
                    if isinstance(parsed, list):
                        history = parsed
                except Exception:
                    # Same leniency as the JSON path — bad history
                    # never breaks the answer.
                    history = None

            persist_thread = (request.form.get("persist") or "").strip().lower() in (
                "1", "true", "yes", "on",
            )
            user_client_id = request.form.get("client_id") or None
            user_created_at = request.form.get("client_created_at") or None

            audio_file = request.files.get("audio_file")
            if audio_file is not None:
                try:
                    audio_bytes = audio_file.read()
                except Exception as read_err:
                    logger.warning(
                        "chat/query: audio read failed user=%s err=%s "
                        "— continuing text-only",
                        request.user_id, read_err,
                    )
                    audio_bytes = None

                ts_raw = (
                    request.form.get("transcript_source") or ""
                ).strip().lower()
                if ts_raw in ("web_speech", "server_whisper"):
                    transcript_source = ts_raw

                try:
                    audio_duration_sec = float(
                        request.form.get("audio_duration_sec") or "0"
                    )
                except (TypeError, ValueError):
                    audio_duration_sec = 0.0
        else:
            body = request.get_json(silent=True) or {}
            question = body.get("question")
            history = body.get("history")
            if history is not None and not isinstance(history, list):
                history = None
            persist_thread = bool(body.get("persist"))
            _cid = body.get("client_id")
            user_client_id = _cid if isinstance(_cid, str) else None
            _cca = body.get("client_created_at")
            user_created_at = _cca if isinstance(_cca, str) else None

        if not isinstance(question, str) or not question.strip():
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "question must be a non-empty string",
            }), 400

        def _finalize(resp, *, intent=None):
            """Persist this turn server-side (founder #2) when the FE opted in
            and the caller is signed in, then return the 200. The bot row carries
            suggested_action + bubbles in its metadata so the contextual chip
            (trainings / strong_sides / best-presentation) reconstructs on
            rehydrate — exactly what was vanishing on relogin. Best-effort: a
            persist failure never fails the chat response."""
            if persist_thread and request.user_id:
                bot_cid = _persist_chat_turn(
                    request.user_id, question, resp.get("answer"),
                    suggested_action=resp.get("suggested_action"),
                    bubbles=resp.get("bubbles"), intent=intent,
                    user_client_id=user_client_id,
                    user_created_at=user_created_at,
                )
                resp["persisted"] = bool(bot_cid)
                if bot_cid:
                    resp["persisted_client_id"] = bot_cid
            # Token pricing: charge the turn AFTER answering, never before.
            # No ref_id — chat is legitimately repeatable, so it must not hit
            # the ledger's once-per-ref index. The FE deliberately does NOT
            # surface a per-message price (150 tokens is noise beside a 35,000
            # coach review, and a per-keystroke meter turns a conversation into
            # a taxi ride) — it still charges, it just isn't shown.
            if request.user_id:
                try:
                    from services.token_account import charge as _charge
                    _charge(str(request.user_id), "chat")
                except Exception:
                    pass
            return jsonify(resp), 200

        # ── Life Panel hashtag router (founder 2026-07-26) — the FIRST
        # intercept, and the feature's ONLY contact point with this file.
        #
        # It fires on a leading `#tag` from a signed-in user who has consented
        # to the Life Panel, and on nothing else. Three guards, cheapest
        # first, so a normal chat turn pays ~nothing:
        #   1. LIFE_PANEL_ENABLED (default 0) — off, and this block is a
        #      boolean check that falls straight through.
        #   2. signed in — anonymous Lounge chat never reaches it.
        #   3. handle_note returns None for an untagged message BEFORE any DB
        #      read, and None for a non-consented user. None ⇒ we do not
        #      touch this turn at all.
        #
        # N3 is the contract: for a non-participating user every response on
        # this endpoint is byte-identical to main. That is why the fall-
        # through is `return None → keep going` rather than any modified
        # answer, and why the whole block is inside its own try/except — a
        # broken Life Panel must cost the panel, never the chat.
        if request.user_id and getattr(config, "LIFE_PANEL_ENABLED", False):
            try:
                from services.life_chat import handle_note
                from services.master_doc_rag import split_answer_into_bubbles
                _ln = handle_note(request.user_id, question.strip())
                if _ln:
                    _ans = _ln.get("answer") or ""
                    # The founder's own words, returned at the moment they
                    # apply — appended only when the wall actually had
                    # something above the relevance floor.
                    _ph = _ln.get("phrase") or {}
                    if _ph.get("body"):
                        _ans = f"{_ans}\n\n“{_ph['body']}”"
                    return _finalize({
                        "answer": _ans,
                        "bubbles": split_answer_into_bubbles(_ans),
                        "show_record_ui": False,
                        "suggested_action": None,
                        "debug": {"intent": "life_panel",
                                  "route": _ln.get("route"),
                                  "link": _ln.get("link")},
                    }, intent="life_panel")
            except Exception as _le:
                logger.warning(
                    "chat/query: life-panel intercept failed user=%s: %s",
                    request.user_id, _le,
                )

        # ── Goal-update intercept (Prompt A §6 C4) — BEFORE the librarian.
        # §0: never add rules to master_doc_rag (attention ceiling). A
        # signed-in user saying "change my goal to X" (any language) updates
        # user_settings.profile_goal and gets an in-language confirmation;
        # the librarian is short-circuited for that turn. Cheap pre-gate
        # inside, so normal chat turns spend no extra LLM call. Best-effort:
        # any failure falls through to the normal answer.
        if request.user_id:
            try:
                from services.goal_update import handle_goal_update
                from services.master_doc_rag import split_answer_into_bubbles
                _gu = handle_goal_update(request.user_id, question.strip())
                if _gu and _gu.get("answer"):
                    return _finalize({
                        "answer": _gu["answer"],
                        "bubbles": split_answer_into_bubbles(_gu["answer"]),
                        "show_record_ui": False,
                        "suggested_action": None,
                        "debug": {
                            "intent": "goal_update",
                            "new_goal": _gu.get("new_goal"),
                        },
                    }, intent="goal_update")
            except Exception as _ge:
                logger.warning(
                    "chat/query: goal-update intercept failed user=%s: %s",
                    request.user_id, _ge,
                )

        # ── Audit intercept (Prompt C §5) — BEFORE the librarian (§0: no
        # master_doc_rag rule edits). A signed-in user asking for their audit
        # gets a short bubble + the audit button (suggested_action="audit")
        # opening the audits page. Deterministic keyword pre-gate inside, so
        # normal chat pays nothing. Best-effort: any failure falls through.
        # Prompt D: RETIRED by default (the Best-Presentation replaces the
        # audit). AUDIT_SURFACE_ENABLED=1 restores it (endpoints stay dormant).
        if request.user_id and getattr(config, "AUDIT_SURFACE_ENABLED", False):
            try:
                from services.audit_intent import handle_audit_intent
                from services.master_doc_rag import split_answer_into_bubbles
                _ai = handle_audit_intent(request.user_id, question.strip())
                if _ai and _ai.get("suggested_action") == "audit":
                    _ans = _ai.get("answer") or ""
                    return _finalize({
                        "answer": _ans,
                        "bubbles": split_answer_into_bubbles(_ans),
                        "show_record_ui": False,
                        "suggested_action": "audit",
                        "debug": {"intent": "audit"},
                    }, intent="audit")
            except Exception as _ae:
                logger.warning(
                    "chat/query: audit intercept failed user=%s: %s",
                    request.user_id, _ae,
                )

        # ── Lounge-bot deterministic intercepts (chat-audit 2026-06-21) —
        # BEFORE the librarian (§0: keep these OUT of master_doc_rag's mega-
        # prompt; the attention ceiling is full and the probe grades the LLM
        # path). Crisis (safety) → record CTA (the acquisition lever, #4:
        # show_record_ui + suggested_action="record_again", reversing #119 for
        # CLEAR intent) → off-mission generative deflect. Runs for anonymous +
        # signed-in; the goal/audit intercepts above are signed-in-only + more
        # specific, so they win for those phrasings. Best-effort.
        try:
            from services.chat_intents import detect_chat_intent
            from services.master_doc_rag import split_answer_into_bubbles
            _ci = detect_chat_intent(question.strip())
            if _ci:
                _ans = _ci["answer"]
                return _finalize({
                    "answer": _ans,
                    "bubbles": split_answer_into_bubbles(_ans),
                    "show_record_ui": _ci["show_record_ui"],
                    "suggested_action": _ci["suggested_action"],
                    "debug": {"intent": _ci["intent"]},
                }, intent=_ci["intent"])
        except Exception as _cie:
            logger.warning("chat/query: chat-intent intercept failed: %s", _cie)

        # ── Path A — LLM answer (the only thing the HTTP response
        # carries back). Unchanged from the pre-BE-3 behavior.
        # Pull admin's private notes for this user → don't-ask block
        # in the FAQ chat system prompt. @require_auth guarantees a
        # user_id; best-effort on the DB read.
        # Per-user layers (admin don't-ask notes + the strong-sides
        # library) apply only when signed in. Anonymous (unsigned-home,
        # §3) gets the general bot — no per-user reads. Both best-effort.
        admin_dont_ask_notes: str | None = None
        library_entries: list | None = None
        if request.user_id:
            try:
                _settings = db.get_user_settings(request.user_id) or {}
                admin_dont_ask_notes = (
                    _settings.get("private_admin_notes") or None
                )
            except Exception as e:
                logger.warning(
                    "chat/query: private_admin_notes load failed "
                    "user=%s: %s", request.user_id, e,
                )

            # willab §3.12 — the user's strong-sides library (coach
            # notes) for the Lounge bot to retrieve/replay. The librarian
            # guardrail (no trajectory/scores) lives in answer_question.
            #
            # B3 — distinguish a GENUINE empty library ([]) from a transient
            # LOAD FAILURE (None). Both used to collapse to None via
            # `or None`, so a failed load read as "no notes" for a user who
            # actually has them — inconsistent turn-to-turn. Retry once, and
            # log every outcome so the real failure rate is measurable.
            #   library_entries == []   → genuinely no notes (bot may say so)
            #   library_entries is None → load FAILED after retry (NOT empty)
            for _attempt in (1, 2):
                try:
                    library_entries = db.get_strong_sides_library(
                        request.user_id
                    ) or []
                    logger.info(
                        "chat/query: library loaded user=%s entries=%d "
                        "(attempt %d)", request.user_id,
                        len(library_entries), _attempt,
                    )
                    break
                except Exception as e:
                    logger.warning(
                        "chat/query: library load failed user=%s "
                        "(attempt %d): %s", request.user_id, _attempt, e,
                    )
                    library_entries = None

        # BE-9 — the Life Panel's per-user block, for participating users only.
        # Retrieved at request time from the requesting user's OWN rows, capped
        # to the top few by relevance; the renderer in master_doc_rag trims and
        # caps again. Everyone else — flag off, not signed in, not consented —
        # passes None, so their prompt is byte-for-byte what it is today.
        # Best-effort: a failed load costs the grounding, never the answer.
        life_context = None
        if request.user_id and getattr(config, "LIFE_PANEL_ENABLED", False):
            try:
                from services.life_chat import has_consented
                if has_consented(request.user_id):
                    from services.life_engine import life_chat_context
                    life_context = life_chat_context(
                        request.user_id, question.strip())
            except Exception as _lce:
                logger.warning(
                    "chat/query: life context load failed user=%s: %s",
                    request.user_id, _lce,
                )

        from services.master_doc_rag import (
            answer_question, split_answer_into_bubbles,
        )
        payload, debug = answer_question(
            question.strip(),
            history=history,
            admin_dont_ask_notes=admin_dont_ask_notes,
            library_entries=library_entries,
            # B3 — None (after retry) means the load FAILED, not empty.
            library_load_failed=bool(request.user_id and library_entries is None),
            life_context=life_context,
        )

        # ── Path B — fire-and-forget DSP extraction. Spawned BEFORE
        # the jsonify so the daemon's stack frame exists by the time
        # the request worker recycles, but AFTER Path A so we never
        # delay the LLM. The dispatch itself is a thread.start() —
        # microseconds; safe to do before returning. Failure to
        # dispatch is logged and swallowed; the LLM answer still
        # ships.
        # Anonymous (unsigned-home) chat skips DSP capture — there's no
        # user to attribute the casual-voice benchmark to.
        if audio_bytes and request.user_id:
            try:
                from services.casual_voice_analytics import (
                    analyze_casual_audio_async,
                )
                analyze_casual_audio_async(
                    user_id=str(request.user_id),
                    # session_id is None for pure Lounge chat — the
                    # endpoint isn't session-bound. The column on
                    # casual_voice_benchmarks is nullable for this
                    # exact reason; see migration comment.
                    session_id=None,
                    audio_bytes=audio_bytes,
                    transcript=question.strip(),
                    duration_sec=audio_duration_sec,
                    transcript_source=transcript_source,
                )
            except Exception as cv_err:
                # The dispatcher should never raise (it's just a
                # thread.start), but defense-in-depth: a broken
                # casual-voice path MUST NOT take down the chat
                # response. Log and move on.
                logger.warning(
                    "chat/query: casual_voice dispatch failed "
                    "user=%s err=%s (non-fatal — LLM answer still "
                    "returned)",
                    request.user_id, cv_err,
                )

        # S1 — per-turn intent → the one contextual button the FE renders.
        # ("audit" is set by the audit intercept above, not the librarian, but
        # is a valid enum value so the FE contract stays consistent.)
        _sa = payload.get("suggested_action")
        if _sa not in ("strong_sides", "trainings", "audit"):
            _sa = None
        _answer = payload.get("answer", "")
        return _finalize({
            "answer": _answer,
            # FE #157 — pre-split chat bubbles (renders 1:1; falls back to
            # splitting `answer` on blank lines when absent). `answer` stays
            # the fallback.
            "bubbles": split_answer_into_bubbles(_answer),
            "show_record_ui": bool(payload.get("show_record_ui", False)),
            "suggested_action": _sa,
            "debug": debug,
        }, intent=(debug or {}).get("intent") or "faq")

    except Exception as e:
        logger.error("chat/query failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Chat query failed",
        }), 500


# ── Phase 9: admin RLHF + profile override ──────────────────────────────


# How many coaching-attempt annotations an admin needs before
# bulk-approve unlocks on the frontend. Exposed by the annotations
# count endpoint so the UI can render a progress indicator. Tuneable
# without a release: just change the constant.
_BULK_APPROVE_THRESHOLD = 100

_ANNOTATION_ACTIONS = {"approved", "edited", "flagged", "rejected"}


@v2_bp.route(
    "/admin/coaching-attempts/<attempt_id>/annotations",
    methods=["POST"],
)
@require_admin
def v2_admin_coaching_attempt_annotation_create(attempt_id):
    """Persist an admin annotation on one coaching attempt.

    Phase 9 — captures admin RLHF on a Phase 2 attempt row. Each
    POST creates a NEW annotation; the same attempt can be reviewed
    by multiple admins and an admin can revise their own verdict by
    posting again (history is preserved by design).

    Body (all fields optional except admin_action)::

        {
          "admin_action": "approved" | "edited" | "flagged" | "rejected",
          "admin_score": 0.78,
          "admin_components": { "specificity": 0.7, ... },
          "admin_note": "Score was generous on engagement.",
          "ai_score_was_correct": false,
          "reason_chip": "score_inflated"
        }

    Response: 201 with the persisted row + the admin's running
    annotations count (for the bulk-approve gate).
    """
    try:
        admin_user_id = request.user_id
        if not _is_valid_uuid(attempt_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "attempt_id must be a valid UUID",
            }), 400

        body = request.get_json(silent=True) or {}
        action = (body.get("admin_action") or "").strip().lower()
        if action not in _ANNOTATION_ACTIONS:
            return jsonify({
                "code": "INVALID_ACTION",
                "error": (
                    "admin_action must be one of: "
                    + ", ".join(sorted(_ANNOTATION_ACTIONS))
                ),
            }), 400

        admin_score = body.get("admin_score")
        if admin_score is not None:
            try:
                admin_score = float(admin_score)
                if not (0.0 <= admin_score <= 1.0):
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "admin_score must be a number in [0, 1]",
                }), 400

        admin_components = body.get("admin_components")
        if admin_components is not None and not isinstance(admin_components, dict):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "admin_components must be an object",
            }), 400

        admin_note = body.get("admin_note")
        if isinstance(admin_note, str):
            admin_note = admin_note.strip()[:2000] or None
        else:
            admin_note = None

        ai_correct = body.get("ai_score_was_correct")
        if ai_correct is not None and not isinstance(ai_correct, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "ai_score_was_correct must be boolean",
            }), 400

        reason_chip = body.get("reason_chip")
        if isinstance(reason_chip, str):
            reason_chip = reason_chip.strip()[:80] or None
        else:
            reason_chip = None

        inserted = db.insert_coaching_attempt_annotation(
            coaching_attempt_id=attempt_id,
            admin_user_id=admin_user_id,
            admin_action=action,
            admin_score=admin_score,
            admin_components=admin_components,
            admin_note=admin_note,
            ai_score_was_correct=ai_correct,
            reason_chip=reason_chip,
        )
        if not inserted:
            return jsonify({
                "code": "PERSIST_FAILED",
                "error": (
                    "Could not save annotation — the attempt may not "
                    "exist or the annotations table is not migrated."
                ),
            }), 500

        admin_count = db.count_annotations_by_admin(admin_user_id)

        return jsonify({
            "annotation": inserted,
            "admin_annotations_count": admin_count,
            "bulk_approve_threshold": _BULK_APPROVE_THRESHOLD,
            "bulk_approve_unlocked": admin_count >= _BULK_APPROVE_THRESHOLD,
        }), 201

    except Exception as e:
        logger.error(
            "admin/coaching-attempts/<id>/annotations POST failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save annotation",
        }), 500


@v2_bp.route(
    "/admin/coaching-attempts/<attempt_id>/annotations",
    methods=["GET"],
)
@require_admin
def v2_admin_coaching_attempt_annotation_list(attempt_id):
    """List all annotations on one coaching attempt, newest first."""
    try:
        if not _is_valid_uuid(attempt_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "attempt_id must be a valid UUID",
            }), 400
        annotations = db.list_annotations_for_coaching_attempt(attempt_id)
        return jsonify({
            "attempt_id": attempt_id,
            "annotations": annotations,
        }), 200
    except Exception as e:
        logger.error(
            "admin/coaching-attempts/<id>/annotations GET failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load annotations",
        }), 500


@v2_bp.route(
    "/admin/users/<user_id>/learner-profile-override",
    methods=["PUT", "DELETE"],
)
@v2_bp.route("/public/unsubscribe", methods=["POST"])
def v2_public_unsubscribe():
    """Token-based unsubscribe from publish-results emails.

    Phase 14. No bearer auth required — the signed token IS the
    auth. Validates signature, audience, and expiry; flips
    user_settings.email_pref_publish_results to FALSE; returns 200
    on first success and on subsequent re-clicks (idempotent).

    Body::
        { "token": "<signed unsubscribe JWT>" }

    Responses (per the frontend BFF contract):
      200 {status, email_obscured?, already_unsubscribed?}
      400 INVALID_INPUT — token missing / non-string
      401 INVALID_TOKEN — bad sig / expired / wrong audience
      404 USER_NOT_FOUND — token decoded but the user is gone
      503 SERVICE_UNAVAILABLE — UNSUBSCRIBE_TOKEN_SECRET unset
    """
    try:
        body = request.get_json(silent=True) or {}
        token = body.get("token")
        if not token or not isinstance(token, str):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "token required",
            }), 400

        from services.unsubscribe_tokens import (
            verify_unsubscribe_token,
            UnsubscribeTokenInvalid,
            UnsubscribeTokenExpired,
            UnsubscribeTokenNotConfigured,
        )

        try:
            user_id = verify_unsubscribe_token(token)
        except UnsubscribeTokenNotConfigured as e:
            logger.error("unsubscribe: secret not configured: %s", e)
            return jsonify({
                "code": "SERVICE_UNAVAILABLE",
                "error": "Unsubscribe service is temporarily unavailable.",
            }), 503
        except UnsubscribeTokenExpired as e:
            return jsonify({
                "code": "INVALID_TOKEN",
                "error": f"This unsubscribe link has expired ({e}).",
            }), 401
        except UnsubscribeTokenInvalid as e:
            return jsonify({
                "code": "INVALID_TOKEN",
                "error": f"This unsubscribe link is invalid ({e}).",
            }), 401

        # Make sure the user still exists (token may outlive the
        # account). We resolve the email both for the optional
        # email_obscured response field AND as the existence check
        # — get_user_email_from_auth returns None when the auth
        # row is gone.
        user_email: str | None = None
        try:
            user_email = db.get_user_email_from_auth(user_id)
        except Exception as e:
            logger.warning(
                "unsubscribe: email lookup failed user=%s err=%s",
                user_id, e,
            )
        if not user_email:
            return jsonify({
                "code": "USER_NOT_FOUND",
                "error": "We can't find that account anymore.",
            }), 404

        # Idempotency — second click within the validity window
        # should return 200 with already_unsubscribed=true, not a
        # 4xx. Read the current pref BEFORE writing so we know
        # whether this click changed state.
        was_subscribed = db.get_email_pref_publish_results(user_id)
        if was_subscribed:
            persisted = db.set_email_pref_publish_results(
                user_id=user_id,
                subscribed=False,
                source="email_token",
            )
            if not persisted:
                logger.warning(
                    "unsubscribe: persist failed user=%s — token "
                    "validated but DB write didn't land",
                    user_id,
                )
                return jsonify({
                    "code": "SERVICE_UNAVAILABLE",
                    "error": (
                        "Couldn't save your preference. Please try "
                        "again in a moment."
                    ),
                }), 503

        return jsonify({
            "status": "ok",
            "email_obscured": _obscure_email(user_email),
            "already_unsubscribed": not was_subscribed,
        }), 200

    except Exception as e:
        logger.error("public/unsubscribe failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "SERVICE_UNAVAILABLE",
            "error": "Unsubscribe service is temporarily unavailable.",
        }), 503


def _obscure_email(email: str) -> str | None:
    """Render ``email`` as ``j**@gmail.com``.

    First char + two stars + @ + domain. Returns None on malformed
    input so the response simply omits the field rather than
    leaking the raw address.
    """
    if not email or "@" not in email:
        return None
    local, _, domain = email.partition("@")
    if not local or not domain:
        return None
    head = local[0]
    return f"{head}**@{domain}"


# ── Directed-freestyle baseline (turns 1-4 for new users) ──────────
# Pivot from Phase 18's "frontend owns turns 1-4 as hardcoded strings"
# back to backend-generated dynamic questions, but with per-turn
# psychological OBJECTIVES so the LLM doesn't drift across the
# onboarding arc. Each turn has a single goal; the LLM builds the
# scenario but must satisfy that goal.
#
# Tone arc for the 4 baseline turns: turns 1-2 are warm (charisma —
# icebreaker + empathy), turns 3-4 are pressure (stress — challenge
# + reflex). After baseline (turn 5+), tone alternates per SSoT §4.


# Post-signup confirmation copy. Task 7 — confirmed wording from
# the FE handoff reply. BE-flag (not FE-hardcoded) so the SLA
# string can be tuned without a FE deploy when coaching-ops
# capacity shifts (busy week → "two business days" etc.). FE has
# its own built-in fallback if this block is omitted from the
# response, so an older BE deploy never leaves the post-signup
# screen blank.
_POST_SIGNUP_CONFIRMATION = {
    "headline": "We're on it.",
    "body": (
        "A human reviews every recording personally — your full "
        "analysis lands within one business day."
    ),
}


def _merge_anonymous_session_into_user(session_id: str, user_id: str):
    """Bind an unclaimed anonymous session to an authenticated user.

    Shared between two endpoints that differ only in payload field name:
      * POST /v2/public/shaky-voice/claim   (cold-start funnel, field=guest_session_id)
      * POST /v2/auth/merge-session         (post-OAuth merge, field=anonymous_session_id)

    Idempotent semantics:
      * Unclaimed                          → claim, enqueue pipeline, 200 + session_id
      * Already claimed by same user       → 200 + session_id (no-op)
      * Already claimed by different user  → 409 ALREADY_CLAIMED
      * Not found                          → 404 GUEST_SESSION_NOT_FOUND
      * Older than TTL                     → 410 GUEST_SESSION_EXPIRED

    Side effects on a successful first claim:
      * UPDATE v2_sessions SET user_id, guest_claimed_at, status, ...
      * UPDATE recording row's user_id
      * Enqueue recording_1_job (analysis pipeline)
      * Extract initial charisma snippets
      * Re-stamp interview snippets with real user_id

    Returns:
        (response_body: dict, http_status: int)
    """
    def _willab_send_response(session_row):
        """willab Lab merge→send (design §13, contract §3.4-3.7).

        If the (claimed) session is a willab Lab recording — already
        processed at upload (snippets/features/stickiness exist) — skip
        ALL the old-funnel processing and just send it to the coach queue,
        returning the §3.4 (response, status). Returns None for every
        non-willab session so the caller falls through to the legacy path
        BYTE-FOR-BYTE unchanged.

        Idempotent: safe on the first claim AND on re-claims (the send
        itself no-ops once the session is in/through the queue), so a retry
        after a transient send failure recovers a stuck session. Honors
        send_result["ok"] — a failed status flip returns 500, never a
        masked "sent_to_coach" (the bug that hid the missing-updated_at
        flip failure).
        """
        rec_id = (session_row or {}).get("recording_1_id")
        rec = db.get_recording(rec_id) if rec_id else None
        from services.lab_send import is_lab_recording, send_lab_recording_to_coach
        if not is_lab_recording(rec):
            return None
        sid = str(session_row.get("id"))
        send_result = send_lab_recording_to_coach(sid, str(user_id))
        logger.info(
            "willab_lab: merge→send sid=%s user=%s result=%s",
            sid, user_id, send_result,
        )
        if not send_result.get("ok"):
            logger.error(
                "willab_lab: merge→send flip FAILED sid=%s result=%s",
                sid, send_result,
            )
            return ({
                "code": "SEND_FAILED",
                "error": "Recording was claimed but could not be sent for review. Please retry.",
                "session_id": sid,
            }, 500)
        # ── willab credits — seed the 15-grant on send; the CHARGE now happens
        # on COACH-FEEDBACK DELIVERY (publish), NOT at send (founder re-lock:
        # 15 free = 3 free feedbacks at 5 each — see _apply_willab_publish_
        # contract). We only ENSURE the balance is initialized here so a brand-
        # new user has their 15 before any spend. Best-effort: a credit hiccup
        # must never unwind a sent slot.
        if not send_result.get("already_sent"):
            try:
                db.v2_ensure_credits_initialized(str(user_id))
            except Exception as _ce:
                logger.warning(
                    "willab_lab: credit init failed sid=%s err=%s (non-fatal)",
                    sid, _ce,
                )
        # Back-fill the ideal-text version bubbles (founder bug 2026-07-18):
        # the worker only fires them for a KNOWN owner, so a guest's takes
        # left the chat empty — and the chat IS the version history. Runs on
        # every claim path (this helper is the shared willab exit) and is
        # idempotent per (arc, version). Best-effort: never unwind a claim.
        try:
            from services.arc_notifications import backfill_ideal_bubbles
            _arc = (session_row or {}).get("arc_id")
            if not _arc:
                # Defensive: never let a narrow row silently skip the
                # back-fill (the whole point is the empty-chat bug).
                _arc = (db.v2_get_session_by_id(sid) or {}).get("arc_id")
            if _arc:
                backfill_ideal_bubbles(db, str(user_id), _arc)
            else:
                logger.warning(
                    "willab_lab: no arc_id for claimed sid=%s — ideal "
                    "bubbles not back-filled", sid)
        except Exception as _bf:
            logger.warning(
                "willab_lab: ideal back-fill failed sid=%s err=%s "
                "(non-fatal)", sid, _bf,
            )
        return ({
            "status": "ok",
            "session_id": sid,
            "analysis_status": "sent_to_coach",   # → review_pending
            "review_pending": True,
            "post_signup_confirmation": _POST_SIGNUP_CONFIRMATION,
        }, 200)

    if not getattr(config, "GUEST_FUNNEL_ENABLED", False):
        return ({"code": "GUEST_FUNNEL_DISABLED", "error": "Guest funnel is disabled"}, 503)

    # Probe the session's current state first so we can return precise error
    # codes. The atomic claim happens in v2_claim_guest_session.
    existing = db.v2_get_session_by_id(session_id)
    if not existing:
        return ({
            "code": "GUEST_SESSION_NOT_FOUND",
            "error": "That trial recording was not found. It may have expired — please record again.",
        }, 404)

    existing_user = existing.get("user_id")
    if existing_user and str(existing_user) != str(user_id):
        return ({
            "code": "ALREADY_CLAIMED",
            "error": "This trial recording was already claimed by a different account.",
        }, 409)
    if existing_user and str(existing_user) == str(user_id):
        # Idempotent re-claim: return the bound session_id without re-enqueueing.
        # For a willab Lab session, (re-)send to the coach queue first so a
        # retry after a transient send failure recovers it (send is a no-op
        # if already queued).
        _wl = _willab_send_response(existing)
        if _wl is not None:
            return _wl
        return ({
            "status": "ok",
            "session_id": str(existing.get("id")),
            "analysis_status": "already_claimed",
        }, 200)

    # TTL guard: even if the cleanup job hasn't run yet, refuse to claim
    # a row older than the configured window.
    try:
        from datetime import datetime, timedelta, timezone
        ttl_hours = int(getattr(config, "GUEST_FUNNEL_TTL_HOURS", 24) or 24)
        created_raw = existing.get("created_at")
        if created_raw:
            if isinstance(created_raw, str):
                created_dt = datetime.fromisoformat(created_raw.replace("Z", "+00:00"))
            else:
                created_dt = created_raw
            if created_dt.tzinfo is None:
                created_dt = created_dt.replace(tzinfo=timezone.utc)
            if datetime.now(timezone.utc) - created_dt > timedelta(hours=ttl_hours):
                return ({
                    "code": "GUEST_SESSION_EXPIRED",
                    "error": "Your trial recording expired. Please record again.",
                }, 410)
    except Exception as ttl_err:
        logger.warning("guest_funnel: ttl check failed (continuing): %s", ttl_err)

    claimed = db.v2_claim_guest_session(session_id, user_id)
    if not claimed:
        # Race lost: someone (or the same user via duplicate request) just
        # bound the row between our probe and the atomic update.
        after = db.v2_get_session_by_id(session_id) or {}
        after_user = after.get("user_id")
        if after_user and str(after_user) == str(user_id):
            _wl = _willab_send_response(after)
            if _wl is not None:
                return _wl
            return ({
                "status": "ok",
                "session_id": str(after.get("id")),
                "analysis_status": "already_claimed",
            }, 200)
        return ({
            "code": "ALREADY_CLAIMED",
            "error": "This trial recording was already claimed.",
        }, 409)

    # ── willab Lab send-gate (design §13, contract §3.4-3.7) ────────
    # A willab Lab recording was ALREADY processed at upload (snippets +
    # features + stickiness exist), so skip ALL the old-funnel processing
    # below (re-extract / recompute would double-process) and just send it
    # to the coach queue via the helper above (shared with the re-claim
    # paths). Gated strictly on the recording's origin, so the legacy claim
    # path below is byte-for-byte unchanged for every non-willab session.
    # This is the BE-composed merge→send the FE wiring expects
    # (PendingSessionClaim → /v2/auth/merge-session, signed + unsigned).
    _wl = _willab_send_response(claimed)
    if _wl is not None:
        return _wl

    # Non-willab sessions: the legacy old-funnel pipeline (recording_1_job
    # + snippet extract + KPI finalize) was removed in the Phase-5 clearance
    # (D1=REPLACE). willab Lab recordings short-circuit above via
    # _willab_send_response; any other (now-legacy) session is simply
    # claimed — there is no old-funnel processing left to run.
    try:
        db.update_snippets_user_id(session_id, str(user_id))
    except Exception as uid_err:
        logger.warning("merge: update_snippets_user_id failed: %s", uid_err)
    logger.info(
        "merge: claimed non-willab session=%s user=%s (legacy pipeline removed)",
        session_id, user_id,
    )
    return ({
        "status": "ok",
        "session_id": str(claimed.get("id")),
        "analysis_status": "claimed",
    }, 200)


@v2_bp.route("/public/shaky-voice/claim", methods=["POST"])
@require_auth
def v2_public_shaky_voice_claim():
    """Bind an unclaimed funnel session (cold-start funnel) to the authenticated user.

    Thin wrapper around `_merge_anonymous_session_into_user`. Accepts
    `guest_session_id` for backwards compatibility with the existing funnel
    client. New OAuth callers should prefer POST /v2/auth/merge-session.
    """
    try:
        body = request.get_json(silent=True) or {}
        guest_session_id = (body.get("guest_session_id") or "").strip()
        if not _is_valid_uuid(guest_session_id):
            return jsonify({"code": "INVALID_INPUT", "error": "guest_session_id must be a UUID"}), 400

        response, status = _merge_anonymous_session_into_user(guest_session_id, request.user_id)
        return jsonify(response), status

    except Exception as e:
        logger.error("guest_funnel: claim failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Claim failed"}), 500


@v2_bp.route("/auth/merge-session", methods=["POST"])
@require_auth
def v2_auth_merge_session():
    """Merge an anonymous cold-start session into the authenticated user account.

    Built for the LinkedIn OAuth flow: the user records anonymously, the
    frontend stashes the `anonymous_session_id`, the OAuth roundtrip
    establishes a session, and the frontend posts the stashed id here so
    the recording, messages, audio files, and snippets are linked to the
    new (or returning) user.

    Auth: required (Bearer token from Supabase session).

    Body: { "anonymous_session_id": "<uuid>" }

    Responses:
        200 { status, session_id, analysis_status: "queued" | "already_claimed" }
        400 INVALID_INPUT          — id missing / not a UUID
        404 GUEST_SESSION_NOT_FOUND — id doesn't match any session
        409 ALREADY_CLAIMED        — session belongs to a different user
        410 GUEST_SESSION_EXPIRED  — older than GUEST_FUNNEL_TTL_HOURS
        500 V2_ERROR               — unexpected server error
        503 GUEST_FUNNEL_DISABLED  — feature flag off
    """
    try:
        body = request.get_json(silent=True) or {}
        anonymous_session_id = (body.get("anonymous_session_id") or "").strip()
        if not _is_valid_uuid(anonymous_session_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "anonymous_session_id must be a UUID",
            }), 400

        response, status = _merge_anonymous_session_into_user(
            anonymous_session_id, request.user_id
        )
        return jsonify(response), status

    except Exception as e:
        logger.error("merge_session: merge failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Session merge failed"}), 500


@v2_bp.route("/auth/signup", methods=["POST"])
def v2_auth_signup():
    """Alias for /auth/signup under the /v2/auth/* namespace.

    The native registration handler lives on `auth_bp` (mounted at `/auth`),
    but the BFF posts to `/v2/auth/signup` to match the sibling
    `/v2/auth/merge-session` endpoint and keep the BFF surface consistent
    under one namespace. This route delegates to the same function so both
    paths produce identical behaviour and the legal-consent gate is
    enforced regardless of which path callers hit.
    """
    from routes.auth import signup as _native_signup
    return _native_signup()


@v2_bp.route("/admin/funnel/afterwards-video", methods=["POST"])
@require_admin
def v2_admin_funnel_afterwards_video_upload():
    """Admin endpoint to upload and configure the afterwards video for Curiosity Gate funnel.

    Accepts multipart form with video_file field, uploads to storage, and stores the URL
    in the funnel_config table.
    """
    from services.coach_video_storage import coach_media_public_url, put_coach_object_bytes
    from datetime import datetime
    import os

    try:
        max_video_mb = max(1, int(getattr(config, "FUNNEL_AFTERWARDS_VIDEO_MAX_MB", 100)))
        max_video_bytes = max_video_mb * 1024 * 1024
        content_length = request.content_length or 0
        if content_length and content_length > max_video_bytes:
            return jsonify({
                "code": "PAYLOAD_TOO_LARGE",
                "error": f"Video is too large. Max allowed is {max_video_mb}MB.",
            }), 413

        video_file = request.files.get("video_file")
        if video_file is None or not (video_file.filename or "").strip():
            return jsonify({"code": "INVALID_INPUT", "error": "video_file is required"}), 400

        safe_name = secure_filename(video_file.filename or "")
        ext = os.path.splitext(safe_name)[1].lower()
        if ext not in {".mp4", ".mov", ".webm", ".m4v"}:
            return jsonify({
                "code": "INVALID_VIDEO_FORMAT",
                "error": "Supported formats: .mp4, .mov, .webm, .m4v",
            }), 415

        video_bytes = video_file.read() or b""
        if not video_bytes:
            return jsonify({"code": "INVALID_INPUT", "error": "video_file is empty"}), 400

        if len(video_bytes) > max_video_bytes:
            return jsonify({
                "code": "PAYLOAD_TOO_LARGE",
                "error": f"Video is too large. Max allowed is {max_video_mb}MB.",
            }), 413

        # Generate storage path with timestamp
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        storage_key = f"funnel/afterwards-video/{timestamp}{ext}"
        bucket = getattr(config, "COACH_FEEDBACK_VIDEO_BUCKET", "coach_feedback_videos")

        # Upload to storage (R2 or Supabase)
        try:
            put_coach_object_bytes(bucket, storage_key, video_bytes, video_file.content_type or "video/mp4")
        except Exception as upload_err:
            logger.error("funnel afterwards-video upload failed: %s", upload_err)
            return jsonify({
                "code": "UPLOAD_FAILED",
                "error": "Failed to upload video to storage.",
            }), 502

        # Generate public URL
        video_url = coach_media_public_url(storage_key)

        # Store URL in funnel_config
        config_row = db.set_funnel_config("afterwards_video_url", video_url)

        logger.info("funnel: uploaded afterwards-video storage_key=%s url=%s", storage_key, video_url)

        return jsonify({
            "status": "ok",
            "video_url": video_url,
            "storage_key": storage_key,
        }), 200

    except Exception as e:
        logger.error("funnel: afterwards-video admin upload failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Upload failed"}), 500


@v2_bp.route("/public/funnel/afterwards-video", methods=["GET"])
def v2_public_funnel_afterwards_video():
    """Public endpoint to fetch the afterwards video URL for Curiosity Gate funnel.

    Returns the configured video URL or null if not set.
    No authentication required.
    """
    try:
        config_row = db.get_funnel_config("afterwards_video_url")
        video_url = (config_row or {}).get("value") if config_row else None

        return jsonify({
            "video_url": video_url,
        }), 200

    except Exception as e:
        logger.error("funnel: afterwards-video public read failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch video"}), 500


def _assemble_insights_from_drafts(session_id, overall_message):
    """Build the USER-lane insights_payload from the coach's persisted
    per-snippet drafts (the post-§F.4 simplified publish, which sends only
    {overall_message, notify_client}). SURFACED + noted snippets become
    snippet_notes; validate_insights_payload then enforces the library floor.
    """
    notes: list = []
    for d in (db.get_coach_snippet_drafts(session_id) or []):
        if not d.get("surfaced"):
            continue
        note = (d.get("note") or "").strip()
        if not note:
            continue
        notes.append({
            "snippet_id": str(d.get("snippet_id")),
            "note": note,
            "tag": d.get("tag"),
            "when": d.get("when_context"),
            "examples": d.get("examples") or [],
            "breakthrough_video_ref": d.get("breakthrough_video_ref"),
            # Free tier (founder 2026-07-06): a real coach-authored correction
            # of the transcript, distinct from the immutable raw Whisper text.
            # None until the coach saves one.
            "transcript_corrected": d.get("transcript_corrected"),
        })
    return {"overall_message": overall_message, "snippet_notes": notes}


def _assemble_labels_from_store(session_id):
    """Build the PRIVATE-lane labels list from training_labels persisted at
    per-snippet save time (post-§F.4 simplified publish). Re-validated +
    re-persisted idempotently by the contract."""
    out: list = []
    for lab in (db.get_training_labels(session_id) or []):
        sid = lab.get("snippet_id")
        if sid is None:
            continue
        out.append({
            "snippet_id": str(sid),
            "value": lab.get("value"),
            "was_pre_filled": bool(lab.get("was_pre_filled", False)),
            "was_overridden": bool(lab.get("was_overridden", False)),
        })
    return out


def _apply_willab_publish_contract(session_id, body, actor_user_id):
    """Shared willab publish-contract gate (handoff §3.9 / §3.10).

    OPT-IN: acts only when ``body`` carries an ``insights_payload`` (a
    willab publish). Absent → returns None (legacy charisma publish,
    undisturbed). When present, validates BOTH split-sink lanes BEFORE
    any persistence / side effect, persists both stores (§2), then fires
    the best-effort user nudge (Lounge "insights ready" card) + the
    idempotent willab credit charge.

    Returns
    -------
    None
        Success, OR not a willab publish (no ``insights_payload``).
    (flask_response, status_int)
        Return this DIRECTLY from the caller — a §3.10 contract
        violation (422) or a persistence failure (500). Nothing has
        been flipped/emailed at that point.

    WHY THIS IS A SHARED HELPER (not two copies):
    The §3.10 "library floor" — ≥1 tagged snippet note + a direction
    label on every snippet — must hold no matter WHICH publish door a
    coach uses. The gate originally lived inline in
    /internal/publish-session-results ONLY, so /admin/sessions/<id>/
    publish (a coach-reachable door, per BE-HANDOFF-tab1-comment-sink-
    split.md) could publish a willab session UNGATED — no notes, no
    tags, insights_payload never written, library floor silently
    broken. Centralizing here means the two doors physically cannot
    drift again.
    """
    # Opt-in: a willab publish carries insights_payload (legacy/body mode —
    # today's FE) OR notify_client (the post-§F.4 simplified publish, which
    # sends just {overall_message, notify_client}; we ASSEMBLE both lanes from
    # the persisted per-snippet drafts + training_labels). Legacy charisma
    # publishes carry neither → undisturbed.
    body_mode = "insights_payload" in body
    assemble_mode = (not body_mode) and ("notify_client" in body)
    if not (body_mode or assemble_mode):
        return None  # legacy publish — nothing to enforce

    from services.insights_payload import (
        InsightsPayloadError, validate_insights_payload,
    )
    from services.training_labels import (
        TrainingLabelError, validate_publish_labels,
    )

    if body_mode:
        raw_insights = body.get("insights_payload")
        raw_labels = body.get("labels")
    else:
        raw_insights = _assemble_insights_from_drafts(
            session_id, body.get("overall_message"),
        )
        raw_labels = _assemble_labels_from_store(session_id)

    # ── Validate BOTH lanes BEFORE any persistence/side effect. ──
    try:
        clean_insights = validate_insights_payload(raw_insights)
    except InsightsPayloadError as ie:
        return jsonify({
            "code": "PUBLISH_CONTRACT_VIOLATION", "error": str(ie),
        }), 422

    # §3.10/S.5: the publish floor is the LIBRARY floor (≥1 surfaced note+tag,
    # enforced above), NOT label coverage. Labels are captured for training but
    # are NEVER mandatory to publish → require_all=False. NB: this shared helper
    # guards the (sole surviving) /internal publish door.
    try:
        _snips = db.get_snippets_by_session(session_id) or []
    except Exception:
        _snips = []
    required_ids = {str(s.get("id")) for s in _snips if s.get("id")}
    try:
        clean_labels = validate_publish_labels(
            raw_labels, required_ids, require_all=False,
        )
    except TrainingLabelError as le:
        return jsonify({
            "code": "PUBLISH_CONTRACT_VIOLATION", "error": str(le),
        }), 422

    # Coach video (B.3): fold the session's coach_video_ref into the published
    # insights so it ships to the user — both modes, AFTER validation (a coach
    # artifact, not subject to the library floor). Absent column/value → no-op.
    try:
        _sess_for_video = db.v2_get_session_by_id(session_id) or {}
        _video_ref = (_sess_for_video.get("coach_video_ref") or "").strip() or None
        if _video_ref:
            clean_insights["video_ref"] = _video_ref
    except Exception:
        pass

    # ── Persist both lanes (split-sink §2: separate stores). ──
    if not db.set_session_insights_payload(session_id, clean_insights):
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to persist insights payload",
        }), 500
    labels_written = db.upsert_training_labels(
        session_id, str(actor_user_id), clean_labels,
    )
    logger.info(
        "publish_contract.willab session=%s notes=%d overall=%s labels=%d",
        session_id, len(clean_insights["snippet_notes"]),
        bool(clean_insights["overall_message"]), labels_written,
    )

    # Arc lifecycle (founder #1, 2026-07-06): a publish may complete the
    # "coach-reviewed" condition — fire the right >=3-takes card now
    # (best_presentation_ready only when reviewed AND paid; else
    # transcript_ready). Idempotent per (arc, kind); best-effort.
    try:
        _pub_sess = db.v2_get_session_by_id(session_id) or {}
        _pub_arc = _pub_sess.get("arc_id")
        if _pub_arc:
            from services.arc_notifications import (
                maybe_fire_best_presentation_ready,
            )
            maybe_fire_best_presentation_ready(db, _pub_arc)
    except Exception as _an_err:
        logger.warning(
            "publish_contract.arc_card_failed session=%s err=%s (non-fatal)",
            session_id, _an_err,
        )

    # Subsystem V — freeze the FINAL delivered comment onto each current coach
    # video take (write-once; the comment→video training pair as delivered).
    # take_summary ← overall_message; breakthrough ← that snippet's note. Best-
    # effort: never affects the publish.
    try:
        _cur_assets = db.get_current_coach_video_assets_for_session(session_id)
        if _cur_assets:
            _note_by_snip = {
                str(n.get("snippet_id")): n.get("note")
                for n in (clean_insights.get("snippet_notes") or [])
                if isinstance(n, dict) and n.get("snippet_id")
            }
            _overall = (clean_insights.get("overall_message") or "").strip() or None
            for _a in _cur_assets:
                if _a.get("comment_text_at_publish"):
                    continue  # already frozen
                if _a.get("content_type") == "take_summary":
                    _final = _overall
                else:
                    _final = _note_by_snip.get(str(_a.get("snippet_id")))
                if _final:
                    db.set_coach_video_comment_at_publish(_a.get("id"), _final)
    except Exception as _cv_err:
        logger.warning(
            "publish_contract.coach_video_snapshot_failed session=%s err=%s "
            "(non-fatal)", session_id, _cv_err,
        )

    # ── User nudge: Lounge "insights ready" card (best-effort, idempotent). ──
    # suppress_lounge_card (founder 2026-07-13): the ARC-BATCH publish door
    # publishes every take in one action and fires ONE arc-level card instead
    # — it opts out of the per-take card here. Per-take doors never set it.
    try:
        from datetime import datetime as _dt, timezone as _tz
        _sess = db.v2_get_session_by_id(session_id) or {}
        _owner = _sess.get("user_id")
        if body.get("suppress_lounge_card") is True:
            _owner = None  # skip the card; everything else unchanged
        if _owner:
            _ctx = _sess.get("intake_context") if isinstance(
                _sess.get("intake_context"), dict) else {}
            db.insert_lounge_messages(str(_owner), [{
                "client_id": str(uuid.uuid5(
                    uuid.NAMESPACE_URL, f"willab-insight:{session_id}",
                )),
                "role": "bot",
                "kind": "insight",
                "body": "Your coach's insights are ready.",
                "metadata": {
                    "session_id": session_id, "insight_ref": session_id,
                    # F4 — so the card reads "Feedback on {topic} (Take N)"
                    # instead of the date fallback.
                    "topic": _ctx.get("topic"),
                    "take_index": _sess.get("take_index"),
                },
                "client_created_at": _dt.now(_tz.utc).isoformat(),
            }])
            logger.info(
                "publish_contract.lounge_card session=%s owner=%s",
                session_id, _owner,
            )
    except Exception as _le:
        logger.warning(
            "publish_contract.lounge_append_failed session=%s err=%s "
            "(non-fatal)", session_id, _le,
        )

    # ── willab credits — charge 5 ON COACH-FEEDBACK DELIVERY (founder re-lock:
    # 15 free = 3 free feedbacks). This publish IS the delivery (insights_payload
    # persisted + the "insights ready" card above). Idempotent per session (the
    # feedback_credits_charged_at flag); a re-publish never re-charges; SOFT
    # (floors at 0) so a low balance never withholds the coach's work — the gate
    # is on STARTING the next recording (FE), not on receiving feedback. Best-
    # effort: a credit hiccup must never unwind a published session.
    try:
        _sess_for_credit = db.v2_get_session_by_id(session_id) or {}
        _credit_owner = _sess_for_credit.get("user_id")
        # Paid Audits (A2): an ARC session ("audit") is monetized per-arc via
        # arc_purchases, NOT credits — so the #154 lab-publish 5-credit soft-
        # deduct is SKIPPED for arc sessions. Non-arc (homework / standalone
        # lab) sessions keep the credit charge exactly as before.
        _is_arc_session = bool(_sess_for_credit.get("arc_id"))
        if _credit_owner and not _is_arc_session:
            db.v2_ensure_credits_initialized(str(_credit_owner))
            db.v2_charge_feedback_credits_once(
                session_id, str(_credit_owner), amount=5,
            )
        elif _is_arc_session:
            logger.info(
                "publish_contract.credit_skip_arc session=%s — arc audit "
                "monetized via arc_purchases, not credits", session_id,
            )
    except Exception as _ce:
        logger.warning(
            "publish_contract.credit_charge_failed session=%s err=%s "
            "(non-fatal)", session_id, _ce,
        )

    return None


@v2_bp.route("/internal/publish-session-results", methods=["POST"])
@require_admin_or_coach
def v2_internal_publish_session_results():
    """willab publish door — the coach (or admin) publishes a session's
    insights. (Re-gated to require_admin_or_coach: the old /admin/sessions/
    <id>/publish door was excised, so this is the sole surviving publish path
    that runs the shared _apply_willab_publish_contract; the FE's
    publishWillabSession already POSTs here.)

    Sends the results-ready email with a CTA to /results — GATED on
    notify_client (the in-app Lounge nudge always fires in the contract
    helper; only the email is opt-out).
    """
    from services.email_service import send_email_resend

    try:
        body = request.get_json(silent=True) or {}
        session_id = (body.get("session_id") or "").strip()

        if not _is_valid_uuid(session_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "session_id must be a valid UUID",
            }), 400

        # Fetch session to get user email
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Session not found",
            }), 404

        # Save-at-publish (founder 2026-07-13): the FE no longer autosaves
        # per keystroke — it may send the coach's full per-snippet authoring
        # inline as ``snippets: [{id, note?, tag?, surfaced?, direction?|
        # direction_label?, ...}]``. Persist each through the SAME two-lane
        # helper as /coach/sessions/<id>/snippets/<id> (validators/caps/
        # stores shared — the doors cannot drift), BEFORE the contract runs
        # so assemble-mode reads the fresh drafts. Optional + backward-
        # compatible: absent → today's behavior (pre-saved coach_state).
        _inline_snips = body.get("snippets")
        if isinstance(_inline_snips, list) and _inline_snips:
            _known_ids = {
                str(s.get("id"))
                for s in (db.get_snippets_by_session(session_id) or [])
                if s.get("id")
            }
            for _entry in _inline_snips:
                if not isinstance(_entry, dict):
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": "snippets: entries must be objects",
                    }), 422
                _snip_id = str(_entry.get("id") or "").strip()
                if _snip_id not in _known_ids:
                    return jsonify({
                        "code": "SNIPPET_NOT_FOUND",
                        "error": f"snippet {_snip_id or '(missing id)'} "
                                 "not in this session",
                    }), 404
                _fields = dict(_entry)
                _fields.pop("id", None)
                # FE alias: `direction` → the store's `direction_label`.
                if "direction" in _fields and "direction_label" not in _fields:
                    _fields["direction_label"] = _fields.pop("direction")
                _lane_err = _save_coach_snippet_lanes(
                    session_id, _snip_id, _fields,
                )
                if _lane_err is not None:
                    return _lane_err

        # willab publish-contract (§3.9/§3.10) — SHARED gate, see
        # _apply_willab_publish_contract. Opt-in on `insights_payload`;
        # validates + persists both split-sink lanes (§2) + fires the
        # user nudge/credits BEFORE any side effect below. Returns a
        # 422/500 tuple on contract/persist failure (nothing flipped
        # or emailed at that point). The SAME helper guards
        # /admin/sessions/<id>/publish so the two doors can't drift.
        _contract_err = _apply_willab_publish_contract(
            session_id, body, request.user_id,
        )
        if _contract_err is not None:
            return _contract_err

        # Phase 10 — emit RLHF annotation events for every snippet in
        # this session BEFORE the status flip + email. Each row in
        # admin_annotation_events captures (ai_draft, admin_final) for
        # admin_comment, follow_up_question, and stress coach_label_
        # notes. Approved-as-is gets reason_chip='approved_as_is';
        # edits get the diff. Best-effort — never blocks the publish.
        try:
            events_written = db.record_snippet_publish_annotations(
                session_id=session_id,
                admin_user_id=str(request.user_id),
            )
            logger.info(
                "publish-results: rlhf events emitted session=%s count=%d",
                session_id, events_written,
            )
        except Exception as annot_err:
            logger.warning(
                "publish-results: rlhf emit failed session=%s err=%s "
                "(non-fatal)", session_id, annot_err,
            )

        # Flip results status so frontend transitions from waiting → results
        try:
            db.v2_update_session_status_unscoped(session_id, "completed")
        except Exception as flip_err:
            logger.warning("publish-results: status flip failed (non-fatal): %s", flip_err)

        user_id = session.get("user_id")
        if not user_id:
            return jsonify({
                "code": "NO_USER",
                "error": "Session has no associated user (not yet claimed)",
            }), 400

        # Fetch user email from Supabase auth
        try:
            import httpx
            auth_headers = {
                "Authorization": f"Bearer {config.SUPABASE_SERVICE_ROLE_KEY}",
                "apikey": config.SUPABASE_SERVICE_ROLE_KEY,
            }
            user_url = f"{config.SUPABASE_URL.rstrip('/')}/auth/v1/admin/users/{user_id}"
            resp = httpx.get(user_url, headers=auth_headers, timeout=10)
            if resp.status_code != 200:
                logger.warning("publish-results: failed to fetch user %s from auth", user_id)
                return jsonify({
                    "code": "AUTH_ERROR",
                    "error": "Could not fetch user email",
                }), 502
            user_data = resp.json()
            user_email = user_data.get("email")
        except Exception as fetch_err:
            logger.error("publish-results: fetch user error: %s", fetch_err)
            return jsonify({
                "code": "AUTH_ERROR",
                "error": "Could not fetch user email",
            }), 502

        if not user_email:
            return jsonify({
                "code": "NO_EMAIL",
                "error": "User has no email",
            }), 400

        # Flip the session status so /results page shows snippets.
        # Done BEFORE the email send so a failed send never blocks
        # the user from reaching their results via direct link.
        db.v2_publish_session_results(session_id)

        # (Old charisma-profile compute removed in the old-subsystem
        # excision — willab publishes never used the result, and AC-9
        # already strips charisma_profile from user payloads. The legacy
        # admin compute-metrics route still computes it on demand.)

        # ── Phase 14 — new PostSessionResultsEmail render pipeline ──
        # Replaces the inline HTML build. The render service handles:
        #   - per-user pref check (skip if unsubscribed)
        #   - server-to-server render call into Next.js
        #   - RFC 8058 List-Unsubscribe headers
        #   - unsubscribe token mint + URL
        # Props for the template:
        first_name: str | None = None
        try:
            details = db.v2_get_student_details(user_id) or {}
            full_name = (details.get("name") or "").strip()
            if full_name:
                first_name = full_name.split()[0]
        except Exception as e:
            logger.warning(
                "publish-results: name lookup failed user=%s err=%s",
                user_id, e,
            )

        snippet_count = 0
        try:
            commented = db.get_snippets_with_comments_by_session(session_id)
            snippet_count = len(commented or [])
        except Exception as e:
            logger.warning(
                "publish-results: snippet count lookup failed "
                "session=%s err=%s", session_id, e,
            )

        top_theme: str | None = None
        try:
            sess_row = db.v2_get_session_by_id(session_id) or {}
            top_theme = (
                (sess_row.get("stickiness_top_topic") or "").strip() or None
            )
        except Exception:
            pass

        from services.post_session_results_email import (
            send_publish_results_email,
        )

        # Deep-link → Lounge chat. On open the chat auto-scrolls to the
        # bottom, showing the "insights ready" card the publish contract
        # already appended to the thread. No overlay param — the user just
        # lands in the Lounge and sees the recent message.
        results_url = (
            f"{config.PUBLIC_FRONTEND_URL.rstrip('/')}/chat"
        )

        # notify_client gate (C): the in-app Lounge nudge already fired in the
        # shared contract helper (always). Only the EMAIL is opt-out; default
        # true preserves the pre-notify_client behaviour (FE sets first-publish
        # = true, edit = false per S.2-G).
        if not bool(body.get("notify_client", True)):
            logger.info(
                "publish-results: email suppressed (notify_client=false) "
                "session_id=%s", session_id,
            )
            return jsonify({
                "status": "ok",
                "email_sent_to": None,
                "results_url": results_url,
                "email_suppressed": True,
            }), 200

        send_result = send_publish_results_email(
            user_id=user_id,
            user_email=user_email,
            user_first_name=first_name,
            snippet_count=snippet_count,
            top_theme=top_theme,
            session_id=session_id,
        )
        status = send_result.get("status")

        if status == "sent":
            logger.info(
                "publish-results: email sent session_id=%s user_id=%s "
                "email=%s", session_id, user_id, user_email,
            )
            return jsonify({
                "status": "ok",
                "email_sent_to": user_email,
                "results_url": results_url,
            }), 200

        if status == "skipped":
            reason = send_result.get("reason") or "unknown"
            logger.info(
                "publish-results: email skipped session_id=%s user_id=%s "
                "reason=%s", session_id, user_id, reason,
            )
            return jsonify({
                "status": "ok",
                "email_sent_to": None,
                "results_url": results_url,
                "email_skipped_reason": reason,
            }), 200

        # render_failed / send_failed — publish itself succeeded
        # (the session is already flipped to completed) so we return
        # 200 with a warning rather than blocking on the email step.
        logger.error(
            "publish-results: email %s session_id=%s user_id=%s err=%s",
            status, session_id, user_id, send_result.get("error"),
        )
        return jsonify({
            "status": "ok",
            "email_sent_to": None,
            "results_url": results_url,
            "warning": (
                "Results published but email delivery failed: "
                f"{send_result.get('error') or status}"
            ),
        }), 200

    except Exception as e:
        logger.error("publish-results: failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to publish results"}), 500


############################################################################
# Admin: AI evaluator rationale review (Phase 14.x — frontend BFF target)
############################################################################

@v2_bp.route(
    "/admin/snippets/<snippet_id>/coaching-rationale",
    methods=["PATCH"],
)
@require_admin
def v2_admin_update_snippet_coaching_rationale(snippet_id):
    """Persist an admin's review of the AI evaluator's rationale.

    Backs the editable-rationale strip on the admin user-detail page.
    The strip pre-fills its textarea with the AI's rationale and lets
    the admin save it as-is (approval signal) or edit it (correction
    signal). At publish time, ``record_snippet_publish_annotations``
    emits one ``admin_annotation_events`` row per reviewed snippet
    (field_name='evaluator_rationale') so the RLHF/DPO export
    captures the (AI draft, admin final) pair the same way it
    already captures admin_comment / follow_up_question.

    Body::

        {
          "rationale":        str,   # text the admin saw on screen
          "edited_by_admin":  bool   # true → store as correction;
                                     # false → store admin_corrected_
                                     #   rationale=null (= approved
                                     #   AI verbatim)
        }

    Responses:
      200 — review saved; returns the updated outcome.evaluator block
      400 INVALID_INPUT       — bad UUID, missing rationale, or
                                edited_by_admin not a bool
      404 NOT_FOUND           — no charisma_snippet with this id
      422 NO_OUTCOME_TO_REVIEW — snippet exists but has no
                                follow_up_outcome / no evaluator
                                (the user hasn't done a coaching
                                attempt for this snippet yet, so
                                there's no AI rationale to review)
      500 V2_ERROR            — unexpected
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "snippet_id must be a valid UUID",
        }), 400

    try:
        body = request.get_json(silent=True) or {}
        rationale = body.get("rationale")
        edited_by_admin = body.get("edited_by_admin")
        is_trivial_edit = bool(body.get("is_trivial_edit", False))

        if not isinstance(rationale, str) or not rationale.strip():
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "rationale must be a non-empty string",
            }), 400
        if not isinstance(edited_by_admin, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "edited_by_admin must be a boolean",
            }), 400

        # ── Trivial-edit gate (Phase 18.x) ──────────────────────────
        # Only applies when the admin claims an edit — approvals
        # (edited_by_admin=False) skip the gate because they store
        # no corrected text and emit no correction signal anyway.
        # Empty-baseline bypass: when there's no AI rationale on the
        # snippet's outcome blob to diff against, the admin is
        # writing net-new content — gate does not apply.
        if edited_by_admin:
            from services.utils import (
                changed_word_tokens,
                TRIVIAL_EDIT_TOKEN_THRESHOLD,
            )
            try:
                _existing = (
                    db.client.table("charisma_snippets")
                    .select("follow_up_outcome")
                    .eq("id", snippet_id)
                    .limit(1)
                    .execute()
                )
                _outcome = (
                    _existing.data[0].get("follow_up_outcome") or {}
                ) if _existing.data else {}
                _evaluator = _outcome.get("evaluator") or {}
                _ai_rationale = (
                    _evaluator.get("rationale") or ""
                ).strip()
            except Exception:
                _ai_rationale = ""

            if _ai_rationale:
                diff_tokens = changed_word_tokens(
                    _ai_rationale, rationale
                )
                if diff_tokens <= TRIVIAL_EDIT_TOKEN_THRESHOLD:
                    if not is_trivial_edit:
                        logger.info(
                            "coaching-rationale.edit_too_small "
                            "snippet=%s diff_tokens=%d threshold=%d",
                            snippet_id, diff_tokens,
                            TRIVIAL_EDIT_TOKEN_THRESHOLD,
                        )
                        return jsonify({
                            "code": "EDIT_TOO_SMALL",
                            "error": (
                                "Too small a change to count as a "
                                "correction (need "
                                f"{TRIVIAL_EDIT_TOKEN_THRESHOLD + 1}+ "
                                "word differences). Tick 'Mark as "
                                "minor edit' to save as a cosmetic "
                                "fix."
                            ),
                            "diff": {
                                "changed_word_tokens": diff_tokens,
                                "threshold": TRIVIAL_EDIT_TOKEN_THRESHOLD,
                            },
                        }), 422
                    # Trivial override accepted — preserve text via
                    # is_trivial_edit forwarding (helper writes the
                    # was_trivial_edit flag on the JSONB so publish-
                    # time consumers can downgrade to approval).

        reviewed_at = datetime.now(timezone.utc).isoformat()
        outcome = db.set_snippet_evaluator_rationale_review(
            snippet_id=snippet_id,
            rationale_text=rationale,
            edited_by_admin=edited_by_admin,
            reviewed_at=reviewed_at,
            is_trivial_edit=is_trivial_edit,
        )
        if not outcome:
            # Distinguish "snippet doesn't exist" from "snippet has
            # no follow_up_outcome to review" with a quick existence
            # probe — both are 4xx but the codes are different so
            # the frontend can show the right toast.
            try:
                exists_probe = (
                    db.client.table("charisma_snippets")
                    .select("id")
                    .eq("id", snippet_id)
                    .limit(1)
                    .execute()
                )
                snippet_exists = bool(exists_probe.data)
            except Exception:
                snippet_exists = False

            if not snippet_exists:
                return jsonify({
                    "code": "NOT_FOUND",
                    "error": "Snippet not found",
                }), 404
            return jsonify({
                "code": "NO_OUTCOME_TO_REVIEW",
                "error": (
                    "Snippet has no coaching outcome yet — the user "
                    "must complete a coaching attempt before the "
                    "rationale can be reviewed."
                ),
            }), 422

        evaluator = outcome.get("evaluator") or {}
        return jsonify({
            "status": "ok",
            "snippet_id": snippet_id,
            "evaluator": {
                "rationale": evaluator.get("rationale"),
                "admin_corrected_rationale": evaluator.get(
                    "admin_corrected_rationale"
                ),
                "admin_reviewed_at": evaluator.get("admin_reviewed_at"),
            },
        }), 200

    except Exception as e:
        logger.error(
            "admin/snippets/<id>/coaching-rationale failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save rationale review",
        }), 500


############################################################################
# Admin: Snippet boundary adjustment (the +/- 2s feature)
############################################################################

@require_admin
def v2_admin_delete_user_file(user_id, file_id):
    """Soft-delete one of ``user_id``'s uploaded files (Task 9).

    Marks ``user_uploaded_files.deleted_at = NOW()`` for the
    target row. The file disappears from the GET /files list
    immediately. R2 bytes + row are purged by a weekly cron that
    sweeps soft-deleted rows.

    Owner-scoping: the path's ``user_id`` is the owner; the
    helper enforces ``user_id eq + id eq + deleted_at IS NULL``.
    A file_id that belongs to a different user, or a file that
    was already soft-deleted, returns 404 — no existence leak.

    Auth: admin only (``@require_admin``).

    Responses:
      204 — soft-delete succeeded; no body.
      400 INVALID_INPUT — bad UUID on either path param.
      404 FILE_NOT_FOUND — file_id doesn't belong to this user,
                           or row was already soft-deleted.
      500 V2_ERROR — unexpected.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400
    if not _is_valid_uuid(file_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "file_id must be a valid UUID",
        }), 400

    try:
        updated = db.soft_delete_user_uploaded_file(
            file_id=file_id, user_id=user_id,
        )
        if not updated:
            return jsonify({
                "code": "FILE_NOT_FOUND",
                "error": "File not found",
            }), 404

        logger.info(
            "admin: soft-deleted user file user=%s file=%s "
            "by admin=%s",
            user_id, file_id,
            getattr(request, "user_id", None),
        )
        return ("", 204)

    except Exception as e:
        logger.error(
            "admin/users/<id>/files/<id> DELETE failed: %s",
            e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to delete file",
        }), 500


def _snippet_start_time(snippet: dict) -> float | None:
    """API-boundary derivation of seconds-float start time.

    The seconds-float pair (start_time / end_time) referenced through
    older API contracts is NOT a persisted schema column — every
    attempt to write it raises PGRST204 (see
    services/db.py::update_snippet_boundaries). All snippets store
    their bounds in the canonical millisecond-integer pair
    (start_offset_ms / duration_ms). We synthesise the seconds-float
    values at response time so any frontend that still consumes the
    old contract keeps working without a stale write.
    """
    ms = snippet.get("start_offset_ms")
    return None if ms is None else round(float(ms) / 1000.0, 3)


def _snippet_end_time(snippet: dict) -> float | None:
    """API-boundary derivation of seconds-float end time. See
    :func:`_snippet_start_time` for why this is computed rather than
    read from the row.
    """
    start_ms = snippet.get("start_offset_ms")
    dur_ms = snippet.get("duration_ms")
    if start_ms is None or dur_ms is None:
        return None
    return round((float(start_ms) + float(dur_ms)) / 1000.0, 3)


def _resolve_turn_audio_url(snippet: dict) -> str | None:
    """Playback URL for a *turn* row (Chat Transcript / Conversation Timeline).

    Distinct from ``_resolve_snippet_audio_url``: a turn is the ORIGINAL
    per-turn recording, not a slice of the concat'd session file. The
    chat-history bubble plays it through a plain ``<audio>`` element with
    no offset clamping, so we must hand back a URL that resolves to a
    standalone-playable file — i.e. the per-turn ``audio_segment_path``
    (the R2 public URL written at upload time), NOT the concat'd
    storage_path the snippet panel uses.

    Fallback chain:
      1. audio_segment_path (set at turn upload, never NULL'd by finalize)
      2. storage_path signed via audio bucket — only when audio_segment_path
         is missing for legacy / cold-start rows
      3. None
    """
    seg = (snippet.get("audio_segment_path") or "").strip()
    if seg:
        return seg
    storage = (snippet.get("storage_path") or "").strip()
    if storage and not storage.startswith("charisma_snippets/"):
        try:
            from services.audio_storage import audio_public_url
            url = audio_public_url(storage)
            if url:
                return url
        except Exception as e:
            logger.warning(
                "turn audio URL: R2 build failed for %s: %s", storage, e
            )
    if storage:
        try:
            return db.create_signed_url(
                config.AUDIO_BUCKET_NAME, storage, config.SIGNED_URL_EXPIRY_SECONDS
            )
        except Exception:
            return None
    return None


@v2_bp.route("/admin/sessions/<session_id>", methods=["GET"])
@require_admin
def v2_admin_get_session(session_id):
    """Comprehensive admin payload for one session.

    Eager-loads everything the admin user-detail view needs:
      - the session row + global metrics
      - the chronological conversation turns (AI question / user answer
        pairs) flattened into a `[{role, content, ...}, ...]` array
      - the full list of charisma_snippets associated with the session
        (both interview turn rows and any extraction-only snippets) so
        the snippet panel and the conversation transcript share one
        source of truth

    The shape is deliberately denormalised — readers don't need to do a
    second round-trip per turn or per snippet to render the page.

    Auth: admin only (via @require_admin).

    Response (200):
        {
            "id":             str,
            "user_id":        str,
            "status":         str | null,
            "results_published_at": str | null,
            "created_at":     str | null,
            "global_metrics": { wpm, fillers, pause_ms, dynamic_db,
                                pitch_center, energy, kpi_score,
                                ai_score, ai_summary },
            "turns": [
                { "role": "ai",   "content": str, "tone": str | null,
                  "turn_number": int },
                { "role": "user", "content": str, "audio_url": str | null,
                  "duration_ms": int | null, "snippet_id": str,
                  "turn_number": int, "metrics": {...} },
                ...
            ],
            "snippets": [
                { "id": str, "type": str | null, "audio_url": str | null,
                  "transcript": str | null, "duration_ms": int | null,
                  "admin_comment": str | null, "is_skipped": bool,
                  "turn_number": int | null, "coach_label": str | null },
                ...
            ],
            "total_turns": int,
            "total_snippets": int
        }
    """
    try:
        session = db.get_session_with_global_metrics(session_id)
        if not session:
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found.",
            }), 404

        user_id = session.get("user_id")

        # One DB read for every snippet on this session — interview turns
        # AND extracted moments live in the same charisma_snippets table,
        # distinguished by whether `turn_number` is populated.
        all_snippets = db.get_snippets_by_session(session_id) or []

        # ── Turns: flatten interview rows into AI/user message pairs ────
        # Interview rows are the ones with turn_number set. We sort by
        # turn_number then start_offset_ms so within-turn ordering stays
        # stable even if turn_number duplicates appear.
        interview_rows = [s for s in all_snippets if s.get("turn_number") is not None]
        interview_rows.sort(
            key=lambda s: (
                s.get("turn_number") or 0,
                s.get("start_offset_ms") or 0,
            )
        )

        turns: list[dict] = []
        for s in interview_rows:
            q_text = (s.get("question_text") or "").strip()
            if q_text:
                turns.append({
                    "role": "ai",
                    "content": q_text,
                    "tone": s.get("question_tone"),
                    "turn_number": s.get("turn_number"),
                })
            turns.append({
                "role": "user",
                "content": (s.get("transcript") or "").strip(),
                # Per-turn ORIGINAL audio URL — plays standalone in the
                # chat bubble. Distinct from the snippet panel below
                # which gets concat'd-file slice URLs.
                "audio_url": _resolve_turn_audio_url(s),
                "duration_ms": s.get("duration_ms"),
                # Offset within the audio_url, for chat bubbles that need
                # to clamp playback. ZERO when audio_url points at the
                # per-turn original file (the common case); the row's
                # actual start_offset_ms (set by finalize) when audio_url
                # falls through to the concat'd full.webm. Frontend uses
                # (start_offset_ms, duration_ms) to seek+stop on play.
                "start_offset_ms": (
                    0
                    if (s.get("audio_segment_path") or "").strip()
                    else int(s.get("start_offset_ms") or 0)
                ),
                "snippet_id": str(s.get("id")) if s.get("id") else None,
                "turn_number": s.get("turn_number"),
                "metrics": {
                    "wpm": s.get("wpm"),
                    "fillers": s.get("fillers"),
                    "pause_ms": s.get("pause_ms"),
                    "dynamic_db": s.get("dynamic_db"),
                    "pitch_center": s.get("pitch_center"),
                    "energy": s.get("energy"),
                },
            })

        # ── Snippets: ONLY extracted highlight snippets ──────────────────
        # The snippet panel in the admin UI is a highlight reel — moments
        # of interest within the full session recording, NOT one row per
        # turn. Turn rows belong in the Chat Transcript / Conversation
        # Timeline (served via the `turns` array above).
        #
        # Distinction: turn rows have `turn_number IS NOT NULL` (set at
        # upload time by /v2/public/interview/upload-answer). Extracted
        # snippets have `turn_number IS NULL` and `source_type` populated
        # (typically "auto_extracted" or "student").
        extracted_only = [s for s in all_snippets if s.get("turn_number") is None]
        snippets = [
            {
                "id": str(s.get("id")) if s.get("id") else None,
                "session_id": str(s.get("session_id")) if s.get("session_id") else str(session_id),
                "user_id": str(s.get("user_id")) if s.get("user_id") else None,
                "recording_id": str(s.get("recording_id")) if s.get("recording_id") else None,
                "type": s.get("snippet_type") or s.get("coach_label"),
                "snippet_type": s.get("snippet_type"),
                # Provenance tag — "auto_extracted" for highlights from
                # services.snippet_truncation, "student" for user-uploaded
                # clips, NULL for legacy path-B rows. Frontend filters
                # the snippet panel on this so legacy noise stays hidden.
                "source_type": s.get("source_type"),
                "coach_label": s.get("coach_label"),
                "audio_url": _resolve_snippet_audio_url(s),
                "audio_segment_path": s.get("audio_segment_path"),
                "storage_path": s.get("storage_path"),
                "transcript": s.get("transcript"),
                "duration_ms": s.get("duration_ms"),
                "start_offset_ms": s.get("start_offset_ms"),
                "admin_comment": s.get("admin_comment"),
                "is_skipped": bool(s.get("is_skipped", False)),
                "turn_number": s.get("turn_number"),
                # Derived at API boundary — these columns don't exist
                # in the schema. See services/db.py::update_snippet_
                # boundaries for the canonical model rationale.
                "start_time": _snippet_start_time(s),
                "end_time": _snippet_end_time(s),
                # Coaching-outcome blob written by
                # services.coaching_outcomes.evaluate_and_record_followup_
                # outcome after the user answered turn 1 of a contextual
                # chat that this snippet seeded (via /chat?sourceSnippet=
                # <id>). Surfaced here so the admin page can render the
                # score + the user's actual answer next to the comment
                # the admin originally wrote — closing the feedback
                # loop. NULL until the user has clicked the CTA AND
                # answered the first question.
                "follow_up_outcome": s.get("follow_up_outcome"),
                "created_at": s.get("created_at"),
            }
            for s in extracted_only
        ]

        global_metrics = {
            "wpm": session.get("global_wpm"),
            "fillers": session.get("global_fillers"),
            "pause_ms": session.get("global_pause_ms"),
            "dynamic_db": session.get("global_dynamic_db"),
            "pitch_center": session.get("global_pitch_center"),
            "energy": session.get("global_energy"),
            "kpi_score": session.get("kpi_score"),
            # Phase 11 — stickiness-topic. Three NULL fields when the
            # admin hasn't yet clicked "Compute Metrics" on this
            # session; the frontend renders "—" in that case. The
            # legacy ai_score / ai_summary block was removed when the
            # panel was redesigned to KPI + Stickiness.
            "stickiness_top_topic": session.get("stickiness_top_topic"),
            "stickiness_score": session.get("stickiness_score"),
            "stickiness_topic_distribution": session.get(
                "stickiness_topic_distribution"
            ),
            "stickiness_computed_at": session.get("stickiness_computed_at"),
            # Phase 17.1 — drift-guard verdict. The admin UI can
            # render a "needs review" banner when this is True and
            # surface drift_diagnostic for the explanation.
            "needs_admin_review": bool(session.get("needs_admin_review")),
            "drift_diagnostic": session.get("drift_diagnostic"),
            # Phase 18.x — Performance summary narrative. The DB
            # column is the legacy ai_task_alignment_comment (the
            # column name pre-dates the API rename); the FE-canonical
            # field name is session_kpi_narrative. The immutable AI
            # draft baseline lives in session_kpi_narrative_ai_draft
            # and is the diff source for the trivial-edit gate on
            # PATCH /v2/admin/sessions/<id>/kpi-narrative.
            "session_kpi_narrative": session.get(
                "ai_task_alignment_comment"
            ),
            "session_kpi_narrative_ai_draft": session.get(
                "session_kpi_narrative_ai_draft"
            ),
        }

        return jsonify({
            "id": str(session_id),
            "user_id": str(user_id) if user_id else None,
            "status": session.get("status"),
            "results_published_at": session.get("results_published_at"),
            "created_at": session.get("created_at"),
            "global_metrics": global_metrics,
            "turns": turns,
            "snippets": snippets,
            "total_turns": len(turns),
            "total_snippets": len(snippets),
        }), 200

    except Exception as e:
        logger.error("admin/sessions/<id> GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch session"}), 500


# ── Task 10 — Next-session icebreaker (admin endpoints) ─────────────
#
# Lives on session N's row; previewed/edited from admin Tab 1
# (Sessions & Analysis). After session N+1's first chat message
# delivers it (via /v2/user/chat/first-question), the row's status
# flips to 'delivered' and the card becomes read-only.
#
# Three endpoints below: GET (poll-safe; FE polls every ~3s while
# queue_status='not_yet_generated' post-finalize), PUT (Save —
# empty save = 'skipped'), POST /regenerate (blows away admin
# edits and re-runs the LLM; rate-limited).
#
# See: services/next_session_icebreaker.py for the generator +
# validator, services/db.py get_next_session_icebreaker_row /
# update_next_session_icebreaker_editable, and
# migrations/add_next_session_icebreaker_columns.sql for the
# column shape.


# In-process rate-limit map for the regenerate endpoint. {sid: ts}.
# Per-worker (no cross-worker coordination), 60s window. The map is
# bounded by the active-admin set size — no eviction needed at
# realistic scale. Promote to Redis if we ever multi-worker the
# admin surface heavily.
_ICEBREAKER_REGEN_RATE_LIMIT_SEC = 60
_icebreaker_regen_last: dict[str, float] = {}


def _build_icebreaker_response(
    session_id: str,
    row: dict,
) -> dict:
    """Shared GET-shape builder.

    Returns the payload structure documented in the FE handoff §2.
    Centralized so GET, PUT, and regenerate all return the same
    shape — FE handles a single response contract.
    """
    from services.next_session_icebreaker import derive_queue_status

    owner_id = row.get("user_id")
    # next_session_id derivation — only fire the lookup when there's
    # actually a draft to talk about. Saves a query on the
    # not_yet_generated state, which is what the FE polls hardest.
    next_session_id: str | None = None
    ai_draft_present = bool(
        (row.get("next_session_icebreaker_ai_draft") or "").strip()
    )
    if ai_draft_present and owner_id:
        next_session_id = db.get_next_session_id_for(
            user_id=str(owner_id),
            after_session_id=session_id,
        )

    queue_status = derive_queue_status(row, has_next_session=bool(next_session_id))

    return {
        "session_id": session_id,
        "ai_draft": row.get("next_session_icebreaker_ai_draft"),
        "ai_draft_generated_at": row.get(
            "next_session_icebreaker_ai_draft_generated_at",
        ),
        "current": row.get("next_session_icebreaker"),
        "edited_at": row.get("next_session_icebreaker_edited_at"),
        "edited_by_admin": bool(
            row.get("next_session_icebreaker_edited_at")
        ),
        "queue_status": queue_status,
        "next_session_id": next_session_id,
        "generation_error": row.get(
            "next_session_icebreaker_generation_error"
        ),
    }


@v2_bp.route(
    "/admin/sessions/<session_id>/next-session-icebreaker",
    methods=["GET"],
)
@require_admin
def v2_admin_get_next_session_icebreaker(session_id):
    """Read the icebreaker state for ``session_id``.

    Poll-safe per FE handoff Change 3: FE polls every ~3s while the
    derived queue_status is 'not_yet_generated' (post-finalize
    spinner), capped at ~60s then manual refresh. Single-row read,
    optional one-query lookup for n+1 — well under the cost
    threshold for that polling cadence.

    Responses:
      200 — the payload shape in services.next_session_icebreaker
            documentation + FE handoff §2.
      400 INVALID_INPUT       — session_id not a UUID
      404 SESSION_NOT_FOUND   — session row missing OR columns not
                                migrated. Same code so the FE
                                renders an empty card either way;
                                the deploy-time migration mismatch
                                is logged server-side.
      500 V2_ERROR            — unexpected.
    """
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "session_id must be a valid UUID",
        }), 400

    try:
        row = db.get_next_session_icebreaker_row(session_id)
        if not row:
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found",
            }), 404

        return jsonify(
            _build_icebreaker_response(session_id, row),
        ), 200

    except Exception as e:
        logger.error(
            "admin/sessions/<id>/next-session-icebreaker GET "
            "failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to fetch next-session icebreaker",
        }), 500


@v2_bp.route(
    "/admin/sessions/<session_id>/next-session-icebreaker",
    methods=["PUT"],
)
@require_admin
def v2_admin_update_next_session_icebreaker(session_id):
    """Save an admin edit to the icebreaker.

    Body::

        { "question": "What surprised you about presenting last week?" }

    Behaviour:
      - Empty-after-trim → status='skipped', current=NULL. n+1 falls
        through to the default first-question path.
      - Non-empty → status='pending', current=<cleaned text>. Hard-
        fails (422) if question doesn't end with '?' (FE handoff Q4)
        or is < 5 / > 280 chars.
      - NO EDIT_TOO_SMALL gate (FE handoff Q2 — icebreakers are
        short by nature, a 1-word swap is meaningful).
      - The immutable ai_draft column is NEVER touched. Diff
        baseline stays pinned at generation time.

    Responses:
      200 — same payload shape as GET, with updated current/status/
            edited_at fields.
      400 INVALID_INPUT       — bad UUID or malformed body
      404 SESSION_NOT_FOUND   — session row missing
      422 INVALID_INPUT       — validator rejected (message in `error`)
      500 V2_ERROR            — unexpected
    """
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "session_id must be a valid UUID",
        }), 400

    try:
        from services.next_session_icebreaker import (
            IcebreakerValidationError,
            validate_icebreaker_body,
        )

        body = request.get_json(silent=True) or {}
        try:
            cleaned = validate_icebreaker_body(body)
        except IcebreakerValidationError as ve:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": str(ve),
            }), 422

        # cleaned == None means "save empty" — admin chose skip.
        if cleaned is None:
            status_value = "skipped"
            current_value: str | None = None
        else:
            status_value = "pending"
            current_value = cleaned

        row_before = db.get_next_session_icebreaker_row(session_id)
        if not row_before:
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found",
            }), 404

        now_iso = datetime.now(timezone.utc).isoformat()
        ok = db.update_next_session_icebreaker_editable(
            session_id=session_id,
            current=current_value,
            edited_at=now_iso,
            status=status_value,
        )
        if not ok:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to persist edit",
            }), 500

        logger.info(
            "admin/next-session-icebreaker.save session=%s "
            "status=%s len=%d",
            session_id, status_value,
            len(current_value or ""),
        )

        # Re-read so the response carries the freshly persisted
        # values (no client/server drift on the timestamp).
        row_after = db.get_next_session_icebreaker_row(session_id) or row_before
        return jsonify(
            _build_icebreaker_response(session_id, row_after),
        ), 200

    except Exception as e:
        logger.error(
            "admin/sessions/<id>/next-session-icebreaker PUT "
            "failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save next-session icebreaker",
        }), 500


@v2_bp.route(
    "/admin/sessions/<session_id>/next-session-icebreaker/regenerate",
    methods=["POST"],
)
@require_admin
def v2_admin_regenerate_next_session_icebreaker(session_id):
    """Re-run the LLM to produce a fresh icebreaker.

    DESTRUCTIVE: per FE handoff Q3, regenerate blows away any
    admin edit on both columns — fresh ai_draft AND fresh current.
    FE owns the confirm modal.

    Rate-limited to one call per session per minute (per worker)
    unless ``{"force": true}`` is in the body. The cap exists to
    keep an admin's accidental double-click from doubling our LLM
    cost, not as a security boundary.

    Responses:
      200 — same payload shape as GET, with new ai_draft + current.
      400 INVALID_INPUT       — bad UUID
      404 SESSION_NOT_FOUND   — session row missing
      429 RATE_LIMITED        — too soon since last regen; includes
                                ``retry_after_seconds``.
      502 LLM_UNAVAILABLE     — generator returned None (LLM down,
                                empty response, or transcript too
                                short). The generation_error column
                                carries the specific tag.
      500 V2_ERROR            — unexpected
    """
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "session_id must be a valid UUID",
        }), 400

    try:
        body = request.get_json(silent=True) or {}
        force = bool(body.get("force", False))

        # Existence check — match the PUT behavior of returning 404
        # before any DB writes when the session is gone.
        row_before = db.get_next_session_icebreaker_row(session_id)
        if not row_before:
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found",
            }), 404

        # Rate-limit: per-session, per-worker, in-memory map.
        # `time.monotonic()` is non-decreasing within a process so a
        # clock-skew event can't accidentally expire a valid entry.
        now_mono = time.monotonic()
        if not force:
            last = _icebreaker_regen_last.get(session_id)
            if last is not None:
                elapsed = now_mono - last
                if elapsed < _ICEBREAKER_REGEN_RATE_LIMIT_SEC:
                    retry_after = int(
                        _ICEBREAKER_REGEN_RATE_LIMIT_SEC - elapsed
                    ) + 1
                    return jsonify({
                        "code": "RATE_LIMITED",
                        "error": (
                            "Regenerate is rate-limited. Try again in "
                            f"{retry_after}s, or pass force=true."
                        ),
                        "retry_after_seconds": retry_after,
                    }), 429

        # Mark the attempt timestamp BEFORE the LLM call so a slow
        # call (or one that hangs to timeout) still counts against
        # the limit. Otherwise an admin could mash regenerate
        # during a slow LLM and queue up parallel duplicates.
        _icebreaker_regen_last[session_id] = now_mono

        from services.next_session_icebreaker import (
            generate_next_session_icebreaker,
        )
        question = generate_next_session_icebreaker(
            session_id=session_id, overwrite=True,
        )

        if not question:
            # generator already wrote the generation_error tag.
            # Re-read so the response surfaces it.
            row_after = (
                db.get_next_session_icebreaker_row(session_id)
                or row_before
            )
            payload = _build_icebreaker_response(session_id, row_after)
            payload["code"] = "LLM_UNAVAILABLE"
            payload["error"] = (
                "Generation failed. The error tag is on "
                "generation_error; try Regenerate again or check "
                "the snippet content."
            )
            return jsonify(payload), 502

        row_after = (
            db.get_next_session_icebreaker_row(session_id)
            or row_before
        )
        logger.info(
            "admin/next-session-icebreaker.regenerate session=%s "
            "len=%d", session_id, len(question or ""),
        )
        return jsonify(
            _build_icebreaker_response(session_id, row_after),
        ), 200

    except Exception as e:
        logger.error(
            "admin/sessions/<id>/next-session-icebreaker/regenerate "
            "failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to regenerate next-session icebreaker",
        }), 500


@v2_bp.route("/chat/snippet-followup", methods=["POST"])
@require_auth
def v2_chat_snippet_followup():
    """One-shot follow-up question generator after a user labels a snippet.

    Body (JSON):
      - snippet_id (UUID, required)
      - user_label (bool, required) — AGREEMENT semantic; see module-level
        comment above and ``docs/PANEL-STATE-MATRIX.md`` preamble.

    Response 200 (JSON):
      {
        "followup_text": "<≤2-sentence question>",
        "debug": {
          "model": "gpt-4o-mini",
          "user_label_interpretation": "agreement"
        }
      }

    Errors:
      400 INVALID_INPUT                — missing/malformed fields
      404 NOT_FOUND                    — snippet missing OR not owner-scoped
      422 SNIPPET_CONTEXT_UNAVAILABLE  — snippet lacks admin_comment
      500 V2_ERROR                     — LLM/parse/other failure
    """
    try:
        user_id = request.user_id
        body = request.get_json(silent=True) or {}

        # ── Input validation ──
        snippet_id = (body.get("snippet_id") or "").strip()
        if not snippet_id or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        user_label_raw = body.get("user_label")
        if not isinstance(user_label_raw, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "user_label must be a boolean (agreement semantic)",
            }), 400
        user_label: bool = user_label_raw

        # ── Owner-scoped fetch ──
        # 404 (not 403) on foreign-owner so we don't leak existence.
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        admin_comment = (snippet.get("admin_comment") or "").strip()
        if not admin_comment:
            # Without the coach's insight the follow-up question would
            # be ungrounded ("how did that make you feel?" style filler).
            # Refuse rather than emit something vapid.
            return jsonify({
                "code": "SNIPPET_CONTEXT_UNAVAILABLE",
                "error": "Snippet has no admin_comment yet",
            }), 422

        transcript = (
            (snippet.get("transcript") or "")
            or (snippet.get("transcription_text") or "")
            or (snippet.get("transcript_text") or "")
            or (snippet.get("transcript_excerpt") or "")
        ).strip()
        coach_label = (snippet.get("coach_label") or "").strip().lower() or None
        snippet_type = (snippet.get("snippet_type") or "").strip().lower() or None
        # Display label = whatever the AI/coach asserted about this
        # snippet, in user-facing words. Fall back through coach_label →
        # snippet_type → "this moment" so the prompt never reads
        # "you {None} this".
        display_label = coach_label or snippet_type or "this moment"

        # ── LLM call ──
        from services.llm import chat_complete
        from services.llm_config import SPEC_SNIPPET_FOLLOWUP

        agreement_phrase = (
            "The user AGREES with the coach's label."
            if user_label
            else "The user DISAGREES with the coach's label."
        )
        system = (
            "You are a warm, curious communication coach. After a "
            "user has agreed or disagreed with a coach's label on a "
            "moment from their own speech, you ask ONE short "
            "follow-up question (≤2 sentences) that invites them to "
            "reflect on why. Anchor your question to the specific "
            "coach insight provided; never ask generic 'how did that "
            "feel' filler. Output strict JSON: "
            '{"followup_text": "<question>"}.'
        )
        user_prompt = (
            f"Coach's label on this snippet: {display_label}\n"
            f"Coach's written insight (admin_comment):\n{admin_comment}\n"
            f"User's spoken transcript on this moment:\n"
            f"{transcript or '(no transcript captured)'}\n\n"
            f"User's response: {agreement_phrase}\n\n"
            "Return strict JSON with a single key followup_text."
        )

        result = chat_complete(
            spec=SPEC_SNIPPET_FOLLOWUP,
            system=system,
            user=user_prompt,
            surface="snippet_followup",
            user_id=str(user_id),
        )
        if result is None:
            # chat_complete already logged the failure reason.
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to generate follow-up",
            }), 500

        parsed = result.parsed
        if not isinstance(parsed, dict):
            logger.error(
                "snippet_followup.malformed_json user=%s snippet=%s raw=%r",
                user_id, snippet_id, result.text[:200],
            )
            return jsonify({
                "code": "V2_ERROR",
                "error": "Coach response was malformed",
            }), 500
        followup_text = (parsed.get("followup_text") or "").strip()

        if not followup_text:
            logger.warning(
                "snippet_followup.empty_text user=%s snippet=%s",
                user_id, snippet_id,
            )
            return jsonify({
                "code": "V2_ERROR",
                "error": "Coach returned an empty follow-up",
            }), 500

        return jsonify({
            "followup_text": followup_text,
            "debug": {
                "model": result.model,
                # PIN: never change to "type" without coordinated FE
                # update + matrix-doc preamble update. See module-level
                # comment for the full contract.
                "user_label_interpretation": "agreement",
            },
        }), 200

    except Exception as e:
        logger.error("snippet_followup.error err=%s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to generate follow-up",
        }), 500


# ── Coaching Directives Queue (Phase Directives-Queue / BE) ───────
#
# User-level 5-step coaching arc. Admin authors a sequence of 5
# questions for one user; the chat / interview surface pops them
# one at a time as the AI question for the next turn, marking
# each exhausted as it fires. When the queue is empty, those
# surfaces fall back to _generate_llm_question.
#
# Replaces the per-user single-question
# user_settings.queued_override_question (removed in Week-1
# cleanup) and the conceptually-misplaced snippet-level
# next_question_1..5 columns (which never shipped to this branch).
#
# Audit: every write logs an INFO line with structured fields
# (user, admin, op, row count). We do NOT route to
# admin_annotations_log — that table's schema captures the RLHF
# (predicted, final) training pair, not admin config changes. The
# application log is the audit trail of record for this surface.


# How many directives the admin authors per arc. Tightened from 5
# to 2 — product spec v2 says two questions is the right size.
# DB CHECK constraint allows 1..5 (legacy), so app-level validation
# is the one enforcing the new ceiling for new arcs.
_DIRECTIVES_ARC_LENGTH = 2
_DIRECTIVES_VALID_POSITIONS = set(range(1, _DIRECTIVES_ARC_LENGTH + 1))


def _validate_directives_rows(rows: object) -> tuple[list, str | None]:
    """Returns (normalized_rows, None) on success or
    ([], error_message) on validation failure. Keeps the validation
    logic out of the route body so the rules are easy to spot and
    test."""
    if not isinstance(rows, list):
        return [], "rows must be an array"
    if len(rows) != _DIRECTIVES_ARC_LENGTH:
        return [], (
            f"rows must contain exactly {_DIRECTIVES_ARC_LENGTH} "
            f"entries (positions 1..{_DIRECTIVES_ARC_LENGTH})"
        )

    seen_positions: set[int] = set()
    out: list[dict] = []
    for idx, r in enumerate(rows):
        if not isinstance(r, dict):
            return [], f"rows[{idx}] must be an object"
        try:
            pos = int(r.get("position"))
        except (TypeError, ValueError):
            return [], (
                f"rows[{idx}].position must be an integer "
                f"1..{_DIRECTIVES_ARC_LENGTH}"
            )
        if pos < 1 or pos > _DIRECTIVES_ARC_LENGTH:
            return [], (
                f"rows[{idx}].position must be in "
                f"[1, {_DIRECTIVES_ARC_LENGTH}], got {pos}"
            )
        if pos in seen_positions:
            return [], f"position {pos} appears more than once"
        seen_positions.add(pos)
        intent_tag = (r.get("intent_tag") or "").strip()
        question = (r.get("question") or "").strip()
        if not intent_tag:
            return [], f"rows[{idx}].intent_tag must be non-empty"
        if not question:
            return [], f"rows[{idx}].question must be non-empty"
        out.append({
            "position": pos,
            "intent_tag": intent_tag,
            "question": question,
        })

    # Positions must cover 1..N exactly (no gaps, no dupes — dupes
    # already caught above; this catches gaps).
    if seen_positions != _DIRECTIVES_VALID_POSITIONS:
        return [], (
            f"positions must cover {sorted(_DIRECTIVES_VALID_POSITIONS)} "
            f"exactly; got {sorted(seen_positions)}"
        )

    # Sort by position so persistence + audit log share one order.
    out.sort(key=lambda r: r["position"])
    return out, None


@v2_bp.route(
    "/admin/users/<user_id>/directives-queue",
    methods=["GET"],
)
@require_admin
def v2_admin_get_directives_queue(user_id):
    """Return the user's current 5-step coaching arc.

    Response 200:
        {
          "rows": [
            {"position": 1, "intent_tag": "warm-up", "question": "...",
             "exhausted": false, "id": "...", "created_at": "...",
             "created_by_admin_id": "..."},
            ...
          ]
        }
    Empty list when no queue exists.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400
    try:
        rows = db.list_directives_queue(user_id)
        return jsonify({"rows": rows}), 200
    except Exception as e:
        logger.error(
            "directives_queue.get_error user=%s err=%s",
            user_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to read directives queue",
        }), 500


@v2_bp.route(
    "/admin/users/<user_id>/directives-queue",
    methods=["POST"],
)
@require_admin
def v2_admin_post_directives_queue(user_id):
    """Replace the user's coaching arc with the posted 5 rows.

    Body (JSON):
        {
          "rows": [
            {"position": 1, "intent_tag": "...", "question": "..."},
            ... five entries total ...
          ]
        }

    Atomically (at the application layer): DELETE existing rows
    for this user, then INSERT the new 5. The historical record is
    in the application log (logger.info with structured fields).

    Returns the inserted rows as the response so the FE can
    rebuild its view without an extra GET round-trip.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400
    try:
        body = request.get_json(silent=True) or {}
        rows_raw = body.get("rows")
        normalized, err = _validate_directives_rows(rows_raw)
        if err:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": err,
            }), 400

        admin_user_id = str(request.user_id) if request.user_id else None
        inserted = db.replace_directives_queue(
            user_id=user_id,
            rows=normalized,
            admin_user_id=admin_user_id,
        )
        if not inserted:
            # Either the table is missing (pre-migration) or the
            # INSERT half-failed after the DELETE. Either way the
            # user now has no queue; surface a recoverable error
            # so the admin retries rather than thinking it worked.
            return jsonify({
                "code": "QUEUE_WRITE_FAILED",
                "error": (
                    "Failed to persist directives queue. The "
                    "user's queue may now be empty — please retry."
                ),
            }), 500

        # Structured audit log. One line per POST, parseable by
        # log-ingesting tools downstream.
        logger.info(
            "directives_queue.replace user=%s admin=%s rows=%d "
            "positions=%s",
            user_id, admin_user_id, len(inserted),
            [r.get("position") for r in inserted],
        )
        return jsonify({"rows": inserted}), 200

    except Exception as e:
        logger.error(
            "directives_queue.post_error user=%s err=%s",
            user_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to write directives queue",
        }), 500


@v2_bp.route(
    "/admin/users/<user_id>/directives-queue",
    methods=["DELETE"],
)
@require_admin
def v2_admin_delete_directives_queue(user_id):
    """Clear the user's coaching arc. Idempotent — calling on an
    empty queue returns 200 with cleared:true."""
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400
    try:
        admin_user_id = str(request.user_id) if request.user_id else None
        ok = db.clear_directives_queue(user_id)
        if not ok:
            return jsonify({
                "code": "QUEUE_WRITE_FAILED",
                "error": "Failed to clear directives queue",
            }), 500
        logger.info(
            "directives_queue.clear user=%s admin=%s",
            user_id, admin_user_id,
        )
        return jsonify({"cleared": True}), 200
    except Exception as e:
        logger.error(
            "directives_queue.delete_error user=%s err=%s",
            user_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to clear directives queue",
        }), 500


@v2_bp.route(
    "/admin/users/<user_id>/directives-queue/suggest",
    methods=["POST"],
)
@require_admin
def v2_admin_suggest_directives_queue(user_id):
    """Generate 5 LLM-suggested directives for this user. NEVER
    persists — the admin reviews the suggestions, edits as
    needed, and then POSTs them via the normal endpoint above.

    Body (JSON, optional):
        {"snippet_id_context": "<uuid>"}  // soft anchor for the arc

    Response 200:
        {
          "rows": [
            {"intent_tag": "...", "question": "..."},
            ... up to 5 entries ...
          ]
        }

    May return ``rows: []`` when:
      - LLM is unavailable (OPENAI_API_KEY missing, etc.)
      - The user has no recent transcripts AND no profile signals
        (cold-start — better to let the admin author manually
        than emit generic filler)
      - The model returns malformed JSON
    The admin UI should render an empty form for manual authoring
    in those cases.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "user_id must be a valid UUID",
        }), 400
    try:
        body = request.get_json(silent=True) or {}
        snippet_id_context = (
            body.get("snippet_id_context") or ""
        ).strip() or None
        if snippet_id_context and not _is_valid_uuid(snippet_id_context):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id_context must be a UUID if provided",
            }), 400

        from services.directive_suggestions import suggest_directive_arc
        rows = suggest_directive_arc(
            user_id=user_id,
            snippet_id_context=snippet_id_context,
        )

        admin_user_id = str(request.user_id) if request.user_id else None
        logger.info(
            "directives_queue.suggest user=%s admin=%s anchor=%s "
            "rows=%d",
            user_id, admin_user_id, snippet_id_context or "-",
            len(rows),
        )
        return jsonify({"rows": rows}), 200

    except Exception as e:
        logger.error(
            "directives_queue.suggest_error user=%s err=%s",
            user_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to generate suggestions",
        }), 500


# ── Public interview funnel: end-of-session signal ────────────────
#
# The frontend BFF at /api/session/finalize forwards here when the
# guest interview funnel ends. Three legitimate reasons today:
#   • threshold  — cold-start 30s aggregate audio threshold reached
#   • max_turns  — legacy fallback when the turn cap fires
#   • user_done  — user clicked "Finish & see results"
#
# Historical note: this endpoint did not exist in this repo. The FE
# BFF was built against it on the assumption that the backend
# wanted an explicit end-of-funnel signal. Without it the FE was
# logging a 404 on every session close. We're shipping the stub now
# so the FE stays clean; the actual end-of-funnel bookkeeping
# happens elsewhere (via upload-answer + the results-publish flow),
# so this handler is intentionally minimal:
#
#   - validates inputs
#   - emits a structured log line so funnel-completion analytics
#     can grep on `funnel.end sid=... reason=...`
#   - returns 200 — the FE treats failure as non-fatal anyway, so
#     200 just keeps the console quiet
#
# When analytics actually wants this data persisted (per-row in
# Postgres, or piped to a warehouse), extend this handler to write
# to v2_sessions or a dedicated `funnel_events` table. For now,
# log-line analytics is enough.


_INTERVIEW_FINALIZE_VALID_REASONS = {"threshold", "max_turns", "user_done"}

# Signup-CTA default copy. Task 7 — confirmed wording from the FE
# handoff reply (matches the brainstorm's "Sign up for full
# analysis" phrasing). Surfaced as `next.signup_cta.copy` in the
# finalize response — a BE flag (not FE hardcoded) so the copy is
# A/B-able without a FE deploy and per-user variants can fan out
# later (e.g. warm-lead vs cold).
_FINALIZE_SIGNUP_CTA_COPY = (
    "Sign up for your full analysis."
)


# ── Coaching intro bubble (Phase Single-Slot-Chat) ────────────────
#
# Frontend contract: after the user labels a snippet (Yes/No) and
# reads the follow-up question, the chat transitions into a new
# official recording session. The intro bubble for that new
# session should feel continuous with what the user just labeled
# — referencing the coach's insight, inviting them to record
# now.
#
# 1–2 sentences, ≤180 chars target, generated by gpt-4o-mini
# grounded in the just-labeled snippet. Falls back to a static
# line when the LLM is unavailable or the snippet lacks
# admin_comment.
#
# Endpoint is owner-scoped: foreign snippet → 404, not 403
# (avoids existence leak — same pattern as snippet-followup).


_COACHING_INTRO_STATIC_FALLBACK = (
    "Now let's record a fresh take and see what shifts. "
    "Tap the mic below when you're ready."
)


@v2_bp.route("/coaching/intro-bubble", methods=["POST"])
@require_auth
def v2_coaching_intro_bubble():
    """Generate a personalized intro line for the new official
    recording session that follows snippet labeling.

    Body (JSON):
      - snippet_id (UUID, required) — the snippet the user just
        labeled. Used to ground the intro in real context.

    Response 200 (always — see fallback contract below):
      {
        "intro_text": "<1–2 sentence intro string>",
        "debug": {
          "model": "gpt-4o-mini",
          "prompt_version": "coaching_intro_v1",
          "source": "llm" | "static_fallback"
        }
      }

    Errors:
      400 INVALID_INPUT  — missing / malformed snippet_id
      404 NOT_FOUND      — snippet missing or not owner-scoped

    Fallback contract: when the LLM call fails OR the snippet is
    missing admin_comment, we still return 200 with the static
    fallback string. The FE NEVER has to handle "intro generation
    failed" — it always gets a usable string.
    """
    try:
        user_id = request.user_id
        body = request.get_json(silent=True) or {}

        snippet_id = (body.get("snippet_id") or "").strip()
        if not snippet_id or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        # Owner-scoped fetch. Foreign / nonexistent → 404 (no
        # existence leak).
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        # ── Directives queue takes priority (Item 7 / Phase 2) ──
        # If the admin has authored a directive arc for this user,
        # pop the next un-exhausted entry and use its question as
        # the intro line — this "smoothly introduces" the admin's
        # next question for the fresh recording session. The
        # admin-authored copy wins over the LLM personalization.
        try:
            directive = db.pop_next_directive(str(user_id))
        except Exception as pop_err:
            logger.warning(
                "coaching_intro_bubble.pop_directive_failed "
                "user=%s err=%s — falling through to LLM path",
                user_id, pop_err,
            )
            directive = None

        if directive and (directive.get("question") or "").strip():
            logger.info(
                "coaching_intro_bubble.directives_queue_hit "
                "user=%s pos=%s intent=%s",
                user_id, directive.get("position"),
                directive.get("intent_tag"),
            )
            return jsonify({
                "intro_text": directive["question"].strip(),
                "debug": {
                    "model": "gpt-4o-mini",
                    "prompt_version": "coaching_intro_v1",
                    "source": "directives_queue",
                    "directive": {
                        "position": directive.get("position"),
                        "intent_tag": directive.get("intent_tag"),
                    },
                },
            }), 200

        # Try the LLM path. ``generate_intro_line`` returns None on
        # any failure mode — we then drop to the static fallback.
        from services.coaching_intro import (
            generate_intro_line,
            PROMPT_VERSION,
        )
        intro = None
        try:
            intro = generate_intro_line(
                user_id=str(user_id),
                snippet=snippet,
            )
        except Exception as gen_err:
            # Defensive: generate_intro_line is supposed to swallow
            # its own errors, but if anything escapes we still want
            # to return 200 with the fallback.
            logger.warning(
                "coaching_intro_bubble.generator_raised user=%s "
                "snippet=%s err=%s — using fallback",
                user_id, snippet_id, gen_err,
            )
            intro = None

        if intro:
            return jsonify({
                "intro_text": intro,
                "debug": {
                    "model": "gpt-4o-mini",
                    "prompt_version": PROMPT_VERSION,
                    "source": "llm",
                },
            }), 200

        # Fallback path — still 200. The FE renders this string
        # exactly like the LLM path; ``debug.source`` lets devs
        # spot fallback rates without consulting backend logs.
        return jsonify({
            "intro_text": _COACHING_INTRO_STATIC_FALLBACK,
            "debug": {
                "model": "gpt-4o-mini",
                "prompt_version": PROMPT_VERSION,
                "source": "static_fallback",
            },
        }), 200

    except Exception as e:
        logger.error(
            "coaching_intro_bubble.error err=%s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Last-resort: still return 200 with the static fallback so
        # the FE flow never breaks on a backend bug. Matches the
        # "always usable string" contract above.
        return jsonify({
            "intro_text": _COACHING_INTRO_STATIC_FALLBACK,
            "debug": {
                "model": "gpt-4o-mini",
                "prompt_version": "coaching_intro_v1",
                "source": "static_fallback",
            },
        }), 200


# ── tester-soft-v1 — KPI timeline + question pool admin CRUD ─────────
#
# M1.1 (raw mode): GET /v2/user/kpi/timeline — per-session KPI
#                  scores in chronological order with a summary card.
#                  No smoothing yet; FE can render a chart now, the
#                  `smoothed_kpi` field will be additive when it lands.
#
# M1.3 schema-only: GET / POST / PATCH / DELETE for chat_question_pool
#                   admin curation. Empty pool = legacy question logic
#                   so this changes nothing until content seeds.


_QUESTION_POOL_VALID_INTENTS = (
    "charisma", "stress", "trust", "post_official",
)
_QUESTION_POOL_VALID_POSITIONS = ("opener", "mid", "closer")
_QUESTION_POOL_MAX_TEXT_LEN = 500


def _validate_question_pool_body(body: Any, *, partial: bool) -> dict:
    """Manual validator for POST/PATCH bodies on the question pool.

    Mirrors the style of v2_routes.py's other manual validators
    (no Pydantic dep). When ``partial=True``, fields are optional
    (PATCH); when False (POST), intent + text are required.

    Returns a clean dict on success. Raises ValueError with a
    user-friendly message on failure.
    """
    if not isinstance(body, dict):
        raise ValueError("Body must be a JSON object")

    cleaned: dict[str, Any] = {}

    if "intent" in body:
        intent = (body.get("intent") or "").strip().lower()
        if intent not in _QUESTION_POOL_VALID_INTENTS:
            raise ValueError(
                "intent: must be one of "
                f"{', '.join(_QUESTION_POOL_VALID_INTENTS)}"
            )
        cleaned["intent"] = intent
    elif not partial:
        raise ValueError("intent: required")

    if "text" in body:
        text_raw = body.get("text")
        if not isinstance(text_raw, str):
            raise ValueError("text: must be a string")
        text = text_raw.strip()
        if not text:
            raise ValueError("text: must be non-empty")
        if len(text) > _QUESTION_POOL_MAX_TEXT_LEN:
            raise ValueError(
                "text: must be "
                f"{_QUESTION_POOL_MAX_TEXT_LEN} characters or fewer"
            )
        cleaned["text"] = text
    elif not partial:
        raise ValueError("text: required")

    if "weight" in body:
        weight_raw = body.get("weight")
        if isinstance(weight_raw, bool) or not isinstance(weight_raw, int):
            raise ValueError("weight: must be an integer")
        if weight_raw < 0 or weight_raw > 10_000:
            raise ValueError("weight: must be between 0 and 10000")
        cleaned["weight"] = weight_raw

    if "position_hint" in body:
        pos = body.get("position_hint")
        if pos is not None:
            if not isinstance(pos, str):
                raise ValueError("position_hint: must be a string or null")
            pos = pos.strip().lower()
            if pos not in _QUESTION_POOL_VALID_POSITIONS:
                raise ValueError(
                    "position_hint: must be one of "
                    f"{', '.join(_QUESTION_POOL_VALID_POSITIONS)} or null"
                )
        cleaned["position_hint"] = pos

    if "active" in body:
        active = body.get("active")
        if not isinstance(active, bool):
            raise ValueError("active: must be a boolean")
        cleaned["active"] = active

    if "notes" in body:
        notes = body.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ValueError("notes: must be a string or null")
        if isinstance(notes, str) and len(notes) > 2_000:
            raise ValueError("notes: must be 2000 characters or fewer")
        cleaned["notes"] = notes

    return cleaned


@v2_bp.route("/admin/question-pool", methods=["GET"])
@require_admin
def v2_admin_question_pool_list():
    """List questions in the pool, filterable by intent + locale.

    Query params:
      intent (optional)   — 'charisma' | 'stress' | 'trust' | 'post_official'
      locale (default 'en')
      active_only (default true) — set to 'false' to include soft-
                                   deleted entries (admin audit)

    Response 200:
      { "questions": [ {id, intent, text, weight, locale, active,
                        position_hint, created_at, notes}, ... ],
        "count": int }
    """
    try:
        intent = (request.args.get("intent") or "").strip().lower() or None
        if intent is not None and intent not in _QUESTION_POOL_VALID_INTENTS:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": (
                    "intent: must be one of "
                    f"{', '.join(_QUESTION_POOL_VALID_INTENTS)}"
                ),
            }), 400

        locale = (request.args.get("locale") or "en").strip()
        active_only_raw = (request.args.get("active_only") or "true").lower()
        active_only = active_only_raw not in ("false", "0", "no")

        rows = db.list_chat_question_pool(
            intent=intent,
            locale=locale,
            active_only=active_only,
        )
        return jsonify({
            "questions": rows,
            "count": len(rows),
        }), 200

    except Exception as e:
        logger.error(
            "admin/question-pool GET failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to list question pool",
        }), 500


@v2_bp.route("/admin/question-pool", methods=["POST"])
@require_admin
def v2_admin_question_pool_create():
    """Insert one question into the pool.

    Body:
      { "intent": "charisma", "text": "...", "weight": 100,
        "position_hint": "opener" | "mid" | "closer" | null,
        "notes": "optional admin note" }

    Responses:
      201 — created; returns the inserted row.
      422 INVALID_INPUT — validator rejected; message in `error`.
      500 V2_ERROR — DB write failed.
    """
    try:
        body = request.get_json(silent=True) or {}
        try:
            cleaned = _validate_question_pool_body(body, partial=False)
        except ValueError as ve:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": str(ve),
            }), 422

        created_by = getattr(request, "user_id", None)
        row = db.insert_chat_question(
            intent=cleaned["intent"],
            text=cleaned["text"],
            weight=cleaned.get("weight", 100),
            locale=(body.get("locale") or "en").strip(),
            position_hint=cleaned.get("position_hint"),
            created_by=str(created_by) if created_by else None,
            notes=cleaned.get("notes"),
        )
        if not row:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to persist question",
            }), 500

        logger.info(
            "admin/question-pool.create id=%s intent=%s",
            row.get("id"), cleaned["intent"],
        )
        return jsonify({"question": row}), 201

    except Exception as e:
        logger.error(
            "admin/question-pool POST failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to create question",
        }), 500


@v2_bp.route("/admin/question-pool/<question_id>", methods=["PATCH"])
@require_admin
def v2_admin_question_pool_update(question_id):
    """Partial update of one question.

    Updatable fields: text, weight, active, position_hint, notes.
    intent + locale are NOT mutable here — those define the pool
    slot, and changing them is functionally a delete + re-insert.

    Body example: { "active": false }
    Body example: { "text": "Updated phrasing?", "weight": 80 }

    Responses:
      200 — updated; returns the new row state.
      422 INVALID_INPUT — validator rejected.
      404 NOT_FOUND — question_id didn't resolve.
      500 V2_ERROR — DB write failed.
    """
    if not _is_valid_uuid(question_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "question_id must be a valid UUID",
        }), 400

    try:
        body = request.get_json(silent=True) or {}
        try:
            cleaned = _validate_question_pool_body(body, partial=True)
        except ValueError as ve:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": str(ve),
            }), 422

        # intent / locale are explicitly NOT honored in PATCH.
        cleaned.pop("intent", None)
        cleaned.pop("locale", None)

        row = db.update_chat_question(question_id, **cleaned)
        if not row:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Question not found",
            }), 404

        return jsonify({"question": row}), 200

    except Exception as e:
        logger.error(
            "admin/question-pool PATCH failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to update question",
        }), 500


@v2_bp.route("/admin/question-pool/<question_id>", methods=["DELETE"])
@require_admin
def v2_admin_question_pool_delete(question_id):
    """Soft-delete one question (sets ``active=false``).

    Hard-delete is intentionally not exposed — questions that have
    been asked of N users carry audit weight, and a soft-delete
    preserves the "this question was previously in rotation" trail
    without breaking any historical join.

    Reactivation: PATCH with ``{"active": true}``.

    Responses:
      204 — soft-deleted.
      400 INVALID_INPUT — bad UUID.
      500 V2_ERROR — DB write failed.
    """
    if not _is_valid_uuid(question_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "question_id must be a valid UUID",
        }), 400

    try:
        ok = db.soft_delete_chat_question(question_id)
        if not ok:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to soft-delete question",
            }), 500
        return ("", 204)
    except Exception as e:
        logger.error(
            "admin/question-pool DELETE failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to soft-delete question",
        }), 500


# ── willab beta — Lab readout re-read + history (parked-restore + scroll-back) ─


@v2_bp.route("/lab/recordings/<session_id>/readout", methods=["GET"])
@optional_auth
def v2_guest_get_recording_readout(session_id):
    """Re-read a GUEST recording's readout — the unauth twin of
    /user/sessions/<id>/readout (bug fix 2026-07-13).

    Why it exists: a signed-out user records, gets the inline 201 readout,
    but the Say-It-Stronger cards generate a few seconds LATER (async
    daemon), and re-opening the recording (the "Your Recording" chat
    bubble) previously hit the @require_auth re-read → 401 → the FE's
    "We couldn't load these insights" screen. This endpoint lets the FE
    (a) POLL until the synonym cards populate and (b) re-open the
    recording, both without auth.

    Ownership model = the guest funnel's: the unguessable session UUID is
    the capability. HARD RULE — only an UNCLAIMED session (user_id IS
    NULL) is served without auth; once a session is CLAIMED by a user,
    only that owner may read it (else 404, no existence leak). So this can
    never surface a signed-in user's readout to a bare id.

    Response mirrors the authed readout: 200 { session_id, state, readout }
             · 400 bad uuid · 404 not found / claimed-by-another · 500
    """
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT", "error": "session_id must be a valid UUID",
        }), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({
                "code": "SESSION_NOT_FOUND", "error": "Recording not found",
            }), 404
        owner = session.get("user_id")
        caller = getattr(request, "user_id", None)
        # Claimed session → owner-only (they should use the authed route,
        # but honor it here for the owner too). Unclaimed → open to the id.
        if owner and str(owner) != str(caller or ""):
            return jsonify({
                "code": "SESSION_NOT_FOUND", "error": "Recording not found",
            }), 404

        # Async analysis (founder 2026-07-15) — job state first; the FE polls
        # this route (guests included) until analysis_state ready|failed.
        _an_state = session.get("analysis_state")
        if _an_state == "processing":
            return jsonify({
                "session_id": session_id, "state": "processing",
                "analysis_state": "processing", "readout": None,
            }), 200
        if _an_state == "failed":
            return jsonify({
                "session_id": session_id, "state": "failed",
                "analysis_state": "failed", "readout": None,
            }), 200

        from services.lab_recording import build_readout_from_session
        readout = build_readout_from_session(session_id)

        if session.get("results_published_at"):
            state = "insights_ready"
        elif session.get("status") == "pending_admin_review":
            state = "review_pending"
        else:
            state = "readout_ready"

        return jsonify({
            "session_id": session_id,
            "state": state,
            # Unambiguous poll terminal (see the authed twin): past
            # processing|failed everything is "ready".
            "analysis_state": "ready",
            "readout": readout,
        }), 200
    except Exception as e:
        logger.error(
            "lab/recordings/<id>/readout GET failed sid=%s err=%s",
            session_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch readout"}), 500


# ── willab beta — coach review flow (design §14, contract §3.8) ──────
#
# Two admin/coach endpoints. The split-sink wall (§2) is the rule: the
# USER re-read (/v2/user/sessions/<id>/readout) OMITS the private
# direction label; the COACH readout below INCLUDES it (the coach
# authors/corrects it). Identity is pseudonymized, never the real
# user_id (§14 red-line 6) — list = low-identifiability; detail =
# pseudonymized-not-anonymized (full transcript + goal, opaque identity).


def _pseudonymous_user_id(user_id):
    """Stable opaque pseudonym for a user_id (§14 red-line 6 — the coach
    never sees the real id). Deterministic so the same user groups across
    the queue + detail, but not reversible to the raw id."""
    if not user_id:
        return None
    import hashlib
    digest = hashlib.sha256(
        (_COACH_PSEUDONYM_SALT + str(user_id)).encode("utf-8")
    ).hexdigest()
    return "u_" + digest[:16]


@v2_bp.route("/admin/review-queue", methods=["GET"])
@require_admin
def v2_admin_review_queue():
    """① Coach review queue — review_pending willab Lab sessions, newest
    sent first. LOW-IDENTIFIABILITY: keyed on pseudonymous_user_id, never
    the real id (§14 red-line 6); topic + sent_at only — transcript + goal
    appear only in the per-session coach readout (②).

    Response 200: [ {session_id, topic, pseudonymous_user_id, sent_at} ]
    """
    try:
        rows = db.list_review_queue()
        out = []
        for r in rows:
            ctx = r.get("intake_context") if isinstance(r.get("intake_context"), dict) else {}
            out.append({
                "session_id": r.get("id"),
                "topic": (ctx or {}).get("topic"),
                "pseudonymous_user_id": _pseudonymous_user_id(r.get("user_id")),
                "sent_at": r.get("guest_claimed_at") or r.get("created_at"),
            })
        return jsonify(out), 200
    except Exception as e:
        logger.error("admin/review-queue GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch review queue"}), 500


# ── willab Phase 4 / Prompt 1 — Learning subsystem (SHADOW) admin surface ──
# The model trains on training_labels ⋈ the 11 features and predicts in SHADOW
# only — it influences NOTHING (no selection, no direction pre-fill). These
# endpoints are the human's window + manual "train now"; auto-retrain (B3) runs
# off the label/publish hook. All @require_admin_or_coach.

@v2_bp.route("/admin/learning/train", methods=["POST"])
@require_admin_or_coach
def v2_admin_learning_train():
    """Manual 'train now'. export → fit logistic → eval → store artifact +
    model_versions row (status=shadow). Small corpus → warnings, never junk.
    200 {version, metrics, corpus_size, warnings}."""
    try:
        from services.learning_train import train_and_register
        result = train_and_register()
        return jsonify(result), 200
    except Exception as e:
        logger.error("admin/learning/train failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Training failed"}), 500


@v2_bp.route("/admin/learning/status", methods=["GET"])
@require_admin_or_coach
def v2_admin_learning_status():
    """Corpus + latest-model snapshot. shadow agreement is wired in B3 (the
    shadow hook); null until predictions exist. SHADOW — influences nothing."""
    try:
        from services.learning_export import export_snippet_labels_dataset
        _rows, summary = export_snippet_labels_dataset()
        latest = db.get_latest_model_version()
        latest_out = None
        if latest:
            latest_out = {
                "version": latest.get("version"),
                "trained_at": latest.get("created_at"),
                "status": latest.get("status"),
                "metrics": latest.get("metrics"),
                "corpus_size": latest.get("corpus_size"),
            }
        total = summary.get("total") or 0
        recommendation = (
            "collect more labels (provisional)" if total < 50
            else "corpus sufficient — train when ready"
        )
        return jsonify({
            "corpus": {
                "total": total,
                "by_class": summary.get("by_class") or {},
                "dropped_no_features": summary.get("dropped_no_features") or 0,
            },
            "latest_model": latest_out,
            "shadow": db.get_shadow_agreement(),  # predicted-vs-coach agreement
            "recommendation": recommendation,
            "mode": "shadow — influences nothing",
        }), 200
    except Exception as e:
        logger.error("admin/learning/status failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch status"}), 500


@v2_bp.route("/admin/learning/models", methods=["GET"])
@require_admin_or_coach
def v2_admin_learning_models():
    """Model history, newest first."""
    try:
        rows = db.list_model_versions()
        return jsonify([
            {
                "version": r.get("version"),
                "trained_at": r.get("created_at"),
                "status": r.get("status"),
                "metrics": r.get("metrics"),
                "corpus_size": r.get("corpus_size"),
            }
            for r in rows
        ]), 200
    except Exception as e:
        logger.error("admin/learning/models failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch models"}), 500


@v2_bp.route("/admin/learning/trace", methods=["GET"])
@require_admin
def v2_admin_learning_trace():
    """Backlog item 11 — the developer learning-trace: one payload describing
    the three learning lanes (shadow direction / annotation writer / acoustic
    baseline): corpora, model history, coefficients, agreement, decision
    points, known gaps. Aggregation lives in services/learning_trace.py.

    ADMIN-ONLY on purpose (not @require_admin_or_coach like the other
    /admin/learning/* endpoints): the payload exposes machine guesses vs
    coach labels — BLIND COACH forbids a coach seeing that. Developer
    observability only; never any user/coach-visible score surface (AC-9).
    Sections degrade to null + errors[] individually — this never 500s for
    one broken corpus."""
    try:
        from services.learning_trace import build_learning_trace
        return jsonify(build_learning_trace()), 200
    except Exception as e:
        logger.error("admin/learning/trace failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to build learning trace"}), 500


@v2_bp.route("/admin/sessions/<session_id>/readout", methods=["GET"])
@require_admin
def v2_admin_get_session_readout(session_id):
    """② Coach authoring Readout — the user §3.3 Readout PLUS the PRIVATE
    direction-label lane per snippet (split-sink §2: the user re-read
    omits labels; the coach authors/corrects them here). Pseudonymized,
    not anonymized: full transcript + goal, identity as
    pseudonymous_user_id (never the real id).

    Response 200:
      { session_id, pseudonymous_user_id, state, session_context,
        readout: { snippets: [ {…§3.3…, label?: {schema_version, value,
                    was_pre_filled, was_overridden}} ], insights_payload? } }

    Cold start (no classifier): snippet.label absent → coach labels from
    scratch. Steady state: pre-filled value present → accept/override.
    """
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT", "error": "session_id must be a valid UUID",
        }), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({
                "code": "SESSION_NOT_FOUND", "error": "Session not found",
            }), 404

        from services.lab_recording import build_readout_from_session
        readout = build_readout_from_session(session_id)

        # Fold the PRIVATE direction-label lane per snippet (coach-only —
        # NEVER in the user re-read; this is the authoring half).
        labels_by_id = {}
        for lab in db.get_training_labels(session_id):
            sid = lab.get("snippet_id")
            if sid is not None:
                labels_by_id[str(sid)] = {
                    "schema_version": lab.get("schema_version"),
                    "value": lab.get("value"),
                    "was_pre_filled": lab.get("was_pre_filled"),
                    "was_overridden": lab.get("was_overridden"),
                }
        for snip in (readout.get("snippets") or []):
            lab = labels_by_id.get(str(snip.get("id")))
            if lab:
                snip["label"] = lab

        published = bool(session.get("results_published_at"))
        if published:
            state = "insights_ready"
        elif session.get("status") == "pending_admin_review":
            state = "review_pending"
        else:
            state = "readout_ready"

        ctx = session.get("intake_context")
        return jsonify({
            "session_id": session_id,
            "pseudonymous_user_id": _pseudonymous_user_id(session.get("user_id")),
            "state": state,
            "session_context": ctx if isinstance(ctx, dict) else {},
            "readout": readout,
        }), 200
    except Exception as e:
        logger.error(
            "admin/sessions/<id>/readout GET failed sid=%s err=%s",
            session_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to fetch coach readout",
        }), 500


@v2_bp.route("/session/status", methods=["GET"])
@require_auth
def v2_session_status():
    """willab session status — the FE's getStatus() seam (homeworkApi).

    GET → {credits, can_start_analysis, audit_paid, audit_price}. Identical
    payload to GET /v2/user/credits; this is the endpoint the FE's BFF proxies
    (/v2/session/status). can_start_analysis drives the Lounge credit/paywall
    gate; audit_paid drives locked affordances; audit_price shows the headline
    $50 on the pricing card.
    """
    try:
        return jsonify(_build_user_session_status(request.user_id)), 200
    except Exception as e:
        logger.error("session/status GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch status"}), 500


@v2_bp.route("/config/recording", methods=["GET"])
@optional_auth
def v2_config_recording():
    """willab recording config (UX Wave v2 D5 / B-3). Single source of truth
    for the recording floor so the FE stops hardcoding 60s. The SERVER is the
    real gate — min_content_gate rejects anything under this on upload (422,
    RECORDING_REJECTED); this just lets the FE preview the same numbers.

    `long_take_caution_sec` (founder 2026-07-27) is the CEILING side of the
    same idea, and is deliberately NOT a gate: at or above it the setup wizard
    shows a soft caution and the student proceeds anyway if they choose. It
    lives here so the FE never hardcodes the threshold it states in copy.
    """
    from services.min_content_gate import MIN_DURATION_SEC, MIN_VOICED_SEC
    return jsonify({
        "min_duration_sec": MIN_DURATION_SEC,
        "min_voiced_sec": MIN_VOICED_SEC,
        "long_take_caution_sec": int(getattr(
            config, "LONG_TAKE_CAUTION_SECONDS", 600) or 600),
    }), 200


@v2_bp.route("/explore/start", methods=["POST"])
@require_auth
def v2_explore_start():
    """Enter an explore session (willab Prompt A §6 C3 — BEAT 0 on-ramp).

    Mints the arc_id BEFORE take 1 and fires the framing cadence bubble
    (rendered in the user's language, goal-woven) so the FE never has to
    hardcode that copy (§7 language fence). The FE then POSTs the first
    /lab/recordings with this arc_id + take_index=1.

    Body (optional JSON): nothing required today; reserved for future
    spark/appetite hints.

    Response 200 { arc_id, take_index, take_count }.
    """
    try:
        from services.explore_arc import resolve_arc
        from services.session_cadence import fire_arc_start

        arc_id, take_index = resolve_arc(True, None, None)  # mint a fresh arc
        goal = (db.get_user_profile(request.user_id) or {}).get("goal")
        # Best-effort: the arc is valid even if the framing render fails.
        fire_arc_start(request.user_id, arc_id, goal=goal)
        return jsonify({
            "arc_id": arc_id,
            "take_index": take_index,
            "take_count": 0,
        }), 200
    except Exception as e:
        logger.error("explore/start failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to start explore session"}), 500


@v2_bp.route("/explore/arc/<arc_id>/moments", methods=["GET"])
@require_auth
def v2_explore_arc_moments(arc_id):
    """Cross-take selection payoff (willab Prompt A §5) — the arc's strongest
    material to study.

    The payload carries a `granularity` discriminator (§5.3) so the FE renders
    the matching surface:
      • "take" — each take's own strongest moments (§5.2; what ships today).
      • "line" — strongest delivery of EACH line (§5.1; behind the §5.0
        alignment gate, currently data-blocked / off).

    AC-9 (§7): score-FREE — text + audio + which take + a plain-language
    rationale; never a number, verdict, or trajectory.

    Ownership: the arc must contain a session owned by the caller, else 404
    (the arc_id is otherwise unattributable — explore takes are claimed to the
    user via the normal guest→signed claim flow).

    Response 200 { arc_id, granularity, take_count, takes:[...] }
             404 NOT_FOUND — no such arc for this user
             500 V2_ERROR
    """
    try:
        from services.cross_take_selection import select_cross_take
        sessions = db.get_arc_sessions(arc_id)
        owned = any(
            str(s.get("user_id")) == str(request.user_id) for s in sessions
        )
        if not owned:
            return jsonify({
                "code": "NOT_FOUND", "error": "arc not found",
            }), 404
        payload = select_cross_take(arc_id)
        return jsonify(payload), 200
    except Exception as e:
        logger.error("explore/arc moments failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load arc moments",
        }), 500


def _arc_owned_by_caller(arc_id):
    """True iff the arc has a session owned by request.user_id. Returns
    (owned, sessions) so callers reuse the read."""
    sessions = db.get_arc_sessions(arc_id)
    owned = any(
        str(s.get("user_id")) == str(request.user_id) for s in sessions
    )
    return owned, sessions


@v2_bp.route("/explore/arc/<arc_id>/best-presentation", methods=["GET"])
@require_auth
def v2_explore_arc_best_presentation(arc_id):
    """Best-Presentation (willab Prompt D) — REPLACES the audit. After the arc's
    3 takes, the user's strongest-rated delivery of each slide (challenge lifts
    the rating, threat lowers it), lightly stitched into 'ideal presentation'
    text, with coach-confirmed breakthrough markers.

    SCORE-FREE (AC-9). Ownership: the arc must contain a session owned by the
    caller, else 404. Not-ready (<3 takes) still returns 200 with populated
    slides + progress.takes_remaining — the FE drives its 'need 3 takes' notice
    off ready / takes_remaining (not off a 404 or an empty body).

    Founder 2026-07-06: 402 gates this endpoint (paid deliverable). PAST the
    gate, ``coach_finalized`` is a SEPARATE, harder gate on CONTENT — the raw
    auto-assembled draft is NEVER served to the student; every slide's `text`
    is "" until the coach has corrected EVERY slide (build_best_presentation
    handles this transparently), regardless of payment. The FE shows "still
    being prepared by your coach" when paid but not yet coach_finalized —
    distinct from the 402 paywall.

    Response 200 {
        arc_id, ready, coach_finalized, presentation_ref,
        progress: { takes_done, takes_target, takes_remaining, ready },
        slides: [ { index, title, body, text, audio_ref,
                    start_offset_ms, duration_ms, take_index,
                    breakthrough, breakthrough_note, coach_edited, edited } ]
    }
             404 NOT_FOUND · 500 V2_ERROR
    """
    try:
        from services.best_presentation import build_best_presentation
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Single-deliverable (founder 2026-07-17): the best presentation is
        # free — no paywall. (audit_paid stays true for FE back-compat.)
        return jsonify({
            "arc_id": arc_id, "audit_paid": True,
            **build_best_presentation(arc_id),
        }), 200
    except Exception as e:
        logger.error("explore/arc best-presentation failed arc=%s: %s", arc_id,
                     e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to build best presentation",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/breakthroughs", methods=["GET"])
@require_auth
def v2_explore_arc_breakthroughs(arc_id):
    """ALL coach-confirmed breakthrough moments in this arc, newest → oldest
    (founder #5 — the "explore my breakthrough moments" list behind the button
    below the best presentation). Same gate as the best-presentation badge (a
    threat→challenge turn on the coach's OWN labels, never a model guess), but
    every breakthrough snippet across all takes, not just the per-slide winner.

    SCORE-FREE (AC-9). Ownership: the arc must contain a session owned by the
    caller, else 404. An empty list (no coach-confirmed breakthroughs yet) is a
    200 with breakthroughs=[] — the FE shows an empty-state, not an error.

    Response 200 {
        arc_id, count,
        breakthroughs: [ { snippet_id, session_id, take_index, created_at,
                           slide_index, transcript, audio_ref,
                           start_offset_ms, duration_ms, note } ]
    }
             404 NOT_FOUND · 500 V2_ERROR
    """
    try:
        from services.best_presentation import build_arc_breakthroughs
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Single-deliverable (founder 2026-07-17): the breakthroughs list is
        # free — no paywall.
        return jsonify({"arc_id": arc_id, **build_arc_breakthroughs(arc_id)}), 200
    except Exception as e:
        logger.error("explore/arc breakthroughs failed arc=%s: %s", arc_id,
                     e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load breakthroughs",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/best-presentation/slides/<int:index>",
             methods=["PUT"])
@require_auth
def v2_explore_arc_edit_slide(arc_id, index):
    """Save the user's edited best-presentation text for one slide (Prompt D —
    the pencil). Overrides the composed text + sticks across recompositions.
    Ownership-checked.

    Rich formatting (backlog 1.7, founder 2026-07-11): the FE's ideal-text
    editor persists a tiny marker subset — **bold**, *italic*, __underline__,
    ==highlight== — INSIDE this same text field. The markers pass through as
    plain text (they degrade readably on every other surface); raw HTML tags
    are stripped server-side so markup can never round-trip into a renderer.

    Body: { "text": str }.  200 { ok, arc_id, index } · 400 · 404 · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        text = (body.get("text") or "").strip() if isinstance(body.get("text"), str) else ""
        # Strip HTML tags (keep the marker subset — it's plain text). Length
        # is checked AFTER stripping so tags can't smuggle past the cap.
        text = re.sub(r"<[^>]*>", "", text).strip()
        if not text:
            return jsonify({"code": "INVALID_INPUT", "error": "text is required"}), 400
        if len(text) > 2000:
            return jsonify({"code": "INVALID_INPUT", "error": "text too long"}), 400
        ok = db.upsert_best_presentation_edit(arc_id, index, text, request.user_id)
        if not ok:
            return jsonify({"code": "V2_ERROR", "error": "Could not save the edit"}), 500
        return jsonify({"ok": True, "arc_id": arc_id, "index": index}), 200
    except Exception as e:
        logger.error("explore/arc edit-slide failed arc=%s idx=%s: %s",
                     arc_id, index, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save edit"}), 500


@v2_bp.route("/explore/arc/<arc_id>/progress", methods=["GET"])
@optional_auth
def v2_explore_arc_progress(arc_id):
    """Cheap poll for the 'X takes to your ideal presentation' bar (Prompt D §5).

    coach_finalized (backlog 4.2, 2026-07-11): whether the coach has corrected
    EVERY slide of the ideal text — at 3/3 takes with coach_finalized=false the
    FE shows "Now we are waiting for the coach to assemble your speech!".
    Computed cheaply here (one edits read + the deck size from the sessions
    already loaded), mirroring services/best_presentation.py's definition —
    the ideal-text payload stays the authoritative gate.

    GUEST-capable since 2026-07-16 (the signed-out-first flow polls this from
    the instant readout — it was 401-ing): a FULLY-UNCLAIMED arc (every
    session user_id NULL) is readable to the bare arc id — the same
    capability-by-uuid rule as the guest readout; any claimed session in the
    arc → owner-only (404 to any other/no caller, no existence leak).

    Response 200 { arc_id, takes_done, takes_target, takes_remaining, ready,
                   coach_finalized }
             · 404 · 500
    """
    try:
        from services.best_presentation import presentation_progress
        sessions = db.get_arc_sessions(arc_id)
        if not sessions:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        _caller = getattr(request, "user_id", None)
        _owners = {str(s.get("user_id")) for s in sessions if s.get("user_id")}
        _owned = bool(_caller) and str(_caller) in _owners
        _guest_ok = not _owners  # fully-unclaimed arc → capability by uuid
        if not (_owned or _guest_ok):
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Canonical deck size = the most-complete deck across takes (same
        # rule as compose); deckless arcs (no deck) are never "finalized".
        _n_slides = 0
        for _s in sessions:
            _ctx = _s.get("intake_context") if isinstance(
                _s.get("intake_context"), dict) else {}
            _n_slides = max(_n_slides, len((_ctx or {}).get("slides") or []))
        _coach_finalized = False
        if _n_slides:
            _edits = db.get_coach_best_presentation_edits(arc_id) or {}
            _coach_finalized = all(
                isinstance(_edits.get(i), str) and _edits[i].strip()
                for i in range(_n_slides)
            )
        from services.best_presentation import spoken_arc_sessions
        return jsonify({
            # SPOKEN takes only (2026-07-15) — a read never inflates N/3.
            "arc_id": arc_id,
            **presentation_progress(len(spoken_arc_sessions(sessions))),
            "coach_finalized": _coach_finalized,
        }), 200
    except Exception as e:
        logger.error("explore/arc progress failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load progress",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/take-comparison", methods=["GET"])
@require_auth
def v2_explore_arc_take_comparison(arc_id):
    """Take-1-vs-take-2 comparison (Paid Audits A6) — the NEUTRAL teaser at the
    paywall. RAW acoustic aggregates (mean pitch, speech rate, pitch range,
    mean pause) for take 1 vs take 2 + a neutral pitch-range movement word
    (widened / narrowed / steadied).

    FREE on purpose — this is the unpaid teaser, so it is NOT behind the A2
    paywall (only ownership-gated). AC-9 / D8: no score, ratio, verdict word, or
    charisma vocabulary; raw values + neutral movement only.

    Response 200 { arc_id, take_count, takes:[...], comparison|null }
             404 NOT_FOUND · 500 V2_ERROR
    """
    try:
        from services.take_comparison import build_take_comparison
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        return jsonify(build_take_comparison(arc_id)), 200
    except Exception as e:
        logger.error("explore/arc take-comparison failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load take comparison",
        }), 500


@v2_bp.route("/arc/<arc_id>/checkout", methods=["POST"])
@require_auth
def v2_arc_checkout(arc_id):
    """Start Stripe Checkout for ONE audit = this arc (Paid Audits A3).

    Ownership-gated (the arc must be the caller's). Already-entitled arcs short-
    circuit (no duplicate charge). Body (optional): { success_url, cancel_url }.

    Response 200 { checkout_url, checkout_session_id, arc_id }
             200 { already_entitled: true, arc_id }   (purchase exists)
             404 NOT_FOUND · 4xx/5xx from Stripe/config
    """
    try:
        from services.arc_entitlement import is_arc_entitled
        from services.arc_checkout import create_arc_checkout_session
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        if is_arc_entitled(db, arc_id, request.user_id):
            return jsonify({"already_entitled": True, "arc_id": arc_id}), 200
        body = request.get_json(silent=True) or {}
        result = create_arc_checkout_session(
            str(arc_id), str(request.user_id), config,
            success_url=(body.get("success_url") or None),
            cancel_url=(body.get("cancel_url") or None),
        )
        return jsonify(result.payload), result.http_status
    except Exception as e:
        logger.error("arc checkout failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to start checkout",
        }), 500


@v2_bp.route("/arc/<arc_id>/redeem", methods=["POST"])
@require_auth
def v2_arc_redeem(arc_id):
    """Redeem a founding free-pass invite code for this arc (Paid Audits A4).

    Ownership-gated. Body: { code }. An active code with uses < max_uses mints a
    'founding_pass' purchase (source='invite_code') and burns one use.

    Response 200 { ok: true, arc_id, kind: 'founding_pass' }
             200 { already_entitled: true, arc_id }
             400 INVALID_INPUT (no code) · 404 NOT_FOUND (arc)
             409 CODE_INVALID (unknown / inactive / exhausted) · 500
    """
    try:
        from services.arc_entitlement import is_arc_entitled
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        if is_arc_entitled(db, arc_id, request.user_id):
            return jsonify({"already_entitled": True, "arc_id": arc_id}), 200
        body = request.get_json(silent=True) or {}
        code = (body.get("code") or "").strip() if isinstance(body.get("code"), str) else ""
        if not code:
            return jsonify({"code": "INVALID_INPUT", "error": "code is required"}), 400
        if not db.consume_arc_invite_code(code):
            return jsonify({
                "code": "CODE_INVALID",
                "error": "That code is not valid, inactive, or fully used.",
            }), 409
        purchase = db.create_arc_purchase(
            str(arc_id), str(request.user_id),
            kind="founding_pass", source="invite_code",
        )
        if not purchase:
            # The use was burned but the purchase failed — log loudly; the user
            # can retry with another code (rare; arc_purchases table missing).
            logger.error(
                "arc redeem: code consumed but purchase failed arc=%s code=%s",
                arc_id, code,
            )
            return jsonify({
                "code": "V2_ERROR", "error": "Could not record the pass",
            }), 500
        return jsonify({"ok": True, "arc_id": arc_id, "kind": "founding_pass"}), 200
    except Exception as e:
        logger.error("arc redeem failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to redeem code",
        }), 500


@v2_bp.route("/talks/<talk_id>/ideal-text", methods=["GET"])
@require_auth
def v2_talk_ideal_text(talk_id):
    """The Ideal-Text report for a talk (Paid Audits A7). A talk IS an arc, so
    talk_id == arc_id.

    Ownership-gated + paywall (the report is the paid deliverable). L1: the
    idealText is the verbatim-selected best take of each slide, never re-
    summarised — but it is a COACH correction now (founder 2026-07-06): the
    raw auto-assembled draft is NEVER served here. ``coachFinalized`` is a
    SEPARATE, harder gate on content past the 402 — every slide's idealText is
    "" until the coach has corrected EVERY slide, regardless of payment. The
    FE shows "still being prepared by your coach" when paid but not finalized.
    AC-9: no score/verdict.

    Response 200 { talkId, talkTitle, ready, coachReviewed, coachFinalized,
                   presentationRef,
                   slides:[ {index, label, title, body, thumbnailUrl,
                             idealText, takeRoute, breakthrough} ] }
             402 PAYMENT_REQUIRED · 404 NOT_FOUND · 500 V2_ERROR
    """
    try:
        from services.ideal_text_report import build_ideal_text_report
        owned, _ = _arc_owned_by_caller(talk_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "talk not found"}), 404
        # Past the gate → entitled (or admin/coach); echo audit_paid (Phase-1).
        return jsonify({
            "audit_paid": True, **build_ideal_text_report(talk_id),
        }), 200
    except Exception as e:
        logger.error("talk ideal-text failed talk=%s: %s", talk_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to build ideal text",
        }), 500


# ── willab — $25/25-credit arc unlock (founder re-price 2026-07-06) ─────

@v2_bp.route("/arc/<arc_id>/unlock", methods=["POST"])
@require_auth
def v2_arc_unlock(arc_id):
    """RETIRED (single-deliverable, founder 2026-07-17). The $25 arc unlock is
    gone; this route is a 410 tombstone (the ideal text + deliverables are free,
    the only paid item is the 5-credit key-moment explanations). 410 GONE."""
    # RETIRED (single-deliverable, founder 2026-07-17): the $25 arc unlock is
    # gone — the ideal text + its deliverables are free; the only paid item is
    # the 5-credit key-moment explanations (POST /arc/<id>/unlock-moments). Kept
    # as a 410 tombstone so any lingering client gets a clear signal.
    return jsonify({
        "code": "GONE",
        "error": "This product was retired. The ideal text is free; "
                 "key-moment explanations unlock for 5 credits.",
    }), 410


@v2_bp.route("/arc/<arc_id>/unlock-moments", methods=["POST"])
@require_auth
def v2_unlock_moments(arc_id):
    """THE one paid item under the single deliverable (founder re-shape
    2026-07-17): open the presentation's key-moment EXPLANATIONS (the coach's
    note/video per moment) — 5 credits, one-time per presentation, covering
    all current AND future moments. The ideal text itself is always free.
    ARC-KEYED path — the FE contract pin (their 748c33d).

    Same deduct-first atomic ordering as the retired arc unlock (deduct →
    exclusive insert → refund on conflict), against the SEPARATE
    moment_unlocks table (no grandfathering from arc_purchases).

    200 { unlocked: true, arc_id, credits_remaining }
    200 { already_entitled: true, arc_id }
    402 { code: INSUFFICIENT_CREDITS, required, current }
    404 · 409 (raced; refunded) · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "presentation not found"}), 404
        if _moments_entitled(arc_id):
            return jsonify({"already_entitled": True,
                            "arc_id": arc_id}), 200

        # Token pricing Phase 1: when the flag is on, key-moment explanations
        # cost TOKENS (2,500 = $0.25), not the legacy 5 credits ($5) — a 20×
        # cut the founder approved on 2026-07-27, because the explanations were
        # already generated during the take and cost us nothing to unlock.
        # Flag off ⇒ the legacy credits path below runs byte-for-byte unchanged.
        from services.token_account import enabled as _tokens_on
        if _tokens_on():
            from services.token_account import charge as _charge
            res = _charge(str(request.user_id), "moment_explanation",
                          ref_id=str(arc_id))
            if not res.ok:
                return jsonify({
                    "code": "INSUFFICIENT_TOKENS",
                    "required": res.charged or 2500,
                    "current": res.balance,
                    "reason": res.reason,
                }), 402
            unlock = db.insert_moment_unlock(str(arc_id),
                                             str(request.user_id), 0)
            if not unlock and not _moments_entitled(arc_id):
                return jsonify({"code": "V2_ERROR",
                                "error": "Could not start the unlock"}), 500
            return jsonify({"unlocked": True, "arc_id": arc_id,
                            "tokens_remaining": res.balance}), 200

        amount = int(getattr(config, "MOMENTS_UNLOCK_CREDITS", 5) or 5)

        new_balance = db.deduct_credits_strict(str(request.user_id), amount)
        if new_balance is None:
            details = db.v2_get_student_details(str(request.user_id)) or {}
            current = int(details.get("credits") or 0)
            return jsonify({
                "code": "INSUFFICIENT_CREDITS",
                "required": amount, "current": current,
            }), 402

        unlock = db.insert_moment_unlock(
            str(arc_id), str(request.user_id), amount)
        if not unlock:
            db.v2_increment_student_credits(str(request.user_id), amount)
            if _moments_entitled(arc_id):
                return jsonify({"code": "MOMENTS_ALREADY_UNLOCKED",
                                "arc_id": arc_id}), 409
            return jsonify({
                "code": "V2_ERROR", "error": "Could not start the unlock",
            }), 500

        return jsonify({
            "unlocked": True, "arc_id": arc_id,
            "credits_remaining": new_balance,
        }), 200
    except Exception as e:
        logger.error("unlock-moments failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to unlock"}), 500


@v2_bp.route("/explore/arc/<arc_id>/moments/<moment_id>", methods=["GET"])
@require_auth
def v2_get_moment_explanation(arc_id, moment_id):
    """ONE key moment's EXPLANATION (single deliverable, founder 2026-07-17;
    per-moment path = the FE contract pin, their 748c33d): the coach's note
    text and/or video + playback span for the tapped moment. Gated by the
    5-credit moments unlock; the 402 carries the price so the unlock prompt
    renders from this response alone. AC-9: qualitative content only — no
    scores, and the private direction label never serializes (it only
    selects, same rule as the feedback page).

    Response is FLAT (the FE reads top-level `note` + `video_ref`):
    200 { arc_id, id, note, video_ref, transcript, audio_ref,
          start_offset_ms, duration_ms, slide_index, recording_kind }
    402 { code: MOMENTS_LOCKED, price_credits } · 404 · 500
    """
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "presentation not found"}), 404
        if not _moments_entitled(arc_id):
            return jsonify({
                "code": "MOMENTS_LOCKED",
                "price_credits": int(getattr(
                    config, "MOMENTS_UNLOCK_CREDITS", 5) or 5),
            }), 402
        spoken, reads = _spoken_takes_and_reads(sessions)
        _want = str(moment_id)
        for s in spoken:
            sid = str(s.get("id"))
            read_rows = reads.get(sid) or []
            for m in _take_key_moments(
                    sid, [str(r.get("id")) for r in read_rows if r.get("id")]):
                if str(m.get("snippet_id")) != _want:
                    continue
                # FLAT top-level note/video_ref (the FE reads exactly these);
                # the playback fields ride along for the moment player.
                return jsonify({
                    "arc_id": arc_id,
                    "id": m.get("snippet_id"),
                    "note": (m.get("comment_text") or None),
                    "video_ref": (m.get("comment_video_ref") or None),
                    "take_session_id": m.get("take_session_id"),
                    "transcript": m.get("transcript"),
                    "audio_ref": m.get("audio_ref"),
                    "start_offset_ms": m.get("start_offset_ms"),
                    "duration_ms": m.get("duration_ms"),
                    "slide_index": m.get("slide_index"),
                    "recording_kind": m.get("recording_kind"),
                }), 200
        return jsonify({"code": "MOMENT_NOT_FOUND",
                        "error": "Not a key moment of this presentation"}), 404
    except Exception as e:
        logger.error("moment explanation failed arc=%s moment=%s: %s",
                     arc_id, moment_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to load the moment"}), 500


# (The #186 batch card + per-slide coach ideal-text editing lived here —
#  DELETED 2026-07-15 after the FE switched to /coach/arc/<id>/publish-analysis,
#  /explore/arc/<id>/feedback and the one-block ideal-text routes. History: PR #186/#193.)


# ── willab — delivery layer (founder 2026-07-15) ────────────────────────
#
# The post-core delivery: per-take FEEDBACK (full text + key moments), the
# one-block IDEAL TEXT (coach-approved, $25-gated), the coach Save/Publish
# flow, and the 4-bubble delivery (3 grey feedback + 1 purple ideal text).
# Supersedes the #186 single batch card (kept below, deprecated, until the
# FE switches) and the per-slide coach ideal-text editing (same deal).


def _moment_suggestions_enabled() -> bool:
    """Star suggestions on the SD ideal text (founder 2026-07-18): grey
    suggestion stars (emphasize / replace) resolved coach-label-first, else
    the deterministic potentiometer (NEVER the shadow model — blind coach);
    orange verified stars carry the coach message. DEFAULT OFF."""
    return (os.getenv("MOMENT_SUGGESTIONS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _instant_ideal_enabled() -> bool:
    """Instant ideal text (founder re-lock 2026-07-17): the MACHINE draft is
    served to the student FREE the moment take 3 lands — the June "the raw
    auto-assembled draft must NEVER reach the student" gate is explicitly
    reversed for this labeled instant lane. The coach-perfected text + takes
    2/3 feedback stay behind approval + the $25 unlock. DEFAULT OFF until the
    FE ships variant handling (deploy order: BE → FE → flip
    INSTANT_IDEAL_TEXT_ENABLED=1 in Railway)."""
    return (os.getenv("INSTANT_IDEAL_TEXT_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _take_full_text(session_id):
    """A take's feedback text: pieces in speech order, per piece the coach
    correction > the user's approved edit > the raw transcript (locked
    assumption A1). Plain text, no playback, no scores."""
    snips = db.get_snippets_by_session(session_id) or []
    corrections = {}
    for d in (db.get_coach_snippet_drafts(session_id) or []):
        _sid = str(d.get("snippet_id"))
        _tx = (d.get("transcript_corrected") or "").strip()
        if _sid and _tx:
            corrections[_sid] = _tx
    edits = {}
    try:
        for e in (db.get_user_transcript_edits(session_id) or []):
            if e.get("snippet_id") and (e.get("text") or "").strip():
                edits[str(e["snippet_id"])] = e["text"].strip()
    except Exception:
        pass
    parts = []
    for s in sorted(snips, key=lambda x: (x.get("start_offset_ms") or 0)):
        _sid = str(s.get("id"))
        txt = (corrections.get(_sid) or edits.get(_sid)
               or s.get("transcript") or s.get("transcription_text") or "")
        txt = txt.strip()
        if txt:
            parts.append(txt)
    return " ".join(parts)


def _take_key_moments(session_id, read_session_ids=None):
    """A take's key moments (locked assumption A2/A3): coach-SURFACED snippets
    marked 'challenge' OR 'threat' (founder 2026-07-16: the coach's video may
    ride a threat-labeled moment too — 'challenge' alone remains the
    breakthrough badge), from the spoken take AND ALL its paired mid-take
    re-reads. Each: playback span + the coach's comment (text and/or video) +
    recording_kind + slide_index. No scores (AC-9); the private direction
    label itself is never serialized — it only SELECTS."""
    _reads = read_session_ids or []
    if isinstance(_reads, str):
        _reads = [_reads]
    out = []
    for sid, kind_default in ([(session_id, "spoken")]
                              + [(r, "read") for r in _reads]):
        if not sid:
            continue
        labels = {
            str(r.get("snippet_id")): r.get("value")
            for r in (db.get_training_labels(sid) or [])
        }
        drafts = {
            str(d.get("snippet_id")): d
            for d in (db.get_coach_snippet_drafts(sid) or [])
            if d.get("snippet_id")
        }
        for s in sorted(db.get_snippets_by_session(sid) or [],
                        key=lambda x: (x.get("start_offset_ms") or 0)):
            _sid = str(s.get("id"))
            d = drafts.get(_sid)
            if not d or not d.get("surfaced"):
                continue
            if labels.get(_sid) not in ("challenge", "threat"):
                continue
            m = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
            _piece = m.get("piece") if isinstance(m.get("piece"), dict) else {}
            out.append({
                "snippet_id": s.get("id"),
                "take_session_id": sid,
                "slide_index": _piece.get("slide_index"),
                "recording_kind": m.get("recording_kind") or kind_default,
                "transcript": (
                    (d.get("transcript_corrected") or "").strip()
                    or s.get("transcript") or s.get("transcription_text") or ""
                ),
                "audio_ref": s.get("audio_segment_path"),
                "start_offset_ms": s.get("start_offset_ms"),
                "duration_ms": s.get("duration_ms"),
                "comment_text": (d.get("note") or "").strip() or None,
                "comment_video_ref": d.get("breakthrough_video_ref"),
            })
    return out


def _moments_entitled(arc_id) -> bool:
    """Single deliverable: is the presentation's key-moment unlock owned?
    Reads ONLY moment_unlocks — the retired $25 arc_purchases never grants
    this (founder-explicit: no grandfathering)."""
    try:
        return bool(db.get_moment_unlock(arc_id))
    except Exception:
        return False


def _moment_explanations_map(session_ids) -> dict:
    """snippet_id → {"has_video": bool} for every coach EXPLANATION (a
    surfaced draft carrying a note and/or video). Key presence = an
    explanation exists (the ORANGE verified star); has_video drives the
    blurred-video affordance. Batch per session; best-effort."""
    out: dict = {}
    for sid in {str(s) for s in (session_ids or []) if s}:
        try:
            for d in (db.get_coach_snippet_drafts(sid) or []):
                _snip = d.get("snippet_id")
                if _snip is None or not d.get("surfaced"):
                    continue
                if (d.get("note") or "").strip() \
                        or d.get("breakthrough_video_ref"):
                    out[str(_snip)] = {
                        "has_video": bool(d.get("breakthrough_video_ref")),
                        # Ticket 6: a blog post the coach attached by hand.
                        # Carried as the raw slug here; resolved to
                        # {slug,title,url} by _moment_reference (which drops it
                        # when the post is a draft or gone).
                        "reference_post_slug": (
                            d.get("reference_post_slug") or None),
                    }
        except Exception:
            continue
    return out


def _moment_reference_map(slugs):
    """{slug: {slug,title,url}} for the DISTINCT slugs on this arc's moments.

    Batched deliberately. The obvious implementation resolves inside the
    per-moment decorator, which is an N+1: a talk with ten verified moments
    would issue ten post lookups on every ideal-text GET — the exact shape the
    load-time ticket is about. Distinct slugs on one arc are typically 0–2, so
    one lookup each is effectively constant.
    """
    out: dict = {}
    for slug in {s for s in (slugs or []) if isinstance(s, str) and s.strip()}:
        ref = _moment_reference(slug)
        if ref:
            out[slug.strip()] = ref
    return out


def _moment_reference(slug):
    """{slug, title, url} for a coach-attached blog post, or None.

    Resolved at READ time, never stored as a URL: the public path is moving
    (/journal -> /blog) and the title can be edited, so resolving late keeps
    both correct. Returns None — i.e. the FE renders nothing — when the slug is
    empty, the post was unpublished, or it was deleted. Serving a dead link to a
    student is worse than serving no link.

    `published_only=True` is the load-bearing argument: it reuses the Journal's
    own draft-invisibility rule, so an in-progress post the coach attached early
    cannot leak.
    """
    slug = (slug or "").strip() if isinstance(slug, str) else ""
    if not slug:
        return None
    try:
        row = db.get_journal_post_by_slug(slug, published_only=True)
    except Exception as e:
        logger.warning("moment reference lookup failed slug=%s: %s", slug, e)
        return None
    if not isinstance(row, dict) or not row.get("slug"):
        return None
    return {
        "slug": row.get("slug"),
        "title": row.get("title") or "",
        "url": f"/blog/{row.get('slug')}",
    }


def _moment_playback_map(session_ids) -> dict:
    """snippet_id → {snippet_audio_ref, start_offset_ms, duration_ms} for
    FREE in-modal playback of the student's own recording (audit
    2026-07-18: the star sheet plays the snippet above the paywall, so this
    can NEVER come from the paid moments GET).

    Parent+offset model: the ref is usually the WHOLE take's audio, so the
    offsets ride along and the FE must clamp to [start, start+duration].
    Uses the shared column-resolver so post-finalize rows (audio_segment_
    path NULL) still play. Batched per session; best-effort → no player."""
    out: dict = {}
    for sid in {str(s) for s in (session_ids or []) if s}:
        try:
            for s in (db.get_snippets_by_session(sid) or []):
                _snip = s.get("id")
                if _snip is None:
                    continue
                try:
                    _url = _resolve_snippet_audio_url(s)
                except Exception:
                    _url = s.get("audio_segment_path")
                if not _url:
                    continue
                out[str(_snip)] = {
                    "snippet_audio_ref": _url,
                    "start_offset_ms": s.get("start_offset_ms"),
                    "duration_ms": s.get("duration_ms"),
                }
        except Exception:
            continue
    return out


def _moment_applied_map(session_ids) -> dict:
    """snippet_id → True when the LAST moment_* suggestion action was
    'applied' (Approve is reversible; last action wins). Best-effort."""
    out: dict = {}
    for sid in {str(s) for s in (session_ids or []) if s}:
        try:
            rows = db.get_suggestion_feedback_by_session(sid) or []
        except Exception:
            continue
        for r in rows:   # rows assumed chronological; last write wins
            if r.get("target") not in ("moment_emphasize", "moment_replace",
                                       "document_replace", "document_bold"):
                continue
            _snip = r.get("snippet_id")
            if _snip is None:
                continue
            out[str(_snip)] = (r.get("action") == "applied")
    return {k: v for k, v in out.items() if v}


def _fold_applied_moments(text, moments) -> str:
    """Serve-time fold of APPLIED star suggestions into the displayed text
    (founder sign-off 2026-07-18 — the canonical ideal text is NEVER
    mutated; this rewrites the response string only):
      * emphasize → the moment's inner span wraps in {{orange:…}}
        ("these words hold particular value");
      * replace   → the inner span is swapped for the generated replacement
        (not bold, not orange — just replaced).
    The [[moment:…]] anchor survives (revert stays addressable). Pure."""
    from services.ideal_text_block import accent_span
    if not isinstance(text, str) or not text:
        return text
    for m in moments or []:
        if not m.get("applied"):
            continue
        sug = m.get("suggestion") or {}
        _id, _sid = m.get("id"), m.get("take_session_id")
        if not _id or not _sid:
            continue
        _pat = re.compile(
            r"\[\[moment:" + re.escape(str(_id)) + r"\|"
            + re.escape(str(_sid)) + r"\]\](?P<inner>.*?)\[\[/moment\]\]",
            re.DOTALL,
        )
        if sug.get("kind") == "replace" and (sug.get("replacement") or "").strip():
            _new = sug["replacement"].strip()
            text = _pat.sub(
                lambda mt: f"[[moment:{_id}|{_sid}]]{_new}[[/moment]]",
                text, count=1)
        elif sug.get("kind") == "emphasize":
            text = _pat.sub(
                # SINGLE marker, never nested (audit 2026-07-18): the FE's
                # rich-marker parser is FLAT — a nested `**{{orange:…}}**`
                # printed its raw syntax to the student. The accent marker
                # alone carries "these words hold particular value". A span
                # already carrying the marker (BAKED by the decision ledger,
                # 2026-07-20) folds to itself — never double-wrapped.
                # accent_span, never an f-string wrap (2026-07-27): a
                # moment's inner span can run across a paragraph break,
                # and a marker that straddles a newline printed a bare
                # `{{orange:` line into the student's text.
                lambda mt: (
                    mt.group(0) if "{{orange:" in mt.group("inner")
                    else (f"[[moment:{_id}|{_sid}]]"
                          f"{accent_span(mt.group('inner'))}[[/moment]]")),
                text, count=1)
    return text


@v2_bp.route("/explore/arc/<arc_id>/feedback", methods=["GET"])
@require_auth
def v2_explore_arc_feedback(arc_id):
    """The per-take FEEDBACK the user opens from the grey bubbles (founder
    2026-07-15): the take's full text all together (NO playback) + the KEY
    MOMENTS (grouped by slide on the FE), each with its snippet playback and
    the coach's comment (text or video). No suggestions, no scores.

    Single-deliverable (founder 2026-07-17): every take's feedback is FREE —
    the $25 arc unlock is retired, so no take is locked. Reads fold into
    their paired take.

    Response 200 { arc_id, takes:[{take_index, session_id, free,
        locked?, full_text?, key_moments?:[…]}], ideal_ready, paywall? }
    404 · 500
    """
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Single-deliverable (founder 2026-07-17): every take's feedback is
        # FREE — the $25 arc unlock is retired, so nothing here is gated.
        spoken, reads = _spoken_takes_and_reads(sessions)
        takes = []
        for s in spoken:
            sid = str(s.get("id"))
            ti = s.get("take_index") or (len(takes) + 1)
            read_rows = reads.get(sid) or []
            takes.append({
                "take_index": ti, "session_id": sid,
                "free": (ti == 1), "locked": False,
                "full_text": _take_full_text(sid),
                "key_moments": _take_key_moments(
                    sid, [str(r.get("id")) for r in read_rows if r.get("id")]),
            })
        ideal = db.get_coach_arc_ideal_text(arc_id)
        if takes:
            # Once per arc, and only when there is feedback to read. Fail-open
            # by construction — the charge result is not consulted.
            _charge_arc_deliverable(request.user_id, "insights", arc_id)
        return jsonify({
            "arc_id": arc_id,
            "takes": takes,
            "ideal_ready": bool(ideal and ideal.get("approved_at")),
        }), 200
    except Exception as e:
        logger.error("explore/arc feedback failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load feedback",
        }), 500


def _ideal_piece_provenance(arc_id):
    """The machine assembly's per-piece slide identity, in served order —
    mirrors maybe_assemble_ideal_text's source choice WITHOUT re-running
    any composition on the student GET:

      * master flag: the skeleton blocks own the cutter's slide_index;
      * living transcript: the take's pieces, slide from the cutter's
        metrics.piece.slide_index bucket;
      * legacy: the persisted best-presentation compose cache — the very
        picks auto_text's paragraphs were joined from. No cache row →
        no attachment; the composer (its LLM pass included) NEVER runs
        on this GET.

    Each entry: {slide_index, snippet_id, take_session_id, take_index,
    status, challenger}. Best-effort; [] when nothing is provable."""
    from services.ideal_text_block import (
        _living_transcript_enabled, _polish_as_suggestions_enabled,
    )
    from services.master_document import master_document_enabled

    def _snip_slide(snip):
        # The cutter's own bucket (the slide on screen when the words
        # were spoken) — same read master_document keys its skeleton on.
        m = (snip or {}).get("metrics")
        piece = m.get("piece") if isinstance(m, dict) else None
        si = piece.get("slide_index") if isinstance(piece, dict) else None
        return si if isinstance(si, int) and not isinstance(si, bool) \
            else None

    if _living_transcript_enabled() and master_document_enabled():
        rows = sorted(
            (r for r in (db.list_ideal_text_blocks(str(arc_id)) or [])
             if r.get("active", True) and r.get("status") != "candidate"),
            key=lambda r: r.get("block_key") or 0)
        if rows:
            out = []
            for r in rows:
                inc = r.get("incumbent_pieces") or []
                out.append({
                    "slide_index": r.get("slide_index"),
                    # The KEYED pill→picker join (FE picker handoff
                    # 2026-08-03): the FE deep-links a paragraph's pill
                    # into the variants sheet by block_key — never by
                    # index-zipping two lists that merely happen to be
                    # sorted the same way.
                    "block_key": r.get("block_key"),
                    "snippet_id": (inc[0].get("snippet_id")
                                   if inc else None),
                    "take_session_id": r.get("incumbent_take_session_id"),
                    "take_index": r.get("incumbent_take_index"),
                    "status": r.get("status") or "settled",
                    "challenger": r.get("challenger_take_index"),
                })
            return out
        # No skeleton yet → the living-transcript document, exactly the
        # fallback the assembly itself makes.
    if _living_transcript_enabled():
        from services.transcript_document import build_transcript_document
        doc = build_transcript_document(arc_id, database=db)
        pieces = (doc or {}).get("pieces") or []
        if not pieces:
            return []
        sid = doc.get("take_session_id")
        snips = {str(s.get("id")): s
                 for s in (db.get_snippets_by_session(sid) or [])} \
            if sid else {}
        return [{
            "slide_index": _snip_slide(snips.get(str(p.get("snippet_id")))),
            "snippet_id": p.get("snippet_id"),
            "take_session_id": p.get("take_session_id"),
            "take_index": p.get("take_index"),
            "status": "settled",
            "challenger": None,
        } for p in pieces]
    _get_cache = getattr(db, "get_best_presentation_cache", None)
    cached = _get_cache(arc_id) if callable(_get_cache) else None
    slides = ((cached or {}).get("payload") or {}).get("slides") or []
    _polish_on = _polish_as_suggestions_enabled()
    out = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        _edited = (s.get("text") or "").strip()
        _verbatim = (s.get("verbatim") or "").strip()
        # Mirror assemble_ideal_text_block's paragraph filter exactly —
        # a pick it skipped must not shift the alignment here.
        if not ((_verbatim if _polish_on else _edited) or _edited):
            continue
        out.append({
            "slide_index": s.get("index"),
            "snippet_id": s.get("snippet_id"),
            "take_session_id": s.get("session_id"),
            "take_index": s.get("take_index"),
            "status": "settled",
            "challenger": None,
        })
    return out


def _ideal_text_pieces(arc_id, served_text, presentation_ref):
    """The slide-linkage `pieces[]` of the SD student GET (FE handoff
    2026-08-03, FE PR #222): one entry per "\\n\\n"-paragraph of the
    SERVED text, each carrying the deck page its words were bucketed to.

    `slide_index` attaches ONLY when the mapping is structural — the
    machine assembly's piece list lines up 1:1 with the served
    paragraphs (the FE's own provability bar: it zips or hides on
    anything weaker). A reshaped text (user rewrite, coach restructure,
    stale cache) misaligns the counts and every slide_index degrades to
    null — the FE falls back to its exact-count zip, never a guessed
    attachment. A deckless arc (no presentation_ref) never attaches:
    the deckless compose keys picks by SECTION index, which is not a
    deck page. Provenance only, no scores (AC-9). Best-effort; []."""
    try:
        paragraphs = [p.strip() for p in (served_text or "").split("\n\n")
                      if p.strip()]
        if not paragraphs:
            return []
        prov = _ideal_piece_provenance(arc_id) if presentation_ref else []
        aligned = bool(prov) and len(prov) == len(paragraphs)
        out = []
        for i, para in enumerate(paragraphs):
            src = prov[i] if aligned else {}
            si = src.get("slide_index")
            if isinstance(si, bool) or not isinstance(si, int) or si < 0:
                si = None
            _snip = src.get("snippet_id")
            _sess = src.get("take_session_id")
            _bk = src.get("block_key")
            out.append({
                "piece_key": i,
                "text": para,
                "slide_index": si,
                "block_key": (_bk if isinstance(_bk, int)
                              and not isinstance(_bk, bool) else None),
                "snippet_id": str(_snip) if _snip else None,
                "take_session_id": str(_sess) if _sess else None,
                "take_index": src.get("take_index"),
                "status": src.get("status") or "settled",
                "challenger": src.get("challenger"),
            })
        return out
    except Exception as e:
        logger.warning("ideal-text pieces failed arc=%s: %s", arc_id, e)
        return []


@v2_bp.route("/explore/arc/<arc_id>/ideal-text", methods=["GET"])
@require_auth
def v2_explore_get_ideal_text(arc_id):
    """The user's ideal-text notebook (the purple bubble).

    Single-deliverable (founder 2026-07-17): the ideal text is FREE in both
    states — never a 402. Returns
    200 { arc_id, version, status:"verified"|"unverified", title,
          updated_at, latest_take_session_id, take_count, reread_done,
          reread_processing, can_record_take, text, user_edited,
          prior_edit?, key_moments, moments_unlocked,
          explanations_available, price_credits,
          notes_text } — free in both states, never 402s. The
    crucial-bubble fields (founder 2026-07-20): `title` = latest take's
    topic, `latest_take_session_id` = the re-read pairing target.
    `take_count` (founder 2026-07-23) = the project's official-take count
    (per-arc, reads excluded); the FE renders the document badge as
    "<take_count>.0" — it climbs on every recorded take, distinct from
    `version` (which bumps only on a text change). The
    two-state mic reads THREE states: `reread_done` (a FINISHED re-read
    of the current version exists → next-take button), `reread_processing`
    (a re-read exists but is still transcribing → the FE holds a loading
    state in the button's place), else neither (→ the re-read mic).
    `can_record_take` (founder 2026-07-24, T1 · 1.2) is the SEPARATE,
    re-read-independent signal for the "record another take" button: true
    the moment the project has a spoken take, so a finished recording
    returns the student straight to this screen ready to record again —
    no loading gate, no forced re-read first. The re-read three-state mic
    above is unchanged (its 2026-07-22 loading gate stays intact);
    `can_record_take` only stops the NEXT take from waiting on it.
    `explanations_available`
    gates the unlock CTA (true only when a coach explanation exists);
    text-suggestion stars carry `quote` (the narrow underline span, or
    null = icon only).

    ?version=N (SD mode, founder 2026-07-20): the HISTORICAL read-only
    view of an old version — 200 { arc_id, version, historical:true,
    status:"superseded", current_version, created_at, text, key_moments }
    from the per-version snapshot; N == current serves the live notebook;
    no snapshot → 200 { historical_unavailable:true, requested_version,
    current_version } (the FE falls back to the live view).
    """
    try:
        owned, _sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        row = db.get_coach_arc_ideal_text(arc_id)

        # ── SINGLE DELIVERABLE (founder re-shape 2026-07-17): the ideal
        # text is FREE in both states — no 402 on this endpoint, ever. The
        # only paid thing in the app is the key-moment EXPLANATIONS
        # (GET /presentation/<id>/moments, 5 credits). ──
        _r = row or {}
        _coach_owned = bool(_r.get("updated_by") or _r.get("approved_at"))
        _machine = ((_r.get("auto_text") or "").strip()
                    or ((_r.get("text") or "").strip()
                        if not _coach_owned else ""))
        _version = _r.get("version") or (1 if _machine else None)

        # ── HISTORICAL view, ?version=N (founder 2026-07-20): an old
        # version bubble opens ITS OWN step — the frozen text + that
        # step's reasoning, read-only. N == current falls through to
        # the live notebook. No snapshot (pre-migration / assembled
        # before history existed) → historical_unavailable and the FE
        # falls back to the live view. Free, owner-only (same gate as
        # the live read). ──
        _hv_raw = request.args.get("version")
        if _hv_raw not in (None, ""):
            try:
                _hv = int(_hv_raw)
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "version must be an integer",
                }), 400
            if _version is None or _hv != _version:
                _snap = db.get_ideal_text_version(arc_id, _hv)
                if not _snap or not (_snap.get("text") or "").strip():
                    return jsonify({
                        "arc_id": arc_id,
                        "historical_unavailable": True,
                        "requested_version": _hv,
                        "current_version": _version,
                    }), 200
                from services.ideal_text_block import (
                    extract_key_moments, sanitize_markers,
                    strip_moment_markers,
                )
                _s_text = _snap["text"]
                _s_moments = extract_key_moments(_s_text)
                _s_sugs = {
                    str(m.get("snippet_id")): m
                    for m in (_snap.get("moments") or [])
                    if isinstance(m, dict) and m.get("snippet_id")
                }
                # The star is EXPLICIT on historical payloads too (FE
                # relay 2026-07-20): the device guard is BE-owned
                # contract logic (#218/#219 pin — the FE renders copy
                # purely from device and must never infer star
                # semantics). Same rule as live: an unknown kind or
                # device yields NO star and NO suggestion.
                from services.delivery_stars import (
                    DELIVERY_DEVICES as _H_DELIVERY,
                )
                from services.moment_suggestions import (
                    _STRUCT_DEVICES as _H_STRUCT,
                )
                _s_out = []
                for m in _s_moments:
                    _e = {
                        "id": m.get("snippet_id"),
                        "snippet_id": m.get("snippet_id"),
                        "anchor": m.get("anchor") or "",
                        "take_session_id": m.get("take_session_id"),
                    }
                    _sm = _s_sugs.get(str(m.get("snippet_id")))
                    if _sm:
                        _kind = _sm.get("kind")
                        _dev = _sm.get("device")
                        _star_ok = (
                            _kind in ("emphasize", "replace")
                            or (_kind == "structure"
                                and _dev in _H_STRUCT)
                            or (_kind == "delivery"
                                and _dev in _H_DELIVERY)
                        )
                        if _star_ok:
                            _e["star"] = "suggestion"
                            _e["suggestion"] = {
                                k: _sm.get(k)
                                for k in ("kind", "device", "quote",
                                          "replacement", "why",
                                          "trigger")
                                if k in _sm
                            }
                    _s_out.append(_e)
                return jsonify({
                    "arc_id": arc_id,
                    "version": _hv,
                    "historical": True,
                    "status": "superseded",
                    "current_version": _version,
                    "created_at": _snap.get("created_at"),
                    # A snapshot was baked before wrap_accent existed, so
                    # an old version can still carry a newline-straddling
                    # accent — sanitize on the way out too.
                    "text": sanitize_markers(strip_moment_markers(_s_text)),
                    "key_moments": _s_out,
                }), 200
        _vv = _r.get("verified_version")
        _vtext = (_r.get("verified_text") or "").strip()
        _verified = bool(_version is not None
                         and _vv == _version and _vtext)
        _base_text = _vtext if _verified else _machine
        # The student's in-place edit WINS display while it was made
        # against the CURRENT version (BE-2). A new take supersedes it —
        # the edit is retained (coach signal) but the fresh machine text
        # shows. `status` still reflects the coach's verification of the
        # version, independent of the student's own tweaks on top.
        _edit = db.get_user_ideal_edit(arc_id, request.user_id)
        _user_edited = bool(
            _edit and _version is not None
            and _edit.get("version") == _version
            and (_edit.get("text") or "").strip())
        _text = _edit["text"] if _user_edited else _base_text
        # ── SUPERSEDED-EDIT RE-OFFER (founder 2026-07-28): when a newer
        # version has superseded the student's edit, serve the retained
        # copy as `prior_edit` so the FE can offer one-click "re-apply
        # your additions" across reload / device switch. The lane
        # semantics are UNCHANGED (the versioning change stays parked:
        # additions/moves never bake forward) — this only exposes the
        # already-retained row to its owner. Best-effort: absent on any
        # hiccup, never breaks the GET. Owner-keyed by the read above.
        _prior_edit = None
        try:
            if not _user_edited and _edit and _version is not None:
                _pe_text = (_edit.get("text") or "").strip()
                _pe_ver = _edit.get("version")
                if _pe_text and isinstance(_pe_ver, int) \
                        and not isinstance(_pe_ver, bool) \
                        and _pe_ver != _version:
                    _prior_edit = {"text": _pe_text, "version": _pe_ver}
        except Exception:
            _prior_edit = None
        from services.ideal_text_block import extract_key_moments

        # ── Star suggestions (2026-07-18, flag-gated). Fold APPLIED
        # suggestions into the DISPLAYED text FIRST (unless the user's
        # free-form edit won — that wins wholesale), then extract the
        # anchors from the folded text so they always match what's
        # served. The canonical row is never touched (L1). ──
        _stars_on = _moment_suggestions_enabled()
        _sugs = db.get_moment_suggestions_by_arc(arc_id) \
            if _stars_on else {}
        # The ONLY two structural devices the FE has copy for — an
        # unknown spelling must yield no star (FE contract pin).
        from services.moment_suggestions import _STRUCT_DEVICES
        from services.delivery_stars import (
            DELIVERY_DEVICES as _DELIVERY_DEVICES,
        )
        _applied = {}
        if _stars_on and _sugs:
            _pre = extract_key_moments(_text)
            _applied = _moment_applied_map(
                [m.get("take_session_id") for m in _pre])
            if not _user_edited and _applied:
                _fold_info = []
                for m in _pre:
                    _mid = str(m.get("snippet_id"))
                    if _mid in _sugs and _applied.get(_mid):
                        _s = _sugs[_mid]
                        _fold_info.append({
                            "id": m.get("snippet_id"),
                            "take_session_id": m.get("take_session_id"),
                            "applied": True,
                            "suggestion": {
                                "kind": _s.get("kind"),
                                "replacement": _s.get("replacement_text"),
                            },
                        })
                _text = _fold_applied_moments(_text, _fold_info)

        # Marker hygiene BEFORE the anchors are read (founder 2026-07-27):
        # a newline-straddling `{{orange:` is re-wrapped per line and any
        # unmatched token loses its braces, keeping every word. It runs
        # here — not at the jsonify — so `key_moments[].anchor` and the
        # tracked-change / key-point offsets below are all measured against
        # the very string the student is served.
        from services.ideal_text_block import sanitize_markers
        _text = sanitize_markers(_text)

        _moments = extract_key_moments(_text)
        # Serve the ANCHOR path, never both (audit 2026-07-18): the FE
        # drops any anchor sitting inside a marker token, which is
        # exactly where the [[moment:…]] wrapper puts it — with the
        # wrappers present every star is lost AND a free suggestion
        # falls through to the paid affordance. Extract first, then
        # strip, so each anchor is plain text in the served string.
        from services.ideal_text_block import strip_moment_markers
        _text = strip_moment_markers(_text)
        _has_expl = _moment_explanations_map(
            [m.get("take_session_id") for m in _moments])
        _playback = _moment_playback_map(
            [m.get("take_session_id") for m in _moments])
        # Ticket 6: resolve every attached post ONCE per request, not once per
        # moment (see _moment_reference_map — the per-moment form is an N+1).
        # isinstance-guarded: this map's values are dicts in production, but
        # callers (and tests) legitimately hand back a truthy marker instead,
        # and a bare .get() there is an AttributeError that takes the whole
        # ideal-text response down with it.
        _refs = _moment_reference_map([
            v.get("reference_post_slug") if isinstance(v, dict) else None
            for v in _has_expl.values()
        ])

        def _decorate(m):
            _mid = str(m.get("snippet_id"))
            entry = {
                "id": m.get("snippet_id"),
                # Both keys on purpose: `id` is the moment-explanation
                # identity, `snippet_id` is what the Approve/Revert
                # feedback POST keys on (audit 2026-07-18 — its absence
                # sent an EMPTY snippet id and Approve never persisted).
                "snippet_id": m.get("snippet_id"),
                # The literal text fragment the FE underlines + taps
                # (SD contract pin — a moment with no anchor is dropped).
                "anchor": m.get("anchor") or "",
                "take_session_id": m.get("take_session_id"),
                "has_explanation": bool(_has_expl.get(_mid)),
                # FREE playback of the student's own recording (parent+
                # offset → the FE clamps to [start, start+duration]).
                **(_playback.get(_mid) or {}),
            }
            if not _stars_on:
                return entry
            if _has_expl.get(_mid):
                # Coach override wins: the ORANGE verified star —
                # permanent, re-openable; message content stays behind
                # the paid moments GET.
                entry["star"] = "verified"
                entry["coach"] = {
                    "has_message": True,
                    "has_video": bool(
                        _has_expl[_mid].get("has_video")),
                }
                # Ticket 6: further reading the coach attached to THIS moment.
                # Key omitted entirely when there is none, or when the post is
                # no longer published — the FE renders the link only when the
                # key is present. Not gated behind the paid moments GET: a
                # public blog link is not the coach's message.
                _expl = _has_expl[_mid]
                _slug = _expl.get("reference_post_slug") if isinstance(_expl, dict) else None
                _ref = _refs.get(_slug.strip()) if isinstance(_slug, str) else None
                if _ref:
                    entry["coach"]["reference"] = _ref
            elif _mid in _sugs and _sugs[_mid].get("kind") == "delivery" \
                    and _sugs[_mid].get("trigger") in _DELIVERY_DEVICES:
                # MEASURED delivery star (founder decisions 2026-07-18):
                # a behavioural prompt, not an edit — no approve/fold;
                # the modal's action is the FE's snippet re-record mic.
                # The FE renders the approved copy PURELY from `device`
                # (same pinned dependency as structural: unknown device
                # → no star), and nothing numeric rides this payload
                # (AC-9: the z-scores stay server-side).
                entry["star"] = "suggestion"
                entry["suggestion"] = {
                    "kind": "delivery",
                    "device": _sugs[_mid].get("trigger"),
                    "quote": None,
                    "why": None,
                }
            elif _mid in _sugs and _sugs[_mid].get("kind") == "structure" \
                    and _sugs[_mid].get("trigger") in _STRUCT_DEVICES:
                # STRUCTURAL star (founder 2026-07-18): a delivery
                # prompt, not an edit — never applied, never folded,
                # always shown. The FE renders fixed signed-off copy
                # from `device`; NO generated prose is served. `quote`
                # is the user's own verbatim words.
                # The device guard is the FE's pinned dependency: it
                # renders the sheet copy PURELY from `device`, so an
                # unknown spelling must yield NO star rather than a
                # star with no copy behind it.
                _s = _sugs[_mid]
                entry["star"] = "suggestion"
                entry["suggestion"] = {
                    "kind": "structure",
                    "device": _s.get("trigger"),
                    "quote": _s.get("why"),
                    "why": None,
                }
            elif _mid in _sugs \
                    and _sugs[_mid].get("kind") not in (
                        "structure", "delivery") \
                    and not _applied.get(_mid):
                # TEXT suggestions only — a structure/delivery row with
                # an unknown device must yield NO star (the FE renders
                # copy purely from device), never fall through here.
                # An APPLIED suggestion is CONSUMED: its result is
                # already folded into the served text, so no star is
                # emitted (audit 2026-07-18 — the FE documents exactly
                # this expectation; keeping the star re-offered work
                # the student had already accepted).
                _s = _sugs[_mid]
                # Quote narrowing (founder 2026-07-20): underline the
                # PHRASE, not the piece. Deterministic per trigger —
                # polish → the trimmed verbatim-vs-polished diff span;
                # a profanity replace → the carrying sentence; anything
                # else → None = star icon only, NO underline (the FE
                # contract). Guarded: a quote must be an exact
                # substring of the anchor (and so of the served text)
                # or it is dropped (the #219 lesson).
                _anchor_txt = m.get("anchor") or ""
                _quote = None
                try:
                    from services.suggestion_quotes import (
                        diff_quote, profanity_sentence,
                    )
                    from services.text_flags import has_profanity
                    if _s.get("trigger") == "polish":
                        _quote = diff_quote(
                            _anchor_txt, _s.get("replacement_text"))
                    elif _s.get("kind") == "replace" \
                            and has_profanity(_anchor_txt):
                        _quote = profanity_sentence(_anchor_txt)
                except Exception:
                    _quote = None
                if _quote and _quote not in _anchor_txt:
                    _quote = None
                entry["star"] = "suggestion"
                entry["suggestion"] = {
                    "kind": _s.get("kind"),
                    "quote": _quote,
                    "replacement": _s.get("replacement_text"),
                    "why": _s.get("why"),
                    # CLAMPED to 'polish'|None (adversarial review
                    # 2026-07-18): the FE only needs to distinguish a
                    # flow-polish replace from the rest; the raw trigger
                    # vocabulary (threat/charisma/…) is INTERNAL —
                    # surfacing it would breach the CONSTRUCT/AC-9
                    # fences (a classifier verdict on a user payload).
                    "trigger": ("polish" if _s.get("trigger") == "polish"
                                else None),
                }
                entry["applied"] = False
            return entry

        _notes = db.get_user_arc_ideal_notes(arc_id, request.user_id)

        # ── Crucial-bubble fields (founder 2026-07-20): title, last
        # update, the re-read pairing target and the two-state mic's
        # `reread_done` — all derived from the ownership read
        # (_sessions), zero extra queries. Reads are paired variants,
        # never takes: they're excluded from title/latest-take and are
        # exactly what reread_done counts. ──
        _spoken_rows, _read_rows = [], []
        for _s in (_sessions or []):
            if (_s.get("recording_kind") == "read") \
                    or _s.get("paired_session_id"):
                _read_rows.append(_s)
            else:
                _spoken_rows.append(_s)
        _spoken_rows.sort(key=lambda s: (s.get("take_index") or 0))
        _title = None
        for _s in _spoken_rows:   # latest take wins (trainings parity)
            _ctx = _s.get("intake_context") if isinstance(
                _s.get("intake_context"), dict) else {}
            _t = _ctx.get("topic")
            if isinstance(_t, str) and _t.strip():
                _title = _t.strip()
        _latest_take_sid = (str(_spoken_rows[-1].get("id"))
                            if _spoken_rows else None)
        # `reread_done` = a FINISHED re-read of the current version
        # exists — NOT merely a row (founder bug 2026-07-22: "the
        # orphaned recording"). In async mode the re-read POST
        # returns before transcription completes, so keying the
        # two-state mic on row-existence un-gated the "record another
        # take" button while the re-read was still processing — the
        # user started a take, then the re-read's late completion
        # tore them back to the ideal text with the mic still live.
        # A re-read counts only when its analysis_state is 'ready'
        # (or absent/null — sync mode + legacy rows are already done
        # by the time the POST returns).
        # THREE states the FE's mic renders (founder 2026-07-22):
        #   * no re-read of this version           → the re-read MIC
        #   * a re-read exists but is transcribing → LOADING, held in
        #     the button's place ("Finishing up your recording…")
        #   * a re-read has finished               → the NEXT-TAKE btn
        # `reread_done: false` alone can't distinguish the first two,
        # so the FE could not hold the loading state — that gap is why
        # the premature button appeared. `reread_processing` closes it:
        # a matching re-read whose analysis_state is 'processing'. A
        # FINISHED re-read wins (done → processing false); a failed one
        # is neither (the FE falls back to the mic so they can retry).
        _reread_done = False
        _reread_processing = False
        if _version is not None:
            for _s in _read_rows:
                _ctx = _s.get("intake_context") if isinstance(
                    _s.get("intake_context"), dict) else {}
                _iv = _ctx.get("ideal_version")
                # Tolerant match: the FE's form-encoded session_context
                # may carry the version as int or string.
                if _ctx.get("read_target") != "ideal_text" \
                        or _iv is None or str(_iv) != str(_version):
                    continue
                _astate = _s.get("analysis_state")
                if _astate in (None, "ready"):
                    _reread_done = True
                elif _astate == "processing":
                    _reread_processing = True
            # A completed re-read is definitive — the loading state
            # only shows when NO re-read of this version is done yet.
            if _reread_done:
                _reread_processing = False

        # ── IMMEDIATE NEXT-TAKE (founder 2026-07-24, T1 · 1.2): recording
        # another take must NOT wait on the re-read practice loop. The
        # re-read three-state mic above (reread_done/reread_processing)
        # is UNTOUCHED — its 2026-07-22 "orphaned recording" loading gate
        # still guards the re-read affordance. But the "record another
        # take" button is DECOUPLED from it: it is available the moment
        # this project has a spoken take, so a finished recording drops
        # the student straight back here ready to record again — no
        # loading state, no forced re-read first. Same continuable-project
        # rule as GET /explore/arc/<id>/setup (≥1 spoken take, reads
        # excluded), so the two can never disagree about whether a take
        # can be started.
        _can_record_take = bool(_spoken_rows)

        # ── SLIDE LINKAGE (FE handoff 2026-08-03, FE PR #222): the deck
        # url + per-paragraph slide identity, so the reading view can
        # interleave slide → its words exactly, cross-device (the FE's
        # localStorage fallback only covered the recording device). The
        # FIRST non-null presentation_ref across takes in take order —
        # the same never-clobbered-by-a-deckless-retake resolution
        # build_best_presentation uses for its canonical deck ref. Zero
        # extra queries (the ownership read already has the sessions). ──
        _pres_ref = None
        for _s in _spoken_rows:
            _ctx = _s.get("intake_context") if isinstance(
                _s.get("intake_context"), dict) else {}
            if _ctx.get("presentation_ref"):
                _pres_ref = _ctx.get("presentation_ref")
                break

        return jsonify({
            "arc_id": arc_id,
            "version": _version,
            "status": "verified" if _verified else "unverified",
            "title": _title,
            "updated_at": _r.get("updated_at"),
            "latest_take_session_id": _latest_take_sid,
            # The project's OFFICIAL-TAKE count (founder 2026-07-23):
            # the FE renders the document badge as "<take_count>.0".
            # PER-PROJECT by construction (spoken takes of THIS arc;
            # reads excluded) — never a global tally, and it grows on
            # every recorded take (unlike `version`, which bumps only
            # when the text actually changes). continue_arc_id is what
            # keeps a new take appending here so this count climbs.
            "take_count": len(_spoken_rows),
            "reread_done": _reread_done,
            # True while a re-read of THIS version is still
            # transcribing — the FE holds a loading state in the
            # button's place until it clears (founder 2026-07-22).
            "reread_processing": _reread_processing,
            # IMMEDIATE next-take affordance (founder 2026-07-24, T1 ·
            # 1.2): the FE can offer "record another take" as soon as
            # this is true — DECOUPLED from reread_done/reread_processing
            # so a completed recording returns here ready to record again
            # with no loading gate and no forced re-read. True once the
            # project has a spoken take (same continuable-project rule as
            # /setup); reads never flip it.
            "can_record_take": _can_record_take,
            "text": _text,
            # The arc's served deck PDF (FE handoff 2026-08-03) — null on
            # a deckless arc; the FE treats anything but a non-empty
            # string as absent.
            "presentation_ref": _pres_ref or None,
            # One entry per "\n\n"-paragraph of `text`, carrying the deck
            # page (`slide_index`) its words were bucketed to when the
            # mapping is provable — null degrades the FE to its
            # exact-count zip, never a guessed attachment.
            "pieces": _ideal_text_pieces(arc_id, _text, _pres_ref),
            # True when the served text is the student's own edit of the
            # current version (the FE labels it).
            "user_edited": _user_edited,
            # The retained edit a NEWER version superseded (founder
            # 2026-07-28) — the FE's one-click "re-apply your additions".
            # Absent when there is nothing to re-offer.
            **({"prior_edit": _prior_edit} if _prior_edit else {}),
            "key_moments": [_decorate(m) for m in _moments],
            "moments_unlocked": _moments_entitled(arc_id),
            # Founder 2026-07-20: the 5-credit unlock buys COACH
            # explanations — the FE must show the unlock CTA ONLY when
            # at least one exists (unverified text → nothing behind the
            # paywall → no paywall shown). Automatic moments are free
            # regardless.
            "explanations_available": bool(_has_expl),
            # MASTER DOCUMENT (founder 2026-07-22): the latest save —
            # the FE hides take badges and gates the re-read button on
            # saved_version == version. Absent pre-migration/flag-off.
            **_ideal_save_state(arc_id, _version),
            # ── LIVING TRANSCRIPT (founder 2026-07-20, flag-gated):
            # span-anchored tracked changes on the full-transcript
            # document — strike/propose/bold/advice, each pointing at
            # exactly the words it is about. Absent when the flag is
            # off (the FE keeps rendering today's star layer). ──
            **_tracked_changes_block(arc_id, _text),
            # The moments-unlock price, top level (the FE reads it here
            # for the locked-moment prompt — the only paid item).
            "price_credits": int(getattr(
                config, "MOMENTS_UNLOCK_CREDITS", 5) or 5),
            # The personal notebook copy — free with the text now.
            "notes_text": _notes, "notes": _notes, "user_notes": _notes,
        }), 200
    except Exception as e:
        logger.error("explore ideal-text GET failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load ideal text",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/notes", methods=["PUT"])
@require_auth
def v2_explore_put_ideal_notes(arc_id):
    """Save the user's PERSONAL notebook copy (never the canonical — L1).
    Same gates as reading it (owned + paid + approved). Body: {text ≤20000}.
    200 {ok} · 400 · 402 · 404 · 500"""
    try:
        owned, _sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        # Single deliverable (2026-07-17): the ideal text is free → so is the
        # personal notebook copy (no gate).
        body = request.get_json(silent=True) or {}
        text = body.get("text")
        if not isinstance(text, str):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text is required"}), 400
        text = re.sub(r"<[^>]*>", "", text).strip()
        if len(text) > 20000:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text too long"}), 400
        ok = db.upsert_user_arc_ideal_notes(arc_id, str(request.user_id), text)
        if not ok:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        return jsonify({"ok": True, "arc_id": arc_id}), 200
    except Exception as e:
        logger.error("ideal-notes PUT failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500


@v2_bp.route("/explore/arc/<arc_id>/prior-take/decide", methods=["POST"])
@require_auth
def v2_explore_decide_prior_take(arc_id):
    """The decision on a cross-take change (founder 2026-07-20 #4):

      accept → the PREVIOUS take's wording replaces the current one and
               BAKES FORWARD — an approved ledger row keyed on the
               current phrase, so every future document carries it and
               it is never re-litigated;
      keep   → the current wording stands; the offer is remembered as
               dismissed and never shown again.

    Body: { action: "accept"|"keep", snippet_id (the previous fragment —
            the change's `snippet_id`), quote (the current words),
            proposed_text (the previous words; required to accept) }
    200 { saved } · 400 · 404 · 500
    """
    try:
        from services.ideal_text_block import _living_transcript_enabled
        if not _living_transcript_enabled():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        if action not in ("accept", "keep"):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "action must be accept or keep"}), 400
        quote = (body.get("quote") or "").strip()
        snippet_id = (body.get("snippet_id") or "").strip()
        proposed = (body.get("proposed_text") or "").strip()
        if not quote or not snippet_id:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "quote and snippet_id are required",
            }), 400
        if action == "accept" and not proposed:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "proposed_text is required"}), 400

        from services.ideal_decision_ledger import normalize_phrase
        _v = None
        try:
            _v = (db.get_coach_arc_ideal_text(arc_id) or {}).get("version")
        except Exception:
            _v = None
        ok = db.upsert_ideal_decision(
            arc_id=str(arc_id), kind="replace",
            target_phrase=normalize_phrase(quote),
            display_phrase=quote,
            replacement_text=(proposed if action == "accept" else None),
            decision=("approved" if action == "accept" else "dismissed"),
            source="prior_take", snippet_id=snippet_id,
            version=(_v if isinstance(_v, int) else None))
        if ok and action == "accept":
            _reassemble_after_decision(arc_id)
        return jsonify({"saved": bool(ok)}), 200
    except Exception as e:
        logger.error("prior-take decide failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the decision"}), 500


@v2_bp.route("/explore/arc/<arc_id>/blocks/<int:block_key>/decide",
             methods=["POST"])
@require_auth
def v2_explore_decide_block(arc_id, block_key):
    """The MASTER-DOCUMENT block decision (founder 2026-07-22):

      accept → the offered block becomes the master's (badge flips to
               the new take; a candidate block activates); the document
               reassembles at once — version bump + snapshot + the
               idempotent ready bubble;
      keep   → the offer is remembered on the block's rejected list and
               never re-offered for that take.

    Body: { action: "accept"|"keep",
            take_session_id: <echo of the offered take — the race guard> }
    200 { saved } · 400 · 404 · 409 NOT_PENDING / STALE_OFFER · 500
    """
    try:
        from services.ideal_text_block import _living_transcript_enabled
        from services.master_document import (
            decide_block, master_document_enabled,
        )
        if not (master_document_enabled() and _living_transcript_enabled()):
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        action = body.get("action")
        if action not in ("accept", "keep"):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "action must be accept or keep"}), 400
        echo = (body.get("take_session_id") or "").strip()
        if not echo:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "take_session_id is required"}), 400
        ok, err = decide_block(arc_id, int(block_key), action, echo, db)
        if not ok:
            if err == "NOT_FOUND":
                return jsonify({"code": "NOT_FOUND",
                                "error": "block not found"}), 404
            if err in ("NOT_PENDING", "STALE_OFFER"):
                return jsonify({
                    "code": err,
                    "error": ("No offer is pending here."
                              if err == "NOT_PENDING"
                              else "A newer take changed this offer."),
                }), 409
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        if action == "accept":
            _reassemble_after_decision(arc_id)
            try:
                from services.arc_notifications import (
                    fire_ideal_version_ready,
                )
                _r2 = db.get_coach_arc_ideal_text(arc_id) or {}
                if _r2.get("version"):
                    fire_ideal_version_ready(
                        db, str(request.user_id), str(arc_id),
                        _r2["version"])
            except Exception:
                pass
        return jsonify({"saved": True}), 200
    except Exception as e:
        logger.error("block decide failed arc=%s key=%s: %s",
                     arc_id, block_key, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the decision"}), 500


def _block_variants_gate() -> bool:
    """The variant-pool read surfaces exist only on top of the master
    model (founder 2026-08-03; BLOCK_VARIANTS_ENABLED default OFF —
    flag off, every route below is a plain 404 and the FE is
    unaffected)."""
    try:
        from services.ideal_text_block import _living_transcript_enabled
        from services.ideal_text_variants import variants_enabled
        from services.master_document import master_document_enabled
        return (variants_enabled() and master_document_enabled()
                and _living_transcript_enabled())
    except Exception:
        return False


@v2_bp.route("/explore/arc/<arc_id>/blocks/variants", methods=["GET"])
@require_auth
def v2_explore_block_variants(arc_id):
    """The PICKER read (founder 2026-08-03, fear #3): per block, every
    text this block has ever had — each take's version (verbatim,
    take-badged) plus the student's latest edit — with the current one
    flagged. Block-level granularity by design (the mobile picker stays
    clean). AC-9: provenance and text only, no scores.

    200 { blocks: [{block_key, label, take_index, variants: [
          {variant_id, source, take_index, text, is_current}]}],
          head_revision } · 404 · 500
    """
    try:
        if not _block_variants_gate():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "arc not found"}), 404
        from services.ideal_text_variants import block_variants_payload
        payload = block_variants_payload(db, str(arc_id))
        if payload is None:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not read the document — "
                                     "try again."}), 500
        return jsonify({"arc_id": arc_id, **payload}), 200
    except Exception as e:
        logger.error("block variants GET failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load"}), 500


@v2_bp.route("/explore/arc/<arc_id>/blocks/<int:block_key>/select",
             methods=["POST"])
@require_auth
def v2_explore_select_block_variant(arc_id, block_key):
    """MIX AND MATCH (founder 2026-08-03): point one block at ANY pooled
    variant — this take's, an earlier take's, or my own edit. The
    displaced text stays in the pool (selecting is never destructive),
    the composition records a new revision, and the document reassembles
    at once.

    Body: { variant_id }
    200 { saved } · 400 · 404 · 409 NOT_PENDING (candidate block) · 500
    """
    try:
        if not _block_variants_gate():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        variant_id = (str(body.get("variant_id") or "")).strip()
        if not variant_id:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "variant_id is required"}), 400
        from services.ideal_text_variants import select_block_variant
        ok, err = select_block_variant(db, str(arc_id), int(block_key),
                                       variant_id, str(request.user_id))
        if not ok:
            if err == "NOT_FOUND":
                return jsonify({"code": "NOT_FOUND",
                                "error": "block or variant not found"}), 404
            if err == "NOT_PENDING":
                return jsonify({"code": "NOT_PENDING",
                                "error": "This block is not selectable "
                                         "yet."}), 409
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        _reassemble_after_decision(arc_id)
        return jsonify({"saved": True}), 200
    except Exception as e:
        logger.error("block select failed arc=%s key=%s: %s",
                     arc_id, block_key, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the selection"}), 500


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/revisions", methods=["GET"])
@require_auth
def v2_explore_ideal_revisions(arc_id):
    """The composition timeline (founder 2026-08-03, fear #2): every
    selection state the document has been in, newest first, with the
    head flagged — the FE's undo/history surface. Selections are pointer
    lists; the texts live in the pool, so nothing here is a copy.

    200 { revisions: [{revision, reason, created_at, is_head}],
          head_revision } · 404 · 500
    """
    try:
        if not _block_variants_gate():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "arc not found"}), 404
        rows = db.list_ideal_text_compositions(str(arc_id), limit=50)
        if rows is None:
            rows = []
        head = (db.get_ideal_text_composition_head(str(arc_id))
                or {}).get("head_revision")
        return jsonify({
            "arc_id": arc_id,
            "head_revision": head,
            "revisions": [{
                "revision": r.get("revision"),
                "reason": r.get("reason"),
                "created_at": r.get("created_at"),
                "is_head": r.get("revision") == head,
            } for r in rows],
        }), 200
    except Exception as e:
        logger.error("ideal revisions GET failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load"}), 500


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/revisions/<int:revision>"
             "/restore", methods=["POST"])
@require_auth
def v2_explore_restore_ideal_revision(arc_id, revision):
    """GO BACK (founder 2026-08-03, fear #2): repoint the document at an
    earlier composition. Blocks that revision recorded write through;
    blocks added since stay as they are (restore repoints, never
    deletes). The restore lands as a NEW revision, so it is itself
    undoable. The document reassembles at once.

    200 { restored, head_revision } · 404 · 500
    """
    try:
        if not _block_variants_gate():
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "arc not found"}), 404
        from services.ideal_text_variants import restore_revision
        ok, err = restore_revision(db, str(arc_id), int(revision),
                                   str(request.user_id))
        if not ok:
            if err == "NOT_FOUND":
                return jsonify({"code": "NOT_FOUND",
                                "error": "revision not found"}), 404
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not restore"}), 500
        _reassemble_after_decision(arc_id)
        head = (db.get_ideal_text_composition_head(str(arc_id))
                or {}).get("head_revision")
        return jsonify({"restored": True, "arc_id": arc_id,
                        "head_revision": head}), 200
    except Exception as e:
        logger.error("ideal revision restore failed arc=%s rev=%s: %s",
                     arc_id, revision, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to restore"}), 500


@v2_bp.route("/explore/arc/<arc_id>/setup", methods=["GET"])
@require_auth
def v2_explore_arc_setup(arc_id):
    """The saved SETUP of a project, so continuing it never re-asks the
    student (founder 2026-07-22, context-aware recording).

    Deliberately MINIMAL — only what the setup screen would otherwise
    ask for, read from the arc's latest SPOKEN take's intake_context:

      200 { arc_id, topic, audience, strategic_context,
            target_length_seconds, slides, presentation_ref }

    `topic` is load-bearing (the record POST rejects a take without
    one); `slides`/`presentation_ref` are load-bearing for a DECKED
    project — the master-document skeleton is keyed on slide index, so
    continuing a decked talk without its deck would produce unmappable
    takes. No scores, no take data, no counts (AC-9).

    Global recording constants deliberately do NOT live here (2026-07-27):
    `long_take_caution_sec` and the min-content floor are properties of the
    product, not of this project, and they have one home —
    GET /v2/config/recording. This payload stays exactly the setup fields
    (there is a test pinning that set).

    404 when the arc isn't the caller's or has no spoken take.
    """
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "project not found"}), 404
        from services.best_presentation import spoken_arc_sessions
        spoken = spoken_arc_sessions(sessions or [])
        if not spoken:
            return jsonify({"code": "NOT_FOUND",
                            "error": "project not found"}), 404
        spoken.sort(key=lambda s: (s.get("take_index") or 0,
                                   s.get("created_at") or ""))
        # The LATEST take's context is the live setup (a later take may
        # have added the deck or changed the audience).
        ctx = {}
        for s in reversed(spoken):
            _c = s.get("intake_context")
            if isinstance(_c, dict) and _c.get("topic"):
                ctx = _c
                break
        if not ctx:
            _last = spoken[-1].get("intake_context")
            ctx = _last if isinstance(_last, dict) else {}
        return jsonify({
            "arc_id": arc_id,
            "topic": ctx.get("topic"),
            "audience": ctx.get("audience"),
            "strategic_context": ctx.get("strategic_context"),
            "target_length_seconds": ctx.get("target_length_seconds"),
            "slides": ctx.get("slides") or [],
            "presentation_ref": ctx.get("presentation_ref"),
        }), 200
    except Exception as e:
        logger.error("arc setup failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to load the setup"}), 500


@v2_bp.route("/explore/arc/<arc_id>/context-document", methods=["POST"])
@require_auth
def v2_explore_upload_context_document(arc_id):
    """Upload a supplementary CONTEXT document (X-1, founder 2026-07-24) — a
    report / case metrics / Q&A (up to ~20 pages) ALONGSIDE the deck. We
    extract its plain text and store it against the arc so the assembly and
    feedback can draw on the background.

    L1: BACKGROUND only — its facts inform feedback/continuity, never the
    verbatim ideal text. multipart `file` (PDF, or UTF-8 text/markdown).

    200 { ok, pages, chars, truncated } · 400 INVALID_INPUT / NO_TEXT ·
    404 · 413 FILE_TOO_LARGE · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "project not found"}), 404
        _max_bytes = max(1, int(
            getattr(config, "CONTEXT_DOC_MAX_MB", 25) or 25)) * 1024 * 1024
        if (request.content_length or 0) > _max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE",
                            "error": "the document is too large"}), 413
        f = request.files.get("file")
        if f is None:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "file is required"}), 400
        data = f.read() or b""
        if not data:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "the file is empty"}), 400
        if len(data) > _max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE",
                            "error": "the document is too large"}), 413
        from services.context_document import extract_context_text
        parsed = extract_context_text(
            data, content_type=getattr(f, "content_type", None),
            filename=getattr(f, "filename", None))
        if not parsed.get("text"):
            return jsonify({
                "code": "NO_TEXT",
                "error": "no readable text found in the document"}), 400
        db.upsert_arc_context_document(
            arc_id, parsed["text"], parsed["pages"], parsed["chars"],
            filename=getattr(f, "filename", None),
            truncated=parsed["truncated"])
        return jsonify({"ok": True, "pages": parsed["pages"],
                        "chars": parsed["chars"],
                        "truncated": parsed["truncated"]}), 200
    except Exception as e:
        logger.error("context-document upload failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to upload"}), 500


@v2_bp.route("/explore/arc/<arc_id>/context-document", methods=["GET"])
@require_auth
def v2_explore_get_context_document(arc_id):
    """Whether a context document is attached (X-1) — the FE renders the chip
    + a 'replace' affordance. The text itself is NOT returned (background
    only). 200 { has_document, pages?, chars?, truncated?, filename? } · 404
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND",
                            "error": "project not found"}), 404
        row = db.get_arc_context_document(arc_id)
        if not row or not (row.get("text") or "").strip():
            return jsonify({"has_document": False}), 200
        return jsonify({
            "has_document": True,
            "pages": row.get("pages"),
            "chars": row.get("chars"),
            "truncated": bool(row.get("truncated")),
            "filename": row.get("filename"),
        }), 200
    except Exception as e:
        logger.error("context-document GET failed arc=%s: %s", arc_id, e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load"}), 500


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/save", methods=["POST"])
@require_auth
def v2_explore_save_ideal_text(arc_id):
    """SAVE = ACCEPT-AND-FREEZE (founder decision #3, 2026-07-22): the
    student accepts the master's current state as their script.

      * every UNACTIONED offer resolves as kept-mine (dismissed-
        remembered — Save must leave a clean document, not hidden
        pending state);
      * the current version is stamped as a save row (the FE hides the
        take badges and gates the re-read button on it);
      * the frozen snapshot rides the existing per-version history lane.

    200 { saved: true, saved_version } · 404 · 409 NOTHING_TO_SAVE · 500
    """
    try:
        from services.ideal_text_block import _living_transcript_enabled
        from services.master_document import master_document_enabled
        if not (master_document_enabled() and _living_transcript_enabled()):
            return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404

        # Resolve every unactioned offer as kept-mine. A failed block
        # READ must not freeze over unknown state, and a failed resolve
        # must not stamp a save that still has hidden pending offers
        # (review findings #8/#11/#18).
        rows = db.list_ideal_text_blocks(str(arc_id))
        if rows is None:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not read the document — "
                                     "try again."}), 500
        from services.master_document import decide_block
        _resolve_failed = False
        for r in rows:
            if r.get("status") == "pending_upgrade":
                ok, _e = decide_block(
                    arc_id, int(r.get("block_key")), "keep",
                    r.get("challenger_take_session_id"), db)
                _resolve_failed = _resolve_failed or not ok
            elif r.get("status") == "candidate":
                ok, _e = decide_block(
                    arc_id, int(r.get("block_key")), "keep",
                    r.get("incumbent_take_session_id"), db)
                _resolve_failed = _resolve_failed or not ok
        if _resolve_failed:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not resolve every open "
                                     "suggestion — try again."}), 500

        _row = db.get_coach_arc_ideal_text(arc_id) or {}
        _v = _row.get("version")
        if not isinstance(_v, int):
            return jsonify({"code": "NOTHING_TO_SAVE",
                            "error": "No ideal text to save yet."}), 409
        ok = db.insert_ideal_text_save(str(arc_id), _v)
        if not ok:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        return jsonify({"saved": True, "arc_id": arc_id,
                        "saved_version": _v}), 200
    except Exception as e:
        logger.error("ideal-text save failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save"}), 500


def _ideal_save_state(arc_id, current_version) -> dict:
    """{saved_version, saved_at, is_saved} from the latest save row —
    {} when the master flag is off or nothing was ever saved."""
    try:
        from services.master_document import master_document_enabled
        if not master_document_enabled():
            return {}
        row = db.get_latest_ideal_text_save(str(arc_id))
        if not row:
            return {}
        _pending = False
        try:
            _pending = any(
                r.get("status") in ("pending_upgrade", "candidate")
                for r in (db.list_ideal_text_blocks(str(arc_id)) or []))
        except Exception:
            _pending = False
        return {
            "saved_version": row.get("version"),
            "saved_at": row.get("saved_at"),
            # A saved document UN-saves when new offers arrive — an
            # offers-only take bumps no version, so the version match
            # alone left is_saved stuck true (review finding #28).
            "is_saved": bool(current_version is not None
                             and row.get("version") == current_version
                             and not _pending),
        }
    except Exception:
        return {}


def _previous_spoken_session(arc_id, current_session_id):
    """The spoken take immediately BEFORE the document's take — the
    comparison base for cross-take discernment. None when this is the
    first take. Best-effort."""
    try:
        from services.best_presentation import spoken_arc_sessions
        spoken = spoken_arc_sessions(db.get_arc_sessions(arc_id) or [])
        spoken.sort(key=lambda s: (s.get("take_index") or 0,
                                   s.get("created_at") or ""))
        ids = [str(s.get("id")) for s in spoken if s.get("id")]
        if not current_session_id or str(current_session_id) not in ids:
            return None
        i = ids.index(str(current_session_id))
        return ids[i - 1] if i > 0 else None
    except Exception:
        return None


def _key_points_enabled() -> bool:
    """E-1 presentation-mode cue sheet (founder 2026-07-24). DEFAULT OFF until
    the FE ships the full↔key-words toggle (E-2); flip KEY_POINTS_ENABLED=1 in
    Railway after. Absent key ⇒ the FE is unaffected."""
    return (os.getenv("KEY_POINTS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _tracked_changes_block(arc_id, served_text) -> dict:
    """The `changes` block of the SD student GET (founder 2026-07-20) —
    {} when the Living Transcript flag is off, so the key is simply
    ABSENT and the FE keeps rendering today's star layer.

    Anchors are resolved against the SERVED text: each piece of the take
    the document came from is located as an exact substring, then the
    change is narrowed inside that window. A piece whose words are no
    longer there (baked, coach-corrected, student-edited) yields NO
    change rather than a mis-pointed one (#219). Best-effort."""
    try:
        from services.ideal_text_block import _living_transcript_enabled
        if not _living_transcript_enabled():
            return {}
        from services.tracked_changes import (
            build_tracked_changes, drop_overlaps, verify_changes,
        )
        from services.transcript_document import (
            build_transcript_document, relocate_pieces,
        )
        from services.master_document import (
            assemble_master_document, master_document_enabled,
            upgrade_changes,
        )
        _master_on = master_document_enabled()
        if _master_on:
            # MASTER MODEL (founder 2026-07-22): the document is the
            # persistent master; its pieces carry per-piece spans + the
            # origin take badge, so the star lane anchors unchanged. The
            # prior-take lane is superseded by block upgrade offers.
            _master = assemble_master_document(arc_id, database=db)
            if _master.get("ready"):
                doc = _master.get("document") or {}
                doc["text"] = _master.get("text")
            else:
                # No skeleton yet (flip-ON before the next take / pre-
                # migration): the star lane keeps anchoring on the
                # living-transcript document rather than going dark.
                _master_on = False
                doc = build_transcript_document(arc_id, database=db)
        else:
            doc = build_transcript_document(arc_id, database=db)
        if not doc:
            return {}
        # The served text may already carry approved bakes / coach text —
        # re-anchor the pieces onto it MONOTONICALLY (never a bare
        # first-occurrence search, the review's mis-anchor defect).
        _pieces = relocate_pieces(served_text, doc.get("pieces") or [])
        # E-1 presentation-mode cue sheet (founder 2026-07-24): one verbatim
        # starting-point milestone per block, for the FE's full↔key-words
        # toggle. Flag-gated (default OFF) so the key is simply ABSENT until
        # the FE ships it. L1-safe (a verbatim prefix of the served text).
        _key_points = None
        try:
            if _key_points_enabled():
                from services.key_points import build_key_points
                _key_points = build_key_points(_pieces, served_text)
        except Exception as _kpe:
            logger.warning("key_points failed arc=%s: %s", arc_id, _kpe)
            _key_points = None
        _sugs = db.get_moment_suggestions_by_arc(arc_id) or {}
        _applied = []
        try:
            # The master document spans takes: feed EVERY distinct origin
            # session, not the doc-level take_session_id (which is None
            # under the master flag and starved the applied map — review
            # findings #12/#16).
            _sess_ids = {p.get("take_session_id")
                         for p in (doc.get("pieces") or [])
                         if p.get("take_session_id")}
            if doc.get("take_session_id"):
                _sess_ids.add(doc.get("take_session_id"))
            _applied = [k for k, v in _moment_applied_map(
                sorted(_sess_ids)).items() if v]
        except Exception:
            _applied = []
        # T3 (founder 2026-07-23): an emphasis star bolds only its
        # KEY-PHRASE sub-span, not the whole fragment. The signal is the
        # snippet's say-it-stronger upgrade wordings — bulk-read once for
        # the emphasize snippets only (bounded; get_snippets_by_ids added
        # #232), never a per-snippet storm. Best-effort → no narrowing
        # falls back to the whole fragment (today's behavior).
        _kp_by_snip = {}
        try:
            from services.tracked_changes import (
                key_phrases_from_say_it_stronger,
            )
            _emph_ids = [k for k, v in (_sugs or {}).items()
                         if isinstance(v, dict)
                         and v.get("kind") == "emphasize"]
            if _emph_ids:
                for _srow in (db.get_snippets_by_ids(_emph_ids) or []):
                    _phr = key_phrases_from_say_it_stronger(
                        _srow.get("say_it_stronger"))
                    if _phr:
                        _kp_by_snip[str(_srow.get("id"))] = _phr
        except Exception as _kp_err:
            logger.warning("emphasis key-phrases failed arc=%s: %s",
                           arc_id, _kp_err)
        changes = build_tracked_changes(
            served_text, _pieces, _sugs, applied=_applied,
            key_phrases_by_snippet=_kp_by_snip)

        # ── CROSS-TAKE DISCERNMENT (founder decision 2026-07-20 #4):
        # where the PREVIOUS take said the same thing better, its wording
        # comes back as an approvable change on this document. The
        # ranking blend does the judging (L2 untouched); a fragment the
        # student already decided on is never re-offered. Best-effort. ──
        if _master_on:
            # Block-level upgrade offers + candidate additions — the
            # master model's cross-take lane.
            try:
                changes.extend(upgrade_changes(arc_id, served_text, db))
            except Exception as _up_err:
                logger.warning("upgrade changes failed arc=%s: %s",
                               arc_id, _up_err)
        try:
            _prev = None if _master_on else _previous_spoken_session(
                arc_id, doc.get("take_session_id"))
            if _prev:
                from services.prior_take_changes import (
                    build_prior_take_changes,
                )
                from services.ideal_decision_ledger import load_ledger
                _prev_doc = build_transcript_document(
                    arc_id, database=db, session_id=_prev)
                if _prev_doc:
                    # ONLY cross-take decisions suppress a cross-take
                    # offer — a star-lane decision on the same snippet
                    # must not silence it (review finding).
                    _decided = {
                        str(r.get("snippet_id"))
                        for r in (load_ledger(db, arc_id) or [])
                        if r.get("snippet_id")
                        and r.get("source") == "prior_take"
                    }
                    changes.extend(build_prior_take_changes(
                        {"text": served_text, "pieces": _pieces},
                        _prev_doc, database=db, decided_ids=_decided))
        except Exception as _pt_err:
            logger.warning("prior-take changes failed arc=%s: %s",
                           arc_id, _pt_err)

        # One span may carry only ONE change — a polish star and a
        # cross-take offer on the same words would render as overlapping
        # strikes (review finding). Earliest-then-narrowest wins.
        changes = drop_overlaps(changes)
        _kp = {"key_points": _key_points} if _key_points is not None else {}
        if not verify_changes(served_text, changes):
            logger.warning("tracked changes: span check failed arc=%s "
                           "(serving none)", arc_id)
            return {"changes": [], **_kp}
        return {"changes": changes, **_kp}
    except Exception as e:
        logger.warning("tracked changes failed arc=%s: %s", arc_id, e)
        return {}


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/user-edit", methods=["PUT"])
@require_auth
def v2_explore_put_ideal_user_edit(arc_id):
    """Persist the student's IN-PLACE edit of the SD ideal text (founder
    2026-07-17). The post-recording screen IS the ideal text 1.0, editable in
    place — this makes that edit survive reloads + show on every surface. The
    edit is stamped with the ideal-text VERSION it was made against; it wins
    display only while that equals the current version (a new take supersedes
    it — retained, not shown; BE-2 pinned default). NEVER overwrites the coach
    canonical or the legacy notebook copy (L1 — separate lanes).

    Body: {text ≤20000, version:int, reapplied?:true}. `reapplied` (founder
    2026-07-28) marks a one-click re-apply of a superseded edit — LOG-ONLY
    telemetry (the decision metric for the parked versioning change): never
    persisted, never surfaced; anything but boolean true is ignored.
    200 {saved: true, version}
    400 INVALID_INPUT · 404 · 409 VERSION_SUPERSEDED {current_version} · 500
    """
    try:
        owned, _sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        text = body.get("text")
        if not isinstance(text, str):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text is required"}), 400
        _v = body.get("version")
        if not isinstance(_v, int) or isinstance(_v, bool) or _v < 1:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "version must be a positive integer"}), 400
        text = re.sub(r"<[^>]*>", "", text).strip()   # markers ride through
        if len(text) > 20000:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text too long"}), 400

        # The current version — the edit only sticks against it. A newer
        # version having assembled since → 409 so the FE refetches + re-offers.
        _row = db.get_coach_arc_ideal_text(arc_id) or {}
        _machine = ((_row.get("auto_text") or "").strip()
                    or ((_row.get("text") or "").strip()
                        if not (_row.get("updated_by")
                                or _row.get("approved_at")) else ""))
        current = _row.get("version") or (1 if _machine else None)
        if not isinstance(current, int):
            return jsonify({"code": "NOTHING_TO_EDIT",
                            "error": "No ideal text to edit yet."}), 409
        if _v != current:
            return jsonify({
                "code": "VERSION_SUPERSEDED",
                "current_version": current,
            }), 409

        ok = db.upsert_user_ideal_edit(
            arc_id, str(request.user_id), text, current)
        if not ok:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        # RE-APPLY TELEMETRY (founder 2026-07-28): one log line per
        # successful one-click re-apply of a superseded edit — the
        # decision metric for the PARKED versioning change (how often do
        # users re-apply an addition a new take dropped?). Log-only:
        # never persisted, never surfaced; only boolean true counts.
        if body.get("reapplied") is True:
            logger.info("ideal_edit.reapplied arc=%s version=%s chars=%d",
                        arc_id, current, len(text))
        # ── EDIT INHERITANCE (founder 2026-07-20, rule 4b): decompose the
        # edit into phrase decisions on the ledger (source='user_edit',
        # approved) so the NEXT version bakes the student's wording
        # forward — their edit is never reversed by a new take. The base
        # is the version's served base (verified snapshot when current,
        # else the machine copy); a wholesale rewrite decomposes to
        # nothing and simply stays the wholesale edit. Best-effort. ──
        try:
            _vv = _row.get("verified_version")
            _vtext = (_row.get("verified_text") or "").strip()
            _base = _vtext if (_vv == current and _vtext) else _machine
            if _base:
                from services.protected_phrases import (
                    record_user_edit_decisions,
                )
                record_user_edit_decisions(
                    db, arc_id, base_text=_base, user_text=text,
                    version=current)
        except Exception as _led_err:
            logger.warning("ideal user-edit: ledger failed arc=%s: %s",
                           arc_id, _led_err)
        # ── VARIANT CAPTURE (founder 2026-08-03, fear #1): under the
        # master model the edit ALSO lands BLOCK-LEVEL in the variant
        # pool (source='user_edit') — a first-class picker citizen a new
        # take can never supersede, beside the whole-blob lane above.
        # Only when the base the student edited against IS the master
        # text (a verified snapshot that diverged would make the diff
        # attribute coach changes to the student). Best-effort. ──
        try:
            from services.master_document import (
                assemble_master_document, master_document_enabled,
            )
            if master_document_enabled():
                _m = assemble_master_document(arc_id, database=db)
                _mtext = (_m.get("text") or "")
                _vbase = ((_row.get("verified_text") or "").strip()
                          if _row.get("verified_version") == current
                          else "") or _machine
                if _m.get("ready") and _mtext and _vbase and \
                        re.sub(r"\s+", " ", _mtext).strip().lower() == \
                        re.sub(r"\s+", " ", _vbase).strip().lower():
                    from services.ideal_text_variants import (
                        capture_user_edit_variants,
                    )
                    capture_user_edit_variants(
                        db, str(arc_id), str(request.user_id), _mtext,
                        ((_m.get("document") or {}).get("pieces") or []),
                        text)
        except Exception as _var_err:
            logger.warning("ideal user-edit: variant capture failed "
                           "arc=%s: %s", arc_id, _var_err)
        return jsonify({"saved": True, "arc_id": arc_id,
                        "version": current}), 200
    except Exception as e:
        logger.error("ideal user-edit PUT failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500


# ── willab — game + snippet library (founder 2026-07-06: PAID, STUBBED) ─
#
# Neither feature exists yet — these are gated stubs so the FE can wire the
# paywall now: unpaid → 402 (drives purchase intent pre-launch); PAID → an
# honest 501 "not yet available" (never a fake unlock).


def _charge_arc_deliverable(user_id, action, arc_id):
    """Charge a once-per-arc deliverable. NEVER raises, NEVER blocks.

    Token pricing Phase 1. Returns the ChargeResult-ish dict or None; callers
    IGNORE the outcome by design. These deliverables are reads of content the
    take already generated — the marginal cost to us is zero — so refusing to
    serve one on a low balance would withhold something already produced and
    paid for, which is exactly the failure fence §6.1 exists to prevent.

    ref_id=arc_id makes it idempotent: re-opening the game or the insights for
    the same presentation charges once, ever. The ledger's partial unique index
    on (user_id, action, ref_id) is the real guard.
    """
    try:
        from services.token_account import charge
        return charge(str(user_id), action, ref_id=str(arc_id)).as_dict()
    except Exception as e:
        logger.warning("token charge failed action=%s arc=%s err=%s",
                       action, arc_id, e)
        return None


@v2_bp.route("/arc/<arc_id>/game", methods=["GET"])
@require_auth
def v2_arc_game(arc_id):
    # NOTE: token charge is applied below, after the arc is confirmed to
    # belong to the caller — see _charge_arc_deliverable.
    """Engine 5 (founder 2026-07-11) — the key-moments game, replacing the
    501 stub. Free (the $25 gate is retired, single-deliverable 2026-07-17).

    Rounds mix the arc's coach-confirmed key moments with the user's OWN
    coach-unmarked moments as decoys; truth is NEVER in this payload (the
    FE learns it by answering). Deterministic order; ?snippet=<id> pins
    that round first (deep links from the Key-moment button / PDF).

    Response 200 { arc_id, rounds:[{round, snippet_id, transcript,
                   audio_ref, start_offset_ms, duration_ms}] }
             200 { arc_id, rounds: [], reason: "NO_KEY_MOMENTS_YET" }
             402 · 404 · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        from services.game_engine import build_game_rounds
        rounds = build_game_rounds(
            db, arc_id, request.user_id,
            first_snippet=(request.args.get("snippet") or None),
        )
        body = {"arc_id": arc_id, "rounds": rounds}
        if not rounds:
            # honest empty state — the coach hasn't confirmed key moments yet
            body["reason"] = "NO_KEY_MOMENTS_YET"
        else:
            # Charge only when there is actually a game to play. An empty
            # NO_KEY_MOMENTS_YET response is the user finding out the coach
            # hasn't marked anything yet — billing them for that would charge
            # for our latency.
            _charge_arc_deliverable(request.user_id, "game", arc_id)
        return jsonify(body), 200
    except Exception as e:
        logger.error("arc game failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load game"}), 500


@v2_bp.route("/arc/<arc_id>/game/answers", methods=["POST"])
@require_auth
def v2_arc_game_answer(arc_id):
    """One game answer → verdict + the "Here is why" content (Engine 5).

    Persists the answer into snippet_peer_labels (source='game') as
    SECOND-ORDER signal below coach truth (L2/L3 — never joined into the
    coach corpus). The why paragraphs are qualitative-only (AC-9): the
    moment's load-bearing words, this user's mined acoustic patterns
    (Engine 4), and the moment's delivery technique; plus the coach's
    breakthrough video when one is attached.

    Body: { "round_id": uuid, "answer": bool }
      (round_id IS the moment's snippet id, echoed from the game GET;
       `snippet_id` / `answer_is_key` accepted as aliases.)
    200 { correct, truth_is_key, why: [str], keywords: [str], video_ref }
    400 · 402 · 404 · 500
    """
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        snippet_id = body.get("round_id") or body.get("snippet_id")
        if not isinstance(snippet_id, str) or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT", "error": "round_id must be a UUID",
            }), 400
        answer = body.get("answer")
        if answer is None:
            answer = body.get("answer_is_key")
        if not isinstance(answer, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "answer must be a boolean",
            }), 400
        from services.game_engine import answer_round
        result = answer_round(
            db, arc_id, request.user_id, snippet_id, answer,
        )
        if result is None:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "That moment is not part of this training",
            }), 404
        return jsonify(result), 200
    except Exception as e:
        logger.error("arc game answer failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to judge answer"}), 500


@v2_bp.route("/arc/<arc_id>/game/save", methods=["POST"])
@require_auth
def v2_arc_game_save(arc_id):
    """"Save to daily practice" — bookmark this game under today's date
    (Engine 5 / backlog 3.3). Idempotent per (user, arc, day).
    200 { saved } · 402 · 404 · 500"""
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        if not db.insert_game_save(str(request.user_id), str(arc_id)):
            return jsonify({
                "code": "V2_ERROR", "error": "Could not save the practice",
            }), 500
        return jsonify({"saved": True, "arc_id": arc_id}), 200
    except Exception as e:
        logger.error("arc game save failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500


@v2_bp.route("/arc/<arc_id>/snippet-library", methods=["GET"])
@require_auth
def v2_arc_snippet_library(arc_id):
    """Stub — the per-user snippet library (not yet built). 501 until it
    ships."""
    try:
        owned, _ = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        return jsonify({
            "code": "NOT_YET_AVAILABLE",
            "message": "Your snippet library is coming soon.",
        }), 501
    except Exception as e:
        logger.error("arc snippet-library failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load snippet library",
        }), 500


# ── FIX.3 — Dad jokes health probe (deploy verification) ────────────


@v2_bp.route("/admin/health/dad-jokes", methods=["GET"])
@require_admin
def v2_admin_dad_jokes_health():
    """Health probe for the dad_jokes table.

    Lets admin + FE verify the migration ran on Supabase. Common
    deploy failure: BE ships the opener endpoints, the migration
    is forgotten, the opener silently 204-skips, FE has no signal.

    Response 200::

        {
          "table_exists": bool,
          "joke_count":   int,            // active rows only
          "sample_joke":  {id, setup, punchline, emoji} | null,
          "verdict":      "ok"
                          | "table_missing"
                          | "table_empty"
        }
    """
    try:
        health = db.dad_jokes_health()
        if not health.get("table_exists"):
            verdict = "table_missing"
        elif (health.get("joke_count") or 0) == 0:
            verdict = "table_empty"
        else:
            verdict = "ok"
        health["verdict"] = verdict
        return jsonify(health), 200
    except Exception as e:
        logger.error(
            "admin/health/dad-jokes failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code":  "V2_ERROR",
            "error": "Failed to probe dad_jokes health",
        }), 500


# ── Ticket 2 — Dad-joke onboarding opener ────────────────────────────
#
# Three-bubble flow on a new user's first onboarding contact:
#   1. /onboarding/opener/start  → returns {stage: 'setup', frame, setup, joke_id}
#   2. /onboarding/opener/next   → body {joke_id, user_reply}
#                                  returns {stage: 'punchline', ack, punchline}
#   3. /onboarding/opener/next   → body {joke_id, user_reply, after_punchline: true}
#                                  returns {stage: 'pivot', pivot_line, done: true}
#
# Auth: @optional_auth — GUEST-ALLOWED (founder 2026-07-14 regression fix).
# The round-4 flow moved onboarding SIGNED-OUT-FIRST (record before signup),
# so a guest hitting the old @require_auth opener got 401 → no joke → "it
# can't." The opener reads NO user data (it just picks a random joke and
# echoes the reply), so anonymous is safe: request.user_id is simply None.
#
# Canonical PIVOT_LINE lives in services/onboarding_opener.py and
# is never LLM-generated. The LLM only produces the optional ack
# line that bridges user reply → punchline.


@v2_bp.route("/onboarding/opener/start", methods=["POST"])
@optional_auth
def v2_onboarding_opener_start():
    """Begin the dad-joke onboarding opener.

    No body required. Picks a random active joke and returns the
    setup bubble shape::

        {
          "stage": "setup",
          "joke_id": "<uuid>",
          "frame":  "Attention, before we begin, let me crack a dad-joke!",
          "setup":  "How do cows stay up to date?"
        }

    Returns 204 (no opener) when the dad_jokes table is empty / not
    yet migrated — FE skips the opener and goes straight to the
    real first onboarding question. Silent fallback by design: the
    joke is decorative, never blocking.
    """
    try:
        from services.onboarding_opener import (
            pick_random_joke, build_setup_message,
        )
        joke = pick_random_joke()
        if not joke:
            logger.info(
                "opener.start.no_joke user=%s — skipping opener",
                request.user_id,
            )
            return ("", 204)
        payload = build_setup_message(joke)
        return jsonify(payload), 200
    except Exception as e:
        logger.error(
            "onboarding/opener/start failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Soft-fail: opener is decorative; return 204 so FE skips
        # without showing an error banner on the user's first
        # onboarding screen.
        return ("", 204)


@v2_bp.route("/onboarding/opener/next", methods=["POST"])
@optional_auth
def v2_onboarding_opener_next():
    """Advance the opener to the next bubble.

    Body::

        {
          "joke_id":          "<uuid>",        # required
          "user_reply":       "<string>",      # optional, used for ack
          "after_punchline":  false            # default false
        }

    Stage transitions:
      after_punchline=false → returns the PUNCHLINE bubble:
        {
          "stage":     "punchline",
          "joke_id":   "<uuid>",
          "ack":       "<≤80-char LLM bridge>",   # may be ""
          "punchline": "They read the moos-paper. 🐄"
        }

      after_punchline=true → returns the PIVOT bubble:
        {
          "stage":      "pivot",
          "joke_id":    null,
          "pivot_line": "Okok, nevermind. Let's focus on public speaking — how can I help you?",
          "done":       true
        }

    The pivot line is HARDCODED in services.onboarding_opener.
    PIVOT_LINE and never produced by the LLM. The ack on the
    punchline bubble is the only LLM-touched content in this flow.

    Responses:
      200 — normal flow
      400 INVALID_INPUT — missing/invalid joke_id
      404 JOKE_NOT_FOUND — joke_id resolves to nothing (admin
                            deactivated the joke between /start
                            and /next, or migration mismatch)
      500 V2_ERROR — unexpected; FE should bail to real onboarding
    """
    try:
        from services.onboarding_opener import (
            build_punchline_message,
            build_pivot_message,
            generate_punchline_ack,
        )

        body = request.get_json(silent=True) or {}
        joke_id_raw = body.get("joke_id")
        after_punchline = bool(body.get("after_punchline", False))
        user_reply = body.get("user_reply") or ""
        if not isinstance(user_reply, str):
            user_reply = ""

        # Pivot path — no joke lookup needed, pure constant return.
        # We accept (but don't require) joke_id here so the FE can
        # round-trip the same payload shape on every /next call.
        if after_punchline:
            return jsonify(build_pivot_message()), 200

        # Punchline path — joke_id is required and must resolve.
        if not joke_id_raw or not isinstance(joke_id_raw, str):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "joke_id is required for the punchline stage",
            }), 400
        if not _is_valid_uuid(joke_id_raw):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "joke_id must be a valid UUID",
            }), 400

        joke = db.get_dad_joke_by_id(joke_id_raw)
        if not joke:
            return jsonify({
                "code": "JOKE_NOT_FOUND",
                "error": "Joke not found",
            }), 404

        # LLM bridge ack — best-effort, empty string on any failure.
        ack = generate_punchline_ack(user_reply)
        payload = build_punchline_message(joke, ack=ack)
        return jsonify(payload), 200

    except Exception as e:
        logger.error(
            "onboarding/opener/next failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to advance opener",
        }), 500
