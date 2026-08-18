"""The willab Lab upload domain: recording intake + slide-deck extract.

  POST /v2/lab/recordings            -- the take upload (record -> take entry
                                        point of the live loop)
  POST /v2/lab/presentation/extract  -- deck PDF -> per-slide text

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 1); the
route bodies are byte-identical to what was there before. Routes register on
the SAME ``v2_bp`` blueprint object, so endpoint names ("v2.<view_func>") and
the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import json
import logging
import os
import uuid

import sentry_sdk
from flask import jsonify, request

from auth import optional_auth
from routes.v2.arcs import _arc_audit_paid, _continue_deck_arc, _continue_topic_arc
from routes.v2.blueprint import v2_bp
from services.rate_limits import heavy_limit, whisper_limit
# Module scope on purpose: `except DeadlineExceeded` in the upload routes
# must resolve even when the failure happens BEFORE the try body reaches
# its own imports — otherwise the handler NameErrors while handling.
from services.upload_guard import (
    DeadlineExceeded, UploadTooLarge, deadline_for, read_capped,
)
from routes.v2.common import (
    _LAB_MAX_AUDIO_MB,
    _PRESENTATION_MAX_MB,
    _VIDEO_UPLOAD_EXTS,
    _async_analysis_enabled,
    _is_valid_uuid,
    _pipeline_queue_enabled,
)
from services.db import db

from config import Config

logger = logging.getLogger(__name__)
config = Config()


def _parse_inline_context_document(upload):
    """Read and extract an optional Take-1 context document.

    A new project has no arc id before this request resolves it, so the brief
    must ride the recording multipart rather than the arc-scoped upload route.
    Return ``(parsed, error)`` where error is ``(code, message, status)``.
    Parsing happens before audio storage: a bad document cannot leave a user
    with a stored take that never entered processing.
    """
    if upload is None:
        return None, None
    max_bytes = max(1, int(
        getattr(config, "CONTEXT_DOC_MAX_MB", 25) or 25)) * 1024 * 1024
    try:
        data = read_capped(upload, max_bytes)
    except UploadTooLarge:
        return None, (
            "FILE_TOO_LARGE", "the context document is too large", 413,
        )
    if not data:
        return None, (
            "INVALID_INPUT", "the context document is empty", 400,
        )
    from services.context_document import extract_context_text
    parsed = extract_context_text(
        data,
        content_type=getattr(upload, "content_type", None),
        filename=getattr(upload, "filename", None),
    )
    if not parsed.get("text"):
        return None, (
            "NO_TEXT", "no readable text found in the context document", 400,
        )
    parsed["filename"] = getattr(upload, "filename", None)
    return parsed, None


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


@v2_bp.route("/lab/presentation/extract", methods=["POST"])
@heavy_limit
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
            # Single source of truth for the FE "too big" popup: machine-
            # readable code + the limit as a number (so the FE renders the
            # message/limit without re-hardcoding it). On-message with the
            # product's "keep slides simple" guidance — a lighter export, not
            # silent server-side compression.
            return jsonify({
                "code": "FILE_TOO_LARGE",
                "error": f"Deck is over {_PRESENTATION_MAX_MB} MB — export a lighter PDF and try again.",
                "limit_mb": _PRESENTATION_MAX_MB,
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


def _recording_flow_tags(form) -> dict:
    """The optional recording-flow tags a take can carry (founder
    2026-07-20), read from FLAT multipart fields and folded into the
    session_context AFTER validation (the validator strips unknown keys —
    nothing rides through on its own). All optional, all bounded:

      paired_snippet_id  a delivery-star snippet re-record's target snippet
                         (UUID; invalid dropped)
      named_emotion      the pre-recording emotion-naming answer (F2
                         handoff §2, 2026-08-03) — a KEY from the closed
                         vocabulary in services/named_emotion.py; unknown
                         words are dropped (never block a recording). The
                         key is the user's own self-report and rides to
                         the coach; its threat/challenge BUCKET is
                         internal-only (CONSTRUCT — log line, never wire).
    """
    tags: dict = {}
    # read_target / ideal_version RETIRED (founder 2026-08-05): they only
    # ever tagged an ideal-text re-read, and that lane is gone. The guard in
    # the handler refuses such an upload outright, so nothing can arrive
    # here wanting them.
    _psnip = (form.get("paired_snippet_id") or "").strip()
    if _psnip and _is_valid_uuid(_psnip):
        tags["paired_snippet_id"] = _psnip
    try:
        from services.named_emotion import normalize_named_emotion
        _emo = normalize_named_emotion(form.get("named_emotion"))
        if _emo:
            tags["named_emotion"] = _emo
    except Exception:
        pass
    return tags


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


@v2_bp.route("/lab/recordings", methods=["POST"])
@whisper_limit
@optional_auth
def v2_lab_create_recording():
    """willab Lab upload — multipart, synchronous, guest-allowed (§3.3).

    Multipart form fields:
      audio_file            (required) the recording
      topic                 (required) session_context topic
      audience              (optional)
      strategic_context     (optional) short free-text note on the stakes /
                            setting / what the speaker wants to nail (④ step
                            5) — BACKGROUND for the qualitative feedback, never
                            the verbatim ideal text
      target_length_seconds (optional, int)
      domain_vocabulary     (optional, JSON array or comma-separated)
      feeling               (optional) pre-take felt state (U10)
      priming_condition     (optional) pre-take framing manipulation —
                            threat|challenge|balanced (live takes only;
                            unknown → stored null). PRIVATE research signal,
                            coach-only, never user-facing.
      priming_phrase        (optional) the exact framing phrase shown (verbatim)
      guest_session_id      (optional) reuse an existing guest session;
                            else a fresh one is minted + returned
      recording_kind        (optional) spoken (default) | read — a read is a
                            paired variant, never a take of its own
      paired_session_id     (required for read) the spoken take this read
                            folds under; an unpaired read is invisible
      paired_snippet_id     (REQUIRED for read since 2026-08-05, UUID) the
                            delivery-star snippet this re-record targets.
                            The only surviving reason to post a read: the
                            ideal-text re-read is retired and a read
                            without this is refused 422.
      continue_arc_id       (optional, UUID) the project the user PICKED —
                            the take appends strictly to it, the
                            continue-arc heuristics are skipped, and the
                            server numbers the take. Owner-only (404)
      project_intent        (optional) new | continue. New clients send this
                            explicit identity boundary: new MUST carry no arc
                            id and always mints one; continue MUST carry the
                            selected continue_arc_id. Legacy omission retains
                            the prior heuristic behaviour.

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
        # A new-project brief rides beside the audio. Keep a total-request
        # ceiling as well as the bounded per-part reads below; the small extra
        # allowance covers multipart fields/boundaries, not another payload.
        _context_max_bytes = max(1, int(
            getattr(config, "CONTEXT_DOC_MAX_MB", 25) or 25)) * 1024 * 1024
        _request_max = max_bytes + 1024 * 1024
        if request.files.get("context_document") is not None:
            _request_max += _context_max_bytes
        if (request.content_length or 0) > _request_max:
            return jsonify({
                "code": "FILE_TOO_LARGE",
                "error": "the recording or context document is too large",
            }), 413
        # BOUNDED read (P0 audit 2026-08-03). Content-Length above is a
        # client assertion — a chunked or mis-declared body sails past it,
        # and the old unbounded .read() then pulled the whole thing into
        # the worker's heap. read_capped stops one byte past the cap.
        deadline = deadline_for("lab-upload")
        try:
            file_bytes = read_capped(audio_file, max_bytes)
        except UploadTooLarge:
            return jsonify({
                "code": "FILE_TOO_LARGE",
                "error": f"audio_file exceeds {_LAB_MAX_AUDIO_MB}MB",
            }), 413
        if not file_bytes:
            return jsonify({
                "code": "INVALID_INPUT", "error": "audio_file is empty",
            }), 400
        # Reject VIDEO (defensive — the FE picker blocks it and the Vercel
        # edge caps size, but a video that slips through should fail clean,
        # not as a confusing downstream decode error). By mimetype (incl.
        # video/webm) OR a video-only extension. NOTE: never include "webm"
        # here — the live mic records audio/webm (.webm); that must pass.
        _up_ct = (audio_file.mimetype or "").strip().lower()
        _up_ext = os.path.splitext(audio_file.filename or "")[1].lower().lstrip(".")
        if _up_ct.startswith("video/") or _up_ext in _VIDEO_UPLOAD_EXTS:
            return jsonify({
                "code": "AUDIO_ONLY",
                "error": "Upload an audio file — video isn't supported.",
            }), 415

        # Optional uploaded context for a BRAND-NEW project. Existing projects
        # use the owner-checked arc endpoint, while this request mints the arc
        # only later. Extract now, then persist immediately after arc resolution
        # and before any analysis job can begin.
        _context_document, _context_error = _parse_inline_context_document(
            request.files.get("context_document"),
        )
        if _context_error:
            _ctx_code, _ctx_message, _ctx_status = _context_error
            return jsonify({
                "code": _ctx_code, "error": _ctx_message,
            }), _ctx_status

        # ── 2. session_context (inline; topic required) ─────────────
        from services.intake_context import (
            IntakeContextError, validate_intake_context_body,
        )
        form = request.form or {}

        # ── LANE GUARD (founder bugs 2026-07-20). A read is a PAIRED
        # variant of a spoken take, never a take of its own. An unpaired
        # read used to fall through as SPOKEN — it took a take number,
        # triggered assembly and minted a version ("the re-read counted
        # as a take"). Fail fast, before any storage or processing. ──
        _kind_raw = (form.get("recording_kind") or "spoken").strip().lower()
        if _kind_raw == "read":
            _pair_raw = (form.get("paired_session_id") or "").strip()
            if not _pair_raw or not _is_valid_uuid(_pair_raw):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": ("A re-read needs the spoken take it belongs "
                              "to (paired_session_id)."),
                }), 422
            # ── IDEAL-TEXT RE-READ IS RETIRED (founder 2026-08-05).
            # "Read out loud" — reading the settled ideal text back into
            # the mic — brought no value to the coach or the user, so it
            # is gone: one lane now, take after take.
            #
            # The read lane ITSELF survives, because it carries a second,
            # unrelated feature: the DELIVERY-STAR snippet re-record
            # (services/reRecordSnippet on the FE), which re-records one
            # snippet with a star's feedback applied and rides the same
            # recording_kind='read' wire. That feature was never in scope
            # here, so the guard is narrow: a read WITHOUT a target
            # snippet is the retired ideal-text re-read and is refused; a
            # read WITH one is a star re-record and passes.
            #
            # Refusing rather than silently downgrading to spoken matters:
            # the ideal-text version is now the SPOKEN TAKE COUNT, so a
            # stale client's re-read landing as a take would bump the
            # version and un-verify a text nobody re-recorded.
            _psnip_raw = (form.get("paired_snippet_id") or "").strip()
            if not _psnip_raw or not _is_valid_uuid(_psnip_raw):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": ("Reading your ideal text out loud has been "
                              "retired. Record the next take instead."),
                }), 422

        # ── EXPLICIT PROJECT SELECTION (founder 2026-07-22): the user
        # PICKED this project from the list, so the server does not guess
        # anything — the take appends strictly to that arc and BOTH
        # continue-arc heuristics are skipped (see step 5). Distinct from
        # the carried `arc_id` (takes 2/3 of one sitting), which keeps
        # today's behavior so the continue-one-arc-per-deck lock
        # (2026-06-20) is untouched.
        #
        # Validated HERE, before any storage: a take must never be stored
        # against a project the caller does not own (same fail-fast rule
        # as the read guard above). ──
        _explicit_arc = (form.get("continue_arc_id") or "").strip()
        from services.explore_arc import validate_project_intent
        _project_intent, _intent_error = validate_project_intent(
            form.get("project_intent"),
            form.get("arc_id"),
            _explicit_arc,
        )
        if _intent_error:
            logger.warning("lab: invalid project identity contract: %s",
                           _intent_error)
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "Something went wrong on our end.",
            }), 400
        if _explicit_arc:
            if not _is_valid_uuid(_explicit_arc):
                return jsonify({
                    "code": "INVALID_INPUT",
                    "error": "continue_arc_id must be a UUID",
                }), 400
            _uid = getattr(request, "user_id", None)
            _owned = False
            if _uid:
                try:
                    _owned = any(
                        str(x.get("user_id")) == str(_uid)
                        for x in (db.get_arc_sessions(_explicit_arc) or []))
                except Exception as _own_err:
                    logger.warning(
                        "lab: continue_arc ownership check failed arc=%s: "
                        "%s", _explicit_arc, _own_err)
                    _owned = False
            if not _owned:
                # No existence leak: unknown and foreign look identical.
                return jsonify({"code": "NOT_FOUND",
                                "error": "project not found"}), 404
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

        def _form_int(name):
            """Optional integer multipart field. Unparseable → None (absent),
            so a malformed value degrades to today's behaviour rather than
            422-ing a recording that is otherwise fine."""
            raw = form.get(name)
            if raw in (None, ""):
                return None
            try:
                return int(float(raw))
            except (TypeError, ValueError):
                return None
        try:
            session_context = validate_intake_context_body({
                "topic": form.get("topic"),
                "audience": form.get("audience"),
                # ④ step 5 (2026-07-24): a short free-text note on the stakes /
                # setting / what the speaker wants to nail. BACKGROUND context
                # for the qualitative feedback — never the verbatim ideal text.
                "strategic_context": form.get("strategic_context"),
                "target_length_seconds": target_len,
                "domain_vocabulary": _parse_lab_vocabulary(
                    form.get("domain_vocabulary"),
                ),
                # Slide-deck context (UX Wave 4 §S) — JSON multipart fields,
                # same pattern as domain_vocabulary.
                "slides": _form_json("slides"),
                "presentation_ref": form.get("presentation_ref") or None,
                "slide_advances": _form_json("slide_advances"),
                # F1 (2026-07-26): the FE-MEASURED offset between the UI clock
                # that stamps slide taps and the recorder's first audio sample.
                # Turns the two-clocks drift from a guess (pause-snap) into a
                # known quantity. Optional — absent keeps today's behaviour.
                "slide_clock_offset_ms": _form_int("slide_clock_offset_ms"),
            }, require_topic=True)
        except IntakeContextError as ve:
            return jsonify({"code": "INVALID_INPUT", "error": str(ve)}), 422

        # Collapse a retry by the captured-take key. Project display names are
        # intentionally irrelevant: two same-named projects are valid and are
        # kept independent by authenticated owner + immutable arc UUID.
        _upload_key = (form.get("upload_idempotency_key") or "").strip()
        if _upload_key:
            _dup = db.v2_find_session_by_upload_key(_upload_key)
            if _dup:
                # A retry can heal the narrow failure window where the take was
                # accepted but its optional brief had not yet been persisted.
                _dup_arc = _dup.get("arc_id")
                if _context_document and _dup_arc:
                    db.upsert_arc_context_document(
                        _dup_arc,
                        _context_document["text"],
                        _context_document["pages"],
                        _context_document["chars"],
                        filename=_context_document.get("filename"),
                        truncated=_context_document["truncated"],
                    )
                logger.info("lab: duplicate upload collapsed key=%s -> %s",
                            _upload_key, _dup.get("id"))
                return jsonify({
                    "duplicate": True,
                    "session_id": _dup.get("id"),
                    "arc_id": _dup.get("arc_id"),
                    "take_index": _dup.get("take_index"),
                }), 200

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
            # Survivorship capture (audit fix #2c): gate-failed takes are dropped
            # before any storage, so we had no "bad take" record. Log the gate
            # METRICS only (no audio — privacy + cost). Best-effort, never blocks
            # the 422 re-record prompt.
            try:
                db.insert_rejected_take(
                    reason=gate.get("reason"),
                    duration_sec=gate.get("duration_sec"),
                    voiced_sec=gate.get("voiced_sec"),
                    thresholds=gate.get("thresholds"),
                    user_id=getattr(request, "user_id", None),
                    guest_session_id=(form.get("guest_session_id") or None),
                    arc_id=(form.get("arc_id") or None),
                    take_index=form.get("take_index"),
                )
            except Exception as _rej_err:
                logger.warning(
                    "lab: rejected-take capture failed: %s (non-fatal)", _rej_err,
                )
            # Minimum duration RETIRED (founder 2026-07-15) — the only
            # rejections left are no_speech / no_audio (pipeline validity,
            # not a UX minimum).
            return jsonify({
                "code": "RECORDING_REJECTED",
                "error": "No speech detected — try recording again.",
                "gate": gate,  # {reason, duration_sec, voiced_sec, thresholds}
            }), 422

        # ── 4. store + session + recording ──────────────────────────
        # Lab audio is the USER's voice — its own bucket, not the coach's
        # media bucket (P0 audit 2026-08-03). Inert until R2_LAB_AUDIO_*
        # is provisioned; see services/lab_audio_storage.py.
        from services.lab_audio_storage import (
            lab_audio_public_url, put_lab_audio_bytes,
        )
        deadline.check("store")
        # ── SESSION-REUSE GUARD (founder bug 2026-07-20: "after the
        # re-read, recording the spoken version analyses the re-read").
        # A session that ALREADY carries a recording is spent: reusing it
        # made the new take inherit the previous one's lane (its
        # recording_kind='read' + paired_session_id), so the fresh spoken
        # audio was stored, analysed and folded as that re-read. A spent
        # id is dropped and a fresh session minted — the response's
        # `session_id` is authoritative and the FE adopts it. ──
        _sid_in = (form.get("guest_session_id") or "").strip()
        if _sid_in:
            _spent = False
            try:
                _prior = db.v2_get_session_by_id(_sid_in)
                if _prior:
                    # Any of these means the row already OWNS a recording
                    # and its lane: reusing it would fold this audio into
                    # that one.
                    _spent = bool(
                        _prior.get("recording_1_id")
                        or _prior.get("recording_kind")
                        or _prior.get("paired_session_id")
                        or _prior.get("analysis_state")
                        or _prior.get("results_published_at")
                    )
            except Exception as _reuse_err:
                # Fail CLOSED: an unknown state must not risk folding a
                # fresh take into a spent session.
                logger.warning(
                    "lab: session-reuse check failed sid=%s: %s (minting "
                    "fresh)", _sid_in, _reuse_err)
                _spent = True
            if _spent:
                logger.info(
                    "lab: spent session %s not reused — minting fresh "
                    "(lane guard)", _sid_in)
                _sid_in = ""
        guest_session_id = _sid_in or str(uuid.uuid4())
        recording_id = str(uuid.uuid4())
        ext = os.path.splitext(audio_file.filename or "")[1] or ".webm"
        parent_key = f"willab_lab/{guest_session_id}/recording_{uuid.uuid4().hex}{ext}"
        content_type = (audio_file.mimetype or "audio/webm").strip() or "audio/webm"

        try:
            bucket = put_lab_audio_bytes(parent_key, file_bytes, content_type)
        except Exception as up_err:
            logger.error("lab: parent upload failed: %s", up_err, exc_info=True)
            return jsonify({
                "code": "V2_ERROR", "error": "Failed to store recording",
            }), 500
        parent_url = lab_audio_public_url(parent_key) or f"s3://{bucket}/{parent_key}"

        # Guest session (create only if it doesn't already exist).
        if not db.v2_get_session_by_id(guest_session_id):
            try:
                db.v2_create_guest_session(guest_session_id)
            except Exception as se:
                logger.error("lab: guest session create failed: %s", se, exc_info=True)
                return jsonify({
                    "code": "V2_ERROR", "error": "Failed to create session",
                }), 500
        # Stamp the take's idempotency key so a lane-fallback retry finds
        # this session instead of minting take N+1 (best-effort — a miss
        # just means the retry cannot collapse).
        if _upload_key:
            db.v2_set_session_upload_key(guest_session_id, _upload_key)

        # Recording-flow tags (founder 2026-07-20): the intake-context
        # validator returns ONLY its canonical keys, so the flow tags the
        # FE sends as flat multipart fields are folded in EXPLICITLY here
        # (nothing "rides through" on its own).
        session_context.update(_recording_flow_tags(form))
        # Drift-metric stream (F2 handoff §2): one internal log line per
        # captured emotion — the rolling threat-share per user is computed
        # OFF-SURFACE from these. Log-only; the bucket never persists.
        if session_context.get("named_emotion"):
            try:
                from services.named_emotion import log_drift_signal
                log_drift_signal(getattr(request, "user_id", None),
                                 guest_session_id,
                                 session_context["named_emotion"])
            except Exception:
                pass

        # Persist session_context on the session row.
        db.set_session_intake_context(guest_session_id, session_context)
        # Mark as a willab Lab session so the history list + send-gate
        # origin path can find it (best-effort; the recording_origin on
        # the recording row is the send-gate's primary gate).
        db.set_session_source(guest_session_id, "audit_upload")
        # Paid Audits (A5): persist the gate's measured duration on the session
        # so the length→audits read (audits_needed) needs no recording join.
        # Best-effort — no-op if the column is missing pre-migration.
        db.set_session_presentation_duration(
            guest_session_id, gate.get("duration_sec"),
        )
        # Attribute the take to the user AT RECORD TIME when signed in (Prompt
        # D): the explore arc + best-presentation/moments/progress are owned
        # reads, so an authed user's takes must be theirs immediately — not only
        # after the guest→signed claim flow. Guests stay user_id NULL (claimed
        # later as before). Best-effort.
        if getattr(request, "user_id", None):
            db.set_session_user_id(guest_session_id, request.user_id)

        # Spoken vs read (founder 2026-07-14). 'read' = the re-read of the
        # suggestion-corrected text; it is a PAIRED VARIANT of its spoken take
        # (paired_session_id), NOT a take of its own — so it inherits the
        # spoken take's arc_id/take_index and never increments the counter.
        _rec_kind = (form.get("recording_kind") or "spoken").strip().lower()
        if _rec_kind not in ("spoken", "read"):
            _rec_kind = "spoken"
        _paired_session_id = (form.get("paired_session_id") or "").strip() or None
        if _paired_session_id and not _is_valid_uuid(_paired_session_id):
            _paired_session_id = None

        # Explore-session arc (Prompt A §3) — link the takes of the SAME talk
        # so they're comparable. Standalone recordings (no explore_session) →
        # arc_id stays None; this is fully opt-in.
        from services.explore_arc import resolve_arc
        arc_id, take_index = resolve_arc(
            form.get("explore_session"),
            form.get("arc_id"),
            form.get("take_index"),
        )

        # EXPLICIT PROJECT SELECTION (validated at step 2, above): the
        # user PICKED this project, so the take appends strictly to it
        # and BOTH continue-arc heuristics are skipped below.
        if _explicit_arc:
            arc_id = _explicit_arc
            # The SERVER numbers the take (never the FE-sent index).
            try:
                from services.best_presentation import spoken_arc_sessions
                take_index = len(spoken_arc_sessions(
                    db.get_arc_sessions(arc_id) or [])) + 1
            except Exception:
                take_index = max(1, take_index or 1)

        # A READ inherits its spoken take's arc + number and short-circuits all
        # the continue-arc / take-counter logic below (it isn't a new take).
        _read_paired = None
        if _rec_kind == "read" and _paired_session_id:
            _read_paired = db.v2_get_session_by_id(_paired_session_id) or {}
            if _read_paired.get("arc_id"):
                arc_id = _read_paired.get("arc_id")
            if _read_paired.get("take_index"):
                take_index = int(_read_paired["take_index"])

        # Continue-one-arc (founder 2026-06-20): a re-recording of the SAME deck
        # (same authed user) joins that deck's existing arc as the next take,
        # instead of the freshly-minted one — ONE ever-growing arc per deck, so
        # the best presentation keeps deepening across sittings. Extended
        # 2026-07-06 (founder bug #4/#6): DECKLESS takes of the SAME TALK (same
        # normalized topic) also continue one arc — the conversational practice
        # flow is deckless, and fresh-arc-per-take split the training across
        # arcs (counter said "1 of 3" while the bubble said "Take 3 of 3", and
        # the coach saw one take per arc). Guests keep the fresh arc.
        # `_explicit_arc` → the user chose the project: NO guessing (the
        # deck-hash / topic-normalisation matching is skipped entirely).
        # `_project_intent == "new"` is the other explicit boundary: this is a
        # brand-new project, so the freshly minted UUID MUST survive. A topic,
        # an uploaded deck, and the shared default deck are content only; none
        # may reconnect this recording to an earlier arc. This is forward-only:
        # clients that omit project_intent keep the legacy resolver and no
        # historical rows are touched.
        #
        # ⚠️ 2026-08-15 — THE BRANCH IS CHOSEN ON `presentation_ref`, NOT ON
        # `slides`. It used to read "has slides → it is a deck → match by deck
        # hash", and that was true until 2026-08-11, when the DEFAULT DECK
        # started shipping on every deckless take so word→slide bucketing
        # would always be defined. The default deck is a CONSTANT: identical
        # bytes for every deckless recording, forever. So its content hash is
        # one fixed value shared by every deckless talk a user has ever given,
        # `_continue_deck_arc` treated them all as re-takes of one deck, and a
        # brand-new topic was appended to the most-developed unrelated arc —
        # inheriting that arc's locked ideal text, so the "analysis" of the
        # new take was the old take's text. Worse, `slides` being non-empty
        # meant the TOPIC guard below — the one thing that would have kept the
        # two talks apart — was never reached at all.
        #
        # "Same deck" means "same UPLOADED deck", and the thing that marks one
        # is the PDF behind it: the FE sends `presentationRef: null` for the
        # default deck on purpose ("never claim a PDF that isn't there"). So a
        # take with a real ref keeps deck-hash continuation exactly as before,
        # and a take standing on the scaffold continues by TOPIC, which is
        # what actually identifies the talk when the deck is generic.
        #
        # Chosen over mirroring the deck's text here and comparing hashes: the
        # copy is the founder's and lives in the frontend, so a BE mirror would
        # go stale on the next word he changes and this bug would return
        # silently. A missing PDF cannot drift.
        if getattr(request, "user_id", None) and arc_id \
                and _rec_kind != "read" and not _explicit_arc \
                and _project_intent != "new":
            _slides_for_arc = (session_context or {}).get("slides") or []
            _deck_ref = (session_context or {}).get("presentation_ref")
            if _slides_for_arc and _deck_ref:
                arc_id, take_index = _continue_deck_arc(
                    request.user_id, _slides_for_arc, arc_id, take_index,
                )
            else:
                arc_id, take_index = _continue_topic_arc(
                    request.user_id,
                    (session_context or {}).get("topic"),
                    arc_id, take_index,
                )
        arc_take_count = None
        if _rec_kind == "read":
            # The read rides its spoken take's number; link + tag, no counting.
            if arc_id:
                db.set_session_arc(guest_session_id, arc_id, take_index)
            db.set_session_recording_kind(
                guest_session_id, "read", _paired_session_id)
            arc_take_count = take_index
        elif arc_id:
            # ONE take-count source of truth (founder bug #6): the server-side
            # arc session count numbers this take — never the FE-sent index
            # (which drifted and produced "Take 3 of 3" beside "1 of 3 takes").
            # Review hardening: (a) a RETRY of an already-arc-linked session
            # keeps its existing number (never double-counts itself); (b) the
            # count EXCLUDES the current session; (c) a failed count read keeps
            # the FE-sent index (fail CLOSED — never mislabel a real take-2/3
            # as take-1, which would open the free-intro human layer).
            _sess_row = db.v2_get_session_by_id(guest_session_id) or {}
            if _sess_row.get("arc_id") and _sess_row.get("take_index"):
                arc_id = _sess_row["arc_id"]
                take_index = int(_sess_row["take_index"])
            else:
                _cnt = db.count_arc_sessions(
                    arc_id, exclude_session_id=guest_session_id,
                )
                if _cnt is not None:
                    take_index = _cnt + 1
                db.set_session_arc(guest_session_id, arc_id, take_index)
            arc_take_count = take_index

        # Persist the Take-1 brief against the immutable project id before the
        # worker is enqueued. The qualitative layer reads it from this table;
        # it never becomes speaker text and never participates in project
        # identity. This is best-effort like the existing arc upload endpoint:
        # an optional document can sharpen feedback but cannot lose a take.
        if _context_document and arc_id:
            _stored_context = db.upsert_arc_context_document(
                arc_id,
                _context_document["text"],
                _context_document["pages"],
                _context_document["chars"],
                filename=_context_document.get("filename"),
                truncated=_context_document["truncated"],
            )
            if not _stored_context:
                logger.warning(
                    "lab: context document was not persisted arc=%s", arc_id,
                )

        # Founder re-lock 2026-07-06: recording/analysis/send are NEVER
        # payment-gated — every take of every arc records, analyzes, and reaches
        # the coach free. (The old take-3 402 here aborted unpaid takes before
        # they persisted — the "coach only received take 1" bug.) Payment gates
        # only the coach-HUMAN-feedback VIEW + the best-presentation deliverable.

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

        # Pre-take priming manipulation (founder 2026-07-13) — the framing panel
        # the student saw before this live take (threat/challenge/balanced, one
        # condition per batch position + the exact phrase). Same private
        # correlation lane as the feeling: stored on the take's session row,
        # surfaced to the COACH review only, NEVER echoed to the readout /
        # instant view / student batch (AC-9 — it's a manipulation label, not
        # user content). Unknown condition → stored null; absent on uploads.
        # Best-effort + a SEPARATE write from the feeling, so a pre-migration
        # hiccup here can never regress the feeling capture above.
        from services.priming import (
            normalize_priming_condition, normalize_priming_phrase,
        )
        _prime_cond = normalize_priming_condition(form.get("priming_condition"))
        _prime_phrase = normalize_priming_phrase(form.get("priming_phrase"))
        if _prime_cond or _prime_phrase:
            db.set_session_priming(guest_session_id, _prime_cond, _prime_phrase)

        # Recording row (recording_origin fallback for pre-migration envs).
        # BE-1 / S2 — persist the gate's measured duration (was hardcoded 0 +
        # discarded). This is the source for cumulative recording-progress.
        _rec_duration = 0
        try:
            _rec_duration = int(round(float(gate.get("duration_sec") or 0)))
        except (TypeError, ValueError):
            _rec_duration = 0
        # Speaker attribution at RECORD TIME (audit fix #2b): stamp the authed
        # uploader on the recording + the snippets/candidate-pool it produces,
        # instead of leaving them NULL until a guest-claim backfill (so per-
        # speaker baselines don't depend on a v2_sessions join). Guests legit-
        # imately stay NULL and are backfilled on claim — unchanged.
        _uploader_id = getattr(request, "user_id", None)
        rec_payload = {
            "id": recording_id, "user_id": _uploader_id,
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

        # ── 5. process → Readout payload ─────────────────────────────
        # The FULL analysis pipeline (transcribe → cut pieces → metrics →
        # persist → cadence → auto-send → arc cards) as ONE worker so it can
        # run either synchronously (legacy) or in a background daemon (async
        # mode, founder 2026-07-15: closing the tab / locking the phone must
        # never kill the analysis). Everything request-scoped is captured
        # HERE — the daemon must never touch flask.request.
        # Last boundary before the expensive stretch (transcribe → cut →
        # metrics → persist). If the budget is already spent, fail clean
        # here instead of starting work we can't finish.
        deadline.check("analyze")
        _cad_user = getattr(request, "user_id", None)
        _worker_filename = audio_file.filename or "lab.webm"
        _worker_spark = str(form.get("spark") or "").strip().lower() in (
            "1", "true", "yes", "on",
        )

        def _run_analysis_pipeline():
            """Runs to completion server-side. Returns (readout, sent).

            Body lives in services/analysis_worker.py::run_full_analysis
            (durable-queue work): the SAME code serves this sync path, the
            ASYNC_ANALYSIS_ENABLED daemon below, and the queue worker
            (services/pipeline_jobs.py) — one implementation, three
            execution modes, so behaviour can't drift between them.
            """
            from services.analysis_worker import run_full_analysis
            return run_full_analysis(
                session_id=guest_session_id,
                user_id=_uploader_id,  # fix #2b: attribute at record time
                recording_id=recording_id,
                audio_bytes=file_bytes,
                filename=_worker_filename,
                session_context=session_context,
                parent_audio_url=parent_url,
                recording_kind=_rec_kind,  # spoken | read (2026-07-14)
                # A re-read z-scores against its PARENT take (2026-07-17).
                paired_session_id=_paired_session_id,
                arc_id=arc_id,
                take_index=take_index,
                arc_take_count=arc_take_count,
                spark_enabled=_worker_spark,
            )

        # DURABLE QUEUE mode (async-queue work 2026-08-03): create a
        # processing_jobs row (Postgres = state of record) and hand the
        # job_id to the Redis/RQ worker service; 202 with job_id + the
        # poll URL. This retires the daemon's accepted gap: a redeploy
        # mid-job is re-run by the sweeper, never stranded. On ANY
        # failure (flag off, broker down, insert failed) fall through to
        # the daemon/sync paths below — the queue can only ADD capacity,
        # never block an upload (live loop).
        if _pipeline_queue_enabled():
            from services.pipeline_jobs import enqueue_session_recording_job
            _job_row = None
            try:
                _job_row = enqueue_session_recording_job(
                    session_id=guest_session_id,
                    user_id=_uploader_id,
                    recording_id=recording_id,
                    bucket=bucket,
                    storage_key=parent_key,
                    filename=_worker_filename,
                    session_context=session_context,
                    parent_audio_url=parent_url,
                    recording_kind=_rec_kind,
                    paired_session_id=_paired_session_id,
                    arc_id=arc_id,
                    take_index=take_index,
                    arc_take_count=arc_take_count,
                    spark_enabled=_worker_spark,
                )
            except Exception as _q_err:
                logger.warning(
                    "lab: queue enqueue raised sid=%s: %s (falling back)",
                    guest_session_id, _q_err,
                )
            if _job_row:
                # State AFTER a confirmed enqueue: if we flipped it first
                # and then fell back to the sync path, nothing would ever
                # write 'ready' and the readout GET would show
                # 'processing' forever. (The worker also stamps
                # 'processing' on claim, covering a crash right here.)
                db.set_session_analysis_state(guest_session_id, "processing")
                _dur_secs_q = int(_rec_duration or 0)
                _job_id_q = str(_job_row.get("id"))
                return jsonify({
                    "status": "processing",
                    "state": "processing",
                    "job_id": _job_id_q,
                    "job_status_url": f"/v2/jobs/{_job_id_q}/status",
                    "session_id": guest_session_id,
                    "recording_id": recording_id,
                    "duration_minutes": round(_dur_secs_q / 60.0, 1),
                    "audits_needed": max(1, -(-_dur_secs_q // 600)),
                    "session_context": session_context,
                    "readout": None,
                    "arc_id": arc_id,
                    "take_index": take_index,
                    "take_count": arc_take_count,
                    "audit_paid": _arc_audit_paid(arc_id, _cad_user),
                }), 202
            logger.warning(
                "lab: queue unavailable sid=%s — falling back to %s path",
                guest_session_id,
                "daemon" if _async_analysis_enabled() else "sync",
            )

        # ASYNC mode (founder 2026-07-15, flag default OFF until the FE ships
        # polling): flip the session to 'processing', run the pipeline in a
        # daemon that survives client disconnect, and 202 immediately. The FE
        # polls the readout GET until state ready|failed. Accepted gap
        # (decision 2026-07-15): a backend redeploy mid-job strands that one
        # job in 'processing' — the FE times out at ~3 min and offers
        # re-record. SUPERSEDED by the durable-queue branch above when
        # PIPELINE_QUEUE_ENABLED is on; kept as its fallback.
        if _async_analysis_enabled():
            db.set_session_analysis_state(guest_session_id, "processing")

            def _analysis_daemon():
                try:
                    _run_analysis_pipeline()
                    db.set_session_analysis_state(guest_session_id, "ready")
                except Exception as _bg_err:
                    logger.error(
                        "lab: ASYNC analysis failed sid=%s: %s",
                        guest_session_id, _bg_err, exc_info=True,
                    )
                    sentry_sdk.capture_exception(_bg_err)
                    db.set_session_analysis_state(
                        guest_session_id, "failed", str(_bg_err),
                    )

            import threading as _threading
            _threading.Thread(target=_analysis_daemon, daemon=True).start()

            _dur_secs_a = int(_rec_duration or 0)
            return jsonify({
                "status": "processing",
                "state": "processing",
                "session_id": guest_session_id,
                "recording_id": recording_id,
                "duration_minutes": round(_dur_secs_a / 60.0, 1),
                "audits_needed": max(1, -(-_dur_secs_a // 600)),
                "session_context": session_context,
                "readout": None,
                "arc_id": arc_id,
                "take_index": take_index,
                "take_count": arc_take_count,
                "audit_paid": _arc_audit_paid(arc_id, _cad_user),
            }), 202

        readout, _sent_to_coach = _run_analysis_pipeline()

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

        # #1 (2026-06-21) — re-derive the RESPONSE readout from the now-persisted
        # session + snippets so the right-after-recording readout carries the
        # SAME per-snippet `slide` (+ top-level `slides` / `presentation_ref`)
        # the GET readout does — process_lab_recording's pure payload has no
        # slide, so the FE had nothing to render above each snippet's text.
        # build_readout_from_session maps each snippet to the slide on screen via
        # the tap timeline. Best-effort: keep the slide-less payload on a hiccup.
        # Free/paid scope: echo the same audit_paid the GET readout uses. The
        # readout's own coach layer is unconditionally free (2026-07-06
        # re-price) — nothing take-aware to compute here anymore.
        _audit_paid = _arc_audit_paid(arc_id, getattr(request, "user_id", None))
        try:
            from services.lab_recording import build_readout_from_session
            # USER surface — no ungated upgrade cards (founder 2026-08-10).
            _full = build_readout_from_session(
                guest_session_id, audit_paid=_audit_paid,
                include_upgrade_cards=False,
            )
            if isinstance(_full, dict) and _full.get("snippets"):
                readout = _full
        except Exception as _rre:
            # F1: the 201 readout falls back to the slide-less payload (no
            # per-slide grouping in the immediate response). Observe it (the
            # wire response is unchanged — still 201, just degraded).
            from services.f1_observability import observe_f1_degrade
            observe_f1_degrade("readout_rederive_failed", exc=_rre,
                               session_id=guest_session_id)

        # Paid Audits (A5): length → how many audits this presentation needs.
        # MINUTES drive the count (founder D5), NOT slide count: one audit per
        # 10 minutes, floor of one. duration_minutes is this take's measured
        # length (from the min-content gate).
        _dur_secs = int(_rec_duration or 0)
        duration_minutes = round(_dur_secs / 60.0, 1)
        audits_needed = max(1, -(-_dur_secs // 600))  # ceil(seconds / 600)

        return jsonify({
            "status": "ok",
            "session_id": guest_session_id,
            "recording_id": recording_id,
            # Length → audits (A5). duration_minutes = this take's length.
            "duration_minutes": duration_minutes,
            "audits_needed": audits_needed,
            # Self-describing + matches the re-read/history `state` field. With
            # auto-send (founder 2026-07-06) an authed upload is ALREADY in the
            # coach queue → review_pending; guests / a send hiccup stay
            # readout_ready (the merge-path send picks them up).
            "state": ("review_pending" if _sent_to_coach else "readout_ready"),
            "session_context": session_context,
            "readout": readout,
            # Explore-session arc (Prompt A §3) — null for standalone takes.
            "arc_id": arc_id,
            "take_index": take_index,
            "take_count": arc_take_count,
            # Per-arc paid flag — an echo for the FE's paid-deliverable CTAs
            # (ideal text / breakthroughs list / game / library). This upload
            # response's own readout is unconditionally free (2026-07-06).
            "audit_paid": _audit_paid,
            # Fresh audit progress (BE-4) — null for guests; see note above.
            "recording_progress": recording_progress,
        }), 201

    except DeadlineExceeded as de:
        # The budget ran out between stages. The audio IS stored and the
        # session row exists, so this is recoverable: the FE re-polls the
        # readout rather than asking for a re-record.
        logger.warning("lab/recordings POST deadline: %s", de)
        return jsonify({
            "code": "PROCESSING_TIMEOUT",
            "error": "That recording is taking longer than expected — "
                     "it's still processing, check back shortly.",
            "session_id": locals().get("guest_session_id"),
        }), 504
    except Exception as e:
        logger.error("lab/recordings POST failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to process recording",
        }), 500


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
            _job = db.get_latest_processing_job_by_session(session_id)
            _progress = None
            if _job:
                try:
                    _percent = max(0, min(100, int(_job.get("percent") or 0)))
                except (TypeError, ValueError):
                    _percent = 0
                _progress = {
                    "stage": str(_job.get("stage") or "processing_recording"),
                    "percent": _percent,
                }
            return jsonify({
                "session_id": session_id, "state": "processing",
                "analysis_state": "processing", "readout": None,
                "processing": _progress,
            }), 200
        if _an_state == "failed":
            return jsonify({
                "session_id": session_id, "state": "failed",
                "analysis_state": "failed", "readout": None,
            }), 200

        from services.lab_recording import build_readout_from_session
        # USER surface — no ungated upgrade cards (founder 2026-08-10).
        readout = build_readout_from_session(
            session_id, include_upgrade_cards=False)

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


@v2_bp.route("/lab/recordings/<session_id>/retry-processing", methods=["POST"])
@optional_auth
def v2_retry_recording_processing(session_id):
    """Retry analysis against the preserved recording object."""
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "session_id must be a valid UUID"}), 400
    session = db.v2_get_session_by_id(session_id)
    caller = getattr(request, "user_id", None)
    owner = (session or {}).get("user_id")
    if not session or (owner and str(owner) != str(caller or "")):
        return jsonify({"code": "SESSION_NOT_FOUND",
                        "error": "Recording not found"}), 404
    from services.pipeline_jobs import retry_failed_session_job
    job = retry_failed_session_job(session_id, str(owner or caller or ""))
    if not job:
        return jsonify({"code": "RETRY_UNAVAILABLE",
                        "error": "Processing could not be restarted"}), 409
    return jsonify({
        "session_id": session_id,
        "state": "processing",
        "job_id": job.get("id"),
    }), 202


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
