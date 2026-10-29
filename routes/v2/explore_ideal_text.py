"""The ONE-BLOCK IDEAL TEXT surface: the student read, the block/prior-take
decisions, revisions, the save + user-edit lanes, and the tracked-changes
block that renders what moved between takes.

This is the F1 deliverable's read surface -- the assembled best-per-slide
text the learner actually sees. Assembly and ranking themselves live in
services/ (ideal_text_block, best_presentation, cross_take_selection); these
routes serve, gate and record decisions against it.

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 4);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Depends one-way on routes/v2/arcs.py (arc ownership + the moment maps) --
never the reverse.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging
import re

import sentry_sdk
from flask import jsonify, request

from auth import require_auth
from routes.v2.guest_owner import caller_is_guest, require_owner_or_guest
from routes.v2.arcs import (
    _arc_owned_by_caller,
    _fold_applied_moments,
    _moment_applied_map,
    _moment_explanations_map,
    _moment_playback_map,
    _moment_reference_map,
    _moment_suggestions_enabled,
    _moments_entitled,
    _reassemble_after_decision,
)
from routes.v2.blueprint import v2_bp
from services.db import db, first_client_repository
from services.ideal_text_changes import with_evidence_coordinates
from services.ideal_text_notebook import (
    NotebookDeps,
    build_notebook,
    optional_read as _ideal_optional_read,
)
from services.ideal_text_part_actions import (
    lock_part,
    root_part,
    seed_parts_for_lock,
)
from services.ideal_text_user_edit import save_user_edit
from services.prior_take_decision import decide_prior_take
from services.rate_limits import llm_limit
from services.refusal import Refusal
from services.token_prices import price_of as _price_of
from services.coach_video_storage import refreshed_media_url
from services.intervention_spend import (
    latest_spoken_take_sid as _latest_take_sid,
)
from services.paragraph_history import history_for_part
from services.slide_helper_words import page_roots, record_pick

logger = logging.getLogger(__name__)


def _publish_ideal_text_core(arc_id, actor_id=None) -> None:
    """Publish the immutable cold-open read model after a product write."""
    try:
        from services.ideal_text_core_snapshot import publish_for_arc
        publish_for_arc(db, str(arc_id), str(actor_id) if actor_id else None)
    except Exception as error:
        logger.warning("ideal-text core publication failed arc=%s: %s",
                       arc_id, error)


def _completed_spoken_sessions(sessions):
    """Official takes whose processing completed successfully.

    Legacy synchronous rows predate ``analysis_state`` and therefore count as
    ready. Pending and failed submissions remain resumable recordings, but
    must not advance the guided journey or its take number.
    """
    return [
        row for row in (sessions or [])
        if row.get("recording_kind") != "read"
        and not row.get("paired_session_id")
        and row.get("analysis_state") in (None, "ready")
    ]


# The /talks/<talk_id>/ideal-text route (Paid Audits A7) was DELETED here
# (founder 2026-08-10: "older feedback system should be ripped off"). It had
# no FE caller and no BFF proxy — the audits product it served is retired,
# and the explore GET below is the one ideal-text read. Its builder
# (services/ideal_text_report.py) is removed too (N48.3 Q13 A).


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/core", methods=["GET"])
@require_owner_or_guest
def v2_explore_get_ideal_text_core(arc_id):
    """Strict, read-only cold-open document.

    This endpoint reads one immutable prepared snapshot.  It does not compose,
    persist, aggregate feedback or prepare analytics.

    ONE REPAIR, WHEN THERE IS NO HEAD AT ALL (founder 2026-09-28, 16A): the
    owner's open asks the ordinary publisher for one -- see
    ``ideal_text_core_snapshot.read_core_or_publish``.  An existing head is only ever read.

    IT DOES RE-ADDRESS THE DECK (2026-09-19, founder: "no slide preview" /
    "it was visible for a moment but then gone").  ``publish_for_arc`` bakes
    ``project.presentation_ref`` into the snapshot as the URL stored at
    upload, and a snapshot is immutable by design -- so whatever address was
    current at publish time is served forever.  Since decks became user
    content (DPIA RISK-11, 2026-09-18) that address is a SIGNATURE, and
    ``refreshed_media_url`` exists precisely because "nothing depends on a
    stored URL staying valid".  Every other read of ``presentation_ref``
    already calls it -- arcs, user_account, coach, and the composing ideal
    text read below.  This one did not, which is the whole defect: the FE's
    first load reads the composing lane and sees a signed deck, every poll
    after reads THIS lane and sees a dead one.

    Re-addressing is not composing.  The stored snapshot, its payload and its
    ``payload_sha256`` are untouched; only the way this response points at the
    same bytes is refreshed.  Nothing re-hashes the served body -- enrichment
    and recording-roots bind on the snapshot id.
    """
    from time import perf_counter
    started = perf_counter()
    from services.db import IdealTextCoreReadError
    try:
        from services.ideal_text_core_snapshot import read_core_or_publish
        core_read = read_core_or_publish(
            db, arc_id, str(request.user_id),
            owner_read=lambda: _arc_owned_by_caller(arc_id))
    except IdealTextCoreReadError:
        # A FAILED read is not "no document yet" (founder 2026-09-26: a
        # dropped connection showed an existing Ideal Text as missing). 503
        # says try again; the client retries and falls back, and never
        # renders a pending screen for a document that exists.
        response = jsonify({
            "code": "IDEAL_TEXT_READ_FAILED",
            "retryable": True,
        })
        response.status_code = 503
        response.headers["Retry-After"] = "2"
        response.headers["Cache-Control"] = "private, no-store"
        return response
    if not core_read:
        response = jsonify({
            "code": "IDEAL_TEXT_DOCUMENT_PENDING",
            "state": "pending",
        })
        response.status_code = 404
    else:
        snapshot = core_read["snapshot"]
        overlay = core_read["dynamic_overlay"]
        payload = dict(snapshot.get("payload") or {})
        payload.update({
            "document_snapshot_id": str(snapshot.get("id")),
            "document_snapshot_sha256": snapshot.get("payload_sha256"),
            "owner_edit": overlay["owner_edit"],
            "confident_moment_summary": overlay["confident_moment_summary"],
            "confident_moment_summary_status": (
                overlay["confident_moment_summary_status"]
            ),
        })
        # A ref this cannot read with certainty comes back unchanged, and a
        # missing one stays missing -- so a deckless arc still reports no deck
        # rather than an address that resolves to nothing.
        payload["presentation_ref"] = refreshed_media_url(
            payload.get("presentation_ref")) or None
        _serve_is_saved(payload, arc_id)
        _serve_deck_flags(payload, arc_id)
        response = jsonify(payload)
    elapsed = (perf_counter() - started) * 1000
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Server-Timing"] = f"ideal_core;dur={elapsed:.1f}"
    return response


@v2_bp.route("/explore/arc/<arc_id>/recording-roots", methods=["GET"])
@require_owner_or_guest
def v2_explore_get_recording_roots(arc_id):
    """Live committed roots, bound to the current immutable document.

    Root choice is product state, not document content and not an ML label.
    The immutable core owns exact Paragraph -> Slide lineage; current part rows
    own the latest lock/root choice (``slide_helper_words.page_roots``).
    """
    owned, _sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    actor_id = str(request.user_id)
    snapshot = db.get_ideal_text_document_core(arc_id, actor_id)
    if not snapshot:
        return jsonify({
            "code": "IDEAL_TEXT_DOCUMENT_PENDING",
            "state": "pending",
        }), 404
    roots = page_roots(db, arc_id, actor_id, snapshot)
    response = jsonify({
        "document_snapshot_id": str(snapshot.get("id")),
        "document_snapshot_sha256": snapshot.get("payload_sha256"),
        "roots": roots,
    })
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/enrichment", methods=["GET"])
@require_owner_or_guest
def v2_explore_get_ideal_text_enrichment(arc_id):
    """Optional sections bound to one immutable document snapshot."""
    from time import perf_counter
    from services.ideal_text_enrichment import (
        FENCED_SECTIONS, EnrichmentDeps, budget_for,
        requested_sections as requested_sections_of,
        run_sections, section_readers, stale_snapshot)
    from services.parallel import run_in_parallel
    started = perf_counter()
    laps: dict[str, float] = {}

    def lap(name, read):
        """``read``, with its wall time kept for the Server-Timing header:
        the sections already name their laps, and the reads around them
        were the unnamed remainder of the request (founder's stopwatch,
        2026-10-18)."""
        def timed():
            lap_started = perf_counter()
            try:
                return read()
            finally:
                laps[name] = (perf_counter() - lap_started) * 1000
        return timed

    snapshot_id = (request.args.get("document_snapshot_id") or "").strip()
    # The ownership read and the core read go out together (2026-10-18: one
    # round trip, not two, before any section starts). The core read is
    # owner-checked itself, and a caller who does not own the arc gets the
    # 404 below whatever it returned.
    #
    # The generation-fenced core read treats a head invalidated by a source
    # mutation as stale immediately.  Reading the mutable head directly here
    # would let enrichment attach to an old document during republishing.
    actor_id = str(request.user_id)
    (owned, sessions), current = run_in_parallel(
        lap("owner_read", lambda: _arc_owned_by_caller(arc_id)),
        lap("core_read", lambda: (
            db.get_ideal_text_document_core(arc_id, actor_id)
            if snapshot_id else None)))
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    if not snapshot_id:
        return jsonify({"code": "SNAPSHOT_REQUIRED",
                        "error": "document_snapshot_id is required"}), 400
    # The core read returns the whole snapshot row, so when it IS the asked-for
    # snapshot there is nothing more to read. Only a mismatch needs the
    # by-id read, to tell "stale" (409) from "never existed" (404).
    selected = (
        current if current and str(current.get("id")) == snapshot_id
        else lap("snapshot_read", lambda: db.get_ideal_text_document_snapshot(
            arc_id, str(request.user_id), snapshot_id))())
    if not selected:
        return jsonify({"code": "SNAPSHOT_NOT_FOUND"}), 404
    if (stale := stale_snapshot(current, selected)) is not None:
        return jsonify(stale), 409

    requested_sections, invalid_sections = requested_sections_of(
        (request.args.get("sections") or "").strip())
    if invalid_sections:
        return jsonify({
            "code": "INVALID_ENRICHMENT_SECTION",
            "sections": invalid_sections,
        }), 400
    readers = section_readers(
        db, arc_id=arc_id, actor_id=str(request.user_id), sessions=sessions,
        selected=selected, snapshot_id=snapshot_id, deps=EnrichmentDeps(
            optional_read=_ideal_optional_read,
            explanations_map=_moment_explanations_map,
            playback_map=_moment_playback_map,
            reference_map=_moment_reference_map,
            moments_entitled=_moments_entitled,
            price_of=_price_of),
        coach_take=request.args.get("take"))
    # Budgets live with `run_sections`. The long one is earned by asking for
    # the SLOW section, not by naming any section at all.
    enrichment_timeout = budget_for(requested_sections)
    sections, timings = run_sections({
        name: reader for name, reader in readers.items()
        if name in requested_sections
    }, timeout_seconds=enrichment_timeout)
    # Optional readers run concurrently and can outlive the snapshot check at
    # the top of this request.  Re-check the generation fence after every
    # reader has settled.  A source mutation during enrichment must return a
    # retryable stale response and, crucially, must never deliver a stale
    # presentation acknowledgement token to the browser.
    #
    # Only `learning` and `document_layers` hand out such tokens (and write
    # on the way), and only when they answer. Every other answer is a plain
    # read bound to the snapshot already checked above, so a pending marks
    # retry or a read-only lane skips this second round trip.
    #
    # The fence read is the head id and the arc's generation, not the whole
    # snapshot again: the row was read and owner-checked above, and only two
    # ids are compared here (founder's stopwatch, 2026-10-18).
    if any(sections.get(name, {}).get("status") == "ready"
           for name in FENCED_SECTIONS):
        final_current = lap("fence_read", lambda: (
            db.get_ideal_text_document_fence(arc_id, str(request.user_id))))()
        if (stale := stale_snapshot(final_current, selected)) is not None:
            return jsonify(stale), 409
    elapsed = (perf_counter() - started) * 1000
    response = jsonify({
        "document_snapshot_id": snapshot_id,
        "sections": sections,
    })
    timing_parts = [f"ideal_enrichment;dur={elapsed:.1f}"]
    timing_parts.extend(
        f"{name};dur={duration:.1f}" for name, duration in laps.items())
    timing_parts.extend(
        f"section_{name};dur={duration:.1f}"
        for name, duration in sorted(timings.items()))
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Server-Timing"] = ", ".join(timing_parts)
    return response



def _notebook_deps() -> NotebookDeps:
    """This surface's helpers, bound per request (so they are the ones the
    module holds right now)."""
    return NotebookDeps(
        suggestions_enabled=_moment_suggestions_enabled,
        applied_lookup=_moment_applied_map,
        fold_applied=_fold_applied_moments,
        explanations_map=_moment_explanations_map,
        playback_map=_moment_playback_map,
        reference_map=_moment_reference_map,
        moments_entitled=_moments_entitled,
        completed_spoken=_completed_spoken_sessions,
        parts_block=_ideal_parts_block,
        tracked_changes_block=_tracked_changes_block,
    )


@v2_bp.route("/explore/arc/<arc_id>/ideal-text", methods=["GET"])
@require_auth
def v2_explore_get_ideal_text(arc_id):
    """The user's ideal-text notebook (the purple bubble).

    Single-deliverable (founder 2026-07-17): the ideal text is FREE in both
    states — never a 402. Returns
    200 { arc_id, version, status:"verified"|"unverified", title,
          updated_at, latest_take_session_id, take_count,
          can_record_take, text, user_edited,
          prior_edit?, key_moments, moments_unlocked,
          explanations_available, price_credits,
          notes_text, has_deck, project_archived } — free in both
    states, never 402s. The
    crucial-bubble fields (founder 2026-07-20): `title` = latest take's
    topic.

    `take_count` (founder 2026-07-23) = the project's official-take count
    (per-arc). Since 2026-08-05 `version` IS this count — every take is
    its own version, and each one needs its own verification (founder:
    "each take is different and each should be verified"). The two used
    to differ, because `version` bumped only when the assembled text
    changed; a take that barely moved the text left the badge frozen.

    RETIRED 2026-08-05 — `reread_done` / `reread_processing` are gone
    with the read-out-loud lane. `can_record_take` (founder 2026-07-24,
    T1 · 1.2) is the signal for the "record another take" button: true
    the moment the project has a spoken take, so a finished recording
    returns the student straight to this screen ready to record again.
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
        payload, status = build_notebook(
            db, arc_id=arc_id, user_id=request.user_id, sessions=_sessions,
            requested_version=request.args.get("version"),
            deps=_notebook_deps())
        if status == 200 and not payload.get("historical"):
            _serve_is_saved(payload, arc_id)
            _serve_deck_flags(payload, arc_id)
        return jsonify(payload), status
    except Exception as e:
        logger.error("explore ideal-text GET failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load ideal text",
        }), 500


@v2_bp.route("/explore/arc/<arc_id>/journey/next-steps", methods=["POST"])
@require_auth
def v2_explore_arc_journey_next_steps(arc_id):
    """Append the current take's exact journey bubble, idempotently."""
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        spoken = _completed_spoken_sessions(sessions)
        take_index = len(spoken)
        from services.journey_messages import journey_message
        message = journey_message(request.user_id, arc_id, take_index)
        if message is None:
            return jsonify({
                "code": "INVALID_STATE",
                "error": "Next steps are available after takes one to three.",
            }), 409
        persisted = db.insert_lounge_messages(request.user_id, [message])
        if not persisted:
            return jsonify({"code": "V2_ERROR",
                            "error": "Failed to save next steps"}), 500
        return jsonify({"message": persisted[0]}), 200
    except Exception as e:
        logger.error("journey next-steps failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save next steps"}), 500


@v2_bp.route("/explore/arc/<arc_id>/review/summary", methods=["POST"])
@require_auth
def v2_explore_arc_review_summary(arc_id):
    """The closing summary after a Take's review, once per Take (founder
    lock 2026-10-12, section 3). Body: {take_session_id, practice?,
    helper_words?, coach_note?}. 200 {message} · 404 · 500"""
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        from services.take_summary import summary_message
        message = summary_message(
            db, user_id=str(request.user_id), arc_id=str(arc_id),
            takes=_completed_spoken_sessions(sessions),
            take_session_id=str(body.get("take_session_id") or ""), body=body)
        if message is None:
            return jsonify({"code": "NOT_FOUND", "error": "take not found"}), 404
        return jsonify({"message": message}), 200
    except Exception as e:
        logger.error("review summary failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save the summary"}), 500


def _tempo_on() -> bool:
    """The caller has the tempo step: the founder, or the rings panel's
    ``tempo_step`` row reaches them (N166 step 6)."""
    from routes.admin import _token_email, is_founder_email
    from services.tempo_stretch import tempo_is_on
    return tempo_is_on(getattr(request, "user_id", None), founder=is_founder_email(_token_email()))


@v2_bp.route("/explore/arc/<arc_id>/review/tempo/<take_session_id>", methods=["GET"])
@require_auth
def v2_explore_arc_review_tempo(arc_id, take_session_id):
    """The tempo step's stretch for one Take (founder 2026-10-26, N162,
    N166). 200 {tempo: {reading, topic, said} | null}
    · 403 a denied permit · 404 · 500"""
    from services.processing_authorization import ProcessingAuthorizationError
    from services.tempo_stretch import tempo_for_take
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        take = str(take_session_id)
        if not owned or take not in {str(s.get("id")) for s in _completed_spoken_sessions(sessions)}:
            return jsonify({"code": "NOT_FOUND", "error": "take not found"}), 404
        if not _tempo_on():
            return jsonify({"tempo": None}), 200
        tempo = tempo_for_take(db, take=take, user_id=str(request.user_id), arc_id=str(arc_id))
        return jsonify({"tempo": tempo}), 200
    except ProcessingAuthorizationError:
        return jsonify({"code": "NOT_AUTHORIZED", "error": "processing not authorized"}), 403
    except Exception as e:
        logger.error("review tempo failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to read the tempo step"}), 500


@v2_bp.route("/explore/arc/<arc_id>/review/tempo/<take_session_id>", methods=["POST"])
@require_auth
def v2_explore_arc_review_tempo_tries(arc_id, take_session_id):
    """The tempo game as played (founder 2026-10-26, N166 step 4), kept for
    Will. Body: {reading, tries: [{result, path}], close}. 200 {kept: true}
    · 400 · 404 · 500"""
    from services.tempo_stretch import keep_tries
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        take = str(take_session_id)
        if (not owned or not _tempo_on()
                or take not in {str(s.get("id")) for s in _completed_spoken_sessions(sessions)}):
            return jsonify({"code": "NOT_FOUND", "error": "take not found"}), 404
        if not keep_tries(db, user_id=str(request.user_id), take=take,
                          body=request.get_json(silent=True) or {}):
            return jsonify({"code": "INVALID", "error": "the tempo game is not whole"}), 400
        return jsonify({"kept": True}), 200
    except Exception as e:
        logger.error("review tempo tries failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to keep the tempo game"}), 500


@v2_bp.route("/explore/arc/<arc_id>/feedback-check", methods=["POST"])
@require_auth
def v2_explore_arc_feedback_check(arc_id):
    """The speaker's tap on "Did this feedback help you?" (WIL-74): Yes, Not
    really, or Skip under "What was missing?". Body: {take_session_id,
    choice}. Writes the tap and the signed reply into the Lounge.
    200 {messages} · 400 · 404 · 500"""
    from services.feedback_check import CheckError, answer
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        body = request.get_json(silent=True) or {}
        take = str(body.get("take_session_id") or "")
        if not owned or take not in {str(s.get("id")) for s in sessions}:
            return jsonify({"code": "NOT_FOUND", "error": "take not found"}), 404
        messages = answer(db, user_id=str(request.user_id), arc_id=str(arc_id),
                          take_session_id=take, choice=str(body.get("choice") or ""))
        return jsonify({"messages": messages}), 200
    except CheckError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("feedback check failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save the answer"}), 500


@v2_bp.route("/explore/arc/<arc_id>/will-question", methods=["POST"])
@require_auth
def v2_explore_arc_will_question(arc_id):
    """The speaker's tap under Will's question after a Take (N82): one of
    the question's answers, or Skip. Body: {take_session_id, choice}. Writes
    the tap and the reply (thanks, or the one follow-up) into the Lounge.
    200 {messages} · 400 · 404 · 500"""
    from services.will_question import QuestionError, answer
    try:
        owned, sessions = _arc_owned_by_caller(arc_id)
        body = request.get_json(silent=True) or {}
        take = str(body.get("take_session_id") or "")
        if not owned or take not in {str(s.get("id")) for s in sessions}:
            return jsonify({"code": "NOT_FOUND", "error": "take not found"}), 404
        messages = answer(db, user_id=str(request.user_id), arc_id=str(arc_id),
                          take_session_id=take, choice=str(body.get("choice") or ""))
        return jsonify({"messages": messages}), 200
    except QuestionError as e:
        return jsonify({"code": e.code, "error": str(e)}), e.status
    except Exception as e:
        logger.error("will question failed arc=%s: %s", arc_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save the answer"}), 500


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
@llm_limit
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
        owned, _pt_sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        saved = decide_prior_take(
            db, arc_id=arc_id, sessions=_pt_sessions,
            body=request.get_json(silent=True) or {}, user_id=request.user_id,
            reassemble=_reassemble_after_decision)
        return jsonify({"saved": saved}), 200
    except Refusal as refusal:
        return jsonify(refusal.body), refusal.status
    except Exception as e:
        logger.error("prior-take decide failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the decision"}), 500


@v2_bp.route("/explore/arc/<arc_id>/blocks/<int:block_key>/decide",
             methods=["POST"])
@llm_limit
@require_auth
def v2_explore_decide_block(arc_id, block_key):
    """Always 404: the master-document block decision is retired (audit C2).

    Its body only ran when ``master_document_enabled()`` was true, and that
    has been permanently False since the experiment was retired. The route
    stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/explore/arc/<arc_id>/blocks/variants", methods=["GET"])
@require_auth
def v2_explore_block_variants(arc_id):
    """Always 404: the variant pool sat on top of the retired master
    document (audit C2). The route stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/explore/arc/<arc_id>/blocks/<int:block_key>/select",
             methods=["POST"])
@require_auth
def v2_explore_select_block_variant(arc_id, block_key):
    """Always 404: the variant pool sat on top of the retired master
    document (audit C2). The route stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/revisions", methods=["GET"])
@require_auth
def v2_explore_ideal_revisions(arc_id):
    """The History under ⋯ (lock 2026-10-12, section 4): every version of
    the document, newest first, each with its Take and its words. Read only
    (rule 5). Owner only."""
    owned, _sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    from services.paragraph_history import document_history
    response = jsonify({"revisions": document_history(
        db.list_ideal_text_versions(arc_id))})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/revisions/<int:revision>"
             "/restore", methods=["POST"])
@require_auth
def v2_explore_restore_ideal_revision(arc_id, revision):
    """Always 404: the variant pool sat on top of the retired master
    document (audit C2). The route stays because the FE still calls it."""
    return jsonify({"code": "NOT_FOUND", "error": "not found"}), 404


@v2_bp.route("/explore/arc/<arc_id>/ideal-text/save", methods=["POST"])
@llm_limit
@require_auth
def v2_explore_save_ideal_text(arc_id):
    """"Save the ideal text", the last item under ⋯: stamps the version on
    screen as saved. It changes no word. Owner only.

    200 {saved: true, arc_id, saved_version} · 404 · 500"""
    owned, _sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    snapshot = db.get_ideal_text_document_core(arc_id, str(request.user_id))
    version = ((snapshot or {}).get("payload") or {}).get("version")
    if not isinstance(version, int):
        return jsonify({"code": "IDEAL_TEXT_DOCUMENT_PENDING",
                        "error": "no document yet"}), 404
    if not db.ideal_text.insert_ideal_text_save(str(arc_id), version):
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the ideal text"}), 500
    return jsonify({"saved": True, "arc_id": arc_id,
                    "saved_version": version}), 200


def _serve_is_saved(payload, arc_id) -> None:
    """`is_saved` on a read: whether the version on screen was saved. Left
    out for a guest (who cannot save) or when unknown; the FE then withholds
    the item."""
    version = payload.get("version")
    if caller_is_guest() or not isinstance(version, int):
        return
    saved = db.ideal_text.ideal_text_saved(str(arc_id), version)
    if isinstance(saved, bool):
        payload["is_saved"] = saved


def _serve_deck_flags(payload, arc_id) -> None:
    """`has_deck` (the current deck has a PDF: "Update slides", else "Add
    slides", N257) and `project_archived` (N14, N254) on a live read. Read
    at serve time, never baked into the immutable snapshot: both change
    without a new Take."""
    from services.slide_deck_update import deck_flags
    payload.update(deck_flags(db, arc_id, payload.get("presentation_ref")))


def _generated_text(arc_id, user_id) -> "str | None":
    """The words the machine wrote for this document: the head snapshot's
    payload text. None when there is no snapshot or the read fails, and the
    parts block then carries no `edited` flags (see `mark_edited`)."""
    try:
        snapshot = db.get_ideal_text_document_snapshot(arc_id, user_id)
        payload = (snapshot or {}).get("payload")
        text = (payload or {}).get("text") if isinstance(payload, dict) else None
        return text if isinstance(text, str) else None
    except Exception as error:
        logger.warning("generated text unavailable arc=%s: %s", arc_id, error)
        return None


def _ideal_parts_block(arc_id, user_id, served_text) -> dict:
    """`{"parts": [...]}` for the student GET, or `{}` (the key ABSENT).

    STALE PARTS ARE NOT SERVED. Parts are written by the client against the
    document it was looking at; the document can then be rewritten underneath
    them by a new take assembling or a coach verifying, and neither of those
    goes through the arranger. Identity pointing at words that are no longer on
    screen is worse than no identity — it is the same failure as a tracked
    change anchored to a fragment that moved (#219), except a lock hung on it
    in PR 3 would silently guard the wrong paragraph.

    So the join has to match. When it does not, the key is simply absent and
    the FE derives parts the way it does today; the next save re-mints them
    against the text actually on screen.

    Best-effort by construction: any failure yields {}, which is the
    pre-migration payload exactly.
    """
    try:
        from services.ideal_text_parts import (
            agrees_with_text, mark_edited, serve,
        )
        parts = serve(db.get_ideal_text_parts(arc_id, user_id,
                                              with_lock=True))
        if parts is None:
            return {}
        parts = mark_edited(parts, _generated_text(arc_id, user_id))
        if not agrees_with_text(parts, served_text):
            # Dropping OPEN parts here is routine staleness. Dropping a
            # LOCK is not — every lock on this document just went invisible
            # for this read, which is field report #5's shape. Under the
            # §12.1 compose fallback the served text always agrees when
            # locks exist, so this firing means a path skipped compose:
            # say so loudly instead of degrading in silence.
            if any(p.get("locked") for p in parts):
                logger.error(
                    "ideal parts: %d stored parts (WITH locks) no longer "
                    "join to the served text arc=%s — locks invisible this "
                    "read (§12.1)", len(parts), arc_id)
            return {}
        return {"parts": parts}
    except Exception as e:
        logger.warning("ideal parts failed arc=%s: %s", arc_id, e)
        return {}


def _previous_spoken_session(arc_id, current_session_id):
    """The spoken take immediately BEFORE the document's take — the
    comparison base for cross-take discernment. None when this is the
    first take. Best-effort."""
    try:
        from services.slide_selection import spoken_arc_sessions
        spoken = spoken_arc_sessions(db.takes.get_arc_sessions(arc_id) or [])
        spoken.sort(key=lambda s: (s.get("take_index") or 0,
                                   s.get("created_at") or ""))
        ids = [str(s.get("id")) for s in spoken if s.get("id")]
        if not current_session_id or str(current_session_id) not in ids:
            return None
        i = ids.index(str(current_session_id))
        return ids[i - 1] if i > 0 else None
    except Exception:
        return None


def _locked_parts(arc_id, user_id, served_text) -> list:
    """The document's parts WITH their lock state, or [] when there are none.

    Same staleness rule as `_ideal_parts_block`: parts that no longer join to
    the served text describe a document the student is not looking at, and
    their offsets would point the layer filter at the wrong paragraph. [] then
    means "no locks to enforce", which is the safe direction — R1 suppresses
    interventions, so a bad parts read must never silently suppress the whole
    surface.
    """
    try:
        from services.ideal_text_parts import agrees_with_text, serve
        rows = db.get_ideal_text_parts(arc_id, user_id, with_lock=True)
        parts = serve(rows)
        if not parts or not agrees_with_text(parts, served_text):
            # [] = "no locks to enforce" — R1 then filters NOTHING, and a
            # composition suggestion can land on a locked paragraph. When
            # the dropped parts actually carried a lock, that is field
            # report #5's second half; the §12.1 compose fallback makes the
            # served text agree whenever locks exist, so a firing here is a
            # path that skipped compose — log it at error, not silence.
            if parts and any(p.get("locked") for p in parts):
                logger.error(
                    "locked parts: %d stored parts (WITH locks) do not "
                    "join to the served text arc=%s — layer filter runs "
                    "EMPTY this read (§12.1)", len(parts), arc_id)
            return []
        # `serve` carries the boolean for the wire; the layer filter reads
        # `locked_at`, so hand it the raw column rather than a second name for
        # the same fact.
        by_id = {str(r.get("id")): r.get("locked_at")
                 for r in rows if isinstance(r, dict)}
        for p in parts:
            p["locked_at"] = by_id.get(p["id"])
        return parts
    except Exception as e:
        logger.warning("locked parts failed arc=%s: %s", arc_id, e)
        return []


def _record_arms(result, session_id, user_id) -> None:
    """Persist one arbitration's experiment arms. Best-effort, never raises.

    THE MODULE IS EXPLICIT that running the controls without this is strictly
    WORSE than not running them: 12% of (user, lane) pairs receive nothing and
    20% of winning notes are withheld, users pay that cost in feedback, and
    without the arm stored next to the outcome no causal claim is recoverable
    — while it looks from the outside exactly like a working experiment.

    ONE ROW PER (session, lane) CONSIDERED, upserted on that pair. This surface
    is POLLED, so the same arbitration is written repeatedly; the upsert makes
    that idempotent, and every value it writes is deterministic for a given
    (user, session) — the assignments are pure functions of the salts, and the
    exploration roll is stable by construction — so a re-write cannot change a
    recorded arm underneath the analysis.
    """
    try:
        from services.manager_engine import arm_rows
        rows = arm_rows(result, session_id=str(session_id or ""),
                        user_id=str(user_id or ""))
        if rows:
            db.record_intervention_arms(rows)
    except Exception as e:
        logger.warning("intervention arms not recorded session=%s: %s",
                       session_id, e)


def _tracked_changes_block(arc_id, served_text, user_id="",
                           take_session_id="", review_version=None,
                           degradation=None, *,
                           background_shadow: bool = False) -> dict:
    """The `changes` block of the SD student GET (founder 2026-07-20) —
    {} when the Living Transcript flag is off, so the key is simply
    ABSENT and the FE keeps rendering today's star layer.

    The stages live in ``services.ideal_text_changes`` (audit Q-C1 / Q-C3);
    this wrapper binds them to the database service and to the helpers this
    surface shares (the moment maps, the previous-take lookup, the locked
    parts, the evidence coordinates, the experiment arms). It keeps the name
    and signature the internal callers and the tests use. ``degradation`` is
    the request's log; without one the block reports its own fallbacks
    under a `degraded` key of its own.
    """
    from services.ideal_text_changes import ChangesDeps, build_changes_block
    return build_changes_block(
        arc_id, served_text, user_id, take_session_id, review_version,
        deps=ChangesDeps(
            database=db,
            first_client_repository=first_client_repository,
            applied_map=_moment_applied_map,
            playback_map=_moment_playback_map,
            previous_spoken_session=_previous_spoken_session,
            locked_parts=_locked_parts,
            with_evidence_coordinates=with_evidence_coordinates,
            record_arms=_record_arms,
        ),
        degradation=degradation,
        background_shadow=background_shadow,
    )


@v2_bp.route("/explore/arc/<arc_id>/parts/<part_id>/lock", methods=["PUT"])
@require_auth
def v2_explore_set_part_lock(arc_id, part_id):
    """Lock or unlock ONE part (SPEC-parts-locking-and-layers §4, R3, R5).

    THE LOCK IS NOT A SETTING — it changes which INTERVENTION LAYER may fire on
    this paragraph. Open (`locked_at IS NULL`) takes composition: the machine
    may propose changing the words. Locked takes accentuation: it may only
    propose styling words already there. Offering the wrong one is worse than
    offering nothing — a rewrite destroys memorisation the speaker has already
    paid for, and an emphasis styles a sentence about to be replaced.

    Body: {locked: bool, text_echo: str}.

    `text_echo` IS THE DOCUMENT THE STUDENT WAS LOOKING AT, and it is required
    rather than nice-to-have. A lock means "these words are settled", so it has
    to be a claim about specific words. Between the GET and this PUT a new take
    can assemble or the coach can verify, replacing the text underneath — and
    locking a part id against a document that has moved settles a paragraph the
    student never read. Same idiom as the block decide endpoint's
    `challenger_session_echo`, and the same 409.

    R2 — APPROVE IS NOT LOCK. This decides no intervention. It promotes one
    part over a series of already-decided changes; the decisions themselves ride
    their own endpoints and are untouched here.

    R3 RETIRED (founder 2026-10-05, "i guess yes"): a part with open
    feedback on it locks like any other. The old gate refused while any served
    row on the paragraph was undecided -- a V3 rewrite or praise note included
    -- and the page read that refusal as final, so helper words saved while
    their lock did not. Nothing is auto-decided: an open row simply stays
    open, and a rewrite on a locked paragraph is refused at Accept
    (`accepted_rewrite`, PROTECTED).

    200 {locked, part_id} · 400 · 404 · 409 STALE_DOCUMENT · 500
    """
    try:
        from services.ideal_text_parts import agrees_with_text
        owned, _lock_sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        locked = body.get("locked")
        if not isinstance(locked, bool):
            return jsonify({"code": "INVALID_INPUT",
                            "error": "locked must be a boolean"}), 400
        echo = body.get("text_echo")
        if not isinstance(echo, str) or not echo.strip():
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text_echo is required"}), 400
        echo = echo.strip()

        user_id = str(getattr(request, "user_id", "") or "")
        parts = _locked_parts(arc_id, user_id, echo)
        if not parts:
            # SEED-ON-LOCK (SPEC-lockin-loop §2): no usable stored identity,
            # but the client sent its derived parts list — validate and adopt
            # it, so the founder's record→accept→"Lock it" loop works on a
            # document the student never manually edited. Refused (no seed
            # sent, malformed, disagrees with the echo, or a stored lock
            # exists) → the 409 below, exactly as before.
            parts = seed_parts_for_lock(db, arc_id, user_id, echo,
                                        body.get("parts"))
        if not parts or not agrees_with_text(parts, echo):
            # Either no identity is stored, or it no longer describes this
            # document. Both mean the same thing to the caller: refetch.
            return jsonify({"code": "STALE_DOCUMENT",
                            "error": "document moved"}), 409
        proposal = lock_part(
            db, arc_id=arc_id, user_id=user_id, part_id=part_id, parts=parts,
            locked=locked, body=body, sessions=_lock_sessions)
        _publish_ideal_text_core(arc_id, user_id)
        return jsonify({
            "locked": locked,
            "part_id": str(part_id),
            "root_phrase_proposal": proposal,
        }), 200
    except Refusal as refusal:
        return jsonify(refusal.body), refusal.status
    except Exception as e:
        logger.error("part lock failed arc=%s part=%s: %s", arc_id, part_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to set the lock"}), 500


@v2_bp.route("/explore/arc/<arc_id>/parts/<part_id>/helper-words",
             methods=["PUT"])
@require_auth
def v2_explore_set_part_helper_words_from_take(arc_id, part_id):
    """Helper words taken from any earlier Take (founder lock 2026-09-30,
    B4, D5): the speaker opens another Take's version of the Paragraph on
    the helper words overlay and taps words there. Those words need not be
    in the current text — they show as the headline with nothing italic
    until said again — so the Paragraph-level rooting phrase, which is a
    span of the current text, cannot hold them. They go to the Slide's
    helper words, where the recording screen and the page read them from,
    replacing the Paragraph's current pick; the lock that follows (the
    same "Use these helper words" tap) locks them like any other pick.
    One Take, one phrase (Q3): the words must be exact words of that one
    version."""
    owned, _sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    body = request.get_json(silent=True) or {}
    user_id = str(request.user_id)
    history = history_for_part(db, arc_id, user_id, str(part_id))
    if history is None:
        return jsonify({"code": "NOT_FOUND", "error": "part not found"}), 404
    from services.slide_helper_words import phrase_in_version, version_of_take
    version = version_of_take(history, body.get("take_index"))
    if version is None:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "that Take has no version of this text"}), 400
    words = phrase_in_version(body.get("phrase"), version.get("paragraphs"))
    from services.slide_helper_words import within_cap
    if words is None or not within_cap(words):
        return jsonify({"code": "INVALID_ROOT_PHRASE",
                        "error": "Choose exact words from that Take."}), 400
    # The Paragraph-level span, if any, is cleared: the Slide's pick is now
    # the one set of words, and the page must not show two.
    db.set_ideal_text_part_root(arc_id=arc_id, user_id=user_id,
                                part_id=str(part_id), phrase=None,
                                start=None, end=None)
    record_pick(db, arc_id, user_id, str(part_id),
                _latest_take_sid(_sessions), words)
    return jsonify({"saved": True, "phrase": words}), 200


@v2_bp.route("/explore/arc/<arc_id>/parts/<part_id>/history",
             methods=["GET"])
@require_owner_or_guest
def v2_explore_get_part_history(arc_id, part_id):
    """The history behind a Paragraph's bookmark (contract 16): its Slide's
    words Take by Take, and the helper words locked when. Owner only."""
    owned, _sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    from services.snippet_audio_url import resolve_snippet_audio_url
    history = _part_history(
        db, arc_id, str(request.user_id), str(part_id),
        lambda snippet: resolve_snippet_audio_url(snippet, db))
    if history is None:
        return jsonify({"code": "NOT_FOUND", "error": "part not found"}), 404
    response = jsonify(history)
    response.headers["Cache-Control"] = "private, no-store"
    return response


def _part_history(database, arc_id, user_id, part_id, resolve_url):
    """One Paragraph's history body, or None when it has none. The ONE
    assembly both the single endpoint and the batch use, so a batched body
    is the single endpoint's body (F5)."""
    history = history_for_part(database, arc_id, user_id, part_id)
    if history is None:
        return None
    from services.paragraph_history import with_earlier_take_details
    return _ideal_optional_read(
        "earlier_take_details", history,
        lambda: with_earlier_take_details(
            database, arc_id, user_id, history, resolve_url))


@v2_bp.route("/explore/arc/<arc_id>/part-histories", methods=["GET"])
@require_owner_or_guest
def v2_explore_get_part_histories(arc_id):
    """Several Paragraphs' histories in one request (F5, founder
    2026-10-08). ``?part_ids=a,b,c`` names them; without it, every Paragraph
    of the published document. 200 ``{"histories": {part_id: <the single
    history endpoint's body>}}``; a Paragraph the single endpoint would
    refuse or fail on is left out. Owner only, as the single endpoint."""
    owned, sessions = _arc_owned_by_caller(arc_id)
    if not owned:
        return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
    from services.paragraph_history import (
        BatchedHistoryReads, once_per_snippet, requested_part_ids,
    )
    from services.snippet_audio_url import resolve_snippet_audio_url
    user_id = str(request.user_id)
    reads = BatchedHistoryReads(db, arc_id, user_id, sessions)
    part_ids = requested_part_ids(request.args.get("part_ids"), reads.core())
    reads.prefetch(part_ids)
    resolve = once_per_snippet(
        lambda snippet: resolve_snippet_audio_url(snippet, db))
    histories = {}
    for part_id in part_ids:
        try:
            history = _part_history(reads, arc_id, user_id, part_id, resolve)
        except Exception as e:
            logger.warning("part history failed arc=%s part=%s: %s",
                           arc_id, part_id, e, exc_info=True)
            continue
        if history is not None:
            histories[part_id] = history
    response = jsonify({"histories": histories})
    response.headers["Cache-Control"] = "private, no-store"
    return response


@v2_bp.route("/explore/arc/<arc_id>/parts/<part_id>/root", methods=["PUT"])
@require_auth
def v2_explore_set_part_root(arc_id, part_id):
    """Accept, replace, or skip the orange exact-span prompt on one part."""
    try:
        owned, _sessions = _arc_owned_by_caller(arc_id)
        if not owned:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        body = request.get_json(silent=True) or {}
        echo = body.get("text_echo")
        if not isinstance(echo, str) or not echo.strip():
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text_echo is required"}), 400
        echo = echo.strip()
        user_id = str(getattr(request, "user_id", "") or "")
        parts = _locked_parts(arc_id, user_id, echo)
        target = next((p for p in parts
                       if p.get("id") == str(part_id).lower()), None)
        if target is None:
            return jsonify({"code": "STALE_DOCUMENT",
                            "error": "document moved"}), 409
        saved = root_part(
            db, arc_id=arc_id, user_id=user_id, part_id=part_id,
            target=target, body=body, sessions=_sessions)
        _publish_ideal_text_core(arc_id, user_id)
        return jsonify(saved), 200
    except Refusal as refusal:
        return jsonify(refusal.body), refusal.status
    except Exception as e:
        logger.error("part root failed arc=%s part=%s: %s",
                     arc_id, part_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the rooting phrase"}), 500


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
        # D22-D24: one database-owned text/parts/revision transaction.
        saved = save_user_edit(db, arc_id=arc_id, user_id=request.user_id,
                               body=request.get_json(silent=True) or {})
        _publish_ideal_text_core(arc_id, str(request.user_id))
        return jsonify(saved), 200
    except Refusal as refusal:
        return jsonify(refusal.body), refusal.status
    except Exception as e:
        logger.error("ideal user-edit PUT failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500
