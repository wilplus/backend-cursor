"""The signed-in user's takes & readouts surface: session results/status,
intake context, the strong-sides library, strengths (per-presentation
groups), take/session/presentation deletes, readout re-reads, transcript
edits, suggestion feedback and the trainings list.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 3);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging

import sentry_sdk
from flask import jsonify, request

from auth import optional_auth, require_auth
from config import Config
from routes.admin import is_admin, is_coach
from routes.v2.arcs import (
    _arc_audit_paid,
    _presentation_id_from_slides,
    _reassemble_after_decision,
)
from routes.v2.blueprint import v2_bp
from routes.v2.common import _is_valid_uuid, _resolve_snippet_audio_url
from services.db import db
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
        from services.slide_word_split import split_words_by_slides
        from services.power_phrase_ranking import power_score
        uid = str(request.user_id)
        library = db.get_strong_sides_library(uid, tag="strong") or []

        # Bucket library rows by session (the coach's STRONG lines).
        by_session: dict = {}
        for row in library:
            sid = row.get("session_id")
            if not sid:
                continue
            by_session.setdefault(sid, []).append(row)

        # PRE-COACH inclusion (founder 2026-06-18): a presentation appears on
        # Trainings the moment it's recorded — not only after the coach
        # publishes. Seed by_session with EVERY lab session (empty rows = no
        # strong lines yet; they layer in on publish). Use the list rows as the
        # session source so we don't re-fetch each one.
        lab_rows = db.v2_list_user_lab_sessions(uid) or []
        sess_rows = {str(s.get("id")): s for s in lab_rows if s.get("id")}
        for sid in sess_rows:
            by_session.setdefault(sid, [])

        # Part B — kill the N+1: resolve every session row once, decide which
        # need snippets (coach-tagged OR deck sessions), then read ALL their
        # snippets in ONE batched query. `words` are excluded (the take viewer
        # reads the precomputed slide_transcripts, #A), slashing the payload.
        _sessions_by_sid: dict = {}
        _need_snippets: list = []
        for sid in by_session:
            session = sess_rows.get(sid) or db.v2_get_session_by_id(sid) or {}
            _sessions_by_sid[sid] = session
            _ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
            if by_session[sid] or (_ctx.get("slides") or []):
                _need_snippets.append(sid)
        _snips_by_sid = db.get_snippets_by_sessions(_need_snippets) or {}

        # Load session metadata + rank lookups per session.
        sess_meta: dict = {}
        for sid in by_session:
            session = _sessions_by_sid.get(sid) or {}
            ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
            slides = ctx.get("slides") or []
            ranks: dict = {}
            sigs: dict = {}  # coach-adjusted power_score inputs per snippet
            all_snippets: list = []
            # Snippets for coach-tagged sessions (ranks / power_score) AND DECK
            # sessions (the per-slide verbatim transcript). Un-coached DECKLESS
            # sessions skip it. Prefer the batched result; fall back to a single
            # read only when the batch had nothing for this sid.
            if by_session[sid] or slides:
                all_snippets = _snips_by_sid.get(sid)
                if all_snippets is None:
                    try:
                        all_snippets = db.get_snippets_by_session(sid) or []
                    except Exception:
                        all_snippets = []
                for s in all_snippets:
                    m = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
                    sid_s = str(s.get("id"))
                    ranks[sid_s] = m.get("rank") if isinstance(m, dict) else None
                    _ss = m.get("slide_stickiness") if isinstance(m, dict) else None
                    sigs[sid_s] = {
                        "overall_score": m.get("overall_score") if isinstance(m, dict) else None,
                        "slide_stickiness": (_ss or {}).get("composite") if isinstance(_ss, dict) else None,
                    }
            sess_meta[sid] = {
                "ctx": ctx,
                "ranks": ranks,
                "sigs": sigs,
                "slides": slides,
                "all_snippets": all_snippets,
                # #A — the COMPLETE per-slide 1:1 transcript precomputed at
                # record time (preferred over the per-snippet split below).
                "slide_transcripts": session.get("slide_transcripts"),
                "created_at": session.get("created_at") or "",
                "arc_id": session.get("arc_id"),
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
            # #A (2026-06-22) — PREFER the precomputed COMPLETE per-slide 1:1
            # transcript (built at record time from the WHOLE-recording word
            # list). It catches the quiet slides the salient-snippet split
            # dropped ("first slide not caught / shifted"). Falls back to the #6
            # per-snippet split (then legacy) for recordings made before this.
            precomputed = meta.get("slide_transcripts")
            pre_by_idx = {
                t["index"]: t for t in precomputed
                if isinstance(t, dict) and isinstance(t.get("index"), int)
            } if isinstance(precomputed, list) and precomputed else {}
            if pre_by_idx:
                # Resolved, not raw: a writer missing its public-URL env
                # leaves s3:// here and the slide player renders dead
                # (founder 2026-08-10 — "the master thing not working").
                from services.audio_ref_resolver import resolve_playable_ref
                parent_audio = resolve_playable_ref(next(
                    (s.get("audio_segment_path")
                     for s in (meta.get("all_snippets") or [])
                     if s.get("audio_segment_path")),
                    None,
                ))
                for sg in slide_groups:
                    pt = pre_by_idx.get(sg["index"]) or {}
                    sg["transcript"] = pt.get("transcript") or ""
                    sg["start_offset_ms"] = pt.get("start_offset_ms")
                    sg["duration_ms"] = pt.get("duration_ms")
                    sg["audio_ref"] = parent_audio
                return slide_groups

            # #6 (2026-06-21) — the FULL verbatim transcript per slide for THIS
            # take (not just the coach standout), so the Trainings take viewer
            # shows what was actually said on each slide instead of "No standout
            # moment yet". All the take's snippets (start_offset ASC → time
            # order), bucketed by slide via the tap timeline, joined verbatim; +
            # the slide's audio span so the FE can play that slide back.
            per_text: dict = {i: [] for i in range(len(slides))}
            per_audio: dict = {}

            def _accrue(si, txt, start_ms, end_ms, audio_ref):
                """Add a text fragment + its audio span to slide ``si``."""
                if not isinstance(si, int) or si < 0 or si >= len(slides):
                    return
                if txt:
                    per_text[si].append(txt)
                a = per_audio.setdefault(si, {
                    "audio_ref": audio_ref,
                    "start_offset_ms": start_ms,
                    "end_ms": start_ms if start_ms is not None else None,
                })
                if a.get("audio_ref") is None:
                    a["audio_ref"] = audio_ref
                if start_ms is not None and (
                    a.get("start_offset_ms") is None
                    or start_ms < a["start_offset_ms"]
                ):
                    a["start_offset_ms"] = start_ms
                if end_ms is not None:
                    a["end_ms"] = max(a.get("end_ms") or 0, end_ms)

            from services.audio_ref_resolver import resolve_playable_ref
            # THE COACH'S CORRECTION WINS (founder 2026-08-11). A human who
            # says "this was on slide N" outranks the tap timeline — that is
            # the whole point of the label, and a coach who corrects a take
            # and watches nothing move stops correcting.
            #
            # WHOLE-SNIPPET, deliberately: the correction is made at snippet
            # grain, so it replaces the word split for that snippet rather
            # than trying to be cleverer than the human. The FE only offers
            # the affordance on snippets the split did NOT divide, so a
            # correction can never flatten a boundary the pipeline got right.
            _slide_fixes = db.get_snippet_slide_corrections(sid) or {}
            for s in (meta.get("all_snippets") or []):
                off = s.get("start_offset_ms")
                dur = s.get("duration_ms")
                _fix = _slide_fixes.get(str(s.get("id")))
                if isinstance(_fix, int):
                    _txt = (
                        s.get("transcript") or s.get("transcription_text") or ""
                    ).strip()
                    _end = (off + dur) if (off is not None and dur is not None) else None
                    _accrue(_fix, _txt, off, _end,
                            resolve_playable_ref(s.get("audio_segment_path")))
                    continue
                # Same parent URL on every row — the resolver passes a
                # healthy public URL through and signs an s3:// fallback.
                audio_ref = resolve_playable_ref(
                    s.get("audio_segment_path"))
                # #6 — PRECISE split: bucket each WORD to the slide on screen at
                # its timestamp, so words spoken after a mid-snippet slide click
                # move to the NEW slide. Returns [] (→ legacy whole-snippet
                # bucketing) when the snippet has no word timestamps or there's
                # no usable click timeline.
                frags = split_words_by_slides(s.get("words"), advances, slides)
                if frags:
                    for f in frags:
                        st = f.get("start_offset_ms")
                        _accrue(
                            f["slide_index"], f.get("transcript"), st,
                            (st or 0) + (f.get("duration_ms") or 0),
                            audio_ref,
                        )
                    continue
                # Fallback (no words / no timeline): whole snippet → start slide.
                si = slide_index_for_offset(off, advances)
                if si is None:
                    si = _best_match_index(
                        s.get("transcript") or s.get("transcription_text"),
                        slides,
                    )
                txt = (
                    s.get("transcript") or s.get("transcription_text") or ""
                ).strip()
                end_ms = (off + dur) if (off is not None and dur is not None) else None
                _accrue(si, txt, off, end_ms, audio_ref)
            for sg in slide_groups:
                i = sg["index"]
                sg["transcript"] = " ".join(per_text.get(i) or [])
                _a = per_audio.get(i) or {}
                sg["audio_ref"] = _a.get("audio_ref")
                sg["start_offset_ms"] = _a.get("start_offset_ms")
                sg["duration_ms"] = (
                    (_a["end_ms"] - _a["start_offset_ms"])
                    if _a.get("end_ms") is not None
                    and _a.get("start_offset_ms") is not None
                    else None
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
                    # the deck PDF for this take (library renders slides from it).
                    "presentation_ref": sess_meta[sid]["ctx"].get("presentation_ref"),
                    # the explore arc this take belongs to (→ best-presentation).
                    "arc_id": sess_meta[sid].get("arc_id"),
                    "slides": _build_take(sid),
                })

            # Group-level ref: the FIRST NON-NULL across takes (a re-take may
            # have dropped the ref) so the library always gets a URL.
            _pres_ref = next(
                (t["presentation_ref"] for t in takes if t["presentation_ref"]),
                None,
            )
            # Group-level arc: the best-presentation reads ONE arc, but a deck
            # re-recorded as a SEPARATE arc spreads its takes across multiple
            # arc_ids (always-on mints a fresh arc per recording session). Pick
            # the arc with the MOST takes — the most-developed sequence, most
            # likely to be ready — NOT just the newest take's arc, which may be
            # a stray 1-take re-record (that would make the FE's group take-count
            # disagree with the overlay's per-arc count: "open" → "need 2 more").
            # Single-arc decks are unaffected (one arc holds all takes). Tie →
            # newest, since `takes` is newest-first.
            _arc_counts: dict = {}
            for _t in takes:
                _aid = _t.get("arc_id")
                if _aid:
                    _arc_counts[_aid] = _arc_counts.get(_aid, 0) + 1
            if _arc_counts:
                _max_n = max(_arc_counts.values())
                _arc_id = next(
                    (t["arc_id"] for t in takes
                     if t.get("arc_id") and _arc_counts[t["arc_id"]] == _max_n),
                    None,
                )
            else:
                _arc_id = None

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
                "presentation_ref": _pres_ref,
                "arc_id": _arc_id,
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


def _user_presentation_sessions_all(user_id: str, presentation_id: str) -> list:
    """EVERY lab session of this user whose deck hashes to presentation_id —
    the COMPLETE delete set (backlog 4.4). The library grouping
    (_user_presentation_groups) under-counts on purpose for take NUMBERING
    (it mirrors what /user/strengths shows), but a DELETE built on it left
    survivors: takes without coach-published 'strong' library rows were
    invisible to it, so a "deleted" training kept resurfacing in any
    session-backed list — the reported bug. Chronological (created_at, id)."""
    pid = (presentation_id or "").strip()
    if not pid:
        return []
    matches = []
    for s in (db.v2_list_user_lab_sessions(user_id) or []):
        ctx = s.get("intake_context") if isinstance(
            s.get("intake_context"), dict) else {}
        slides = (ctx or {}).get("slides") or []
        if slides and _presentation_id_from_slides(slides) == pid:
            matches.append((s.get("created_at") or "", str(s.get("id"))))
    return [sid for _, sid in sorted(matches)]


@v2_bp.route("/user/presentations/<presentation_id>", methods=["DELETE"])
@require_auth
def v2_user_delete_presentation(presentation_id):
    """Delete a whole presentation (deck) and ALL its takes — owner-scoped,
    HARD delete (the recordings are gone everywhere, incl. coach history).
    Deletes the COMPLETE session set for the deck (not just the
    library-visible takes — backlog 4.4 fix; see
    _user_presentation_sessions_all).
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
    upload-time payload byte-for-byte. Post-publish it also carries the
    coach layer (insights_payload + per-snippet coach note/tag).

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
              coach: { note, tag, when?, examples? },   # post-publish only
          } ],
          "slides"?: [...], "presentation_ref"?: str,   # the deck (render once/group)
          "insights_payload"?: {...},
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

    GUEST-capable since 2026-07-16 (the round-4 signed-out-first flow: the
    instant view's Approve taps write through here BEFORE signup — they were
    silently 401-ing for guests). Same capability rule as the guest readout:
    an UNCLAIMED session (user_id NULL) is writable to the bare session id; a
    claimed session is owner-only — 404 to any other/no caller (no existence
    leak). Edits ride the session, so a later claim keeps them.

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
        _owner = session.get("user_id")
        _caller = getattr(request, "user_id", None)
        if _owner and str(_owner) != str(_caller or ""):
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

    Guest-allowed with the SAME capability rule as the guest readout: an
    UNCLAIMED session (user_id NULL) is writable to a bare session id; a
    claimed session is owner-only (404 to any other/no caller — no existence
    leak).

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
        owner = session.get("user_id")
        caller = getattr(request, "user_id", None)
        # Claimed → owner-only; unclaimed → bare-capability (guest). Same
        # no-existence-leak rule as the guest readout.
        if owner and str(owner) != str(caller or ""):
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
                    record_star_decision(
                        db, _arc, suggestion=_sug_row, target=target,
                        action=action,
                        target_text=_document_phrase_for(
                            _arc, snippet_id,
                            fallback=(snip.get("transcript")
                                      or snip.get("transcription_text"))),
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
                    if action == "applied":
                        # Living Transcript: an approved change must
                        # disappear from the document NOW, not next take.
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
    credits = int(db.v2_ensure_credits_initialized(str(user_id)))

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
    3-take training, DECKLESS included (the deck-hash grouping in
    /user/strengths dropped deckless takes into the flat general bucket, so
    they never appeared as a training). Replaces /user/strengths as the
    training-tab source on the FE.

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


@v2_bp.route("/user/snippets/<snippet_id>/owner-confidence-label",
             methods=["PUT"])
@require_auth
def v2_put_owner_confidence_label(snippet_id):
    """The ideal-text modal's blind label (founder 2026-08-10: "the modal
    in the ideal text has an option to label the voice snippet").

    The OWNER'S lane of the SAME ternary instrument every other lane
    writes — yes / no / neutral XOR unrateable, into state_ratings
    (confidence_labels), lane resolved to game_owner. This is what makes
    "min twice labelled" reachable: coach + owner are the two labels that
    admit a snippet to the game, and the panel grows from there.

    OWNER-scoped, unlike the peer-review POST above: the modal is the
    speaker labelling their own voice, so the snippet's session must
    belong to the caller — 404 otherwise (no existence oracle).

    BLIND at the ask (RATE_AND_REVEAL): the FE asks BEFORE any machine
    read is shown and disables the control after commit, so the row's
    saw_model_output=False invariant (I1) holds by construction here too.

    Body: { value: "yes"|"no"|"neutral" XOR unrateable: true,
            note?, latency_ms? }
    200 {saved} · 400 · 404 · 500
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "snippet_id must be a valid UUID",
        }), 400
    try:
        from services.state_ratings import resolve_lane, validate_rating
        snip = db.get_snippet_by_id(snippet_id)
        if not snip:
            return jsonify({
                "code": "NOT_FOUND", "error": "snippet not found",
            }), 404
        sess = db.v2_get_session_by_id(str(snip.get("session_id") or ""))
        if not sess or str(sess.get("user_id")) != str(request.user_id):
            return jsonify({
                "code": "NOT_FOUND", "error": "snippet not found",
            }), 404
        body = request.get_json(silent=True) or {}
        row, err = validate_rating({
            "state_id": "confidence",
            "value": body.get("value"),
            "unrateable": body.get("unrateable", False),
            "note": body.get("note"),
            "latency_ms": body.get("latency_ms"),
        })
        if err:
            return jsonify({"code": "INVALID_INPUT", "error": err}), 400
        lane = resolve_lane(sess.get("source"), is_coach=False,
                            is_owner=True)
        saved = db.upsert_state_rating(
            snippet_id=str(snippet_id), row=row,
            rater_id=str(request.user_id),
            session_id=str(sess.get("id")),
            lane=lane)
        if not saved:
            return jsonify({
                "code": "V2_ERROR",
                "error": "could not save the label (run "
                         "migrations/add_state_generic_ratings.sql)",
            }), 500
        return jsonify({"saved": True, "snippet_id": snippet_id}), 200
    except Exception as e:
        logger.error("owner-confidence-label failed snip=%s: %s",
                     snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to save the label",
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
