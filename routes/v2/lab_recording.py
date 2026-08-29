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
from dataclasses import dataclass
from typing import Any, Mapping

import sentry_sdk
from flask import jsonify, request

from auth import optional_auth
from routes.v2.arcs import _arc_audit_paid
from routes.v2.blueprint import v2_bp
from services.rate_limits import heavy_limit, whisper_limit
# Module scope on purpose: `except DeadlineExceeded` in the upload routes
# must resolve even when the failure happens BEFORE the try body reaches
# its own imports — otherwise the handler NameErrors while handling.
from services.upload_guard import DeadlineExceeded
from routes.v2.common import (
    _LAB_MAX_AUDIO_MB,
    _PRESENTATION_MAX_MB,
    _VIDEO_UPLOAD_EXTS,
    _async_analysis_enabled,
    _is_valid_uuid,
    _pipeline_queue_enabled,
)
from services.db import db
from services.lab_recording_intake import (
    RecordingIntakeError,
    parse_recording_lane,
    parse_session_context,
)
from services.lab_audio_intake import read_recording_upload
from services.create_take import (
    CreateTakeError,
    TakeCoordinates,
    TakeProjectContext,
    attach_recording_to_project,
    ensure_project_presentation_unchanged,
    session_owned_by_principal,
    resolve_take_project,
)
from services.lab_recording_gate import (
    RecordingRejected,
    require_analyzable_recording,
)
from services.lab_analysis_dispatch import (
    AnalysisInputs,
    CompletedAnalysis,
    FailedIdealTextAnalysis,
    PendingAnalysis,
    dispatch_recording_analysis,
)
from services.lab_recording_persistence import (
    RecordingPersistenceError,
    persist_recording_row,
    persist_session_metadata,
    store_recording_audio,
)
from services.lab_recording_response import build_completed_recording_response
from services.project_ownership import GUEST_OWNER_HEADER
from services.project_repository import ProjectRepository
from services.take_lifecycle import TakeLifecycleError, register_attempt
from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)

from config import Config

logger = logging.getLogger(__name__)
config = Config()


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
                         key is the user's own self-report and may be shown to
                         the coach. No inferred psychological state is added.
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


@dataclass(frozen=True)
class PreparedLabUpload:
    form: Mapping[str, Any]
    project: TakeProjectContext
    audio_file: Any
    audio_bytes: bytes
    context_document: dict | None
    deadline: Any
    recording_kind: str
    paired_take_id: str | None
    session_context: dict[str, Any]
    gate: dict[str, Any]


@dataclass(frozen=True)
class PersistedLabTake:
    session_id: str
    recording_id: str
    bucket: str
    storage_key: str
    audio_url: str
    duration_seconds: int
    uploader_id: str | None
    coordinates: TakeCoordinates
    canonical_attempt_registered: bool
    phase1_boundary_registered: bool


def _is_data_foundation_canary_owner(
    user_id: str | None,
    owner_principal_id: str | None = None,
) -> bool:
    """Return true only for the authenticated founder during canary."""
    if not user_id or not config.DATA_FOUNDATION_CANARY_ENABLED:
        return False
    payload = getattr(request, "token_payload", None)
    email = str((payload or {}).get("email") or "").strip().lower()
    founder_email = str(config.ADMIN_EMAIL or "").strip().lower()
    approved_email = str(
        config.MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL or ""
    ).strip().lower()
    expected_principal = str(
        config.MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID or ""
    ).strip().lower()
    supplied_principal = str(owner_principal_id or "").strip().lower()
    return bool(
        email
        and founder_email
        and approved_email
        and email == founder_email == approved_email
        and expected_principal
        and supplied_principal == expected_principal
    )


def _intake_error(error: Exception) -> RecordingIntakeError:
    return RecordingIntakeError("INVALID_INPUT", str(error), 422)


def _seed_domain_vocabulary(
    session_context: dict[str, Any],
    user_id: str | None,
) -> None:
    if not user_id:
        return
    try:
        from services.domains import resolve_whisper_vocab
        domain = (db.get_user_profile(user_id) or {}).get("domain")
        session_context["domain_vocabulary"] = resolve_whisper_vocab(
            session_context.get("domain_vocabulary"), domain,
        )
    except Exception as error:
        logger.warning("lab: domain-vocab autoseed failed: %s", error)


def _prepare_lab_upload(
    form: Mapping[str, Any],
    project: TakeProjectContext,
    user_id: str | None,
) -> PreparedLabUpload:
    recording_upload = read_recording_upload(
        request.files,
        content_length=request.content_length,
        max_audio_mb=_LAB_MAX_AUDIO_MB,
        context_max_mb=getattr(config, "CONTEXT_DOC_MAX_MB", 25),
        video_extensions=_VIDEO_UPLOAD_EXTS,
    )
    lane = parse_recording_lane(form, is_valid_uuid=_is_valid_uuid)
    try:
        session_context = parse_session_context(
            form, parse_vocabulary=_parse_lab_vocabulary,
        )
    except Exception as error:
        from services.intake_context import IntakeContextError
        if isinstance(error, IntakeContextError):
            raise _intake_error(error) from error
        raise
    ensure_project_presentation_unchanged(
        project, session_context, database=db,
    )
    _seed_domain_vocabulary(session_context, user_id)
    gate = require_analyzable_recording(
        recording_upload.audio_bytes,
        database=db,
        project_id=project.project_id,
        owner_principal_id=project.principal.id,
        user_id=user_id,
        log=logger,
    )
    return PreparedLabUpload(
        form=form,
        project=project,
        audio_file=recording_upload.audio_file,
        audio_bytes=recording_upload.audio_bytes,
        context_document=recording_upload.context_document,
        deadline=recording_upload.deadline,
        recording_kind=lane.recording_kind,
        paired_take_id=lane.paired_session_id,
        session_context=session_context,
        gate=gate,
    )


def _persist_context_document(upload: PreparedLabUpload) -> None:
    document = upload.context_document
    if not document:
        return
    stored = db.upsert_arc_context_document(
        upload.project.project_id,
        document["text"],
        document["pages"],
        document["chars"],
        filename=document.get("filename"),
        truncated=document["truncated"],
    )
    if not stored:
        logger.warning(
            "lab: context document was not persisted project=%s",
            upload.project.project_id,
        )


def _persist_lab_take(
    upload: PreparedLabUpload,
    user_id: str | None,
) -> PersistedLabTake:
    authorization = ProcessingAuthorizationService(db)
    acquisition_principal_id = authorization.resolve_acquisition_principal(
        upload.project.principal.id,
        user_id=str(user_id) if user_id else None,
    )
    stored = store_recording_audio(
        upload.audio_file,
        upload.audio_bytes,
        upload_key=upload.project.idempotency_key,
        owner_principal_id=upload.project.principal.id,
        acquisition_principal_id=acquisition_principal_id,
        user_id=user_id,
        database=db,
        deadline=upload.deadline,
        log=logger,
    )
    phase1_boundary_registered = False
    try:
        boundary = authorization.finalize_recording(
            attempt_id=stored.session_id,
            acquisition_principal_id=acquisition_principal_id,
            project_id=upload.project.project_id,
            recording_id=stored.recording_id,
            upload_idempotency_key=upload.project.idempotency_key,
            storage_provider=stored.storage_provider,
            bucket=stored.bucket,
            object_key=stored.storage_key,
            byte_size=len(upload.audio_bytes),
            content_type=stored.content_type,
            exact_bytes_sha256=stored.exact_bytes_sha256,
            verification_method=stored.verification_method,
        )
        phase1_boundary_registered = boundary is not None
    except Exception:
        try:
            authorization.queue_orphan(
                acquisition_principal_id=acquisition_principal_id,
                storage_provider=stored.storage_provider,
                bucket=stored.bucket,
                object_key=stored.storage_key,
                exact_bytes_sha256=stored.exact_bytes_sha256,
                reason_code="PHASE1_BOUNDARY_FAILED",
            )
        except Exception:
            pass
        raise
    persist_session_metadata(
        stored.session_id,
        upload.session_context,
        flow_tags=_recording_flow_tags(upload.form),
        duration_seconds=upload.gate.get("duration_sec"),
        user_id=user_id,
        database=db,
    )
    coordinates = attach_recording_to_project(
        upload.project,
        recording_id=stored.session_id,
        recording_kind=upload.recording_kind,
        paired_take_id=upload.paired_take_id,
        database=db,
    )
    _persist_context_document(upload)
    recording_row = persist_recording_row(
        form=upload.form,
        session_id=stored.session_id,
        recording_id=stored.recording_id,
        storage_key=stored.storage_key,
        audio_url=stored.audio_url,
        gate=upload.gate,
        user_id=user_id,
        arc_id=coordinates.project_id,
        take_index=coordinates.take_index,
        database=db,
        log=logger,
    )
    canonical_attempt_registered = _is_data_foundation_canary_owner(
        user_id, upload.project.principal.id,
    )
    if canonical_attempt_registered:
        try:
            register_attempt(
                database=db,
                attempt_id=stored.session_id,
                owner_principal_id=upload.project.principal.id,
                project_id=coordinates.project_id,
                upload_idempotency_key=upload.project.idempotency_key,
                recording_id=stored.recording_id,
                storage_bucket=stored.bucket,
                storage_key=stored.storage_key,
                recording_kind=upload.recording_kind,
            )
        except TakeLifecycleError as error:
            logger.error(
                "lab: canonical recording attempt failed sid=%s: %s",
                stored.session_id,
                error,
            )
            raise RecordingPersistenceError(
                "Failed to register recording attempt"
            ) from error
    return PersistedLabTake(
        session_id=stored.session_id,
        recording_id=stored.recording_id,
        bucket=stored.bucket,
        storage_key=stored.storage_key,
        audio_url=stored.audio_url,
        duration_seconds=recording_row.duration_seconds,
        uploader_id=recording_row.uploader_id,
        coordinates=coordinates,
        canonical_attempt_registered=canonical_attempt_registered,
        phase1_boundary_registered=phase1_boundary_registered,
    )


def _analysis_response(
    upload: PreparedLabUpload,
    take: PersistedLabTake,
    user_id: str | None,
) -> tuple[dict, int]:
    upload.deadline.check("analyze")
    spark_enabled = str(upload.form.get("spark") or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    dispatch = dispatch_recording_analysis(
        AnalysisInputs(
            session_id=take.session_id,
            user_id=take.uploader_id,
            recording_id=take.recording_id,
            audio_bytes=upload.audio_bytes,
            filename=upload.audio_file.filename or "lab.webm",
            session_context=upload.session_context,
            parent_audio_url=take.audio_url,
            recording_kind=upload.recording_kind,
            paired_session_id=upload.paired_take_id,
            arc_id=take.coordinates.project_id,
            take_index=take.coordinates.take_index,
            arc_take_count=take.coordinates.take_count,
            spark_enabled=spark_enabled,
            bucket=take.bucket,
            storage_key=take.storage_key,
            duration_seconds=take.duration_seconds,
            canonical_attempt_registered=(
                take.canonical_attempt_registered
            ),
            phase1_boundary_registered=take.phase1_boundary_registered,
        ),
        database=db,
        queue_enabled=_pipeline_queue_enabled,
        async_enabled=_async_analysis_enabled,
        audit_paid_for_arc=_arc_audit_paid,
        log=logger,
    )
    if isinstance(dispatch, PendingAnalysis):
        payload = dict(dispatch.payload)
        payload["project_id"] = take.coordinates.project_id
        return payload, 202
    if isinstance(dispatch, FailedIdealTextAnalysis):
        payload = dict(dispatch.payload)
        payload["project_id"] = take.coordinates.project_id
        # A terminal domain state, not an HTTP transport failure: the take and
        # its feedback were persisted, while the body explicitly says the
        # required document did not succeed.
        return payload, 200
    if not isinstance(dispatch, CompletedAnalysis):
        raise RuntimeError("analysis dispatch returned an invalid result")
    payload = build_completed_recording_response(
        session_id=take.session_id,
        recording_id=take.recording_id,
        session_context=upload.session_context,
        readout=dispatch.readout,
        sent_to_coach=dispatch.sent_to_coach,
        arc_id=take.coordinates.project_id,
        take_index=take.coordinates.take_index,
        take_count=take.coordinates.take_count,
        duration_seconds=take.duration_seconds,
        user_id=user_id,
        database=db,
        audit_paid_for_arc=_arc_audit_paid,
        log=logger,
    )
    payload["project_id"] = take.coordinates.project_id
    return payload, 201


def _duplicate_take_response(context: TakeProjectContext) -> dict[str, Any]:
    duplicate = context.duplicate_take or {}
    return {
        "duplicate": True,
        "session_id": duplicate.get("id"),
        "project_id": context.project_id,
        "arc_id": context.project_id,
        "take_index": duplicate.get("take_index"),
        "take_count": duplicate.get("take_index"),
    }


def _owned_recording_session(session_id: str) -> dict | None:
    """Return a Take only when the request proves its canonical owner."""
    session = db.v2_get_session_by_id(session_id)
    if not session_owned_by_principal(
        session,
        repository=ProjectRepository(db),
        user_id=getattr(request, "user_id", None),
        guest_token=request.headers.get(GUEST_OWNER_HEADER),
    ):
        return None
    return session


def _require_session_processing_authority(session: dict, operation: str) -> None:
    service = ProcessingAuthorizationService(db)
    if not service.enforced:
        return
    principal_id = str(session.get("owner_principal_id") or "")
    if not principal_id and session.get("user_id"):
        principal = ProjectRepository(db).owner_for_user(str(session["user_id"]))
        principal_id = principal.id
    if not principal_id:
        raise ProcessingAuthorizationError(
            "PROCESSING_PRINCIPAL_UNRESOLVED",
            "The recording owner could not be resolved.", 403,
        )
    acquisition_principal_id = service.resolve_acquisition_principal(
        principal_id,
        user_id=str(session.get("user_id") or "") or None,
        recording_id=str(session.get("recording_id") or "") or None,
    )
    service.require_current(acquisition_principal_id, operation=operation)


@v2_bp.route("/lab/recordings", methods=["POST"])
@whisper_limit
@optional_auth
def v2_lab_create_recording():
    """Create one strictly owned, project-scoped Take and analyze it."""
    session_id = None
    try:
        form = request.form or {}
        user_id = getattr(request, "user_id", None)
        project = resolve_take_project(
            form,
            user_id=user_id,
            guest_token=request.headers.get(GUEST_OWNER_HEADER),
            database=db,
        )
        service = ProcessingAuthorizationService(db)
        service.require_current(
            service.resolve_acquisition_principal(
                project.principal.id,
                user_id=str(user_id) if user_id else None,
            ),
            operation="recording",
        )
        if project.duplicate_take:
            return jsonify(_duplicate_take_response(project)), 200
        upload = _prepare_lab_upload(form, project, user_id)
        persisted = _persist_lab_take(upload, user_id)
        session_id = persisted.session_id
        payload, status = _analysis_response(upload, persisted, user_id)
        return jsonify(payload), status
    except (CreateTakeError, RecordingIntakeError) as error:
        return jsonify({"code": error.code, "error": error.message}), error.status
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status
    except RecordingRejected as error:
        return jsonify({
            "code": "RECORDING_REJECTED",
            "error": "No speech detected — try recording again.",
            "gate": error.gate,
        }), 422
    except RecordingPersistenceError as error:
        return jsonify({"code": "V2_ERROR", "error": error.message}), 500
    except DeadlineExceeded as error:
        logger.warning("lab/recordings POST deadline: %s", error)
        return jsonify({
            "code": "PROCESSING_TIMEOUT",
            "error": "That recording is taking longer than expected — "
                     "it's still processing, check back shortly.",
            "session_id": session_id,
        }), 504
    except Exception as error:
        logger.error("lab/recordings POST failed: %s", error, exc_info=True)
        sentry_sdk.capture_exception(error)
        return jsonify({
            "code": "V2_ERROR", "error": "Failed to process recording",
        }), 500


@v2_bp.route("/lab/recordings/<session_id>/readout", methods=["GET"])
@optional_auth
def v2_guest_get_recording_readout(session_id):
    """Read one Take after verifying its authenticated or Guest ID owner."""
    if not _is_valid_uuid(session_id):
        return jsonify({
            "code": "INVALID_INPUT", "error": "session_id must be a valid UUID",
        }), 400
    try:
        session = _owned_recording_session(session_id)
        if not session:
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
        if _an_state in ("failed", "failed_ideal_text_unconfirmed"):
            return jsonify({
                "session_id": session_id, "state": _an_state,
                "analysis_state": _an_state, "readout": None,
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
    session = _owned_recording_session(session_id)
    if not session:
        return jsonify({"code": "SESSION_NOT_FOUND",
                        "error": "Recording not found"}), 404
    try:
        _require_session_processing_authority(session, "manual_processing_retry")
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status
    from services.pipeline_jobs import retry_failed_session_job
    job = retry_failed_session_job(
        session_id, str(session.get("user_id") or "guest"))
    if not job:
        return jsonify({"code": "RETRY_UNAVAILABLE",
                        "error": "Processing could not be restarted"}), 409
    return jsonify({
        "session_id": session_id,
        "state": "processing",
        "job_id": job.get("id"),
    }), 202


@v2_bp.route(
    "/lab/recordings/<session_id>/retry-ideal-text", methods=["POST"])
@optional_auth
def v2_retry_recording_ideal_text(session_id):
    """Retry only Take 1 document creation from stored analysis artifacts.

    This endpoint cannot re-upload or re-transcribe: its durable job payload
    contains session/project identity only and runs the Ideal Text assembler
    directly against persisted snippets/transcript rows.
    """
    if not _is_valid_uuid(session_id):
        return jsonify({"code": "INVALID_INPUT",
                        "error": "session_id must be a valid UUID"}), 400
    session = _owned_recording_session(session_id)
    if not session:
        return jsonify({"code": "SESSION_NOT_FOUND",
                        "error": "Recording not found"}), 404
    try:
        _require_session_processing_authority(session, "ideal_text_retry")
    except ProcessingAuthorizationError as error:
        return jsonify({"code": error.code, "error": error.message}), error.status
    arc_id = session.get("arc_id")
    take_index = session.get("take_index")
    if (not arc_id or isinstance(take_index, bool) or take_index != 1
            or session.get("recording_kind") == "read"):
        return jsonify({
            "code": "IDEAL_TEXT_RETRY_UNAVAILABLE",
            "error": "Ideal Text retry is available for Take 1 only",
        }), 409

    from services.ideal_text_confirmation import confirmed_ideal_text

    confirmed = confirmed_ideal_text(
        db.get_coach_arc_ideal_text(str(arc_id)))
    if confirmed:
        db.set_session_analysis_state(session_id, "ready")
        if session.get("user_id"):
            try:
                from services.arc_notifications import fire_ideal_version_ready

                fire_ideal_version_ready(
                    db,
                    session.get("user_id"),
                    arc_id,
                    confirmed.get("version") or 1,
                    spoken_take_count=1,
                )
            except Exception:
                pass
        return jsonify({
            "session_id": session_id,
            "state": "ready",
            "already_confirmed": True,
        }), 200

    state = session.get("analysis_state")
    if state not in ("failed_ideal_text_unconfirmed", "processing"):
        return jsonify({
            "code": "IDEAL_TEXT_RETRY_UNAVAILABLE",
            "error": "Ideal Text retry is not available for this take",
        }), 409

    from services.pipeline_jobs import enqueue_ideal_text_retry_job

    job = enqueue_ideal_text_retry_job(
        session_id=session_id,
        user_id=session.get("user_id"),
        arc_id=str(arc_id),
        take_index=1,
    )
    if not job:
        return jsonify({
            "code": "IDEAL_TEXT_RETRY_UNAVAILABLE",
            "error": "Ideal Text creation could not be restarted",
        }), 503
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
