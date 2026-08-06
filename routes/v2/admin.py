"""The /v2/admin/* surface: the admin console's reads and writes.

Student/session inspection, snippet coaching rationale + annotations, the
question pool, the directives queue, the next-session icebreaker, the
learning-model train/status/trace endpoints and the review queue.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 5);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging

import sentry_sdk
from flask import jsonify, request

import hashlib
from datetime import datetime, timezone
from typing import Any
from werkzeug.utils import secure_filename

from routes.admin import require_admin, require_admin_or_coach
from routes.v2.common import (
    _COACH_PSEUDONYM_SALT,
    _is_valid_uuid,
    _resolve_snippet_audio_url,
)
from services.rate_limits import heavy_limit, llm_limit, regenerate_limit
from config import Config
from routes.v2.blueprint import v2_bp
from services.db import db
from services.snippet_values import resolve_all

logger = logging.getLogger(__name__)
config = Config()


# ---------- Admin ----------
@v2_bp.route("/admin/health", methods=["GET"])
@require_admin
def v2_admin_health():
    """Debug: verify admin routes are reachable. Returns 200 if token is valid and admin."""
    return jsonify({"status": "ok", "message": "Admin API reachable"}), 200


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
                # PM-9: the six denormalized columns are dead on the live path
                # (services/snippet_values) — the admin metrics panel has been
                # rendering six NULLs for every auto-extracted snippet, which
                # is every snippet the lab pipeline produces.
                "metrics": resolve_all(s),
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
