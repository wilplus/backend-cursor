"""The willab coach review domain: /v2/coach/* (34 routes).

The coach queue, per-session review, snippet lanes/stars/confidence, the
coach-owned ideal-text correction surface, training imports, audits and
breakthrough video. Moved verbatim out of ``routes/v2_routes.py`` (god-file
split, phase 2) -- route bodies are byte-identical to what was there before.

Routes register on the SAME ``v2_bp`` object, so endpoint names
("v2.<view_func>") and the URL map are unchanged by the split.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import sentry_sdk
from flask import jsonify, request
from werkzeug.utils import secure_filename

from config import Config
from routes.admin import require_admin_or_coach
from routes.v2.arcs import _spoken_takes_and_reads
from routes.v2.blueprint import v2_bp
from services.rate_limits import heavy_limit, llm_limit, whisper_limit
# Module scope on purpose: `except DeadlineExceeded` in the upload routes
# must resolve even when the failure happens BEFORE the try body reaches
# its own imports — otherwise the handler NameErrors while handling.
from services.upload_guard import (
    DeadlineExceeded, UploadTooLarge, deadline_for, read_capped,
)
from utils.errors import safe_error
from routes.v2.common import (
    _COACH_PSEUDONYM_SALT,
    _LAB_MAX_AUDIO_MB,
    _PRESENTATION_MAX_MB,
    _VIDEO_UPLOAD_EXTS,
    _is_valid_uuid,
)
from services.db import db

logger = logging.getLogger(__name__)
config = Config()


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
    h = int(hashlib.sha256(
        (_COACH_PSEUDONYM_SALT + str(user_id)).encode("utf-8")
    ).hexdigest(), 16)
    adj = _COACH_PSEUDONYM_ADJ[(h // len(_COACH_PSEUDONYM_ANIMAL)) % len(_COACH_PSEUDONYM_ADJ)]
    animal = _COACH_PSEUDONYM_ANIMAL[h % len(_COACH_PSEUDONYM_ANIMAL)]
    return f"{adj} {animal}"


def _coach_state_map(session_id, rater_id=None):
    """Per-snippet coach_state, folding the lanes → the resume read.
    direction_label <- training_labels (PRIVATE, retired); note/tag/surfaced
    <- coach_snippet_drafts (USER). THIS is what makes note/tag/surfaced
    round-trip on reopen (not just the label — the bug this layer fixes).

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
    ratings = (db.get_own_state_ratings_for_session(session_id, rater_id)
               if rater_id else {})
    out = {}
    for sid in set(labels) | set(drafts) | set(ratings):
        d = drafts.get(sid) or {}
        r = ratings.get(sid) or {}
        out[sid] = {
            "direction_label": labels.get(sid),
            "note": (d.get("note") or ""),
            "tag": d.get("tag"),
            "surfaced": bool(d.get("surfaced")),
            "breakthrough_video_ref": d.get("breakthrough_video_ref"),
            "transcript_corrected": d.get("transcript_corrected"),
            # This coach's own ternary answer, or None/False when they have
            # not answered yet. `unrateable` is separate from `value` here for
            # the same reason it is separate everywhere else: an abstention is
            # not a third answer.
            "rating_value": r.get("value"),
            "rating_unrateable": bool(r.get("unrateable")),
        }
    return out


def _coach_state_for(session_id, snippet_id):
    """One snippet's coach_state (default-empty when nothing authored yet)."""
    return _coach_state_map(session_id).get(str(snippet_id), {
        "direction_label": None, "note": "", "tag": None, "surfaced": False,
        "breakthrough_video_ref": None, "transcript_corrected": None,
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
        for r in (db.get_read_sessions_for(session_id) or []):
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
        _ideal_ready_arcs = []
        for _aid in {s.get("arc_id") for s in sessions if s.get("arc_id")}:
            try:
                _row = db.get_coach_arc_ideal_text(_aid)
                if _row and (_row.get("text") or "").strip() \
                        and not _row.get("approved_at"):
                    _ideal_ready_arcs.append(str(_aid))
            except Exception:
                continue
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


@v2_bp.route("/coach/annotation-uploads", methods=["POST"])
@whisper_limit
@require_admin_or_coach
def v2_coach_annotation_upload():
    """ANNOTATION MODE (Stage 4 / T4, founder 2026-07-23): the coach
    uploads an audio file and gets it chopped straight into labelable
    snippets — WITHOUT any ideal-text assembly — to bank key-moment
    annotations toward the 1,000-annotation goal.

    Reuses the shipped machinery (guardrail: no new chunker, no new UI):
      * the same ≤200-char punctuation-aware cutter (process_lab_recording);
      * the same coach review queue + snippet-review UI
        (source='audit_upload' → send_lab_recording_to_coach flips it to
        pending_admin_review; the queue row carries annotation_mode=true
        so the FE labels it).
    NO arc, NO version, NO master document — the assembly block the
    student POST runs is simply never called here.

    Multipart: audio_file (required) · label (optional, the coach's
    reference title). Audio only — video is refused (AUDIO_ONLY).

    201 { session_id, n_snippets, annotation_mode:true } · 400 · 413 ·
    415 · 422 (no speech) · 500
    """
    try:
        if "audio_file" not in request.files:
            return jsonify({"code": "AUDIO_FILE_REQUIRED",
                            "error": "audio_file is required"}), 400
        audio_file = request.files.get("audio_file")
        max_bytes = _LAB_MAX_AUDIO_MB * 1024 * 1024
        if (request.content_length or 0) > max_bytes:
            return jsonify({"code": "FILE_TOO_LARGE",
                            "error": f"exceeds {_LAB_MAX_AUDIO_MB}MB"}), 413
        # Bounded read + wall-clock budget — same guards as the student
        # lab POST (P0 audit 2026-08-03).
        deadline = deadline_for("annotation-upload")
        try:
            file_bytes = read_capped(audio_file, max_bytes)
        except UploadTooLarge:
            return jsonify({"code": "FILE_TOO_LARGE",
                            "error": f"exceeds {_LAB_MAX_AUDIO_MB}MB"}), 413
        if not file_bytes:
            return jsonify({"code": "INVALID_INPUT",
                            "error": "audio_file is empty"}), 400
        # Audio only (guardrail: keep video blocked) — same gate as the
        # student POST.
        _up_ct = (audio_file.mimetype or "").strip().lower()
        _up_ext = os.path.splitext(
            audio_file.filename or "")[1].lower().lstrip(".")
        if _up_ct.startswith("video/") or _up_ext in _VIDEO_UPLOAD_EXTS:
            return jsonify({
                "code": "AUDIO_ONLY",
                "error": "Upload an audio file — video isn't supported.",
            }), 415

        # Min-content gate — a silent file has nothing to annotate.
        from services.min_content_gate import evaluate_min_content_bytes
        gate = evaluate_min_content_bytes(file_bytes)
        if not gate["ok"]:
            return jsonify({
                "code": "RECORDING_REJECTED",
                "error": "No speech detected — try another file.",
                "gate": gate,
            }), 422

        coach_id = getattr(request, "user_id", None)
        session_id = str(uuid.uuid4())
        recording_id = str(uuid.uuid4())
        ext = os.path.splitext(audio_file.filename or "")[1] or ".webm"
        key = f"willab_annotation/{session_id}/audio_{uuid.uuid4().hex}{ext}"
        content_type = (audio_file.mimetype
                        or "audio/webm").strip() or "audio/webm"
        # Coach-uploaded, but still a person's recorded voice — same
        # bucket as student takes, not the coach media bucket.
        from services.lab_audio_storage import (
            lab_audio_public_url, put_lab_audio_bytes,
        )
        deadline.check("store")
        try:
            bucket = put_lab_audio_bytes(key, file_bytes, content_type)
        except Exception as _up_err:
            logger.error("annotation upload: store failed: %s", _up_err,
                         exc_info=True)
            return jsonify({"code": "V2_ERROR",
                            "error": "Failed to store audio"}), 500
        parent_url = lab_audio_public_url(key) or f"s3://{bucket}/{key}"

        # The RECORDINGS row — REQUIRED before any snippet insert:
        # charisma_snippets.recording_id is a NOT NULL FK, and
        # process_lab_recording inserts one snippet per piece against it.
        # Without this row every insert fails the FK SILENTLY (bulk +
        # per-row both swallow) → zero snippets → the feature banks
        # nothing while returning 201 (review 2026-07-23; the student
        # path creates this row too). user_id stays NULL — an annotation
        # upload is training data, not a student's speaker baseline; the
        # coach is recorded in intake_context, NOT as the session owner,
        # so they never appear as a phantom student in the roster.
        _rec_payload = {
            "id": recording_id, "user_id": None,
            "session_v2_id": session_id,
            "storage_path": key, "audio_url": parent_url,
            "duration": gate.get("duration_sec"),
            "recording_origin": "willab_lab",
        }
        try:
            db.create_recording(_rec_payload)
        except Exception as _ce:
            _e = str(_ce).lower()
            if "recording_origin" in _e or "pgrst204" in _e:
                db.create_recording({k: v for k, v in _rec_payload.items()
                                     if k != "recording_origin"})
            else:
                logger.error("annotation upload: create_recording failed: "
                             "%s", _ce, exc_info=True)
                return jsonify({"code": "V2_ERROR",
                                "error": "Failed to store audio"}), 500

        # The session: source='audit_upload' (queue entry) + the
        # annotation_mode marker; user_id stays NULL (see above); NO arc.
        _label = (request.form.get("label") or "").strip()[:200] or None
        if not db.v2_get_session_by_id(session_id):
            db.v2_create_guest_session(session_id)
        db.set_session_source(session_id, "audit_upload")
        db.set_session_intake_context(session_id, {
            "topic": _label or "Annotation",
            "annotation_mode": True,
            "uploaded_by_coach": str(coach_id) if coach_id else None,
        })
        try:
            db.v2_set_guest_session_recording(session_id, recording_id)
        except Exception as _le:
            logger.warning("annotation upload: link recording failed "
                           "sid=%s: %s (non-fatal)", session_id, _le)

        # Snippets ONLY — the same cutter, no assembly (the student
        # POST's arc/ideal-text block is never invoked here).
        from services.lab_recording import process_lab_recording
        deadline.check("analyze")
        readout = process_lab_recording(
            session_id=session_id,
            user_id=None,
            recording_id=recording_id,
            audio_bytes=file_bytes,
            filename=audio_file.filename or "annotation.webm",
            session_context={"topic": _label or "Annotation",
                             "annotation_mode": True},
            parent_audio_url=parent_url,
            recording_kind="spoken",
        )
        _n = len(readout.get("snippets") or [])

        # Into the coach queue — flip the status DIRECTLY (the same flip
        # send_lab_recording_to_coach performs) rather than via that
        # helper, which would also fire the student "session ready"
        # admin email on a coach self-upload (review 2026-07-23).
        try:
            db.v2_update_session_status_unscoped(
                session_id, "pending_admin_review")
        except Exception as _qe:
            logger.warning("annotation upload: queue flip failed sid=%s: "
                           "%s", session_id, _qe)

        return jsonify({"session_id": session_id, "n_snippets": _n,
                        "annotation_mode": True}), 201
    except DeadlineExceeded as de:
        logger.warning("annotation upload deadline: %s", de)
        return jsonify({
            "code": "PROCESSING_TIMEOUT",
            "error": "That upload is taking longer than expected — "
                     "it's still processing, check back shortly.",
        }), 504
    except Exception as e:
        logger.error("annotation upload failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR",
                        "error": "Failed to process the upload"}), 500


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
        rows = db.list_review_queue() or []
        out = []
        for r in rows:
            sid = r.get("id")
            ctx = r.get("intake_context") if isinstance(r.get("intake_context"), dict) else {}
            cstate = _coach_state_map(sid)
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
                "n_snippets": len(db.get_snippets_by_session(sid) or []),
                "state": _coach_session_state(r, cstate),
                "sent_at": r.get("guest_claimed_at") or r.get("created_at") or "",
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


@v2_bp.route("/coach/sessions/<session_id>", methods=["GET"])
@require_admin_or_coach
def v2_coach_get_session(session_id):
    """② Coach review session payload (FE PR #73 → /v2/coach/sessions/<id>).

    Identity-stripped (S.4): pseudonym + domain only — NO user_id / name /
    email. Per-snippet coach_state folds BOTH lanes so the coach's note / tag /
    surfaced / direction ALL resume on reopen (the round-trip the old
    label-only readout dropped).

    Moment order (founder 2026-07-24, T1 · 1.2): the take's moments are
    returned MOST-SIGNIFICANT-FIRST (key → close-to-key → least distinctive)
    via the deterministic, coach-only ``acoustic_read`` triage signal, so the
    coach assesses the significant moments before the flat ones and neither a
    hyper-positive (charisma) nor a hyper-negative (stress) extreme is buried.
    See ``services.coach_moment_order``. Coach-only, never the shadow guess
    (BLIND COACH), never the user readout (AC-9). Folded re-reads keep their
    own order, appended after the take.
    """
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT", "error": "session_id must be a UUID"}), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404

        # Readiness rig #3 — first-touch coach-time baseline: stamp when the
        # coach first OPENS this session for review (set-once). Best-effort;
        # never affects the review payload.
        try:
            db.stamp_review_opened(session_id)
        except Exception as _ro_err:
            logger.warning("coach/get-session: review_opened stamp failed sid=%s: %s",
                           session_id, _ro_err)

        from services.lab_recording import build_readout_from_session
        # include_slide_scores=True → coach gets Stickiness #2 (per-snippet
        # on-slide-ness + the per-slide coverage ledger). Coach-only (AC-9).
        readout = build_readout_from_session(session_id, include_slide_scores=True)
        cstate = _coach_state_map(
            session_id, rater_id=getattr(request, "user_id", None))
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
        def _shape_snip(snip, cstate_map, owning_sid, kind_default=None):
            _sid = str(snip.get("id"))
            _coach_state = dict(cstate_map.get(_sid, {
                "direction_label": None, "note": "", "tag": None, "surfaced": False,
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
                # Stress↔charisma potentiometer + outside-normal-range triage
                # flag (founder 2026-07-14) — the coach's breakthrough-hunt
                # signal (`outside_normal_range` = "potentially a key moment").
                # Deterministic acoustic-only, COACH-ONLY (the user readout
                # never carries it). Present on pieces rows.
                "acoustic_read": snip.get("acoustic_read"),
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
            }

        snippets = [
            _shape_snip(s, cstate, str(session_id))
            for s in (readout.get("snippets") or [])
        ]
        # KEY MOMENTS FIRST (founder 2026-07-24, T1 · 1.2): order THIS take's
        # moments most-significant-first (key → close-to-key → least
        # distinctive) so the coach lands on the significant parts before the
        # flat ones. Deterministic acoustic_read only (never the shadow guess —
        # BLIND COACH); reorders the coach packet only (never the user readout
        # — AC-9). The re-reads fold in AFTER, keeping their own order (their
        # clock restarts at 0, so they are never cross-sorted with the take).
        from services.coach_moment_order import (
            order_coach_moments_by_significance,
        )
        snippets = order_coach_moments_by_significance(snippets)

        # Fold the paired mid-take RE-READS into this take's packet (founder
        # 2026-07-16: "re-reads are part of the take, revealed by clicking
        # next, never separate items"). Appended AFTER the parent's pieces —
        # NEVER sorted across sessions by start_offset_ms (the read's clock
        # restarts at 0). Best-effort: a fold hiccup degrades to the parent
        # take alone (LIVE LOOP).
        _shadow_groups = [(str(session_id), list(snippets))]
        read_sessions = []
        try:
            read_sessions = [
                r for r in (db.get_read_sessions_for(session_id) or [])
                if isinstance(r, dict) and r.get("id")
            ]
        except Exception as _rl_err:
            logger.warning("coach/get-session: read lookup failed sid=%s: %s",
                           session_id, _rl_err)
        for _r in read_sessions:
            _rid = str(_r.get("id"))
            try:
                _r_readout = build_readout_from_session(
                    _rid, include_slide_scores=True)
                _r_cstate = _coach_state_map(_rid)
                _r_snips = [
                    _shape_snip(s, _r_cstate, _rid, "read")
                    for s in (_r_readout.get("snippets") or [])
                ]
            except Exception as _rf_err:
                logger.warning(
                    "coach/get-session: read fold failed sid=%s read=%s: %s",
                    session_id, _rid, _rf_err)
                continue
            try:
                db.stamp_review_opened(_rid)
            except Exception:
                pass
            snippets.extend(_r_snips)
            _shadow_groups.append((_rid, _r_snips))
        # One continuous "next" sequence across the merged packet.
        for _i, _s in enumerate(snippets):
            _s["index"] = _i

        # Phase 4 / Prompt 1 (B3) — SHADOW direction predictions for this
        # session's reviewed snippets. Fire-and-forget; logged to
        # shadow_predictions, NEVER in this packet, influences nothing.
        # Dispatched per OWNING session — a read's snippets must log under
        # the read's own session id, never the spoken take's.
        try:
            from services.learning_serve import dispatch_shadow_predictions
            for _own_sid, _grp in _shadow_groups:
                dispatch_shadow_predictions(_own_sid, _grp)
        except Exception as _shadow_err:
            logger.warning("coach/get-session: shadow dispatch failed: %s", _shadow_err)

        ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
        insights = session.get("insights_payload") if isinstance(session.get("insights_payload"), dict) else {}
        from services.feelings import shape_coach_feelings
        # "Ideal text ready to review" (founder 2026-07-15) — a persisted,
        # unapproved machine draft exists for this session's arc.
        _arc_ideal_ready = False
        if session.get("arc_id"):
            try:
                _it_row = db.get_coach_arc_ideal_text(session.get("arc_id"))
                _arc_ideal_ready = bool(
                    _it_row and (_it_row.get("text") or "").strip()
                    and not _it_row.get("approved_at"))
            except Exception:
                _arc_ideal_ready = False
        # Founder 2026-07-15: saved = REVIEWED (three explicit states beside
        # the legacy `state`; additive, FE maps safe-ahead).
        if session.get("results_published_at"):
            _review_state = "delivered"
        elif session.get("coach_feedback_saved_at"):
            _review_state = "reviewed"
        else:
            _review_state = "to_review"
        return jsonify({
            "session_id": session_id,
            "pseudonym": _coach_pseudonym(session.get("user_id")),
            "domain": (ctx or {}).get("domain") or "",
            "topic": (ctx or {}).get("topic") or "",
            # The user's pre-recording named emotion (F2 handoff §2) —
            # their own self-report, founder-decided coach-visible (not a
            # machine guess; blind-coach untouched). The KEY only: its
            # threat/challenge bucket is internal and never serialized
            # (CONSTRUCT fence).
            "named_emotion": (ctx or {}).get("named_emotion"),
            "sent_at": session.get("guest_claimed_at") or session.get("created_at") or "",
            "state": _coach_session_state(session, cstate),
            "review_state": _review_state,
            "arc_id": session.get("arc_id"),
            "arc_ideal_ready": _arc_ideal_ready,
            # Folded mid-take re-reads (founder 2026-07-16): their snippets
            # ride in snippets[] after the parent's, each stamped with its
            # owning take_session_id + recording_kind='read'.
            "has_reread": bool(read_sessions),
            "read_session_ids": [str(r.get("id")) for r in read_sessions],
            # Per-read tags (founder 2026-07-20): an ideal-text re-read
            # carries read_target='ideal_text' + ideal_version in its
            # session_context → the coach UI labels it "Re-read of ideal
            # text vN". Additive beside read_session_ids; per-take re-reads
            # simply carry nulls. Coach-only surface.
            "reads": [{
                "session_id": str(r.get("id")),
                "created_at": r.get("created_at"),
                "read_target": (r.get("intake_context") or {}).get(
                    "read_target") if isinstance(
                    r.get("intake_context"), dict) else None,
                "ideal_version": (r.get("intake_context") or {}).get(
                    "ideal_version") if isinstance(
                    r.get("intake_context"), dict) else None,
            } for r in read_sessions],
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
            # Pre-take priming manipulation (founder 2026-07-13) — which framing
            # this take was recorded under (threat/challenge/balanced). Coach-
            # only, from the session row; never user-facing (AC-9 — a research
            # manipulation label, not user content). Null on older/unprimed takes.
            "priming_condition": session.get("priming_condition"),
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
    Split-sink §2 unchanged: label → PRIVATE training_labels; note/tag/
    surfaced/when/examples/transcript_corrected → USER coach_snippet_drafts.
    """
    from services.training_labels import (
        VALID_VALUES, SCHEMA_VERSION, derive_override_flags,
    )
    from services.insights_payload import VALID_TAGS

    # ── PRIVATE lane — direction label (training_labels). ──
    # `direction_label` (str | null). null CLEARS; a value upserts.
    if "direction_label" in body:
        value = body["direction_label"]
        if value is None:
            db.delete_training_label(session_id, snippet_id)
        elif value in VALID_VALUES:
            # Override signal (audit fix #2a): fresh label vs revision of a
            # prior one, derived from the snippet's existing stored label.
            # Coach labels BLIND → this is coach-vs-own-prior.
            _prior_val = None
            for _r in (db.get_training_labels(session_id) or []):
                if str(_r.get("snippet_id")) == snippet_id:
                    _prior_val = _r.get("value")
                    break
            _pre_filled, _overridden = derive_override_flags(_prior_val, value)
            db.upsert_training_labels(session_id, str(request.user_id), [{
                "snippet_id": snippet_id,
                "schema_version": SCHEMA_VERSION,
                "value": value,
                "was_pre_filled": _pre_filled,
                "was_overridden": _overridden,
            }])
            # Phase 4 / Prompt 1 (B3, SHADOW) — backfill the coach's actual
            # label onto the shadow prediction + best-effort auto-retrain.
            # The new model stays status=shadow and influences NOTHING.
            try:
                from services.learning_serve import maybe_auto_retrain
                db.backfill_shadow_coach_actual(snippet_id, value)
                maybe_auto_retrain()
            except Exception as _learn_err:
                logger.warning(
                    "coach/save-snippet: shadow learn hook failed: %s",
                    _learn_err,
                )
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
    # Breakthrough video — a public URL (str | null). null/empty CLEARS.
    # The explanation text is the `note`; this stores only the video URL.
    if "breakthrough_video_ref" in body:
        bvr_raw = body.get("breakthrough_video_ref")
        if bvr_raw is not None and not isinstance(bvr_raw, str):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "breakthrough_video_ref: must be a string or null",
            }), 422
        bvr = (bvr_raw or "").strip()
        if len(bvr) > 2048:
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "breakthrough_video_ref: 2048 chars max",
            }), 422
        if bvr and not (
            bvr.startswith("https://") or bvr.startswith("http://")
        ):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "breakthrough_video_ref: must be an http(s) URL",
            }), 422
        draft_fields["breakthrough_video_ref"] = bvr or None
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
          "transcript_corrected"?: "..."  // FREE tier the instant it's saved (2026-07-06)
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

        # Bucket-tolerant read: a take may live in the lab bucket or, if
        # it predates the split, the coach bucket (P0 audit 2026-08-03).
        from services.lab_audio_storage import get_lab_audio_bytes
        try:
            audio_bytes = get_lab_audio_bytes(storage_path)
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
    persists coach_video_ref on the session; the publish contract folds it into
    insights_payload so it ships to the user with the insights. Re-upload
    overwrites (deterministic storage key).

    multipart/form-data: video_file (.mp4/.mov/.webm/.m4v).
    200 { status, session_id, video_ref } · 400/404/413/415/502
    """
    # Local import on purpose: binds at CALL time, so tests that monkeypatch
    # services.coach_video_storage attributes take effect.
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

        # Subsystem V — idempotency (retry dedupe). A re-upload of the SAME
        # record action (same key) reuses the stored take instead of creating a
        # phantom one. Best-effort: a missing table just falls through.
        _idem = (request.form.get("upload_idempotency_key") or "").strip() or None
        if _idem:
            _existing = db.get_coach_video_asset_by_idempotency_key(_idem)
            if _existing and _existing.get("video_ref"):
                db.set_session_coach_video_ref(session_id, _existing["video_ref"])
                return jsonify({
                    "status": "ok", "session_id": session_id,
                    "video_ref": _existing["video_ref"], "deduped": True,
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

        video_ref = coach_media_public_url(storage_key)
        db.set_session_coach_video_ref(session_id, video_ref)
        logger.info("coach video stored sid=%s key=%s", session_id, storage_key)

        # Subsystem V — capture the take into the training corpus (best-effort;
        # NEVER breaks the upload). take_summary's comment ("overall message")
        # only exists at publish, so comment_text_snapshot is null here and the
        # real text is captured as comment_text_at_publish later.
        try:
            from services.coach_video_capture import capture_coach_video
            capture_coach_video(
                database=db, session_id=session_id, content_type="take_summary",
                recorded_by=str(request.user_id), video_ref=video_ref,
                comment_text=None, snippet_id=None,
                device=(request.form.get("device") or None),
                source=(request.form.get("source") or None),
                duration=request.form.get("duration"),
                idempotency_key=_idem,
                video_bytes=video_bytes, filename=safe_name,
            )
        except Exception as _cap_err:
            logger.warning("coach video corpus capture failed sid=%s: %s (non-fatal)",
                           session_id, _cap_err)

        return jsonify({
            "status": "ok", "session_id": session_id, "video_ref": video_ref,
        }), 200
    except Exception as e:
        logger.error("coach/session-video failed sid=%s err=%s", session_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to store coach video"}), 500


@v2_bp.route(
    "/coach/sessions/<session_id>/snippets/<snippet_id>/breakthrough-video",
    methods=["POST"],
)
@heavy_limit
@require_admin_or_coach
def v2_coach_snippet_breakthrough_video(session_id, snippet_id):
    """Per-snippet coach BREAKTHROUGH VIDEO upload (Phase 2 of #131; founder
    2026-06-20 "upload a file in review").

    A coach attaches one short explanatory video to a breakthrough snippet
    during review. REUSES the coach video transport/storage (services/coach_
    video_storage — same bucket/path as the session feedback video; no new
    infra). Stores the file, persists the public URL on the snippet's DRAFT
    (coach_snippet_drafts.breakthrough_video_ref); at publish the contract
    folds it into insights_payload.snippet_notes and build_readout_from_session
    surfaces it as the snippet's top-level breakthrough_video_ref (all wired in
    #131). The explanation TEXT is the coach note itself — this stores only the
    video. Re-upload overwrites (deterministic storage key).

    Requires migrations/add_breakthrough_video_ref_to_coach_snippet_drafts.sql.

    multipart/form-data: video_file (.mp4/.mov/.webm/.m4v).
    200 { status, session_id, snippet_id, breakthrough_video_ref }
    400 INVALID_INPUT · 404 SESSION/SNIPPET_NOT_FOUND · 413 · 415 · 502
    """
    # Local import on purpose: binds at CALL time, so tests that monkeypatch
    # services.coach_video_storage attributes take effect.
    from services.coach_video_storage import (
        coach_media_public_url, put_coach_object_bytes,
    )
    import os

    if not _is_valid_uuid(session_id) or not _is_valid_uuid(snippet_id):
        return jsonify({
            "code": "INVALID_INPUT",
            "error": "session_id and snippet_id must be UUIDs",
        }), 400
    try:
        session = db.v2_get_session_by_id(session_id)
        if not session:
            return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
        # Snippet must belong to THIS session OR one of its folded mid-take
        # re-reads (founder 2026-07-16) — the video persists under the
        # snippet's OWNING session (the draft round-trips via the read's own
        # session id in the merged packet).
        _owner_sid = _snippet_owner_map(session_id).get(snippet_id)
        if not _owner_sid:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND", "error": "Snippet not in this session",
            }), 404

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

        # Subsystem V — idempotency (retry dedupe): reuse the stored take.
        _idem = (request.form.get("upload_idempotency_key") or "").strip() or None
        if _idem:
            _existing = db.get_coach_video_asset_by_idempotency_key(_idem)
            if _existing and _existing.get("video_ref"):
                db.upsert_coach_snippet_draft(
                    _owner_sid, snippet_id,
                    {"breakthrough_video_ref": _existing["video_ref"]},
                    updated_by=str(request.user_id),
                )
                return jsonify({
                    "status": "ok", "session_id": session_id, "snippet_id": snippet_id,
                    "take_session_id": _owner_sid,
                    "breakthrough_video_ref": _existing["video_ref"], "deduped": True,
                    # Authoritative echo (founder 2026-07-17: the direction
                    # chip un-marked after an upload) — the FE writes THIS
                    # back instead of clobbering its local coach_state.
                    "coach_state": _coach_state_for(_owner_sid, snippet_id),
                }), 200

        bucket = getattr(config, "COACH_FEEDBACK_VIDEO_BUCKET", "coach_feedback_videos")
        # Subsystem V — NON-deterministic key so a re-record does NOT overwrite
        # the prior take. User-facing ref is repointed to the newest below.
        storage_key = f"coach-snippet-breakthrough/{_owner_sid}/{snippet_id}/{uuid.uuid4().hex}{ext}"
        try:
            put_coach_object_bytes(
                bucket, storage_key, video_bytes,
                video_file.content_type or "video/mp4",
            )
        except Exception as upload_err:
            logger.error(
                "breakthrough video upload failed sid=%s snip=%s err=%s",
                session_id, snippet_id, upload_err,
            )
            return jsonify({"code": "UPLOAD_FAILED", "error": "Failed to upload video to storage."}), 502

        breakthrough_video_ref = coach_media_public_url(storage_key)
        # Persist on the snippet draft (USER lane) — same field/path as the
        # publish payload's breakthrough_video_ref. Best-effort: a None return
        # means the column is missing (run the migration) — the file is stored
        # and the URL is valid; a re-upload after the migration persists it.
        saved = db.upsert_coach_snippet_draft(
            _owner_sid, snippet_id,
            {"breakthrough_video_ref": breakthrough_video_ref},
            updated_by=str(request.user_id),
        )
        # Subsystem V — capture the take into the training corpus (best-effort;
        # NEVER breaks the upload). The breakthrough comment IS the snippet note
        # (read whatever exists at record time; may be NULL if not written yet).
        try:
            from services.coach_video_capture import capture_coach_video
            _note_now = None
            for _d in (db.get_coach_snippet_drafts(_owner_sid) or []):
                if str(_d.get("snippet_id")) == snippet_id:
                    _note_now = (_d.get("note") or None)
                    break
            capture_coach_video(
                database=db, session_id=_owner_sid, content_type="breakthrough",
                recorded_by=str(request.user_id), video_ref=breakthrough_video_ref,
                comment_text=_note_now, snippet_id=snippet_id,
                device=(request.form.get("device") or None),
                source=(request.form.get("source") or None),
                duration=request.form.get("duration"),
                idempotency_key=_idem,
                video_bytes=video_bytes, filename=safe_name,
            )
        except Exception as _cap_err:
            logger.warning(
                "breakthrough video corpus capture failed sid=%s snip=%s: %s (non-fatal)",
                session_id, snippet_id, _cap_err,
            )
        if saved is None:
            logger.warning(
                "breakthrough video: draft persist returned None sid=%s snip=%s "
                "(run add_breakthrough_video_ref_to_coach_snippet_drafts.sql?)",
                session_id, snippet_id,
            )
        logger.info(
            "breakthrough video stored sid=%s snip=%s key=%s",
            session_id, snippet_id, storage_key,
        )
        return jsonify({
            "status": "ok",
            "session_id": session_id,
            "snippet_id": snippet_id,
            # The session the draft actually persists under (a folded re-read
            # snippet routes to its own session, 2026-07-16).
            "take_session_id": _owner_sid,
            "breakthrough_video_ref": breakthrough_video_ref,
            # Authoritative echo (founder 2026-07-17: the direction chip
            # un-marked after an upload) — carries the persisted
            # direction_label/note/tag/surfaced + the fresh video ref, so
            # the FE restores the chips from truth instead of clobbering
            # its local coach_state.
            "coach_state": _coach_state_for(_owner_sid, snippet_id),
        }), 200
    except Exception as e:
        logger.error(
            "coach/snippet-breakthrough-video failed sid=%s snip=%s err=%s",
            session_id, snippet_id, e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to store breakthrough video",
        }), 500


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
                "error": f"PDF is over {_PRESENTATION_MAX_MB} MB — export a lighter file and try again.",
                "limit_mb": _PRESENTATION_MAX_MB,
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


@v2_bp.route("/coach/arc/<arc_id>/best-presentation", methods=["GET"])
@require_admin_or_coach
def v2_coach_arc_best_presentation(arc_id):
    """The coach's own preview of the auto-assembled draft + their own
    corrections so far. Ungated by ownership/payment — coach-only auth is the
    gate. Response shape matches the student route, plus always-populated
    `text` regardless of coach_finalized.
    """
    try:
        from services.best_presentation import build_best_presentation
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
        from services.best_presentation import (
            TAKES_TARGET, spoken_arc_sessions,
        )
        _arc_sessions = db.get_arc_sessions(arc_id)
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

        row = db.get_coach_arc_ideal_text(arc_id)
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
        ok = db.upsert_coach_arc_ideal_text(
            arc_id, text, str(request.user_id))
        if not ok:
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
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
        sessions = db.get_arc_sessions(arc_id)
        if not sessions:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        outcome = db.verify_ideal_text(arc_id, str(request.user_id))
        if outcome is None:
            return jsonify({
                "code": "NOTHING_TO_VERIFY",
                "error": "No ideal-text version to verify yet.",
            }), 409
        row = db.get_coach_arc_ideal_text(arc_id) or {}
        version = row.get("version") or 1
        if outcome == "already":
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
        row = db.get_coach_arc_ideal_text(arc_id)
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
        ok = db.upsert_coach_arc_ideal_text(
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
                _sessions = db.get_arc_sessions(arc_id) or []
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
      snippets?: [{id, note?, tag?, surfaced?, direction?|direction_label?,
                   transcript_corrected?, ...}]   → the two-lane store, via
                  the SAME shared helper as every other door (no drift);
      labels?:   [{snippet_id, value, ...}]       → private training_labels
                  (harmless duplicate of snippets[].direction — idempotent);
      insights_payload? / overall_message? / notify_client?  → accepted and
                  IGNORED here (assembly happens at publish; persisting
                  insights_payload pre-publish would leak the coach layer to
                  the user readout, which folds it whenever present).

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

        # Founder 2026-07-16: the coach saves the MERGED packet (the take +
        # its folded mid-take re-reads) under the spoken take's path — every
        # row routes to its OWNING session (a read snippet persists under
        # the read's own session id, where all downstream readers look).
        _owners = {}
        _inline = body.get("snippets")
        _labels = body.get("labels")
        if (isinstance(_inline, list) and _inline) \
                or (isinstance(_labels, list) and _labels):
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
                if "direction" in _fields and "direction_label" not in _fields:
                    _fields["direction_label"] = _fields.pop("direction")
                _lane_err = _save_coach_snippet_lanes(
                    _owners[_snip_id], _snip_id, _fields,
                )
                if _lane_err is not None:
                    return _lane_err
                _n_saved += 1

        # ── labels[] (old publish-body shape) — private lane, idempotent. ──
        if isinstance(_labels, list) and _labels:
            try:
                from services.training_labels import validate_publish_labels
                clean = validate_publish_labels(
                    _labels, set(_owners), require_all=False)
                # Group by owning session — a label on a folded read snippet
                # must store under the read's session id (that's where the
                # key-moment selection and the learning export read them).
                _by_owner = {}
                for _lab in clean:
                    _own = _owners.get(str(_lab.get("snippet_id"))) \
                        or str(session_id)
                    _by_owner.setdefault(_own, []).append(_lab)
                for _own, _own_labels in _by_owner.items():
                    db.upsert_training_labels(
                        _own, str(request.user_id), _own_labels)
            except Exception as _lab_err:
                # This is a DB/PostgREST exception, not a validation
                # message: its text carries table + column names.
                return safe_error(
                    "INVALID_INPUT", 422,
                    message="Those labels could not be saved.",
                    exc=_lab_err, log="feedback: label upsert failed")

        if not db.set_session_feedback_saved(session_id):
            return jsonify({"code": "V2_ERROR",
                            "error": "Could not save"}), 500
        return jsonify({"saved": True, "session_id": session_id,
                        "snippets_saved": _n_saved}), 200
    except Exception as e:
        logger.error("save-feedback failed sid=%s: %s", session_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to save"}), 500


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
        sessions = db.get_arc_sessions(arc_id)
        if not sessions:
            return jsonify({"code": "NOT_FOUND", "error": "arc not found"}), 404
        spoken, reads = _spoken_takes_and_reads(sessions)

        takes = []
        pending = []
        for s in spoken:
            sid = str(s.get("id"))
            if s.get("results_published_at"):
                _rs = "delivered"
            elif s.get("coach_feedback_saved_at"):
                _rs = "reviewed"
            else:
                _rs = "to_review"
                pending.append(sid)
            takes.append({
                "session_id": sid,
                "take_index": s.get("take_index"),
                "review_state": _rs,
                "has_reread": bool(reads.get(sid)),
            })

        from services.best_presentation import TAKES_TARGET
        row = db.get_coach_arc_ideal_text(arc_id) or {}
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

        blockers = []
        if not spoken:
            blockers.append("NO_TAKES")
        if pending:
            blockers.append("TAKES_NOT_SAVED")
        if not _approved:
            blockers.append("IDEAL_TEXT_NOT_APPROVED")

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
# confidence/direction labeling surface: different endpoints, and the payload
# carries no acoustic_read, no direction, and no shadow prediction. A coach can
# judge the ADVICE with full sight and must still label the VOICE blind.
# Pinned by test_star_verdicts.py.
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
        sessions = db.get_arc_sessions(arc_id)
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
        snippets_by_id: dict = {}
        if suggestions:
            _starred = set(suggestions.keys())
            for _s in sessions:
                _sid = str(_s.get("id") or "")
                if not _sid:
                    continue
                for _snip in (db.get_snippets_by_session(_sid) or []):
                    _snip_id = str(_snip.get("id") or "")
                    if _snip_id not in _starred:
                        continue
                    snippets_by_id[_snip_id] = {
                        "audio_ref": (_snip.get("audio_segment_path")
                                      or _snip.get("audio_ref")
                                      or _snip.get("storage_path")),
                        "start_offset_ms": _snip.get("start_offset_ms"),
                        "duration_ms": _snip.get("duration_ms"),
                        "transcript": (_snip.get("transcript")
                                       or _snip.get("transcript_excerpt")
                                       or ""),
                        "take_index": _s.get("take_index"),
                    }

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
      speaker_sex   (optional) female | male | prefer_not_to_say — WHOSE
                    VOICE this is, not the coach's. The confidence composite
                    routes one cue's DIRECTION on it, and an imported take is
                    someone else's voice filed under the coach's account, so
                    absent it the pipeline uses the acoustic route rather
                    than inheriting the coach's own declared sex.
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
      queue_per_band (optional, int) how many pieces per confidence band to
                    queue for labelling (default 5 → up to ~15-20 queued)

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
            speaker_sex=(request.form.get("speaker_sex") or "").strip() or None,
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
            "queue_count": len(ctx.get("label_queue") or []),
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
          status, queue_count, labelled_count, language, speaker_sex,
          duration_sec, archived_at}], count }
    """
    try:
        rows = db.list_training_import_sessions(
            user_id=(request.args.get("user_id") or None)) or []
        include_archived = (request.args.get("include_archived") or "") in (
            "1", "true", "yes")
        labelled = db.count_labelled_snippets_by_session_ids(
            [r.get("id") for r in rows])
        out = []
        for r in rows:
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
                "queue_count": len(ctx.get("label_queue") or []),
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
                # cue's DIRECTION routes on it, so "which route did this run
                # use" is worth being able to see. Declared value only —
                # absent means the acoustic route decided.
                "speaker_sex": ctx.get("speaker_sex"),
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
        if not db.set_session_intake_context(str(session_id), ctx):
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
            if not db.set_session_intake_context(str(session_id), ctx):
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


@v2_bp.route("/coach/sessions/<session_id>/confidence-queue", methods=["GET"])
@require_admin_or_coach
def v2_coach_confidence_queue(session_id):
    """The pieces queued for confidence labelling on one take, blind.

    The queue was chosen at import time by sampling ACROSS the confidence
    spectrum — some the composite reads as confident, some middling, some
    doubtful — so the corpus has the negative examples a binary recogniser
    needs. The bands are used to select and then discarded: this payload
    carries the moment (words + audio) and NOTHING that could hint at an
    answer (BLIND COACH — no voice_confidence, no acoustic_read, no tone
    word). Falls back to a fresh stratified pick when the session carries no
    stored queue (any take, not just an import).

    200 { session_id, queue: [{snippet_id, transcript, audio_ref,
          start_offset_ms, duration_ms, label}], count, labelled }
    404 · 500
    """
    try:
        sess = db.v2_get_session_by_id(str(session_id))
        if not sess:
            return jsonify({"code": "NOT_FOUND",
                            "error": "session not found"}), 404
        from services.confidence_labels import (
            queue_payload, stratified_label_queue,
        )
        snippets = db.get_snippets_by_session(str(session_id)) or []
        ctx = sess.get("intake_context") if isinstance(
            sess.get("intake_context"), dict) else {}
        stored = ctx.get("label_queue")
        if isinstance(stored, list) and stored:
            wanted = {str(s) for s in stored}
            picked = [s for s in snippets if str(s.get("id")) in wanted]
        else:
            picked = stratified_label_queue(snippets, seed=str(session_id))

        rows = queue_payload(picked)
        # PLAYABLE urls, not storage keys (FE §2): this is a LISTENING screen
        # — the coach hears the piece and judges. A bare key renders a dead
        # player and the surface silently degrades to labelling TEXT, which
        # is a different task and a corpus of a different thing. A row whose
        # audio_ref is already an http(s) URL is left alone; a key is signed.
        _resolve_audio_refs(rows)
        labels = db.get_confidence_labels_by_snippet_ids(
            [r["snippet_id"] for r in rows]) or {}
        labelled = 0
        for r in rows:
            mine = [lbl for lbl in labels.get(str(r["snippet_id"]), [])
                    if str(lbl.get("rater_id") or "")
                    == str(getattr(request, "user_id", "") or "")]
            if mine:
                labelled += 1
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
            else:
                r["label"] = None
        return jsonify({"session_id": session_id, "queue": rows,
                        "count": len(rows), "labelled": labelled}), 200
    except Exception as e:
        logger.warning("confidence queue failed sid=%s: %s", session_id, e)
        return jsonify({"code": "SERVER_ERROR",
                        "error": "could not load the queue"}), 500


@v2_bp.route("/coach/snippets/<snippet_id>/confidence-label", methods=["PUT"])
@require_admin_or_coach
def v2_coach_put_confidence_label(snippet_id):
    """The coach's confidence call on ONE snippet — THE core training signal.

    TERNARY body (SPEC.md v3 §3.2, current):

        { state_id: "confidence",
          value: "yes" | "no" | "neutral",   # XOR unrateable
          unrateable?: bool,
          note?: str, latency_ms?: int }

      value       yes / no / NEUTRAL. The middle is not a hedge — a recogniser
                  that has never seen the middle has never seen the boundary
                  it exists to find, and every agreement number computed
                  without it is measured on the easy cases only.
      unrateable  a SEPARATE control, not a fourth value. `neutral` judges the
                  MOMENT; `unrateable` judges the rater's ability to judge it,
                  usually because of the audio. Folding them books unclear
                  audio as a real middling rating.

    LEGACY body { confident: bool, intensity?: 1..5, note?: str } is still
    accepted and translated (true->yes, false->no), so the current FE keeps
    working through the cutover rather than the instrument change breaking a
    live surface. `intensity` rides along when the same request carried it —
    it is the 1-5 scale Jiang & Pell's listeners used and remains the human
    side of the validation gate. A legacy body cannot express `neutral`; that
    is the whole reason the instrument changed.

    Re-labelling REPLACES this rater's row (the corpus wants their current
    view); other raters' rows are untouched, so multi-rater agreement stays
    possible.

    LANE is derived, never sent by the client (SPEC §6.2). A coach rating an
    import is BOOTSTRAP, not coach — one rater on a model-proposed candidate
    from a corpus the founder assembled is not panel-grade however expert the
    rater, and that distinction is impossible to reconstruct afterwards.

    AC-9: nothing here is ever serialized toward a student.

    200 { saved, snippet_id, state_id, value, unrateable, lane,
          confident, intensity } · 400 · 404 · 500
    """
    if not _is_valid_uuid(snippet_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "snippet_id must be a valid UUID"}), 400
    body = request.get_json(silent=True) or {}

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

    row, err = validate_rating(body)
    if err:
        return jsonify({"code": "INVALID_INPUT", "error": err}), 400
    try:
        snip = db.get_snippet_by_id(snippet_id)
        if not snip:
            return jsonify({"code": "NOT_FOUND",
                            "error": "snippet not found"}), 404
        session_id = snip.get("session_id")
        sess = db.v2_get_session_by_id(str(session_id)) if session_id else None
        lane = resolve_lane((sess or {}).get("source"), is_coach=True)

        saved = db.upsert_state_rating(
            snippet_id=snippet_id, row=row,
            rater_id=getattr(request, "user_id", None),
            session_id=session_id, lane=lane,
            intensity=legacy_intensity,
        )
        if not saved:
            return jsonify({
                "code": "SERVER_ERROR",
                "error": "could not save the rating (run "
                         "migrations/add_state_generic_ratings.sql)",
            }), 500
        value = row["value"]
        return jsonify({
            "saved": True, "snippet_id": snippet_id,
            "state_id": row["state_id"], "value": value,
            "unrateable": row["unrateable"], "lane": lane,
            # Legacy fields, derived — the current FE reads these.
            "confident": (True if value == "yes"
                          else False if value == "no" else None),
            "intensity": legacy_intensity,
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
    """RETIRED (single-deliverable, founder 2026-07-17): publish was replaced
    by VERIFY (POST /v2/coach/arc/<arc_id>/verify). Always 410 GONE."""
    try:
        return jsonify({
            "code": "GONE",
            "error": "Publish was replaced by Verify "
                     "(POST /v2/coach/arc/<arc_id>/verify).",
        }), 410
    except Exception as e:
        logger.error("publish-analysis failed arc=%s: %s", arc_id, e,
                     exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to publish the analysis",
        }), 500
