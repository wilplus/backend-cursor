"""The guest funnel and account merge: /v2/public/* and /v2/auth/*.

The shaky-voice upload + claim, the afterwards video, signup, and the
anonymous-session merge that adopts a guest's takes into the account they
create at Send.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 5);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging

import sentry_sdk
from flask import jsonify, request

import mimetypes
import os
import uuid
from werkzeug.utils import secure_filename

from auth import require_auth
from routes.v2.common import _client_ip_from_request, _is_valid_uuid
from services.rate_limits import guest_funnel_limit
from config import Config
from routes.v2.blueprint import v2_bp
from services.db import db

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
        # ── THE SEED GRANT IS GONE (founder 2026-08-12). "New users do not
        # need an extra seed grant on top of the tier allowance. The standard
        # 12,000/month free tier is perfectly sufficient."
        #
        # This block ensured a brand-new user held the legacy 15 credits before
        # any spend. Under tokens the equivalent is not needed and would be
        # actively wrong: token_account.ensure_period_current seeds the account
        # on FIRST TOUCH with the tier's full monthly grant, lazily and
        # self-healingly. A second seed on the send path would be a parallel
        # grant with its own idempotency to get right, racing the one that
        # already works.
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
