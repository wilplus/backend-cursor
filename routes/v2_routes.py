"""
V2 routes: admin CRUD + the willab learner flow (Lab/Readout/Insights,
Lounge, Library, profile). All /v2/admin/* require auth + admin.
(The legacy homework student flow was removed in the Phase-5 clearance.)
"""
from flask import request, jsonify
from config import Config
from auth import require_auth, optional_auth
from routes.admin import (  # noqa: F401 — is_admin/is_coach kept: tests patch them on this module
    require_admin, is_admin, require_admin_or_coach, is_coach,
)
from services.db import db
from services.rate_limits import (
    guest_funnel_limit,
    heavy_limit,
    llm_limit,
    regenerate_limit,
)
import logging
import sentry_sdk
import json
import hashlib
import mimetypes
import os
import uuid
from datetime import datetime, timezone
from werkzeug.utils import secure_filename
from typing import Any
from utils.errors import safe_error


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
    _arc_owned_by_caller,
    _charge_arc_deliverable,
    _continue_deck_arc,
    _continue_topic_arc,
    _fold_applied_moments,
    _moment_applied_map,
    _moment_explanations_map,
    _moment_playback_map,
    _moment_reference,
    _moment_reference_map,
    _moment_suggestions_enabled,
    _moments_entitled,
    _presentation_id_from_slides,
    _reassemble_after_decision,
    _spoken_takes_and_reads,
    _take_full_text,
    _take_key_moments,
    v2_arc_checkout,
    v2_arc_game,
    v2_arc_game_answer,
    v2_arc_game_save,
    v2_arc_redeem,
    v2_arc_snippet_library,
    v2_arc_unlock,
    v2_explore_arc_best_presentation,
    v2_explore_arc_breakthroughs,
    v2_explore_arc_edit_slide,
    v2_explore_arc_feedback,
    v2_explore_arc_moments,
    v2_explore_arc_progress,
    v2_explore_arc_setup,
    v2_explore_arc_take_comparison,
    v2_explore_get_context_document,
    v2_explore_start,
    v2_explore_upload_context_document,
    v2_get_moment_explanation,
    v2_unlock_moments,
)
from routes.v2.explore_ideal_text import (  # noqa: F401 — re-exported for import compat
    _block_variants_gate,
    _ideal_piece_provenance,
    _ideal_save_state,
    _ideal_text_pieces,
    _instant_ideal_enabled,
    _key_points_enabled,
    _previous_spoken_session,
    _tracked_changes_block,
    v2_explore_block_variants,
    v2_explore_decide_block,
    v2_explore_decide_prior_take,
    v2_explore_get_ideal_text,
    v2_explore_ideal_revisions,
    v2_explore_put_ideal_notes,
    v2_explore_put_ideal_user_edit,
    v2_explore_restore_ideal_revision,
    v2_explore_save_ideal_text,
    v2_explore_select_block_variant,
    v2_talk_ideal_text,
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


# The guest funnel's two hourly caps (per-IP + global) now live in
# services/rate_limits.py::guest_funnel_limit, decorated onto the upload
# route below. Same caps, same config vars, same 429 copy — but counted in
# the shared Redis instead of an in-process dict, so the real cap is the
# stated cap rather than `stated x gunicorn workers`, and it survives a
# restart.


@v2_bp.route("/public/shaky-voice/upload", methods=["POST"])
@guest_funnel_limit
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
        return safe_error("INTERNAL_ERROR", 500, exc=e)


@v2_bp.route("/coaching/start", methods=["POST"])
@llm_limit
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
@llm_limit
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
@llm_limit
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
@llm_limit
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


@v2_bp.route("/user/snippets/<snippet_id>/confidence-review", methods=["POST"])
@require_auth
def v2_user_snippet_confidence_review(snippet_id):
    """The PEER-REVIEW VALIDATION LOOP (founder 2026-08-03) — what the retired
    acoustic stress lane became.

    A user or peer is shown the AI's confidence choice on one snippet and
    answers one question: did it get this right?

    Body::

        { "ai_correct": true | false, "model_version": "…" }   // version optional

    ``ai_correct`` must be a REAL boolean. The string "true" is a 400, not a
    coercion — this is training data, and a coerced value is a fabricated
    label indistinguishable from a real one afterwards (the same rule the
    coach confidence-label route holds).

    ``model_version`` records WHICH prediction was validated. Omitted → the
    currently-shadowed version is stamped server-side, because "the AI got
    this right" is meaningless without knowing which AI.

    Replace-on-reflag: one row per (snippet_id, reviewer_user_id). A reviewer
    who changes their mind updates their row; duplicate rows from one rater
    are junk labels (N3, same as the voice game). Different reviewers keep
    their own rows so peer agreement stays computable.

    NOT owner-scoped, deliberately — this is PEER review, so the reviewer is
    frequently not the speaker. ``require_auth`` + a real snippet is the gate;
    the unique constraint is what stops one account stuffing the corpus.

    Responses::

        200 { "saved": true, "snippet_id": ..., "ai_correct": ... }
        400 INVALID_INPUT — bad UUID / non-boolean ai_correct / bad
                            model_version type
        404 NOT_FOUND     — snippet doesn't exist
        500 V2_ERROR

    AC-9: capture only. Nothing here is ever read back to a user as a score,
    verdict or ratio. BLIND COACH: these flags are NON-BLIND (the reviewer saw
    the AI's call) and are stored in their own table under their own
    provenance so they can never blend indistinguishably into the coach's
    blind corpus — see migrations/add_snippet_confidence_reviews.sql.
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "snippet_id must be a valid UUID",
        }), 400

    from services.confidence_reviews import validate_confidence_review

    row, err = validate_confidence_review(request.get_json(silent=True) or {})
    if err:
        return jsonify({"code": "INVALID_INPUT", "error": err}), 400

    try:
        if not db.get_snippet_by_id(snippet_id):
            return jsonify({
                "code": "NOT_FOUND", "error": "snippet not found",
            }), 404

        model_version = row["model_version"]
        if not model_version:
            # Attribute the prediction server-side. Best-effort: an
            # unattributed row is still a usable verdict, so a registry read
            # that fails must never cost us the label.
            try:
                from services.learning_serve import current_shadow_version
                model_version = current_shadow_version()
            except Exception as e:
                logger.warning(
                    "confidence_review: shadow version lookup failed snip=%s: "
                    "%s (storing unattributed)", snippet_id, e,
                )
                model_version = None

        saved = db.upsert_snippet_confidence_review(
            snippet_id=snippet_id,
            reviewer_user_id=str(request.user_id),
            ai_correct=row["ai_correct"],
            model_version=model_version,
        )
        if not saved:
            return jsonify({
                "code": "V2_ERROR",
                "error": "could not save the review (run "
                         "migrations/add_snippet_confidence_reviews.sql)",
            }), 500

        return jsonify({
            "saved": True,
            "snippet_id": snippet_id,
            "ai_correct": row["ai_correct"],
        }), 200
    except Exception as e:
        logger.error(
            "confidence_review.error snip=%s err=%s", snippet_id, e,
            exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to record the confidence review",
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
            # PUBLIC endpoint (no auth) — the exception text describes the
            # token scheme and its TTL, which is a free hint to anyone
            # probing the signature. Detail to the log, not the link page.
            logger.info("unsubscribe: expired token: %s", e)
            return jsonify({
                "code": "INVALID_TOKEN",
                "error": "This unsubscribe link has expired.",
            }), 401
        except UnsubscribeTokenInvalid as e:
            logger.info("unsubscribe: invalid token: %s", e)
            return jsonify({
                "code": "INVALID_TOKEN",
                "error": "This unsubscribe link is invalid.",
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
    # Local import on purpose: binds at CALL time, so tests that monkeypatch
    # services.coach_video_storage attributes take effect.
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
        db.set_funnel_config("afterwards_video_url", video_url)

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


# The regenerate endpoint's 60s-per-session double-click guard now lives
# in services/rate_limits.py::regenerate_limit (decorated below) — same
# window, same force bypass, but counted in the shared Redis instead of a
# per-worker dict, so a second click landing on a second worker no longer
# buys a second LLM call.


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
@llm_limit
@regenerate_limit
@require_admin
def v2_admin_regenerate_next_session_icebreaker(session_id):
    """Re-run the LLM to produce a fresh icebreaker.

    DESTRUCTIVE: per FE handoff Q3, regenerate blows away any
    admin edit on both columns — fresh ai_draft AND fresh current.
    FE owns the confirm modal.

    Rate-limited to one call per session per minute (shared across
    workers) unless ``{"force": true}`` is in the body. The cap
    exists to keep an admin's accidental double-click from doubling
    our LLM cost, not as a security boundary.

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
        # Existence check — match the PUT behavior of returning 404
        # before any DB writes when the session is gone. The regenerate
        # window was already spent by @regenerate_limit, which deducts
        # on the way IN — so a slow (or hanging) LLM call still counts
        # against the limit and an admin mashing the button during one
        # can't queue up parallel duplicates.
        row_before = db.get_next_session_icebreaker_row(session_id)
        if not row_before:
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found",
            }), 404

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
@llm_limit
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
@llm_limit
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
@llm_limit
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
@heavy_limit
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
@llm_limit
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
@llm_limit
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
