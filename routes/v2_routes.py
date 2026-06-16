"""
V2 routes: admin CRUD + the willab learner flow (Lab/Readout/Insights,
Lounge, Library, profile). All /v2/admin/* require auth + admin.
(The legacy homework student flow was removed in the Phase-5 clearance.)
"""
from flask import Blueprint, request, jsonify, make_response
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

logger = logging.getLogger(__name__)
v2_bp = Blueprint("v2", __name__, url_prefix="/v2")
config = Config()


def _is_valid_uuid(val):
    import re
    return bool(re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', str(val or ''), re.I))


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


def _client_ip_from_request() -> str:
    """Best-effort client IP. Trusts X-Forwarded-For first (Railway/CDN), then remote_addr."""
    xff = (request.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        # First entry is the original client per RFC 7239 conventions.
        return xff.split(",")[0].strip() or (request.remote_addr or "0.0.0.0")
    return request.remote_addr or "0.0.0.0"


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

_INTERVIEW_QUESTIONS_FALLBACK = {
    "charisma": [
        "Tell us, in your own words: do you think you're a good communicator? Why?",
        "What's something you're genuinely passionate about?",
        "Describe a moment in your life or career that you're really proud of.",
        "If you could teach anyone one thing, what would it be and why?",
        "What's the best piece of advice you've ever received?",
        "What makes you unique compared to other people in your field?",
    ],
    "stress": [
        "What's your biggest professional weakness, and how does it show up day-to-day?",
        "Describe a time you completely failed at something that mattered to you.",
        "If I told you your communication style sometimes puts people off, how would you respond?",
        "Explain a complex topic from your field as if you're talking to a 10-year-old.",
        "What would your harshest critic say about you — and would they be right?",
        "Tell me about a decision you made that you still regret.",
    ],
}

_INTERVIEW_SYSTEM_PROMPT = """You are an interview coach conducting a voice charisma assessment.
Your job is to ask questions that alternate between two tones:

1. CHARISMA-PROVOKING questions: These let the interviewee shine — topics where they can show passion, storytelling ability, warmth, and vocal energy. Examples: achievements, passions, advice they'd give.

2. STRESS-PROVOKING questions: These are challenging, slightly uncomfortable, or technical — designed to test how the person handles pressure, pauses, and uncertainty. Examples: failures, weaknesses, defending a controversial stance.

RULES:
- You MUST alternate tones: if the previous question was charisma, the next MUST be stress, and vice versa.
- Keep questions concise (1-2 sentences max).
- Never repeat a question you've already asked in this session.
- You must dynamically build upon a specific element from the user's most recent answer to challenge them further. DO NOT parrot or awkwardly repeat their words back to them. Push the conversation forward contextually.
- Never break character or explain what you're doing.
- FORMATTING RULE: If you include a brief acknowledgment or validation before your question,
  separate it from the question using the exact delimiter `|||`.
  Example: `That was a vivid story! ||| Now tell me about a time you completely failed at something that mattered to you.`
  If there is no acknowledgment, return ONLY the question text with no delimiter.

LANGUAGE HANDLING — English-only with a one-shot disclaimer:
- You always speak ENGLISH, regardless of the language the user uses. Do NOT mirror, translate into, or switch to the user's language.
- The FIRST time in this conversation that you detect the user has spoken a language other than English (e.g. Polish, Spanish, French, etc.), prepend EXACTLY this disclaimer as the acknowledgment segment before your next question, separated by `|||`:
  "I only speak English, but feel free to continue in your native language! The acoustic analysis will still be completed perfectly."
  Example: `I only speak English, but feel free to continue in your native language! The acoustic analysis will still be completed perfectly. ||| Tell me about a moment when…`
- Inspect the conversation history before issuing this disclaimer. If you have ALREADY issued it once in this session (look for the exact phrase in your prior turns), do NOT repeat it — just continue with your next question in English.
- After the disclaimer fires, immediately continue with your normal coaching agenda (in English).

IDENTITY & PERSONA — graceful pivot, never get stuck:
- If the user asks about your identity, name, whether you're real, human, or an AI (e.g. "Who are you?", "Are you real?", "What is your name?", "Am I talking to a bot?"), respond with a brief, graceful acknowledgment IMMEDIATELY followed by your next coaching question, separated by `|||`.
  Example: `I am your AI coaching chatbot! But let's get back to it... ||| Tell me about the toughest decision you've ever had to defend.`
- Never give a long, robotic AI disclaimer. Never let the conversation get stuck on your identity.
- On repeat identity probes within the same session, shorten the acknowledgment further (or drop it entirely) and pivot straight back to the coaching agenda. You are always in control of the dialogue flow.
"""

from services.skills import (
    get_skill as _get_skill,
    list_skill_ids as _list_skill_ids,
    resolve_for_snippet as _skill_for_snippet,
)


# Phase 7 — the registry in services/skills/ is the source of truth
# for which intents the contextual /chat flow accepts. The literal
# {"charisma", "stress"} that used to live here is gone; adding a
# skill is now a package-level change, not a route-level edit.
_CONTEXTUAL_INTENTS = _list_skill_ids()

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


def _build_few_shot_block(
    *,
    intent: str,
    exclude_snippet_id: str | None = None,
    limit: int = 3,
    viewer_user_id: str | None = None,
) -> str:
    """Render the top-N high-scoring past exchanges as a system-prompt
    preamble for contextual question generation.

    Pulls from db.get_top_followup_examples which returns charisma_snippets
    rows whose follow_up_outcome.score is at least min_score. Each example
    is rendered with four pieces of context:
      - the original user transcript (the moment the coach annotated)
      - the coach's insight
      - the question that was asked
      - the user's actual answer + the evaluator's score

    When ``viewer_user_id`` is provided AND Config.FEW_SHOT_TENANT_SCOPED
    is on, retrieval is scoped to the viewer's company (joined via
    user_settings.company_id) plus any 'canonical' rows. Otherwise the
    legacy cross-tenant retrieval is preserved exactly. Every call
    writes one row to ``few_shot_retrievals`` for compliance + Phase 1
    pool-depth telemetry.

    Returns an empty string when no qualifying examples exist (early
    days of the loop, before enough outcomes have accumulated) — the
    caller is responsible for handling the empty case.

    Example budget: we trim each field to a sane character cap so a
    handful of long transcripts can't blow the context window. The
    examples block typically lands in the 400-1200 char range.
    """
    examples = db.get_top_followup_examples(
        intent,
        limit=limit,
        exclude_snippet_id=exclude_snippet_id,
        viewer_user_id=viewer_user_id,
    )
    if not examples:
        return ""

    def _truncate(s: str | None, cap: int) -> str:
        text = (s or "").strip()
        if not text:
            return ""
        if len(text) <= cap:
            return text
        return text[:cap].rstrip() + "…"

    chunks: list[str] = [
        "Below are examples of past coaching follow-ups that the user "
        "actually engaged with deeply (each scored highly by an automated "
        "evaluator). Study the STYLE of the questions: specific, somatic, "
        "concrete, non-leading. Use the SAME style when you generate the "
        "new question further down."
    ]
    for i, ex in enumerate(examples, start=1):
        outcome = ex.get("follow_up_outcome") or {}
        evaluator = (outcome.get("evaluator") or {}) if isinstance(outcome, dict) else {}
        score_raw = outcome.get("score") if isinstance(outcome, dict) else None
        try:
            score_pct = int(round(float(score_raw) * 100))
        except (TypeError, ValueError):
            score_pct = 0
        question = (
            ex.get("follow_up_question")
            or (outcome.get("question_text") if isinstance(outcome, dict) else None)
            or ""
        )
        user_answer = (
            (outcome.get("user_answer") or {}).get("text")
            if isinstance(outcome, dict)
            else None
        ) or ""
        chunks.append(
            f"\nEXAMPLE {i} (score: {score_pct}/100)\n"
            f"Original moment: \"{_truncate(ex.get('transcript'), 240)}\"\n"
            f"Coach insight:   \"{_truncate(ex.get('admin_comment'), 200)}\"\n"
            f"Question asked:  \"{_truncate(question, 200)}\"\n"
            f"User responded:  \"{_truncate(user_answer, 280)}\""
        )
    return "\n".join(chunks)


def _build_longitudinal_context_block(
    *,
    snippet_id: str | None,
    user_id: str | None,
) -> str | None:
    """Phase 15 — assemble per-user longitudinal context for the
    first-question prompt of a contextual /chat click.

    Returns a multi-section string ready to splice into the system
    prompt, or None when no signal is available for this user.

    Sections (each independently optional):

      [LEARNER PROFILE]              — behavioral_profile + recurring
                                       themes from inferred profile,
                                       layered with any admin override.
      [RECENT REFLECTION]            — current_learner_mirror narrative
                                       (truncated to 600 chars so it
                                       doesn't dominate the prompt).
      [PRIOR ATTEMPTS ON THIS MOMENT]— last 3 coaching_attempts for
                                       this snippet+user, with the
                                       questions previously asked so
                                       the LLM avoids repeating
                                       angles and acknowledges
                                       progress.

    Failure modes swallow + log — a partial block is better than
    blocking the first-question generation. Returns None when ALL
    three sections come back empty (caller falls through to the
    pre-Phase-15 behaviour).
    """
    if not user_id or not snippet_id:
        return None

    sections: list[str] = []
    settings: dict = {}

    # ── Learner profile section removed in the excision (sniper
    # behavioral_profile + learner_profile inferred themes no longer
    # inject). settings still loaded for the sections below. ───────
    try:
        settings = db.get_user_settings(user_id) or {}
    except Exception as e:
        logger.warning(
            "first-question: settings load failed user=%s err=%s",
            user_id, e,
        )

    # ── Recent reflection (mirror) ────────────────────────────────
    try:
        mirror = (settings or db.get_user_settings(user_id) or {}).get(
            "current_learner_mirror"
        ) or {}
        narrative = (mirror.get("narrative") or "").strip() if isinstance(mirror, dict) else ""
        if narrative:
            if len(narrative) > 600:
                narrative = narrative[:600].rstrip() + "…"
            sections.append(f"[RECENT REFLECTION]\n{narrative}")
    except Exception as e:
        logger.warning(
            "first-question: mirror load failed user=%s err=%s",
            user_id, e,
        )

    # ── Prior sessions: archetype + recent admin coaching notes ──
    # Cross-session memory. The infinite-flywheel UX is "each loop
    # is wiser than the last" — the LLM should see what archetype
    # the user landed on in their previous session(s) and what the
    # admin has been telling them, so the new opening question
    # builds on (not repeats) that thread.
    try:
        prior_sessions = (
            db.v2_get_published_sessions_for_user(user_id) or []
        )
        last_session = prior_sessions[0] if prior_sessions else None

        archetype: str | None = None
        if isinstance(last_session, dict):
            cp = last_session.get("charisma_profile") or {}
            if isinstance(cp, dict):
                archetype = (cp.get("archetype") or "").strip() or None

        # Pull the most recent admin coaching notes the user has
        # received across ALL their published snippets. We cap at 3
        # so the LLM has continuity without the prompt ballooning.
        recent_notes: list[str] = []
        try:
            note_rows = (
                db.client.table("charisma_snippets")
                .select("admin_comment, created_at, session_id")
                .eq("user_id", user_id)
                .not_.is_("admin_comment", "null")
                .order("created_at", desc=True)
                .limit(8)
                .execute()
                .data
            ) or []
            for r in note_rows:
                # Exclude the snippet the user is currently working
                # on — the parent prompt already has its admin_comment.
                if r.get("session_id") and r.get("session_id") == snippet_id:
                    continue
                note = (r.get("admin_comment") or "").strip()
                if not note:
                    continue
                if len(note) > 180:
                    note = note[:180].rstrip() + "…"
                recent_notes.append(note)
                if len(recent_notes) >= 3:
                    break
        except Exception as note_err:
            logger.warning(
                "first-question: recent admin notes load failed "
                "user=%s err=%s", user_id, note_err,
            )

        if archetype or recent_notes:
            lines = ["[PRIOR SESSIONS]"]
            if archetype:
                lines.append(
                    f"Last session's archetype read: {archetype}. "
                    "Use this as a continuity anchor — acknowledge "
                    "the trajectory, don't restart from zero."
                )
            if recent_notes:
                lines.append(
                    "Recent admin coaching notes (most-recent first):"
                )
                for note in recent_notes:
                    lines.append(f"  • {note}")
                lines.append(
                    "Build on these threads — do NOT repeat advice "
                    "the admin already gave; probe the next layer."
                )
            sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(
            "first-question: prior-sessions load failed user=%s err=%s",
            user_id, e,
        )

    # ── Prior attempts on THIS snippet ────────────────────────────
    try:
        attempts = db.list_coaching_attempts_for_snippet(
            snippet_id, user_id=user_id,
        ) or []
        # list_coaching_attempts_for_snippet returns chronological
        # (attempt_number ASC) — last 3 means the most recent three.
        recent = attempts[-3:] if attempts else []
        question_lines: list[str] = []
        for a in recent:
            q = (a.get("question_text") or "").strip()
            if not q:
                continue
            if len(q) > 200:
                q = q[:200].rstrip() + "…"
            question_lines.append(f"  - {q}")
        if question_lines:
            lines = ["[PRIOR ATTEMPTS ON THIS MOMENT]"]
            lines.append(
                f"The user has already worked through these "
                f"{len(question_lines)} angle(s) on THIS snippet:"
            )
            lines.extend(question_lines)
            lines.append(
                "Open with ONE sentence acknowledging their progress "
                "(\"You've already worked the X angle…\"), then ask a "
                "NEW question that probes a different dimension — "
                "emotion if they covered mechanics, mechanics if they "
                "covered emotion, the people involved if they covered "
                "the situation, etc. DO NOT repeat any prior question's "
                "angle."
            )
            sections.append("\n".join(lines))
    except Exception as e:
        logger.warning(
            "first-question: prior attempts load failed "
            "snippet=%s user=%s err=%s",
            snippet_id, user_id, e,
        )

    if not sections:
        return None
    return "\n\n".join(sections)


def _generate_llm_question(
    turn_number: int,
    tone: str,
    previous_turns: list | None = None,
    user_id: str | None = None,
    *,
    contextual_init: dict | None = None,
    timeout_seconds: float | None = None,
    baseline_objective: str | None = None,
    conversation_summary: str | None = None,
) -> str | None:
    """Call GPT-4o-mini to generate the next interview question.

    Falls back to the hardcoded bank on failure.
    Returns the question text, or None on error (caller uses fallback).

    timeout_seconds — Phase 13. When set, the OpenAI call is bounded
    by this wall-clock budget. Used by the smart-EBCP-bypass path so
    a stalled LLM doesn't keep a returning user staring at a blank
    chat; the caller catches None and substitutes the scripted EBCP
    turn 1 as a safety net.

    baseline_objective — Directed-freestyle pivot. When the caller
    supplies a per-turn objective string (turns 1-4 for users with
    baseline_established=False), it's spliced into the system prompt
    as a [CURRENT_TURN_OBJECTIVE] block so the LLM has a concrete
    psychological target for THIS turn (icebreaker, empathy,
    pressure, quick reflex) rather than freelancing across the four
    onboarding turns. Returning users get None and the prompt
    falls back to standard alternation.

    conversation_summary — Phase A2.1 rolling digest. When passed,
    replaces the quadratic-cost full-history replay: the prompt
    gets the digest as a context block + only the last 2 raw
    turns in chat history. NULL on the very first turn (cold-
    start) or when the async summary writer hasn't caught up; the
    prompt builder degrades to using all of previous_turns in
    that case so we never serve a turn with NO context.
    """
    try:
        from services.openai_service import OpenAIService
        import openai

        service = OpenAIService()
        if not service.client:
            return None

        # Special: contextual "retention loop" init question (single deepening question)
        if contextual_init and int(turn_number or 1) == 1:
            intent = (contextual_init.get("intent") or "").strip().lower()
            transcript = (contextual_init.get("transcript") or "").strip()
            admin_comment = (contextual_init.get("admin_comment") or "").strip()
            source_snippet_id = contextual_init.get("source_snippet_id")
            # Transcript is OPTIONAL — the publish gate only demands
            # admin_comment, so we mirror that here. When transcript
            # is empty the base prompt below substitutes a neutral
            # "the user just recorded a moment" phrasing so the LLM
            # still has a coherent setup.
            if intent in _CONTEXTUAL_INTENTS and admin_comment:
                # ── Few-shot retrieval ──────────────────────────────
                # Pull the top-scoring past exchanges with the SAME intent
                # so the model is anchored on wording that historically
                # produced specific, emotionally-rich answers. Falls
                # silent when there aren't enough labeled outcomes yet
                # (no examples block in the prompt, model generates
                # purely from the current snippet's context).
                few_shot_block = _build_few_shot_block(
                    intent=intent,
                    exclude_snippet_id=source_snippet_id,
                    # Phase 1 tenant scoping flows through the caller's
                    # user_id so retrieval can JOIN through
                    # user_settings.company_id. When None (background
                    # script, internal caller), the legacy path runs.
                    viewer_user_id=user_id,
                )

                # ── Phase 15 longitudinal context ───────────────────
                # When enabled, splice in learner-profile + mirror +
                # prior attempts on THIS snippet so the LLM stops
                # producing the same opener on every click. Gated by
                # LONGITUDINAL_FIRST_QUESTION_ENABLED so deploy is a
                # no-op until the operator flips it; falls silent if
                # the user has no signal yet (cold-start unaffected).
                longitudinal_block: str | None = None
                try:
                    from config import Config
                    if Config().LONGITUDINAL_FIRST_QUESTION_ENABLED:
                        longitudinal_block = _build_longitudinal_context_block(
                            snippet_id=source_snippet_id,
                            user_id=user_id,
                        )
                except Exception as long_err:
                    logger.warning(
                        "first-question: longitudinal block failed: %s",
                        long_err,
                    )

                # ── Phase 16 baseline insight ───────────────────────
                # Pre-baked digest of the user's EBCP turns 1-4. Read
                # from the cache only — we don't compute here because
                # this is the contextual /chat path, not the
                # interview funnel where compute happens at turn 5.
                # Gated by BASELINE_SUMMARY_ENABLED.
                baseline_block: str | None = None
                try:
                    from config import Config
                    if Config().BASELINE_SUMMARY_ENABLED and user_id:
                        summary = db.get_user_baseline_summary(user_id)
                        if summary:
                            from services.baseline_summary import (
                                format_baseline_for_prompt,
                            )
                            baseline_block = format_baseline_for_prompt(summary)
                except Exception as bs_err:
                    logger.warning(
                        "first-question: baseline block failed: %s",
                        bs_err,
                    )

                # When transcript is missing (Whisper miss / extracted
                # highlight without a captured slice), fall back to a
                # neutral framing that grounds the LLM in the coach
                # insight alone. The "What did the user say" line is
                # built once so both branches share the substitution.
                if transcript:
                    moment_line = f"In that recording, they said: '{transcript}'."
                else:
                    moment_line = (
                        "We don't have a transcript of the exact words, "
                        "but the coach flagged this moment specifically."
                    )

                if intent == "charisma":
                    base = (
                        "You are a coaching assistant. "
                        "The user clicked 'Understand your charisma' on a past recording. "
                        f"{moment_line} "
                        f"The human coach commented: '{admin_comment}'. "
                        "Respond with two parts: (1) a brief warm acknowledgment of this specific moment, "
                        "then (2) ONE deepening question to help them deconstruct WHY they felt so confident "
                        "and how they can replicate it. "
                        "FORMATTING RULE: Separate the acknowledgment from the question using the exact "
                        "delimiter `|||`. "
                        "Example: `That moment you described is exactly where charisma lives! ||| "
                        "What were you thinking about right before you said that?` "
                        "Return ONLY these two parts separated by `|||`, nothing else."
                    )
                else:
                    base = (
                        "You are a coaching assistant. "
                        "The user clicked 'Release your stress'. "
                        f"{moment_line} "
                        f"The human coach commented: '{admin_comment}'. "
                        "Respond with two parts: (1) a brief empathetic acknowledgment of this moment, "
                        "then (2) ONE deepening question to help them identify the root cause of that "
                        "specific stress spike. "
                        "FORMATTING RULE: Separate the acknowledgment from the question using the exact "
                        "delimiter `|||`. "
                        "Example: `That sounds like a genuinely pressured moment. ||| "
                        "What was the thing you most feared would go wrong right then?` "
                        "Return ONLY these two parts separated by `|||`, nothing else."
                    )

                # Few-shot examples first (anchors wording), then
                # Phase 16 baseline insight (who this user is from
                # their EBCP run), then Phase 15 longitudinal context
                # (recent attempts on this snippet + recurring
                # entities), then the base task description.
                #
                # Order matters: the LLM should read who-this-user-is
                # BEFORE the imperative task block. Baseline (stable
                # identity) comes before longitudinal (recent state)
                # so the model anchors on identity and adapts on
                # recent — not the other way around.
                prompt_parts: list[str] = []
                if few_shot_block:
                    prompt_parts.append(few_shot_block)
                if baseline_block:
                    prompt_parts.append(baseline_block)
                if longitudinal_block:
                    prompt_parts.append(longitudinal_block)
                prompt_parts.append(base)
                system_prompt = "\n\n".join(prompt_parts)

                # Phase 15 / 16 — bump temperature when ANY user-
                # specific context is in play (longitudinal block OR
                # the Phase 16 baseline insight) so even identical
                # raw inputs produce verbal variety. Falls back to
                # the legacy 0.7 when both blocks are empty
                # (preserves cold-start behaviour byte-for-byte).
                ctx_temperature = (
                    0.85
                    if (longitudinal_block or baseline_block)
                    else 0.7
                )

                response = service.client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[{"role": "system", "content": system_prompt}],
                    max_tokens=180,
                    temperature=ctx_temperature,
                )
                question = response.choices[0].message.content.strip()
                if question.startswith('"') and question.endswith('"'):
                    question = question[1:-1]
                return question if question else None

        # Build system prompt with optional user-specific injection
        system_prompt = _INTERVIEW_SYSTEM_PROMPT
        if user_id:
            system_prompt = _augment_interview_prompt_with_profile(
                system_prompt, user_id,
            )
            # Phase 16 — splice in the pre-baked baseline digest so
            # the LLM doesn't redo extraction + generation in one
            # call. Flag-gated; falls through silently when the
            # summary hasn't been computed yet (cold-start users or
            # admin resets that haven't graduated again).
            try:
                from config import Config
                if Config().BASELINE_SUMMARY_ENABLED:
                    summary = db.get_user_baseline_summary(user_id)
                    if summary:
                        from services.baseline_summary import (
                            format_baseline_for_prompt,
                        )
                        baseline_block = format_baseline_for_prompt(summary)
                        if baseline_block:
                            system_prompt = (
                                f"{system_prompt}\n\n{baseline_block}"
                            )
            except Exception as bs_err:
                logger.warning(
                    "interview: baseline_summary inject failed "
                    "user=%s err=%s", user_id, bs_err,
                )

        # ── Phase A2.1 — rolling conversation summary ───────────────
        # Splice order (pitfall #7 in the learning-loop spec —
        # augmentation order is load-bearing, later blocks get more
        # model attention):
        #
        #   1. base interview prompt
        #   2. profile / [LEARNER PROFILE] (existing)
        #   3. baseline_summary (Phase 16, stable identity)
        #   4. conversation_summary (THIS BLOCK — per-session digest)
        #   5. baseline_objective ([CURRENT_TURN_OBJECTIVE], per-turn
        #      directive — stays last so it anchors the generate step)
        #
        # The summary goes BETWEEN baseline (stable user identity) and
        # baseline_objective (per-turn imperative) because it's
        # per-session ephemera that's more recent than baseline but
        # less imperative than the current-turn directive. Keeping
        # baseline_objective last preserves its anchoring effect.
        if conversation_summary:
            try:
                from services.conversation_summary import (
                    format_summary_for_prompt,
                )
                summary_block = format_summary_for_prompt(conversation_summary)
                if summary_block:
                    system_prompt = (
                        f"{system_prompt}\n\n{summary_block}"
                    )
            except Exception as sum_err:
                logger.warning(
                    "interview: conversation_summary splice failed "
                    "(continuing without): %s", sum_err,
                )

        # Directed-freestyle objective for the 4 onboarding turns.
        # When the caller passes a baseline_objective, the LLM gets
        # a hard psychological target for THIS turn instead of free-
        # styling across the onboarding phase. Goes AFTER the
        # profile/baseline/summary blocks so identity context is
        # read first, then the per-turn directive is the last
        # instruction the model sees before "generate" — anchoring
        # effect on the response.
        if baseline_objective:
            system_prompt = (
                f"{system_prompt}\n\n[CURRENT_TURN_OBJECTIVE]\n"
                f"{baseline_objective.strip()}\n\n"
                "Build a one-question scenario that delivers the "
                "objective above. Stay in the interview-coach voice. "
                "Do NOT explain the objective to the user — just ask "
                "the question."
            )

        # Build conversation history for context.
        # Phase A2.1: when a conversation_summary is in play, the
        # digest covers the older turns and we only need the LAST 2
        # raw turns for short-range fidelity (the model gets
        # "what was JUST said" verbatim, longer-range memory from
        # the summary block above). When no summary exists yet
        # (cold-start), fall back to replaying ALL previous_turns
        # so the first few turns don't lose context.
        messages = [{"role": "system", "content": system_prompt}]

        if previous_turns:
            turns_to_render = (
                previous_turns[-2:]
                if conversation_summary
                else previous_turns
            )
            for turn in turns_to_render:
                messages.append({"role": "assistant", "content": turn.get("question", "")})
                if turn.get("transcript"):
                    messages.append({"role": "user", "content": turn["transcript"]})

        # Request next question
        messages.append({
            "role": "user",
            "content": f"Generate the next question. This is turn {turn_number}. Required tone: {tone}.",
        })

        # Phase 13 — optional per-call timeout for the bypass-EBCP
        # path. The OpenAI Python SDK accepts a ``timeout`` kwarg on
        # the request that maps to httpx; if it isn't honoured for
        # some reason the outer try/except still catches the slow
        # call and falls back to the scripted EBCP turn 1.
        create_kwargs = {
            "model": "gpt-4o-mini",
            "messages": messages,
            "max_tokens": 150,
            "temperature": 0.8,
        }
        if timeout_seconds is not None:
            create_kwargs["timeout"] = float(timeout_seconds)
        response = service.client.chat.completions.create(**create_kwargs)

        question = response.choices[0].message.content.strip()
        # Strip quotes if the LLM wrapped it
        if question.startswith('"') and question.endswith('"'):
            question = question[1:-1]
        return question if question else None

    except Exception as e:
        logger.warning("_generate_llm_question failed (will use fallback): %s", e)
        return None


@v2_bp.route("/user/results/<session_id>", methods=["GET"])
@require_auth
def v2_user_get_results(session_id):
    """User results endpoint for /results dual-state page.

    Always returns { session_id, status }. Status is determined by:
      - results_published_at IS NOT NULL → "completed" (admin has reviewed & published)
      - otherwise → "processing"

    When completed, payload includes all non-skipped snippets with their
    metrics, admin_comment, snippet_type, and audio URLs.

    Optional query param ``include_contrast=true`` (Phase
    Stress-Contrast / BE-3) attaches a ``contrast`` field powered
    by ``db.compute_stress_contrast``: median deltas between the
    user's last 5 published snippets ("official / high-stakes")
    and their last 5 casual voice benchmarks captured during
    /v2/chat/query. ``contrast`` is None when either side has
    fewer than 3 samples; the frontend uses None to omit the card
    entirely (do not render a placeholder).
    """
    try:
        if not _is_valid_uuid(session_id):
            return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a valid UUID"}), 400

        user_id = request.user_id
        session = db.v2_get_session(session_id, user_id)
        if not session:
            return jsonify({"code": "NOT_FOUND", "error": "Session not found"}), 404

        # BE-3: stress contrast is opt-in via query param so callers
        # that don't render the dashboard section don't pay for two
        # extra table reads. Cheap when included (≤10 indexed rows
        # per side) but still gated for hygiene.
        include_contrast = (
            (request.args.get("include_contrast") or "")
            .strip()
            .lower()
            in ("1", "true", "yes")
        )

        # Dual-state: admin must explicitly publish before user sees results
        is_published = bool(session.get("results_published_at"))
        status = "completed" if is_published else "processing"

        payload = {
            "session_id": str(session_id),
            "status": status,
            "created_at": session.get("created_at"),
        }

        if status == "completed":
            snippets = db.v2_get_results_snippets_for_session(session_id, user_id)
            # Shape each snippet for frontend consumption.
            #
            # IMPORTANT: audio_url comes from _resolve_snippet_audio_url
            # (NOT the raw audio_segment_path column) so:
            #   - Concat'd session snippets (storage_path =
            #     session_recordings/<sid>/full.webm) get the R2 audio
            #     bucket public URL — playable directly in the
            #     <audio> tag without RLS / signing dance.
            #   - Student / Path-C rows (storage_path =
            #     charisma_snippets/<uuid>) get a short-lived Supabase
            #     signed URL.
            #   - Legacy rows (audio_segment_path = an absolute URL)
            #     fall through to that URL.
            # The previous version returned audio_segment_path verbatim,
            # which was NULL for every auto_extracted snippet — so the
            # /results page rendered un-playable cards.
            #
            # start_offset_ms ships too so the frontend can clamp
            # playback when audio_url points at a concat'd full.webm.
            payload["snippets"] = [
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
                for s in snippets
            ]
            # Include session-level summary if available.
            # Phase 18.x split-sinks Option A — prefer the immutable
            # AI draft over the editable column so admin's narrative
            # edits don't leak to the user. Legacy fallback when the
            # draft column is NULL.
            payload["ai_summary"] = (
                session.get("session_kpi_narrative_ai_draft")
                or session.get("ai_task_alignment_comment")
            )
            payload["ai_score"] = session.get("ai_task_alignment_score")

        # ── BE-3 Stress Contrast ─────────────────────────────────────
        # Gated by ?include_contrast=true. Computed across the WHOLE
        # user (last 5 published snippets vs last 5 casual chat
        # benchmarks), not just this session — that's the point: the
        # delta is a per-user trait, not a per-session one. Surface
        # it on the same payload so the dashboard renders it in the
        # session-review view without a second round-trip.
        #
        # Returns None when either pool has <3 samples; the frontend
        # treats None as "omit the section entirely" (do NOT render
        # a 'not enough data' placeholder — see FE Prompt 3 C7).
        if include_contrast:
            try:
                payload["contrast"] = db.compute_stress_contrast(user_id)
            except Exception as contrast_err:
                # Aggregator failure must not break the rest of the
                # results payload. Log and surface None so the FE
                # uniformly handles "no contrast available".
                logger.warning(
                    "user/results: stress contrast failed user=%s "
                    "session=%s err=%s",
                    user_id, session_id, contrast_err,
                )
                payload["contrast"] = None

        return jsonify(payload), 200

    except Exception as e:
        logger.error("user/results failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch results"}), 500


def _metrics_ready(session: dict) -> bool:
    """Task-8 mirror — has the compute-metrics / finalize chain
    populated the session-level aggregates yet?

    Marker is ``global_wpm`` because it's set atomically with the
    other globals in ``compute_session_global_metrics`` and is
    NEVER set by any other write path. Any of global_fillers,
    global_pause_ms etc. would work equivalently; wpm is the
    canonical "metrics computed" signal.

    Returns False for sessions where compute-metrics hasn't run
    yet (the user is still in the "processing" phase from the FE's
    chat-phase router).
    """
    return session.get("global_wpm") is not None


def _derive_session_status(session: dict, snippet_counts: dict) -> str:
    """Compute a single user-facing status string from the raw session row.

    Status values map to the frontend routing decisions on /results:
        no_session     — user has zero sessions (caller handles)
        processing     — recording exists but ML hasn't extracted snippets yet
        pending_review — snippets exist, admin still labelling / writing comments
        completed      — admin has clicked "Publish Results" (results_published_at set)
        error          — recording_1_processing_status is "failed"

    The transitions are deliberately one-way for the user-facing surface:
    pending_review never goes back to processing once snippets exist; if the
    admin un-publishes a session we leave it as pending_review.
    """
    if session.get("results_published_at"):
        return "completed"

    rec_status = (session.get("recording_1_processing_status") or "").lower()
    if rec_status == "failed":
        return "error"

    total_snippets = snippet_counts.get("total", 0)
    if total_snippets > 0:
        # Snippets have been extracted; we're now waiting on the admin
        # human-in-the-loop review. Note: we don't gate on
        # `with_admin_comment > 0` here because a session can be
        # legitimately published with no comments (rare but allowed).
        return "pending_review"

    # No snippets yet — still in the ML extraction / processing phase.
    return "processing"


@v2_bp.route("/user/sessions/current", methods=["GET"])
@require_auth
def v2_user_sessions_current():
    """Rich session-state surface for post-auth routing decisions.

    Replaces the narrow /user/results/latest by exposing every column the
    frontend needs to decide where to send a freshly-authenticated user
    (record screen, processing/waiting screen, results page) without
    multiple round-trips.

    Returns 200 with:
        {
            "has_session": bool,
            "session_id": str | None,
            "status": "no_session" | "processing" | "pending_review"
                    | "completed" | "error",
            "metrics_ready": bool,         # Phase Task-8 mirror — true once
                                            # global_metrics has been populated
                                            # (compute-metrics ran OR finalize
                                            # chain populated them)
            "snippets_published": bool,    # mirrors results_published_at IS NOT NULL
            "has_recordings": bool,
            "turn_count": int,             # interview turns answered (rec'd snippets)
            "snippet_count": int,          # total non-skipped snippets
            "published_snippet_count": int,# snippets the admin has commented on
            "results_published_at": str | None,
            "recording_processing_status": str | None,  # raw ML pipeline state
            "created_at": str | None
        }

    The metrics_ready / snippets_published booleans are intentionally
    compositional (per the task-8 handoff reply) so a future "partial
    publish" or "metrics-recompute-in-flight" state can be expressed
    without churning the enum. FE switches the chat-phase router on
    the booleans, not the enum.

    The endpoint NEVER returns mock data. When the user has no sessions the
    response is { has_session: false, status: "no_session", ...zeros }.
    """
    try:
        user_id = request.user_id
        session = db.v2_get_latest_session_for_user(user_id)

        if not session:
            return jsonify({
                "has_session": False,
                "session_id": None,
                "status": "no_session",
                "metrics_ready": False,
                "snippets_published": False,
                "has_recordings": False,
                "turn_count": 0,
                "snippet_count": 0,
                "published_snippet_count": 0,
                "results_published_at": None,
                "recording_processing_status": None,
                "created_at": None,
            }), 200

        session_id = str(session.get("id"))
        snippet_counts = db.v2_count_session_snippets(session_id)
        status = _derive_session_status(session, snippet_counts)

        # `has_recordings` is true iff the session has a bound recording.
        # We check the recording_1 link rather than counting rows on the
        # recordings table — same answer, one fewer query.
        has_recordings = bool(session.get("recording_1_id"))

        return jsonify({
            "has_session": True,
            "session_id": session_id,
            "status": status,
            "metrics_ready": _metrics_ready(session),
            "snippets_published": bool(session.get("results_published_at")),
            "has_recordings": has_recordings,
            # Each charisma_snippet row corresponds to one interview turn
            # the user actually answered, so total snippet count == turn count.
            "turn_count": snippet_counts.get("total", 0),
            "snippet_count": snippet_counts.get("total", 0),
            "published_snippet_count": snippet_counts.get("with_admin_comment", 0),
            "results_published_at": session.get("results_published_at"),
            "recording_processing_status": session.get("recording_1_processing_status"),
            "created_at": session.get("created_at"),
        }), 200

    except Exception as e:
        logger.error("user/sessions/current failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch session state"}), 500


@v2_bp.route(
    "/user/sessions/<session_id>/intake-context",
    methods=["GET"],
)
@require_auth
def v2_user_get_session_intake_context(session_id):
    """Read the per-session speech-context intake block (Task 9).

    Backs the FE's "tell us about this talk" form — FE GETs on
    form-open to prefill a returning user's draft. Always returns
    200 with explicit nulls when unset; "no answers yet" is nulls,
    not 404 (the session row exists, the column is just null).

    Owner-scoped: non-owner gets 404 (not 403) to avoid existence
    leak. Same pattern as the session-summary endpoint.

    Response 200::

        {
          "topic":                 str | null,
          "audience":              str | null,
          "target_length_seconds": int | null
        }

      400 INVALID_INPUT       — bad UUID
      404 SESSION_NOT_FOUND   — session doesn't exist OR not owner
      500 V2_ERROR            — unexpected
    """
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "session_id must be a valid UUID",
        }), 400

    try:
        session = db.v2_get_session_by_id(session_id)
        if not session or str(
            session.get("user_id") or ""
        ) != str(request.user_id):
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found",
            }), 404

        ctx = session.get("intake_context")
        if not isinstance(ctx, dict):
            ctx = {}
        return jsonify({
            "topic": ctx.get("topic"),
            "audience": ctx.get("audience"),
            "target_length_seconds": ctx.get("target_length_seconds"),
            "domain_vocabulary": ctx.get("domain_vocabulary"),
        }), 200

    except Exception as e:
        logger.error(
            "user/sessions/<id>/intake-context GET failed sid=%s err=%s",
            session_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to fetch intake context",
        }), 500


@v2_bp.route(
    "/user/sessions/<session_id>/intake-context",
    methods=["PUT"],
)
@require_auth
def v2_user_put_session_intake_context(session_id):
    """Full-replace write of the intake-context blob (Task 9).

    FE owns the draft and PUTs the whole 3-field form on submit —
    partial updates are out of scope (matches the spec's "full
    replace" decision). Empty body {} is valid and clears the
    column back to {topic: null, audience: null, target_length_
    seconds: null}.

    Validation (services.intake_context.validate_intake_context_body):
      - topic, audience: optional str, trimmed, ≤200 chars; empty-
        after-trim collapses to null
      - target_length_seconds: optional int in [30, 7200]
      - bools rejected as integers

    No gating: PUT is accepted on warmup / Session-1 sessions too
    (per the spec — no Session-1 check by design).

    Response 200: same shape as GET (echoes the persisted state).

      400 INVALID_INPUT       — body malformed / out-of-range / wrong type
      404 SESSION_NOT_FOUND   — session doesn't exist OR not owner
      500 V2_ERROR            — unexpected DB failure
    """
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "session_id must be a valid UUID",
        }), 400

    try:
        from services.intake_context import (
            IntakeContextError,
            validate_intake_context_body,
        )
        try:
            # willab §3.2 / invariant §5.10 — session_context REQUIRES
            # a topic; BE rejects empty (not trusted to FE).
            ctx = validate_intake_context_body(
                request.get_json(silent=True) or {},
                require_topic=True,
            )
        except IntakeContextError as ve:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": str(ve),
            }), 400

        session = db.v2_get_session_by_id(session_id)
        if not session or str(
            session.get("user_id") or ""
        ) != str(request.user_id):
            return jsonify({
                "code": "SESSION_NOT_FOUND",
                "error": "Session not found",
            }), 404

        ok = db.set_session_intake_context(session_id, ctx)
        if not ok:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to persist intake context",
            }), 500

        logger.info(
            "user/sessions/intake-context.put user=%s sid=%s fields=%s",
            request.user_id, session_id,
            sorted(k for k, v in ctx.items() if v is not None),
        )
        return jsonify(ctx), 200

    except Exception as e:
        logger.error(
            "user/sessions/<id>/intake-context PUT failed sid=%s err=%s",
            session_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to update intake context",
        }), 500


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


def _augment_interview_prompt_with_profile(
    base_prompt: str,
    user_id: str,
) -> str:
    """Phase 13 — soft profile injection for the interview-question generator.

    Appends a [COACHING CONTEXT] block with the user's effective
    learner type + admin's global LLM instructions. Adds a stability
    directive telling the model to USE the profile to shape tone
    without becoming locked-in by it ("still probe beyond their
    stated strengths"). Custom instructions remain available as the
    legacy ADDITIONAL INSTRUCTIONS block so the existing wording
    admins typed in keeps applying.

    Failure modes swallow — a missing settings row or DB hiccup
    returns the base prompt unchanged so question generation never
    hard-fails on profile load.
    """
    admin_instructions = ""
    dont_ask_notes = ""
    settings: dict = {}
    try:
        settings = db.get_user_settings(user_id) or {}
        admin_instructions = (
            settings.get("custom_llm_instructions") or ""
        ).strip()
        dont_ask_notes = (
            settings.get("private_admin_notes") or ""
        ).strip()
    except Exception as e:
        logger.warning(
            "interview: settings load failed user=%s: %s", user_id, e,
        )

    # Old-subsystem learner-type (sniper behavioral_profile) injection
    # removed in the excision — willab no longer classifies a learner type.

    # ── Phase 17 — Master Score (B6) block ───────────────────────
    # Pulls the most recent session's persisted kpi_score / global
    # acoustic aggregates and renders them as a tight
    # [PERFORMANCE METRICS] block. Anti-parrot directive can now
    # cite concrete numbers ("your pace landed at 145 wpm, well in
    # band, but your dynamic range came in low") rather than
    # generic shape. Falls silent when no recent session has
    # measurements — protects cold-start users from a misleading
    # "your score" line in the prompt.
    metrics_block: str | None = None
    try:
        metrics_block = _build_master_score_block(user_id)
    except Exception as e:
        logger.warning(
            "interview: master-score block failed user=%s: %s", user_id, e,
        )

    # ── Phase 12.x — private admin notes → don't-ask block ───────
    # Surfaces user_settings.private_admin_notes as a "topics to
    # navigate around" instruction. Same DB read above already
    # pulled the column from the settings dict; render via the
    # shared helper so all four chat surfaces use identical wording.
    from services.utils import render_admin_dont_ask_block
    dont_ask_block = render_admin_dont_ask_block(dont_ask_notes)

    if (
        not admin_instructions
        and not metrics_block and not dont_ask_block
    ):
        return base_prompt

    block_lines = ["", "[COACHING CONTEXT]"]
    if admin_instructions:
        block_lines.append(f"Admin Notes: {admin_instructions}")
    block_lines.append("")
    block_lines.append(
        "Directive: Use this profile to shape your challenge style and "
        "tone, but DO NOT become trapped by it. You must still probe "
        "beyond their stated strengths and test their boundaries under "
        "pressure."
    )

    augmented = base_prompt + "\n" + "\n".join(block_lines)

    if metrics_block:
        augmented += "\n\n" + metrics_block

    # Keep the legacy verbatim block as well — admins relying on the
    # old "ADDITIONAL INSTRUCTIONS FOR THIS USER" wording in their
    # user_settings.custom_llm_instructions content still see it
    # surface unchanged.
    if admin_instructions:
        augmented += (
            "\n\nADDITIONAL INSTRUCTIONS FOR THIS USER:\n"
            f"{admin_instructions}"
        )

    # Don't-ask block goes LAST so it's the final framing the model
    # sees before the user message. Strongest position for negative
    # constraints in practice.
    if dont_ask_block:
        augmented += "\n\n" + dont_ask_block

    return augmented


def _build_master_score_block(user_id: str) -> str | None:
    """Phase 17 — render the user's latest B6 Master Score for the LLM.

    Source: the most recent v2_sessions row that has computed
    metrics. Surfaces kpi_score (B7, the persisted 0..100 score),
    plus the global acoustic averages that fed it, plus the
    stickiness topic (C4) when present.

    Returns None when no recent session has metrics — better to
    omit the block than to print "—" placeholders the LLM would
    parrot back at the user.

    Uses the LATEST session's data on purpose: the next interview
    question is FORWARD-looking from the user's last completed run,
    not their lifetime average. If we ever want a lifetime view, it
    belongs in a separate block (e.g. learner profile).
    """
    if not user_id:
        return None
    try:
        latest = db.v2_get_latest_published_session_for_user(user_id) or {}
    except Exception as e:
        logger.warning(
            "master-score-block: session load failed user=%s: %s", user_id, e,
        )
        return None
    if not latest:
        return None

    kpi = latest.get("kpi_score")
    g_wpm = latest.get("global_wpm")
    g_fillers = latest.get("global_fillers")
    g_dynamic = latest.get("global_dynamic_db")
    g_pitch = latest.get("global_pitch_center")
    g_pause = latest.get("global_pause_ms")
    sticky_topic = (latest.get("stickiness_top_topic") or "").strip() or None

    # Nothing measurable on the latest session — bail rather than
    # render a hollow block.
    if all(v is None for v in (kpi, g_wpm, g_fillers, g_dynamic, g_pitch, g_pause)):
        return None

    lines: list[str] = [
        "[PERFORMANCE METRICS — from this user's most recent session]"
    ]
    if isinstance(kpi, (int, float)):
        lines.append(f"Master score (KPI, 0-100): {round(float(kpi), 1)}")
    if isinstance(g_wpm, (int, float)):
        lines.append(f"Pace: {round(float(g_wpm), 1)} WPM (target band 120-160)")
    if isinstance(g_fillers, (int, float)):
        lines.append(f"Fillers across session: {int(g_fillers)}")
    if isinstance(g_dynamic, (int, float)):
        lines.append(f"Dynamic range: {round(float(g_dynamic), 1)} dB")
    if isinstance(g_pitch, (int, float)):
        lines.append(f"Pitch centre: {round(float(g_pitch), 1)} st")
    if isinstance(g_pause, (int, float)):
        lines.append(f"Average pause: {round(float(g_pause), 0)} ms")
    if sticky_topic:
        lines.append(f"Sticky topic last session: {sticky_topic}")
    lines.append("")
    lines.append(
        "Directive: cite ONE specific metric above when it would "
        "ground your question — e.g. \"your pace ran at 175 WPM in "
        "the last session, so this time...\". Do NOT recite the "
        "whole block; pick the most coachable number for THIS turn."
    )
    return "\n".join(lines)


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


@v2_bp.route("/user/chat/first-question", methods=["POST"])
@require_auth
def v2_user_chat_first_question():
    """Start a contextual chat by generating the first AI question.

    Query params (any one spelling accepted, see comment below):
      - sourceSnippetId / sourceSnippet / source_snippet_id  (UUID)
      - intent: charisma|stress
    """
    try:
        user_id = request.user_id
        # Defensive param read: the frontend /chat page URL has used
        # `sourceSnippet` while the backend canonical name is
        # `sourceSnippetId`. A mismatch causes the contextual init
        # to silently fall through to the cold-start interview path
        # ("Are you good at math?"). Accept all three spellings so a
        # one-side-only deploy can never reintroduce that bug —
        # whichever key the BFF forwards, we resolve it.
        source_snippet_id = (
            request.args.get("sourceSnippetId")
            or request.args.get("sourceSnippet")
            or request.args.get("source_snippet_id")
            or ""
        ).strip() or None
        intent = (request.args.get("intent") or "").strip().lower() or None

        # ── Admin overrides (priority order) ────────────────────────
        # 1) coaching_directives_queue — new user-level 5-step arc.
        #    Pop the lowest-position un-exhausted row, mark exhausted.
        #    Wins over contextual snippet flow, stored follow-up, and
        #    the dynamic LLM. Phase Directives-Queue (BE).
        #
        # Legacy queued_override_question (single-question override
        # via PUT /v2/admin/user/<id>/context) was removed in the
        # Week-1 cleanup. The directives-queue is the single admin
        # override path now. Old data in user_settings.queued_
        # override_question persists in the DB but is ignored.
        directive = db.pop_next_directive(user_id)
        if directive:
            logger.info(
                "first_question.directives_queue_hit user=%s pos=%s "
                "intent=%s",
                user_id, directive.get("position"),
                directive.get("intent_tag"),
            )
            return jsonify({
                "status": "ok",
                "question": directive.get("question"),
                "source": "directives_queue",
                "directive": {
                    "position": directive.get("position"),
                    "intent_tag": directive.get("intent_tag"),
                },
            }), 200

        # ── 2) Task 10 — next-session icebreaker (soft-queue read).
        # Cold-start path only: if a sourceSnippet/intent is provided
        # the user came in via the snippet-deep-dive CTA, not a fresh
        # session opener, and the icebreaker should be saved for a
        # true new-session entry. Marks the source row 'delivered'
        # atomically with the read (mirrors pop_next_directive's
        # mark-exhausted pattern).
        #
        # Priority slot: AFTER directives_queue (admin always wins),
        # BEFORE contextual_init / dynamic LLM.
        if not (source_snippet_id or intent):
            icebreaker_payload = db.pop_pending_icebreaker_for_user(
                user_id,
            )
            if icebreaker_payload:
                logger.info(
                    "first_question.icebreaker_hit user=%s "
                    "source_sid=%s",
                    user_id,
                    icebreaker_payload.get("source_session_id"),
                )
                return jsonify({
                    "status": "ok",
                    "question": icebreaker_payload.get("question"),
                    "source": "prev_session_icebreaker",
                    "icebreaker": {
                        "source_session_id": icebreaker_payload.get(
                            "source_session_id",
                        ),
                    },
                }), 200

        contextual_init = None
        if source_snippet_id or intent:
            if not (source_snippet_id and intent):
                return jsonify({"code": "INVALID_INPUT", "error": "sourceSnippetId and intent must be provided together"}), 400
            if not _is_valid_uuid(source_snippet_id):
                return jsonify({"code": "INVALID_INPUT", "error": "sourceSnippetId must be a valid UUID"}), 400
            if intent not in _CONTEXTUAL_INTENTS:
                return jsonify({"code": "INVALID_INPUT", "error": "intent must be 'charisma' or 'stress'"}), 400

            snippet = db.v2_get_charisma_snippet_for_user(source_snippet_id, user_id)
            if not snippet:
                return jsonify({"code": "NOT_FOUND", "error": "Snippet not found"}), 404

            # ── Infinite Retention Trigger: use stored follow_up_question first ──
            # The admin pre-generated (and may have hand-edited) this question when
            # labeling the snippet. Serving it directly avoids latency at click time
            # and ensures the admin's wording is used verbatim.
            stored_follow_up = (snippet.get("follow_up_question") or "").strip()
            if stored_follow_up:
                return jsonify({
                    "status": "ok",
                    "question": stored_follow_up,
                    "source": "stored_follow_up",
                }), 200

            # No pre-stored question → fall back to dynamic LLM generation.
            #
            # Gate alignment fix: the publish gate
            # (v2_get_results_snippets_for_session) requires only
            # admin_comment NOT NULL — transcript is optional there.
            # If we hard-fail here on missing transcript we break the
            # CTA on snippets that the admin legitimately published
            # (e.g. when Whisper missed a 5s slice). Soften: require
            # only admin_comment. The LLM still has the coach insight
            # to anchor on; transcript is forwarded as empty and the
            # base prompt handles that case.
            transcript = (
                (snippet.get("transcript") or "")
                or (snippet.get("transcription_text") or "")
                or (snippet.get("transcript_text") or "")
                or (snippet.get("transcript_excerpt") or "")
            ).strip()
            admin_comment = (snippet.get("admin_comment") or "").strip()
            if not admin_comment:
                return jsonify({
                    "code": "SNIPPET_CONTEXT_UNAVAILABLE",
                    "error": "Snippet admin_comment is not available yet",
                }), 422
            if not transcript:
                logger.info(
                    "first-question: snippet has no transcript, proceeding "
                    "with admin_comment only snippet=%s user=%s",
                    source_snippet_id, user_id,
                )

            contextual_init = {
                "intent": intent,
                "transcript": transcript,
                "admin_comment": admin_comment,
                # Forwarded so the few-shot retrieval doesn't echo this
                # exact snippet back as one of its own examples.
                "source_snippet_id": source_snippet_id,
            }

        # Generate the first question dynamically
        tone = "charisma" if (intent != "stress") else "stress"
        question = _generate_llm_question(
            turn_number=1,
            tone=tone,
            previous_turns=None,
            user_id=user_id,
            contextual_init=contextual_init,
        )
        if not question:
            # Phase 7 — first-question fallback lives on the Skill
            # object so it stays consistent with the rest of that
            # skill's tone. Defaults to stress's question when the
            # intent doesn't resolve.
            fallback_skill = _get_skill(intent) or _get_skill("stress")
            if fallback_skill is not None:
                question = fallback_skill.contextual_first_question

        return jsonify({
            "status": "ok",
            "question": question,
            "source": "llm_generated",
        }), 200

    except Exception as e:
        logger.error("user/chat/first-question failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to generate first question"}), 500


_SELF_RATING_RE = re.compile(
    r"\b(10|[1-9]|one|two|three|four|five|six|seven|eight|nine|ten)\b",
    re.IGNORECASE,
)
_SELF_RATING_WORD_MAP: dict[str, int] = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
# Phase 8 self-rating: bound the free-text payload so an abusive
# client can't ship megabytes through the endpoint. The frontend
# input is the chat composer (typically <200 chars).
_SELF_RATING_TEXT_MAX = 500


def _parse_self_rating_from_text(text: str) -> int | None:
    """Pull a 1..10 integer out of a free-form user reply.

    Accepts digits ("8", "10") and English number words ("eight",
    "ten") case-insensitively. Returns the FIRST 1-10 number found,
    or None when nothing matches.

    Examples:
      "8"              → 8
      "I'd say 8"      → 8
      "9/10"           → 9
      "eight"          → 8
      "TEN"            → 10
      "8 out of 10"    → 8
      "11"             → None (digit out of range; word_boundary kills it)
      "ten and a half" → 10
      ""               → None
    """
    if not text:
        return None
    m = _SELF_RATING_RE.search(text)
    if not m:
        return None
    token = m.group(1).strip().lower()
    if token in _SELF_RATING_WORD_MAP:
        return _SELF_RATING_WORD_MAP[token]
    try:
        n = int(token)
        return n if 1 <= n <= 10 else None
    except (TypeError, ValueError):
        return None


def _first_self_rating(attempts: list[dict]) -> int | None:
    """First chronological self-rating present in ``attempts``.

    Used by /coaching/progress to show first → best progression.
    Attempts are already ordered by attempt_number ASC when the
    progress endpoint builds them.
    """
    for a in attempts:
        r = a.get("self_rating")
        if isinstance(r, int) and 1 <= r <= 10:
            return r
    return None


def _best_self_rating(attempts: list[dict]) -> int | None:
    """Highest self-rating across ``attempts``. None when no attempt has one."""
    ratings = [
        a.get("self_rating") for a in attempts
        if isinstance(a.get("self_rating"), int)
        and 1 <= a.get("self_rating") <= 10
    ]
    return max(ratings) if ratings else None


@v2_bp.route("/user/coaching/self-rating", methods=["POST"])
@require_auth
def v2_user_coaching_self_rating():
    """Capture the user's in-chat 1..10 self-rating for a coaching attempt.

    Phase 8 of the snippet-CTA learning loop. After the LLM evaluation
    lands in coaching_attempts (Phase 2), the frontend asks the user
    "on a scale of 1-10, how do you feel about that response?" inside
    the chat thread and POSTs the reply here.

    Body (any of these shapes works; ``rating`` wins when both are set)::

        { "snippet_id": "<uuid>", "rating": 8 }
        { "snippet_id": "<uuid>", "rating_text": "I'd say 8" }
        { "snippet_id": "<uuid>", "rating_text": "8", "attempt_number": 3 }

    ``attempt_number`` is optional — when omitted we target the most
    recent attempt for this (snippet, user). That is the common path
    because the rating ask follows the latest evaluation in the chat.

    Status codes:
      200 — rating accepted; response carries the persisted row.
      400 — input invalid (missing snippet_id, can't parse a 1..10).
      404 — snippet not owned by the requesting user.
      425 — no coaching_attempts row exists yet (race with the
            evaluation daemon). Client should retry after a beat.
      500 — unexpected error.
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

        attempt_number = body.get("attempt_number")
        if attempt_number is not None:
            try:
                attempt_number = int(attempt_number)
                if attempt_number < 1:
                    raise ValueError
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "attempt_number must be a positive integer",
                }), 400

        rating_text_raw = (body.get("rating_text") or "")
        if not isinstance(rating_text_raw, str):
            rating_text_raw = str(rating_text_raw)
        rating_text = rating_text_raw[:_SELF_RATING_TEXT_MAX].strip() or None

        # rating wins when both shapes are sent — it's the explicit
        # numeric path the frontend uses when it already parsed the
        # number client-side.
        rating_val = body.get("rating")
        rating: int | None = None
        if rating_val is not None:
            try:
                rating = int(rating_val)
            except (TypeError, ValueError):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "rating must be an integer 1..10",
                }), 400
        elif rating_text:
            rating = _parse_self_rating_from_text(rating_text)

        if rating is None or not (1 <= rating <= 10):
            return jsonify({
                "code": "RATING_UNPARSEABLE",
                "error": "Could not read a number from 1 to 10 in the reply",
            }), 400

        # Owner check — block users from rating someone else's snippet.
        snippet = db.v2_get_charisma_snippet_for_user(snippet_id, user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        updated = db.update_coaching_attempt_self_rating(
            snippet_id=snippet_id,
            user_id=user_id,
            rating=rating,
            rating_text=rating_text,
            attempt_number=attempt_number,
        )
        if not updated:
            # No row found for (snippet, user[, attempt_number]).
            # Most likely cause: the eval daemon hasn't finished
            # writing the coaching_attempts row yet. 425 (Too Early)
            # tells the client to retry shortly.
            return jsonify({
                "code": "ATTEMPT_NOT_READY",
                "error": (
                    "No coaching attempt found for this snippet yet. "
                    "Wait a moment and retry."
                ),
            }), 425

        return jsonify({
            "status": "ok",
            "snippet_id": snippet_id,
            "attempt_number": updated.get("attempt_number"),
            "self_rating": updated.get("self_rating"),
            "self_rating_text": updated.get("self_rating_text"),
            "self_rating_submitted_at": updated.get("self_rating_submitted_at"),
        }), 200

    except Exception as e:
        logger.error("user/coaching/self-rating failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save self-rating",
        }), 500


@v2_bp.route("/user/consent", methods=["GET", "PUT"])
@require_auth
def v2_user_consent():
    """Unified consent surface for the four prompted moments.

    Returns / accepts the four boolean consent flags the frontend
    surfaces during onboarding: mic-access, share-voice-clone,
    email-notifications, and Terms-of-Service acceptance. The first
    three are runtime preferences stored on user_settings; the
    fourth reads the immutable user_consents ledger against
    ``Config.CURRENT_TERMS_VERSION`` so the historical audit trail
    stays intact (we never UPDATE the ledger, only INSERT a new row
    on re-accept).

    Response shape (200, both GET and PUT)::

        {
          "has_answered":           bool,    # true once any flag
                                              # has been answered
          "mic_consent":            true|false|null,
          "mic_consent_set_at":     "ISO8601"|null,
          "share_consent":          true|false|null,
          "share_consent_set_at":   "ISO8601"|null,
          "email_consent":          true|false|null,
          "email_consent_set_at":   "ISO8601"|null,
          "terms_consent":          bool,     # true iff a
                                               # user_consents row
                                               # at the current
                                               # terms_version exists
          "terms_version_current":  "1.0",
          "terms_version_accepted": "1.0"|null,
          "terms_accepted_at":      "ISO8601"|null
        }

    NULL semantics:
      • mic/share/email = NULL  ⇒ user has never been asked. The
        frontend uses this to decide whether to surface the prompt
        in the first place. has_answered also stays false until at
        least one is non-NULL (or the user has accepted terms).
      • mic/share/email = true / false ⇒ user has explicitly
        answered. *_set_at is stamped at the moment of the answer.
      • terms_consent is computed, not stored on user_settings —
        it's a boolean derived from the ledger lookup.

    PUT body — every field is optional; only included keys are
    written (PATCH-style semantics)::

        {
          "mic_consent":   true | false | null,
          "share_consent": true | false | null,
          "email_consent": true | false | null,
          "terms_consent": true      # ONLY true is accepted —
                                      # accepting terms inserts a
                                      # ledger row at the current
                                      # version. false / null are
                                      # rejected since the ledger
                                      # is append-only and you
                                      # cannot un-accept.
        }

    Setting mic/share/email to null is a valid "clear" — the
    preference column goes back to NULL and the frontend re-prompts
    on the next visit. set_at is also cleared.

    Setting terms_consent=true is idempotent — if the user already
    has a row at the current version, no new row is written and
    the existing terms_accepted_at is preserved (the underlying
    upsert uses on_conflict=do_nothing).

    Responses:
      200 — full state echoed back (single round trip on PUT)
      400 INVALID_INPUT — bad body shape or terms_consent not true
      500 V2_ERROR / PERSIST_FAILED — DB hiccup
    """
    user_id = request.user_id

    try:
        if request.method == "PUT":
            body = request.get_json(silent=True)
            if not isinstance(body, dict):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "Request body must be a JSON object",
                }), 400

            # Validate the three runtime flags. None is a valid
            # "clear"; anything other than bool/None is rejected.
            def _validate(key: str):
                if key not in body:
                    return False, None
                value = body[key]
                if value is None or isinstance(value, bool):
                    return True, value
                return None, None  # signals invalid

            mic_present, mic_val = _validate("mic_consent")
            if mic_present is None:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "mic_consent must be true, false, or null",
                }), 400
            share_present, share_val = _validate("share_consent")
            if share_present is None:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "share_consent must be true, false, or null",
                }), 400
            email_present, email_val = _validate("email_consent")
            if email_present is None:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "email_consent must be true, false, or null",
                }), 400

            # Terms is append-only: only `true` is meaningful. We
            # reject `false`/`null` explicitly so callers don't
            # quietly assume they can rescind acceptance via this
            # endpoint (compliance: the ledger has no concept of
            # "un-accept" and the audit row stays once written).
            terms_consent_write = False
            if "terms_consent" in body:
                tc = body["terms_consent"]
                if tc is not True:
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": (
                            "terms_consent only accepts true (accept "
                            "current terms). The legal ledger is "
                            "append-only — false/null are not valid."
                        ),
                    }), 400
                terms_consent_write = True

            # Persist the three runtime preferences first; terms
            # second so a terms-write failure doesn't leave the
            # frontend thinking it landed when only the prefs did.
            ok = db.set_user_consent_preferences(
                user_id=user_id,
                mic=mic_val,
                share=share_val,
                email=email_val,
                update_mic=bool(mic_present),
                update_share=bool(share_present),
                update_email=bool(email_present),
            )
            if not ok:
                return jsonify({
                    "code": "PERSIST_FAILED",
                    "error": (
                        "Could not save consent preferences. "
                        "Please retry."
                    ),
                }), 500

            if terms_consent_write:
                ip = (
                    request.headers.get("X-Forwarded-For", "")
                    .split(",")[0]
                    .strip()
                    or request.remote_addr
                )
                ua = request.headers.get("User-Agent")
                ledger_row = db.record_user_consent(
                    user_id=user_id,
                    terms_version=config.CURRENT_TERMS_VERSION,
                    ip_address=ip,
                    user_agent=ua,
                )
                if ledger_row is None:
                    return jsonify({
                        "code": "PERSIST_FAILED",
                        "error": (
                            "Could not record terms acceptance. "
                            "Please retry."
                        ),
                    }), 500

            # Fall through to the GET read-back so the response is
            # always the full current state — caller doesn't need a
            # follow-up fetch.

        state = db.get_user_consent_state(
            user_id,
            current_terms_version=config.CURRENT_TERMS_VERSION,
        )
        return jsonify(state), 200

    except Exception as e:
        logger.error(
            "user/consent %s failed: %s",
            request.method, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to load consent state",
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
          ]
        }

    Responses::

        200 {
              "answer":         str,    # the chat bubble text
              "bubbles":        [str],  # pre-split chat bubbles (FE #157)
              "show_record_ui": bool,   # per-turn record affordance
                                         # toggle (RULE I) — in-app mic
              "suggested_action": str | None,  # the one contextual button
              "debug":          {...}   # model + history_used / error
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

        if not isinstance(question, str) or not question.strip():
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "question must be a non-empty string",
            }), 400

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
                    return jsonify({
                        "answer": _gu["answer"],
                        "bubbles": split_answer_into_bubbles(_gu["answer"]),
                        "show_record_ui": False,
                        "suggested_action": None,
                        "debug": {
                            "intent": "goal_update",
                            "new_goal": _gu.get("new_goal"),
                        },
                    }), 200
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
        if request.user_id:
            try:
                from services.audit_intent import handle_audit_intent
                from services.master_doc_rag import split_answer_into_bubbles
                _ai = handle_audit_intent(request.user_id, question.strip())
                if _ai and _ai.get("suggested_action") == "audit":
                    _ans = _ai.get("answer") or ""
                    return jsonify({
                        "answer": _ans,
                        "bubbles": split_answer_into_bubbles(_ans),
                        "show_record_ui": False,
                        "suggested_action": "audit",
                        "debug": {"intent": "audit"},
                    }), 200
            except Exception as _ae:
                logger.warning(
                    "chat/query: audit intercept failed user=%s: %s",
                    request.user_id, _ae,
                )

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
        return jsonify({
            "answer": _answer,
            # FE #157 — pre-split chat bubbles (renders 1:1; falls back to
            # splitting `answer` on blank lines when absent). `answer` stays
            # the fallback.
            "bubbles": split_answer_into_bubbles(_answer),
            "show_record_ui": bool(payload.get("show_record_ui", False)),
            "suggested_action": _sa,
            "debug": debug,
        }), 200

    except Exception as e:
        logger.error("chat/query failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Chat query failed",
        }), 500


@v2_bp.route("/user/snippets/<snippet_id>/label", methods=["POST"])
@require_auth
def v2_user_snippet_label(snippet_id):
    """Capture the user's self-confirmation of a snippet's
    charismatic read (the chat state machine's "Would you label
    your voice here as Charismatic? Yes / No" beat).

    RLHF signal. Paired with ``coach_label`` (admin annotation),
    the (admin, user) tuple is the training pair we export later:
    when the user disagrees with the admin, that's the moment the
    classifier most needs to learn from.

    Body::

        { "label": true | false }
        // OR, equivalent alias for symmetry with the sibling
        // /v2/chat/snippet-followup endpoint:
        { "user_label": true | false }
        // If BOTH keys are present, ``label`` wins (canonical).

    Responses::

        200 { "status": "ok", "snippet_id": ..., "user_charisma_label": ... }
        400 INVALID_INPUT — bad UUID / non-bool label / both keys missing
        404 NOT_FOUND     — snippet doesn't exist or isn't owned by
                            this user
        500 V2_ERROR

    Owner-scoped at both the route level (require_auth + the
    db.set_user_snippet_charisma_label filter on user_id) so a
    user can't write to someone else's row even if they guess the
    snippet UUID.
    """
    try:
        if not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        body = request.get_json(silent=True) or {}
        # Canonical field is "label"; "user_label" is an alias kept
        # in sync with the sibling /v2/chat/snippet-followup endpoint
        # so the frontend can use one consistent body shape across
        # both labeling-related calls. If both are present, the
        # canonical name wins.
        label = body.get("label")
        if label is None:
            label = body.get("user_label")
        # Strict bool — accept True/False only. The frontend
        # ActionBubble emits one of those two; anything else (None,
        # int, string "yes" / "charisma") signals a malformed call
        # we want to surface rather than coerce.
        if not isinstance(label, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": (
                    "label (or user_label) must be a boolean "
                    "(true or false)"
                ),
            }), 400

        user_id = request.user_id
        updated = db.set_user_snippet_charisma_label(
            snippet_id=snippet_id,
            user_id=str(user_id),
            label=label,
        )
        if not updated:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found or not owned by user",
            }), 404

        return jsonify({
            "status": "ok",
            "snippet_id": snippet_id,
            "user_charisma_label": updated.get("user_charisma_label"),
            "user_charisma_label_set_at": updated.get(
                "user_charisma_label_set_at"
            ),
        }), 200

    except Exception as e:
        logger.error(
            "user_snippet_label.error err=%s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to record snippet label",
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
        # ── willab credits — charge 1 on send-SUCCESS, first flip only ──
        # (UX Wave v2 C2). already_sent==True is a re-claim/retry/OAuth-
        # callback no-op → never re-charge. The lab_credits_charged_at flag
        # is the real exactly-once guard (all paths resolve to one sid), so
        # this is belt-and-suspenders. Seed the 15-grant before the first
        # spend. Best-effort: a credit hiccup must never unwind a sent slot.
        if not send_result.get("already_sent"):
            try:
                db.v2_ensure_credits_initialized(str(user_id))
                db.v2_charge_lab_credits_once(sid, str(user_id), amount=1)
            except Exception as _ce:
                logger.warning(
                    "willab_lab: credit charge failed sid=%s err=%s (non-fatal)",
                    sid, _ce,
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

    # ── User nudge: Lounge "insights ready" card (best-effort, idempotent). ──
    try:
        from datetime import datetime as _dt, timezone as _tz
        _owner = (db.v2_get_session_by_id(session_id) or {}).get("user_id")
        if _owner:
            db.insert_lounge_messages(str(_owner), [{
                "client_id": str(uuid.uuid5(
                    uuid.NAMESPACE_URL, f"willab-insight:{session_id}",
                )),
                "role": "bot",
                "kind": "insight",
                "body": "Your coach's insights are ready.",
                "metadata": {
                    "session_id": session_id, "insight_ref": session_id,
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

    # ── willab credits — charged at SEND now, NOT publish (UX Wave v2). ──
    # The 1-credit charge relocated to send-success (_willab_send_response →
    # db.v2_charge_lab_credits_once), so publish no longer touches the ledger.
    # The per-session lab_credits_charged_at flag keeps it exactly-once.

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


def _resolve_snippet_audio_url(snippet: dict) -> str | None:
    """Pick a playable audio URL from whichever column the writer used.

    The four snippet states we have to play through one <audio> element:
      - Path A pre-finalize: audio_segment_path = R2 public URL for the
        per-turn .webm, storage_path NULL.
      - Path A post-finalize: storage_path = bucket-relative key of the
        concat'd session full.webm (Supabase Storage). audio_segment_path
        is left intact (historical record + idempotent re-finalize), but
        storage_path is what start_offset_ms / duration_ms are RELATIVE TO,
        so it must win.
      - Path B (extract_recording_snippets): audio_segment_path = full URL,
        storage_path NULL.
      - Path C (charisma_snippet_service) and student uploads: storage_path
        set, audio_segment_path NULL.

    Precedence is therefore: storage_path → audio_segment_path → None.
    Returning None means there's truly nothing playable. Keeping
    audio_segment_path as the fallback (rather than the primary) is what
    makes the per-turn → canonical-recording migration safe — the moment
    finalize_session_recording populates storage_path, the snippet flips
    from playing its per-turn file to playing a slice of the concat'd
    session audio, no DB cleanup required.
    """
    storage = (snippet.get("storage_path") or "").strip()
    if storage:
        # Two classes of storage_path coexist:
        #   - "session_recordings/<sid>/full.webm" and
        #     "guest_funnel/<sid>/turn_N.webm" — interview audio in R2,
        #     served via the audio bucket's public base URL.
        #   - "charisma_snippets/<uuid>" — student-uploaded clips in
        #     Supabase Storage, served via signed URLs.
        # Disambiguate by prefix. Anything that isn't a known
        # Supabase-only prefix is assumed to be audio-bucket content.
        is_supabase_prefix = storage.startswith("charisma_snippets/")
        if not is_supabase_prefix:
            try:
                from services.audio_storage import audio_public_url
                url = audio_public_url(storage)
                if url:
                    return url
            except Exception as e:
                logger.warning(
                    "snippet audio URL: R2 audio URL build failed for %s: %s",
                    storage, e,
                )
            # R2_AUDIO_PUBLIC_BASE_URL not set (local dev) — fall through
            # to the Supabase signed-URL path so dev still works.
        try:
            return db.create_signed_url(
                config.AUDIO_BUCKET_NAME, storage, config.SIGNED_URL_EXPIRY_SECONDS
            )
        except Exception as e:
            logger.warning(
                "snippet audio URL: signed url failed for %s: %s — falling back",
                storage, e,
            )
            # fall through to audio_segment_path
    seg = (snippet.get("audio_segment_path") or "").strip()
    if seg:
        return seg
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


# ── Chat-surface consent flags (Phase Single-Slot-Chat) ──────────
#
# GET / PUT /v2/user/sharing-consent — four-flag fan-out (Option A
# from the BE prompt). Each flag corresponds to one YesNoPills
# consent moment in the chat funnel:
#   mic_consent    — microphone permission
#   share_consent  — share recorded snippets with the human coach
#   email_consent  — receive weekly progress emails
#   terms_consent  — accept Terms & Privacy
#
# Storage: nullable booleans on user_settings (added by
# migrations/add_consent_flags_to_user_settings.sql). NULL = not
# yet answered → FE shows the prompt for that slot. TRUE/FALSE =
# answered.
#
# Legacy ``opt_in`` alias (response echo + PUT body acceptance)
# was removed in the Week-1 cleanup. The four canonical fields
# above are the only contract now. Stragglers that PUT ``opt_in``
# get a warning log and the field is silently ignored.

_CONSENT_FIELDS_FE = (
    "mic_consent",
    "share_consent",
    "email_consent",
    "terms_consent",
)


def _shape_consent_response(state: dict) -> dict:
    """Compose the GET/PUT response body from a consent state
    dict (as returned by ``db.get_consent_state``).

    has_answered = any of the four is non-null. FE uses it as a
    coarse "has the user been through the funnel at all" check;
    per-moment gating uses the individual fields.
    """
    has_answered = any(
        state.get(field) is not None
        for field in _CONSENT_FIELDS_FE
    )
    out = {
        "has_answered": has_answered,
        "mic_consent": state.get("mic_consent"),
        "share_consent": state.get("share_consent"),
        "email_consent": state.get("email_consent"),
        "terms_consent": state.get("terms_consent"),
    }
    return out


@v2_bp.route("/user/sharing-consent", methods=["GET"])
@require_auth
def v2_user_get_sharing_consent():
    """Return the user's four-flag consent state.

    Response 200::

        {
          "has_answered": bool,
          "mic_consent":   bool | null,
          "share_consent": bool | null,
          "email_consent": bool | null,
          "terms_consent": bool | null
        }
    """
    try:
        state = db.get_consent_state(str(request.user_id))
        return jsonify(_shape_consent_response(state)), 200
    except Exception as e:
        logger.error(
            "user_sharing_consent.get_error user=%s err=%s",
            getattr(request, "user_id", None), e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to read consent state",
        }), 500


@v2_bp.route("/user/sharing-consent", methods=["PUT"])
@require_auth
def v2_user_put_sharing_consent():
    """Update any subset of the four consent flags.

    Body (JSON): any subset of mic_consent / share_consent /
    email_consent / terms_consent (each must be bool).

    Note: the legacy ``opt_in`` alias (which previously mapped to
    ``share_consent``) was removed in the Week-1 cleanup. If a
    caller still sends ``opt_in``, we log a warning and silently
    ignore it — use ``share_consent`` directly.

    Response 200: same shape as GET, echoing the post-write state.
    """
    try:
        user_id = str(request.user_id)
        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "Body must be a JSON object",
            }), 400

        # Legacy-caller detection — log once so we can spot
        # FE stragglers still sending opt_in. Silently ignored.
        if "opt_in" in body:
            logger.warning(
                "user_sharing_consent.legacy_field_ignored "
                "field=opt_in user=%s — use share_consent",
                user_id,
            )

        patch: dict = {}
        for field in _CONSENT_FIELDS_FE:
            if field in body:
                val = body[field]
                if val is not None and not isinstance(val, bool):
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": f"{field} must be a boolean or null",
                    }), 400
                patch[field] = val

        if not patch:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": (
                    "Body must include at least one of: "
                    "mic_consent, share_consent, email_consent, "
                    "terms_consent"
                ),
            }), 400

        new_state = db.upsert_consent_fields(user_id, patch)
        if new_state is None:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to write consent state",
            }), 500

        # ── Task 8 — append-only GDPR audit ledger ─────────────────
        # One row per changed field in user_consent_events. Failure-
        # tolerant: the preference upsert above already succeeded
        # and we don't want a ledger hiccup to look like the PUT
        # itself failed (the helper logs to Sentry instead).
        client_ip = _client_ip_from_request()
        user_agent = (request.headers.get("User-Agent") or "")[:512] or None
        for field, value in patch.items():
            try:
                db.insert_user_consent_event(
                    user_id=user_id,
                    consent_type=field,
                    consent_value=value,
                    ip_address=client_ip,
                    user_agent=user_agent,
                )
            except Exception as ledger_err:
                logger.warning(
                    "user_sharing_consent.ledger_failed "
                    "user=%s field=%s err=%s (non-fatal)",
                    user_id, field, ledger_err,
                )

        logger.info(
            "user_sharing_consent.put user=%s fields=%s",
            user_id, sorted(patch.keys()),
        )
        return jsonify(_shape_consent_response(new_state)), 200

    except Exception as e:
        logger.error(
            "user_sharing_consent.put_error user=%s err=%s",
            getattr(request, "user_id", None), e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to update consent state",
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


@v2_bp.route("/user/kpi/timeline", methods=["GET"])
@require_auth
def v2_user_kpi_timeline():
    """Return the user's session-by-session KPI trajectory.

    M1.1 raw mode — per-session scores, no smoothing, no per-intent
    cuts. The smoothing layer ships in a follow-up once we have
    real distributions; the `smoothed_kpi` field will be additive
    so FE chart code keeps rendering across the rollout.

    Query params:
      limit (int, optional, default 200) — max series length

    Response 200:
      Shape documented in services.kpi_timeline.build_user_kpi_timeline.

    Response 401: missing auth (handled by decorator).
    Response 500: unexpected (FE should fall back to empty chart).
    """
    try:
        user_id = request.user_id
        limit_raw = request.args.get("limit")
        limit = 200
        if limit_raw:
            try:
                limit = max(1, min(int(limit_raw), 500))
            except ValueError:
                pass  # silently coerce to default; non-blocking

        from services.kpi_timeline import build_user_kpi_timeline
        payload = build_user_kpi_timeline(user_id, limit=limit)
        return jsonify(payload), 200

    except Exception as e:
        logger.error(
            "user/kpi/timeline failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Soft-fail: return an empty payload so the FE chart renders
        # its empty state rather than an error banner. Shape mirrors
        # build_user_kpi_timeline — KPI fields removed per AC-9 (KPI
        # is private-lane / coach-side; never user-facing).
        return jsonify({
            "series": [],
            "summary": {
                "sessions_count": 0,
            },
        }), 200


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


# ── willab beta — user profile / intake (design §2, contract §3.1) ──
#
# The one-time, non-recording intake: the user picks a domain (one of
# five chips) + states a goal in their own words. Stored on
# user_settings (profile_domain + profile_goal), distinct from the
# admin-authored v2_speaker_profiles. Domain is metadata, never a flow
# fork. GET prefills the form / the Lab's read-only goal reminder.

_PROFILE_GOAL_MAX_LEN = 500


@v2_bp.route("/user/profile", methods=["GET"])
@require_auth
def v2_user_get_profile():
    """Read the user's intake profile.

    Response 200:
      { "domain": "<enum>" | null, "goal": "<str>" | null,
        "domain_vocabulary_default": [ ...seed for domain... ],
        "is_coach": bool }

    `domain_vocabulary_default` is the editable seed the Lab pre-fills
    `session_context.domain_vocabulary` from (empty list when no
    domain is set yet). Both domain + goal null pre-intake.

    `is_coach` (F.9b) is RENDER-ONLY — it lets the FE show/hide the coach
    surface. It is NEVER the authorization gate: every coach route is
    server-enforced via require_admin_or_coach against the coach_users
    allowlist. Append-only field; existing consumers ignore it.
    """
    try:
        from services.domains import default_domain_vocabulary
        profile = db.get_user_profile(request.user_id) or {
            "domain": None, "goal": None,
        }
        return jsonify({
            "domain": profile.get("domain"),
            "goal": profile.get("goal"),
            "domain_vocabulary_default": default_domain_vocabulary(
                profile.get("domain"),
            ),
            "is_coach": is_coach(request.user_id),
        }), 200
    except Exception as e:
        logger.error(
            "user/profile GET failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to fetch profile",
        }), 500


@v2_bp.route("/user/profile", methods=["POST"])
@require_auth
def v2_user_set_profile():
    """Submit the intake profile (design §3.1) — non-recording.

    Body:
      { "domain": "public_speaking|sales|executive_presence|
                   customer_service|interview_prep" | null,
        "goal":   "free text" | null }

    Both optional so a partial intake (domain picked, goal skipped, or
    vice-versa) is accepted — the intake is two bounded turns, but the
    store doesn't force both. `domain` (when present) must be one of
    the five enum keys; `goal` is trimmed, ≤500 chars, empty→null.

    Responses:
      200 — same shape as GET (echoes persisted state + vocab default)
      422 INVALID_INPUT — bad domain enum or over-long goal
      500 V2_ERROR — persist failed
    """
    try:
        from services.domains import (
            default_domain_vocabulary, is_valid_domain,
        )

        body = request.get_json(silent=True) or {}
        if not isinstance(body, dict):
            return jsonify({
                "code": "INVALID_INPUT", "error": "Body must be a JSON object",
            }), 422

        raw_domain = body.get("domain")
        domain: str | None = None
        if raw_domain is not None:
            if not is_valid_domain(raw_domain):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": (
                        "domain: must be one of public_speaking, sales, "
                        "executive_presence, customer_service, interview_prep"
                    ),
                }), 422
            domain = raw_domain

        raw_goal = body.get("goal")
        goal: str | None = None
        if raw_goal is not None:
            if not isinstance(raw_goal, str):
                return jsonify({
                    "code": "INVALID_INPUT", "error": "goal: must be a string",
                }), 422
            cleaned = raw_goal.strip()
            if cleaned:
                if len(cleaned) > _PROFILE_GOAL_MAX_LEN:
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": (
                            f"goal: must be {_PROFILE_GOAL_MAX_LEN} "
                            "characters or fewer"
                        ),
                    }), 422
                goal = cleaned

        ok = db.set_user_profile(request.user_id, domain=domain, goal=goal)
        if not ok:
            return jsonify({
                "code": "V2_ERROR", "error": "Failed to persist profile",
            }), 500

        logger.info(
            "user/profile.set user=%s domain=%s goal_len=%d",
            request.user_id, domain or "-", len(goal or ""),
        )
        return jsonify({
            "domain": domain,
            "goal": goal,
            "domain_vocabulary_default": default_domain_vocabulary(domain),
        }), 200

    except Exception as e:
        logger.error(
            "user/profile POST failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save profile",
        }), 500


# ── willab beta — strong-sides library read (design §7, contract §3.11) ─


@v2_bp.route("/user/library", methods=["GET"])
@require_auth
def v2_user_get_library():
    """The user's strong-sides library — coach-tagged snippets ingested
    on insights-read. Backs the Lounge bot's retrieval + a future FE
    library view.

    Query: tag (optional) = 'strong' | 'to_work_on' filter.

    Response 200:
      { "entries": [ {id, session_id, snippet_id, note, tag,
                      snippet_ref, created_at} ],   // newest first
        "count": int }

    Librarian-not-judge (§7): pure replay of human-authored coach notes;
    no trajectory/improvement is computed here or anywhere downstream.
    """
    try:
        tag = (request.args.get("tag") or "").strip() or None
        if tag is not None and tag not in ("strong", "to_work_on"):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "tag must be 'strong' or 'to_work_on'",
            }), 400
        entries = db.get_strong_sides_library(request.user_id, tag=tag) or []

        # Enrich each entry with deck context so the FE can group strong-sides
        # by training (FE PR #152): per-entry slide (the slide on screen when
        # this moment was spoken), rank (Stickiness #2), session_topic, and
        # presentation_ref. Additive — existing consumers (Lounge librarian
        # bot's _render_library_block) ignore the new fields. Fetches each
        # session + its snippets ONCE (cached) so the cost is O(unique sessions)
        # regardless of library size.
        from services.slide_alignment import slide_for_snippet
        _session_cache: dict = {}
        _rank_cache: dict = {}

        def _load(sid):
            if sid in _session_cache:
                return _session_cache[sid], _rank_cache[sid]
            session = db.v2_get_session_by_id(sid) or {}
            ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
            _session_cache[sid] = ctx if isinstance(ctx, dict) else {}
            # rank lookup — one fetch per session, snippet_id → metrics.rank.
            ranks: dict = {}
            try:
                for s in (db.get_snippets_by_session(sid) or []):
                    m = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
                    if isinstance(m, dict):
                        ranks[str(s.get("id"))] = m.get("rank")
            except Exception:
                pass
            _rank_cache[sid] = ranks
            return _session_cache[sid], _rank_cache[sid]

        for e in entries:
            sid = e.get("session_id")
            if not sid:
                e.setdefault("slide", None)
                e.setdefault("rank", None)
                e.setdefault("session_topic", "")
                e.setdefault("presentation_ref", None)
                continue
            ctx, ranks = _load(sid)
            slides = ctx.get("slides") or []
            advances = ctx.get("slide_advances") or []
            ref = e.get("snippet_ref") if isinstance(e.get("snippet_ref"), dict) else {}
            # Reuse the same mapping as the readout — timeline-exact, text-
            # overlap fallback when no advances. None when no deck.
            e["slide"] = slide_for_snippet(ref, advances, slides) if slides else None
            e["rank"] = ranks.get(str(e.get("snippet_id")))
            e["session_topic"] = ctx.get("topic") or ""
            e["presentation_ref"] = ctx.get("presentation_ref")

        return jsonify({"entries": entries, "count": len(entries)}), 200
    except Exception as e:
        logger.error("user/library GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to fetch library",
        }), 500


def _presentation_id_from_slides(slides) -> str:
    """Stable content hash of a deck's slides, independent of the served PDF
    URL (which changes on every re-upload). Same deck text → same id → same
    presentation group. Uses normalized title+body so cosmetic re-uploads
    don't split the take history."""
    import hashlib
    if not slides:
        return ""
    parts = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        t = (s.get("title") or "").strip()
        b = (s.get("body") or "").strip()
        parts.append(f"{t}\n{b}")
    canonical = "\n---\n".join(parts)
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()[:16]


@v2_bp.route("/user/strengths", methods=["GET"])
@require_auth
def v2_user_get_strengths():
    """Strong-sides view grouped by PRESENTATION (the deck), not by session.

    Shape (FE handoff):
      {
        general:       [{transcript, note, audio_ref, features, start_offset_ms,
                          duration_ms, rank, session_id, created_at}],
        presentations: [{
          presentation_id,                 # stable hash of slides text
          presentation_ref,                # served PDF url (latest take)
          topic,                           # from intake_context (latest take)
          slides:     [{index, title, body}],    # the deck (latest take)
          best_lines: [{slide_index, title, transcript, note, audio_ref,
                        features, rank}],       # single best take per slide
          takes:      [{                          # newest take first
            session_id, take_number, created_at,
            slides: [{index, title, body, strong_snippets: [
              {transcript, note, audio_ref, features, rank, start_offset_ms,
               duration_ms}
            ]}]
          }]
        }]
      }

    presentation_id = SHA1 of canonical slides text → stable across re-uploads
    (URL changes; content doesn't). take_number = chronological order of that
    deck's recordings (1 = first take, 2 = second, …). best_lines = per slide,
    the single snippet with the lowest rank across ALL takes of that deck.
    features = the per-snippet acoustic vector already baked into each library
    row's snippet_ref (build_readout_features at ingest).
    """
    try:
        from services.slide_alignment import (
            slide_index_for_offset, _best_match_index,
        )
        from services.power_phrase_ranking import power_score
        uid = str(request.user_id)
        library = db.get_strong_sides_library(uid, tag="strong") or []

        # Bucket library rows by session.
        by_session: dict = {}
        for row in library:
            sid = row.get("session_id")
            if not sid:
                continue
            by_session.setdefault(sid, []).append(row)

        # Load session metadata + rank lookups ONCE per session.
        sess_meta: dict = {}
        for sid in by_session:
            session = db.v2_get_session_by_id(sid) or {}
            ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
            try:
                snippets = db.get_snippets_by_session(sid) or []
            except Exception:
                snippets = []
            ranks: dict = {}
            sigs: dict = {}  # coach-adjusted power_score inputs per snippet
            for s in snippets:
                m = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
                sid_s = str(s.get("id"))
                ranks[sid_s] = m.get("rank") if isinstance(m, dict) else None
                _ss = m.get("slide_stickiness") if isinstance(m, dict) else None
                sigs[sid_s] = {
                    "overall_score": m.get("overall_score") if isinstance(m, dict) else None,
                    "slide_stickiness": (_ss or {}).get("composite") if isinstance(_ss, dict) else None,
                }
            slides = ctx.get("slides") or []
            sess_meta[sid] = {
                "ctx": ctx,
                "ranks": ranks,
                "sigs": sigs,
                "slides": slides,
                "created_at": session.get("created_at") or "",
                "presentation_id": _presentation_id_from_slides(slides),
            }

        # Split: no-deck sessions → general; deck sessions → grouped by pid.
        general: list = []
        pres_sessions: dict = {}  # pid → [sid, …]
        for sid, rows in by_session.items():
            meta = sess_meta[sid]
            if not meta["slides"]:
                for row in rows:
                    ref = row.get("snippet_ref") if isinstance(row.get("snippet_ref"), dict) else {}
                    general.append({
                        "transcript": ref.get("transcript") or "",
                        "note": row.get("note") or "",
                        "audio_ref": ref.get("audio_ref"),
                        "features": ref.get("features"),
                        "start_offset_ms": ref.get("start_offset_ms"),
                        "duration_ms": ref.get("duration_ms"),
                        "rank": meta["ranks"].get(str(row.get("snippet_id"))),
                        "session_id": sid,
                        "created_at": row.get("created_at"),
                    })
            else:
                pres_sessions.setdefault(meta["presentation_id"], []).append(sid)
        # Newest moment first inside `general`.
        general.sort(key=lambda g: g.get("created_at") or "", reverse=True)

        def _build_take(sid):
            """One take = one recording session of a given deck."""
            meta = sess_meta[sid]
            ctx = meta["ctx"]
            advances = ctx.get("slide_advances") or []
            slides = meta["slides"]
            ranks = meta["ranks"]
            sigs = meta["sigs"]
            slide_groups = [
                {
                    "index": i,
                    "title": (sl.get("title") or "") if isinstance(sl, dict) else "",
                    "body": (sl.get("body") or "") if isinstance(sl, dict) else "",
                    "strong_snippets": [],
                }
                for i, sl in enumerate(slides)
            ]
            for row in by_session[sid]:
                ref = row.get("snippet_ref") if isinstance(row.get("snippet_ref"), dict) else {}
                off = ref.get("start_offset_ms")
                idx = slide_index_for_offset(off, advances)
                if idx is None:
                    idx = _best_match_index(ref.get("transcript"), slides)
                if not isinstance(idx, int) or idx < 0 or idx >= len(slides):
                    continue
                sid_s = str(row.get("snippet_id"))
                _sig = sigs.get(sid_s, {})
                # Coach-adjusted power_score: these are all coach-tagged
                # 'strong' (the human gate), ordered by activation + slide
                # coverage. tag='strong' is uniform here, so it sets the floor;
                # activation + slide_stickiness do the ordering within.
                ps = power_score(
                    activation=_sig.get("overall_score"),
                    slide_stickiness=_sig.get("slide_stickiness"),
                    tag="strong",
                    rank=ranks.get(sid_s),
                )
                slide_groups[idx]["strong_snippets"].append({
                    "transcript": ref.get("transcript") or "",
                    "note": row.get("note") or "",
                    "audio_ref": ref.get("audio_ref"),
                    "features": ref.get("features"),
                    "start_offset_ms": off,
                    "duration_ms": ref.get("duration_ms"),
                    "rank": ranks.get(sid_s),
                    "power_score": ps,
                })
            # Order each slide's strong snippets by the coach-adjusted
            # power_score DESC (higher = better power phrase); None ranks fall
            # out via a 0-activation floor.
            for sg in slide_groups:
                sg["strong_snippets"].sort(
                    key=lambda s: -(s.get("power_score") or 0.0)
                )
            return slide_groups

        # Build presentations.
        presentations: list = []
        for pid, sids in pres_sessions.items():
            # take_number assignment — chronological (1 = first take).
            sids_asc = sorted(sids, key=lambda s: (sess_meta[s]["created_at"], s))
            take_number = {sid: i + 1 for i, sid in enumerate(sids_asc)}
            # Response order: newest take first.
            sids_desc = sorted(sids, key=lambda s: (sess_meta[s]["created_at"], s), reverse=True)
            latest_meta = sess_meta[sids_desc[0]]
            latest_slides = latest_meta["slides"]

            takes = []
            for sid in sids_desc:
                takes.append({
                    "session_id": sid,
                    "take_number": take_number[sid],
                    "created_at": sess_meta[sid]["created_at"],
                    "slides": _build_take(sid),
                })

            # best_lines: per slide_index, the single snippet with the HIGHEST
            # coach-adjusted power_score across all takes (the power phrase for
            # that slide). Each take's strong_snippets[0] is already the best
            # for that take (power-sorted).
            best_lines = []
            for i in range(len(latest_slides)):
                sl = latest_slides[i] if isinstance(latest_slides[i], dict) else {}
                best = None
                best_ps = None
                for t in takes:
                    snips = t["slides"][i]["strong_snippets"] if i < len(t["slides"]) else []
                    if not snips:
                        continue
                    top = snips[0]  # already power_score-sorted (best first)
                    ps = top.get("power_score")
                    if best is None or (
                        ps is not None and (best_ps is None or ps > best_ps)
                    ):
                        best_ps = ps
                        best = top
                if best:
                    best_lines.append({
                        "slide_index": i,
                        "title": sl.get("title") or "",
                        "transcript": best.get("transcript") or "",
                        "note": best.get("note") or "",
                        "audio_ref": best.get("audio_ref"),
                        "features": best.get("features"),
                        "rank": best.get("rank"),
                        "power_score": best.get("power_score"),
                    })

            presentations.append({
                "presentation_id": pid,
                "presentation_ref": latest_meta["ctx"].get("presentation_ref"),
                "topic": latest_meta["ctx"].get("topic") or "",
                "slides": [
                    {
                        "index": i,
                        "title": (s.get("title") or "") if isinstance(s, dict) else "",
                        "body": (s.get("body") or "") if isinstance(s, dict) else "",
                    }
                    for i, s in enumerate(latest_slides)
                ],
                "best_lines": best_lines,
                "takes": takes,
            })

        # Presentations: newest most-recent-take first.
        presentations.sort(
            key=lambda p: p["takes"][0]["created_at"] if p["takes"] else "",
            reverse=True,
        )
        return jsonify({"general": general, "presentations": presentations}), 200
    except Exception as e:
        logger.error("user/strengths GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch strengths"}), 500


def _user_presentation_groups(user_id: str) -> dict:
    """{presentation_id: [session_id ordered take 1..N]} for this user.

    MIRRORS the /user/strengths grouping so take_number lines up with what
    the FE shows: only the user's library (strong-tagged) sessions that have
    a deck, grouped by the stable slide-text hash, each group ordered by
    (created_at, session_id) ascending (take 1 = oldest)."""
    library = db.get_strong_sides_library(user_id, tag="strong") or []
    seen: dict = {}
    for row in library:
        sid = row.get("session_id")
        if sid:
            seen.setdefault(sid, True)
    groups: dict = {}
    for sid in seen:
        session = db.v2_get_session_by_id(sid) or {}
        ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
        slides = (ctx or {}).get("slides") or []
        if not slides:
            continue  # deckless moments live in `general`, not a presentation
        pid = _presentation_id_from_slides(slides)
        if not pid:
            continue
        groups.setdefault(pid, []).append((session.get("created_at") or "", sid))
    return {
        pid: [sid for _, sid in sorted(items, key=lambda t: (t[0], t[1]))]
        for pid, items in groups.items()
    }


def _hard_delete_session_for_user(user_id: str, session_id: str) -> None:
    """Durable delete of one take: drop its library rows (so it leaves
    /user/strengths now) AND the underlying session (so the readout-read
    re-ingest can't resurrect it). Owner-scoped; best-effort per step."""
    try:
        db.delete_strong_sides_library_for_session(user_id, session_id)
    except Exception as e:
        logger.warning("presentation delete: library purge failed sid=%s err=%s", session_id, e)
    try:
        db.v2_delete_session(session_id, user_id)
    except Exception as e:
        logger.warning("presentation delete: session delete failed sid=%s err=%s", session_id, e)


@v2_bp.route("/user/presentations/<presentation_id>", methods=["DELETE"])
@require_auth
def v2_user_delete_presentation(presentation_id):
    """Delete a whole presentation (deck) and ALL its takes — owner-scoped,
    HARD delete (the recordings are gone everywhere, incl. coach history).
    200 {deleted_sessions} · 404 if the user has no such presentation."""
    try:
        uid = str(request.user_id)
        groups = _user_presentation_groups(uid)
        sids = groups.get((presentation_id or "").strip())
        if not sids:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "No such presentation for this user",
            }), 404
        for sid in sids:
            _hard_delete_session_for_user(uid, sid)
        logger.info(
            "presentation deleted user=%s pid=%s takes=%d",
            uid, presentation_id, len(sids),
        )
        return jsonify({"status": "ok", "deleted_sessions": len(sids)}), 200
    except Exception as e:
        logger.error("user/presentations DELETE failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to delete presentation"}), 500


@v2_bp.route(
    "/user/presentations/<presentation_id>/takes/<take_number>",
    methods=["DELETE"],
)
@require_auth
def v2_user_delete_take(presentation_id, take_number):
    """Delete a single take (one recording session) of a presentation —
    owner-scoped HARD delete. take_number is 1-based, chronological (matches
    /user/strengths). 200 · 400 bad take_number · 404 unknown presentation/take."""
    try:
        uid = str(request.user_id)
        try:
            n = int(take_number)
        except (TypeError, ValueError):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "take_number must be a positive integer",
            }), 400
        if n < 1:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "take_number must be a positive integer",
            }), 400
        groups = _user_presentation_groups(uid)
        sids = groups.get((presentation_id or "").strip())
        if not sids:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "No such presentation for this user",
            }), 404
        if n > len(sids):
            return jsonify({
                "code": "NOT_FOUND",
                "error": f"take {n} does not exist (presentation has {len(sids)})",
            }), 404
        sid = sids[n - 1]  # take_number is 1-based, take 1 = oldest
        _hard_delete_session_for_user(uid, sid)
        logger.info(
            "take deleted user=%s pid=%s take=%d session=%s",
            uid, presentation_id, n, sid,
        )
        return jsonify({"status": "ok", "deleted_session": sid, "take_number": n}), 200
    except Exception as e:
        logger.error("user/presentations/takes DELETE failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to delete take"}), 500


# ── willab beta — Lab readout re-read + history (parked-restore + scroll-back) ─


@v2_bp.route("/user/sessions/<session_id>/readout", methods=["GET"])
@require_auth
def v2_user_get_session_readout(session_id):
    """Re-read the canonical §3.3 Readout for one of the user's sessions.

    Serves parked-restore (the report loads identically an hour later)
    and history-detail (tap a past report). Re-derived from PERSISTED
    snippets (features + the persisted stickiness), so it matches the
    upload-time payload byte-for-byte. Post-publish it also carries the
    coach layer (insights_payload + per-snippet coach note/tag).

    Owner-scoped: non-owner → 404 (no existence leak).

    Response 200:
      { "session_id", "published": bool, "state": str,
        "readout": { "snippets": [...§3.3...], "insights_payload"?: {...} } }
    """
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT", "error": "session_id must be a valid UUID",
        }), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session or str(session.get("user_id") or "") != str(request.user_id):
            return jsonify({
                "code": "SESSION_NOT_FOUND", "error": "Session not found",
            }), 404

        from services.lab_recording import build_readout_from_session
        readout = build_readout_from_session(session_id)

        published = bool(session.get("results_published_at"))
        if published:
            state = "insights_ready"
            # willab §7 — ingest this published session's coach-tagged
            # snippets into the user's strong-sides library ON READ. This
            # is the SOLE ingest trigger (the library grows per delivered
            # session the user actually opens); idempotent upsert,
            # self-guarding, never raises. Read back by the Lounge
            # librarian bot (master_doc_rag.answer_question).
            try:
                from services.strong_sides_library import ingest_session_library
                n = ingest_session_library(session_id, str(request.user_id))
                if n:
                    logger.info(
                        "library: ingested %d strong-sides rows on read "
                        "sid=%s user=%s", n, session_id, request.user_id,
                    )
            except Exception as _lib_err:
                logger.warning(
                    "library: ingest-on-read failed sid=%s err=%s "
                    "(non-fatal)", session_id, _lib_err,
                )
        elif session.get("status") == "pending_admin_review":
            state = "review_pending"
        else:
            state = "readout_ready"

        return jsonify({
            "session_id": session_id,
            "published": published,
            "state": state,
            "readout": readout,
        }), 200
    except Exception as e:
        logger.error(
            "user/sessions/<id>/readout GET failed sid=%s err=%s",
            session_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch readout"}), 500


@v2_bp.route("/user/readouts", methods=["GET"])
@require_auth
def v2_user_list_readouts():
    """The user's Lab session history (scroll-back to previous reports).

    Lightweight list, newest first; the FE fetches the full readout per
    session via /v2/user/sessions/<id>/readout on tap.

    Response 200:
      { "readouts": [ {session_id, created_at, topic, state} ], "count": int }
      state ∈ readout_ready | review_pending | insights_ready
    """
    try:
        rows = db.list_user_lab_sessions(request.user_id)
        out: list = []
        for r in rows:
            ctx = r.get("intake_context") if isinstance(r.get("intake_context"), dict) else {}
            published = bool(r.get("results_published_at"))
            if published:
                state = "insights_ready"
            elif r.get("status") == "pending_admin_review":
                state = "review_pending"
            else:
                state = "readout_ready"
            out.append({
                "session_id": r.get("id"),
                "created_at": r.get("created_at"),
                "topic": (ctx or {}).get("topic"),
                "state": state,
            })
        return jsonify({"readouts": out, "count": len(out)}), 200
    except Exception as e:
        logger.error("user/readouts GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch readouts"}), 500


# ── willab beta — coach review flow (design §14, contract §3.8) ──────
#
# Two admin/coach endpoints. The split-sink wall (§2) is the rule: the
# USER re-read (/v2/user/sessions/<id>/readout) OMITS the private
# direction label; the COACH readout below INCLUDES it (the coach
# authors/corrects it). Identity is pseudonymized, never the real
# user_id (§14 red-line 6) — list = low-identifiability; detail =
# pseudonymized-not-anonymized (full transcript + goal, opaque identity).

_COACH_PSEUDONYM_SALT = "willab-coach-pseudonym-v1"


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


# ══════════════════════════════════════════════════════════════════
# willab COACH SURFACE — canonical /v2/coach/* namespace (FE §F / PR #73).
#
# The FE coach overlay + queue speak this namespace + vocabulary: friendly
# `pseudonym`, per-snippet `coach_state` (both lanes folded), `direction_label`,
# state ∈ {pending,in_progress,done}. These routes are the alignment layer over
# the same handlers/db methods — no new logic, just the FE-facing shape. The
# namespace reversal (supersedes the earlier "re-gate /admin/*") is recorded in
# docs/coach-namespace-delta.md.
#
# IDENTITY (S.4 / §14 red-line 6): every coach response is pseudonymized —
# `pseudonym` + `domain` only, NEVER user_id / real name / email.
# ══════════════════════════════════════════════════════════════════

# Friendly, stable, non-reversible pseudonym (§B.4): adjective + animal from a
# salted hash of user_id. Same user → same handle across queue + overlay (a
# coach recognises a returning user without knowing who they are). No stored
# map. Wordlists sized for beta; expand per §B.4 (≈10× user count) at scale.
_COACH_PSEUDONYM_ADJ = (
    "Playful", "Quiet", "Bright", "Curious", "Bold", "Gentle", "Swift",
    "Calm", "Clever", "Brave", "Sunny", "Steady", "Witty", "Warm", "Keen",
    "Nimble", "Mellow", "Lively", "Patient", "Earnest", "Cheery", "Frank",
    "Spry", "Wry",
)
_COACH_PSEUDONYM_ANIMAL = (
    "Octopus", "Otter", "Falcon", "Badger", "Heron", "Lynx", "Marten",
    "Sparrow", "Dolphin", "Ibex", "Magpie", "Beaver", "Finch", "Hare",
    "Stork", "Vole", "Wren", "Crane", "Mole", "Newt", "Quail", "Robin",
    "Seal", "Tern",
)


def _coach_pseudonym(user_id):
    """Stable friendly handle for a user_id (e.g. "Playful Octopus"). Never
    reversible to identity; no stored map. Empty user_id → 'Anonymous'."""
    if not user_id:
        return "Anonymous"
    import hashlib
    h = int(hashlib.sha256(
        (_COACH_PSEUDONYM_SALT + str(user_id)).encode("utf-8")
    ).hexdigest(), 16)
    adj = _COACH_PSEUDONYM_ADJ[(h // len(_COACH_PSEUDONYM_ANIMAL)) % len(_COACH_PSEUDONYM_ADJ)]
    animal = _COACH_PSEUDONYM_ANIMAL[h % len(_COACH_PSEUDONYM_ANIMAL)]
    return f"{adj} {animal}"


def _coach_state_map(session_id):
    """Per-snippet coach_state, folding BOTH lanes → the resume read.
    direction_label ← training_labels (PRIVATE); note/tag/surfaced ←
    coach_snippet_drafts (USER). THIS is what makes note/tag/surfaced
    round-trip on reopen (not just the label — the bug this layer fixes)."""
    labels = {}
    for lab in (db.get_training_labels(session_id) or []):
        sid = lab.get("snippet_id")
        if sid is not None:
            labels[str(sid)] = lab.get("value")
    drafts = {}
    for d in (db.get_coach_snippet_drafts(session_id) or []):
        sid = d.get("snippet_id")
        if sid is not None:
            drafts[str(sid)] = d
    out = {}
    for sid in set(labels) | set(drafts):
        d = drafts.get(sid) or {}
        out[sid] = {
            "direction_label": labels.get(sid),
            "note": (d.get("note") or ""),
            "tag": d.get("tag"),
            "surfaced": bool(d.get("surfaced")),
        }
    return out


def _coach_state_for(session_id, snippet_id):
    """One snippet's coach_state (default-empty when nothing authored yet)."""
    return _coach_state_map(session_id).get(str(snippet_id), {
        "direction_label": None, "note": "", "tag": None, "surfaced": False,
    })


def _coach_session_state(session, cstate_map):
    """FE lifecycle state: done (published) > in_progress (any authoring) >
    pending (nothing authored yet)."""
    if session.get("results_published_at"):
        return "done"
    return "in_progress" if cstate_map else "pending"


@v2_bp.route("/user/credits", methods=["GET"])
@require_auth
def v2_user_get_credits():
    """willab credit balance (UX Wave v2 C5 / S.2). GET → {credits: int}.

    Lazy-seeds the 15-credit grant on first touch (idempotent via
    credits_initialized_at — never re-granted after spend-to-zero), then
    returns the server-owned balance. The DECREMENT is a side-effect of
    send-success (the claim/merge path), NEVER a separate FE call.
    """
    try:
        credits = db.v2_ensure_credits_initialized(str(request.user_id))
        return jsonify({"credits": int(credits)}), 200
    except Exception as e:
        logger.error("user/credits GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch credits"}), 500


@v2_bp.route("/user/recording-progress", methods=["GET"])
@require_auth
def v2_user_recording_progress():
    """willab recording progress toward the first audit (UX Wave 3 C-2 / S2).

    GET → {recorded_seconds:int, threshold_seconds:int, unlocked:bool}.
    recorded_seconds = the SERVER's cumulative sum of the user's Lab recording
    durations (the FE renders bar = recorded/threshold and NEVER sums snippet
    durations — those are selected windows, not total recorded time).
    """
    from services.user_audit import AUDIT_UNLOCK_SECONDS
    try:
        recorded = int(db.v2_get_cumulative_recorded_seconds(str(request.user_id)) or 0)
        return jsonify({
            "recorded_seconds": recorded,
            "threshold_seconds": AUDIT_UNLOCK_SECONDS,
            "unlocked": recorded >= AUDIT_UNLOCK_SECONDS,
        }), 200
    except Exception as e:
        logger.error("user/recording-progress GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch progress"}), 500


@v2_bp.route("/user/last-setup", methods=["GET"])
@require_auth
def v2_user_last_setup():
    """willab "do the same as last time" — the user's most-recent training
    set-up, prefillable into the set-up form. Read-only; cross-device (sources
    the last session's intake_context server-side, not localStorage).

    Returns the prefillable subset (NOT slide_advances — the tap timeline is
    per-recording, the new run generates its own):
      200 { available: true, topic, audience, target_length_seconds,
            domain_vocabulary, slides, presentation_ref }
      200 { available: false }   — no prior session
    """
    try:
        sessions = db.v2_list_user_lab_sessions(str(request.user_id), limit=1) or []
        if not sessions:
            return jsonify({"available": False}), 200
        ctx = sessions[0].get("intake_context")
        ctx = ctx if isinstance(ctx, dict) else {}
        return jsonify({
            "available": True,
            "topic": ctx.get("topic"),
            "audience": ctx.get("audience"),
            "target_length_seconds": ctx.get("target_length_seconds"),
            "domain_vocabulary": ctx.get("domain_vocabulary") or [],
            "slides": ctx.get("slides") or [],
            "presentation_ref": ctx.get("presentation_ref"),
        }), 200
    except Exception as e:
        logger.error("user/last-setup GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch last setup"}), 500


@v2_bp.route("/config/recording", methods=["GET"])
@optional_auth
def v2_config_recording():
    """willab recording config (UX Wave v2 D5 / B-3). Single source of truth
    for the recording floor so the FE stops hardcoding 60s. The SERVER is the
    real gate — min_content_gate rejects anything under this on upload (422,
    RECORDING_REJECTED); this just lets the FE preview the same numbers.
    """
    from services.min_content_gate import MIN_DURATION_SEC, MIN_VOICED_SEC
    return jsonify({
        "min_duration_sec": MIN_DURATION_SEC,
        "min_voiced_sec": MIN_VOICED_SEC,
    }), 200


@v2_bp.route("/coach/students", methods=["GET"])
@require_admin_or_coach
def v2_coach_students():
    """willab coach roster (UX Wave v2 E3 / §B.4 / S.6). Pseudonymized list of
    every willab student — solo-coach beta, so no per-coach assignment table
    yet (every student is in scope). Each row: {pseudonym, domain (profile),
    last_active}. NEVER user_id / name / email. Paginated (?limit=&offset=),
    newest-active first.
    """
    try:
        try:
            limit = max(1, min(200, int(request.args.get("limit", 100))))
        except (TypeError, ValueError):
            limit = 100
        try:
            offset = max(0, int(request.args.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0
        rows = db.list_coach_students(limit=limit, offset=offset) or []
        out = []
        for r in rows:
            uid = r.get("user_id")
            prof = db.get_user_profile(uid) or {}
            out.append({
                # Opaque drill key — the FE keys the student detail view
                # (GET /v2/coach/students/<user_id>) on this and NEVER renders
                # it. A random UUID is not name/email, so this does not breach
                # §B.4 (pseudonym + domain are still the only DISPLAYED fields).
                "user_id": str(uid) if uid else "",
                "pseudonym": _coach_pseudonym(uid),
                "domain": (prof or {}).get("domain") or "",
                "last_active": r.get("last_active") or "",
                # read-only coach-load signal (the beta "drowning guard") —
                # total Lab sessions for this user. No PII; instrumentation only.
                "session_count": int(r.get("session_count") or 0),
            })
        return jsonify(out), 200
    except Exception as e:
        logger.error("coach/students GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch students"}), 500


@v2_bp.route("/coach/students/<user_id>", methods=["GET"])
@require_admin_or_coach
def v2_coach_student_detail(user_id):
    """willab coach student drill-down (UX Wave 3 E-1b / S6). Pseudonymized:
    {pseudonym, domain, goal, sessions:[{session_id, topic, created_at, state}]}.
    NEVER name/email. `goal` is user free-text and may self-identify — inherent,
    not scrubbable (Flag 1: pseudonymized-default; a real-identity view is an
    explicit admin-only exception needing founder approval).
    """
    if not _is_valid_uuid(user_id):
        return jsonify({"code": "INVALID_INPUT", "error": "user_id must be a UUID"}), 400
    try:
        prof = db.get_user_profile(user_id) or {}
        rows = db.v2_list_user_lab_sessions(user_id) or []
        # Unknown id → 404. A real roster student always has >=1 Lab session;
        # 404 only when there's no footprint at all (no sessions AND no profile)
        # so a transient sessions-read hiccup can't false-404 a known student.
        if not rows and not (prof.get("domain") or prof.get("goal")):
            return jsonify({
                "code": "STUDENT_NOT_FOUND",
                "error": "No willab student for that id.",
            }), 404
        # U10 rollup — the feeling the student named per session, mapped by
        # session_id (one batch read) so the coach sees the felt-state spread
        # across the student's takes in one place. Coach-only (split-sink).
        _feel_by_session = {}
        for _fr in db.get_feelings_by_sessions([s.get("id") for s in rows]):
            _feel_by_session.setdefault(_fr.get("session_id"), _fr.get("feeling"))
        sessions = []
        for s in rows:
            ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
            if s.get("results_published_at"):
                state = "insights_ready"
            elif s.get("status") == "pending_admin_review":
                state = "review_pending"
            else:
                state = "readout_ready"
            sessions.append({
                "session_id": s.get("id"),
                "topic": (ctx or {}).get("topic") or "",
                "created_at": s.get("created_at"),
                "state": state,
                # nervous/excited/calm/unsure, or null if not captured.
                "feeling": _feel_by_session.get(s.get("id")),
            })
        return jsonify({
            "pseudonym": _coach_pseudonym(user_id),
            "domain": (prof or {}).get("domain") or "",
            "goal": (prof or {}).get("goal") or "",
            # Goal-change context (Prompt A §6 C4 follow-up) — what the goal
            # WAS before the last change + when, so the coach sees old→new.
            # Null/empty when the goal has never been changed.
            "previous_goal": (prof or {}).get("previous_goal") or "",
            "goal_changed_at": (prof or {}).get("goal_changed_at") or "",
            "sessions": sessions,
        }), 200
    except Exception as e:
        logger.error("coach/student-detail GET failed user=%s err=%s", user_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch student"}), 500


@v2_bp.route("/coach/students/<user_id>/audit-data", methods=["GET"])
@require_admin_or_coach
def v2_coach_audit_data(user_id):
    """Audit-assembly data — the felt-state correlation for the interactive
    HTML audit (so it SUCKS UP the user's real data instead of being typed).

    Groups the stored pre-recording feelings (U10) against the existing
    per-snippet performance signal to produce the audit's "Performance under
    feeling" + "Stress as fuel" sections. DIRECTIONAL coaching indicators —
    `headline`s are DRAFTS the coach curates; everything is gated on a minimum
    number of takes (returns null headlines below it, never a one-take claim).

    Coach-facing assembly (the coach reviews + curates before it reaches the
    user — the audit is the human-gated deliverable). Compose with
    GET /v2/user/strengths for the per-slide "best line" sections.

    200 { user_id, performance_under_feeling, stress_as_fuel, takes:[...] }
    """
    if not _is_valid_uuid(user_id):
        return jsonify({"code": "INVALID_INPUT", "error": "user_id must be a UUID"}), 400
    try:
        from services.feeling_performance import (
            correlate_feeling_performance, session_performance, stress_as_fuel,
        )
        rows = db.v2_list_user_lab_sessions(user_id) or []
        feel_by_session = {}
        for _fr in db.get_feelings_by_sessions([s.get("id") for s in rows]):
            feel_by_session.setdefault(_fr.get("session_id"), _fr.get("feeling"))

        takes = []
        pairs = []
        for s in rows:
            sid = s.get("id")
            feeling = feel_by_session.get(sid)
            if not feeling:
                continue  # no felt-state → not part of the correlation
            perf = session_performance(db.get_snippets_by_session(sid))
            ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
            takes.append({
                "session_id": sid,
                "topic": (ctx or {}).get("topic") or "",
                "feeling": feeling,
                "performance": round(perf, 2) if perf is not None else None,
            })
            pairs.append({"feeling": feeling, "performance": perf})

        return jsonify({
            "user_id": user_id,
            "performance_under_feeling": correlate_feeling_performance(pairs),
            "stress_as_fuel": stress_as_fuel(pairs),
            "takes": takes,
        }), 200
    except Exception as e:
        logger.error("coach/audit-data GET failed user=%s err=%s", user_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to assemble audit data"}), 500


@v2_bp.route("/coach/students/<user_id>/audit", methods=["GET"])
@require_admin_or_coach
def v2_coach_student_audit(user_id):
    """willab user_audit — coach panel DOWNLOAD (UX Wave 3 BE-3 / S5).
    Assembled from existing insights + strong_sides_library (no generator).
    `unlocked` reflects the S2 threshold; the coach decides whether to surface
    'send' on a still-locked audit.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({"code": "INVALID_INPUT", "error": "user_id must be a UUID"}), 400
    try:
        from services.user_audit import assemble_user_audit
        audit = assemble_user_audit(user_id)
        audit["pseudonym"] = _coach_pseudonym(user_id)
        return jsonify(audit), 200
    except Exception as e:
        logger.error("coach/student-audit GET failed user=%s err=%s", user_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to assemble audit"}), 500


@v2_bp.route("/coach/students/<user_id>/audit/send", methods=["POST"])
@require_admin_or_coach
def v2_coach_student_audit_send(user_id):
    """willab user_audit — coach MANUAL email trigger (UX Wave 3 BE-3 / S5).
    Emails the assembled audit to the student. Gated on S2 unlock (>=10 min
    cumulative recorded). 409 if still locked; 422 if no email on file.
    """
    if not _is_valid_uuid(user_id):
        return jsonify({"code": "INVALID_INPUT", "error": "user_id must be a UUID"}), 400
    try:
        from services.user_audit import (
            assemble_user_audit, render_user_audit_html, audit_email_subject,
        )
        audit = assemble_user_audit(user_id)
        if not audit.get("unlocked"):
            return jsonify({
                "code": "AUDIT_LOCKED",
                "error": "Audit not unlocked yet (under the recording threshold).",
                "recorded_seconds": audit.get("recorded_seconds"),
                "threshold_seconds": audit.get("threshold_seconds"),
            }), 409
        email = db.get_user_email_from_auth(user_id)
        if not email:
            return jsonify({
                "code": "NO_EMAIL", "error": "No email on file for this user.",
            }), 422
        from services.email_service import send_email_resend
        send_email_resend(
            to=email,
            subject=audit_email_subject(),
            html=render_user_audit_html(audit),
        )
        logger.info("coach: user_audit emailed user=%s", user_id)
        return jsonify({"status": "sent", "email_sent_to": email}), 200
    except Exception as e:
        logger.error("coach/student-audit send failed user=%s err=%s", user_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to send audit"}), 500


@v2_bp.route("/coach/queue", methods=["GET"])
@require_admin_or_coach
def v2_coach_queue():
    """① Coach review queue (FE PR2 → /v2/coach/queue). Pseudonymized rows,
    FIFO (oldest sent first). Each row: {session_id, pseudonym, domain, topic,
    n_snippets, state, sent_at} — NEVER user_id / name / email."""
    try:
        rows = db.list_review_queue() or []
        out = []
        for r in rows:
            sid = r.get("id")
            ctx = r.get("intake_context") if isinstance(r.get("intake_context"), dict) else {}
            cstate = _coach_state_map(sid)
            out.append({
                "session_id": sid,
                "pseudonym": _coach_pseudonym(r.get("user_id")),
                "domain": (ctx or {}).get("domain") or "",
                "topic": (ctx or {}).get("topic") or "",
                "n_snippets": len(db.get_snippets_by_session(sid) or []),
                "state": _coach_session_state(r, cstate),
                "sent_at": r.get("guest_claimed_at") or r.get("created_at") or "",
            })
        out.sort(key=lambda x: x.get("sent_at") or "")  # FIFO, oldest first
        return jsonify(out), 200
    except Exception as e:
        logger.error("coach/queue GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch coach queue"}), 500


@v2_bp.route("/coach/sessions/<session_id>", methods=["GET"])
@require_admin_or_coach
def v2_coach_get_session(session_id):
    """② Coach review session payload (FE PR #73 → /v2/coach/sessions/<id>).

    Identity-stripped (S.4): pseudonym + domain only — NO user_id / name /
    email. Per-snippet coach_state folds BOTH lanes so the coach's note / tag /
    surfaced / direction ALL resume on reopen (the round-trip the old
    label-only readout dropped).
    """
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        from services.lab_recording import build_readout_from_session
        # include_slide_scores=True → coach gets Stickiness #2 (per-snippet
        # on-slide-ness + the per-slide coverage ledger). Coach-only (AC-9).
        readout = build_readout_from_session(session_id, include_slide_scores=True)
        cstate = _coach_state_map(session_id)
        # Phase 4 / Prompt 2 — the AI-Commentator draft the coach's comment
        # field opens PRE-FILLED with (frozen; the coach types over it). {} when
        # the migration hasn't run → blank field, same as before.
        ai_drafts = db.get_ai_draft_coach_notes_by_session(session_id)

        snippets = []
        for snip in (readout.get("snippets") or []):
            _sid = str(snip.get("id"))
            _coach_state = dict(cstate.get(_sid, {
                "direction_label": None, "note": "", "tag": None, "surfaced": False,
            }))
            _coach_state["ai_draft_coach_note"] = ai_drafts.get(_sid)
            snippets.append({
                "id": snip.get("id"),
                "index": snip.get("index"),
                "transcript": snip.get("transcript") or "",
                "audio_ref": snip.get("audio_ref"),
                "start_offset_ms": snip.get("start_offset_ms"),
                "duration_ms": snip.get("duration_ms"),
                "stickiness": snip.get("stickiness") or {"composite": None, "comment": None},
                # C1 / §B.1 — the coach packet carries the raw acoustic
                # 11-vector for REFERENCE (render no verdict). Coach surface
                # only; the split-sink user readout already exposes the same
                # vector by design. build_readout_from_session computed it.
                "features": snip.get("features"),
                # UX Wave 4 Phase 2 — the slide on screen when this snippet was
                # spoken (from the tap timeline), so the coach reviews delivery
                # against what the slide claimed. None when no deck.
                "slide": snip.get("slide"),
                # Stickiness #2 (coach-only): per-snippet on-slide-ness +
                # blended overall + rank (annotation, readout stays chronological).
                "slide_stickiness": snip.get("slide_stickiness"),
                "overall_score": snip.get("overall_score"),
                "rank": snip.get("rank"),
                "coach_state": _coach_state,
            })

        # Phase 4 / Prompt 1 (B3) — SHADOW direction predictions for this
        # session's reviewed snippets. Fire-and-forget; logged to
        # shadow_predictions, NEVER in this packet, influences nothing.
        try:
            from services.learning_serve import dispatch_shadow_predictions
            dispatch_shadow_predictions(session_id, snippets)
        except Exception as _shadow_err:
            logger.warning("coach/get-session: shadow dispatch failed: %s", _shadow_err)

        ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
        insights = session.get("insights_payload") if isinstance(session.get("insights_payload"), dict) else {}
        from services.feelings import shape_coach_feelings
        return jsonify({
            "session_id": session_id,
            "pseudonym": _coach_pseudonym(session.get("user_id")),
            "domain": (ctx or {}).get("domain") or "",
            "topic": (ctx or {}).get("topic") or "",
            "sent_at": session.get("guest_claimed_at") or session.get("created_at") or "",
            "state": _coach_session_state(session, cstate),
            "overall_message": (insights or {}).get("overall_message") or "",
            "video_ref": (session.get("coach_video_ref") or None),
            # Slide-deck context (UX Wave 4 BE-S6a) — coach sees the deck while
            # reviewing; per-snippet slide mapping is Phase 2.
            "slides": (ctx or {}).get("slides") or [],
            "presentation_ref": (ctx or {}).get("presentation_ref") or None,
            # Per-slide coverage ledger (Stickiness #2 (i)) — coach audit.
            "slide_coverage": readout.get("slide_coverage") or [],
            "snippets": snippets,
            # U10 — the pre-recording feeling(s) the student named (nervous/
            # excited/calm/unsure), shown at the END of the snippets. Coach-only
            # (split-sink/AC-9, never user-facing); the felt-state input the
            # coach factors into the audit's "Performance under feeling".
            "feelings": shape_coach_feelings(db.get_feelings_by_session(session_id)),
        }), 200
    except Exception as e:
        logger.error("coach/get-session failed sid=%s err=%s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch coach session"}), 500


@v2_bp.route("/coach/sessions/<session_id>/slide-alignment", methods=["GET"])
@require_admin_or_coach
def v2_coach_slide_alignment(session_id):
    """willab slide↔delivery coverage ledger (UX Wave 4, claim-ledger).
    COACH-REFERENCE ONLY (AC-9). Reads the PERSISTED per-slide ledger computed
    at processing time (no live LLM call) — the structured "delivered N of M
    points per slide" audit. Consolidated from the old prose verdict: the
    ledger is the single source.

      200 { slide_coverage:[{slide_index, covered, partial, total, ledger}] }
      200 { available: false }   — no deck / not scored
    """
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        from services.lab_recording import build_readout_from_session
        readout = build_readout_from_session(session_id, include_slide_scores=True)
        coverage = readout.get("slide_coverage") or []
        if not coverage:
            return jsonify({"available": False}), 200
        return jsonify({"slide_coverage": coverage}), 200
    except Exception as e:
        logger.error("coach/slide-alignment failed sid=%s err=%s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to compute slide alignment"}), 500


@v2_bp.route("/coach/sessions/<session_id>/snippets/<snippet_id>", methods=["POST"])
@require_admin_or_coach
def v2_coach_save_snippet(session_id, snippet_id):
    """③ willab coach per-snippet immediate save (E1 / §B.3 / S.5).

    FE contract (PR #73): body uses `direction_label` (not `label`); the
    response echoes the persisted `coach_state` (both lanes folded), which the
    FE writes back into its local state. Sending `direction_label: null` CLEARS
    the label.

    Persists ONE snippet's coach authoring immediately, so reopening the
    overlay resumes where the coach left off (no all-in-memory-until-publish
    loss). Partial saves are first-class — send only the fields that changed.

    Body (any subset)::
        { "label"?:   "threat"|"ambiguous"|"challenge"   // or {value, was_pre_filled, was_overridden}
          "note"?:    "..."        // empty/whitespace -> cleared
          "tag"?:     "strong"|"to_work_on"
          "surfaced"?: bool         // does this snippet reach the user?
          "when"?:    "...", "examples"?: ["..."] }       // optional PR-2 fields

    TWO-LANE write, NO cross-derivation (split-sink §2 / S.1):
      * label -> PRIVATE training_labels (direction-v1). Never user-facing.
      * note/tag/surfaced/when/examples -> USER coach_snippet_drafts (assembled
        into insights_payload at publish). The tag is NOT derived from the
        label, nor vice-versa — separate request fields, separate stores.

    Idempotent on (session_id, snippet_id). NO publish-floor validation here
    (drafts are partial; the floor is enforced at publish). Coach-facing only:
    the response echoes the coach's own input — no salience/control score, no
    real identity, never serialized to the user.

    200 { status, session_id, snippet_id, saved: { label?, draft? } }
    400 INVALID_INPUT · 404 SESSION_NOT_FOUND / SNIPPET_NOT_FOUND · 422 invalid value
    """
    from services.training_labels import VALID_VALUES, SCHEMA_VERSION
    from services.insights_payload import VALID_TAGS

    if not _is_valid_uuid(session_id) or not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT", "error": "session_id and snippet_id must be UUIDs",
        }), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        # Snippet must belong to THIS session (no cross-session writes).
        snips = db.get_snippets_by_session(session_id) or []
        if snippet_id not in {str(s.get("id")) for s in snips if s.get("id")}:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND", "error": "Snippet not in this session",
            }), 404

        body = request.get_json(silent=True) or {}

        # ── PRIVATE lane — direction label (training_labels). ──
        # FE sends `direction_label` (str | null). null CLEARS; a value upserts.
        if "direction_label" in body:
            value = body["direction_label"]
            if value is None:
                db.delete_training_label(session_id, snippet_id)
            elif value in VALID_VALUES:
                db.upsert_training_labels(session_id, str(request.user_id), [{
                    "snippet_id": snippet_id,
                    "schema_version": SCHEMA_VERSION,
                    "value": value,
                    "was_pre_filled": False,
                    "was_overridden": False,
                }])
                # Phase 4 / Prompt 1 (B3, SHADOW) — close the loop: backfill the
                # coach's actual label onto this snippet's shadow prediction, and
                # auto-retrain in the background if enough new labels accrued
                # (≥25 new / ≥50 floor, no cron). Both best-effort; the new model
                # stays status=shadow and influences NOTHING.
                try:
                    from services.learning_serve import maybe_auto_retrain
                    db.backfill_shadow_coach_actual(snippet_id, value)
                    maybe_auto_retrain()
                except Exception as _learn_err:
                    logger.warning("coach/save-snippet: shadow learn hook failed: %s", _learn_err)
            else:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": f"direction_label: must be one of {', '.join(VALID_VALUES)} or null",
                }), 422

        # ── USER lane — note / tag / surfaced / when / examples (drafts). ──
        draft_fields: dict = {}
        if "note" in body:
            note_raw = body.get("note")
            if note_raw is not None and not isinstance(note_raw, str):
                return jsonify({"code": "INVALID_INPUT", "error": "note: must be a string"}), 422
            note = (note_raw or "").strip()
            if len(note) > 2000:
                return jsonify({"code": "INVALID_INPUT", "error": "note: 2000 chars max"}), 422
            draft_fields["note"] = note or None
        if "tag" in body:
            tag = body.get("tag")
            if tag is not None and tag not in VALID_TAGS:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": f"tag: must be one of {', '.join(VALID_TAGS)}",
                }), 422
            draft_fields["tag"] = tag
        if "surfaced" in body:
            surfaced = body.get("surfaced")
            if not isinstance(surfaced, bool):
                return jsonify({"code": "INVALID_INPUT", "error": "surfaced: must be a boolean"}), 422
            draft_fields["surfaced"] = surfaced
        if "when" in body:
            when_raw = body.get("when")
            if when_raw is not None and not isinstance(when_raw, str):
                return jsonify({"code": "INVALID_INPUT", "error": "when: must be a string"}), 422
            when = (when_raw or "").strip()
            if len(when) > 1000:
                return jsonify({"code": "INVALID_INPUT", "error": "when: 1000 chars max"}), 422
            draft_fields["when_context"] = when or None
        if "examples" in body:
            ex_raw = body.get("examples")
            if ex_raw is None:
                draft_fields["examples"] = []
            elif not isinstance(ex_raw, list):
                return jsonify({"code": "INVALID_INPUT", "error": "examples: must be a list"}), 422
            else:
                cleaned_ex = []
                for ex in ex_raw[:10]:
                    if isinstance(ex, str) and ex.strip():
                        cleaned_ex.append(ex.strip()[:500])
                draft_fields["examples"] = cleaned_ex

        if draft_fields:
            db.upsert_coach_snippet_draft(
                session_id, snippet_id, draft_fields, updated_by=str(request.user_id),
            )

        # Echo the persisted coach_state (BOTH lanes folded) — the FE writes
        # this back into its local state, so it must reflect what's stored.
        return jsonify({
            "coach_state": _coach_state_for(session_id, snippet_id),
        }), 200
    except Exception as e:
        logger.error(
            "coach/save-snippet failed sid=%s snip=%s err=%s",
            session_id, snippet_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save snippet"}), 500


@v2_bp.route("/coach/sessions/<session_id>/recut", methods=["POST"])
@require_admin_or_coach
def v2_coach_session_recut(session_id):
    """willab admin re-cut (UX Wave 3 E-2 / S7). Re-runs the willab segmenter
    on the session's STORED parent audio and replaces the auto-cut snippets.

    DEVIATION (reported): the spec named apply_extracted_snippets, but that is
    the OLD funnel's pipeline (turn rows / session_recordings/full.webm).
    willab Lab audio lives in the coach bucket and is cut by
    process_lab_recording, so re-cut re-runs THAT on the re-downloaded parent.

    Guard: refused on a PUBLISHED session (never disturb a delivered report).
    Caveat: re-cut mints new snippet ids, so any pre-publish coach drafts/
    labels on the old snippets are orphaned (invisible to the new cut).
    """
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        if session.get("results_published_at"):
            return jsonify({
                "code": "ALREADY_PUBLISHED",
                "error": "Cannot re-cut a published session.",
            }), 409
        # Guard the PARTIALLY-REVIEWED case: re-cut mints new snippet ids, so
        # any coach labels/drafts already on this session would be orphaned —
        # and labels are private-lane training signal, not just UX. Refuse
        # unless ?force=true (a deliberate "discard my N labels" choice the FE
        # must confirm). On force we delete the now-orphaned rows so they don't
        # pollute the training set with dead-snippet references.
        _force = (request.args.get("force") or "").strip().lower() in ("1", "true", "yes")
        _labels = db.get_training_labels(session_id) or []
        _drafts = db.get_coach_snippet_drafts(session_id) or []
        if (_labels or _drafts) and not _force:
            return jsonify({
                "code": "RECUT_WOULD_DISCARD_LABELS",
                "error": (
                    "Re-cut mints new snippets and would discard the coach "
                    "labels/notes already on this session. Re-send with "
                    "?force=true to re-cut and discard them."
                ),
                "labels": len(_labels),
                "drafts": len(_drafts),
            }), 409
        recording_id = session.get("recording_1_id")
        if not recording_id:
            return jsonify({"code": "NO_RECORDING", "error": "Session has no recording."}), 404
        rec = db.get_recording(recording_id)
        if not rec:
            return jsonify({"code": "NO_RECORDING", "error": "Recording not found."}), 404
        storage_path = rec.get("storage_path")
        parent_url = rec.get("audio_url") or storage_path
        if not storage_path:
            return jsonify({"code": "NO_AUDIO", "error": "Recording has no stored audio."}), 422

        from services.coach_video_storage import get_coach_object_bytes
        try:
            audio_bytes = get_coach_object_bytes("coach_feedback_videos", storage_path)
        except Exception as fe:
            logger.error("recut: audio fetch failed sid=%s err=%s", session_id, fe)
            return jsonify({"code": "AUDIO_FETCH_FAILED", "error": "Could not load stored audio."}), 502
        if not audio_bytes:
            return jsonify({"code": "NO_AUDIO", "error": "Stored audio is empty."}), 422

        # Replace the existing auto-cut snippets, then re-run the segmenter.
        # On a forced re-cut, also clear the now-orphaned coach labels/drafts
        # (the coach explicitly chose to discard them) so dead-snippet rows
        # don't linger in the private-lane training set.
        if _force and (_labels or _drafts):
            db.delete_training_labels_for_session(session_id)
            db.delete_coach_snippet_drafts_for_session(session_id)
            logger.info(
                "recut: force-discarded coach work sid=%s labels=%d drafts=%d",
                session_id, len(_labels), len(_drafts),
            )
        db.v2_delete_lab_snippets_for_recording(recording_id)
        from services.lab_recording import process_lab_recording
        readout = process_lab_recording(
            session_id=session_id,
            user_id=session.get("user_id"),
            recording_id=recording_id,
            audio_bytes=audio_bytes,
            filename=(storage_path.rsplit("/", 1)[-1] or "lab.webm"),
            session_context=(
                session.get("intake_context")
                if isinstance(session.get("intake_context"), dict) else {}
            ),
            parent_audio_url=parent_url,
        )
        snippets = (readout or {}).get("snippets") or []
        logger.info("recut: sid=%s re-cut snippets=%d", session_id, len(snippets))
        return jsonify({
            "status": "ok", "session_id": session_id,
            "snippet_count": len(snippets), "snippets": snippets,
        }), 200
    except Exception as e:
        logger.error("coach/session-recut failed sid=%s err=%s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to re-cut session"}), 500


@v2_bp.route("/coach/sessions/<session_id>/video", methods=["POST"])
@require_admin_or_coach
def v2_coach_session_video(session_id):
    """④ willab coach feedback video for a session (B.3).

    REUSES the existing coach video transport/storage (services/coach_video_
    storage — same bucket + R2/Supabase path the funnel afterwards-video +
    feedback videos use; no new infra/bucket/transcoding). Stores the file,
    persists coach_video_ref on the session; the publish contract folds it into
    insights_payload so it ships to the user with the insights. Re-upload
    overwrites (deterministic storage key).

    multipart/form-data: video_file (.mp4/.mov/.webm/.m4v).
    200 { status, session_id, video_ref } · 400/404/413/415/502
    """
    from services.coach_video_storage import (
        coach_media_public_url, put_coach_object_bytes,
    )
    import os

    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        max_video_mb = max(1, int(getattr(config, "COACH_FEEDBACK_VIDEO_MAX_MB", 100)))
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

        storage_key = f"coach-feedback/{session_id}{ext}"
        bucket = getattr(config, "COACH_FEEDBACK_VIDEO_BUCKET", "coach_feedback_videos")
        try:
            put_coach_object_bytes(
                bucket, storage_key, video_bytes,
                video_file.content_type or "video/mp4",
            )
        except Exception as upload_err:
            logger.error("coach video upload failed sid=%s err=%s", session_id, upload_err)
            return jsonify({"code": "UPLOAD_FAILED", "error": "Failed to upload video to storage."}), 502

        video_ref = coach_media_public_url(storage_key)
        db.set_session_coach_video_ref(session_id, video_ref)
        logger.info("coach video stored sid=%s key=%s", session_id, storage_key)
        return jsonify({
            "status": "ok", "session_id": session_id, "video_ref": video_ref,
        }), 200
    except Exception as e:
        logger.error("coach/session-video failed sid=%s err=%s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to store coach video"}), 500


# ── willab beta — Lab upload handler (design §4, contract §3.3) ──────
#
# The convergence: multipart audio + inline session_context → min-content
# gate → store → Whisper → segment → features → per-snippet stickiness →
# §3.3 Readout payload, synchronously (FE confirmed multipart-sync).
#
# AUTH-MODEL ASSUMPTIONS (flagged for FE — easy to change, the route is
# thin):
#   (a) PUBLIC / guest-allowed — the willab pre-send flow is unsigned
#       (account is created only at Send, §13), so the Lab records as a
#       guest. Mirrors the existing /v2/public/interview/* funnel:
#       guest_session_id keyed, user_id=NULL, claimed at send via
#       v2_claim_guest_session.
#   (b) session_context arrives INLINE in the multipart (topic + optional
#       audience/target_length_seconds/domain_vocabulary), because an
#       unsigned user's session_context isn't on the server (the
#       @require_auth /intake-context PUT is the signed-user variant).
# If FE wants optional-auth (use the real user_id when a JWT is present)
# or a separate guest session_context step, say so — small change.

# Presentation recordings run minutes, not seconds — 25MB was too tight (a
# real talk 413'd). 100MB headroom; the global MAX_CONTENT_LENGTH (500MB) still
# bounds it, and oversized audio is compressed to a 16kHz mono mp3 before the
# OpenAI Whisper call (which itself caps at 25MB) — see process_lab_recording.
_LAB_MAX_AUDIO_MB = 100


def _parse_lab_vocabulary(raw):
    """Parse the multipart domain_vocabulary field — accepts a JSON
    array string or a comma-separated list. Returns a list or None."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return parsed
    except Exception:
        pass
    return [t.strip() for t in s.split(",") if t.strip()]


_PRESENTATION_MAX_MB = 20  # slide decks; FE mirrors this guard


@v2_bp.route("/lab/presentation/extract", methods=["POST"])
@optional_auth
def v2_lab_presentation_extract():
    """willab slide-deck extract (UX Wave 4 §S / BE-S2). GUEST-ALLOWED.

    Upload a PDF → (a) per-slide {title, body} text for the editable form +
    analysis, and (b) the stored PDF the FE renders with PDF.js. Parse-and-
    store: the PDF is stored + a browser-fetchable URL returned as
    presentation_ref. (PDF-only — PPTX returns 415 "export to PDF"; the
    server-side PPTX→PDF path was dropped, see services/deck_parser.py.)

      200 { slides:[{title,body}], presentation_ref, slide_count, source, warnings }
      400 missing/empty file · 413 too large · 415 unsupported · 422 unparseable
    """
    try:
        if "file" not in request.files:
            return jsonify({"code": "INVALID_INPUT", "error": "file is required"}), 400
        f = request.files.get("file")
        from services.deck_parser import SUPPORTED_EXTS
        ext = os.path.splitext(f.filename or "")[1].lower()
        if ext not in SUPPORTED_EXTS:
            return jsonify({
                "code": "UNSUPPORTED_TYPE",
                "error": (
                    "Upload a PDF. (Export PowerPoint/Keynote to PDF first — "
                    "PPTX isn't supported yet.)"
                ),
            }), 415
        data = f.read()
        if not data:
            return jsonify({"code": "INVALID_INPUT", "error": "file is empty"}), 400
        if len(data) > _PRESENTATION_MAX_MB * 1024 * 1024:
            return jsonify({
                "code": "FILE_TOO_LARGE",
                "error": f"file exceeds {_PRESENTATION_MAX_MB}MB",
            }), 413

        from services.deck_parser import extract_deck, DeckParseError
        try:
            parsed = extract_deck(data, f.filename or "deck")
        except DeckParseError as de:
            return jsonify({"code": "UNPARSEABLE", "error": str(de)}), 422
        except Exception as pe:
            logger.error("presentation extract failed: %s", pe, exc_info=True)
            return jsonify({"code": "UNPARSEABLE", "error": "Could not parse the file."}), 422

        # Store the served PDF; return a browser-fetchable URL. Prefer the
        # stable public URL (persists for history scroll-back); fall back to a
        # presigned GET only if the public base isn't configured.
        from services.coach_video_storage import (
            put_coach_object_bytes, coach_media_public_url,
        )
        key = f"willab_presentations/{uuid.uuid4().hex}.pdf"
        try:
            put_coach_object_bytes(
                "coach_feedback_videos", key, parsed["pdf_bytes"], "application/pdf",
            )
        except Exception as se:
            logger.error("presentation store failed: %s", se, exc_info=True)
            return jsonify({"code": "V2_ERROR", "error": "Could not store the presentation."}), 502
        presentation_ref = coach_media_public_url(key)
        if not presentation_ref:
            from services.coach_video_storage import presigned_get_coach_object
            presentation_ref = presigned_get_coach_object(
                "coach_feedback_videos", key, expires_in=604800,
            )
        slides = parsed["slides"]
        return jsonify({
            "slides": slides,
            "presentation_ref": presentation_ref,
            "slide_count": len(slides),
            "source": parsed["source"],
            "warnings": parsed.get("warnings") or [],
        }), 200
    except Exception as e:
        logger.error("lab/presentation/extract failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to process presentation"}), 500


@v2_bp.route("/coach/audits", methods=["POST"])
@require_admin_or_coach
def v2_coach_create_audit():
    """willab Audit Delivery (Prompt C §3 C1) — a coach uploads a PDF audit for
    a user. Stores the PDF in R2, records the row, and emails the user a link.

    multipart/form-data:
      pdf_file   (required) the audit PDF
      user_id    (required) the user it's for
      name       (required) e.g. "Speaking Impact Audit, Booksy pitch"
      audit_date (optional) ISO timestamp; defaults to now()

    201 { id, name, audit_date, email_sent }
    400 INVALID_INPUT · 413 FILE_TOO_LARGE · 415 UNSUPPORTED_TYPE · 502 V2_ERROR
    """
    try:
        form = request.form or {}
        target_user = (form.get("user_id") or "").strip()
        name = (form.get("name") or "").strip()
        audit_date = (form.get("audit_date") or "").strip() or None
        if not _is_valid_uuid(target_user):
            return jsonify({"code": "INVALID_INPUT", "error": "user_id must be a UUID"}), 400
        if not name:
            return jsonify({"code": "INVALID_INPUT", "error": "name is required"}), 400

        f = request.files.get("pdf_file")
        if f is None or not (f.filename or "").strip():
            return jsonify({"code": "INVALID_INPUT", "error": "pdf_file is required"}), 400
        ext = os.path.splitext(secure_filename(f.filename or ""))[1].lower()
        if ext != ".pdf":
            return jsonify({
                "code": "UNSUPPORTED_TYPE",
                "error": "Upload a PDF. (Export to PDF first.)",
            }), 415
        data = f.read() or b""
        if not data:
            return jsonify({"code": "INVALID_INPUT", "error": "pdf_file is empty"}), 400
        if len(data) > _PRESENTATION_MAX_MB * 1024 * 1024:
            return jsonify({
                "code": "FILE_TOO_LARGE",
                "error": f"file exceeds {_PRESENTATION_MAX_MB}MB",
            }), 413

        from services.coach_video_storage import put_coach_object_bytes
        key = f"willab_audits/{uuid.uuid4().hex}.pdf"
        try:
            put_coach_object_bytes("coach_feedback_videos", key, data, "application/pdf")
        except Exception as se:
            logger.error("audit store failed user=%s: %s", target_user, se, exc_info=True)
            return jsonify({"code": "V2_ERROR", "error": "Could not store the audit."}), 502

        row = db.insert_user_audit(target_user, name, key, audit_date)
        if not row:
            return jsonify({"code": "V2_ERROR", "error": "Could not record the audit."}), 502

        # Notify the user (best-effort — the upload already succeeded).
        email_sent = False
        try:
            from services.audit_email import send_audit_ready_email
            email_sent = send_audit_ready_email(target_user)
        except Exception as ee:
            logger.warning("audit: email dispatch failed user=%s: %s", target_user, ee)

        logger.info("audit: uploaded user=%s id=%s email_sent=%s",
                    target_user, row.get("id"), email_sent)
        return jsonify({
            "id": row.get("id"),
            "name": row.get("name"),
            "audit_date": row.get("audit_date"),
            "email_sent": email_sent,
        }), 201
    except Exception as e:
        logger.error("coach/audits POST failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to upload audit"}), 500


@v2_bp.route("/user/audits", methods=["GET"])
@require_auth
def v2_user_get_audits():
    """willab Audit Delivery (Prompt C §3 C2) — the signed-in user's audits,
    newest first, each with a short-lived signed PDF URL. Empty list when none
    (NEVER 404).

    200 { audits: [ { id, name, date, pdf_url } ] }
    """
    try:
        from services.coach_video_storage import (
            coach_media_public_url, presigned_get_coach_object,
        )
        rows = db.list_user_audits(request.user_id) or []
        audits = []
        for r in rows:
            key = r.get("storage_path") or ""
            url = coach_media_public_url(key) if key else None
            if not url and key:
                url = presigned_get_coach_object(
                    "coach_feedback_videos", key, expires_in=604800,
                )
            audits.append({
                "id": r.get("id"),
                "name": r.get("name"),
                "date": r.get("audit_date"),
                "pdf_url": url,
            })
        return jsonify({"audits": audits}), 200
    except Exception as e:
        logger.error("user/audits GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load audits"}), 500


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


@v2_bp.route("/lab/recordings", methods=["POST"])
@optional_auth
def v2_lab_create_recording():
    """willab Lab upload — multipart, synchronous, guest-allowed (§3.3).

    Multipart form fields:
      audio_file            (required) the recording
      topic                 (required) session_context topic
      audience              (optional)
      target_length_seconds (optional, int)
      domain_vocabulary     (optional, JSON array or comma-separated)
      guest_session_id      (optional) reuse an existing guest session;
                            else a fresh one is minted + returned

    Flow (invariant order):
      1. read audio
      2. validate session_context (topic required, §3.2/§5.10)
      3. MIN-CONTENT GATE before any processing (§5.5) → 422 re-record
      4. store parent audio + guest session + recording + session_context
      5. process → §3.3 Readout payload (sync)

    Responses:
      201 { session_id, recording_id, session_context, readout:{snippets[]} }
      400 INVALID_INPUT / AUDIO_FILE_REQUIRED — bad multipart
      413 FILE_TOO_LARGE
      422 INVALID_INPUT (topic) | RECORDING_REJECTED (gate: too_short/
          no_speech — FE shows re-record)
      500 V2_ERROR
    """
    try:
        # ── 1. audio ────────────────────────────────────────────────
        if "audio_file" not in request.files:
            return jsonify({
                "code": "AUDIO_FILE_REQUIRED",
                "error": "audio_file is required",
            }), 400
        audio_file = request.files.get("audio_file")
        max_bytes = _LAB_MAX_AUDIO_MB * 1024 * 1024
        if (request.content_length or 0) > max_bytes:
            return jsonify({
                "code": "FILE_TOO_LARGE",
                "error": f"audio_file exceeds {_LAB_MAX_AUDIO_MB}MB",
            }), 413
        file_bytes = audio_file.read()
        if not file_bytes:
            return jsonify({
                "code": "INVALID_INPUT", "error": "audio_file is empty",
            }), 400
        if len(file_bytes) > max_bytes:
            return jsonify({
                "code": "FILE_TOO_LARGE",
                "error": f"audio_file exceeds {_LAB_MAX_AUDIO_MB}MB",
            }), 413

        # ── 2. session_context (inline; topic required) ─────────────
        from services.intake_context import (
            IntakeContextError, validate_intake_context_body,
        )
        form = request.form or {}
        target_raw = form.get("target_length_seconds")
        try:
            target_len = int(target_raw) if target_raw not in (None, "") else None
        except (TypeError, ValueError):
            target_len = None
        def _form_json(name):
            raw = form.get(name)
            if raw in (None, ""):
                return None
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return None
        try:
            session_context = validate_intake_context_body({
                "topic": form.get("topic"),
                "audience": form.get("audience"),
                "target_length_seconds": target_len,
                "domain_vocabulary": _parse_lab_vocabulary(
                    form.get("domain_vocabulary"),
                ),
                # Slide-deck context (UX Wave 4 §S) — JSON multipart fields,
                # same pattern as domain_vocabulary.
                "slides": _form_json("slides"),
                "presentation_ref": form.get("presentation_ref") or None,
                "slide_advances": _form_json("slide_advances"),
            }, require_topic=True)
        except IntakeContextError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 422

        # Whisper-prime fallback: the FE dropped the keywords input, so
        # domain_vocabulary now arrives empty. Auto-seed it from the user's
        # DOMAIN so domain jargon still primes Whisper (transcription-only —
        # feeds nothing else; an explicit list would still win). Authed only:
        # guests have no profile domain → stays empty (slide titles still
        # prime). Best-effort.
        if getattr(request, "user_id", None):
            try:
                from services.domains import resolve_whisper_vocab
                _dom = (db.get_user_profile(request.user_id) or {}).get("domain")
                session_context["domain_vocabulary"] = resolve_whisper_vocab(
                    session_context.get("domain_vocabulary"), _dom,
                )
            except Exception as _ve:
                logger.warning("lab: domain-vocab autoseed failed: %s", _ve)

        # ── 3. MIN-CONTENT GATE before processing (§5.5) ────────────
        from services.min_content_gate import evaluate_min_content_bytes
        gate = evaluate_min_content_bytes(file_bytes)
        if not gate["ok"]:
            return jsonify({
                "code": "RECORDING_REJECTED",
                "error": (
                    "Recording too short — record at least 60 seconds."
                    if gate["reason"] == "too_short"
                    else "No speech detected — try recording again."
                ),
                "gate": gate,  # {reason, duration_sec, voiced_sec, thresholds}
            }), 422

        # ── 4. store + session + recording ──────────────────────────
        from services.coach_video_storage import (
            put_coach_object_bytes, coach_media_public_url,
        )
        bucket = "coach_feedback_videos"
        guest_session_id = (
            (form.get("guest_session_id") or "").strip()
            or str(uuid.uuid4())
        )
        recording_id = str(uuid.uuid4())
        ext = os.path.splitext(audio_file.filename or "")[1] or ".webm"
        parent_key = f"willab_lab/{guest_session_id}/recording_{uuid.uuid4().hex}{ext}"
        content_type = (audio_file.mimetype or "audio/webm").strip() or "audio/webm"

        try:
            put_coach_object_bytes(bucket, parent_key, file_bytes, content_type)
        except Exception as up_err:
            logger.error("lab: parent upload failed: %s", up_err, exc_info=True)
            return jsonify({
                "code": "V2_ERROR", "error": "Failed to store recording",
            }), 500
        parent_url = coach_media_public_url(parent_key) or f"s3://{bucket}/{parent_key}"

        # Guest session (create only if it doesn't already exist).
        if not db.v2_get_session_by_id(guest_session_id):
            try:
                db.v2_create_guest_session(guest_session_id)
            except Exception as se:
                logger.error("lab: guest session create failed: %s", se, exc_info=True)
                return jsonify({
                    "code": "V2_ERROR", "error": "Failed to create session",
                }), 500

        # Persist session_context on the session row.
        db.set_session_intake_context(guest_session_id, session_context)
        # Mark as a willab Lab session so the history list + send-gate
        # origin path can find it (best-effort; the recording_origin on
        # the recording row is the send-gate's primary gate).
        db.set_session_source(guest_session_id, "audit_upload")

        # Explore-session arc (Prompt A §3) — link the takes of the SAME talk
        # so they're comparable. Standalone recordings (no explore_session) →
        # arc_id stays None; this is fully opt-in.
        from services.explore_arc import resolve_arc
        arc_id, take_index = resolve_arc(
            form.get("explore_session"),
            form.get("arc_id"),
            form.get("take_index"),
        )
        arc_take_count = None
        if arc_id:
            db.set_session_arc(guest_session_id, arc_id, take_index)
            arc_take_count = db.get_arc_take_count(arc_id)

        # Pre-recording feeling (U10) — the user named their state before this
        # take (nervous/excited/calm/unsure). Split-sink / AC-9: stored
        # privately for the audit-stage correlation, NEVER scored or echoed.
        # Optional + best-effort: a missing/unknown value just stores nothing.
        from services.feelings import normalize_feeling
        _feeling = normalize_feeling(form.get("feeling"))
        if _feeling:
            db.insert_recording_feeling(
                session_id=guest_session_id, feeling=_feeling,
                user_id=getattr(request, "user_id", None),
                recording_id=recording_id, arc_id=arc_id, take_index=take_index,
            )

        # Recording row (recording_origin fallback for pre-migration envs).
        # BE-1 / S2 — persist the gate's measured duration (was hardcoded 0 +
        # discarded). This is the source for cumulative recording-progress.
        _rec_duration = 0
        try:
            _rec_duration = int(round(float(gate.get("duration_sec") or 0)))
        except (TypeError, ValueError):
            _rec_duration = 0
        rec_payload = {
            "id": recording_id, "user_id": None,
            "session_v2_id": guest_session_id,
            "storage_path": parent_key, "audio_url": parent_url,
            "duration": _rec_duration,
            "recording_origin": "willab_lab",
        }
        try:
            db.create_recording(rec_payload)
        except Exception as ce:
            err_low = str(ce).lower()
            if "recording_origin" in err_low or "pgrst204" in err_low:
                db.create_recording({k: v for k, v in rec_payload.items() if k != "recording_origin"})
            else:
                logger.error("lab: create_recording failed: %s", ce, exc_info=True)
                return jsonify({
                    "code": "V2_ERROR", "error": "Failed to create recording",
                }), 500
        try:
            db.v2_set_guest_session_recording(guest_session_id, recording_id)
        except Exception as le:
            logger.warning("lab: link recording failed (non-fatal): %s", le)

        # ── 5. process → Readout payload (sync) ─────────────────────
        from services.lab_recording import process_lab_recording
        readout = process_lab_recording(
            session_id=guest_session_id,
            user_id=None,
            recording_id=recording_id,
            audio_bytes=file_bytes,
            filename=audio_file.filename or "lab.webm",
            session_context=session_context,
            parent_audio_url=parent_url,
        )

        logger.info(
            "lab: recording processed sid=%s rec=%s snippets=%d",
            guest_session_id, recording_id,
            len(readout.get("snippets") or []),
        )

        # Explore-session cadence (Prompt A §6 C3) — after a take in an arc,
        # invite the NEXT take as a Lounge bubble. Needs an authenticated
        # owner (lounge is per-user); guests get no cadence. Best-effort +
        # idempotent — never blocks or double-fires; never touches the
        # readout response.
        _cad_user = getattr(request, "user_id", None)
        if _cad_user and arc_id:
            try:
                from services.session_cadence import fire_post_take
                _goal = (db.get_user_profile(_cad_user) or {}).get("goal")
                _spark = str(form.get("spark") or "").strip().lower() in (
                    "1", "true", "yes", "on",
                )
                fire_post_take(
                    _cad_user, arc_id, take_index,
                    take_count=arc_take_count,
                    spark_enabled=_spark,
                    goal=_goal,
                )
            except Exception as _ce:
                logger.warning("lab: cadence fire failed sid=%s: %s",
                               guest_session_id, _ce)

        # Recording-progress toward the first audit (BE-4) — so the FE can
        # refresh the "X:XX left to unlock" line IMMEDIATELY instead of showing
        # a stale value until the next session load. This upload's session is a
        # guest session (user_id=None) and is attributed to the user only on a
        # later claim/merge, so it is NOT yet in the cumulative sum — we project
        # it by ADDING this recording's duration on top. The authoritative value
        # remains GET /user/recording-progress after the claim. Auth-only +
        # best-effort: omitted for guests / on any hiccup.
        recording_progress = None
        _prog_user = getattr(request, "user_id", None)
        if _prog_user:
            try:
                from services.user_audit import AUDIT_UNLOCK_SECONDS
                _base = int(db.v2_get_cumulative_recorded_seconds(str(_prog_user)) or 0)
                _projected = _base + int(_rec_duration or 0)
                recording_progress = {
                    "recorded_seconds": _projected,
                    "threshold_seconds": AUDIT_UNLOCK_SECONDS,
                    "unlocked": _projected >= AUDIT_UNLOCK_SECONDS,
                }
            except Exception as _pe:
                logger.warning("lab: recording_progress projection failed sid=%s: %s",
                               guest_session_id, _pe)

        return jsonify({
            "status": "ok",
            "session_id": guest_session_id,
            "recording_id": recording_id,
            # A fresh upload is always readout_ready (processed, not yet sent).
            # Explicit so the 201 is self-describing + matches the re-read /
            # history `state` field (FE asked: Q2 of the last-pass handoff).
            "state": "readout_ready",
            "session_context": session_context,
            "readout": readout,
            # Explore-session arc (Prompt A §3) — null for standalone takes.
            "arc_id": arc_id,
            "take_index": take_index,
            "take_count": arc_take_count,
            # Fresh audit progress (BE-4) — null for guests; see note above.
            "recording_progress": recording_progress,
        }), 201

    except Exception as e:
        logger.error("lab/recordings POST failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to process recording",
        }), 500


# ── willab beta — Lounge thread persistence (BE contract §3.15) ─────
#
# Per-user Lounge chat thread that survives reload + device switch.
# FE rehydrates on mount (GET, cursor-paged) and appends per turn
# (POST, idempotent batch — also the merge-on-signup path). Text only,
# never audio; never in the coach packet; never profiled (§2/AC-6).
#
# Validation + page shaping live in services/lounge_messages.py; the
# queries in services/db.py. These handlers are thin auth + wiring.


@v2_bp.route("/user/lounge/messages", methods=["GET"])
@require_auth
def v2_user_lounge_messages_get():
    """Rehydrate the Lounge thread (newest page) or page older.

    Query:
      limit  (default 50, max 200)  — page size
      before (ISO-8601, optional)   — cursor; rows strictly older than
                                      this. Absent → latest page.

    Response 200 (BE contract §3.15):
      {
        "messages": [ {id, client_id, role, kind, body, metadata,
                       client_created_at} ],   // ASC by client_created_at
        "has_more": bool,                       // older messages exist
        "oldest_cursor": "<iso>" | null         // pass as ?before= for
                                                // the next older page
      }

    No `before` → latest `limit` (bottom of thread). `before=<cursor>`
    → the page immediately older. Empty thread / missing table →
    empty page (the Lounge renders blank, never errors).
    """
    try:
        from services.lounge_messages import (
            LoungeValidationError,
            parse_limit,
            shape_lounge_page,
            validate_before_cursor,
        )

        limit = parse_limit(request.args.get("limit"))
        try:
            before = validate_before_cursor(request.args.get("before"))
        except LoungeValidationError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 400

        rows_desc = db.get_lounge_messages_page(
            request.user_id, limit=limit, before=before,
        )
        return jsonify(shape_lounge_page(rows_desc, limit)), 200

    except Exception as e:
        logger.error(
            "user/lounge/messages GET failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Soft-fail to an empty page so the Lounge mounts rather than
        # showing an error on its home surface.
        return jsonify({
            "messages": [], "has_more": False, "oldest_cursor": None,
        }), 200


@v2_bp.route("/user/lounge/messages", methods=["POST"])
@require_auth
def v2_user_lounge_messages_post():
    """Idempotent batch append (also the merge-on-signup path).

    Body:
      { "messages": [ { client_id, role, kind, body, metadata?,
                        client_created_at } ] }

    The FE sends the user turn + bot reply together after each turn
    (FE-append, §7.6), and system lines as they happen. On signup it
    replays the localStorage thread as batches through THIS endpoint
    (§7.8 — no separate /merge alias); client_created_at preserves
    order, client_id prevents dupes.

    Idempotent on (user_id, client_id) — re-sending a stored client_id
    is a no-op upsert, not a duplicate.

    Responses:
      200 { "messages": [ ...persisted rows with server id ] }
      422 INVALID_INPUT — validator rejected (role/kind enum, non-UUID
                          client_id, bad client_created_at, batch over
                          200, body over cap)
      500 V2_ERROR — persist failed
    """
    try:
        from services.lounge_messages import (
            LoungeValidationError,
            validate_lounge_batch,
        )

        body = request.get_json(silent=True) or {}
        try:
            cleaned = validate_lounge_batch(body)
        except LoungeValidationError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 422

        persisted = db.insert_lounge_messages(request.user_id, cleaned)
        if not persisted:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to persist lounge messages",
            }), 500

        logger.info(
            "user/lounge/messages.append user=%s count=%d",
            request.user_id, len(cleaned),
        )
        return jsonify({"messages": persisted}), 200

    except Exception as e:
        logger.error(
            "user/lounge/messages POST failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to append lounge messages",
        }), 500


@v2_bp.route("/user/lounge/messages", methods=["DELETE"])
@require_auth
def v2_user_lounge_messages_delete():
    """Clear the user's entire Lounge thread (BE contract §3.14 —
    user-deletable privacy commitment). Account deletion is handled
    separately by the ON DELETE CASCADE FK; this is the explicit
    'clear my Lounge' action.

    Responses:
      204 — thread cleared
      500 V2_ERROR — delete failed
    """
    try:
        ok = db.delete_lounge_messages_for_user(request.user_id)
        if not ok:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to clear lounge thread",
            }), 500
        logger.info("user/lounge/messages.cleared user=%s", request.user_id)
        return ("", 204)
    except Exception as e:
        logger.error(
            "user/lounge/messages DELETE failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to clear lounge thread",
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
# Auth: @require_auth — the opener fires inside the authenticated
# onboarding flow, after JWT issue. Pre-auth users see a different
# landing path that doesn't touch this endpoint.
#
# Canonical PIVOT_LINE lives in services/onboarding_opener.py and
# is never LLM-generated. The LLM only produces the optional ack
# line that bridges user reply → punchline.


@v2_bp.route("/onboarding/opener/start", methods=["POST"])
@require_auth
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
@require_auth
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
