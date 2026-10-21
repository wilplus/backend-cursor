"""The willab coach review domain: /v2/coach/* (34 routes).

The coach queue, per-session review, snippet lanes/stars/confidence, the
coach-owned ideal-text correction surface, training imports, audits and
breakthrough video. Moved verbatim out of ``routes/v2_routes.py`` (god-file
split, phase 2) -- route bodies are byte-identical to what was there before.

Routes register on the SAME ``v2_bp`` object, so endpoint names
("v2.<view_func>") and the URL map are unchanged by the split.

Formerly re-exported from the ``routes.v2_routes`` façade (removed 2026-09-14,
audit Q-A3); import from this module.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Optional

import sentry_sdk
from flask import jsonify, request

from config import Config
from routes.admin import is_admin, require_admin_or_coach, require_founder
from routes.phase2_guard import operational_purpose_disabled
from routes.v2.blueprint import v2_bp
from routes.v2.processing_authorization import speaker_provider_route
from services.rate_limits import heavy_limit, llm_limit, whisper_limit
# Module scope on purpose: `except DeadlineExceeded` in the upload routes
# must resolve even when the failure happens BEFORE the try body reaches
# its own imports — otherwise the handler NameErrors while handling.
from routes.v2.common import _is_valid_uuid
from services.db import db
from services.refusal import Refusal
from services.coach_pseudonym import coach_pseudonym as _coach_pseudonym
from services.coach_queue import bookmarks_for, load_review_queue
from services.coach_confidence_rating import (
    admit_rater, rating_body, rating_response, record_rating,
)
from services.coach_students import student_detail
from services.coach_video_upload import (
    read_video_upload, store_session_video, video_max_mb,
)
from services.training_import_request import start_training_import
from services.training_import_setup import setup_complete
from services.coach_review_claim import claim_review_and_reread
from services.parallel import run_in_parallel
from services.coach_video_storage import refreshed_media_url
from services.coach_moment_errors import (
    apply_moment_edit,
    coach_moment_fields,
)
from services.coach_practice_review import save_coach_decision
# Module level, because the packet SHAPER uses them and it is module level too
# — the blind rules belong beside the row they gate, not inside one route.
from services.coach_blind_gate import (
    has_committed_blind_label,
    reveal_owner_answer_after_commit,
)

logger = logging.getLogger(__name__)
config = Config()


# ══════════════════════════════════════════════════════════════════
# willab COACH SURFACE — canonical /v2/coach/* namespace (FE §F / PR #73).
#
# The FE coach overlay + queue speak this namespace + vocabulary: friendly
# `pseudonym`, per-snippet `coach_state`,
# state ∈ {pending,in_progress,done}. These routes are the alignment layer over
# the same handlers/db methods — no new logic, just the FE-facing shape. The
# namespace reversal (supersedes the earlier "re-gate /admin/*") is recorded in
# docs/coach-namespace-delta.md.
#
# IDENTITY (S.4 / §14 red-line 6): every coach response is pseudonymized —
# `pseudonym` + `domain` only, NEVER user_id / real name / email.
# ══════════════════════════════════════════════════════════════════

# Friendly, stable, non-reversible pseudonym (§B.4): one copy, in
# services.coach_pseudonym, shared with the coach's email threads.


def _drafts_by_snippet(session_id, draft_rows=None):
    """This session's drafts keyed by snippet.

    `draft_rows` lets a caller that already read many sessions in ONE query
    hand its rows in — the coach queue does, which is how that list stopped
    costing a round trip per take. None reads this one session, which is what
    every single-session caller wants and exactly what this did before.

    Lives outside `_coach_state_map` so the route fence's line budget for that
    function is spent on its own decision rather than on a lookup.
    """
    rows = (db.get_coach_snippet_drafts(session_id) or []
            if draft_rows is None else draft_rows)
    return {
        str(d.get("snippet_id")): d
        for d in rows if d.get("snippet_id") is not None
    }


def _coach_state_map(session_id, rater_id=None, *, draft_rows=None,
                     ratings=None, asks=None):
    """Per-snippet coach_state for the resume read.

    Draft authoring and the authenticated coach's own blind confidence rating
    are kept separate, then folded into one response object for the editor.

    RATING RESUME (2026-08-07). `rater_id` folds in THIS coach's own ternary
    rating so a rated snippet does not read as unanswered after a reload —
    the card had no way to know it had already been answered, and a coach
    re-rating from scratch is both wasted work and a second, non-independent
    look at the same clip.

    OWN ratings only, never the panel's. Another rater's answer on screen
    would anchor the next one and destroy the independence that makes
    multi-rater agreement mean anything. Omitting `rater_id` yields no
    ratings at all, which is the safe default for any caller that has not
    thought about whose answer it is showing.

    `ratings` and `asks` are this coach's own ratings of this session and
    their open asks (`open_asks`) when the caller already read them, as the
    session read does for a Take and its re-reads at once; None reads them.
    """
    drafts = _drafts_by_snippet(session_id, draft_rows)
    if ratings is None:
        ratings = (db.get_own_state_ratings_for_session(session_id, rater_id)
                   if rater_id else {})
    out = {}
    for sid in set(drafts) | set(ratings):
        d = drafts.get(sid) or {}
        r = ratings.get(sid) or {}
        out[sid] = {
            "note": (d.get("note") or ""),
            "tag": d.get("tag"),
            "surfaced": bool(d.get("surfaced")),
            "transcript_corrected": d.get("transcript_corrected"),
            # This coach's own ternary answer, or None/False when they have
            # not answered yet. `unrateable` is separate from `value` here for
            # the same reason it is separate everywhere else: an abstention is
            # not a third answer.
            "rating_value": r.get("value"),
            "rating_unrateable": bool(r.get("unrateable")),
        }
    if rater_id:
        # LISTEN AGAIN (0444; QG12a A, P26b A). While this coach has an open
        # ask on a moment, their earlier answer is masked here, the one map
        # every blind door keys on (the moment gate, the transcript and
        # owner-answer release, the practice door): the moment is blind
        # again until the new answer lands. The key of the signed line rides
        # as `listen_again`; nothing says why (BLIND COACH).
        from services.coach_listen_again import mask_states, open_asks
        if asks is None:
            asks = open_asks(db, coach_id=rater_id, session_ids=[session_id])
        out = mask_states(out, asks.get(str(session_id), {}))
    return out


def _confidence_queue_selection(session_id, session, snippets):
    """One source of truth for the blind queue and its post-label audit."""
    from services.confidence_labels import (
        corpus_label_queue, selection_records, stored_selection_records,
    )
    from services.corpus_spotting import stored_spotting

    ctx = session.get("intake_context") if isinstance(
        session.get("intake_context"), dict) else {}
    stored = stored_selection_records(ctx)
    if stored:
        by_id = {
            str(snippet.get("id")): snippet
            for snippet in snippets
            if isinstance(snippet, dict) and snippet.get("id")
        }
        # Persisted cohort order is part of the blind assignment. A set here
        # would quietly restore database order and could make position a tell.
        return [by_id[record["snippet_id"]] for record in stored
                if record["snippet_id"] in by_id]

    # An import's V3 spotting, when it has one, puts each block's pick and a
    # rival first (N56.4); without one this is the mixed queue, unchanged.
    selected = corpus_label_queue(
        snippets, stored_spotting(ctx), seed=str(session_id))
    records = selection_records(selected)
    if records:
        # Freeze the cohort and its selection provenance on first build.
        db.takes.set_session_intake_context(
            str(session_id), {**ctx, "label_queue_selection": records})
    return selected


def _stored_confidence_queue_count(context):
    """Canonical count for v2 cohorts and legacy ID-only sessions."""
    from services.confidence_labels import stored_selection_records
    return len(stored_selection_records(context))


def _session_recording(session):
    """Best-effort recording metadata used only for declared language."""
    recording_id = session.get("recording_id") if isinstance(session, dict) else None
    return db.get_recording(str(recording_id)) if recording_id else None


def _rater_language_outcome(session, snippets=None, proficient=None,
                            recordings=None):
    """Resolve queue eligibility for the current authenticated rater.

    Language is a routing dimension only. Unknown and mismatched clips are
    withheld; they are never converted to ``not_sure`` or ``audio_unclear``.

    ``recordings`` is a queue's batch of recording languages by recording id
    (``db.get_recording_languages``); None reads this session's recording.
    """
    from services.rater_languages import evaluate_rater_access, session_language

    rater_id = str(getattr(request, "user_id", "") or "")
    if proficient is None:
        proficient = db.get_user_proficient_languages(rater_id)
    # A declared language decides before the recording is looked at, so the
    # recording is read only when the Take declares none.
    if recordings is not None:
        recording = recordings.get(str((session or {}).get("recording_id")))
    else:
        recording = None if session_language(session) else _session_recording(session)
    language = session_language(
        session,
        recording=recording,
        snippets=snippets or [],
    )
    return evaluate_rater_access(proficient, language), language


def _rater_language_error(outcome, language=None):
    """HTTP workflow response for a non-routable blind-label request."""
    if outcome == "profile_required":
        return jsonify({
            "code": "RATER_LANGUAGES_REQUIRED",
            "error": "Choose the languages you understand before rating clips.",
        }), 428
    if outcome == "language_unknown":
        return jsonify({
            "code": "CLIP_LANGUAGE_UNKNOWN",
            "error": "This clip has no verified language and cannot be routed.",
        }), 409
    if outcome == "mismatch":
        return jsonify({
            "code": "RATER_LANGUAGE_MISMATCH",
            "error": "This clip is not in one of your selected languages.",
            "language": language,
        }), 409
    return None


def _practice_door_open(coach_state):
    """Q3 (founder 2026-09-29): any saved answer but Audio unclear opens the
    coach's practice review and exercise request. Yes, In-between, No and
    Not sure are answers about the moment; Audio unclear is an abstention,
    so the moment stays unrated and the door stays shut."""
    state = coach_state or {}
    return (
        state.get("rating_value") in ("yes", "in_between", "no", "not_sure")
        and not state.get("rating_unrateable")
    )


def _coach_state_for(session_id, snippet_id):
    """One snippet's coach_state (default-empty when nothing authored yet)."""
    return _coach_state_map(session_id).get(str(snippet_id), {
        "note": "", "tag": None, "surfaced": False,
        "transcript_corrected": None,
        "rating_value": None, "rating_unrateable": False,
    })


def _snippet_owner_map(session_id):
    """snippet_id → OWNING session id, across a take AND its folded mid-take
    re-reads (founder 2026-07-16: the coach edits the MERGED packet under the
    spoken take's path). Every write must persist under the row's own session
    — the downstream readers (key moments, labels export, the learning loop)
    are all keyed by the read's session id. Best-effort on the read lookup:
    a hiccup degrades to the parent take's snippets alone."""
    owners = {}
    for s in (db.get_snippets_by_session(session_id) or []):
        if s.get("id"):
            owners[str(s.get("id"))] = str(session_id)
    try:
        for r in (db.takes.get_read_sessions_for(session_id) or []):
            rid = str(r.get("id"))
            for s in (db.get_snippets_by_session(rid) or []):
                if s.get("id"):
                    owners.setdefault(str(s.get("id")), rid)
    except Exception as e:
        logger.warning(
            "snippet owner map: read lookup failed sid=%s: %s", session_id, e,
        )
    return owners


def _coach_session_state(session, cstate_map):
    """FE lifecycle state: done (published) > in_progress (any authoring) >
    pending (nothing authored yet)."""
    if session.get("results_published_at"):
        return "done"
    return "in_progress" if cstate_map else "pending"


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
        rows = db.takes.list_coach_students(limit=limit, offset=offset) or []
        # ONE PROFILE READ FOR THE WHOLE LIST. This read a whole profile per
        # student to render a single field; a hundred students meant a hundred
        # round trips before the coach saw a name.
        _profiles = db.get_user_profiles(
            [r.get("user_id") for r in rows if r.get("user_id")]) or {}
        out = []
        for r in rows:
            uid = r.get("user_id")
            prof = _profiles.get(str(uid)) or {}
            out.append({
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
        detail = student_detail(db, user_id)
        if detail is None:
            return jsonify({
                "code": "STUDENT_NOT_FOUND",
                "error": "No willab student for that id.",
            }), 404
        return jsonify({"pseudonym": _coach_pseudonym(user_id), **detail}), 200
    except Exception as e:
        logger.error("coach/student-detail GET failed user=%s err=%s", user_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch student"}), 500


@v2_bp.route("/coach/students/<user_id>/audit", methods=["GET"])
@require_admin_or_coach
def v2_coach_student_audit(user_id):
    """willab user_audit — coach panel DOWNLOAD (UX Wave 3 BE-3 / S5).
    Assembled from delivered exact-evidence FeedbackItems (no generator).
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
    FIFO (oldest sent first). Each row: {session_id, pseudonym, domain,
    topic, n_snippets, state, sent_at, arc_id?, take_index?, has_reread?}.
    No user_id: rows are grouped by pseudonym (founder 2026-10-20, replacing
    the 2026-07-16 opaque drill key). Read rows are folded into their parent
    take (never listed); has_reread marks the parent."""
    try:
        # An unset profile is a setup state, not an empty queue: make the
        # distinction explicit so the UI can ask once rather than silently
        # suggesting that no work exists.
        proficient = db.get_user_proficient_languages(
            str(getattr(request, "user_id", "") or ""))
        if not proficient:
            return _rater_language_error("profile_required")

        rows, _snips, _states = load_review_queue(db, _coach_state_map)
        out = []
        for r in rows:
            sid = r.get("id")
            snippets = _snips.get(str(sid)) or []
            outcome, _language = _rater_language_outcome(
                r, snippets, proficient=proficient)
            if outcome != "matched":
                # Unknown and mismatched sessions remain stored and can be
                # routed to another eligible coach. They are not ratings.
                continue
            ctx = r.get("intake_context") if isinstance(r.get("intake_context"), dict) else {}
            cstate = _states.get(str(sid)) or {}
            out.append({
                "session_id": sid,
                # Speakers are grouped by pseudonym; no user_id reaches a coach
                # (founder 2026-10-20).
                "pseudonym": _coach_pseudonym(r.get("user_id")),
                "domain": (ctx or {}).get("domain") or "",
                "topic": (ctx or {}).get("topic") or "",
                # Annotation-mode uploads (T4) ride the SAME queue + UI,
                # labeled so the coach can tell them from student takes.
                "annotation_mode": bool((ctx or {}).get("annotation_mode")),
                "n_snippets": len(snippets),
                "state": _coach_session_state(r, cstate),
                "sent_at": r.get("review_requested_at") or r.get("created_at") or "",
                # Grouping labels (additive; None on pre-arc rows).
                "arc_id": r.get("arc_id"),
                "take_index": r.get("take_index"),
                # This take has folded mid-take re-read(s) inside its packet.
                "has_reread": bool(r.get("has_reread")),
            })
        out.sort(key=lambda x: x.get("sent_at") or "")  # FIFO, oldest first
        return jsonify(out), 200
    except Exception as e:
        logger.error("coach/queue GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch coach queue"}), 500


@v2_bp.route("/coach/queue/moments", methods=["GET"])
@require_admin_or_coach
def v2_coach_moments_queue():
    """The coach's walk (founder 2026-09-30, A1 to A8; P2-6): speakers
    oldest first, their takes, and each bookmarked moment with one word for
    where THIS coach is with it. The kind of a moment rides only once this
    coach has rated it (BLIND COACH). Only moments the speaker was shown
    (opened or skipped) or answered are listed (N48.2, Q1 A). Same language
    filter and pseudonyms as the review queue; the shape is
    services.coach_moments_queue'. The ledger routes the clip (K4, K5): a
    moment this coach reported as Audio unclear goes to another coach, a
    quarantined or settled one asks nobody new; routing only, never a value."""
    from services.coach_moments_queue import queue_for_coach
    try:
        rater_id = str(getattr(request, "user_id", "") or "")
        proficient = db.get_user_proficient_languages(rater_id)
        if not proficient:
            return _rater_language_error("profile_required")
        rows, snips, _states = load_review_queue(db, snippets=False)
        matched = _language_matched_rows(rows, snips, proficient)
        return jsonify(queue_for_coach(
            db, matched, rater_id=rater_id,
            moments_for=_queue_moments_for(matched),
            pseudonym_for=_coach_pseudonym)), 200
    except Exception as e:
        logger.error("coach/queue/moments GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch the queue"}), 500


@v2_bp.route("/coach/queue/moments/close", methods=["POST"])
@require_founder
def v2_coach_close_moments():
    """The founder's Delete on a speaker's row of the queue (2026-10-20):
    the speaker's waiting moments leave every coach's queue; the Takes, their
    requests and their Ideal Text stay. Body {session_ids}: the speaker's
    Takes. What closes is what the founder's own queue counts as waiting on
    them, so the row's number is exactly what goes, and a Take still waiting
    for its text closes whole (the greyed row); a Take not in the review
    queue closes nothing. 200 {closed: n} · 400 · 403 · 500."""
    from services.coach_moments_queue import (
        MAX_CLOSE_TAKES, close_moments, queue_for_coach, waiting_for_text,
        waiting_moments,
    )
    body = request.get_json(silent=True)
    ids = body.get("session_ids") if isinstance(body, dict) else None
    if (not isinstance(ids, list) or not 0 < len(ids) <= MAX_CLOSE_TAKES
            or not all(_is_valid_uuid(str(i)) for i in ids)):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "session_ids must list the speaker's Takes."}), 400
    try:
        wanted = {str(i) for i in ids}
        rows, _snips, _states = load_review_queue(db, snippets=False)
        rows = [r for r in rows if str(r.get("id")) in wanted]
        queue = queue_for_coach(
            db, rows, rater_id=str(getattr(request, "user_id", "") or ""),
            moments_for=_queue_moments_for(rows),
            pseudonym_for=_coach_pseudonym, alarm=False)
        return jsonify({"closed": close_moments(
            db, rows, waiting_moments(queue), whole=waiting_for_text(queue))}), 200
    except Exception as e:
        logger.error("coach/queue/moments/close failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not close those moments."}), 500


@v2_bp.route("/coach/speakers", methods=["GET"])
@require_admin_or_coach
def v2_coach_speakers():
    """The Speakers button (coach panel lock, founder 2026-10-07): every
    speaker this coach may hear, by pseudonym, with their goal, what waits
    and which Takes are answered. Same language gate as the queue; never a
    name, email or user_id; nothing about any moment (BLIND COACH)."""
    from services.coach_speakers import speakers_for_coach
    try:
        rater_id = str(getattr(request, "user_id", "") or "")
        proficient = db.get_user_proficient_languages(rater_id)
        if not proficient:
            return _rater_language_error("profile_required")
        rows, snips, _states = load_review_queue(db, snippets=False)
        matched = _language_matched_rows(rows, snips, proficient)
        return jsonify(speakers_for_coach(
            db, matched, rater_id=rater_id,
            moments_for=_queue_moments_for(matched),
            pseudonym_for=_coach_pseudonym)), 200
    except Exception as e:
        logger.error("coach/speakers GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to fetch the speakers"}), 500


# Phase 4 / Prompt 2 — the AI-Commentator draft the coach's comment
# field opens PRE-FILLED with (frozen; the coach types over it). {} when
# the migration hasn't run → blank field, same as before.
# Coach comment pre-fill RETIRED (founder 2026-07-14): "no pre-filled
# comment; the system should learn from what the coach writes." So the
# editable note now opens EMPTY and every snippet defaults NOT-shown
# (surfaced=False) — the coach opts IN only the moments they mark as
# key/breakthrough. (The ai_draft column is no longer generated by
# default; it stays readable behind COACH_PREFILL_ENABLED for a
# possible revert, but is neither surfaced nor promoted here.)
def _language_matched_rows(rows, snips, proficient):
    """The queue rows this rater may see, and one internal log line for each
    Take withheld by language, naming the filter (founder 2026-10-01, 0a:
    a Take that leaves the queue is never silently absent). Nothing here
    reaches a user.

    The recordings' languages are read once for the whole queue: a read per
    Take was the bulk of the coach panel's load time (founder 2026-10-18).
    Only a Take that declares no language needs its recording: a declared
    one decides before the recording is looked at (founder 2026-10-21)."""
    from services.rater_languages import session_language
    recordings = db.get_recording_languages(
        [row.get("recording_id") for row in rows if not session_language(row)])
    matched = []
    for row in rows:
        sid = str(row.get("id"))
        outcome, language = _rater_language_outcome(
            row, snips.get(sid) or [], proficient=proficient,
            recordings=recordings)
        if outcome == "matched":
            matched.append(row)
        else:
            logger.info("coach queue: take withheld sid=%s filter=language "
                        "outcome=%s language=%s", sid, outcome, language)
    return matched


def _queue_moments_for(rows):
    """The queue's `moments_for`: a take's bookmarked snippet ids in order,
    or None while its bookmarks are not frozen yet. Not a drop: the take
    rides as "Waiting for the text" (founder 2026-10-01, A1) until the bake
    or the first read freezes them, and the log names the filter. The
    frozen sets of every row in `rows` are read in one batch, not one read
    per Take (founder 2026-10-18), and only the bookmarked snippets are
    read to order them, not every piece of every Take (founder 2026-10-21):
    services.coach_queue.bookmarks_for."""
    return bookmarks_for(db, rows, _bookmarked_snippet_ids)


def _frozen_feedback_set(arc_id, session_id, feedback_sets=None):
    """This Take's frozen selection: from a queue's batch when one is handed
    in (``db.get_ideal_text_feedback_sets``), else one read."""
    if feedback_sets is None:
        return db.get_ideal_text_feedback_set(str(arc_id), str(session_id))
    return next((row for row in feedback_sets.get(str(session_id)) or []
                 if str(row.get("arc_id")) == str(arc_id)), None)


def _bookmarked_snippet_ids(session, session_id, feedback_sets=None):
    """The snippets this take actually surfaced to the USER as bookmarks.

    FOUNDER 2026-09-24: "I want to have those that were bookmarked, green and
    orange and only them, cause the user potentially judged them; and thus the
    judgement from the coach should be on those too." He then settled on
    marking rather than filtering — the coach still walks every piece, and the
    bookmarked ones simply say so.

    THE SET IS THE MANAGER'S FROZEN SELECTION, not a re-derivation. Recomputing
    "what would be selected now" could disagree with what the user was actually
    shown, and a coach marking a moment the user never met is worse than no
    mark at all. `ideal_text_feedback_sets` is that freeze, insert-once per
    take, and each of its keys carries the snippet it landed on.

    CONFIDENT VOICE ONLY. Those are the moments the user was asked the
    confidence question about, and the coach's blind pass asks the same
    question — so they are the ones whose answers are comparable. The other
    lanes (praise, rewrite) are not bookmarks in that sense.

    Returns None while the take has no frozen selection yet, so the queue
    can say "Waiting for the text" instead of silently listing nothing
    (founder 2026-10-01, A1); an empty set means frozen with no Confident
    Voice bookmark. A read miss degrades to the empty set, never to a wrong
    mark.
    """
    arc_id = session.get("arc_id") if isinstance(session, dict) else None
    if not arc_id or not session_id:
        return set()
    try:
        row = _frozen_feedback_set(arc_id, session_id, feedback_sets)
        if not row:
            return None
        from services.take_feedback_set import (
            CONFIDENT_VOICE_FAMILY, sanitize_selected_keys,
        )
        return {
            str(key["snippet_id"])
            for key in sanitize_selected_keys(row.get("selected_keys"))
            if key.get("feedback_family") == CONFIDENT_VOICE_FAMILY
            and key.get("snippet_id")
        }
    except Exception as e:
        # Best-effort: a marker is not worth failing the review over. An empty
        # set degrades to today's screen (no marks), never to a wrong one.
        logger.warning("bookmarked snippet ids failed sid=%s err=%s",
                       session_id, e)
        return set()


def _owner_confidence_answers(session):
    """What the SPEAKER answered about each moment of this arc, by snippet.

    FOUNDER 2026-09-24: "in the coach review I want to see what the user judged
    after I judge it." One read for the whole packet rather than one per piece.

    Their self-report lane and nothing else: `take_feedback_self_report`, whose
    `provenance` column is CHECK-constrained to `user_self_report`, filtered to
    the confident-voice family — the same question the coach is being asked, so
    the two answers are about the same thing. Nothing here writes, and no coach
    table is touched: L3 keeps the lanes separate in storage, which is where it
    means it.
    """
    arc_id = session.get("arc_id") if isinstance(session, dict) else None
    if not arc_id:
        return {}
    try:
        rows = db.list_confident_voice_self_reports(str(arc_id)) or []
    except Exception as e:
        logger.warning("owner confidence answers failed arc=%s err=%s",
                       arc_id, e)
        return {}
    out = {}
    for row in rows:
        sid = str((row or {}).get("snippet_id") or "")
        response = str((row or {}).get("response") or "")
        # Ordered by created_at, so the LAST write for a moment is the
        # speaker's current answer — the same "current answer" the coach's own
        # table keeps.
        if sid and response:
            out[sid] = response
    return out


def _shape_coach_review_packet(readout, cstate_map, session_id, held):
    """Every evidence piece of one take, each saying whether it was bookmarked.

    Its own function so the route does not grow. The bookmarks and the
    speaker's answers are one read each for the whole packet rather than one
    per piece, made beside the claim (`_coach_review_reads`).
    """
    return [
        _shape_coach_review_snippet(
            snip, cstate_map, str(session_id),
            bookmarked_ids=held["bookmarked"],
            owner_answers=held["owner_answers"])
        for snip in (readout.get("snippets") or [])
    ]


def _shape_coach_review_snippet(snip, cstate_map, owning_sid,
                                kind_default=None, bookmarked_ids=None,
                                owner_answers=None):
    _sid = str(snip.get("id"))
    _coach_state = dict(cstate_map.get(_sid, {
        "note": "", "tag": None, "surfaced": False,
    }))
    return {
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
        # Spoken vs read (founder 2026-07-14) — which delivery this
        # snippet is: the original spoken take or the re-read of the
        # corrected text. The coach labels each by it; the FE renders
        # the small "re-read" chip from it.
        "recording_kind": snip.get("recording_kind") or kind_default,
        # Which session this row PERSISTS under (founder 2026-07-16 —
        # the folded packet spans the take + its re-reads; writes on
        # this snippet route to this session).
        "take_session_id": owning_sid,
        # NO machine comment pre-fill (founder 2026-07-14): the coach
        # writes the key-moment comment from scratch; the system learns
        # from what they write.
        "coach_state": _coach_state,
        # Did the USER meet this moment as a bookmark (founder 2026-09-24)?
        # One boolean, never the tier: the coach is told the moment was
        # surfaced, never what the machine made of it.
        "bookmarked": _sid in (bookmarked_ids or set()),
        # What the SPEAKER answered about this same moment — released only
        # after THIS coach has committed their own, exactly as the transcript
        # is. Gated HERE rather than in the redactor because the unlocked
        # packet never passes through it, and a coach who skipped a moment
        # must not be handed the speaker's answer to it.
        "owner_answer": reveal_owner_answer_after_commit(
            (owner_answers or {}).get(_sid),
            committed=has_committed_blind_label(_coach_state),
        ),
    }


def _claim_attempt(session_id, session, actor_id, actor_is_admin):
    """Claim the review, then re-read the session under the claim:
    ``(session, None)``, or ``(None, error)`` with what either step raised.
    It runs beside the packet's reads, on another thread, so the error is
    handed back for `_claim_coach_review` to answer on the request's own."""
    try:
        return claim_review_and_reread(
            db, session_id, actor_id,
            actor_is_admin=actor_is_admin, before_claim=session,
        ), None
    except Exception as e:  # noqa: BLE001 - handed back; _claim_coach_review logs it
        return None, e


def _claim_coach_review(session_id, session, attempt):
    """The answer to a claim attempt (`_claim_attempt`).

    Returns ``(session, None, read_only)``, or ``(None, error_response,
    False)`` when either step failed: a failed re-read is the same 503 as a
    failed claim.

    A review another coach already owns opens READ-ONLY (founder
    2026-10-08, "make sure the playbacks work all across the app"): K4
    routes an Audio-unclear moment to a second coach, and the moments queue
    does not filter by claimer, so that coach must still be able to hear the
    clip. Nothing is claimed for them, the payload goes through the same
    per-coach blind gate as the owner's (BLIND COACH), and the publish RPC
    still refuses a non-owner (``publish_coach_review_revision_v1``).
    """
    claimed, assignment_error = attempt
    if assignment_error is None:
        return claimed, None, False
    low = str(assignment_error).lower()
    if "unclaimed guest" in low:
        return None, (jsonify({
            "code": "UNCLAIMED_GUEST",
            "error": "This take must be claimed before coach review.",
        }), 409), False
    if "another coach" in low:
        logger.info(
            "coach/get-session: read-only open sid=%s (assigned to another coach)",
            session_id)
        return session, None, True
    logger.error(
        "coach/get-session: review assignment failed sid=%s: %s",
        session_id,
        assignment_error,
        exc_info=assignment_error,
    )
    return None, (jsonify({
        "code": "REVIEW_ASSIGNMENT_FAILED",
        "error": "Could not open this review safely.",
    }), 503), False


def _coach_session_readout(session_id, snippet_rows, session_row, held_rows):
    """The coach's readout for one session, built from rows already in hand.

    `include_slide_scores=True` gives the coach Stickiness #2: per-snippet
    on-slide-ness plus the per-slide coverage ledger. Coach-only (AC-9).

    The caller read the snippets for its language check and the session again
    after the review claim; `held_rows` are the session's transcript edits and
    suggestion taps, read beside the claim (`_coach_review_reads`). The session
    row serves its `intake_context` and `slide_transcripts` too, so the readout
    reads nothing of its own.

    The post-claim re-read (``_claim_coach_review``) STAYS, and this is why
    the session is passed rather than re-read here: review ownership must
    never be decided on a row read before the claim was taken.
    """
    from services.lab_recording import build_readout_from_session
    # include_insights=False (founder 2026-09-26, "the coach review is just
    # very long"): it only adds the published take's surfaced feedback items
    # and overall message, and the coach payload reads neither.
    return build_readout_from_session(
        session_id, include_insights=False, include_slide_scores=True,
        snippet_rows=snippet_rows, session_row=session_row, **held_rows)


def _read_sessions_of(session_id):
    """The Take's mid-take re-reads, oldest first; [] on a failed lookup, and
    the packet is then the parent take alone (LIVE LOOP)."""
    try:
        return [
            r for r in (db.takes.get_read_sessions_for(session_id) or [])
            if isinstance(r, dict) and r.get("id")
        ]
    except Exception as _rl_err:
        logger.warning("coach/get-session: read lookup failed sid=%s: %s",
                       session_id, _rl_err)
        return []


def _read_snippets_of(session_id, read_ids):
    """One snippet read for every re-read instead of one each (founder
    2026-09-26). An empty or failed batch gives {}, and each re-read's
    readout then reads its own snippets exactly as before."""
    if not read_ids:
        return {}
    try:
        return db.get_snippets_by_sessions(read_ids, include_words=True) or {}
    except Exception as _rb_err:
        logger.warning("coach/get-session: read batch failed sid=%s: %s",
                       session_id, _rb_err)
        return {}


def _readout_reads(session_id, *, with_slide_transcripts=False):
    """The reads of one session's readout that its rows do not carry, as
    ``{build_readout_from_session keyword: thunk}``: transcript edits,
    suggestion taps, and for a re-read (whose row has no `slide_transcripts`)
    its persisted per-slide transcript."""
    thunks = {
        "edit_rows": lambda: db.get_user_transcript_edits(session_id),
        "feedback_rows": lambda: db.get_suggestion_feedback_by_session(session_id),
    }
    if with_slide_transcripts:
        thunks["slide_transcripts"] = (
            lambda: db.takes.get_session_slide_transcripts(session_id))
    return thunks


def _coach_review_reads(session_id, session, rater_id):
    """Every read of the coach's session payload but the Take, its pieces and
    the claim, side by side (founder 2026-10-21: the coach's link took 6.7 s,
    about thirty reads one after another). Nothing here is decided by the
    claim, so it runs beside it; the packet is built only once it is taken.

    Two rounds: what needs only this Take (its re-reads among them), then
    what needs the re-reads' ids too, the coach's drafts, ratings and open
    asks read once for the Take and all its re-reads. Every reader is
    best-effort, as each was when it ran on its own.
    """
    from services.coach_listen_again import open_asks
    sid = str(session_id)
    take_reads = _readout_reads(sid)
    owner_answers, reads, bookmarked, *take_rows = run_in_parallel(
        # First: the speaker's answers are two reads (answers, revisions).
        lambda: _owner_confidence_answers(session),
        lambda: _read_sessions_of(sid),
        lambda: _bookmarked_snippet_ids(session, sid) or set(),
        *take_reads.values())
    held_rows = {sid: dict(zip(take_reads, take_rows))}
    read_ids = [str(r.get("id")) for r in reads]
    ids = [sid, *read_ids]
    read_reads = {
        (rid, key): thunk for rid in read_ids
        for key, thunk in _readout_reads(rid, with_slide_transcripts=True).items()
    }
    drafts, ratings, asks, read_snippets, *read_rows = run_in_parallel(
        lambda: db.get_coach_snippet_drafts_by_sessions(ids) or {},
        lambda: db.get_own_state_ratings_for_sessions(ids, rater_id) or {},
        lambda: open_asks(db, coach_id=rater_id, session_ids=ids),
        lambda: _read_snippets_of(sid, read_ids),
        *read_reads.values())
    for (rid, key), value in zip(read_reads, read_rows):
        held_rows.setdefault(rid, {})[key] = value
    return {
        "owner_answers": owner_answers,
        "bookmarked": bookmarked,
        "reads": reads,
        "read_snippets": read_snippets,
        "rows": held_rows,
        "states": {
            i: _coach_state_map(
                i, rater_id=rater_id or None,
                draft_rows=drafts.get(i) or [],
                ratings=ratings.get(i) or {}, asks=asks)
            for i in ids
        },
    }


def _fold_coach_review_reads(session_id, snippets, held):
    """Fold the re-reads' pieces into the Take's packet, from the rows
    `_coach_review_reads` holds, then stamp each folded re-read as opened."""
    from services.lab_recording import build_readout_from_session
    folded = []
    for _r in held["reads"]:
        _rid = str(_r.get("id"))
        rows = dict(held["rows"][_rid])
        # The re-read's own row, with the per-slide transcript read for it.
        session_row = {**_r, "slide_transcripts": rows.pop("slide_transcripts")}
        try:
            _r_readout = build_readout_from_session(
                _rid, include_insights=False, include_slide_scores=True,
                snippet_rows=held["read_snippets"].get(_rid),
                session_row=session_row, **rows)
            _r_snips = [
                _shape_coach_review_snippet(s, held["states"][_rid], _rid, "read")
                for s in (_r_readout.get("snippets") or [])
            ]
        except Exception as _rf_err:
            logger.warning(
                "coach/get-session: read fold failed sid=%s read=%s: %s",
                session_id, _rid, _rf_err)
            continue
        folded.append(_rid)
        snippets.extend(_r_snips)
    run_in_parallel(*[
        (lambda rid=rid: db.takes.stamp_review_opened(rid)) for rid in folded])
    return held["reads"]


def _session_shows_slides(session):
    """Could the surface that collected a rating for this session show a slide?

    FOUNDER 2026-09-24 put the slide on the coach's blind judgement screen, so
    a confidence label collected there is no longer a voice-only judgement and
    the corpus has to be able to say which it is (`saw_slide`).

    A DECK, NOT A ROW. The claim this stamps is about the SURFACE — the same
    thing `saw_model_output` claims — so it asks whether this session has a
    presentation at all, not whether the tap timeline mapped this particular
    moment onto a page. Three surfaces share the rating endpoint and only one
    of them draws slides: the imported-corpus queue rates clips that belong to
    no deck, so this reads false there and the claim stays true.

    Deliberately cheap. Resolving the moment's own slide means rebuilding the
    readout's tap timeline on every rating write, which is a large cost for a
    distinction the corpus does not draw.
    """
    if not isinstance(session, dict):
        return False
    ctx = session.get("intake_context")
    ctx = ctx if isinstance(ctx, dict) else {}
    return bool(str(ctx.get("presentation_ref") or "").strip())


def _coach_get_session_identity_fields(
    *, session_id, session, cstate, ctx, _context_unlocked, _blind_progress,
):
    return {
        "session_id": session_id,
        "pseudonym": _coach_pseudonym(session.get("user_id")),
        "domain": ((ctx or {}).get("domain") or "")
        if _context_unlocked else "",
        "topic": ((ctx or {}).get("topic") or "")
        if _context_unlocked else "",
        # The user's pre-recording named emotion (F2 handoff §2) —
        # their own self-report, founder-decided coach-visible (not a
        # machine guess; blind-coach untouched). No inferred
        # psychological category is attached or serialized.
        "named_emotion": ((ctx or {}).get("named_emotion")
                          if _context_unlocked else None),
        "sent_at": session.get("review_requested_at") or session.get("created_at") or "",
        "state": _coach_session_state(session, cstate),
        "arc_id": session.get("arc_id"),
        "context_unlocked": _context_unlocked,
        "blind_label": _blind_progress,
    }


def _coach_get_session_reads_fields(read_sessions, _context_unlocked):
    return {
        # Folded mid-take re-reads (founder 2026-07-16): their snippets
        # ride in snippets[] after the parent's, each stamped with its
        # owning take_session_id + recording_kind='read'.
        "has_reread": bool(read_sessions) if _context_unlocked else False,
        "read_session_ids": (
            [str(r.get("id")) for r in read_sessions]
            if _context_unlocked else []),
        # Per-read tags (founder 2026-07-20): an ideal-text re-read
        # carries read_target='ideal_text' + ideal_version in its
        # session_context → the coach UI labels it "Re-read of ideal
        # text vN". Additive beside read_session_ids; per-take re-reads
        # simply carry nulls. Coach-only surface.
        "reads": ([{
            "session_id": str(r.get("id")),
            "created_at": r.get("created_at"),
            "read_target": (r.get("intake_context") or {}).get(
                "read_target") if isinstance(
                r.get("intake_context"), dict) else None,
            "ideal_version": (r.get("intake_context") or {}).get(
                "ideal_version") if isinstance(
                r.get("intake_context"), dict) else None,
        } for r in read_sessions] if _context_unlocked else []),
    }


def _coach_get_session_media_fields(
    *, readout, ctx, _context_unlocked, _served_snippets,
):
    return {
        # `presentation_ref` — THE DECK FILE, AND IT IS NOT GATED (founder
        # 2026-09-25). The 2026-09-24 override already put `slide` on the
        # blind allowlist — "I want as a coach to see the slide at the top; to
        # know on which slide they are talking about" — but the file needed to
        # DRAW that slide stayed behind this gate, so the ruling only half
        # landed: the blind screen received a title and a body and redrew them
        # as text, and the coach was shown a reconstruction of their speaker's
        # slide rather than the slide.
        #
        # It discloses nothing the override did not already allow. The page is
        # the same page; only its fidelity changes. What pays for it is the
        # same thing that pays for `slide`: every rating written from this
        # surface is stamped `saw_slide`, so the corpus can tell a voice-only
        # label from a voice-plus-slide one instead of silently merging them.
        # Do not gate this again while `slide` is on that allowlist — the two
        # halves are one ruling and splitting them is what caused this.
        #
        # The whole deck (`slides`, for the slide-mapping control), the Take
        # Message and video, and the pre-recording feelings left with the
        # arc-level delivery (founder 2026-09-30, B3 to B6; contract 65).
        "presentation_ref": refreshed_media_url(
            (ctx or {}).get("presentation_ref") or None),
        # Per-slide coverage ledger (Stickiness #2 (i)) — coach audit.
        "slide_coverage": (readout.get("slide_coverage") or [])
        if _context_unlocked else [],
        "snippets": _served_snippets,
    }


def _coach_get_session_response(
    *, session_id, session, cstate, readout, ctx, _context_unlocked,
    _blind_progress, _served_snippets, read_sessions, read_only=False,
):
    """``read_only`` is True when another coach owns this review (founder
    2026-10-08): the clip plays and this coach's own judgements save, but
    review-level publishing is not theirs (the publish RPC refuses a
    non-owner), and the payload stays on the blind allowlist even after all
    of their own answers: their answers reveal their own rows' words only,
    never the owner's contextual editor."""
    return {
        "read_only": bool(read_only),
        **_coach_get_session_identity_fields(
            session_id=session_id, session=session, cstate=cstate, ctx=ctx,
            _context_unlocked=_context_unlocked, _blind_progress=_blind_progress,
        ),
        **_coach_get_session_reads_fields(read_sessions, _context_unlocked),
        **_coach_get_session_media_fields(
            readout=readout, ctx=ctx,
            _context_unlocked=_context_unlocked, _served_snippets=_served_snippets,
        ),
    }


@v2_bp.route("/coach/sessions/<session_id>", methods=["GET"])
@require_admin_or_coach
def v2_coach_get_session(session_id):
    """② Coach review session payload (FE PR #73 → /v2/coach/sessions/<id>).

    Identity-stripped (S.4): pseudonym + domain only — NO user_id / name /
    email. Per-snippet coach_state folds the coach's note / tag / surfaced
    authoring so it all resumes on reopen.

    Moments remain in spoken order. Folded re-reads keep their own order and
    are appended after the take.
    """
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    rater_id = str(getattr(request, "user_id", "") or "")
    try:
        # Reads that need only the ids, side by side (founder 2026-10-21: the
        # coach's link took 6.7 s, every read waiting on the one before).
        session, snippets_for_language, proficient = run_in_parallel(
            lambda: db.v2_get_session_by_id(session_id),
            lambda: db.get_snippets_by_session(session_id) or [],
            lambda: db.get_user_proficient_languages(rater_id))
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        language_outcome, _language = _rater_language_outcome(
            session, snippets_for_language, proficient=proficient or [])
        language_error = _rater_language_error(language_outcome, _language)
        if language_error is not None:
            return language_error

        # First open atomically owns the review; another coach's review opens
        # read-only and blind (_claim_coach_review). Publishing stays the owner's.
        # The packet's reads run beside the claim, none decided by it.
        actor_is_admin = is_admin(rater_id)
        attempt, held = run_in_parallel(
            lambda: _claim_attempt(session_id, session, rater_id, actor_is_admin),
            lambda: _coach_review_reads(session_id, session, rater_id))
        session, claim_error, read_only = _claim_coach_review(
            session_id, session, attempt)
        if claim_error is not None:
            return claim_error

        readout = _coach_session_readout(
            session_id, snippets_for_language, session,
            held["rows"][str(session_id)])
        cstate = held["states"][str(session_id)]

        snippets = _shape_coach_review_packet(readout, cstate, session_id, held)
        # Fold the paired mid-take RE-READS into this take's packet (founder
        # 2026-07-16: "re-reads are part of the take, revealed by clicking
        # next, never separate items"). Appended AFTER the parent's pieces —
        # NEVER sorted across sessions by start_offset_ms (the read's clock
        # restarts at 0). Best-effort: a fold hiccup degrades to the parent
        # take alone (LIVE LOOP).
        read_sessions = _fold_coach_review_reads(session_id, snippets, held)
        # One continuous "next" sequence across the merged packet.
        for _i, _s in enumerate(snippets):
            _s["index"] = _i

        # BLIND-FIRST.  The contextual editor unlocks only after THIS coach
        # has committed a rating (or explicit technical abstention) for every
        # evidence piece in the packet.  Until then the server returns an
        # allowlisted audio+transcript packet, so a frontend regression cannot
        # reveal words, slide, analytics, or user-facing draft before the
        # label.  Each row's transcript is released only after THIS coach has
        # committed that row's audio-only answer.
        from services.coach_blind_gate import (
            blind_label_progress, redact_contextual_snippets,
        )
        _blind_progress = blind_label_progress(snippets)
        _context_unlocked = bool(_blind_progress["complete"]) and not read_only
        _served_snippets = (
            snippets if _context_unlocked
            else redact_contextual_snippets(snippets)
        )

        ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
        return jsonify(_coach_get_session_response(
            session_id=session_id, session=session, cstate=cstate,
            readout=readout, ctx=ctx, _context_unlocked=_context_unlocked,
            _blind_progress=_blind_progress, _served_snippets=_served_snippets,
            read_sessions=read_sessions, read_only=read_only,
        )), 200
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
        # The session row is already in hand from the 404 check above.
        readout = build_readout_from_session(
            session_id, include_slide_scores=True, session_row=session)
        coverage = readout.get("slide_coverage") or []
        if not coverage:
            return jsonify({"available": False}), 200
        return jsonify({"slide_coverage": coverage}), 200
    except Exception as e:
        logger.error("coach/slide-alignment failed sid=%s err=%s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to compute slide alignment"}), 500


@v2_bp.route("/coach/snippets/<snippet_id>/reference", methods=["PUT"])
@require_admin_or_coach
def v2_coach_put_moment_reference(snippet_id):
    """Attach (or clear) a blog post as further reading on ONE moment.

    Ticket 6, founder 2026-07-26: the COACH picks the post by hand, and only on
    a coach-verified ("golden star") moment. No automatic or LLM matching — the
    ask was "material that matches exactly this problem", and a wrongly-attached
    post reads as sloppy.

    Body { slug: str }   → attach that post
    Body { slug: null }  → clear the reference

    The slug is validated against the Journal, so a typo fails HERE rather than
    silently producing a moment whose reference never renders. A DRAFT post is
    accepted (the coach may line one up before publishing) but the student
    payload omits it until the post is actually published — same
    draft-invisibility rule the public Journal uses.

    200 { saved, snippet_id, reference_post_slug } · 400 · 404 · 500
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT", "error": "snippet_id must be a valid UUID",
        }), 400
    body = request.get_json(silent=True) or {}
    if "slug" not in body:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "slug: required (null to clear)"}), 400
    raw = body.get("slug")
    slug = raw.strip() if isinstance(raw, str) else None
    if raw is not None and not isinstance(raw, str):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "slug: must be a string or null"}), 400
    try:
        snip = db.get_snippet_by_id(snippet_id)
        if not snip or not snip.get("session_id"):
            return jsonify({"code": "NOT_FOUND",
                            "error": "snippet not found"}), 404
        if slug:
            # Accept a draft (published_only=False) — the coach may attach
            # before publishing — but a slug that does not exist at all is a
            # typo and must fail loudly.
            if not db.get_journal_post_by_slug(slug, published_only=False):
                return jsonify({"code": "NOT_FOUND",
                                "error": f"no blog post with slug '{slug}'"}), 404
        saved = db.upsert_coach_snippet_draft(
            str(snip.get("session_id")), snippet_id,
            {"reference_post_slug": slug or None},
            updated_by=getattr(request, "user_id", None),
        )
        if saved is None:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Could not save the reference",
            }), 500
        return jsonify({
            "saved": True,
            "snippet_id": snippet_id,
            "reference_post_slug": slug or None,
        }), 200
    except Exception as e:
        logger.error("coach reference save failed snip=%s: %s", snippet_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the reference"}), 500


@v2_bp.route("/coach/snippets/<snippet_id>/say-it-stronger", methods=["PUT"])
@llm_limit
@require_admin_or_coach
def v2_coach_put_say_it_stronger(snippet_id):
    """Coach-corrected 'Say It Stronger' card (Engine 1, founder 2026-07-11).

    The auto card generates instantly at upload; the coach edits it here.
    The user readout folds FINAL over AUTO the moment this saves — the auto
    draft column stays untouched (the (draft, final) pair is the future
    correction corpus). Validated through the SAME cleaner as generation
    (shape, ≤3 upgrades, kind enum, AC-9 guard on why/reasons — digits and
    construct vocabulary are nulled, coach input included).

    Body: the card object {already_strong, upgrades, rewrite_your_voice,
          rewrite_polished, why}.
    200 { saved, snippet_id, say_it_stronger } · 400 · 404 · 500
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT", "error": "snippet_id must be a valid UUID",
        }), 400
    try:
        snip = db.get_snippet_by_id(snippet_id)
        if not snip:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND", "error": "Snippet not found",
            }), 404
        body = request.get_json(silent=True)
        from services.say_it_stronger import _clean_payload
        cleaned = _clean_payload(
            body, (snip.get("transcript")
                   or snip.get("transcription_text") or ""),
        )
        if cleaned is None:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "Not a valid Say It Stronger card",
            }), 400
        cleaned["edited_by_coach"] = True
        if not db.set_charisma_snippet_say_it_stronger_final(
                str(snippet_id), cleaned):
            return jsonify({
                "code": "V2_ERROR", "error": "Could not save the card",
            }), 500
        return jsonify({
            "saved": True, "snippet_id": snippet_id,
            "say_it_stronger": cleaned,
        }), 200
    except Exception as e:
        logger.error("coach say-it-stronger PUT failed snip=%s: %s",
                     snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save card"}), 500


def _speaker_practice_permitted(take_session_id: str) -> bool:
    """Whether the speaker behind this Take allows practice (E3).

    A coach may not send an exercise to someone who turned practice off, or
    never turned it on: choosing one for them is the practice purpose, not
    coach review. Asked of the one boundary that decides it, about the
    SPEAKER, never the coach making the request: the speaker as their own
    Data & consent page reads them (take_speaker_principal), not the acquirer
    of this one recording, which for an older Take can be an earlier
    principal of theirs with no receipt of the policy in force.
    """
    from services.processing_authorization import (
        PERSONALISED_PRACTICE,
        ProcessingAuthorizationService,
    )
    service = ProcessingAuthorizationService(db)
    try:
        principal = service.take_speaker_principal(str(take_session_id))
    except Exception as e:
        logger.warning("coach practice gate: speaker unresolved take=%s: %s",
                       take_session_id, e)
        return not service.enforced
    if service.choice_permitted(principal, PERSONALISED_PRACTICE):
        return True
    # Why, so the next refusal is read from the logs: an explicit no, no
    # receipt of the policy in force, or a read that failed (all None).
    choices = service.consent_choices(principal) or {}
    logger.warning(
        "coach practice gate refused take=%s principal=%s choices=%s",
        take_session_id, principal,
        {key: choices.get(key) for key in (
            "has_receipt", "policy_id", "practice_in_service",
            PERSONALISED_PRACTICE)})
    return False


def _coach_moment_edit(practice: dict):
    """PATCH on the practice review: name an error, or undo a teaching.

    Reached only through the practice route, AFTER its blind gate, so an
    edit here is behind exactly the gate and the purpose guard the review
    itself is. The work is apply_moment_edit's.
    """
    status, error = apply_moment_edit(
        db, practice, request.get_json(silent=True) or {},
        str(getattr(request, "user_id", "")))
    if error:
        return jsonify(error), status
    return jsonify({"practice": _coach_practice_payload(practice)}), status


def _machine_pick(practice: dict) -> Optional[dict]:
    """What the machine picked for this moment and why (step 6). Reached only
    through the practice route, after its blind gate; routing only, never the
    machine's confidence read."""
    from services.exercise_pick_view import machine_pick
    return machine_pick(db, practice.get("take_session_id"),
                        practice.get("snippet_id"))


def _coach_practice_payload(practice: dict) -> dict:
    """Coach-only attempt bundle, intentionally separate from blind packet."""
    from services.audio_ref_resolver import resolve_playable_ref
    from services.confident_voice_practice import ASSESSMENT_COPY, coach_exercise_order
    original_raw = db.get_active_diagnostic_exercise(
        str(practice.get("exercise_id") or "")) or \
        (practice.get("exercise_snapshot")
         if isinstance(practice.get("exercise_snapshot"), dict) else {})
    original_exercise: dict[str, Any] = (
        original_raw if isinstance(original_raw, dict) else {})
    custom_exercise = practice.get("coach_custom_exercise")
    exercise: dict[str, Any]
    if isinstance(custom_exercise, dict):
        exercise = custom_exercise
    else:
        selected_exercise = db.get_active_diagnostic_exercise(
            str(practice.get("coach_selected_exercise_id")
                or practice.get("exercise_id") or "")) or original_exercise
        exercise = (selected_exercise
                    if isinstance(selected_exercise, dict) else {})
    # Best match for THIS clip first, by the speaker's own ranking; every
    # reviewed exercise stays in the list (coach_exercise_order).
    available_exercises = [{
        "exercise_id": active.get("exercise_id"),
        "version": active.get("version"),
        "title": active.get("title"),
        "instruction": active.get("instruction"),
        "explanation_video_ref": active.get("explanation_video_url"),
    } for active in coach_exercise_order(practice, db)]
    attempts = db.list_confident_voice_practice_attempts(
        str(practice.get("id")))
    return {
        "id": str(practice.get("id")),
        "project_id": str(practice.get("project_id")),
        "take_session_id": str(practice.get("take_session_id")),
        "snippet_id": str(practice.get("snippet_id")),
        "slide_index": practice.get("slide_index"),
        "paragraph_index": practice.get("paragraph_index"),
        "evidence_span": practice.get("evidence_span"),
        "exact_passage": practice.get("exact_passage"),
        "original_audio_ref": resolve_playable_ref(
            practice.get("original_audio_ref")),
        "original_start_offset_ms": practice.get("original_start_offset_ms"),
        "original_duration_ms": practice.get("original_duration_ms"),
        "original_user_answer": practice.get("original_user_answer"),
        "final_user_answer": practice.get("final_user_answer"),
        "selected_attempt_id": practice.get("selected_attempt_id"),
        "professional_coach_decision": practice.get(
            "professional_coach_decision"),
        "coach_shared_at": practice.get("coach_shared_at"),
        "exercise": {
            "exercise_id": exercise.get("exercise_id")
                           or practice.get("exercise_id"),
            "version": exercise.get("version")
                       or practice.get("exercise_version"),
            "title": exercise.get("title"),
            "instruction": exercise.get("instruction"),
            "explanation_video_ref": (
                practice.get("coach_explanation_video_url")
                or exercise.get("explanation_video_url")
                or exercise.get("explanation_video_ref")
            ),
            "is_custom": isinstance(custom_exercise, dict),
        },
        "available_exercises": available_exercises,
        "machine_pick": _machine_pick(practice),
        **coach_moment_fields(practice, db),
        "attempts": [{
            "id": str(row.get("id")),
            "attempt_index": row.get("attempt_index"),
            "audio_ref": resolve_playable_ref(row.get("audio_ref")),
            "duration_ms": row.get("duration_ms"),
            "comparison": row.get("comparison"),
            "assessment_key": row.get("assessment_key"),
            "assessment": ASSESSMENT_COPY.get(
                str(row.get("assessment_key") or ""),
                "Acoustically similar."),
            "is_strongest": bool(row.get("is_strongest")),
            "is_selected": str(row.get("id")) == str(
                practice.get("selected_attempt_id") or ""),
            "kept": bool(row.get("kept")),
            "user_answer": row.get("user_answer"),
            # The machine leg remains private so it cannot anchor this
            # professional judgment. The coach sees only their own saved
            # answer on the selected practice recording.
            "coach_confidence_decision": row.get(
                "coach_confidence_decision"),
        } for row in attempts],
    }



@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/confidence-practice",
    methods=["GET", "PUT", "PATCH"],
)
@require_admin_or_coach
@operational_purpose_disabled("personalized_exercise_recommendation")
def v2_coach_confident_voice_practice(session_id, snippet_id):
    """Review/share practice only after the coach's blind moment rating.

    This is a separate request rather than a field in the normal session
    packet.  Therefore the machine-routed exercise and owner answers cannot
    anchor the coach before their independent confidence judgment is saved.
    """
    if not _is_valid_uuid(session_id) or not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "session_id and snippet_id must be UUIDs"}), 400
    session = db.v2_get_session_by_id(session_id)
    if not session:
        return jsonify({"code": "SESSION_NOT_FOUND",
                        "error": "Session not found"}), 404
    owner_sid = _snippet_owner_map(session_id).get(snippet_id)
    if not owner_sid:
        return jsonify({"code": "SNIPPET_NOT_FOUND",
                        "error": "Snippet not in this session"}), 404
    # Hard blind gate: the current coach must first commit their own rating.
    state = _coach_state_map(owner_sid, rater_id=getattr(request, "user_id", None))
    coach_state = state.get(str(snippet_id)) or {}
    if not _practice_door_open(coach_state):
        return jsonify({"code": "BLIND_RATING_REQUIRED",
                        "error": "Rate the original moment before reviewing practice."}), 409
    if not _speaker_practice_permitted(owner_sid):  # E3, founder 2026-09-25
        return jsonify({"code": "SPEAKER_PRACTICE_OFF",
                        "error": "The speaker turned practice off."}), 409
    practice = db.get_confident_voice_practice_by_moment(owner_sid, snippet_id)
    if not practice or str(practice.get("snippet_id")) != str(snippet_id):
        return jsonify({"code": "NOT_FOUND",
                        "error": "practice not found"}), 404
    if request.method == "GET":
        return jsonify({"practice": _coach_practice_payload(practice)}), 200
    if request.method == "PATCH":
        return _coach_moment_edit(practice)

    try:
        updated = save_coach_decision(
            db, practice, request.get_json(silent=True) or {},
            str(request.user_id))
    except Refusal as refusal:
        return jsonify(refusal.body), refusal.status
    return jsonify({"practice": _coach_practice_payload(updated)}), 200


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/exercise-request",
    methods=["GET", "PUT"],
)
@require_admin_or_coach
@operational_purpose_disabled("personalized_exercise_recommendation")
def v2_coach_exercise_request(session_id, snippet_id):
    """A moment no exercise fitted (founder 2026-09-28; contract 35b, 35f).

    Behind the same blind gate as the practice review: that the machine found
    nothing for this moment, and what it spotted, would anchor the coach's own
    confidence judgment, so none of it is revealed until they have rated the
    moment. The work is services.exercise_coach_requests'.
    """
    if not _is_valid_uuid(session_id) or not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "session_id and snippet_id must be UUIDs"}), 400
    session = db.v2_get_session_by_id(session_id)
    if not session:
        return jsonify({"code": "SESSION_NOT_FOUND",
                        "error": "Session not found"}), 404
    owner_sid = _snippet_owner_map(session_id).get(snippet_id)
    if not owner_sid:
        return jsonify({"code": "SNIPPET_NOT_FOUND",
                        "error": "Snippet not in this session"}), 404
    state = _coach_state_map(owner_sid, rater_id=getattr(request, "user_id", None))
    if not _practice_door_open(state.get(str(snippet_id))):
        return jsonify({"code": "BLIND_RATING_REQUIRED",
                        "error": "Rate the original moment first."}), 409
    if not _speaker_practice_permitted(owner_sid):
        return jsonify({"code": "SPEAKER_PRACTICE_OFF",
                        "error": "The speaker turned practice off."}), 409
    from services.exercise_coach_requests import review
    status, payload = review(
        db, take_session_id=owner_sid, snippet_id=snippet_id,
        method=request.method, body=request.get_json(silent=True),
        coach_id=str(getattr(request, "user_id", "")))
    return jsonify(payload), status


def _moment_gate(session_id, snippet_id):
    """The blind gate for a coach's answer about one moment (0402): a valid
    pair of ids, a session, a snippet that belongs to it, and THIS coach's
    own rating saved first. ``(error_response, owner_sid)``; the routes for
    the draft, the queue's answers and the named errors share it, so no
    door opens before the rating (BLIND COACH)."""
    if not _is_valid_uuid(session_id) or not _is_valid_uuid(snippet_id):
        return (jsonify({"code": "INVALID_INPUT",
                         "error": "session_id and snippet_id must be UUIDs"}), 400), None
    if not db.v2_get_session_by_id(session_id):
        return (jsonify({"code": "SESSION_NOT_FOUND",
                         "error": "Session not found"}), 404), None
    owner_sid = _snippet_owner_map(session_id).get(snippet_id)
    if not owner_sid:
        return (jsonify({"code": "SNIPPET_NOT_FOUND",
                         "error": "Snippet not in this session"}), 404), None
    state = _coach_state_map(owner_sid, rater_id=getattr(request, "user_id", None))
    if not _practice_door_open(state.get(str(snippet_id))):
        return (jsonify({"code": "BLIND_RATING_REQUIRED",
                         "error": "Rate the original moment first."}), 409), None
    return None, owner_sid


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/exercise-request/draft",
    methods=["POST"],
)
@require_admin_or_coach
@operational_purpose_disabled("personalized_exercise_recommendation")
@llm_limit
@speaker_provider_route
def v2_coach_exercise_request_draft(session_id, snippet_id):
    """A first draft for the coach's answer, by the request's kind (founder
    2026-09-30, C2; P2-2): a script, a praise line or a clearer version.
    Coach-only, behind the blind gate; kept on the request row so the
    coach's final can be paired with it. The work is
    services.coach_request_drafts'."""
    error, owner_sid = _moment_gate(session_id, snippet_id)
    if error:
        return error
    if not _speaker_practice_permitted(owner_sid):
        return jsonify({"code": "SPEAKER_PRACTICE_OFF",
                        "error": "The speaker turned practice off."}), 409
    from services.coach_request_drafts import draft_for_request
    status, payload = draft_for_request(
        db, db.get_exercise_coach_request(owner_sid, snippet_id),
        request.get_json(silent=True),
        coach_id=str(getattr(request, "user_id", "")))
    return jsonify(payload), status


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/practice-judgement",
    methods=["PUT"],
)
@require_admin_or_coach
@operational_purpose_disabled("personalized_exercise_recommendation")
def v2_coach_practice_judgement(session_id, snippet_id):
    """Body {answer}: the coach's answer, one of the five, on the speaker's
    chosen practice recording (founder 2026-10-05, Q6; N45). Behind the
    blind gate; the work is services.coach_practice_judgement's."""
    error, owner_sid = _moment_gate(session_id, snippet_id)
    if error:
        return error
    if not _speaker_practice_permitted(owner_sid):
        return jsonify({"code": "SPEAKER_PRACTICE_OFF",
                        "error": "The speaker turned practice off."}), 409
    from services.coach_practice_judgement import judge_selected_attempt
    status, payload = judge_selected_attempt(
        db, take_session_id=owner_sid, snippet_id=snippet_id,
        body=request.get_json(silent=True),
        coach_id=str(getattr(request, "user_id", "")))
    return jsonify(payload), status


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/exercise-request/video",
    methods=["POST"],
)
@heavy_limit
@require_admin_or_coach
def v2_coach_exercise_request_video(session_id, snippet_id):
    """The video a coach adds to a written answer (founder 2026-09-30, A5;
    0403): a praise line, a clearer version or a note may carry one. Stored
    like an exercise video (public journal media), kept on the request row,
    and it rides `coach_answer` once the answer is shared. Behind the blind
    gate; a resolved request takes no new video.

    multipart/form-data: video_file. 200 {video_url} · 400/404/409/413/415/502
    """
    error, owner_sid = _moment_gate(session_id, snippet_id)
    if error:
        return error
    from services.coach_answer_video import store_answer_video
    status, payload = store_answer_video(
        db, request_row=db.get_exercise_coach_request(owner_sid, snippet_id),
        video_file=request.files.get("video_file"),
        max_mb=int(getattr(Config, "COACH_FEEDBACK_VIDEO_MAX_MB", 100) or 100),
        coach_id=str(getattr(request, "user_id", "")))
    return jsonify(payload), status


@v2_bp.route("/coach/sessions/<session_id>/walk-take", methods=["GET"])
@require_admin_or_coach
def v2_coach_walk_take(session_id):
    """Always 404 for a valid id: the Students screens' walk-take read stays
    off (founder 2026-10-05, N48.5 Q26 A), and its switch and body were
    deleted 2026-10-11. The route stays because the FE still calls it."""
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    return jsonify({"code": "NOT_FOUND", "error": "No such Take."}), 404


@v2_bp.route("/coach/sessions/<session_id>/word", methods=["GET", "PUT"])
@require_admin_or_coach
def v2_coach_take_word(session_id):
    """A word for this Take (founder 2026-09-30, B3; P2-5): one optional
    message and video per Take, per coach. GET this coach's own; PUT {text,
    video_ref, share} saves it and, on share, sends it to the speaker, who
    reads it as "Your coach". The video comes from the session video upload
    (POST .../video), which returns the ref; a PUT that names no video_ref
    keeps the saved video, and an explicit null removes it (founder
    2026-10-19). A GET whose read fails answers 500, never "no word" (N80:
    the panel would draft over the saved words). Nothing here gates a
    per-moment share."""
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    if not db.v2_get_session_by_id(session_id):
        return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
    from services.coach_take_word import TakeWordRefusal, save_take_word, take_word_for
    coach_id = str(getattr(request, "user_id", "") or "")
    if request.method == "GET":
        try:
            saved = take_word_for(db, take_session_id=session_id, coach_id=coach_id)
        except Exception as e:
            logger.error("take word read failed sid=%s: %s", session_id, e, exc_info=True)
            sentry_sdk.capture_exception(e)
            return jsonify({"code": "V2_ERROR", "error": "Could not read the word."}), 500
        return jsonify({"word": saved}), 200
    try:
        word = save_take_word(db, take_session_id=session_id, coach_id=coach_id,
                              body=request.get_json(silent=True))
    except TakeWordRefusal as refusal:
        return jsonify({"code": refusal.code, "error": refusal.message}), refusal.status
    except Exception as e:
        logger.error("take word save failed sid=%s: %s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Could not save the word."}), 500
    return jsonify({"word": word}), 200


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/moment",
    methods=["GET"],
)
@require_admin_or_coach
def v2_coach_moment_read(session_id, snippet_id):
    """The Read screen's one source (founder 2026-09-30, A2; P2-10): the
    passage, both answers, the request that reached the coach, the named
    patterns and the speaker's goal, all after THIS coach's own rating and
    never before (BLIND COACH). The work is services.coach_moment_read's."""
    error, owner_sid = _moment_gate(session_id, snippet_id)
    if error:
        return error
    try:
        payload = _moment_read_payload(owner_sid, snippet_id)
    except Exception as e:
        logger.error("coach moment read failed sid=%s snip=%s: %s",
                     session_id, snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to read the moment"}), 500
    return jsonify(payload), 200


def _moment_read_payload(owner_sid, snippet_id, *, session=None, snippet_row=None):
    """The Read screen's body for one moment, for THIS coach. Only ever
    called behind `_moment_gate`, which is the blind gate, or the label
    save's own form of it. ``session`` and ``snippet_row`` are the Take and
    the moment when the caller already holds them."""
    from services.coach_moment_read import moment_read
    if session is None:
        session = db.v2_get_session_by_id(owner_sid) or {}
    return moment_read(
        db, take_session_id=owner_sid, snippet_id=snippet_id,
        rater_id=str(getattr(request, "user_id", "")),
        owner_user_id=session.get("user_id"), snippet_row=snippet_row)


def _moment_read_after_rating(session_id, snippet_id, held=None) -> dict:
    """``{"moment_read": <the moment GET's body>}`` once the rating is saved,
    else ``{}`` (C2, founder 2026-10-08: "What happened" arrives with the
    saved answer instead of after a second round trip).

    THE SAME GATE AND THE SAME READ as `v2_coach_moment_read`, called after
    the confidence-label PUT has durably written this coach's rating, inside
    that request — so nothing about the moment reaches the coach before
    their answer (BLIND COACH), and an answer the gate keeps shut (Audio
    unclear) gets no read, exactly as the GET would refuse it. Any failure
    omits the key; the rating is saved either way.

    ``held`` is the save's own ``(session, snippet, rating row)`` on a
    coach's FIRST answer: the gate's reads would only find them again (the
    snippet is the Take's own row, and the rating just written is the one
    the door reads), so the door is decided on the written answer and the
    moment comes with no read of the whole talk (founder 2026-10-21, the
    save took 9 s). A reconsideration or a self-report goes through the
    gate itself."""
    try:
        if held is not None:
            sess, snip, row = held
            if not _practice_door_open({"rating_value": row.get("value"),
                                        "rating_unrateable": bool(row.get("unrateable"))}):
                return {}
            return {"moment_read": _moment_read_payload(
                str(session_id), str(snippet_id), session=sess, snippet_row=snip)}
        error, owner_sid = _moment_gate(str(session_id), str(snippet_id))
        if error:
            return {}
        return {"moment_read": _moment_read_payload(owner_sid, str(snippet_id))}
    except Exception as e:
        logger.warning("moment read after rating failed sid=%s snip=%s: %s",
                       session_id, snippet_id, e, exc_info=True)
        return {}


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/diagnosis",
    methods=["GET", "PUT"],
)
@require_admin_or_coach
def v2_coach_moment_diagnosis(session_id, snippet_id):
    """The diagnosis first (coach panel lock flow 6; Q-B7 A; Q-B12 A; D-CP-4;
    0445). GET: the errors in the lock's order, the machine-heard ones first
    and flagged, then the library's, then the coach-named ones, with THIS
    coach's current diagnosis. PUT {error_id} | {new_name} | {no_error}: one
    diagnosis per coach per moment, re-settable with the history kept. Coach
    provenance only, never a label; behind the blind gate (BLIND COACH). The
    work is services.coach_diagnosis'."""
    error, owner_sid = _moment_gate(session_id, snippet_id)
    if error:
        return error
    from services.coach_diagnosis import review
    status, payload = review(
        db, take_session_id=owner_sid, snippet_id=snippet_id,
        coach_id=str(getattr(request, "user_id", "")), method=request.method,
        body=request.get_json(silent=True) if request.method == "PUT" else None)
    return jsonify(payload), status


# The arc-level delivery (founder 2026-09-30, B3 to B6; contract 65) and its
# 410 routes are gone (deleted 2026-10-11). Their tables stay as history and
# take no new writes. What reaches the speaker now is a shared answer on its
# moment (35g-2) and the Take word (35g-6); the coach's judgement is the one
# instrument (35g-5), written by the confidence-label PUT below.


@v2_bp.route("/coach/sessions/<session_id>/video", methods=["POST"])
@heavy_limit
@require_admin_or_coach
def v2_coach_session_video(session_id):
    """④ willab coach feedback video for a session (B.3).

    REUSES the existing coach video transport/storage (services/coach_video_
    storage — same bucket + R2/Supabase path the funnel afterwards-video +
    feedback videos use; no new infra/bucket/transcoding). Stores the file,
    persists coach_video_ref on the session; the canonical readout exposes it
    in the separate take-level coach_review object. Re-upload overwrites
    (deterministic storage key).

    multipart/form-data: video_file (.mp4/.mov/.webm/.m4v).
    200 { status, session_id, video_ref } · 400/404/413/415/502
    """
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        upload = read_video_upload(
            request.files, request.content_length, video_max_mb(config))
        return jsonify(store_session_video(
            db, session_id, upload,
            (request.form.get("upload_idempotency_key") or "").strip() or None)), 200
    except Refusal as refusal:
        return jsonify(refusal.body), refusal.status
    except Exception as e:
        logger.error("coach/session-video failed sid=%s err=%s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to store coach video"}), 500


# The coach's Ideal Text edit, verify and approve (retired founder
# 2026-09-30, B2; contract 40, 64) and their 410 routes are gone: a coach
# never edits the speaker's document (L1). `coach_arc_ideal_text` stays as
# history.


def _resolve_audio_refs(rows: list, *, expires_in: int = 6 * 3600) -> None:
    """Turn every row's ``audio_ref`` into something an <audio src> can play.

    Already-absolute http(s) URLs pass through untouched (imports store a
    public URL). A bare storage key is signed for the session's length —
    long enough that a coach can work through a queue without links dying
    mid-batch. Best-effort per row: a key that cannot be signed becomes
    None (logged by the resolver), so the row shows no player instead of a
    raw ref no browser can load (founder 2026-10-08)."""
    # The bucket-authoritative branch is HOISTED (founder 2026-08-10):
    # this fix lived only here while every user surface handed the raw
    # column through — services/audio_ref_resolver.py is the one copy now.
    from services.audio_ref_resolver import resolve_playable_ref
    for r in rows or []:
        ref = r.get("audio_ref")
        resolved = resolve_playable_ref(ref, expires_in=expires_in)
        if resolved != ref:
            # None when it could not be signed: the row shows no player
            # rather than a raw ref no browser can load.
            r["audio_ref"] = resolved


@v2_bp.route("/coach/training-imports", methods=["POST"])
@whisper_limit
@require_admin_or_coach
def v2_coach_training_import():
    """Upload ONE audio file as coach-reviewable TRAINING data — analysed
    like a real take, but never a project the speaker owns (founder
    2026-07-28).

    Multipart form:
      audio_file    (required) any container ffmpeg reads (webm/mp3/m4a/wav…)
      topic         (required) what the talk is about — labels it for review
      speaker_label (optional) whose voice this is: the grouping key of the
                    80/20 split; absent, the import is a speaker of its own.
      user_id       (optional) who the corpus row belongs to; defaults to the
                    uploading coach
      note          (optional) free-text provenance (where it came from)
      language      (required since N56.4) ISO-639-1 ('pl', 'de', …): our
                    Whisper prompt is an English disfluency primer and
                    Whisper follows its prompt's language.
      stages        (optional) comma-separated ticks — the COACH-ONLY choice
                    of how much analysis to run. Default 'confidence':
                      confidence  always on — transcript, pieces, acoustics,
                                  the confidence read, the label queue. This
                                  is the corpus; Whisper is the only spend.
                      analytics   the per-piece LLM layers (stickiness,
                                  say-it-stronger, suggestion stars) — the
                                  ADVICE model's corpus, ~16 calls/file.
                      ideal_text  assembly + polish. A user deliverable;
                                  irrelevant to training.
                    A normal user's upload is never offered this and always
                    runs everything (POST /v2/lab/recordings, untouched).
      queue_per_band (optional, legacy int) review-budget unit. The mixed
                    policy targets three times this value (default 5 → 15),
                    divided across boundary, balance, and random exploration.

    ONE FILE PER REQUEST: per-file progress and failures, no job queue.
    Open since 2026-10-06 (founder, CO1 A, N56.4); its code switch was
    removed 2026-10-12 ("remove the learning doors"). Each import runs the V3
    spotting and its speaker's fixed 80/20 split. source='training_import'
    keeps it out of the speaker's project list AND their acoustic baseline
    (imports are z-scored against themselves): services/training_import.py.

    200 { ok, session_id, arc_id, snippet_count, ... }  → review at
         GET /v2/coach/arc/<arc_id>/stars
    422 { code: "AUDIO_REJECTED", reason }   the min-content gate (silence /
         corrupt / too short) — the same gate live takes pass
    400 (audio_file, topic or language missing) · 500
    """
    audio_file = request.files.get("audio_file")
    if not audio_file:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "audio_file is required"}), 400
    topic = (request.form.get("topic") or "").strip()
    if not topic:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "topic is required"}), 400
    language = (request.form.get("language") or "").strip()
    if not language:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "language is required"}), 400
    try:
        payload, status = start_training_import(
            db, audio_file, request.form,
            uploader_id=getattr(request, "user_id", None),
            topic=topic, language=language)
        return jsonify(payload), status
    except Exception as e:
        logger.error("training import failed: %s", e, exc_info=True)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not import the audio"}), 500


@v2_bp.route("/coach/training-imports/<session_id>", methods=["GET"])
@require_admin_or_coach
def v2_coach_training_import_status(session_id):
    """Poll one import's analysis. The 202 from the POST is not the outcome —
    this is.

    200 { session_id, arc_id, status: "processing"|"ready"|"failed",
          snippet_count, queue_count, error }
    404 · 500

    ``status`` mirrors v2_sessions.analysis_state; a NULL state reads as
    'ready' (pre-async rows were only ever persisted after a completed
    synchronous analysis, so NULL means finished, not unknown).
    """
    try:
        sess = db.v2_get_session_by_id(str(session_id))
        if not sess:
            return jsonify({"code": "NOT_FOUND",
                            "error": "import not found"}), 404
        state = sess.get("analysis_state") or "ready"
        ctx = sess.get("intake_context") if isinstance(
            sess.get("intake_context"), dict) else {}
        snippets = (db.get_snippets_by_session(str(session_id)) or []
                    if state == "ready" else [])
        # A failed poll returns the SAME shape as the POST's failure (FE §6):
        # reason + detail + duration_sec, so one renderer handles both. The
        # reason is recovered from analysis_error, which the import writes as
        # "REASON: detail" — split on the first colon, and degrade to the
        # whole string as the detail if it was written by something else.
        _reason = None
        _detail = None
        _err = sess.get("analysis_error")
        if state == "failed" and isinstance(_err, str) and _err.strip():
            head, sep, tail = _err.partition(":")
            if sep and head.strip().isupper() and " " not in head.strip():
                _reason, _detail = head.strip(), tail.strip()
            else:
                _detail = _err.strip()
        return jsonify({
            "session_id": session_id,
            "arc_id": sess.get("arc_id"),
            "status": state,
            "topic": ctx.get("topic") or "",
            "speaker_label": ctx.get("speaker_label"),
            "language": ctx.get("language"),
            "snippet_count": len(snippets),
            "queue_count": _stored_confidence_queue_count(ctx),
            # Present on every poll, not just the terminal one: it is what
            # separates "never decoded" from "decoded but nothing
            # transcribed", and the FE renders it on the empty-import state.
            "duration_sec": ctx.get("duration_sec"),
            "reason": _reason,
            "detail": _detail,
            "error": _err,
        }), 200
    except Exception as e:
        logger.warning("training import status failed sid=%s: %s",
                       session_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not read the import"}), 500


#: What the list's language gate reads of an undeclared import's pieces.
_IMPORT_LANGUAGE_COLUMNS = "id, session_id, start_offset_ms, language"
#: The most imports one step of the list reads (and the step without ?limit).
_IMPORT_PAGE_MAX = 200


def _import_page(args) -> tuple[int, int]:
    """``(limit, offset)`` of one step of the corpus list (N100): ?limit in
    1..200, 200 when absent or unreadable; ?offset from 0."""
    def number(name, default):
        raw = str(args.get(name) or "").strip()
        return int(raw) if raw.isdigit() else default
    return (min(max(number("limit", _IMPORT_PAGE_MAX), 1), _IMPORT_PAGE_MAX),
            number("offset", 0))


@v2_bp.route("/coach/training-imports", methods=["GET"])
@require_admin_or_coach
def v2_coach_list_training_imports():
    """The imported training takes, newest first — the coach's index into the
    corpus. Each row's `arc_id` opens the normal review surfaces
    (GET /v2/coach/arc/<arc_id>/stars, .../ideal-text).

    Carries `status` and `queue_count` per row (added 2026-07-28 with the
    async import): since the POST now returns 202 before the analysis runs,
    this list — not the upload response — is where an import's outcome
    actually shows up. Without them a finished import and a still-running one
    look identical, which is exactly how a working import reads as "0 pieces".

    `snippet_count` is deliberately NOT here: it needs one query per row, and
    a corpus list is long. Poll GET /v2/coach/training-imports/<session_id>
    for one import's piece count; `queue_count` (what the coach will actually
    label) is free and rides here. `labelled_count` IS here (FE 2026-07-30)
    because it batches: one confidence_labels query covers the whole list,
    where the FE's fallback was one queue request per row.

    Archived imports (DELETE below) are filtered out unless
    ?include_archived=1 — archive is a tidier list, never lost corpus.

    One step at a time (founder 2026-10-21, N100): ?limit (1..200, 200
    when absent) imports from ?offset (0 when absent), newest first;
    `next_offset` is where the next step starts, null after the last.

    200 { imports: [{session_id, arc_id, topic, speaker_label, created_at,
          status, queue_count, labelled_count, language,
          duration_sec, archived_at, setup_complete}], count, next_offset }
    """
    try:
        proficient = db.get_user_proficient_languages(
            str(getattr(request, "user_id", "") or ""))
        if not proficient:
            return _rater_language_error("profile_required")

        limit, offset = _import_page(request.args)
        rows = db.takes.list_training_import_sessions(
            user_id=(request.args.get("user_id") or None),
            limit=limit, offset=offset) or []
        # A full step may have more behind it; a short one is the last.
        next_offset = offset + len(rows) if len(rows) == limit else None
        include_archived = (request.args.get("include_archived") or "") in (
            "1", "true", "yes")
        # The language gate, read for the whole list at once: an import that
        # declares its language (every one since N56.4) needs no read; the
        # pieces of the others, read together, only for their languages
        # (founder 2026-10-21: one read of every piece per import made the
        # list take 15.7 s).
        from services.rater_languages import session_language
        undeclared = [r.get("id") for r in rows if not session_language(r)]
        snips = (db.get_snippets_by_sessions(
            undeclared, columns=_IMPORT_LANGUAGE_COLUMNS) or {}) if undeclared else {}
        routed = _language_matched_rows(rows, snips, proficient)
        labelled = db.count_labelled_snippets_by_session_ids(
            [r.get("id") for r in routed])
        out = []
        for r in routed:
            ctx = r.get("intake_context") if isinstance(
                r.get("intake_context"), dict) else {}
            if ctx.get("archived_at") and not include_archived:
                continue
            out.append({
                "session_id": r.get("id"),
                "arc_id": r.get("arc_id"),
                "topic": ctx.get("topic") or "",
                "speaker_label": ctx.get("speaker_label") or None,
                "created_at": r.get("created_at"),
                # NULL analysis_state reads as 'ready': pre-async rows were
                # only ever persisted after a completed synchronous analysis.
                "status": r.get("analysis_state") or "ready",
                "queue_count": _stored_confidence_queue_count(ctx),
                # DISTINCT labelled pieces, fresh from the database — the
                # honest half of the FE's badge, batched above.
                "labelled_count": labelled.get(str(r.get("id")), 0),
                # WHICH LANGUAGE THIS RUN ACTUALLY USED (FE 2026-07-29).
                # null = auto-detected, which is a real answer, not a gap:
                # a Polish talk left on auto-detect comes back TRANSLATED
                # into English — the audio is right, the words are not, and
                # nothing else on the row says so. Now that the index works
                # it outlives the browser session, so this is the surface
                # where that question gets asked.
                "language": ctx.get("language"),
                "setup_complete": setup_complete(ctx),
                "duration_sec": ctx.get("duration_sec"),
                # null on live rows; set = when it was archived. Present on
                # every row so the shape doesn't shift with the query param.
                "archived_at": ctx.get("archived_at"),
            })
        return jsonify({"imports": out, "count": len(out),
                        "next_offset": next_offset}), 200
    except Exception as e:
        logger.warning("list training imports failed: %s", e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not list imports"}), 500


@v2_bp.route("/coach/training-imports/<session_id>", methods=["DELETE"])
@require_admin_or_coach
def v2_coach_archive_training_import(session_id):
    """ARCHIVE a training import — DELETE the verb, archive the semantics.

    Deliberate (FE asked which, 2026-07-30): labelled data is training data,
    and a coach tidying a list must not be able to destroy corpus. The row
    leaves the index (unless ?include_archived=1); the pieces, the labels
    and the audio all stay. POST .../restore undoes it. Nothing here ever
    touches confidence_labels or charisma_snippets.

    The stamp rides intake_context (no migration): the index already reads
    that JSONB for every other row field.

    Guarded to source='training_import' ONLY — a coach-scope endpoint must
    not be able to hide a real user's session.

    200 {archived: true, session_id, archived_at} · 404 · 409 · 500
    """
    try:
        sess = db.v2_get_session_by_id(str(session_id))
        if not sess:
            return jsonify({"code": "NOT_FOUND",
                            "error": "import not found"}), 404
        if sess.get("source") != "training_import":
            return jsonify({"code": "NOT_AN_IMPORT",
                            "error": "not a training import"}), 409
        ctx = sess.get("intake_context") if isinstance(
            sess.get("intake_context"), dict) else {}
        stamp = datetime.now(timezone.utc).isoformat()
        ctx["archived_at"] = stamp
        if not db.takes.set_session_intake_context(str(session_id), ctx):
            return jsonify({"code": "SERVER_ERROR",
                            "error": "could not archive the import"}), 500
        return jsonify({"archived": True, "session_id": str(session_id),
                        "archived_at": stamp}), 200
    except Exception as e:
        logger.warning("archive training import failed sid=%s: %s",
                       session_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not archive the import"}), 500


@v2_bp.route("/coach/training-imports/<session_id>/erase", methods=["POST"])
@require_founder
def v2_coach_erase_training_import(session_id):
    """ERASE a training import for good: the founder only (2026-10-19).

    Unlike the archive above, nothing comes back: the audio, the moments,
    the transcript and every judgement go (services/training_import_erase).
    For audio we hold no rights to.

    200 {erased: true, session_id, deleted} · 403 · 404 · 409 · 500
    """
    from services.training_import_erase import (
        EraseRefused, erase_training_import,
    )
    if not _is_valid_uuid(str(session_id)):
        return jsonify({"code": "NOT_FOUND", "error": "import not found"}), 404
    try:
        return jsonify(erase_training_import(db, str(session_id))), 200
    except EraseRefused as refusal:
        return jsonify({"code": refusal.code,
                        "error": "could not erase the import"}), refusal.status
    except Exception as e:
        logger.error("erase training import failed sid=%s: %s",
                     session_id, e, exc_info=True)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not erase the import"}), 500


@v2_bp.route("/coach/training-imports/<session_id>/restore",
             methods=["POST"])
@require_admin_or_coach
def v2_coach_restore_training_import(session_id):
    """Undo the archive above; the row returns to the index. Idempotent —
    restoring a live import is a 200 no-op.

    200 {archived: false, session_id} · 404 · 409 · 500
    """
    try:
        sess = db.v2_get_session_by_id(str(session_id))
        if not sess:
            return jsonify({"code": "NOT_FOUND",
                            "error": "import not found"}), 404
        if sess.get("source") != "training_import":
            return jsonify({"code": "NOT_AN_IMPORT",
                            "error": "not a training import"}), 409
        ctx = sess.get("intake_context") if isinstance(
            sess.get("intake_context"), dict) else {}
        if ctx.pop("archived_at", None) is not None:
            if not db.takes.set_session_intake_context(str(session_id), ctx):
                return jsonify({
                    "code": "SERVER_ERROR",
                    "error": "could not restore the import"}), 500
        return jsonify({"archived": False,
                        "session_id": str(session_id)}), 200
    except Exception as e:
        logger.warning("restore training import failed sid=%s: %s",
                       session_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not restore the import"}), 500


@v2_bp.route("/coach/training-imports/<session_id>", methods=["PUT"])
@require_admin_or_coach
def v2_coach_training_import_setup(session_id):
    """Finish (or correct) an import's set-up without re-importing it
    (coach panel lock, training corpus CO1 A): topic, whose voice it is,
    where it came from, and the language. Body {topic, language,
    speaker_label?, source?}. An import whose set-up is not complete serves
    no moments. 200 {session_id, topic, language, speaker_label, source,
    setup_complete} · 400 · 404 · 409 NOT_AN_IMPORT · 500"""
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "session_id must be a valid UUID"}), 400
    from services.training_import_setup import apply_setup
    try:
        status, payload = apply_setup(
            db, str(session_id), request.get_json(silent=True))
        return jsonify(payload), status
    except Exception as e:
        logger.warning("training import setup failed sid=%s: %s",
                       session_id, e, exc_info=True)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not save the set-up"}), 500


def _confidence_queue_snippets_and_language_error(session_id, sess):
    snippets = db.get_snippets_by_session(str(session_id)) or []
    language_outcome, _language = _rater_language_outcome(sess, snippets)
    language_error = _rater_language_error(language_outcome)
    return snippets, language_error


def _confidence_queue_legacy_assignment(
    session_id, _canonical_evidence, _coach_id, _packet_hash, _legacy_key,
):
    return db.assign_canonical_coach_confidence_evidence(
        take_id=str(session_id),
        evidence_span_id=str(
            _canonical_evidence["evidence_span_id"]),
        coach_id=_coach_id,
        blind_packet_hash=str(_packet_hash),
        assignment_reason="legacy_blind_resume",
        idempotency_key=(
            "coach-assignment:" + _legacy_key),
    )


def _confidence_queue_legacy_record_judgment(
    _canonical_evidence, _coach_id, _legacy_value, _packet_hash, _legacy_key,
):
    from services.feedback_data_contract import TAXONOMY_VERSION
    db.record_canonical_coach_confidence_judgment(
        evidence_span_id=str(
            _canonical_evidence["evidence_span_id"]),
        coach_id=_coach_id,
        value=str(_legacy_value),
        taxonomy_version=TAXONOMY_VERSION,
        blind_packet_hash=str(_packet_hash),
        idempotency_key=_legacy_key,
    )


def _confidence_queue_canonical_backfill(session_id, r, mine):
    # CANONICAL BACKFILL-ON-RESUME. A blind legacy judgment may
    # have committed during the additive rollout before its
    # canonical evidence/label RPC was available. At this point
    # the same coach has already committed (``mine``), so copying
    # that explicit value into the immutable canonical chain does
    # not reveal or infer an answer. The key is stable and the
    # packet hash covers only the pre-judgment allowlist.
    try:
        from services.feedback_data_contract import (
            blind_packet_hash,
            content_hash,
        )

        _legacy_value = mine[0].get("value")
        if _legacy_value in (
                "yes", "in_between", "no", "not_sure",
                "audio_unclear"):
            _canonical_evidence = (
                db.ideal_text.get_canonical_confidence_evidence(
                    take_id=str(session_id),
                    snippet_id=str(r["snippet_id"]),
                )
            )
            _packet_hash = blind_packet_hash(
                _canonical_evidence)
            if _canonical_evidence and _packet_hash:
                _legacy_identity = (
                    mine[0].get("id")
                    or mine[0].get("created_at")
                    or content_hash(mine[0])
                )
                _legacy_key = (
                    "coach-confidence-legacy:"
                    f"{_legacy_identity}"
                )
                _coach_id = str(getattr(
                    request, "user_id", "") or "")
                _assignment = _confidence_queue_legacy_assignment(
                    session_id, _canonical_evidence, _coach_id,
                    _packet_hash, _legacy_key,
                )
                if _assignment is not None:
                    _confidence_queue_legacy_record_judgment(
                        _canonical_evidence, _coach_id, _legacy_value,
                        _packet_hash, _legacy_key,
                    )
    except Exception as _canonical_backfill_error:
        logger.warning(
            "canonical coach label backfill failed "
            "take=%s snippet=%s: %s",
            session_id, r.get("snippet_id"),
            _canonical_backfill_error,
        )


def _confidence_queue_row(r, *, session_id, pending_rereviews, labels):
    from services.label_quorum import (
        rater_submission_access, routing_priority,
    )
    r["re_review"] = str(r["snippet_id"]) in pending_rereviews
    snippet_labels = labels.get(str(r["snippet_id"]), [])
    mine = [lbl for lbl in snippet_labels
            if str(lbl.get("rater_id") or "")
            == str(getattr(request, "user_id", "") or "")]
    access = rater_submission_access(
        snippet_labels, getattr(request, "user_id", None))
    rereview_allowed = bool(
        r["re_review"]
        and access["outcome"] not in (
            "fresh_rater_required", "audio_quarantined",
        )
    )
    # A fresh rater sees only work the canonical ledger still needs.
    # This is what makes one unclear-audio report wait, while two
    # independent reports quarantine the artifact. A rater's own
    # saved row remains visible for honest resume/history, but an
    # unclear-audio answer is read-only for that same person.
    if not mine and not access["allowed"] and not rereview_allowed:
        return None
    r["rating_locked"] = bool(
        not access["allowed"] and not rereview_allowed)
    r["rating_lock_reason"] = (
        access["outcome"] if r["rating_locked"] else None)
    machine_value = next((
        label.get("machine_value") for label in snippet_labels
        if label.get("machine_value") in ("yes", "in_between", "no")
    ), None)
    r["_queue_priority"] = routing_priority(
        access["resolution"], machine_value)
    is_labelled = bool(mine)
    if mine:
        # `note` rides the label (FE §5): without it, a saved note
        # vanishes the moment the coach steps back to the piece,
        # which reads as data loss rather than as a display gap.
        #
        # `value`/`unrateable` are the ternary instrument (SPEC §3.2);
        # `confident`/`intensity` are kept so the current FE renders
        # unchanged through the cutover. A row written before the
        # migration has value=None, which the FE reads as "not yet
        # re-rated on the new instrument" rather than as unlabelled.
        r["label"] = {"value": mine[0].get("value"),
                      "unrateable": bool(mine[0].get("unrateable")),
                      "confident": mine[0].get("confident"),
                      "intensity": mine[0].get("intensity"),
                      "note": mine[0].get("note")}
        _confidence_queue_canonical_backfill(session_id, r, mine)
    else:
        r["label"] = None
    # D5 complete-batch blindness: this queue is always audio-only,
    # including answered rows. Transcript content is returned by the
    # reviewer-specific guidance context only after every required
    # assignment in the canonical batch has an immutable judgment.
    r["transcript"] = ""
    return r, is_labelled


def _coach_legacy_blind_learning_exposure(
    row, *, evidence, packet_hash, session_id, _project_id, _owner_id,
    _coach_id, _blind_candidates, visible_payload,
):
    from services.feedback_data_contract import TAXONOMY_VERSION
    from services.learning_exposures import (
        prepare_blind_confidence_presentation,
    )
    # An answered row is history/resume, not a new exposure.
    if row.get("label") is not None:
        return []
    return [
        prepare_blind_confidence_presentation(
            database=db,
            owner_principal_id=_owner_id,
            project_id=_project_id,
            take_id=str(session_id),
            evidence_span_id=str(
                evidence["evidence_span_id"]),
            actor_role="coach",
            actor_id=_coach_id,
            complete_candidate_set=_blind_candidates,
            selected_candidate=visible_payload,
            visible_payload=visible_payload,
            versions={
                "surface_schema":
                    "blind-confidence-exposure-v2-opaque",
                "taxonomy_version": TAXONOMY_VERSION,
                "blind_packet_hash": str(packet_hash),
            },
            delivery_mode="canary",
        )
    ]


def _coach_legacy_blind_presentation_row(
    row, *, session_id, _project_id, _owner_id, _coach_id, _blind_candidates,
):
    from services.feedback_data_contract import blind_packet_hash
    try:
        evidence = db.ideal_text.get_canonical_confidence_evidence(
            take_id=str(session_id),
            snippet_id=str(row.get("snippet_id") or ""),
        )
        packet_hash = blind_packet_hash(evidence)
        if not evidence or not packet_hash:
            return None
        assignment_key = (
            "coach-assignment:visible-queue:"
            f"{session_id}:{row['snippet_id']}:{_coach_id}"
        )
        assignment = db.assign_canonical_coach_confidence_evidence(
            take_id=str(session_id),
            evidence_span_id=str(evidence["evidence_span_id"]),
            coach_id=_coach_id,
            blind_packet_hash=str(packet_hash),
            assignment_reason="blind_confidence_visible_queue",
            idempotency_key=assignment_key,
        )
        if assignment is None:
            return None
        assignment_id = str(assignment.get("assignment_id") or "")
        if not _is_valid_uuid(assignment_id):
            return None
        visible_payload = {
            "snippet_id": str(row["snippet_id"]),
            "playback_reference_id": assignment_id,
            "re_review": bool(row.get("re_review")),
        }
        learning_exposures = _coach_legacy_blind_learning_exposure(
            row, evidence=evidence, packet_hash=packet_hash,
            session_id=session_id, _project_id=_project_id,
            _owner_id=_owner_id, _coach_id=_coach_id,
            _blind_candidates=_blind_candidates,
            visible_payload=visible_payload,
        )
        # Explicit allowlist: raw storage references, clip
        # coordinates, transcript, predictions and evidence kind
        # never cross the pre-judgment response boundary.
        return {
            "snippet_id": str(row["snippet_id"]),
            "playback_reference_id": assignment_id,
            "label": row.get("label"),
            "re_review": bool(row.get("re_review")),
            "rating_locked": bool(row.get("rating_locked")),
            "rating_lock_reason": row.get("rating_lock_reason"),
            "learning_exposures": learning_exposures,
        }
    except Exception as exposure_error:
        logger.warning(
            "blind presentation not prepared take=%s snippet=%s: %s",
            session_id, row.get("snippet_id"), exposure_error,
        )
        return None


def _pop_confidence_chain_handle(body):
    """Q2: the chain's handle the queue row carried, plus the exposure id the
    render receipt returned. Taken off the body before validation; it is not
    part of the rating."""
    if not isinstance(body, dict):
        return None
    return body.pop("mlc2", None)


def _confidence_chain_judgment(
    mlc2_handle, *, snippet_id, rater_id, value, self_report,
):
    """Q2 (2026-09-29): the same answer as the confidence chain's immutable
    blind_coach judgment, revealed in the same transaction, while the chain
    writes. Never on a self-report (the owner is not a peer) and never a
    reason to refuse the legacy save: a failed canonical write is logged and
    the readiness counters show it. Returns identifiers only, or None.

    The walk's Judge screen carries the same handle since 2026-10-05
    (N48.5 Q27 A: "the coach walk's blind labels as its judgements";
    routes/v2/confidence_chain_coach.py prepares it). Only a blind answer
    becomes the chain's blind_coach judgement: one given after this coach
    saw the clip's non-blind side is stamped not blind (35g-11) and stays
    out of the chain."""
    if mlc2_handle is None or self_report:
        return None
    from services.coach_exposure import rating_is_blind
    if not rating_is_blind(db, coach_id=str(rater_id or ""),
                           snippet_id=str(snippet_id)):
        return None
    try:
        from services.confidence_chain_consumer import (
            ConfidenceChainConsumerStore, record_coach_judgment,
        )
        assignment = (
            mlc2_handle.get("review_assignment_id")
            if isinstance(mlc2_handle, dict) else None
        )
        return record_coach_judgment(
            store=ConfidenceChainConsumerStore(db.client),
            handle=mlc2_handle,
            reviewer_principal_id=(
                _confidence_chain_reviewer_principal(rater_id) or ""),
            value=value,
            idempotency_key=(
                f"coach-card-judgment:{assignment}" if assignment else
                f"coach-card-judgment:{snippet_id}:{rater_id}"),
        )
    except Exception as chain_error:  # noqa: BLE001
        logger.warning(
            "confidence chain judgment not written snippet=%s: %s",
            snippet_id, chain_error,
        )
        sentry_sdk.capture_exception(chain_error)
        return None


def _confidence_chain_reviewer_principal(coach_user_id):
    """The coach's owner principal, looked up only while the chain writes."""
    from services.confidence_chain_consumer import consumer_enabled
    if not consumer_enabled() or not coach_user_id:
        return None
    principal = db.get_owner_principal_for_user(str(coach_user_id)) or {}
    value = str(principal.get("id") or "").strip()
    return value if _is_valid_uuid(value) else None


def _coach_legacy_blind_presentation_queue(
    visible_rows, *, session_id, _project_id, _owner_id, _coach_id,
    _blind_candidates,
):
    # Q2 (2026-09-29): while the confidence chain writes (founder_canary),
    # each unlabelled row also carries the chain's blind-packet handle, so
    # the same card's answer becomes the chain's immutable judgment. The
    # handle is four identifiers; the packet itself never leaves the server.
    from services.confidence_chain_consumer import (
        ConfidenceChainConsumerStore, attach_coach_packet, consumer_enabled,
    )
    chain_store = (
        ConfidenceChainConsumerStore(db.client) if consumer_enabled() else None
    )
    chain_reviewer = _confidence_chain_reviewer_principal(_coach_id)
    opaque_rows = []
    for row in visible_rows:
        opaque = _coach_legacy_blind_presentation_row(
            row, session_id=session_id, _project_id=_project_id,
            _owner_id=_owner_id, _coach_id=_coach_id,
            _blind_candidates=_blind_candidates,
        )
        if opaque is None:
            continue
        if chain_store is not None:
            opaque = attach_coach_packet(
                opaque, store=chain_store, take_id=str(session_id),
                snippet_id=str(row.get("snippet_id") or ""),
                reviewer_principal_id=chain_reviewer,
            )
        opaque_rows.append(opaque)
    return opaque_rows


@v2_bp.route("/coach/sessions/<session_id>/confidence-queue", methods=["GET"])
@require_admin_or_coach
def v2_coach_confidence_queue(session_id):
    """The pieces queued for confidence labelling on one take, blind.

    The queue mixes model-boundary candidates, balanced predicted regions,
    and a random exploration slice. Selection reason and probability are
    persisted for audit but discarded from this payload, which
    carries the moment (words + audio) and NOTHING that could hint at an
    answer (BLIND COACH — audio only before the answer; no transcript,
    voice_confidence, acoustic_read, or tone word). Transcript content remains
    absent even for answered rows; only the separate complete-batch reveal
    endpoint may return it. If no cohort exists, one mixed-policy cohort is
    built and persisted exactly once (any take, not just an import). A corpus
    import (switch on) has no canonical handles: its rows carry no
    playback_reference_id and play from
    GET /v2/coach/corpus/clips/<snippet_id>/playback.

    200 { session_id, queue: [{snippet_id, playback_reference_id, label}],
          count, labelled }
    404 · 500
    """
    try:
        sess = db.v2_get_session_by_id(str(session_id))
        if not sess:
            return jsonify({"code": "NOT_FOUND",
                            "error": "session not found"}), 404
        from services.confidence_labels import queue_payload
        snippets, language_error = _confidence_queue_snippets_and_language_error(
            session_id, sess)
        if language_error is not None:
            return language_error
        picked = _confidence_queue_selection(session_id, sess, snippets)

        rows = queue_payload(picked)
        pending_rereviews = {
            str(item.get("snippet_id")): item
            for item in db.list_pending_confidence_rereviews(session_id) or []
            if item.get("snippet_id")
        }
        if pending_rereviews:
            rows.sort(key=lambda item: (
                0 if str(item.get("snippet_id")) in pending_rereviews else 1,
            ))
        labels = db.get_confidence_labels_by_snippet_ids(
            [r["snippet_id"] for r in rows]) or {}
        labelled = 0
        visible_rows = []
        for r in rows:
            result = _confidence_queue_row(
                r, session_id=session_id, pending_rereviews=pending_rereviews,
                labels=labels,
            )
            if result is None:
                continue
            row, is_labelled = result
            if is_labelled:
                labelled += 1
            visible_rows.append(row)
        # Human disagreement and audio retries move ahead of ordinary unseen
        # rows. The priority is stripped before serialization: routing logic
        # must not become an answer hint on the blind screen.
        visible_rows.sort(key=lambda row: (
            0 if row.get("re_review") else 1,
            -int(row.get("_queue_priority") or 0),
        ))
        for row in visible_rows:
            row.pop("_queue_priority", None)
        visible_rows = _confidence_queue_presented(
            visible_rows, sess=sess, session_id=session_id)
        return jsonify({"session_id": session_id, "queue": visible_rows,
                        "count": len(visible_rows),
                        "labelled": labelled}), 200
    except Exception as e:
        logger.warning("confidence queue failed sid=%s: %s", session_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not load the queue"}), 500


def _confidence_queue_presented(visible_rows, *, sess, session_id):
    """The queue's rows as the coach receives them, blind.

    A corpus import, while the import switch is on, is presented from its own
    frozen cohort (services/corpus_coach_queue.py, founder 2026-10-06, CO1 A,
    N56.4): it has no owner principal, project or evidence span, and is not
    given any. Every other Take: the canonical blind presentation.
    """
    from services.corpus_coach_queue import (
        corpus_presented_rows, corpus_queue_open,
    )
    if corpus_queue_open(sess):
        return corpus_presented_rows(visible_rows)
    # Canonical blind presentations. Assignment and packet preparation are
    # idempotent and remain distinct from exposure: only the browser ACK
    # after a row paints creates the receipt. No transcript, prediction or
    # prior label enters this pre-judgment packet.
    _coach_id = str(getattr(request, "user_id", "") or "")
    _owner_id = str(sess.get("owner_principal_id") or "")
    _project_id = str(sess.get("project_id") or "")
    _blind_candidates = [{
        "candidate_key": str(row.get("snippet_id") or ""),
    } for row in visible_rows]
    # The MLC-3 inline blind assignment is retired (founder 2026-09-30,
    # L8; contract 66): _inline_authoring_for is False for every coach,
    # so the queue is the blind presentation queue or nothing.
    if (_coach_id and _owner_id and _project_id and
            not _inline_authoring_for(_coach_id)):
        return _coach_legacy_blind_presentation_queue(
            visible_rows, session_id=session_id, _project_id=_project_id,
            _owner_id=_owner_id, _coach_id=_coach_id,
            _blind_candidates=_blind_candidates,
        )
    return []


@v2_bp.route("/coach/corpus/clips/<snippet_id>/playback", methods=["GET"])
@require_admin_or_coach
def v2_coach_corpus_clip_playback(snippet_id):
    """Play one queued clip of a corpus import (founder 2026-10-06, CO1 A,
    N56.4). Replaces, for imports, the retired ``/v2/coach/mlc3/
    source-playback/<id>`` the corpus page still points at.

    Coaches and admins only, language-matched like the
    queue and the label. Only a clip in an import's frozen label queue
    plays; anything else (unknown, an ordinary Take's clip, a clip the
    cohort did not draw) is the same 404.

    200 { snippet_id, url, start_offset_ms, duration_ms, expires_in_s }
        ``url`` is a signed URL to the import's audio, valid
        ``expires_in_s`` seconds; play ``duration_ms`` from
        ``start_offset_ms``. No pick, block, policy, score or transcript.
    400 · 401 · 403 · 404 · 409/428 (language routing) · 410 · 503 · 500
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "snippet_id must be a valid UUID"}), 400
    try:
        from services.corpus_coach_queue import playback_body, queued_corpus_clip
        snip, sess = queued_corpus_clip(db, str(snippet_id))
        if snip is None:
            return jsonify({"code": "NOT_FOUND",
                            "error": "clip not found"}), 404
        outcome, language = _rater_language_outcome(sess, [snip])
        language_error = _rater_language_error(outcome, language)
        if language_error is not None:
            return language_error
        body = playback_body(snip)
        if body is None:
            return jsonify({"code": "PLAYBACK_UNAVAILABLE",
                            "error": "the clip's audio could not be signed"}), 503
        response = jsonify(body)
        response.headers["Cache-Control"] = "private, no-store, max-age=0"
        return response, 200
    except Exception as e:
        logger.warning("corpus clip playback failed snip=%s: %s", snippet_id, e,
                       exc_info=True)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not play the clip"}), 500


def _inline_authoring_for(coach_id: str) -> bool:
    """Retired with the MLC-3 service loop (founder 2026-09-30, L8; contract
    66): the corpus queue never hands out an MLC-3 inline blind assignment
    again, whatever the building switch or the coach_inline_authoring ring
    row says, because the routes such a ``blind_review`` handle pointed at
    (``/v2/coach/mlc3/...``) answer 410. Every coach keeps the blind
    presentation queue. Always False."""
    return False


@v2_bp.route("/coach/sessions/<session_id>/language", methods=["PUT"])
@require_admin_or_coach
def v2_coach_confirm_session_language(session_id):
    """Confirm routing language for a historical Take with missing metadata.

    Language is routing metadata, never a confidence judgment. Existing
    provider or coach evidence is immutable through this endpoint: an exact
    replay succeeds and a competing value fails closed.
    """
    try:
        from services.rater_languages import normalize_language, session_language

        body = request.get_json(silent=True) or {}
        language = normalize_language(body.get("language"))
        if not language:
            return jsonify({
                "code": "INVALID_LANGUAGE",
                "error": "language must be a two-letter ISO code",
            }), 422

        sess = db.v2_get_session_by_id(str(session_id))
        if not sess:
            return jsonify({"code": "NOT_FOUND", "error": "session not found"}), 404
        recording_id = str(sess.get("recording_id") or "")
        recording = db.get_recording(recording_id) if recording_id else None
        if not recording:
            return jsonify({
                "code": "RECORDING_NOT_FOUND",
                "error": "the Take has no canonical recording",
            }), 409

        current = session_language(sess, recording=recording, snippets=[])
        if current:
            if current != language:
                return jsonify({
                    "code": "CLIP_LANGUAGE_ALREADY_SET",
                    "error": "the recording already has a different verified language",
                    "language": current,
                }), 409
            return jsonify({
                "session_id": str(session_id),
                "language": current,
                "replayed": True,
            }), 200

        stored = db.set_recording_transcription_language_if_missing(
            recording_id,
            language,
        )
        if stored != language:
            if stored:
                return jsonify({
                    "code": "CLIP_LANGUAGE_ALREADY_SET",
                    "error": "the recording language changed while it was being confirmed",
                    "language": stored,
                }), 409
            return jsonify({
                "code": "LANGUAGE_CONFIRMATION_FAILED",
                "error": "the recording language could not be saved",
            }), 500

        logger.info(
            "coach confirmed historical recording language sid=%s "
            "recording_id=%s language=%s actor=%s",
            session_id,
            recording_id,
            language,
            getattr(request, "user_id", None),
        )
        return jsonify({
            "session_id": str(session_id),
            "language": language,
            "replayed": False,
        }), 200
    except Exception as error:
        logger.warning(
            "coach language confirmation failed sid=%s err=%s",
            session_id,
            error,
        )
        return jsonify({
            "code": "SERVER_ERROR",
            "error": "could not confirm the recording language",
        }), 500


def _reconcile_album_after_judgement(sess, snippet_id, session_id):
    """THE ALBUM'S COACH LEG (founder 2026-09-30, B3; contract 65): the
    walk's judgement is final when written, so the judgement write is the
    moment the exact clip is reconciled against the user's yes and the
    machine's star. The arc-level publish job that once did it is retired.
    Best-effort inside: never breaks the rating."""
    from services.voice_album import reconcile_voice_album_clip
    reconcile_voice_album_clip(
        sess.get("project_id") or sess.get("arc_id"), snippet_id,
        take_session_id=session_id, database=db)


def _rating_selection(sess, session_id, snippet_id):
    """K9 (decisions log K9; W6 2026-10-05): what put this clip in front of
    the coach, stamped on the rating server-side and never shown before it
    (services.coach_moments_queue.selection_stamp). A clip of a corpus
    labelling cohort keeps the cohort's own record; a speaker's Take, the
    walk's census of the bookmarks that reached the speaker."""
    from services.coach_moments_queue import reached_moments, selection_stamp
    from services.confidence_labels import stored_selection_records
    from services.parallel import run_in_parallel
    ctx = sess.get("intake_context") if isinstance(sess, dict) else None
    record = next((r for r in stored_selection_records(ctx)
                   if r.get("snippet_id") == str(snippet_id)), None)
    if record is not None or (sess or {}).get("source") == "training_import":
        return selection_stamp(cohort_record=record, reached_bookmark=False)
    sid = str(session_id)
    try:
        # The walk's census, its four reads side by side (founder
        # 2026-10-21, the save took 9 s): the same reach as
        # reached_for_sessions, from the same reads.
        marked, requests, events, answered = run_in_parallel(
            lambda: _bookmarked_snippet_ids(sess, sid) or set(),
            lambda: db.list_exercise_coach_requests_for_sessions([sid]),
            lambda: db.list_moment_events_for_sessions([sid]),
            lambda: db.list_confident_voice_answered_moments([sid]))
        reached = reached_moments(events, answered, (requests or {}).keys()).get(sid, set())
    except Exception as e:  # noqa: BLE001 -- the rating stands, stamped unknown
        logger.warning("rating selection read failed sid=%s: %s", session_id, e)
        return selection_stamp(reached_bookmark=None)
    return selection_stamp(
        reached_bookmark=str(snippet_id) in marked and str(snippet_id) in reached)


def _after_coach_judgement(sess, *, snippet_id, session_id, lane, self_report,
                           value, note, is_rereview):
    """What a coach's judgment of record sets off: the User Yes / Coach No
    re-review and the Album's coach leg. Never on a self-report. A plain
    reconsideration changes nothing of record, so the route skips it; a
    re-review is the one later answer the policy reads (contract 34)."""
    if lane != "coach" or self_report or not sess or not sess.get("user_id"):
        return
    # A corpus import has no speaker in the product: its user_id is the
    # importer, never the voice on the clip, and it has no owner answer and
    # no Album (L3; founder 2026-10-06, CO1 A, N56.4). Its label stays a
    # coach label and sets off nothing of an owner's.
    if sess.get("source") == "training_import":
        return
    from services.confidence_review_policy import reconcile_confidence_review
    reconcile_confidence_review(
        db, snippet_id=snippet_id, session=sess,
        owner_user_id=sess.get("user_id"), coach_value=value,
        coach_note=note, coach_write=True, is_rereview=is_rereview)
    _reconcile_album_after_judgement(sess, snippet_id, session_id)


@v2_bp.route("/coach/snippets/<snippet_id>/confidence-label", methods=["PUT"])
@require_admin_or_coach
def v2_coach_put_confidence_label(snippet_id):
    """The coach's confidence call on ONE snippet — THE core training signal.

    Five-state body (SPEC.md v3 §3.2, current):

        { state_id: "confidence",
          value: "yes" | "in_between" | "no" |
                 "not_sure" | "audio_unclear",
          note?: str, latency_ms?: int }

      value       yes / in_between / no are perceptual judgments. not_sure is
                  rater uncertainty. audio_unclear is a technical failure.
                  The three meanings remain separate in storage.

    LEGACY body { confident: bool, intensity?: 1..5, note?: str } is still
    accepted and translated (true->yes, false->no), so the current FE keeps
    working through the cutover rather than the instrument change breaking a
    live surface. `intensity` rides along when the same request carried it —
    it is the 1-5 scale Jiang & Pell's listeners used and remains the human
    side of the validation gate. A legacy body cannot express `neutral`; that
    is the whole reason the instrument changed.

    THE ORIGINAL JUDGMENT IS NEVER EDITABLE (LOCKIN §5c; contract 34; W6
    2026-10-05). A rater's first answer on a clip is their judgment of
    record in confidence_labels; a later answer by the same rater is a
    reconsideration, appended to label_revision with its own timestamp and
    provenance, and never written over the original (which every quorum,
    Album leg and measure reads). Other raters' rows are untouched, so
    multi-rater agreement stays possible. A technical ``audio_unclear``
    answer goes to a different eligible human, and the first rater cannot
    turn a second listen into a falsely independent answer. Each rating is
    stamped server-side with why the clip was in front of the rater (K9).

    LANE is derived, never sent by the client. It follows the verified rating
    act, not the clip source: this authenticated, blind, language-matched
    coach route writes ``coach`` for both rehearsal and imported-corpus clips.
    ``bootstrap`` is reserved for seeded/historical evidence whose rating
    conditions cannot be proven panel-grade.

    AC-9: nothing here is ever serialized toward a student.

    200 { saved, snippet_id, state_id, value, unrateable, lane,
          confident, intensity } · 400 · 404 · 500
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "snippet_id must be a valid UUID"}), 400
    body = request.get_json(silent=True) or {}
    request_idempotency_key = body.get("idempotency_key") if isinstance(body, dict) else None
    is_rereview = body.get("re_review") is True
    mlc2_handle = _pop_confidence_chain_handle(body)

    from services.state_ratings import resolve_lane, validate_rating

    try:
        body, legacy_intensity = rating_body(body)
    except Refusal as refusal:
        return jsonify(refusal.body), refusal.status

    try:
        snip = db.get_snippet_by_id(snippet_id)
        if not snip:
            return jsonify({"code": "NOT_FOUND", "error": "snippet not found"}), 404
        session_id = snip.get("session_id")
        sess = db.v2_get_session_by_id(str(session_id)) if session_id else None
        if not sess:
            return jsonify({"code": "NOT_FOUND",
                            "error": "session not found"}), 404
        row, err = validate_rating(body, saw_slide=_session_shows_slides(sess))
        if err:
            return jsonify({"code": "INVALID_INPUT", "error": err}), 400
        language_outcome, _language = _rater_language_outcome(sess, [snip])
        language_error = _rater_language_error(language_outcome)
        if language_error is not None:
            return language_error
        # Provenance, not clip source, defines the lane. Authentication,
        # blindness, and language matching have all been enforced above.
        lane = resolve_lane(is_coach=True, panel_grade=True)
        rater_id = getattr(request, "user_id", None)
        self_report, reconsidering = admit_rater(
            db, sess, snippet_id, rater_id, is_rereview)
        from services.label_quorum import machine_proposal
        record_rating(
            db, reconsidering,
            snippet_id=snippet_id, row=row, rater_id=rater_id,
            session_id=session_id, lane=lane, intensity=legacy_intensity,
            self_report=self_report,
            # RULE 1 — the proposal that routed this clip here, stamped
            # server-side into its own column. The coach never saw it (BLIND
            # COACH / I1); it is stored so "which prediction did this human
            # disagree with" stays answerable, and it is never a vote.
            machine_value=machine_proposal(snip),
            selection=_rating_selection(sess, session_id, snippet_id))
        value = row["value"]
        from services.coach_judgement_record import canonical_dual_write
        canonical_dual_write(
            db, session_id=session_id, snippet_id=snippet_id, rater_id=rater_id,
            value=value, request_idempotency_key=request_idempotency_key)
        # The chain's blind_coach judgment is immutable: a reconsideration
        # is never a second one.
        canonical_judgment = None if reconsidering else _confidence_chain_judgment(
            mlc2_handle, snippet_id=snippet_id, rater_id=rater_id, value=value, self_report=self_report)
        if is_rereview or not reconsidering:
            _after_coach_judgement(
                sess, snippet_id=snippet_id, session_id=session_id, lane=lane,
                self_report=self_report, value=value, note=row.get("note"),
                is_rereview=is_rereview)
        # BLINDNESS RELEASE: only after the judgment above was written.
        return jsonify({
            **rating_response(db, snip, snippet_id, row, lane,
                              legacy_intensity, canonical_judgment),
            **_moment_read_after_rating(  # C2, after the write
                session_id, snippet_id,
                held=None if reconsidering or self_report else (sess, snip, row)),
        }), 200
    except Refusal as refusal:
        return jsonify(refusal.body), refusal.status
    except Exception as e:
        logger.warning("confidence rating failed snip=%s: %s", snippet_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not save the rating"}), 500


# ── THE SPEAKING ERROR LIBRARY ────────────────────────────────────────────
#
# Naming a speaking pattern is a coach's job and must not wait for a deploy;
# DETECTING one is code and cannot happen without one. `status` is the seam
# between those two rates of change (migrations/add_speaking_error_library),
# and this pair is the coach's side of it.
#
# WHY THIS EXISTS WHEN routes/journal.py ALREADY WRITES THE SAME TABLE. That
# pair is gated on the shared JOURNAL_ADMIN_PASSWORD, which a coach does not
# have — they sign in with a coach account. A write surface the intended
# author cannot reach is not a write surface. Both call the SAME service, so
# the two refusals it owns (no `detected` claim; no demotion of an entry that
# is already detected) hold identically no matter which door was used.
#
# PROVENANCE (L3). A row here is a NAME and a DEFINITION. It is never evidence
# that the pattern occurred in any particular recording, which is why nothing
# in this pair accepts a snippet, a session, or a take. `observed_by` is
# authorship and is taken from the AUTHENTICATED caller rather than the body:
# a self-declared author is not provenance, and the body is the one part of
# this request the caller fully controls.


@v2_bp.route("/coach/catalogue", methods=["GET"])
@require_admin_or_coach
def v2_coach_list_catalogue():
    """The signed lines, every version, so an author sees what exists before
    writing the same line twice (founder 2026-09-30, E3; P1-4).
    200 { lines } · 403 · 500"""
    try:
        return jsonify({"lines": db.list_feedback_catalogue(
            active_only=False)}), 200
    except Exception as e:
        logger.error("coach/catalogue GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to read the catalogue"}), 500


@v2_bp.route("/coach/catalogue", methods=["POST"])
@require_admin_or_coach
def v2_coach_add_catalogue_line():
    """One signed line for one pattern: a new version, never an edit.
    `signed_by` is the authenticated caller (L3). The line is copy a speaker
    reads, so it is held to the same rule as every other line: words, no
    number about a person. 200 { line } · 400 · 403 · 500"""
    from services.feedback_catalogue import CatalogueRefusal, validate_line
    try:
        row = validate_line(request.get_json(silent=True) or {})
    except CatalogueRefusal as refusal:
        return jsonify({"code": refusal.code,
                        "error": refusal.message}), refusal.status
    try:
        saved = db.insert_feedback_catalogue_line(
            **row, signed_by=str(request.user_id or "") or None)
        if not isinstance(saved, dict):
            return jsonify({"code": "V2_ERROR",
                            "error": "Failed to save the line"}), 500
        return jsonify({"line": saved}), 200
    except Exception as e:
        logger.error("coach/catalogue POST failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the line"}), 500


@v2_bp.route("/coach/speaking-errors", methods=["GET"])
@require_admin_or_coach
def v2_coach_list_speaking_errors():
    """The whole library, retired entries included, so an author can see what
    already exists before naming something twice. 200 { errors } · 403 · 500"""
    try:
        return jsonify(
            {"errors": db.list_speaking_errors(active_only=False)}), 200
    except Exception as e:
        logger.error("coach/speaking-errors GET failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to read the error library"}), 500


@v2_bp.route("/coach/speaking-errors", methods=["POST"])
@require_admin_or_coach
def v2_coach_save_speaking_error():
    """Name and define one OBSERVED speaking error.

    Thin on purpose: the check-then-write lives in
    services/speaking_error_library.py, which owns both halves and both
    refusals. 200 { error } · 400 · 403 · 409 · 500
    """
    from services.speaking_error_library import (
        LibraryRefusal, save_observed_error,
    )
    body = request.get_json(silent=True) or {}
    if not isinstance(body, dict):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "body must be an object"}), 400
    try:
        saved = save_observed_error(
            db, {**body, "observed_by": str(request.user_id or "")})
    except LibraryRefusal as refusal:
        return jsonify({"code": refusal.code,
                        "error": refusal.message}), refusal.status
    except Exception as e:
        logger.error("coach/speaking-errors POST failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the error"}), 500
    if not saved:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not save the error"}), 500
    return jsonify({"error": saved}), 200
