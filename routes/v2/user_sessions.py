"""The signed-in user's takes and readouts surface: session results/status,
intake context, take/session/project deletes, readout re-reads, transcript
edits, suggestion feedback and the trainings list.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 3);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging
import uuid
from datetime import datetime, timezone

import sentry_sdk
from flask import jsonify, request

from auth import optional_auth, require_auth
from config import Config
from routes.admin import is_admin, is_coach
from routes.v2.arcs import (
    _arc_audit_paid,
    _presentation_group_key,
    _reassemble_after_decision,
)
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid, _resolve_snippet_audio_url
from services.db import db
from services.create_take import session_owned_by_principal
from services.project_ownership import GUEST_OWNER_HEADER
from services.project_repository import ProjectRepository
from services.snippet_values import resolve_all

logger = logging.getLogger(__name__)
config = Config()


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

        # Founder re-lock 2026-07-06: the automatic results read is never
        # 402-gated (payment scopes only the coach HUMAN layer, and this legacy
        # route carries the old coaching shape the willab FE doesn't use).

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
                    # PM-9: the denormalized columns are dead on the live
                    # path (services/snippet_values), so this returned six
                    # NULLs. Split-sink unchanged — these are the same raw
                    # reference figures the user-lane panel already shows,
                    # with no verdict, flag or characterization attached.
                    "metrics": resolve_all(s),
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
def _user_presentation_groups(user_id: str) -> dict:
    """Compatibility grouping for historical project deletion.

    New code uses immutable project IDs. Historical sessions that predate the
    canonical project table remain groupable by their deck hash until their
    owner migrates or deletes them.
    """
    groups: dict = {}
    for session in (db.v2_list_user_lab_sessions(user_id) or []):
        sid = str(session.get("id") or "")
        if not sid:
            continue
        ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
        slides = (ctx or {}).get("slides") or []
        if not slides:
            continue
        pid = _presentation_group_key(ctx)
        if not pid:
            continue
        groups.setdefault(pid, []).append((session.get("created_at") or "", sid))
    return {
        pid: [sid for _, sid in sorted(items, key=lambda t: (t[0], t[1]))]
        for pid, items in groups.items()
    }


def _hard_delete_session_for_user(user_id: str, session_id: str) -> None:
    """Durably delete one historical take through the owner-scoped adapter."""
    try:
        db.v2_delete_session(session_id, user_id)
    except Exception as e:
        logger.warning("presentation delete: session delete failed sid=%s err=%s", session_id, e)


def _user_presentation_sessions_all(user_id: str, presentation_id: str) -> list:
    """EVERY lab session of this user whose deck hashes to presentation_id —
    the COMPLETE historical delete set. It is derived from owner-scoped
    sessions rather than any retired feedback collection, so a deleted
    training cannot resurface. Chronological (created_at, id)."""
    pid = (presentation_id or "").strip()
    if not pid:
        return []
    matches = []
    for s in (db.v2_list_user_lab_sessions(user_id) or []):
        ctx = s.get("intake_context") if isinstance(
            s.get("intake_context"), dict) else {}
        # Same key the grouping uses — a delete set derived differently from
        # the group it claims to delete is how a "delete one training" wipes
        # every deckless session the user owns.
        if _presentation_group_key(ctx) == pid:
            matches.append((s.get("created_at") or "", str(s.get("id"))))
    return [sid for _, sid in sorted(matches)]


@v2_bp.route("/user/presentations/<presentation_id>", methods=["DELETE"])
@require_auth
def v2_user_delete_presentation(presentation_id):
    """Delete a whole presentation (deck) and ALL its takes — owner-scoped,
    HARD delete (the recordings are gone everywhere, incl. coach history).
    Deletes the complete owner-scoped session set for the deck (see
    ``_user_presentation_sessions_all``).
    200 {deleted_sessions} · 404 if the user has no such presentation."""
    try:
        uid = str(request.user_id)
        sids = _user_presentation_sessions_all(uid, presentation_id)
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
    owner-scoped HARD delete. take_number is 1-based and chronological.
    200 · 400 bad take_number · 404 unknown presentation/take."""
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


@v2_bp.route("/user/sessions/<session_id>", methods=["DELETE"])
@require_auth
def v2_user_delete_session(session_id):
    """Delete ONE recording session directly by id — owner-scoped HARD delete
    (library rows + session; same helper as the presentation/take deletes).
    This is the delete path for DECKLESS trainings, which have no
    presentation_id and were previously undeletable (backlog 4.4).
    200 {deleted_session} · 400 bad uuid · 404 not found / not the owner."""
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT", "error": "session_id must be a valid UUID",
        }), 400
    try:
        uid = str(request.user_id)
        session = db.v2_get_session_by_id(session_id)
        if not session or str(session.get("user_id") or "") != uid:
            return jsonify({
                "code": "SESSION_NOT_FOUND", "error": "Session not found",
            }), 404
        _hard_delete_session_for_user(uid, session_id)
        logger.info("session deleted user=%s sid=%s", uid, session_id)
        return jsonify({"status": "ok", "deleted_session": session_id}), 200
    except Exception as e:
        logger.error("user/sessions DELETE failed sid=%s: %s",
                     session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to delete session"}), 500


@v2_bp.route("/user/sessions/<session_id>/readout", methods=["GET"])
@require_auth
def v2_user_get_session_readout(session_id):
    """Re-read the canonical §3.3 Readout for one of the user's sessions.

    Serves parked-restore (the report loads identically an hour later)
    and history-detail (tap a past report). Re-derived from PERSISTED
    snippets (features + the persisted stickiness), so it matches the
    upload-time payload byte-for-byte. Post-publish it also carries canonical
    exact-evidence FeedbackItems and a separate take-level coach-review layer.

    Owner-scoped: non-owner → 404 (no existence leak).

    Response 200:
      { "session_id", "published": bool, "state": str,
        "readout": {
          "snippets": [ {            # §3.3, CHRONOLOGICAL (start_offset_ms ASC)
              id, index, transcript, audio_ref, start_offset_ms, duration_ms,
              features, stickiness,
              slide: { index, title, body },     # slide on screen when spoken
                                                 # (tap timeline) — GROUP BY slide.index
              breakthrough: bool, breakthrough_note,   # coach-confirmed (F2)
          } ],
          "slides"?: [...], "presentation_ref"?: str,   # the deck (render once/group)
          "feedback_items": [...],
          "coach_review": { "overall_message"?, "video_ref"? },
        } }

    The per-snippet `slide` (slide_alignment.slide_for_snippet) plus top-level
    `slides` / `presentation_ref` are the contract the FE per-slide readout
    groups by (one slide header → its snippets stacked chronologically) — don't
    drop them.
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

        # Async analysis (founder 2026-07-15) — while the background daemon
        # is still running (or after it failed), serve the job state instead
        # of a partial readout; the FE polls until ready|failed. NULL state =
        # legacy/sync rows → fall through to the normal read.
        _an_state = session.get("analysis_state")
        if _an_state == "processing":
            return jsonify({
                "session_id": session_id, "published": False,
                "state": "processing", "analysis_state": "processing",
                "readout": None,
            }), 200
        if _an_state == "failed":
            return jsonify({
                "session_id": session_id, "published": False,
                "state": "failed", "analysis_state": "failed",
                "readout": None,
            }), 200

        # Founder re-lock 2026-07-06: the AUTOMATIC readout AND the coach's
        # per-take layer (note, corrected transcript, breakthrough badge+video)
        # are NEVER 402-gated — every take of every arc reads free the instant
        # the coach saves + surfaces it. Payment gates ONLY the four dedicated
        # deliverables (ideal text, breakthroughs list, game, library), not
        # this readout. audit_paid is kept as a top-level echo (the FE uses it
        # to contextualize those OTHER surfaces' CTAs from this screen).
        _audit_paid = _arc_audit_paid(
            session.get("arc_id"), request.user_id,
        )

        from services.lab_recording import build_readout_from_session
        # include_upgrade_cards=False — USER surface: the manager engine is
        # the sole gatekeeper (founder 2026-08-10); ungated LLM rewrite
        # cards do not ride the student payload.
        readout = build_readout_from_session(
            session_id, audit_paid=_audit_paid, include_upgrade_cards=False,
        )

        published = bool(session.get("results_published_at"))
        if published:
            state = "insights_ready"
        elif session.get("status") == "pending_admin_review":
            state = "review_pending"
        else:
            state = "readout_ready"

        return jsonify({
            "session_id": session_id,
            "published": published,
            "state": state,
            # The async job's TERMINAL signal, unambiguous for the FE poll:
            # anything past processing|failed is "ready" (NULL = legacy/sync
            # rows, only ever persisted after a completed analysis).
            "analysis_state": "ready",
            # Per-arc paid flag, mirrored top-level (also inside the readout) —
            # an echo for the FE's OTHER paid-deliverable CTAs; this readout's
            # own coach layer is unconditionally free (2026-07-06 re-price).
            "audit_paid": _audit_paid,
            "readout": readout,
        }), 200
    except Exception as e:
        logger.error(
            "user/sessions/<id>/readout GET failed sid=%s err=%s",
            session_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch readout"}), 500


_TRANSCRIPT_EDIT_MAX_LEN = 2000


@v2_bp.route("/user/sessions/<session_id>/transcript-edits", methods=["PUT"])
@optional_auth
def v2_user_put_transcript_edit(session_id):
    """Save the user's corrected transcript text for ONE target on their own
    readout (founder 2026-07-07) — either a snippet's transcript or a
    deckless full-transcript chunk. Display layer ONLY: the coach keeps
    reviewing the ORIGINAL transcript; readout reads carry the edit as
    ``user_edited_text`` beside (never instead of) ``transcript``.

    GUEST-capable: the matching signed Guest ID has the same authority as an
    authenticated owner. A bare session UUID is never authorization. Edits
    ride the Take, so the atomic post-signup claim preserves them.

    Body: { "text": str (required, ≤2000 chars),
            "snippet_id": uuid XOR "chunk_index": int≥0 }

    Response 200 { saved: true, session_id, snippet_id?, chunk_index? }
             400 INVALID_INPUT · 404 SESSION_NOT_FOUND · 500 V2_ERROR
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
        _caller = getattr(request, "user_id", None)
        if not session_owned_by_principal(
            session,
            repository=ProjectRepository(db),
            user_id=_caller,
            guest_token=request.headers.get(GUEST_OWNER_HEADER),
        ):
            return jsonify({
                "code": "SESSION_NOT_FOUND", "error": "Session not found",
            }), 404

        body = request.get_json(silent=True) or {}
        # Type-check BEFORE .strip() — a truthy non-string ({"text": 5})
        # must be a clean 400, not an AttributeError → 500 + Sentry noise
        # (review finding).
        text_raw = body.get("text")
        if text_raw is not None and not isinstance(text_raw, str):
            return jsonify({
                "code": "INVALID_INPUT", "error": "text must be a string",
            }), 400
        text = (text_raw or "").strip()
        if not text:
            return jsonify({
                "code": "INVALID_INPUT", "error": "text is required",
            }), 400
        if len(text) > _TRANSCRIPT_EDIT_MAX_LEN:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": f"text exceeds {_TRANSCRIPT_EDIT_MAX_LEN} characters",
            }), 400

        snippet_raw = body.get("snippet_id")
        if snippet_raw is not None and not isinstance(snippet_raw, str):
            return jsonify({
                "code": "INVALID_INPUT", "error": "snippet_id must be a string",
            }), 400
        snippet_id = (snippet_raw or "").strip() or None
        chunk_index = body.get("chunk_index")
        has_snip = snippet_id is not None
        has_chunk = isinstance(chunk_index, int) and not isinstance(
            chunk_index, bool) and chunk_index >= 0
        if has_snip == has_chunk:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "exactly one of snippet_id or chunk_index is required",
            }), 400
        if has_snip and not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT", "error": "snippet_id must be a UUID",
            }), 400

        # Target-existence checks (review must-fix): an edit may only land on
        # a target this session actually has — otherwise orphan rows accrue
        # invisibly (accepted with 200 but never surfaced by the readout
        # fold), unbounded chunk_index rows bloat every readout re-read
        # (including the coach view), and an INT4-overflow chunk_index would
        # 500 at insert instead of 400 here.
        if has_snip:
            snip_row = db.get_snippet_by_id(snippet_id)
            if not snip_row or str(snip_row.get("session_id") or "") != str(session_id):
                return jsonify({
                    "code": "SNIPPET_NOT_FOUND",
                    "error": "That moment is not part of this session",
                }), 404
        else:
            # SAME helper the readout fold uses — the two counts can't drift.
            from services.slide_word_split import deckless_chunks_from_stx
            _stx = db.get_session_slide_transcripts(session_id) or []
            n_chunks = len(deckless_chunks_from_stx(_stx))
            if chunk_index >= n_chunks:
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "chunk_index is out of range for this session",
                }), 400

        ok = db.upsert_user_transcript_edit(
            str(session_id),
            snippet_id=snippet_id if has_snip else None,
            chunk_index=chunk_index if has_chunk else None,
            text=text,
        )
        if not ok:
            return jsonify({
                "code": "V2_ERROR", "error": "Could not save the edit",
            }), 500
        out = {"saved": True, "session_id": session_id}
        if has_snip:
            out["snippet_id"] = snippet_id
        else:
            out["chunk_index"] = chunk_index
        return jsonify(out), 200
    except Exception as e:
        logger.error(
            "transcript-edit PUT failed sid=%s err=%s",
            session_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save edit"}), 500


_SUGGESTION_TARGETS = ("upgrade", "rewrite_your_voice", "rewrite_polished",
                       "comment", "comment_video",
                       # Star suggestions (2026-07-18): per-star Approve /
                       # Revert on the SD ideal text (no apply_all surfaced).
                       "moment_emphasize", "moment_replace",
                       # LIVING TRANSCRIPT (FE contract 2026-07-21): a
                       # span-anchored tracked change on the document.
                       # Founder bug 2026-07-22: the FE shipped these and
                       # this allowlist rejected them with 400 — every
                       # Accept/Keep on the document failed ("Couldn't
                       # save that just now"). The #221 bug class: new
                       # vocabulary on one side, an unwidened guard on
                       # the other.
                       "document_replace", "document_bold",
                       # Structural stars are delivery prompts (no Approve);
                       # this target is accepted forward-compatibly for
                       # engagement feedback but changes NO serve behavior
                       # (never in the applied-map / fold).
                       "moment_structure")
# "reverted" (2026-07-15): Approve is a reversible toggle on the FE — the
# undo reports here so applied→reverted pairs keep the preference signal
# honest (second-order lane, below coach truth, as ever).
# "dismissed" (2026-07-20, gradual refinement rule 2): an explicit
# rejection of a star — recorded on the decision ledger so the same
# suggestion is never generated again for that phrase.
_SUGGESTION_ACTIONS = ("applied", "preferred", "apply_all", "reverted",
                       "dismissed")


@v2_bp.route("/user/snippets/<snippet_id>/suggestion-feedback",
             methods=["POST"])
@optional_auth
def v2_user_suggestion_feedback(snippet_id):
    """Record one Apply / ✓-prefer tap on a suggestion row (founder
    2026-07-14) — the four cases: word/phrase upgrade, rewrite, the comment,
    the comment-with-video, plus the per-piece "apply all". A SECOND-ORDER
    preference signal (below coach truth); capture only, never echoed back
    as any score (AC-9).

    Guest-allowed under the same canonical ownership rule as the guest
    readout: the request must present either the authenticated owner or the
    matching signed Guest ID. A bare session UUID is never authorization.

    Body: { "session_id": uuid (required),
            "target": "upgrade"|"rewrite_your_voice"|"rewrite_polished"|
                      "comment"|"comment_video",
            "action": "applied"|"preferred"|"apply_all",
            "upgrade_index"?: int ≥ 0 (target=upgrade),
            "suggestion_version"?: str }
    200 { saved } · 400 · 404 · 500
    """
    try:
        body = request.get_json(silent=True) or {}
        session_id = (body.get("session_id") or "").strip()
        if not _is_valid_uuid(snippet_id) or not _is_valid_uuid(session_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id and session_id must be UUIDs",
            }), 400
        target = body.get("target")
        if target not in _SUGGESTION_TARGETS:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": f"target: must be one of {', '.join(_SUGGESTION_TARGETS)}",
            }), 400
        action = body.get("action")
        if action not in _SUGGESTION_ACTIONS:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": f"action: must be one of {', '.join(_SUGGESTION_ACTIONS)}",
            }), 400
        upgrade_index = body.get("upgrade_index")
        if upgrade_index is not None and (
            not isinstance(upgrade_index, int)
            or isinstance(upgrade_index, bool) or upgrade_index < 0
        ):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "upgrade_index: must be a non-negative integer",
            }), 400

        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "NOT_FOUND", "error": "Not found"}), 404
        caller = getattr(request, "user_id", None)
        if not session_owned_by_principal(
            session,
            repository=ProjectRepository(db),
            user_id=caller,
            guest_token=request.headers.get(GUEST_OWNER_HEADER),
        ):
            return jsonify({"code": "NOT_FOUND", "error": "Not found"}), 404

        snip = db.get_snippet_by_id(snippet_id)
        if not snip or str(snip.get("session_id")) != session_id:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "That moment is not part of this session",
            }), 404

        ok = db.insert_user_suggestion_feedback(
            snippet_id=snippet_id,
            session_id=session_id,
            user_id=caller,
            target=target,
            action=action,
            upgrade_index=upgrade_index,
            suggestion_version=(
                str(body.get("suggestion_version"))
                if body.get("suggestion_version") is not None else None
            ),
        )
        # ── DECISION LEDGER (founder 2026-07-20, gradual refinement):
        # a star tap is also a durable per-PHRASE decision — applied bakes
        # into every future version, dismissed is never re-offered,
        # reverted wipes the slate. Phrase = the snippet's piece text (the
        # anchor's verbatim span). Best-effort: never breaks the POST. ──
        if target in ("moment_replace", "moment_emphasize",
                      "document_replace", "document_bold") \
                and action in ("applied", "dismissed", "reverted"):
            try:
                _arc = session.get("arc_id")
                if _arc:
                    from services.ideal_decision_ledger import (
                        record_star_decision,
                    )
                    _sug_row = (db.get_moment_suggestions_by_arc(_arc)
                                or {}).get(str(snippet_id))
                    _ver = None
                    try:
                        _ver = (db.get_coach_arc_ideal_text(_arc)
                                or {}).get("version")
                    except Exception:
                        _ver = None
                    # The ledger is keyed on the phrase AS IT APPEARS IN
                    # THE DOCUMENT — not the raw snippet transcript.
                    # Founder bug 2026-07-22: the document is smoothed
                    # (fillers out, casing/punctuation applied), so a row
                    # keyed on the raw transcript could never be found by
                    # the bake and the approval silently did nothing
                    # ("the system does not accept my approval").
                    # §12.3 — the intent key's location: the cutter's own
                    # slide bucket for this snippet (the one cross-take
                    # key). Missing/legacy metrics → None; the row then
                    # carries the phrase key only, exactly as before.
                    _piece = (snip.get("metrics") or {}).get("piece") \
                        if isinstance(snip.get("metrics"), dict) else None
                    _slide_i = _piece.get("slide_index") \
                        if isinstance(_piece, dict) else None
                    _decision_text = _document_phrase_for(
                        _arc, snippet_id,
                        fallback=(snip.get("transcript")
                                  or snip.get("transcription_text")))
                    # A coach revision is a new proposal against the text the
                    # user currently has. Store its visible before/after pair
                    # so accepting it never mutates an earlier machine
                    # decision in place.
                    if body.get("source") == "coach_revision":
                        _quote = body.get("quote")
                        _proposed = body.get("proposed_text")
                        if (isinstance(_quote, str) and _quote.strip()
                                and isinstance(_proposed, str)
                                and _proposed.strip()):
                            _decision_text = _quote.strip()
                            _sug_row = {
                                **(_sug_row or {}),
                                "replacement_text": _proposed.strip(),
                            }
                    record_star_decision(
                        db, _arc, suggestion=_sug_row, target=target,
                        action=action, target_text=_decision_text,
                        snippet_id=snippet_id, version=_ver,
                        slide_index=_slide_i)
                    # THE VOICE ALBUM (founder 2026-08-14, mirror ruling):
                    # an APPLIED emphasize is the USER signal of the entry
                    # rule — if the acoustic star and a published coach
                    # 'strong' already agree, the moment lands now. A
                    # REVERT withdraws that signal, and the album is a
                    # pure reflection of current state ("not an
                    # append-only graveyard of changed minds"), so the
                    # same refresh REMOVES the entry. Best-effort: never
                    # breaks the decide POST.
                    if action in ("applied", "reverted") and target in (
                            "moment_emphasize", "document_bold"):
                        try:
                            from services.voice_album import (
                                refresh_voice_album,
                            )
                            refresh_voice_album(_arc, database=db)
                        except Exception as _va_err:
                            logger.warning(
                                "voice_album: decide hook failed arc=%s: "
                                "%s", _arc, _va_err)
                    # THE TAKE'S BUDGET (founder 2026-08-10): a decided star
                    # keeps its slot — applied and dismissed alike; a revert
                    # returns it (undecided again, SPEC R4). The row doubles
                    # as SPEC §6's ground truth. Best-effort.
                    from services.intervention_spend import spend, unspend
                    _star_key = f"star:{target}:{snippet_id}"
                    _arc_sessions = db.get_arc_sessions(_arc) or []
                    # THE STYLE LANE (slice 2, founder 2026-08-11): a post-
                    # lock bold decision rides OUTSIDE the ≤3 — the FE marks
                    # it and the row lands with lane:style, which
                    # spent_count excludes. The row still lands (the
                    # learning loop wants every explicit decision). A
                    # forged flag frees only the student's own slots —
                    # no fence rides on it.
                    _style = bool(body.get("style_lane")) \
                        and target == "document_bold"
                    # PROPOSAL HISTORY: the texts ride when the client
                    # sends them (optional — older clients simply write
                    # text-less rows, which the history read skips).
                    _q = body.get("quote")
                    _pt = body.get("proposed_text")
                    _wk = body.get("why_key")
                    if action == "reverted":
                        unspend(db, _arc, _arc_sessions,
                                change_key=_star_key)
                    else:
                        spend(db, _arc, _arc_sessions,
                              change_key=_star_key,
                              decision=("approved" if action == "applied"
                                        else "disregarded"),
                              lane=("lane:style" if _style else None),
                              intervention_type=(
                                  "EMPHASISE"
                                  if target in ("moment_emphasize",
                                                "document_bold")
                                  else "REWRITE"),
                              quote=(str(_q) if isinstance(_q, str)
                                     and _q.strip() else None),
                              proposed_text=(str(_pt)
                                             if isinstance(_pt, str)
                                             and _pt.strip() else None),
                              why_key=(str(_wk) if isinstance(_wk, str)
                                       and _wk.strip() else None))
                    # A dismissed star also stops being OFFERED right now:
                    # the ledger remembers the decision; the row removal
                    # kills the anchor/star on every future serve (rule 2
                    # applies to the current version too, not only the
                    # next assembly).
                    if action == "dismissed":
                        db.delete_moment_suggestion(str(snippet_id))
                    if action in ("applied", "reverted"):
                        # Living Transcript: an approved change must
                        # appear in the document NOW, and an Undo must restore
                        # the original NOW rather than waiting for another
                        # take to trigger assembly.
                        _reassemble_after_decision(_arc)
            except Exception as _led_err:
                logger.warning(
                    "suggestion-feedback: ledger write failed snip=%s: %s",
                    snippet_id, _led_err)
        # Degrade gracefully (standing constraint): this is a best-effort,
        # capture-only second-order signal. A missing table (migration pending)
        # or a transient write hiccup returns 200 {saved:false} — the Apply/✓
        # tap must never error in the user's face over a training-side write.
        return jsonify({"saved": bool(ok)}), 200
    except Exception as e:
        logger.error("suggestion-feedback failed snip=%s err=%s",
                     snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to save feedback",
        }), 500


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


def _build_user_session_status(user_id):
    """The willab session-status surface.

    Returns {credits, can_start_analysis, audit_paid, audit_price}.

    Founder re-price 2026-07-06: RECORDING IS NEVER BLOCKED — every take of
    every arc records/analyzes/sends free, so ``can_start_analysis`` is always
    True (kept in the payload for FE back-compat). Payment (POST /v2/arc/<id>
    /unlock, 25 credits = $25) gates only the FOUR paid deliverables (coach-
    corrected ideal text, breakthroughs list, game, library) — never the
    per-take readout (coach note/transcript-correction there is free
    unconditionally). audit_paid mirrors the latest arc's entitlement so the
    FE can gate those locked affordances globally; audit_price carries both
    the display price AND its live credits cost (see arc_entitlement.audit_price).
    """
    from services.arc_entitlement import is_arc_entitled, audit_price
    # CREDITS ARE RETIRED (tokens only). This used to call
    # v2_ensure_credits_initialized, which SEEDED 25 credits into
    # v2_student_details for every account that had never been touched — a
    # live write, on a live read path, in a currency nothing spends any more.
    # The key stays on the payload at 0 so an older client parsing it does
    # not trip; no FE code reads it.
    credits = 0

    audit_paid = False
    if is_admin(user_id) or is_coach(user_id):
        # Coach/admin are never gated — they review every arc.
        audit_paid = True
    else:
        try:
            latest = db.v2_list_user_lab_sessions(str(user_id), limit=1) or []
        except Exception:
            latest = []
        arc_id = latest[0].get("arc_id") if latest else None
        if arc_id:
            audit_paid = bool(is_arc_entitled(db, arc_id, user_id))

    return {
        "credits": credits,
        "can_start_analysis": True,
        "audit_paid": audit_paid,
        "audit_price": audit_price(config),
    }


@v2_bp.route("/user/trainings", methods=["GET"])
@require_auth
def v2_user_list_trainings():
    """The training tab, grouped BY ARC (founder 2026-07-13) — one card per
    3-take training, including deckless projects. This is the canonical
    training-tab source on the frontend.

    Per training: the takes (all recordings, take order), `batch_verified`
    (the coach's explicit arc publish landed), and `ideal_ready` (the
    ideal-presentation button can open). AC-9: no scores anywhere.

    Response 200 { trainings: [ { arc_id, topic, created_at, take_count,
        takes_target, takes:[{session_id, take_index, created_at, has_slides,
        coach_reviewed}], batch_verified, delivered_at, ideal_ready } ] }
    """
    try:
        from services.best_presentation import TAKES_TARGET
        rows = db.list_user_arc_sessions(request.user_id) or []
        by_arc: dict = {}
        for r in rows:
            _aid = r.get("arc_id")
            if _aid:
                by_arc.setdefault(str(_aid), []).append(r)
        deliveries = db.list_arc_batch_deliveries(list(by_arc.keys())) or {}

        trainings = []
        for aid, sess in by_arc.items():
            # Reads are paired variants of their spoken take (2026-07-14) —
            # they must not appear/count as takes of their own.
            sess = [s for s in sess
                    if s.get("recording_kind") != "read"
                    and not s.get("paired_session_id")]
            sess.sort(key=lambda s: (s.get("take_index") or 0))
            if not sess:
                continue
            topic = None
            n_slides = 0
            cover_ref = None
            for s in sess:
                ctx = s.get("intake_context") if isinstance(
                    s.get("intake_context"), dict) else {}
                t = ctx.get("topic")
                if isinstance(t, str) and t.strip():
                    topic = t.strip()  # latest take wins (take order)
                n_slides = max(n_slides, len((ctx or {}).get("slides") or []))
                # Trainings-page header image (founder 2026-07-15) — the deck
                # PDF; first non-null across takes; null → FE mock picture.
                if cover_ref is None and ctx.get("presentation_ref"):
                    cover_ref = ctx.get("presentation_ref")
            takes = [{
                "session_id": str(s.get("id")),
                "take_index": s.get("take_index"),
                "created_at": s.get("created_at"),
                "has_slides": bool((
                    s.get("intake_context")
                    if isinstance(s.get("intake_context"), dict) else {}
                ).get("slides")),
                "coach_reviewed": bool(s.get("results_published_at")),
                # The take opens its FEEDBACK page once published (founder
                # 2026-07-15) — alias kept beside coach_reviewed for the FE.
                "feedback_available": bool(s.get("results_published_at")),
            } for s in sess]
            delivered = deliveries.get(aid)
            # Cheap coach_finalized mirror (same rule as /progress): every
            # deck slide coach-corrected. Deckless arcs (no deck) become
            # ideal_ready via the batch delivery itself (whose publish
            # already required the full coach_finalized).
            coach_finalized = False
            if n_slides:
                _edits = db.get_coach_best_presentation_edits(aid) or {}
                coach_finalized = all(
                    isinstance(_edits.get(i), str) and _edits[i].strip()
                    for i in range(n_slides)
                )
            trainings.append({
                "arc_id": aid,
                # FE also accepts "title"; the ideal-presentation deep link
                # uses best_presentation_arc_id (== arc_id here) — sent
                # explicitly though the FE falls back to arc_id if omitted.
                "topic": topic,
                "best_presentation_arc_id": aid,
                "cover_ref": cover_ref,
                "created_at": sess[0].get("created_at") if sess else None,
                "take_count": len(sess),
                "takes_target": TAKES_TARGET,
                "takes": takes,
                "batch_verified": bool(delivered),
                "delivered_at": (delivered or {}).get("published_at"),
                "ideal_ready": bool(delivered) or coach_finalized,
            })
        trainings.sort(key=lambda t: t.get("created_at") or "", reverse=True)
        return jsonify({"trainings": trainings}), 200
    except Exception as e:
        logger.error("user/trainings failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load trainings",
        }), 500


def _document_phrase_for(arc_id, snippet_id, *, fallback=None):
    """The phrase a decision must be keyed on: the piece's text AS IT
    APPEARS IN THE DOCUMENT.

    Founder bug 2026-07-22 ("the system does not accept my approval").
    The document is smoothed — fillers removed, casing and punctuation
    applied — and it may carry a coach correction or the student's own
    transcript edit instead of the raw words. A ledger row keyed on the
    RAW snippet transcript therefore could never be located by the bake,
    so the approval saved and then did nothing.

    Falls back to the supplied raw text when the flag is off or the
    document cannot be built (legacy lanes are unaffected)."""
    try:
        from services.ideal_text_block import _living_transcript_enabled
        if not _living_transcript_enabled():
            return fallback
        # THE SERVED document is the key space. Under the master flag
        # that is the master (whose pieces span takes) — keying on the
        # latest-take document resurrected the #230 "approval saves but
        # never applies" class (review findings #9/#15/#25).
        from services.master_document import (
            assemble_master_document, master_document_enabled,
        )
        if master_document_enabled():
            _m = assemble_master_document(arc_id, database=db)
            if _m.get("ready"):
                for p in ((_m.get("document") or {}).get("pieces") or []):
                    if str(p.get("snippet_id")) == str(snippet_id):
                        return p.get("text") or fallback
                # fall through: skeleton not covering the snippet →
                # transcript-document lookup below
        from services.transcript_document import build_transcript_document
        doc = build_transcript_document(arc_id, database=db)
        for p in ((doc or {}).get("pieces") or []):
            if str(p.get("snippet_id")) == str(snippet_id):
                return p.get("text") or fallback
    except Exception as e:
        logger.warning("document phrase lookup failed arc=%s snip=%s: %s",
                       arc_id, snippet_id, e)
    return fallback


@v2_bp.route("/user/snippets/<snippet_id>/confidence-review", methods=["POST"])
@require_auth
def v2_user_snippet_confidence_review(snippet_id):
    """Backward-compatible Confident Voice routing endpoint.

    The response is owner-scoped and writes only owner_voice_album_routing.
    It is not a peer vote, training label, quorum input, calibration row,
    evaluation, SFT or DPO signal.
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "snippet_id must be a valid UUID",
        }), 400
    from services.voice_album_routing import validate_owner_voice_album_route
    row, err = validate_owner_voice_album_route(
        request.get_json(silent=True) or {})
    if err:
        return jsonify({"code": "INVALID_INPUT", "error": err}), 400
    try:
        snip = db.get_snippet_by_id(snippet_id)
        sess = db.v2_get_session_by_id(
            str((snip or {}).get("session_id") or ""))
        if (not snip or not sess
                or str(sess.get("user_id")) != str(request.user_id)
                or not sess.get("arc_id")):
            return jsonify({
                "code": "NOT_FOUND", "error": "snippet not found",
            }), 404
        piece = ((snip.get("metrics") or {}).get("piece")
                 if isinstance(snip.get("metrics"), dict) else {})
        slide_index = (piece.get("slide_index")
                       if isinstance(piece, dict) else None)
        response = row["response"]
        saved = db.upsert_owner_voice_album_route(
            snippet_id=str(snippet_id),
            owner_user_id=str(request.user_id),
            arc_id=str(sess["arc_id"]),
            response=response,
            slide_index=slide_index,
            model_version=row.get("model_version"),
        )
        if not saved:
            return jsonify({
                "code": "V2_ERROR",
                "error": "could not save Voice Album routing (run "
                         "migrations/add_owner_voice_album_routing.sql)",
            }), 500
        from services.voice_album import refresh_voice_album
        refresh_voice_album(sess["arc_id"], database=db)
        from services.arc_notifications import fire_voice_album_ready
        fire_voice_album_ready(
            db, request.user_id, sess["arc_id"])
        from services.confidence_review_policy import (
            reconcile_confidence_review,
        )
        reconcile_confidence_review(
            db, snippet_id=snippet_id, session=sess,
            owner_user_id=request.user_id)
        return jsonify({
            "saved": True, "snippet_id": snippet_id,
            "ai_correct": row["ai_correct"],
        }), 200
    except Exception as e:
        logger.error("confidence_review.error snip=%s err=%s",
                     snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save Voice Album routing",
        }), 500


@v2_bp.route("/user/snippets/<snippet_id>/confidence-agree",
             methods=["PUT"])
@require_auth
def v2_put_confidence_agree(snippet_id):
    """Route the owner's answer on a displayed Confident Voice card.

    This endpoint is the evidence that the response is anchored. It writes a
    routing-only row used by the Voice Album reconciliation and nothing else.
    In particular it does not write state_ratings/confidence_labels, so it
    cannot enter training, quorum, calibration, evaluation, SFT or DPO.
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "snippet_id must be a valid UUID",
        }), 400
    try:
        from services.voice_album_routing import routing_response_from_rating
        response, err = routing_response_from_rating(
            request.get_json(silent=True) or {})
        if err:
            return jsonify({"code": "INVALID_INPUT", "error": err}), 400
        snip = db.get_snippet_by_id(snippet_id)
        sess = db.v2_get_session_by_id(
            str((snip or {}).get("session_id") or ""))
        if (not snip or not sess
                or str(sess.get("user_id")) != str(request.user_id)
                or not sess.get("arc_id")):
            return jsonify({
                "code": "NOT_FOUND", "error": "snippet not found",
            }), 404
        piece = ((snip.get("metrics") or {}).get("piece")
                 if isinstance(snip.get("metrics"), dict) else {})
        slide_index = (piece.get("slide_index")
                       if isinstance(piece, dict) else None)
        saved = db.upsert_owner_voice_album_route(
            snippet_id=str(snippet_id),
            owner_user_id=str(request.user_id),
            arc_id=str(sess["arc_id"]),
            response=str(response),
            slide_index=slide_index,
        )
        if not saved:
            return jsonify({
                "code": "V2_ERROR",
                "error": "could not save the answer (run "
                         "migrations/add_owner_voice_album_routing.sql)",
            }), 500
        from services.voice_album import refresh_voice_album
        refresh_voice_album(sess["arc_id"], database=db)
        from services.arc_notifications import fire_voice_album_ready
        fire_voice_album_ready(
            db, request.user_id, sess["arc_id"])
        from services.confidence_review_policy import (
            reconcile_confidence_review,
        )
        reconcile_confidence_review(
            db, snippet_id=snippet_id, session=sess,
            owner_user_id=request.user_id)
        return jsonify({
            "saved": True, "snippet_id": snippet_id, "response": response,
        }), 200
    except Exception as e:
        logger.error("confidence-agree failed snip=%s: %s",
                     snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save the answer",
        }), 500


def _practice_user_payload(practice, attempts=None):
    """Owner-safe practice shape. Raw metrics/comparison scores stay private."""
    from services.confident_voice_practice import (
        FINAL_QUESTION, FINAL_STRONGEST, INSTRUCTION, TITLE, UNSUCCESSFUL,
        public_attempt,
    )
    # A coach's private draft is never user-visible. Only an explicit Share
    # copies a complete exercise snapshot into coach_shared_exercise; until
    # then the owner continues to see the original manager-selected exercise.
    shared_exercise = practice.get("coach_shared_exercise")
    if practice.get("coach_shared_at") and isinstance(shared_exercise, dict):
        exercise = shared_exercise
    else:
        exercise = db.get_active_diagnostic_exercise(
            str(practice.get("exercise_id") or "")) or \
            (practice.get("exercise_snapshot")
             if isinstance(practice.get("exercise_snapshot"), dict) else {})
    rows = attempts if attempts is not None else \
        db.list_confident_voice_practice_attempts(str(practice.get("id")))
    from services.audio_ref_resolver import resolve_playable_ref
    public_rows = [public_attempt({
        **row,
        "audio_ref": resolve_playable_ref(row.get("audio_ref")),
    }) for row in rows]
    strongest = next((row for row in public_rows if row["is_strongest"]), None)
    improved = any(bool((row.get("comparison") or {}).get("improved"))
                   for row in rows if isinstance(row, dict))
    final_ready = len(public_rows) >= 3
    final_message = (
        UNSUCCESSFUL if final_ready and not improved
        else FINAL_STRONGEST if strongest else None
    )
    return {
        "id": str(practice.get("id")),
        "status": practice.get("status") or "open",
        "exercise": {
            "exercise_id": exercise.get("exercise_id")
                           or practice.get("exercise_id"),
            "version": exercise.get("version")
                       or practice.get("exercise_version"),
            "title": exercise.get("title") or TITLE,
            "instruction": exercise.get("instruction") or INSTRUCTION,
            "explanation_video_ref": (
                exercise.get("explanation_video_url")
                or exercise.get("explanation_video_ref")
            ),
        },
        "passage": practice.get("exact_passage") or "",
        "original_audio_ref": _resolve_snippet_audio_url({
            "audio_segment_path": practice.get("original_audio_ref"),
        }),
        "original_start_offset_ms": practice.get("original_start_offset_ms") or 0,
        "original_duration_ms": practice.get("original_duration_ms") or 0,
        "attempts": public_rows,
        "attempts_remaining": max(0, 3 - len(public_rows)),
        "strongest_attempt": strongest,
        "final_ready": final_ready,
        "final_message": final_message,
        "final_question": FINAL_QUESTION if final_ready or strongest else None,
        "final_user_answer": practice.get("final_user_answer"),
        "selected_attempt_id": practice.get("selected_attempt_id"),
    }


@v2_bp.route("/user/snippets/<snippet_id>/confidence-practice",
             methods=["POST"])
@require_auth
def v2_start_confident_voice_practice(snippet_id):
    """Open/resume the one optional same-passage practice for this take."""
    if not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "snippet_id must be a valid UUID"}), 400
    body = request.get_json(silent=True) or {}
    original_answer = body.get("original_user_answer")
    if original_answer not in ("yes", "no"):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "original_user_answer must be yes or no"}), 400
    try:
        snip = db.get_snippet_by_id(snippet_id)
        session = db.v2_get_session_by_id(
            str((snip or {}).get("session_id") or ""))
        if (not snip or not session
                or str(session.get("user_id")) != str(request.user_id)
                or not session.get("arc_id")):
            return jsonify({"code": "NOT_FOUND",
                            "error": "snippet not found"}), 404
        owner_route = next((
            row for row in db.list_owner_voice_album_routes(
                str(session.get("arc_id")))
            if str(row.get("snippet_id")) == str(snippet_id)
            and str(row.get("owner_user_id")) == str(request.user_id)
        ), None)
        if not owner_route or owner_route.get("response") != original_answer:
            return jsonify({"code": "ANSWER_REQUIRED",
                            "error": "Answer the Confident Voice question first."}), 409
        exercise_id = str(body.get("exercise_id") or "hear-every-word-v1")
        exercise = db.get_active_diagnostic_exercise(exercise_id)
        if not exercise:
            return jsonify({"code": "EXERCISE_UNAVAILABLE",
                            "error": "This exercise is not available."}), 409
        take_id = str(session.get("id"))
        existing = db.get_confident_voice_practice_by_take(
            take_id, str(request.user_id))
        if existing:
            if str(existing.get("snippet_id")) != str(snippet_id):
                return jsonify({"code": "TAKE_EXERCISE_LIMIT",
                                "error": "An exercise was already offered for this take."}), 409
            return jsonify({"practice": _practice_user_payload(existing)}), 200

        from services.confident_voice_practice import exercise_eligibility
        take_snippets = db.get_snippets_by_session(take_id) or []
        wpms = []
        for row in take_snippets:
            resolved = resolve_all(row)
            wpm = resolved.get("wpm")
            if isinstance(wpm, (int, float)) and not isinstance(wpm, bool):
                wpms.append(float(wpm))
        import statistics
        verdict = exercise_eligibility(
            snip,
            session_median_wpm=statistics.median(wpms) if wpms else None,
        )
        if not verdict.get("eligible"):
            return jsonify({"code": "NOT_ELIGIBLE",
                            "error": "This moment does not match the exercise."}), 409
        supported = exercise.get("supported_confidence_patterns")
        if isinstance(supported, list) and supported \
                and verdict.get("pattern") not in supported:
            return jsonify({"code": "NOT_ELIGIBLE",
                            "error": "This moment does not match the exercise."}), 409
        evidence = body.get("evidence") if isinstance(body.get("evidence"), dict) else {}
        span = evidence.get("span") if isinstance(evidence.get("span"), dict) else {}
        slide_index = evidence.get("slide_index")
        paragraph_index = evidence.get("paragraph_index")
        if str(evidence.get("project_id") or "") != str(session.get("arc_id")) \
                or str(evidence.get("take_session_id") or "") != take_id \
                or not isinstance(slide_index, int) or slide_index < 0 \
                or not isinstance(paragraph_index, int) or paragraph_index < 0 \
                or not isinstance(span.get("start"), int) \
                or not isinstance(span.get("end"), int) \
                or span["end"] <= span["start"]:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "exact feedback evidence is required"}), 400
        transcript = (snip.get("transcript") or "").strip()
        audio_ref = snip.get("audio_segment_path") or snip.get("audio_ref")
        created = db.create_confident_voice_practice({
            "owner_user_id": str(request.user_id),
            "project_id": str(session["arc_id"]),
            "take_session_id": take_id,
            "snippet_id": str(snippet_id),
            "exercise_id": exercise_id,
            "exercise_version": int(exercise.get("version") or 1),
            "exercise_snapshot": {
                "exercise_id": exercise_id,
                "version": int(exercise.get("version") or 1),
                "title": exercise.get("title"),
                "instruction": exercise.get("instruction"),
                "explanation_video_url": exercise.get("explanation_video_url"),
                "source": "diagnostic_library",
            },
            "slide_index": slide_index,
            "paragraph_index": paragraph_index,
            "evidence_span": span,
            "exact_passage": transcript,
            "original_audio_ref": str(audio_ref),
            "original_start_offset_ms": int(snip.get("start_offset_ms") or 0),
            "original_duration_ms": int(snip.get("duration_ms") or 0),
            "machine_assessment": {
                "pattern": verdict.get("pattern"),
                "priority": verdict.get("priority"),
            },
            "acoustic_evidence": {
                "signals": verdict.get("signals"),
                "snapshot": verdict.get("snapshot"),
                "pace_high": verdict.get("pace_high"),
            },
            "original_user_answer": original_answer,
        })
        if not created:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not start this practice."}), 500
        return jsonify({"practice": _practice_user_payload(created, [])}), 201
    except Exception as e:
        logger.error("confidence-practice start failed snip=%s: %s",
                     snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not start this practice."}), 500


@v2_bp.route("/user/confidence-practice/<practice_id>", methods=["GET"])
@require_auth
def v2_get_confident_voice_practice(practice_id):
    if not _is_valid_uuid(practice_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "practice_id must be a valid UUID"}), 400
    practice = db.get_confident_voice_practice(
        practice_id, str(request.user_id))
    if not practice:
        return jsonify({"code": "NOT_FOUND", "error": "practice not found"}), 404
    return jsonify({"practice": _practice_user_payload(practice)}), 200


@v2_bp.route("/user/confidence-practice/<practice_id>/attempts",
             methods=["POST"])
@require_auth
def v2_add_confident_voice_practice_attempt(practice_id):
    """Transcribe and acoustically compare one retained same-text attempt."""
    if not _is_valid_uuid(practice_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "practice_id must be a valid UUID"}), 400
    practice = db.get_confident_voice_practice(
        practice_id, str(request.user_id))
    if not practice:
        return jsonify({"code": "NOT_FOUND", "error": "practice not found"}), 404
    if practice.get("status") != "open":
        return jsonify({"code": "PRACTICE_CLOSED",
                        "error": "This practice is already closed."}), 409
    existing = db.list_confident_voice_practice_attempts(practice_id)
    if len(existing) >= 3:
        return jsonify({"code": "ATTEMPT_LIMIT",
                        "error": "This practice already has three attempts."}), 409
    upload = request.files.get("audio_file")
    if not upload:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "audio_file is required"}), 400
    try:
        audio_bytes = upload.read()
        if len(audio_bytes) < 1000:
            return jsonify({"code": "AUDIO_TOO_SHORT",
                            "error": "That recording was too short. Try again."}), 422
        mime = (upload.mimetype or "audio/webm").split(";", 1)[0]
        ext = ".webm" if "webm" in mime else ".m4a" if "mp4" in mime else ".wav"
        from services.snippet_transcription import transcribe_snippet_bytes
        transcription = transcribe_snippet_bytes(
            audio_bytes, hint_filename=f"practice{ext}")
        if not transcription or not transcription.get("transcript"):
            return jsonify({"code": "TRANSCRIPTION_FAILED",
                            "error": "We couldn't hear that clearly. Try again."}), 422
        from services.confident_voice_practice import (
            acoustic_snapshot, comparison_for_attempt, passage_alignment,
        )
        alignment = passage_alignment(
            str(practice.get("exact_passage") or ""),
            str(transcription.get("transcript") or ""))
        if not alignment.get("matches"):
            return jsonify({"code": "PASSAGE_MISMATCH",
                            "error": "Please read the exact passage shown and try again."}), 422
        from services.audio_metrics import analyze_audio
        duration_ms = transcription.get("transcribed_duration_ms")
        try:
            captured_duration_sec = max(
                0.0, float(request.form.get("duration_sec") or 0.0))
        except (TypeError, ValueError):
            captured_duration_sec = 0.0
        duration_sec = (float(duration_ms) / 1000.0
                        if isinstance(duration_ms, int) and duration_ms > 0
                        else captured_duration_sec)
        metrics = analyze_audio(
            audio_bytes, str(transcription["transcript"]), duration_sec)
        if not metrics:
            return jsonify({"code": "ANALYSIS_FAILED",
                            "error": "We couldn't compare that attempt. Try again."}), 422
        # Apply the SAME existing, self-relative acoustic confidence signal
        # used by full-take snippets when a valid speaker/take baseline is
        # available. Honest absence stays None; we never synthesize a score.
        try:
            from services.voice_confidence import (
                read_for_piece, resolve_confidence_baseline, resolve_take_sex,
            )
            take_rows = db.get_snippets_by_session(
                str(practice.get("take_session_id"))) or []
            take_metrics = [row.get("metrics") for row in take_rows
                            if isinstance(row.get("metrics"), dict)]
            baseline, baseline_kind = resolve_confidence_baseline(
                str(practice.get("owner_user_id") or request.user_id),
                take_metrics, database=db)
            session = db.v2_get_session_by_id(
                str(practice.get("take_session_id"))) or {}
            sex, sex_source = resolve_take_sex(
                str(practice.get("owner_user_id") or request.user_id),
                session, baseline, database=db)
            confidence_read = read_for_piece(
                metrics, baseline, baseline_kind, sex, sex_source)
            if confidence_read:
                metrics["voice_confidence"] = confidence_read
        except Exception as confidence_err:
            logger.info(
                "confidence-practice attempt confidence unavailable id=%s: %s",
                practice_id, confidence_err)
        current_snapshot = acoustic_snapshot({
            "metrics": metrics,
            "words": transcription.get("words") or [],
            "duration_ms": duration_ms or int(duration_sec * 1000),
            "audio_ref": "captured",
            "transcript": transcription["transcript"],
        })
        from services.confident_voice_practice import (
            machine_confidence_decision,
        )
        original = ((practice.get("acoustic_evidence") or {}).get("snapshot")
                    if isinstance(practice.get("acoustic_evidence"), dict) else {}) or {}
        previous = (existing[-1].get("acoustic_metrics") if existing else None)
        strongest_row = next((row for row in existing if row.get("is_strongest")), None)
        strongest_snapshot = (strongest_row or {}).get("acoustic_metrics")
        comparison = comparison_for_attempt(
            original, current_snapshot, previous, strongest_snapshot)
        attempt_index = len(existing) + 1
        key = (f"confidence-practice/{request.user_id}/{practice_id}/"
               f"{attempt_index}-{uuid.uuid4().hex}{ext}")
        from services.lab_audio_storage import (
            lab_audio_public_url, put_lab_audio_bytes, target_bucket,
        )
        bucket = put_lab_audio_bytes(key, audio_bytes, mime)
        audio_ref = lab_audio_public_url(key) or f"s3://{bucket or target_bucket()}/{key}"
        inserted = db.insert_confident_voice_practice_attempt({
            "practice_id": str(practice_id),
            "attempt_index": attempt_index,
            "storage_path": key,
            "audio_ref": audio_ref,
            "mime_type": mime,
            "duration_ms": int(duration_ms or max(1, duration_sec * 1000)),
            "transcript": str(transcription["transcript"]),
            "transcript_alignment": alignment,
            "acoustic_metrics": current_snapshot,
            "comparison": comparison,
            "assessment_key": comparison["assessment_key"],
            "machine_confidence_decision": machine_confidence_decision(
                current_snapshot),
        })
        if not inserted:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save that attempt."}), 500
        candidates = existing + [inserted]
        def _attempt_strength(row):
            value = (row.get("comparison") or {}).get("internal_strength")
            return float(value) if isinstance(value, (int, float)) else -999.0
        strongest = max(
            candidates,
            key=_attempt_strength,
        )
        db.set_confident_voice_practice_strongest(
            practice_id, str(strongest.get("id")))
        refreshed = db.list_confident_voice_practice_attempts(practice_id)
        return jsonify({"practice": _practice_user_payload(practice, refreshed)}), 201
    except Exception as e:
        logger.error("confidence-practice attempt failed id=%s: %s",
                     practice_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not compare that attempt."}), 500


@v2_bp.route("/user/confidence-practice/<practice_id>/complete",
             methods=["PUT"])
@require_auth
def v2_complete_confident_voice_practice(practice_id):
    """Dismiss or retain an attempt. Never writes any presentation surface."""
    if not _is_valid_uuid(practice_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "practice_id must be a valid UUID"}), 400
    practice = db.get_confident_voice_practice(
        practice_id, str(request.user_id))
    if not practice:
        return jsonify({"code": "NOT_FOUND", "error": "practice not found"}), 404
    body = request.get_json(silent=True) or {}
    if practice.get("status") != "open":
        return jsonify({"code": "PRACTICE_CLOSED",
                        "error": "This practice is already closed."}), 409
    now = datetime.now(timezone.utc).isoformat()
    if body.get("action") == "dismiss":
        updated = db.update_confident_voice_practice(
            practice_id, str(request.user_id),
            {"status": "dismissed", "closed_at": now})
        if not updated:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not close this practice."}), 500
        return jsonify({"practice": _practice_user_payload(updated)}), 200
    answer, attempt_id = body.get("user_answer"), body.get("attempt_id")
    if answer not in ("yes", "no") or not _is_valid_uuid(str(attempt_id or "")):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "attempt_id and user_answer are required"}), 400
    attempts = db.list_confident_voice_practice_attempts(practice_id)
    strongest = next((row for row in attempts if row.get("is_strongest")), None)
    if not strongest or str(strongest.get("id")) != str(attempt_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "Choose the acoustically strongest attempt."}), 400
    kept = db.keep_confident_voice_practice_attempt(
        practice_id, str(attempt_id), str(answer))
    if not kept:
        return jsonify({"code": "NOT_FOUND",
                        "error": "attempt not found"}), 404
    updated = db.update_confident_voice_practice(
        practice_id, str(request.user_id), {
            "status": "completed",
            "selected_attempt_id": str(attempt_id),
            "final_user_answer": str(answer),
            "closed_at": now,
        })
    if not updated:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not finish this practice."}), 500
    # Deliberate absence: no ideal-text, decision, style, cue, flagship or
    # voice_album call belongs here. Professional review remains separate.
    return jsonify({"practice": _practice_user_payload(updated)}), 200


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
