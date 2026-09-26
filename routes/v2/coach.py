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
import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any

import sentry_sdk
from flask import jsonify, request
from werkzeug.utils import secure_filename

from config import Config
from routes.admin import is_admin, require_admin_or_coach
from routes.phase2_guard import (
    operational_purpose_disabled,
    phase2_learning_disabled,
)
from routes.v2.arcs import _spoken_takes_and_reads
from routes.v2.blueprint import v2_bp
from services.rate_limits import heavy_limit, llm_limit, whisper_limit
# Module scope on purpose: `except DeadlineExceeded` in the upload routes
# must resolve even when the failure happens BEFORE the try body reaches
# its own imports — otherwise the handler NameErrors while handling.
from routes.v2.common import (
    _COACH_PSEUDONYM_SALT,
    _is_valid_uuid,
)
from services.db import db
from services.coach_queue import load_review_queue
from services.coach_review_claim import claim_review_and_reread
from services.coach_video_storage import refreshed_media_url
from services.coach_moment_errors import (
    apply_moment_edit,
    coach_moment_fields,
    teach_on_attach,
    with_moment_errors,
)
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
    h = int(hashlib.sha256(
        (_COACH_PSEUDONYM_SALT + str(user_id)).encode("utf-8")
    ).hexdigest(), 16)
    adj = _COACH_PSEUDONYM_ADJ[(h // len(_COACH_PSEUDONYM_ANIMAL)) % len(_COACH_PSEUDONYM_ADJ)]
    animal = _COACH_PSEUDONYM_ANIMAL[h % len(_COACH_PSEUDONYM_ANIMAL)]
    return f"{adj} {animal}"


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


def _coach_state_map(session_id, rater_id=None, *, draft_rows=None):
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
    """
    drafts = _drafts_by_snippet(session_id, draft_rows)
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
    return out


def _confidence_queue_selection(session_id, session, snippets):
    """One source of truth for the blind queue and its post-label audit."""
    from services.confidence_labels import (
        mixed_label_queue, selection_records, stored_selection_records,
    )

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

    selected = mixed_label_queue(snippets, seed=str(session_id))
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


def _rater_language_outcome(session, snippets=None, proficient=None):
    """Resolve queue eligibility for the current authenticated rater.

    Language is a routing dimension only. Unknown and mismatched clips are
    withheld; they are never converted to ``not_sure`` or ``audio_unclear``.
    """
    from services.rater_languages import evaluate_rater_access, session_language

    rater_id = str(getattr(request, "user_id", "") or "")
    if proficient is None:
        proficient = db.get_user_proficient_languages(rater_id)
    language = session_language(
        session,
        recording=_session_recording(session),
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
        rows = db.takes.v2_list_user_lab_sessions(user_id) or []
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
        # Founder 2026-07-16: a mid-take RE-READ is part of its parent take —
        # never an extra row on the drill-down. Hide read rows; mark parents.
        _reread_parents = {
            str(s.get("paired_session_id")) for s in rows
            if s.get("paired_session_id")
        }
        rows = [s for s in rows
                if not (s.get("recording_kind") == "read"
                        or s.get("paired_session_id"))]
        sessions = []
        for s in rows:
            ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
            if s.get("results_published_at"):
                state = "insights_ready"
            elif s.get("status") == "pending_admin_review":
                state = "review_pending"
            else:
                state = "readout_ready"
            # Founder 2026-07-15: "saved feedback means REVIEWED." Three
            # explicit states beside the legacy `state` (additive — the FE
            # maps review_state safe-ahead): delivered (published) →
            # reviewed (coach saved the take's feedback) → to_review.
            if s.get("results_published_at"):
                review_state = "delivered"
            elif s.get("coach_feedback_saved_at"):
                review_state = "reviewed"
            else:
                review_state = "to_review"
            sessions.append({
                "session_id": s.get("id"),
                "topic": (ctx or {}).get("topic") or "",
                "created_at": s.get("created_at"),
                "state": state,
                "review_state": review_state,
                "arc_id": s.get("arc_id"),
                # nervous/excited/calm/unsure, or null if not captured.
                "feeling": _feel_by_session.get(s.get("id")),
                # This take has folded mid-take re-read(s) in its packet.
                "has_reread": str(s.get("id")) in _reread_parents,
            })
        # "Ideal text ready to review" badges (founder 2026-07-15) — the arcs
        # with a persisted MACHINE draft awaiting the coach (unapproved).
        # ONE READ FOR EVERY PROJECT, not one each. A student with a dozen
        # projects paid a dozen round trips to decide which badges to draw.
        _ideal_ready_arcs = []
        _ideal_rows = db.ideal_text.get_coach_arc_ideal_texts(
            [s.get("arc_id") for s in sessions if s.get("arc_id")]) or {}
        for _aid, _row in _ideal_rows.items():
            if _row and (_row.get("text") or "").strip() \
                    and not _row.get("approved_at"):
                _ideal_ready_arcs.append(str(_aid))
        return jsonify({
            "pseudonym": _coach_pseudonym(user_id),
            "domain": (prof or {}).get("domain") or "",
            "goal": (prof or {}).get("goal") or "",
            # Arcs whose ideal text awaits coach review/approval.
            "ideal_ready_arc_ids": _ideal_ready_arcs,
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

    Groups the user's stored pre-recording self-reports against the existing
    per-snippet delivery signal to produce the audit's "Performance under
    feeling" section. These are user-declared states, not machine-inferred
    emotions. DIRECTIONAL coaching indicators —
    `headline`s are DRAFTS the coach curates; everything is gated on a minimum
    number of takes (returns null headlines below it, never a one-take claim).

    Coach-facing assembly (the coach reviews + curates before it reaches the
    user — the audit is the human-gated deliverable).

    200 { user_id, performance_under_feeling, takes:[...] }
    """
    if not _is_valid_uuid(user_id):
        return jsonify({"code": "INVALID_INPUT", "error": "user_id must be a UUID"}), 400
    try:
        from services.feeling_performance import (
            correlate_feeling_performance, session_performance,
        )
        rows = db.takes.v2_list_user_lab_sessions(user_id) or []
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
    FIFO (oldest sent first). Each row: {session_id, user_id, pseudonym,
    domain, topic, n_snippets, state, sent_at, arc_id?, take_index?,
    has_reread?}. `user_id` is the same OPAQUE drill key the roster exposes
    (founder 2026-07-16, BE-4 — the FE groups the queue per student and opens
    the student list from it; a random UUID is not name/email, so §14
    red-line 6 still holds: pseudonym + domain remain the only DISPLAYED
    fields). Read rows are folded into their parent take (never listed);
    has_reread marks the parent."""
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
                # Opaque drill key — mirrors GET /v2/coach/students (never
                # rendered; keys the per-student grouping + drill-down).
                "user_id": str(r.get("user_id")) if r.get("user_id") else "",
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
def _bookmarked_snippet_ids(session, session_id):
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

    Returns an empty set, never None: a take with no frozen selection has no
    bookmarks to report, and treating "not selected yet" as "unknown" would
    only give the caller a third state to get wrong.
    """
    arc_id = session.get("arc_id") if isinstance(session, dict) else None
    if not arc_id or not session_id:
        return set()
    try:
        row = db.get_ideal_text_feedback_set(str(arc_id), str(session_id))
        if not row:
            return set()
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


def _shape_coach_review_packet(readout, cstate_map, session, session_id):
    """Every evidence piece of one take, each saying whether it was bookmarked.

    Its own function so the route does not grow: `v2_coach_get_session` is
    grandfathered at the route fence and may only shrink, and the bookmark
    lookup is one DB read for the whole packet rather than one per piece.
    """
    bookmarked = _bookmarked_snippet_ids(session, session_id)
    owner = _owner_confidence_answers(session)
    return [
        _shape_coach_review_snippet(
            snip, cstate_map, str(session_id),
            bookmarked_ids=bookmarked, owner_answers=owner)
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


def _claim_coach_review(session_id, session):
    """Claim the review, then re-read the session under the claim.

    Returns ``(session, None)``, or ``(None, error_response)`` when either
    step fails: a failed re-read is the same 503 as a failed claim.
    """
    try:
        return claim_review_and_reread(
            db,
            session_id,
            str(request.user_id),
            actor_is_admin=is_admin(str(request.user_id)),
            before_claim=session,
        ), None
    except Exception as assignment_error:
        low = str(assignment_error).lower()
        if "unclaimed guest" in low:
            return None, (jsonify({
                "code": "UNCLAIMED_GUEST",
                "error": "This take must be claimed before coach review.",
            }), 409)
        if "another coach" in low:
            return None, (jsonify({
                "code": "REVIEW_ASSIGNED_TO_ANOTHER_COACH",
                "error": "This review is assigned to another coach.",
            }), 409)
        logger.error(
            "coach/get-session: review assignment failed sid=%s: %s",
            session_id,
            assignment_error,
        )
        return None, (jsonify({
            "code": "REVIEW_ASSIGNMENT_FAILED",
            "error": "Could not open this review safely.",
        }), 503)


def _coach_session_readout(session_id, snippet_rows, session_row):
    """The coach's readout for one session, built from rows already in hand.

    `include_slide_scores=True` gives the coach Stickiness #2: per-snippet
    on-slide-ness plus the per-slide coverage ledger. Coach-only (AC-9).

    The caller read both of these a moment earlier — the snippets for its
    language check, the session again after the review claim — so without
    handing them in, opening one lesson paid for the same two queries twice.

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
        snippet_rows=snippet_rows, session_row=session_row)


def _fold_coach_review_reads(session_id, snippets, cstate):
    from services.lab_recording import build_readout_from_session
    read_sessions = []
    try:
        read_sessions = [
            r for r in (db.takes.get_read_sessions_for(session_id) or [])
            if isinstance(r, dict) and r.get("id")
        ]
    except Exception as _rl_err:
        logger.warning("coach/get-session: read lookup failed sid=%s: %s",
                       session_id, _rl_err)
    # One snippet read for every re-read instead of one each (founder
    # 2026-09-26). An empty or failed batch hands in None, and the readout
    # then reads for itself exactly as before.
    _read_snips: dict = {}
    if read_sessions:
        try:
            _read_snips = db.get_snippets_by_sessions(
                [str(r.get("id")) for r in read_sessions],
                include_words=True) or {}
        except Exception as _rb_err:
            logger.warning("coach/get-session: read batch failed sid=%s: %s",
                           session_id, _rb_err)
    for _r in read_sessions:
        _rid = str(_r.get("id"))
        try:
            _r_readout = build_readout_from_session(
                _rid, include_insights=False, include_slide_scores=True,
                snippet_rows=_read_snips.get(_rid))
            _r_cstate = _coach_state_map(
                _rid, rater_id=getattr(request, "user_id", None))
            _r_snips = [
                _shape_coach_review_snippet(s, _r_cstate, _rid, "read")
                for s in (_r_readout.get("snippets") or [])
            ]
        except Exception as _rf_err:
            logger.warning(
                "coach/get-session: read fold failed sid=%s read=%s: %s",
                session_id, _rid, _rf_err)
            continue
        try:
            db.takes.stamp_review_opened(_rid)
        except Exception:
            pass
        snippets.extend(_r_snips)
    return read_sessions


def _coach_arc_ideal_ready(session, _context_unlocked):
    if not (_context_unlocked and session.get("arc_id")):
        return False
    try:
        _it_row = db.ideal_text.get_coach_arc_ideal_text(session.get("arc_id"))
        return bool(
            _it_row and (_it_row.get("text") or "").strip()
            and not _it_row.get("approved_at"))
    except Exception:
        return False


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


def _coach_review_state(session):
    if session.get("results_published_at"):
        return "delivered"
    if session.get("coach_feedback_saved_at"):
        return "reviewed"
    return "to_review"


def _coach_get_session_identity_fields(
    *, session_id, session, cstate, ctx, _context_unlocked, _blind_progress,
    _arc_ideal_ready, _review_state,
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
        "review_state": _review_state,
        "arc_id": session.get("arc_id"),
        "arc_ideal_ready": _arc_ideal_ready if _context_unlocked else False,
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
    *, session_id, session, readout, ctx, _context_unlocked, _served_snippets,
):
    from services.feelings import shape_coach_feelings
    return {
        "overall_message": (
            session.get("coach_overall_message") or ""
            if _context_unlocked else ""),
        "video_ref": (refreshed_media_url(session.get("coach_video_ref") or None)
                      if _context_unlocked else None),
        # Slide-deck context (UX Wave 4 BE-S6a) — coach sees the deck while
        # reviewing; per-snippet slide mapping is Phase 2.
        #
        # `slides` — the WHOLE deck, for the slide-correction control. Stays
        # behind the context gate: correcting a mapping is authoring, not
        # rating, and a blind rater has no business paging the deck.
        "slides": ((ctx or {}).get("slides") or [])
        if _context_unlocked else [],
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
        "presentation_ref": refreshed_media_url(
            (ctx or {}).get("presentation_ref") or None),
        # Per-slide coverage ledger (Stickiness #2 (i)) — coach audit.
        "slide_coverage": (readout.get("slide_coverage") or [])
        if _context_unlocked else [],
        "snippets": _served_snippets,
        # U10 — the pre-recording feeling(s) the student named (nervous/
        # excited/calm/unsure), shown at the END of the snippets. Coach-only
        # (split-sink/AC-9, never user-facing); the felt-state input the
        # coach factors into the audit's "Performance under feeling".
        "feelings": (
            shape_coach_feelings(db.get_feelings_by_session(session_id))
            if _context_unlocked else []),
    }


def _coach_get_session_response(
    *, session_id, session, cstate, readout, ctx, _context_unlocked,
    _blind_progress, _served_snippets, read_sessions, _arc_ideal_ready,
    _review_state,
):
    return {
        **_coach_get_session_identity_fields(
            session_id=session_id, session=session, cstate=cstate, ctx=ctx,
            _context_unlocked=_context_unlocked, _blind_progress=_blind_progress,
            _arc_ideal_ready=_arc_ideal_ready, _review_state=_review_state,
        ),
        **_coach_get_session_reads_fields(read_sessions, _context_unlocked),
        **_coach_get_session_media_fields(
            session_id=session_id, session=session, readout=readout, ctx=ctx,
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
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        snippets_for_language = db.get_snippets_by_session(session_id) or []
        language_outcome, _language = _rater_language_outcome(
            session, snippets_for_language)
        language_error = _rater_language_error(language_outcome, _language)
        if language_error is not None:
            return language_error

        # First open atomically owns the review.  Admins may inspect another
        # coach's assignment, but publishing then requires an audited override.
        session, claim_error = _claim_coach_review(session_id, session)
        if claim_error is not None:
            return claim_error

        readout = _coach_session_readout(
            session_id, snippets_for_language, session)
        cstate = _coach_state_map(
            session_id, rater_id=getattr(request, "user_id", None))

        snippets = _shape_coach_review_packet(
            readout, cstate, session, session_id)
        # Fold the paired mid-take RE-READS into this take's packet (founder
        # 2026-07-16: "re-reads are part of the take, revealed by clicking
        # next, never separate items"). Appended AFTER the parent's pieces —
        # NEVER sorted across sessions by start_offset_ms (the read's clock
        # restarts at 0). Best-effort: a fold hiccup degrades to the parent
        # take alone (LIVE LOOP).
        read_sessions = _fold_coach_review_reads(session_id, snippets, cstate)
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
        _context_unlocked = bool(_blind_progress["complete"])
        _served_snippets = (
            snippets if _context_unlocked
            else redact_contextual_snippets(snippets)
        )

        ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
        # "Ideal text ready to review" (founder 2026-07-15) — a persisted,
        # unapproved machine draft exists for this session's arc.
        _arc_ideal_ready = _coach_arc_ideal_ready(session, _context_unlocked)
        # Founder 2026-07-15: saved = REVIEWED (three explicit states beside
        # the legacy `state`; additive, FE maps safe-ahead).
        _review_state = _coach_review_state(session)
        return jsonify(_coach_get_session_response(
            session_id=session_id, session=session, cstate=cstate,
            readout=readout, ctx=ctx, _context_unlocked=_context_unlocked,
            _blind_progress=_blind_progress, _served_snippets=_served_snippets,
            read_sessions=read_sessions, _arc_ideal_ready=_arc_ideal_ready,
            _review_state=_review_state,
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


def _save_coach_snippet_lanes(session_id, snippet_id, body):
    """SHARED two-lane persist for one snippet's coach authoring — used by
    BOTH the per-snippet immediate-save route AND the publish route's inline
    ``snippets[]`` batch (founder 2026-07-13: the FE saves everything at
    Publish instead of per keystroke). One implementation so the two doors
    physically cannot drift (same validators, same caps, same stores).

    Runs inside a request context (reads ``request.user_id``). Returns None
    on success, or a ``(flask_response, status)`` tuple to return directly.
    Persists note/tag/surfaced/when/examples/transcript_corrected to the
    user-facing coach draft. Blind confidence ratings use their own endpoint.
    """
    from services.feedback_repository import LEGACY_COACH_TAGS

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
        if tag is not None and tag not in LEGACY_COACH_TAGS:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": (
                    "tag: must be one of "
                    f"{', '.join(LEGACY_COACH_TAGS)}"
                ),
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
    # Coach-corrected transcript (founder 2026-07-06) — a real coach-
    # authored artifact, distinct from `note`. Free tier the instant it's
    # saved + surfaced (no payment check anywhere in this path).
    if "transcript_corrected" in body:
        tx_raw = body.get("transcript_corrected")
        if tx_raw is not None and not isinstance(tx_raw, str):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "transcript_corrected: must be a string",
            }), 422
        tx = (tx_raw or "").strip()
        if len(tx) > 4000:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "transcript_corrected: 4000 chars max",
            }), 422
        draft_fields["transcript_corrected"] = tx or None

    if draft_fields:
        db.upsert_coach_snippet_draft(
            session_id, snippet_id, draft_fields,
            updated_by=str(request.user_id),
        )
    return None


def _speaker_practice_permitted(take_session_id: str) -> bool:
    """Whether the speaker behind this Take allows practice (E3).

    A coach may not send an exercise to someone who turned practice off, or
    never turned it on: choosing one for them is the practice purpose, not
    coach review. Asked of the one boundary that decides it, about the
    SPEAKER, never the coach making the request.
    """
    from services.processing_authorization import (
        PERSONALISED_PRACTICE,
        ProcessingAuthorizationService,
    )
    service = ProcessingAuthorizationService(db)
    try:
        principal = service.take_acquisition_principal(str(take_session_id))
    except Exception:
        return not service.enforced
    return service.choice_permitted(principal, PERSONALISED_PRACTICE)


def _requested_video_url(body: dict) -> tuple[Any, Any]:
    """The coach's explanation video address, or the reason it is refused.

    Returns ``(url_or_None, None)`` or ``(None, message)``. Moved out of the
    practice route unchanged, so the route stays inside its frozen size.
    """
    requested = body.get("explanation_video_url")
    if requested is None:
        return None, None
    if not isinstance(requested, str):
        return None, "explanation_video_url must be a URL."
    requested = requested.strip()
    if requested and not re.match(r"^https?://[^\s]+$", requested,
                                  re.IGNORECASE):
        return None, "explanation_video_url must use http or https."
    return requested, None


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
    # Hard blind gate: the current coach must first commit a definite rating.
    state = _coach_state_map(owner_sid, rater_id=getattr(request, "user_id", None))
    coach_state = state.get(str(snippet_id)) or {}
    if coach_state.get("rating_value") not in ("yes", "no"):
        return jsonify({"code": "BLIND_RATING_REQUIRED",
                        "error": "Rate the original moment before reviewing practice."}), 409
    if not _speaker_practice_permitted(owner_sid):  # E3, founder 2026-09-25
        return jsonify({"code": "SPEAKER_PRACTICE_OFF",
                        "error": "The speaker turned practice off."}), 409
    practice = db.get_confident_voice_practice_by_take(owner_sid)
    if not practice or str(practice.get("snippet_id")) != str(snippet_id):
        return jsonify({"code": "NOT_FOUND",
                        "error": "practice not found"}), 404
    if request.method == "GET":
        return jsonify({"practice": _coach_practice_payload(practice)}), 200
    if request.method == "PATCH":
        return _coach_moment_edit(practice)

    body = request.get_json(silent=True) or {}
    decision = body.get("professional_coach_decision")
    if decision not in ("yes", "no", "refine"):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "professional_coach_decision is required"}), 400
    selected_attempt_id = str(practice.get("selected_attempt_id") or "")
    selected_attempt_decision = body.get("selected_attempt_coach_decision")
    if selected_attempt_id and selected_attempt_decision not in ("yes", "no"):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "Judge the selected practice recording itself.",
        }), 400
    custom_body = body.get("custom_exercise")
    custom_exercise = None
    exercise_id = None
    if custom_body is not None:
        # FILED INTO THE LIBRARY, not minted here (founder 2026-09-25). It has
        # to name the error it treats, or it can never reach anyone: routing
        # matches an exercise's errors against the errors a detector actually
        # found on a clip. Filing it also keeps a coach's judgement about one
        # recording from riding along onto that speaker's later practice (L3).
        from services.diagnostic_exercise_catalogue import (
            CatalogueRefusal,
            file_coach_exercise,
        )
        custom_body = with_moment_errors(custom_body, practice, db)
        try:
            exercise = file_coach_exercise(
                db, practice_id=practice.get("id"), fields=custom_body)
        except CatalogueRefusal as refusal:
            return jsonify({"code": refusal.code,
                            "error": refusal.message}), refusal.status
        if not exercise:
            return jsonify({"code": "EXERCISE_UNAVAILABLE",
                            "error": "The exercise could not be saved."}), 503
        custom_exercise = exercise
        exercise_id = str(exercise.get("exercise_id") or "")
    else:
        exercise_id = str(body.get("exercise_id") or practice.get("exercise_id"))
        exercise = db.get_active_diagnostic_exercise(exercise_id)
        if not exercise:
            return jsonify({"code": "EXERCISE_UNAVAILABLE",
                            "error": "Select an active reviewed exercise."}), 409
    requested_video_url, invalid_video = _requested_video_url(body)
    if invalid_video:
        return jsonify({"code": "INVALID_INPUT", "error": invalid_video}), 400
    final_video_url = (
        requested_video_url
        or exercise.get("explanation_video_url")
        or exercise.get("explanation_video_ref")
    )
    share = body.get("share_with_user") is True
    if share and not final_video_url:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "Add an explanation video before sharing."}), 400
    exercise_snapshot = {
        "exercise_id": exercise.get("exercise_id"),
        "version": int(exercise.get("version") or 1),
        "title": exercise.get("title"),
        "instruction": exercise.get("instruction"),
        "explanation_video_url": final_video_url,
        "source": exercise.get("source") or "diagnostic_library",
    }
    patch = {
        "professional_coach_decision": decision,
        "coach_selected_exercise_id": exercise_id,
        "coach_custom_exercise": custom_exercise,
        "coach_explanation_video_url": final_video_url,
    }
    if share:
        patch.update({
            "coach_shared_exercise": exercise_snapshot,
            "coach_shared_by": str(request.user_id),
            "coach_shared_at": datetime.now(timezone.utc).isoformat(),
        })
    if selected_attempt_id:
        selected_attempt = db.set_confident_voice_practice_attempt_coach_decision(
            str(practice.get("id")), selected_attempt_id,
            str(selected_attempt_decision), str(request.user_id))
        if not selected_attempt:
            return jsonify({
                "code": "V2_ERROR",
                "error": "Could not save the selected recording judgment.",
            }), 500
    updated = db.update_confident_voice_practice(
        str(practice.get("id")), None, patch)
    if not updated:
        return jsonify({"code": "V2_ERROR",
                        "error": "Could not save the coach decision."}), 500
    if selected_attempt_id:
        from services.confident_voice_practice import (
            reconcile_practice_voice_album,
        )
        admitted = reconcile_practice_voice_album(updated, database=db)
        if admitted:
            from services.arc_notifications import fire_voice_album_ready
            fire_voice_album_ready(
                db, practice.get("owner_user_id"), practice.get("project_id"))
    if share and custom_exercise is None:  # "Attach = both" (founder 09-25)
        teach_on_attach(db, practice, exercise_id, str(request.user_id))
    if share:
        from services.arc_notifications import fire_confidence_practice_shared
        emitted = fire_confidence_practice_shared(
            db, practice.get("owner_user_id"), practice.get("project_id"),
            practice.get("id"))
        if emitted:
            db.update_confident_voice_practice(
                str(practice.get("id")), None,
                {"chat_emitted_at": datetime.now(timezone.utc).isoformat()})
    return jsonify({"practice": _coach_practice_payload(updated)}), 200


@v2_bp.route("/coach/sessions/<session_id>/snippets/<snippet_id>", methods=["POST"])
@require_admin_or_coach
def v2_coach_save_snippet(session_id, snippet_id):
    """③ willab coach per-snippet immediate save (E1 / §B.3 / S.5).

    Persists ONE snippet's coach authoring immediately, so reopening the
    overlay resumes where the coach left off (no all-in-memory-until-publish
    loss). Partial saves are first-class — send only the fields that changed.

    Body (any subset)::
        { "note"?:    "..."        // empty/whitespace -> cleared
          "tag"?:     "strong"|"to_work_on"
          "surfaced"?: bool         // does this snippet reach the user?
          "transcript_corrected"?: "..."  // FREE tier the instant it's saved (2026-07-06)
          "when"?:    "...", "examples"?: ["..."] }       // optional PR-2 fields

    note/tag/surfaced/when/examples are assembled into the user-facing payload
    at publish. Blind confidence ratings use their own state-rating endpoint.

    Idempotent on (session_id, snippet_id). NO publish-floor validation here
    (drafts are partial; the floor is enforced at publish). Coach-facing only:
    the response echoes the coach's own input — no salience/control score, no
    real identity, never serialized to the user.

    200 { coach_state }
    400 INVALID_INPUT · 404 SESSION_NOT_FOUND / SNIPPET_NOT_FOUND · 422 invalid value
    """
    if not _is_valid_uuid(session_id) or not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT", "error": "session_id and snippet_id must be UUIDs",
        }), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        # Snippet must belong to THIS session OR one of its folded mid-take
        # re-reads (founder 2026-07-16 — the coach edits the MERGED packet
        # under the spoken take's path). The write ROUTES to the snippet's
        # OWNING session so every downstream reader (key moments, labels
        # export, learning loop) — all keyed by the read's own session id —
        # sees it.
        _owner_sid = _snippet_owner_map(session_id).get(snippet_id)
        if not _owner_sid:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND", "error": "Snippet not in this session",
            }), 404

        body = request.get_json(silent=True) or {}

        # SHARED two-lane persist (also the publish route's inline snippets[]
        # path) — one implementation so the two doors cannot drift.
        _lane_err = _save_coach_snippet_lanes(_owner_sid, snippet_id, body)
        if _lane_err is not None:
            return _lane_err

        # Echo the persisted coach_state (BOTH lanes folded) — the FE writes
        # this back into its local state, so it must reflect what's stored.
        return jsonify({
            "coach_state": _coach_state_for(_owner_sid, snippet_id),
        }), 200
    except Exception as e:
        logger.error(
            "coach/save-snippet failed sid=%s snip=%s err=%s",
            session_id, snippet_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save snippet"}), 500


@v2_bp.route("/coach/sessions/<session_id>/recut", methods=["POST"])
@heavy_limit
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
        # any coach drafts already on this session would be orphaned. Refuse
        # unless ?force=true so the discard is explicit.
        _force = (request.args.get("force") or "").strip().lower() in ("1", "true", "yes")
        _drafts = db.get_coach_snippet_drafts(session_id) or []
        if _drafts and not _force:
            return jsonify({
                "code": "RECUT_WOULD_DISCARD_COACH_WORK",
                "error": (
                    "Re-cut mints new snippets and would discard the coach "
                    "notes already on this session. Re-send with "
                    "?force=true to re-cut and discard them."
                ),
                "drafts": len(_drafts),
            }), 409
        recording_id = session.get("recording_id")
        if not recording_id:
            return jsonify({"code": "NO_RECORDING", "error": "Session has no recording."}), 404
        rec = db.get_recording(recording_id)
        if not rec:
            return jsonify({"code": "NO_RECORDING", "error": "Recording not found."}), 404
        storage_path = rec.get("storage_path")
        parent_url = rec.get("audio_url") or storage_path
        if not storage_path:
            return jsonify({"code": "NO_AUDIO", "error": "Recording has no stored audio."}), 422

        from services.processing_authorization import ProcessingAuthorizationService
        authorization = ProcessingAuthorizationService(db)
        try:
            if authorization.enforced:
                from services.authorized_provider import (
                    AuthorizedProviderAdapter,
                    ProviderCoordinates,
                )
                attempt_result = (
                    db.client.table("processing_recording_attempts")
                    .select("id,acquisition_principal_id")
                    .eq("recording_id", str(recording_id)).limit(1).execute()
                )
                attempt = (attempt_result.data or [None])[0]
                if not isinstance(attempt, dict):
                    raise RuntimeError("AUTHORIZED_AUDIO_LINEAGE_MISSING")
                object_result = (
                    db.client.table("processing_audio_objects")
                    .select("storage_provider,bucket,object_key")
                    .eq("recording_attempt_id", str(attempt["id"]))
                    .limit(1).execute()
                )
                audio_object = (object_result.data or [None])[0]
                if not isinstance(audio_object, dict):
                    raise RuntimeError("AUTHORIZED_AUDIO_OBJECT_MISSING")
                principal_id = str(attempt["acquisition_principal_id"])
                authorization.require_current(principal_id, operation="coach_recut")
                adapter = AuthorizedProviderAdapter(
                    db,
                    ProviderCoordinates(principal_id, session_id, str(recording_id)),
                    authorization=authorization,
                )
                audio_bytes = adapter.download_audio(
                    storage_provider=str(audio_object["storage_provider"]),
                    bucket=str(audio_object["bucket"]),
                    object_key=str(audio_object["object_key"]),
                    idempotency_key=f"coach-recut-download:{session_id}:{uuid.uuid4()}",
                )
            else:
                # Compatibility before the reviewed Phase‑1 policy is active.
                from services.lab_audio_storage import get_lab_audio_bytes
                audio_bytes = get_lab_audio_bytes(storage_path)
        except Exception as fe:
            from services.processing_authorization import ProcessingAuthorizationError
            if isinstance(fe, ProcessingAuthorizationError):
                return jsonify({"code": fe.code, "error": fe.message}), fe.status
            logger.error("recut: audio fetch failed sid=%s err=%s", session_id, fe)
            return jsonify({"code": "AUDIO_FETCH_FAILED", "error": "Could not load stored audio."}), 502
        if not audio_bytes:
            return jsonify({"code": "NO_AUDIO", "error": "Stored audio is empty."}), 422

        # Replace the existing auto-cut snippets, then re-run the segmenter.
        # On a forced re-cut, also clear the now-orphaned coach drafts.
        if _force and _drafts:
            db.delete_coach_snippet_drafts_for_session(session_id)
            logger.info(
                "recut: force-discarded coach work sid=%s drafts=%d",
                session_id, len(_drafts),
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
            # Preserve the session's spoken/read kind across a re-cut.
            recording_kind=(session.get("recording_kind") or "spoken"),
            # …and its parent take, so a re-cut re-read keeps the acoustic
            # reference that makes its needle honest (2026-07-17).
            paired_session_id=session.get("paired_session_id"),
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
    # Local import on purpose: binds at CALL time, so tests that monkeypatch
    # services.coach_video_storage attributes take effect.
    from services.coach_video_storage import put_coach_object_bytes

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

        # Subsystem V — idempotency (retry dedupe). A re-upload of the SAME
        # record action (same key) reuses the stored take instead of creating a
        # phantom one. Best-effort: a missing table just falls through.
        _idem = (request.form.get("upload_idempotency_key") or "").strip() or None
        if _idem:
            _existing = db.get_coach_video_asset_by_idempotency_key(_idem)
            if _existing and _existing.get("video_ref"):
                db.takes.set_session_coach_video_ref(session_id, _existing["video_ref"])
                return jsonify({
                    "status": "ok", "session_id": session_id,
                    "video_ref": refreshed_media_url(_existing["video_ref"]), "deduped": True,
                }), 200

        bucket = getattr(config, "COACH_FEEDBACK_VIDEO_BUCKET", "coach_feedback_videos")
        # Subsystem V — NON-deterministic key so a re-record does NOT overwrite
        # the prior take (which is training/preference data). The user-facing ref
        # is repointed to the newest take below.
        storage_key = f"coach-feedback/{session_id}/{uuid.uuid4().hex}{ext}"
        try:
            put_coach_object_bytes(
                bucket, storage_key, video_bytes,
                video_file.content_type or "video/mp4",
            )
        except Exception as upload_err:
            logger.error("coach video upload failed sid=%s err=%s", session_id, upload_err)
            return jsonify({"code": "UPLOAD_FAILED", "error": "Failed to upload video to storage."}), 502

        video_ref = f"s3://{bucket}/{storage_key}"  # private bucket: signed on read
        db.takes.set_session_coach_video_ref(session_id, video_ref)
        logger.info("coach video stored sid=%s key=%s", session_id, storage_key)

        # Phase 1 stores the coach's product video only.  The former
        # best-effort corpus capture was a hidden pooled-learning write and is
        # deliberately absent until a separately approved Phase-2 cutover.

        return jsonify({
            "status": "ok", "session_id": session_id,
            "video_ref": refreshed_media_url(video_ref),
        }), 200
    except Exception as e:
        logger.error("coach/session-video failed sid=%s err=%s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to store coach video"}), 500


@v2_bp.route("/coach/arc/<arc_id>/best-presentation", methods=["GET"])
@require_admin_or_coach
def v2_coach_arc_best_presentation(arc_id):
    """The coach's own preview of the auto-assembled draft + their own
    corrections so far. Ungated by ownership/payment — coach-only auth is the
    gate. Response shape matches the student route, plus always-populated
    `text` regardless of coach_finalized.
    """
    try:
        from services.slide_selection import build_best_presentation
        return jsonify({
            "arc_id": arc_id,
            **build_best_presentation(arc_id, coach_view=True),
        }), 200
    except Exception as e:
        logger.error("coach/arc best-presentation failed arc=%s: %s", arc_id,
                     e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load best presentation",
        }), 500


# ── willab — coach-owned ideal-text correction (founder 2026-07-06) ─────
#
# The coach's OWN editing surface: always shows the CURRENT draft (auto, or
# the coach's own correction where saved), regardless of coach_finalized —
# the coach needs to see their own in-progress work. Never gated by payment
# (constraint: the coach always reviews every take/arc, independent of the
# student's payment state).


# (The #186 batch card + per-slide coach ideal-text editing lived here —
#  DELETED 2026-07-15 after the FE switched to /coach/arc/<id>/publish-analysis,
#  /explore/arc/<id>/feedback and the one-block ideal-text routes. History: PR #186/#193.)


@v2_bp.route("/coach/arc/<arc_id>/ideal-text", methods=["GET"])
@require_admin_or_coach
def v2_coach_get_ideal_text(arc_id):
    """The coach's review copy of the ONE-BLOCK ideal text. Since 2026-07-15
    the draft is assembled EAGERLY when the arc's 3rd spoken take lands (see
    maybe_assemble_ideal_text) — this GET normally serves the PERSISTED block
    instantly. The lazy compute stays as the cold fallback so the panel is
    never dead.

    ``assembly_state`` + spoken take counts make the panel observable:
      "pending" — fewer than 3 spoken takes (show "N of 3 takes recorded");
      "ready"   — a block is served (persisted machine draft, coach edit, or
                  the lazy-computed fallback);
      "empty"   — 3 takes in, but the assembler has nothing to select yet
                  (no coach-confirmed picks). NEVER served as "ready" with an
                  empty block: that renders as a dead panel (2026-07-17).

    200 { arc_id, text, key_moments, approved, ready,
          source: "coach"|"machine"|"auto",
          assembly_state, takes_done, takes_target }
    """
    try:
        from services.ideal_text_block import (
            assemble_ideal_text_block, extract_key_moments,
            maybe_assemble_ideal_text,
        )
        from services.slide_selection import (
            TAKES_TARGET, spoken_arc_sessions,
        )
        _arc_sessions = db.takes.get_arc_sessions(arc_id)
        _spoken_n = len(spoken_arc_sessions(_arc_sessions))
        _counts = {"takes_done": min(_spoken_n, TAKES_TARGET),
                   "takes_target": TAKES_TARGET}
        # The STUDENT's own edit, read-only reference for the coach (BE-3):
        # {text, version, updated_at} | null. Separate lane — the coach
        # reconciles it by hand; it never overwrites the coach text (L1).
        _owner = next(
            (s.get("user_id") for s in (_arc_sessions or [])
             if s.get("user_id")), None)
        _user_edit = db.get_user_ideal_edit(arc_id, _owner) if _owner else None

        row = db.ideal_text.get_coach_arc_ideal_text(arc_id)
        if row and (row.get("text") or "").strip():
            text = row["text"]
            return jsonify({
                "arc_id": arc_id, "text": text,
                "key_moments": extract_key_moments(text),
                "approved": bool(row.get("approved_at")),
                "ready": True,
                # coach = a human edited/owns it; machine = the eager draft
                "source": ("coach" if row.get("updated_by") else "machine"),
                "assembly_state": "ready",
                "user_edit": _user_edit,
                **_counts,
            }), 200

        # No persisted block. <3 spoken takes → honest pending (the FE shows
        # the count); ≥3 → the eager job hasn't landed (older arc / hiccup):
        # assemble NOW, persist for next time, serve it.
        if _spoken_n < TAKES_TARGET:
            return jsonify({
                "arc_id": arc_id, "text": "",
                "key_moments": [], "approved": False, "ready": False,
                "source": "auto", "assembly_state": "pending",
                "user_edit": _user_edit,
                **_counts,
            }), 200
        maybe_assemble_ideal_text(arc_id)  # persist for the next open
        auto = assemble_ideal_text_block(arc_id)
        _auto_text = (auto.get("text") or "").strip()
        # 3 takes in but the assembler produced NOTHING (no coach-confirmed
        # picks to select from yet) is a real, distinct state — serving it as
        # "ready" hands the panel an empty block and reads to the coach as a
        # dead screen. Say so honestly (founder 2026-07-17).
        if not _auto_text:
            logger.info(
                "ideal-text: %d spoken takes but the assembler produced no "
                "block arc=%s (no coach-confirmed picks yet?)",
                _spoken_n, arc_id)
        return jsonify({
            "arc_id": arc_id, "text": _auto_text,
            "key_moments": auto.get("key_moments") or [],
            "approved": False,
            "ready": bool(_auto_text),
            "source": "auto",
            "assembly_state": ("ready" if _auto_text else "empty"),
            "user_edit": _user_edit,
            **_counts,
        }), 200
    except Exception as e:
        logger.error("coach ideal-text GET failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load ideal text",
        }), 500


@v2_bp.route("/coach/arc/<arc_id>/ideal-text", methods=["PUT"])
@require_admin_or_coach
def v2_coach_put_ideal_text(arc_id):
    """Save the coach's one-block edit (markers travel with the text; raw
    HTML stripped; ≤20000 chars). Body: {text}. 200 {ok} · 400 · 500"""
    try:
        body = request.get_json(silent=True) or {}
        text = body.get("text")
        if not isinstance(text, str) or not text.strip():
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text is required"}), 400
        text = re.sub(r"<[^>]*>", "", text).strip()
        if len(text) > 20000:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "text too long"}), 400
        ok = db.ideal_text.upsert_coach_arc_ideal_text(
            arc_id, text, str(request.user_id))
        if not ok:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        from services.ideal_text_core_snapshot import publish_for_arc
        publish_for_arc(db, str(arc_id))
        return jsonify({"ok": True, "arc_id": arc_id}), 200
    except Exception as e:
        logger.error("coach ideal-text PUT failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500


@v2_bp.route("/coach/arc/<arc_id>/verify", methods=["POST"])
@heavy_limit
@require_admin_or_coach
def v2_coach_verify_ideal_text(arc_id):
    """VERIFY — the coach's ONE action under the single deliverable (founder
    re-shape 2026-07-17; replaces approve + publish). Marks the CURRENT
    ideal-text version verified (who/when stamped, the served text
    snapshotted), and fires the per-version "verified" bubble to the owner.
    The student GET then serves the verified text FREE — no payment gate on
    the text, ever. A new take afterwards bumps the version → status resets
    to unverified and the loop continues. Idempotent per version.

    200 { verified: true, arc_id, version }
    200 { already_verified: true, arc_id, version }
    409 NOTHING_TO_VERIFY · 404 · 500
    """
    try:
        sessions = db.takes.get_arc_sessions(arc_id)
        if not sessions:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        outcome = db.verify_ideal_text(arc_id, str(request.user_id))
        if outcome is None:
            return jsonify({
                "code": "NOTHING_TO_VERIFY",
                "error": "No ideal-text version to verify yet.",
            }), 409
        row = db.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
        version = row.get("version") or 1
        if outcome == "already":
            from services.ideal_text_core_snapshot import publish_for_arc
            publish_for_arc(db, str(arc_id))
            return jsonify({"already_verified": True, "arc_id": arc_id,
                            "version": version}), 200
        owner = next(
            (s.get("user_id") for s in sessions if s.get("user_id")), None)
        if owner:
            from services.arc_notifications import fire_ideal_verified
            fire_ideal_verified(db, owner, arc_id, version)

        # ── Learning-pipeline item 3 (founder 2026-07-27) ─────────────────
        # Verify IS the coach-finalize act on the ideal text, so this is the
        # sentence-level correction capture point: diff the frozen machine
        # draft (auto_text) against the verified text, one annotation event
        # per changed sentence run, one approved_as_is block event when the
        # coach verified untouched. Runs ONLY on the 'verified' outcome —
        # 'already' returned above, so exactly-once-per-version is inherited
        # from verify_ideal_text. Best-effort; never blocks the verify.
        try:
            from services.ideal_text_annotations import (
                emit_ideal_text_annotations,
            )
            _n = emit_ideal_text_annotations(
                db,
                arc_id=arc_id,
                owner_user_id=owner,
                coach_user_id=str(request.user_id),
                draft_text=row.get("auto_text"),
                final_text=row.get("verified_text"),
                # Staleness guard (review finding, HIGH): if a new take
                # refreshed auto_text AFTER the coach's last edit, the diff
                # would blame machine-v(N)↔v(N+1) drift on the coach — the
                # module skips emission in that case.
                auto_updated_at=row.get("auto_updated_at"),
                coach_updated_at=row.get("updated_at"),
                coach_owned=bool(row.get("updated_by")
                                 or row.get("approved_at")),
            )
            if _n:
                logger.info("ideal-text annotations emitted arc=%s count=%d",
                            arc_id, _n)
        except Exception as _ann_err:
            logger.warning("ideal-text annotation capture failed arc=%s: %s "
                           "(non-fatal)", arc_id, _ann_err)

        from services.ideal_text_core_snapshot import publish_for_arc
        publish_for_arc(db, str(arc_id))
        return jsonify({"verified": True, "arc_id": arc_id,
                        "version": version}), 200
    except Exception as e:
        logger.error("coach/verify failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to verify"}), 500


@v2_bp.route("/coach/arc/<arc_id>/ideal-text/approve", methods=["POST"])
@heavy_limit
@require_admin_or_coach
def v2_coach_approve_ideal_text(arc_id):
    """Approve the ideal text for delivery (the Publish precondition). With
    no saved coach block yet, the AUTO draft is persisted as the block and
    approved in one deterministic action (review-without-edit approval).
    200 {ok, approved:true} · 409 IDEAL_TEXT_EMPTY · 500"""
    try:
        row = db.ideal_text.get_coach_arc_ideal_text(arc_id)
        text = (row or {}).get("text") or ""
        if not text.strip():
            from services.ideal_text_block import assemble_ideal_text_block
            auto = assemble_ideal_text_block(arc_id)
            text = auto.get("text") or ""
            if not text.strip():
                return jsonify({
                    "code": "IDEAL_TEXT_EMPTY",
                    "error": "Nothing to approve — the arc has no "
                             "assembled ideal text yet.",
                }), 409
        ok = db.ideal_text.upsert_coach_arc_ideal_text(
            arc_id, text, str(request.user_id), approve=True)
        if not ok:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not approve"}), 500

        # ── Learning-pipeline item 3 at APPROVE (FE close-out 2026-07-28) ──
        # The shipped FE's Verify button posts THIS route — nothing in the FE
        # calls /verify — so without a hook here the sentence-level capture
        # never fires in production. Approve has no re-approve guard, so
        # exactly-once comes from the annotation PROBE instead: first approve
        # captures, re-approves skip (the /verify route keeps its richer
        # per-version guard and needs no probe). Same staleness fence as
        # verify, read from the PRE-approve row — the approve upsert above
        # stamps updated_by/updated_at, which must not vouch for freshness.
        # Best-effort; never blocks the approve.
        try:
            import re as _re
            from services.ideal_text_annotations import (
                emit_ideal_text_annotations,
            )
            _arc_uuid = str(arc_id) if _re.match(
                r"^[0-9a-fA-F-]{36}$", str(arc_id)) else None
            if not db.has_ideal_text_annotations(_arc_uuid):
                _sessions = db.takes.get_arc_sessions(arc_id) or []
                _owner = next((s.get("user_id") for s in _sessions
                               if s.get("user_id")), None)
                _pre = row or {}
                # Review-without-edit: the text being approved IS the fresh
                # machine assembly (no stored block existed) — draft==final
                # by construction, an endorsement, not an absent draft.
                _machine_approved = not ((_pre.get("text") or "").strip())
                _n = emit_ideal_text_annotations(
                    db,
                    arc_id=arc_id,
                    owner_user_id=_owner,
                    coach_user_id=str(request.user_id),
                    draft_text=(text if _machine_approved
                                else _pre.get("auto_text")),
                    final_text=text,
                    auto_updated_at=_pre.get("auto_updated_at"),
                    coach_updated_at=_pre.get("updated_at"),
                    coach_owned=bool(_pre.get("updated_by")
                                     or _pre.get("approved_at")),
                )
                if _n:
                    logger.info("ideal-text annotations emitted at approve "
                                "arc=%s count=%d", arc_id, _n)
        except Exception as _ann_err:
            logger.warning("ideal-text annotation capture at approve failed "
                           "arc=%s: %s (non-fatal)", arc_id, _ann_err)

        from services.ideal_text_core_snapshot import publish_for_arc
        publish_for_arc(db, str(arc_id))
        return jsonify({"ok": True, "arc_id": arc_id, "approved": True}), 200
    except Exception as e:
        logger.error("coach ideal-text approve failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to approve"}), 500


@v2_bp.route("/coach/sessions/<session_id>/save-feedback", methods=["POST"])
@require_admin_or_coach
def v2_coach_save_feedback(session_id):
    """The per-take coach 'Save' checkpoint (founder 2026-07-15): PERSISTS the
    coach's authoring for this take and stamps it reviewed-and-saved so the
    coach can move to the next recording. Delivers NOTHING to the student —
    the single 'Save and Publish full analysis' does.

    Body (FE sends the same shape the old publish door took — save-at-once,
    no per-keystroke autosave):
      snippets?: [{id, note?, tag?, surfaced?, transcript_corrected?, ...}]
                  → the coach draft store, via
                  the SAME shared helper as every other door (no drift);
      overall_message? → persisted as the separate take-level coach summary.
                  Exact-evidence paragraph feedback remains in the canonical
                  draft repository until publish.

    200 {saved:true, snippets_saved} · 400 · 404 · 422 · 500"""
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "session_id must be a UUID"}), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND",
                            "error": "Session not found"}), 404
        body = request.get_json(silent=True) or {}

        if "insights_payload" in body:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "insights_payload is retired",
            }), 422

        if "overall_message" in body:
            from services.feedback_repository import (
                FeedbackContractError,
                normalize_coach_overall_message,
            )
            try:
                overall_message = normalize_coach_overall_message(
                    body.get("overall_message"))
            except FeedbackContractError as error:
                return jsonify({
                    "code": "INVALID_INPUT", "error": str(error),
                }), 422
            if not db.takes.set_session_coach_overall_message(
                session_id, overall_message,
            ):
                return jsonify({
                    "code": "V2_ERROR",
                    "error": "Could not save coach review summary",
                }), 500

        # Founder 2026-07-16: the coach saves the MERGED packet (the take +
        # its folded mid-take re-reads) under the spoken take's path — every
        # row routes to its OWNING session (a read snippet persists under
        # the read's own session id, where all downstream readers look).
        _owners = {}
        _inline = body.get("snippets")
        if isinstance(_inline, list) and _inline:
            _owners = _snippet_owner_map(session_id)

        # ── Persist the inline authoring (same doors-can't-drift helper). ──
        _n_saved = 0
        if isinstance(_inline, list) and _inline:
            for _entry in _inline:
                if not isinstance(_entry, dict):
                    return jsonify({
                        "code": "INVALID_INPUT",
                        "error": "snippets: entries must be objects",
                    }), 422
                _snip_id = str(_entry.get("id") or "").strip()
                if _snip_id not in _owners:
                    return jsonify({
                        "code": "SNIPPET_NOT_FOUND",
                        "error": f"snippet {_snip_id or '(missing id)'} "
                                 "not in this session",
                    }), 404
                _fields = dict(_entry)
                _fields.pop("id", None)
                _lane_err = _save_coach_snippet_lanes(
                    _owners[_snip_id], _snip_id, _fields,
                )
                if _lane_err is not None:
                    return _lane_err
                _n_saved += 1

        if not db.takes.set_session_feedback_saved(session_id):
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        return jsonify({"saved": True, "session_id": session_id,
                        "snippets_saved": _n_saved}), 200
    except Exception as e:
        logger.error("save-feedback failed sid=%s: %s", session_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500


def _arc_has_a_surfaced_note(spoken):
    """Does anywhere in this arc carry a surfaced note? — the library floor.

    ONE READ FOR THE WHOLE ARC. This scanned take by take and broke on the
    first hit: cheap for a coach who authored something on take 1, a round
    trip PER TAKE for the case that actually matters — a journey with no
    notes yet, which is every new student's.

    True on a read miss, DELIBERATELY: a miss must not fabricate a blocker
    and lock the coach out of publishing. Publish re-checks per take anyway,
    where a miss is a 409 with copy that says what to do — a false ENABLE
    costs one clear error, a false DISABLE costs a coach who cannot ship
    work they have already done.
    """
    try:
        by_take = db.get_coach_snippet_drafts_by_sessions(
            [s.get("id") for s in spoken if s.get("id")]) or {}
    except Exception:
        return True
    return any(
        d.get("surfaced") and (d.get("note") or "").strip()
        for rows in by_take.values() for d in rows
    )


@v2_bp.route("/coach/arc/<arc_id>/review-state", methods=["GET"])
@require_admin_or_coach
def v2_coach_arc_review_state(arc_id):
    """The coach's arc wrap-up state (founder 2026-07-17) — ONE read that
    answers "what's left before I can publish?", so the post-last-take screen
    (Open the ideal text → PUBLISH) needs no client-side inference across
    per-take calls.

    The publish preconditions are the SAME ones publish-analysis enforces
    (every spoken take saved + the ideal text approved) — served here as data
    instead of only as a 409, so the FE can render the button's state up front
    rather than discovering it on a failed POST.

    200 {
      arc_id, published,
      takes: [{session_id, take_index, review_state, has_reread}],   # spoken
      takes_saved, takes_total, takes_target,
      ideal: {assembly_state, ready, approved, source, takes_done},
      can_publish, blockers: ["TAKES_NOT_SAVED"|"IDEAL_TEXT_NOT_APPROVED"|
                              "NO_TAKES"],
      pending_session_ids: [...]        # the unsaved takes, for the FE's copy
    }
    404 · 500
    """
    try:
        sessions = db.takes.get_arc_sessions(arc_id)
        if not sessions:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        spoken, reads = _spoken_takes_and_reads(sessions)

        takes = []
        pending = []
        for s in spoken:
            sid = str(s.get("id"))
            publish_payload = None
            if s.get("results_published_at"):
                _rs = "delivered"
            elif s.get("coach_feedback_saved_at"):
                _rs = "reviewed"
                try:
                    from services.feedback_repository import (
                        FeedbackRepository,
                        serialize_feedback_item,
                    )

                    publish_payload = {
                        "session_id": sid,
                        "overall_message": (
                            str(s.get("coach_overall_message") or "").strip()
                            or None
                        ),
                        "feedback_items": [
                            serialize_feedback_item(item)
                            for item in FeedbackRepository(db).surfaced_items(sid)
                        ],
                        # Video remains private unless the coach explicitly
                        # chooses Share with user in the final payload.
                        "share_video": False,
                    }
                except Exception as payload_error:
                    logger.warning(
                        "coach review-state payload invalid sid=%s: %s",
                        sid,
                        payload_error,
                    )
            else:
                _rs = "to_review"
                pending.append(sid)
            takes.append({
                "session_id": sid,
                "take_index": s.get("take_index"),
                "review_state": _rs,
                "has_reread": bool(reads.get(sid)),
                "publish_payload": publish_payload,
            })

        from services.slide_selection import TAKES_TARGET
        row = db.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
        _ideal_text = (row.get("text") or "").strip()
        _approved = bool(row.get("approved_at"))
        ideal = {
            # "ready" the moment a block exists to review; "pending" until the
            # eager assembly at spoken take 3 has something to show.
            "assembly_state": ("ready" if _ideal_text else "pending"),
            "ready": bool(_ideal_text),
            "approved": _approved,
            "source": ("coach" if row.get("updated_by")
                       else ("machine" if _ideal_text else None)),
            "takes_done": min(len(spoken), TAKES_TARGET),
        }

        # ── WHAT ACTUALLY BLOCKS A PUBLISH (founder ruling 2026-08-14) ──
        #
        # "Post it when I want, even with a single feedback." The old gate
        # demanded EVERY take saved AND the ideal text verified, which made
        # coach work all-or-nothing: review 17 of 18 moments, save one take
        # of two, skip the verify — and the student saw exactly as much as if
        # the panel had never been opened. That is how a month of recordings
        # produced nothing.
        #
        # The library floor stays, and is now the ONLY content gate: at least
        # one surfaced snippet carrying a note, somewhere in the arc. It is
        # what guarantees a publish delivers something rather than an empty
        # envelope, and it is enforced again per-take at publish time.
        _has_a_note = _arc_has_a_surfaced_note(spoken)

        # ONLY ONE BLOCKER SURVIVES: there is nothing recorded to publish.
        #
        # Not even the library floor blocks HERE, and that is deliberate.
        # `get_coach_snippet_drafts` returns [] on a read failure exactly as
        # it does when there genuinely are no drafts, so blocking on it would
        # let one transient hiccup grey out the publish button with a reason
        # the coach cannot act on. The floor is re-checked per take at publish
        # time against fresh reads, where a miss is a 409 with copy that says
        # what to do — a false ENABLE costs one clear error message, a false
        # DISABLE costs a coach who cannot ship work they have already done.
        blockers = []
        if not spoken:
            blockers.append("NO_TAKES")

        # ADVISORIES, not blockers. The panel shows them so the coach knows
        # what a publish right now would leave out — unsaved takes are
        # skipped and stay visibly "to review" (partial publish, founder
        # 2026-08-14) — but nothing here disables the button.
        advisories = []
        if pending:
            advisories.append("TAKES_NOT_SAVED")
        if not _approved:
            advisories.append("IDEAL_TEXT_NOT_APPROVED")
        if spoken and not _has_a_note:
            advisories.append("NO_FEEDBACK")

        _body = {
            "arc_id": arc_id,
            "published": bool(spoken) and all(
                s.get("results_published_at") for s in spoken),
            "takes": takes,
            "takes_saved": len(spoken) - len(pending),
            "takes_total": len(spoken),
            "takes_target": TAKES_TARGET,
            "ideal": ideal,
            "can_publish": not blockers,
            "blockers": blockers,
            "advisories": advisories,
            "pending_session_ids": pending,
        }
        # Single deliverable (2026-07-17): the wrap-up's action is VERIFY —
        # available whenever a current version exists and isn't verified yet.
        _v = row.get("version") or (1 if _ideal_text else None)
        _vv = row.get("verified_version")
        _verified = bool(_v is not None and _vv == _v
                         and (row.get("verified_text") or "").strip())
        _body.update({
            "version": _v,
            "verification_status": (
                "verified" if _verified
                else ("unverified" if _ideal_text else None)),
            "verify_available": bool(_ideal_text and not _verified),
        })
        return jsonify(_body), 200
    except Exception as e:
        logger.error("coach/arc review-state failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to load the review state",
        }), 500


# ── Coach STAR VERDICT (founder 2026-07-27) ───────────────────────────────
# The decision-layer correction corpus for the voice-text analytics: the coach
# judges whether each fired star DESERVED to fire, and as the right kind.
#
# BLIND COACH — these two endpoints deliberately show the coach the machine's
# guess. That is safe here (a star is not a confidence label) and unsafe on the
# labeling lane, so they are kept STRICTLY SEPARATE from the blind
# blind confidence-labeling surface: different endpoints, and the payload
# carries no acoustic read or shadow prediction. A coach can
# judge the ADVICE with full sight and must still label the VOICE blind.
# Pinned by test_star_verdicts.py.
def _star_playback_by_snippet(sessions, starred) -> dict:
    """Playback fields for each starred snippet across the arc's takes.

    One batch read for the arc's takes instead of one per take (founder
    2026-09-26). Full rows: the playback falls back to audio_ref /
    storage_path / transcript_excerpt, which the slim projection leaves out.
    """
    # Resolved (founder 2026-08-10: "I need the playbacks to work in the
    # feedbacks review") — an s3:// fallback ref rendered every star row's
    # player dead; the resolver signs it against its own bucket and passes
    # healthy URLs through.
    from services.audio_ref_resolver import resolve_playable_ref
    _ids = [str(_s.get("id") or "") for _s in sessions if _s.get("id")]
    _by_session = (db.get_snippets_by_sessions(
        _ids, include_words=True) or {}) if _ids else {}
    out: dict = {}
    for _s in sessions:
        _sid = str(_s.get("id") or "")
        for _snip in (_by_session.get(_sid) or []) if _sid else []:
            _snip_id = str(_snip.get("id") or "")
            if _snip_id not in starred:
                continue
            out[_snip_id] = {
                "audio_ref": resolve_playable_ref(
                    _snip.get("audio_segment_path")
                    or _snip.get("audio_ref")
                    or _snip.get("storage_path")),
                "start_offset_ms": _snip.get("start_offset_ms"),
                "duration_ms": _snip.get("duration_ms"),
                "transcript": (_snip.get("transcript")
                               or _snip.get("transcript_excerpt")
                               or ""),
                "take_index": _s.get("take_index"),
            }
    return out


@v2_bp.route("/coach/arc/<arc_id>/stars", methods=["GET"])
@require_admin_or_coach
def v2_coach_arc_stars(arc_id):
    """Every star the system fired on this arc, with the coach's judgment.

    The review list for the star-verdict surface: one row per starred moment,
    carrying what the machine produced (kind, device, why, replacement) and the
    coach's existing verdict when they've already judged it. `device_options`
    is what they may pick when answering "wrong kind", so the FE renders the
    choices without hard-coding a vocabulary that lives in the BE.

    200 { arc_id, stars: [...], judged, total, summary }
    404 · 500
    """
    try:
        sessions = db.takes.get_arc_sessions(arc_id)
        if not sessions:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404

        from services.star_verdicts import corpus_summary, stars_with_verdicts

        suggestions = db.get_moment_suggestions_by_arc(arc_id) or {}
        verdicts = db.get_star_verdicts_by_snippet_ids(
            list(suggestions.keys())) or {}

        # Playback context per starred snippet (FE ask 2026-07-28): the coach
        # hears the moment they're judging. Allowlisted fields only — the
        # snippet row's metrics (acoustic_read/voice_confidence) must NOT ride
        # an analytics review payload (BLIND COACH); the allowlist lives in
        # stars_with_verdicts._SNIPPET_PLAYBACK_KEYS.
        snippets_by_id = (_star_playback_by_snippet(
            sessions, set(suggestions.keys())) if suggestions else {})

        stars = stars_with_verdicts(list(suggestions.values()), verdicts,
                                    snippets_by_id)
        # Chronology isn't available on the suggestion row, so order by the
        # thing the coach cares about: unjudged first, then by family.
        stars.sort(key=lambda s: (s.get("judged"),
                                  s.get("star_kind") or "",
                                  s.get("star_device") or ""))
        return jsonify({
            "arc_id": arc_id,
            "stars": stars,
            "total": len(stars),
            "judged": sum(1 for s in stars if s.get("judged")),
            "summary": corpus_summary(list(verdicts.values())),
        }), 200
    except Exception as e:
        logger.warning("v2_coach_arc_stars failed arc=%s: %s", arc_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not load stars"}), 500


@v2_bp.route("/coach/snippets/<snippet_id>/star-verdict", methods=["PUT"])
@require_admin_or_coach
def v2_coach_put_star_verdict(snippet_id):
    """Record the coach's judgment of ONE fired star — and, since §4b of the
    FE handoff (2026-07-28), optionally their corrected wording riding the
    same PUT.

    Body { star_kind, star_device?, verdict, corrected_device?, note?,
           star_version?, why_final?, replacement_text_final? }

      verdict='keep'             the star was right (the endorsement signal)
      verdict='wrong_kind'       requires corrected_device — the confusion pair
      verdict='should_not_fire'  this moment deserved silence

    The *_final keys are the coach's rewrite of what the star SAYS. The FE
    sends them ONLY when the coach actually changed the text, and sending
    them on the verdict write makes the half-state (an edit with no verdict)
    unrepresentable at the wire — the edit→keep PAIR is what trains. Partial
    semantics: an absent key preserves the stored correction; there is no
    null-clear on this route (the full-state star-text PUT keeps that). Text
    writes happen BEFORE the verdict, so a keep's corpus emission always
    carries the fresh wording; a guard-tripping string 400s before ANYTHING
    is written (the gesture stays atomic).

    Idempotent: re-judging the same star REPLACES the previous verdict.
    Nothing here mutates the machine's draft text or the student's flow (L1
    — the student sees the coach's folded wording, which is the point).
    Verdicts are never surfaced to the student (AC-9).

    200 { saved, snippet_id, verdict } · 400 · 404 · 500
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "snippet_id must be a valid UUID"}), 400
    body = request.get_json(silent=True) or {}

    from services.star_verdicts import (
        validate_star_text_updates, validate_verdict,
    )

    row, err = validate_verdict(body)
    if err:
        return jsonify({"code": "INVALID_INPUT", "error": err}), 400
    text_updates, text_err = validate_star_text_updates(body)
    if text_err:
        return jsonify({"code": "INVALID_INPUT", "error": text_err}), 400

    try:
        snip = db.get_snippet_by_id(snippet_id)
        if not snip:
            return jsonify({"code": "NOT_FOUND",
                            "error": "snippet not found"}), 404
        session_id = snip.get("session_id")
        arc_id = None
        owner_user_id = None
        if session_id:
            _sess = db.v2_get_session_by_id(str(session_id)) or {}
            arc_id = _sess.get("arc_id")
            owner_user_id = _sess.get("user_id")

        # The verdict this one replaces — read BEFORE the upsert so a
        # first-time KEEP is distinguishable from a re-KEEP (below).
        # Error-distinguishing read: a FAILED read must not look like "no
        # prior verdict" or a re-keep during a transient error double-writes
        # the corpus row — _prior_ok=False fails the emission closed.
        _prior, _prior_ok = db.get_star_verdict(snippet_id)

        # §4b text first (so the keep-emission below reads the fresh final).
        # A failed write fails the WHOLE gesture before the verdict lands —
        # per the FE contract only edited rows can reach this branch, so the
        # plain verdict path can never regress behind it.
        if text_updates:
            _text_saved = db.set_moment_suggestion_final(
                str(snippet_id),
                edited_by=getattr(request, "user_id", None),
                **text_updates,
            )
            if not _text_saved:
                return jsonify({
                    "code": "SERVER_ERROR",
                    "error": "could not save the corrected wording (run "
                             "migrations/add_moment_suggestion_final.sql)",
                }), 500

        saved = db.upsert_star_verdict(
            snippet_id=snippet_id, row=row, session_id=session_id,
            arc_id=arc_id, coach_user_id=getattr(request, "user_id", None),
        )
        if not saved:
            return jsonify({
                "code": "SERVER_ERROR",
                "error": "could not save verdict (run "
                         "migrations/add_star_verdicts.sql)",
            }), 500

        # ── Learning-pipeline item 2 (founder 2026-07-27/28) ──────────────
        # A verdict flipping TO 'keep' is the coach signing off the star's
        # TEXT — emit the (machine draft, coach-corrected final) pair into
        # the writer corpus. Untouched text → approved_as_is endorsement;
        # coach-rewritten text (§4b riding this PUT, or the star-text PUT) →
        # the correction pair. Only text crosses lanes; the verdict stays in
        # star_verdicts (the decision corpus). Guarded on the flip — plus the
        # re-keep-with-a-fresh-correction case (text_updated), which is a
        # genuinely new pair the flip guard alone would drop. wrong_kind /
        # should_not_fire emit nothing (a rejected star's text must not train
        # the writer as preferred output). Best-effort — a miss never fails
        # the save.
        try:
            from services.star_verdicts import (
                annotation_pair_for_star, should_emit_keep_text,
            )
            if (_prior_ok
                    and should_emit_keep_text(
                        row["verdict"], (_prior or {}).get("verdict"),
                        text_updated=bool(text_updates))
                    and owner_user_id and arc_id):
                _sugg = (db.get_moment_suggestions_by_arc(arc_id)
                         or {}).get(str(snippet_id))
                _pair = annotation_pair_for_star(_sugg)
                if _pair:
                    _draft_text, _final_text = _pair
                    db.create_admin_annotation_event(
                        user_id=str(owner_user_id),
                        session_id=str(session_id) if session_id else None,
                        section_type="moment_suggestion",
                        field_name="moment_suggestion",
                        ai_original_text=_draft_text,
                        coach_final_text=_final_text,
                        reason_chip=("approved_as_is"
                                     if _draft_text == _final_text else None),
                        custom_reason=None,
                        created_by=str(getattr(request, "user_id", "") or ""),
                        draft_id=str(snippet_id),
                    )
        except Exception as _emit_err:
            logger.warning(
                "star-verdict keep-emit failed snip=%s: %s (non-fatal)",
                snippet_id, _emit_err,
            )

        return jsonify({"saved": True, "snippet_id": snippet_id,
                        "verdict": row["verdict"]}), 200
    except Exception as e:
        logger.warning("v2_coach_put_star_verdict failed snip=%s: %s",
                       snippet_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not save verdict"}), 500


def _resolve_audio_refs(rows: list, *, expires_in: int = 6 * 3600) -> None:
    """Turn every row's ``audio_ref`` into something an <audio src> can play.

    Already-absolute http(s) URLs pass through untouched (imports store a
    public URL). A bare storage key is signed for the session's length —
    long enough that a coach can work through a queue without links dying
    mid-batch. Best-effort per row: a key that cannot be signed is left as
    it is rather than nulled, so the failure is visible and debuggable
    instead of a silently missing player."""
    # The bucket-authoritative branch is HOISTED (founder 2026-08-10):
    # this fix lived only here while every user surface handed the raw
    # column through — services/audio_ref_resolver.py is the one copy now.
    from services.audio_ref_resolver import resolve_playable_ref
    for r in rows or []:
        ref = r.get("audio_ref")
        resolved = resolve_playable_ref(ref, expires_in=expires_in)
        if resolved and resolved != ref:
            r["audio_ref"] = resolved


def _int_or(raw, default: int) -> int:
    """Form int with a fallback — a typo in an optional knob must not 400 an
    upload that already cost the coach a file read."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


@v2_bp.route("/coach/training-imports", methods=["POST"])
@phase2_learning_disabled
@whisper_limit
@require_admin_or_coach
def v2_coach_training_import():
    """Upload ONE audio file as coach-reviewable TRAINING data — analysed
    like a real take, but never a project the speaker owns (founder
    2026-07-28).

    Multipart form:
      audio_file    (required) any container ffmpeg reads (webm/mp3/m4a/wav…)
      topic         (required) what the talk is about — labels it for review
      speaker_label (optional) whose voice this is. Worth filling for a
                    multi-speaker corpus: it is the only grouping key a
                    per-speaker model will have.
      user_id       (optional) who the corpus row belongs to; defaults to the
                    uploading coach
      note          (optional) free-text provenance (where it came from)
      language      (optional) ISO-639-1 ('pl', 'de', …). Absent =
                    auto-detect. Non-English NEEDS this: our Whisper prompt
                    is an English disfluency primer and Whisper follows its
                    prompt's language.
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

    ONE FILE PER REQUEST, on purpose: a batch endpoint would either block for
    minutes or need a job queue, and per-file requests give the FE real
    progress and per-file failures instead of one opaque 500.

    The import is marked source='training_import', which keeps it out of the
    speaker's project list AND out of their acoustic baseline (imports are
    z-scored against themselves) — see services/training_import.py.

    200 { ok, session_id, arc_id, snippet_count, ... }  → review at
         GET /v2/coach/arc/<arc_id>/stars
    422 { code: "AUDIO_REJECTED", reason }   the min-content gate (silence /
         corrupt / too short) — the same gate live takes pass
    400 · 500
    """
    audio_file = request.files.get("audio_file")
    if not audio_file:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "audio_file is required"}), 400
    topic = (request.form.get("topic") or "").strip()
    if not topic:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "topic is required"}), 400
    try:
        audio_bytes = audio_file.read()
        from services.training_import import (
            prepare_training_import, run_training_import_analysis,
        )
        _filename = audio_file.filename or "import.webm"
        _queue_per_band = _int_or(request.form.get("queue_per_band"), 5)
        prepared = prepare_training_import(
            audio_bytes=audio_bytes,
            filename=_filename,
            content_type=audio_file.mimetype,
            user_id=(request.form.get("user_id")
                     or getattr(request, "user_id", None)),
            topic=topic,
            speaker_label=(request.form.get("speaker_label") or "").strip()
                          or None,
            source_note=(request.form.get("note") or "").strip() or None,
            stages=(request.form.get("stages") or None),
            # BOTH spellings (fix 2026-07-29): I documented
            # `upload_idempotency_key` (the coach-video lane's name) but the
            # FE shipped `idempotency_key`, so the key was being silently
            # ignored and the dedupe it exists for never ran. Accepting both
            # costs nothing and neither side has to redeploy to be correct.
            idempotency_key=((request.form.get("idempotency_key")
                              or request.form.get("upload_idempotency_key")
                              or "").strip() or None),
            language=(request.form.get("language") or "").strip() or None,
        )
        if not prepared.get("ok"):
            _reason = prepared.get("reason") or "failed"
            if _reason in ("no_audio", "too_short", "silence", "gate",
                           "gate_error", "no_topic"):
                return jsonify({
                    "code": "AUDIO_REJECTED", "reason": _reason,
                    "error": prepared.get("detail")
                             or "the audio did not pass the content gate",
                }), 422
            return jsonify({"code": "SERVER_ERROR", "reason": _reason,
                            "error": prepared.get("detail")
                                     or "import failed"}), 500

        # The idempotency key already produced this import — return the
        # original rather than minting a second (a talk imported twice is
        # labelled twice and trains twice, invisibly).
        if prepared.get("duplicate"):
            return jsonify({**prepared, "status": "duplicate"}), 200

        # ── 202, then analyse in the background ───────────────────────────
        # Whisper + the cutting pass is MINUTES on a long talk, and the FE's
        # proxy caps far below that. Returning the request before the work
        # removes the dangerous shape entirely: a gateway timeout on a
        # request whose BE work then succeeded, which the coach reads as
        # "failed" and retries into a duplicate. The FE polls
        # GET /v2/coach/training-imports/<session_id> for the outcome; the
        # session's analysis_state carries it (the same processing → ready |
        # failed lane the live async path already uses).
        import threading
        _t = threading.Thread(
            target=run_training_import_analysis,
            kwargs={"prepared": prepared, "audio_bytes": audio_bytes,
                    "filename": _filename,
                    "queue_per_band": _queue_per_band},
            daemon=True,
        )
        _t.start()
        # THE 202 IS A RECEIPT, NOT A RESULT — and it must be impossible to
        # read as one (FE §6.4). It carries NO count field: a consumer whose
        # rule is "ok:true with a count present = finished" would otherwise
        # see a bare ok:true, default the missing counts to 0, and announce a
        # zero-piece failure that never happened. `status: "processing"` says
        # the same thing positively. Both properties are pinned by test —
        # adding snippet_count/queue_count here would break a real consumer.
        return jsonify({
            "ok": True, "status": "processing",
            "session_id": prepared["session_id"],
            "arc_id": prepared["arc_id"],
            "stages": prepared["stages"],
            "duration_sec": prepared.get("duration_sec"),
            "speaker_label": prepared.get("speaker_label"),
            "language": prepared.get("language"),
            "filename": _filename,
        }), 202
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

    200 { imports: [{session_id, arc_id, topic, speaker_label, created_at,
          status, queue_count, labelled_count, language,
          duration_sec, archived_at}], count }
    """
    try:
        proficient = db.get_user_proficient_languages(
            str(getattr(request, "user_id", "") or ""))
        if not proficient:
            return _rater_language_error("profile_required")

        rows = db.takes.list_training_import_sessions(
            user_id=(request.args.get("user_id") or None)) or []
        include_archived = (request.args.get("include_archived") or "") in (
            "1", "true", "yes")
        routed = []
        for r in rows:
            snippets = db.get_snippets_by_session(str(r.get("id"))) or []
            outcome, _language = _rater_language_outcome(
                r, snippets, proficient=proficient)
            if outcome == "matched":
                routed.append(r)
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
                # Same class of question for the confidence composite: one
                "duration_sec": ctx.get("duration_sec"),
                # null on live rows; set = when it was archived. Present on
                # every row so the shape doesn't shift with the query param.
                "archived_at": ctx.get("archived_at"),
            })
        return jsonify({"imports": out, "count": len(out)}), 200
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


def _coach_inline_canonical_queue_rows(
    prepared: dict[str, Any],
    *,
    session_id: str,
    project_id: str,
) -> list[dict[str, Any]]:
    """Project frozen D5 items without collapsing their review identity.

    A snippet identifies audio lineage, not a review act. The same clip may
    have multiple frozen candidate/membership assignments, so this function
    iterates the canonical items directly and preserves database order.
    """
    raw_items = prepared.get("items")
    if not isinstance(raw_items, list):
        raise ValueError("COACH_INLINE_CANONICAL_ITEMS_REQUIRED")
    rows: list[dict[str, Any]] = []
    decision_values = {
        "rating_yes": "yes",
        "rating_in_between": "in_between",
        "rating_no": "no",
        "rating_not_sure": "not_sure",
        "rating_audio_unclear": "audio_unclear",
    }
    for expected_position, raw in enumerate(raw_items, start=1):
        if not isinstance(raw, dict):
            raise ValueError("COACH_INLINE_CANONICAL_ITEM_INVALID")
        exact = raw
        required_uuids = (
            "review_batch_id",
            "review_assignment_id",
            "blind_packet_id",
            "take_id",
            "snippet_id",
            "playback_reference_id",
            "presentation_id",
            "acknowledgement_token",
        )
        if any(
            not _is_valid_uuid(str(exact.get(key) or ""))
            for key in required_uuids
        ):
            raise ValueError("COACH_INLINE_CANONICAL_IDENTITY_INVALID")
        if str(exact["review_assignment_id"]) != str(
            exact["playback_reference_id"]
        ):
            raise ValueError("COACH_INLINE_PLAYBACK_IDENTITY_INVALID")
        payload_hash = str(exact.get("visible_payload_sha256") or "")
        if re.fullmatch(r"[0-9a-f]{64}", payload_hash) is None:
            raise ValueError("COACH_INLINE_VISIBLE_PAYLOAD_INVALID")
        position = exact.get("canonical_position")
        if not isinstance(position, int) or position != expected_position:
            raise ValueError("COACH_INLINE_CANONICAL_ORDER_INVALID")
        if str(exact["take_id"]) != session_id:
            continue
        value = decision_values.get(str(exact.get("judgment") or ""))
        label = None if value is None else {
            "value": value,
            "unrateable": value == "audio_unclear",
            "confident": True if value == "yes" else (
                False if value == "no" else None
            ),
            "intensity": None,
            "note": None,
        }
        rows.append({
            "snippet_id": str(exact["snippet_id"]),
            "review_assignment_id": str(exact["review_assignment_id"]),
            "canonical_position": position,
            "playback_reference_id": str(exact["playback_reference_id"]),
            "label": label,
            "re_review": False,
            "rating_locked": label is not None,
            "rating_lock_reason": (
                "immutable_blind_judgment" if label else None
            ),
            "learning_exposures": [],
            "blind_review": {
                "project_id": project_id,
                "review_batch_id": str(exact["review_batch_id"]),
                "review_assignment_id": str(exact["review_assignment_id"]),
                "blind_packet_id": str(exact["blind_packet_id"]),
                "presentation_id": str(exact["presentation_id"]),
                "acknowledgement_token": str(
                    exact["acknowledgement_token"]
                ),
                "visible_payload_sha256": payload_hash,
            },
        })
    return rows


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


def _coach_inline_authoring_queue(
    visible_rows, *, session_id, _project_id, _owner_id, _coach_id,
):
    from services.db import first_client_repository

    reviewer_identity = db.get_owner_principal_for_user(_coach_id) or {}
    reviewer_principal_id = str(reviewer_identity.get("id") or "")
    prepared = first_client_repository.prepare_coach_inline_blind_batch({
        "p_project_id": _project_id,
        "p_acquisition_principal_id": _owner_id,
        "p_reviewer_principal_id": reviewer_principal_id,
        "p_idempotency_key": (
            f"coach-inline-visible-request:{_project_id}:"
            f"{reviewer_principal_id}"
        ),
    }) if _is_valid_uuid(reviewer_principal_id) else None
    if not prepared:
        raise ValueError("COACH_INLINE_CANONICAL_BATCH_REQUIRED")
    # Render the exact frozen assignments themselves. Never use
    # snippet_id as a dictionary key: two legitimate review acts may
    # share one clip while carrying different membership/candidate,
    # offer, packet and presentation identities.
    return _coach_inline_canonical_queue_rows(
        prepared,
        session_id=str(session_id),
        project_id=_project_id,
    )


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


def _coach_legacy_blind_presentation_queue(
    visible_rows, *, session_id, _project_id, _owner_id, _coach_id,
    _blind_candidates,
):
    opaque_rows = []
    for row in visible_rows:
        opaque = _coach_legacy_blind_presentation_row(
            row, session_id=session_id, _project_id=_project_id,
            _owner_id=_owner_id, _coach_id=_coach_id,
            _blind_candidates=_blind_candidates,
        )
        if opaque is not None:
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
    built and persisted exactly once (any take, not just an import).

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
        from services.coach_guidance_delivery import inline_authoring_is_enabled
        if (_coach_id and _owner_id and _project_id and
                inline_authoring_is_enabled()):
            visible_rows = _coach_inline_authoring_queue(
                visible_rows, session_id=session_id, _project_id=_project_id,
                _owner_id=_owner_id, _coach_id=_coach_id,
            )
        elif _coach_id and _owner_id and _project_id:
            visible_rows = _coach_legacy_blind_presentation_queue(
                visible_rows, session_id=session_id, _project_id=_project_id,
                _owner_id=_owner_id, _coach_id=_coach_id,
                _blind_candidates=_blind_candidates,
            )
        else:
            visible_rows = []
        return jsonify({"session_id": session_id, "queue": visible_rows,
                        "count": len(visible_rows),
                        "labelled": labelled}), 200
    except Exception as e:
        logger.warning("confidence queue failed sid=%s: %s", session_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not load the queue"}), 500


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


@v2_bp.route(
    "/coach/sessions/<session_id>/confidence-comparison",
    methods=["GET"],
)
@require_admin_or_coach
def v2_coach_confidence_comparison(session_id):
    """Founder-only, post-label machine × own-coach comparison.

    It is a separate endpoint from the blind queue and emits only rows this
    caller has already labelled.  The stored machine proposal is a historical
    routing snapshot, never a quorum vote.
    """
    from services.founder_confidence_comparison import (
        build_founder_comparison, is_founder_comparison_email,
    )

    token_payload = getattr(request, "token_payload", None) or {}
    if not is_founder_comparison_email(token_payload.get("email")):
        return jsonify({"code": "FORBIDDEN", "error": "Not available"}), 403
    try:
        sess = db.v2_get_session_by_id(str(session_id))
        if not sess or sess.get("source") != "training_import":
            return jsonify({"code": "NOT_FOUND", "error": "Not found"}), 404
        snippets = db.get_snippets_by_session(str(session_id)) or []
        picked = _confidence_queue_selection(session_id, sess, snippets)
        snippet_ids = [str(row.get("id")) for row in picked if row.get("id")]
        labels = db.get_confidence_labels_by_snippet_ids(snippet_ids) or {}
        comparison = build_founder_comparison(
            picked,
            labels,
            rater_id=getattr(request, "user_id", None),
        )
        return jsonify({
            "session_id": str(session_id),
            **comparison,
            "note": "Machine is a proposal, not a quorum vote.",
        }), 200
    except Exception as error:
        logger.warning(
            "confidence comparison failed sid=%s: %s", session_id, error,
        )
        return jsonify({
            "code": "SERVER_ERROR",
            "error": "could not load the comparison",
        }), 500


@v2_bp.route("/coach/arcs/<arc_id>/ab-pairs", methods=["GET"])
@require_admin_or_coach
def v2_coach_ab_pairs(arc_id):
    """BLINDED A/B — the same slide, two takes, no labels (founder 2026-08-11).

    The corpus that unblocks piece (b): power_score's DELIVERY term is
    ranking-inert until the composite is anchored against blinded human
    ratings, and line-level cross-take selection is disabled until a
    fuzzy-alignment spike can run on real multi-take arcs. One coach act
    produces both — a preference to correlate against, and a matched
    cross-take pair.

    THE PAYLOAD CARRIES NO TAKE IDENTITY. Each side is words + audio +
    timing and nothing else: no session id, no take index, no timestamp. A
    rater who can tell which take is later is rating a story about
    improvement rather than a delivery, so the blinding is enforced in
    services/ab_slide_pairs.py rather than trusted to the UI.

    Already-rated pairs are dropped: `?all=1` keeps them (re-rating is
    legitimate — it is how intra-rater reliability gets measured — but the
    queue should not serve the same pair forever).

      200 { arc_id, pairs: [{pair_id, slide_index, slide_title,
                             left:{…}, right:{…}}], rated_count }
      200 { pairs: [], reason } — fewer than two takes, or no deck
    """
    try:
        from services.ab_slide_pairs import build_pairs
        from services.audio_ref_resolver import resolve_playable_ref
        from services.slide_selection import spoken_arc_sessions
        sessions = spoken_arc_sessions(db.takes.get_arc_sessions(arc_id) or [])
        if len(sessions) < 2:
            return jsonify({"arc_id": arc_id, "pairs": [],
                            "reason": "needs at least two spoken takes"}), 200
        takes, slides = [], []
        for sess in sessions:
            sid = str(sess.get("id") or "")
            if not sid:
                continue
            row = db.v2_get_session_by_id(sid) or {}
            ctx = row.get("intake_context")
            ctx = ctx if isinstance(ctx, dict) else {}
            if not slides:
                slides = ctx.get("slides") or []
            takes.append({
                "session_id": sid,
                "slide_transcripts": db.takes.get_session_slide_transcripts(sid),
                "audio_ref": resolve_playable_ref(row.get("audio_path")),
            })
        if not slides:
            return jsonify({"arc_id": arc_id, "pairs": [],
                            "reason": "no deck on this arc"}), 200
        pairs = build_pairs(takes, slides)
        rated = db.list_slide_ab_verdicts(arc_id) or []
        if (request.args.get("all") or "") not in ("1", "true", "yes"):
            from services.ab_slide_pairs import pair_id as _pid
            seen = {
                _pid(r.get("slide_index") or 0,
                     r.get("session_left") or "", r.get("session_right") or "")
                for r in rated if isinstance(r, dict)
            }
            pairs = [p for p in pairs if p["pair_id"] not in seen]
        return jsonify({"arc_id": arc_id, "pairs": pairs,
                        "rated_count": len(rated)}), 200
    except Exception as e:
        logger.error("coach/ab-pairs failed arc=%s err=%s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to build the comparison queue"}), 500


@v2_bp.route("/coach/arcs/<arc_id>/ab-verdict", methods=["PUT"])
@require_admin_or_coach
def v2_coach_ab_verdict(arc_id):
    """One blinded judgment: { pair_id, verdict: 'left'|'right'|'tie' }.

    The server resolves the blinded side back to a real session — the FE
    never learns which take it picked, so a rater cannot drift toward "the
    later one" over a session of ratings.

    A TIE IS A VERDICT, stored with a NULL winner: "a human looked and could
    not separate them" is exactly the signal that tells the composite where
    NOT to claim a difference. Absence of a row means nobody looked.

    Both texts ride along. A pair is only alignment ground truth if you can
    still read both sides of it, and the document reassembles on every take.

    200 { saved, slide_index, verdict } · 400 · 500
    """
    body = request.get_json(silent=True) or {}
    try:
        from services.ab_slide_pairs import resolve_verdict
        resolved = resolve_verdict(body.get("pair_id"), body.get("verdict"))
        if resolved is None:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "pair_id: unreadable, or verdict not left/right/tie",
            }), 400
        # The words as the rater read them, pulled from the same persisted
        # per-slide transcript the pair was built from.
        def _text(session_id):
            for t in (db.takes.get_session_slide_transcripts(session_id) or []):
                if isinstance(t, dict) and t.get("index") == resolved["slide_index"]:
                    return t.get("transcript") or ""
            return None
        saved = db.record_slide_ab_verdict(
            arc_id=arc_id,
            slide_index=resolved["slide_index"],
            session_left=resolved["session_left"],
            session_right=resolved["session_right"],
            verdict=resolved["verdict"],
            winner_session_id=resolved["winner_session_id"],
            left_text=_text(resolved["session_left"]),
            right_text=_text(resolved["session_right"]),
            rated_by=str(getattr(request, "user_id", "") or "") or None,
        )
        return jsonify({"saved": bool(saved),
                        "slide_index": resolved["slide_index"],
                        "verdict": resolved["verdict"]}), 200
    except Exception as e:
        logger.error("coach/ab-verdict failed arc=%s err=%s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the comparison"}), 500


@v2_bp.route("/coach/snippets/<snippet_id>/slide", methods=["PUT"])
@require_admin_or_coach
def v2_coach_put_snippet_slide(snippet_id):
    """THE WORD→SLIDE GROUND TRUTH (founder 2026-08-11). The coach says which
    slide was ON SCREEN while this snippet was spoken.

        { slide_index: int }   this snippet was delivered on slide N
        { slide_index: null }  withdraw a correction — the pipeline was right

    WHAT THIS IS FOR. The pipeline buckets words by the tap timeline and
    nothing has ever checked it against a human; services/slide_boundary_
    metrics.py can only report exposure and impact, never accuracy, and says
    so in its own header — the missing piece is exactly this row. Every
    correction is also one (speech window, slide) training pair, which is the
    corpus any learned aligner would need before it could be trained at all.

    WHAT IT IS NOT. Not "these words are about slide N". Correctness here is
    what the audience was looking at, so a speaker who ran ahead of their own
    deck is not a bucketing error. The FE copy says so; this docstring is the
    contract behind it, because a corpus that mixes the two teaches the
    opposite of the thing we measure.

    The index is validated against THIS session's deck: a correction pointing
    at a slide the deck does not have is a corrupt label, and it fails here
    rather than landing in the corpus.

    Append-only — the row is inserted, never upserted, so the trail of what
    the pipeline said and what the human said instead survives.

    200 { saved, snippet_id, slide_index } · 400 · 404 · 500
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "snippet_id must be a valid UUID"}), 400
    body = request.get_json(silent=True) or {}
    if "slide_index" not in body:
        return jsonify({"code": "INVALID_INPUT",
                        "error": "slide_index: required (null to withdraw)"}), 400
    raw = body.get("slide_index")
    if raw is not None and (isinstance(raw, bool) or not isinstance(raw, int)):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "slide_index: must be an integer or null"}), 400
    try:
        snip = db.get_snippet_by_id(snippet_id)
        if not snip or not snip.get("session_id"):
            return jsonify({"code": "NOT_FOUND",
                            "error": "snippet not found"}), 404
        session_id = str(snip.get("session_id"))
        session = db.v2_get_session_by_id(session_id) or {}
        ctx = session.get("intake_context")
        ctx = ctx if isinstance(ctx, dict) else {}
        slides = ctx.get("slides") or []
        if raw is not None and not (0 <= raw < len(slides)):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": (f"slide_index: out of range for this deck "
                          f"({len(slides)} slide(s))"),
            }), 400
        # What the pipeline says right now, recorded beside the correction:
        # without it the corpus knows where the words belong but never how
        # far off the timeline was, and the size of the miss IS the
        # measurement.
        was = None
        try:
            from services.slide_alignment import slide_for_snippet
            was = slide_for_snippet(
                snip, ctx.get("slide_advances") or [], slides
            ) if slides else None
        except Exception:
            was = None
        saved = db.record_snippet_slide_correction(
            session_id=session_id,
            snippet_id=snippet_id,
            slide_index=raw,
            was_slide_index=was,
            corrected_by=str(getattr(request, "user_id", "") or "") or None,
        )
        return jsonify({"saved": bool(saved), "snippet_id": snippet_id,
                        "slide_index": raw}), 200
    except Exception as e:
        logger.error("coach/snippet-slide failed snippet=%s err=%s",
                     snippet_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to save the slide correction"}), 500


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

    Re-labelling normally REPLACES this rater's row (the corpus wants their
    current view); other raters' rows are untouched, so multi-rater agreement
    stays possible. A technical ``audio_unclear`` answer is the exception:
    that artifact must go to a different eligible human and the first rater
    cannot turn a second listen into a falsely independent answer.

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
    request_idempotency_key = (
        body.get("idempotency_key") if isinstance(body, dict) else None
    )
    is_rereview = body.get("re_review") is True

    from services.state_ratings import resolve_lane, validate_rating

    legacy_intensity = None
    if "confident" in body:
        # Legacy shape. Validate it on the OLD validator so its strictness is
        # unchanged, then translate — the translation stays visible here in
        # one place rather than buried in a validator that would then appear
        # to accept two instruments.
        from services.confidence_labels import validate_confidence_label
        legacy, err = validate_confidence_label(body)
        if err:
            return jsonify({"code": "INVALID_INPUT", "error": err}), 400
        legacy_intensity = legacy.get("intensity")
        body = {
            "state_id": "confidence",
            "value": "yes" if legacy["confident"] else "no",
            "note": legacy.get("note"),
        }

    try:
        snip = db.get_snippet_by_id(snippet_id)
        if not snip:
            return jsonify({"code": "NOT_FOUND",
                            "error": "snippet not found"}), 404
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

        # RULE 2 (founder 2026-08-11) — the owner is not a peer, and that is
        # about WHOSE CLIP it is, not which surface rated it. A coach rating a
        # session they own writes lane='coach' and is still a self-report, so
        # ownership is compared explicitly here rather than read off the lane.
        rater_id = getattr(request, "user_id", None)
        self_report = bool(
            rater_id and sess and str(sess.get("user_id")) == str(rater_id))
        from services.label_quorum import (
            machine_proposal, rater_submission_access,
        )
        existing_by_snippet = db.get_confidence_labels_by_snippet_ids(
            [snippet_id]) or {}
        existing_labels = existing_by_snippet.get(str(snippet_id), [])
        access = rater_submission_access(existing_labels, rater_id)
        if not access["allowed"]:
            if access["outcome"] == "fresh_rater_required":
                return jsonify({
                    "code": "FRESH_RATER_REQUIRED",
                    "error": "This clip is waiting for another eligible rater.",
                }), 409
            if access["outcome"] == "audio_quarantined":
                return jsonify({
                    "code": "AUDIO_QUARANTINED",
                    "error": "Independent raters reported that this audio cannot be judged.",
                }), 409
            if not is_rereview:
                return jsonify({
                    "code": "RATING_CLOSED",
                    "error": "This clip no longer needs another blind rating.",
                }), 409
        saved = db.upsert_state_rating(
            snippet_id=snippet_id, row=row,
            rater_id=rater_id,
            session_id=session_id, lane=lane,
            intensity=legacy_intensity,
            self_report=self_report,
            # RULE 1 — the proposal that routed this clip here, stamped
            # server-side into its own column. The coach never saw it (BLIND
            # COACH / I1); it is stored so "which prediction did this human
            # disagree with" stays answerable, and it is never a vote.
            machine_value=machine_proposal(snip),
        )
        if not saved:
            return jsonify({
                "code": "SERVER_ERROR",
                "error": "could not save the rating (run "
                         "migrations/add_state_generic_ratings.sql)",
            }), 500
        value = row["value"]
        # Append-only canonical shadow. The legacy current-answer row remains
        # the live read during parity; this row preserves the original blind
        # judgment and any later reconsideration as a superseding revision.
        # The lookup reads evidence only—never owner/machine/peer answers.
        try:
            from services.feedback_data_contract import (
                TAXONOMY_VERSION,
                blind_packet_hash,
                content_hash,
            )

            canonical_evidence = db.ideal_text.get_canonical_confidence_evidence(
                take_id=str(session_id), snippet_id=str(snippet_id),
            )
            if canonical_evidence is not None:
                packet_hash = blind_packet_hash(canonical_evidence)
                supplied_key = request_idempotency_key
                canonical_key = (
                    supplied_key.strip()
                    if isinstance(supplied_key, str) and supplied_key.strip()
                    else "coach-confidence:" + content_hash({
                        "request_id": str(uuid.uuid4()),
                        "take_id": str(session_id),
                        "snippet_id": str(snippet_id),
                        "coach_id": str(rater_id),
                        "value": value,
                    })
                )
                canonical_assignment = (
                    db.assign_canonical_coach_confidence_evidence(
                        take_id=str(session_id),
                        evidence_span_id=str(
                            canonical_evidence["evidence_span_id"]),
                        coach_id=str(rater_id),
                        blind_packet_hash=str(packet_hash),
                        assignment_reason="blind_confidence_queue",
                        idempotency_key=(
                            "coach-assignment:" + canonical_key),
                    ) if packet_hash else None
                )
                canonical_label = (
                    db.record_canonical_coach_confidence_judgment(
                        evidence_span_id=str(
                            canonical_evidence["evidence_span_id"]),
                        coach_id=str(rater_id),
                        value=value,
                        taxonomy_version=TAXONOMY_VERSION,
                        blind_packet_hash=str(packet_hash),
                        idempotency_key=canonical_key,
                    ) if canonical_assignment is not None else None
                )
                if canonical_label is None:
                    logger.warning(
                        "canonical coach label dual-write missing "
                        "take=%s snippet=%s", session_id, snippet_id,
                    )
        except Exception as canonical_error:
            logger.warning(
                "canonical coach label dual-write failed take=%s "
                "snippet=%s: %s", session_id, snippet_id, canonical_error,
            )
        if lane == "coach" and not self_report and sess and sess.get("user_id"):
            from services.confidence_review_policy import (
                reconcile_confidence_review,
            )
            reconcile_confidence_review(
                db, snippet_id=snippet_id, session=sess,
                owner_user_id=sess.get("user_id"), coach_value=value,
                coach_note=row.get("note"), coach_write=True,
                is_rereview=is_rereview)
        # BLINDNESS RELEASE. This read occurs only after the independent
        # judgment above was durably written. Queue/read payloads never call
        # it, so the coach cannot see the owner label or machine proposal
        # before committing. The original judgment remains in label_revision;
        # a later reconsideration is another revision, never a replacement.
        _owner_reports = db.list_take_feedback_self_reports_by_snippet(
            str(snippet_id))
        _owner_report = next((
            report for report in reversed(_owner_reports)
            if isinstance(report, dict)
            and report.get("feedback_family") == "confident_voice"
        ), None)
        return jsonify({
            "saved": True, "snippet_id": snippet_id,
            "state_id": row["state_id"], "value": value,
            "unrateable": row["unrateable"], "lane": lane,
            # Legacy fields, derived — the current FE reads these.
            "confident": (True if value == "yes"
                          else False if value == "no" else None),
            "intensity": legacy_intensity,
            # Exact words are released only by this successful write. Blind
            # queue reads redact them until the same rater has a saved row.
            "transcript": (snip.get("transcript")
                           or snip.get("transcript_excerpt") or ""),
            "owner_self_report": (
                {
                    "value": _owner_report.get("response"),
                    "created_at": _owner_report.get("created_at"),
                    "provenance": "user_self_report",
                } if _owner_report else None
            ),
            "machine_value": machine_proposal(snip),
        }), 200
    except Exception as e:
        logger.warning("confidence rating failed snip=%s: %s", snippet_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not save the rating"}), 500


@v2_bp.route("/coach/snippets/<snippet_id>/star-text", methods=["PUT"])
@require_admin_or_coach
def v2_coach_put_star_text(snippet_id):
    """The coach's corrected wording for ONE fired star (founder 2026-07-28)
    — "review how the comment was written", the say-it-stronger twin pattern
    applied to moment suggestions.

    Body (FULL correction state — the body IS the state, an omitted or null
    field reverts that part to the machine draft):
        { "why": "…" | null, "replacement_text": "…" | null }

    The machine's draft columns are never touched (the (draft, final) pair is
    the correction corpus). Every reader folds final-over-draft at the DB
    reader, so the student sees the coach's wording immediately (L1: no row
    mutation of the draft). Strings pass the SAME AC-9 qualitative guard as
    generation; a guard violation is a loud 400, never a silent null.

    The pair enters admin_annotation_events when the coach KEEPS the star
    (the verdict route above) — edit first, then keep.

    200 { saved, snippet_id, why, replacement_text }   // the correction state
    400 · 404 · 500
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "snippet_id must be a valid UUID"}), 400
    body = request.get_json(silent=True) or {}

    from services.star_verdicts import validate_star_text

    row, err = validate_star_text(body)
    if err:
        return jsonify({"code": "INVALID_INPUT", "error": err}), 400

    try:
        snip = db.get_snippet_by_id(snippet_id)
        if not snip:
            return jsonify({"code": "NOT_FOUND",
                            "error": "snippet not found"}), 404
        saved = db.set_moment_suggestion_final(
            str(snippet_id),
            why_final=row["why"],
            replacement_text_final=row["replacement_text"],
            edited_by=getattr(request, "user_id", None),
        )
        if not saved:
            return jsonify({
                "code": "SERVER_ERROR",
                "error": "could not save star text (run "
                         "migrations/add_moment_suggestion_final.sql)",
            }), 500
        return jsonify({"saved": True, "snippet_id": snippet_id,
                        "why": row["why"],
                        "replacement_text": row["replacement_text"]}), 200
    except Exception as e:
        logger.warning("v2_coach_put_star_text failed snip=%s: %s",
                       snippet_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not save star text"}), 500


# The /coach/arc/<id>/publish ALIAS is RETIRED (FE handoff 2026-07-17):
# the FE relay now targets /publish-analysis directly (their commit
# 63be223, FE-4). History: the alias briefly restored the OLD #186 path
# (deleted in #195) after the FE's publish button 404'd on its first-ever
# reachable click.
@v2_bp.route("/coach/arc/<arc_id>/publish-analysis", methods=["POST"])
@require_admin_or_coach
def v2_coach_publish_analysis(arc_id):
    """Publish complete saved take snapshots as one atomic revision batch."""
    try:
        sessions = db.takes.get_arc_sessions(arc_id)
        if not sessions:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        spoken, _reads = _spoken_takes_and_reads(sessions)
        if not spoken:
            return jsonify({"code": "NOTHING_TO_PUBLISH",
                            "error": "No recordings to publish yet."}), 409

        spoken_ids = {str(row.get("id")) for row in spoken if row.get("id")}
        body = request.get_json(silent=True) or {}
        reviews = body.get("reviews")
        if not isinstance(reviews, list) or not reviews:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "reviews must contain at least one complete saved take",
            }), 400
        for payload in reviews:
            if not isinstance(payload, dict):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "reviews entries must be objects",
                }), 400
            if str(payload.get("session_id") or "") not in spoken_ids:
                return jsonify({
                    "code": "TAKE_SCOPE_MISMATCH",
                    "error": "Every published take must belong to this project",
                }), 422

        from routes.v2.canonical_publish import publish_complete_reviews

        response, status = publish_complete_reviews(
            reviews,
            actor_user_id=str(request.user_id),
            admin_override_reason=body.get("admin_override_reason"),
        )
        if status != 200:
            return response, status
        published = response.get_json().get("takes") or []
        delivered_at = max(
            (str(row.get("published_at") or "") for row in published),
            default="",
        ) or datetime.now(timezone.utc).isoformat()
        return jsonify({
            "arc_id": arc_id,
            "takes_published": len(published),
            "takes_skipped": len(spoken_ids) - len(published),
            "delivered_at": delivered_at,
            "takes": published,
        }), 200
    except Exception as e:
        logger.error("publish-analysis failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to publish the analysis",
        }), 500


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
