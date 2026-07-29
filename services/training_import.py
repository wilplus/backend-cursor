"""Training-audio import (founder 2026-07-28) — bulk audio in, coach-reviewable
pieces out, WITHOUT minting a project the speaker owns.

THE ASK. "Can I upload numerous audio files and have them only chopped into
pieces for the coach — a tick that says this is training data, not a new
project?" This is that lane.

WHAT IT DOES. Each file runs the SAME pipeline a live take runs — transcribe,
cut ≤200-char pieces, metrics, acoustic read, stars, the coach packet. Nothing
about the analysis is special-cased: an imported take and a recorded take are
indistinguishable downstream, which is the point (the corpus must match what
the model will see in production).

WHAT IT DOESN'T DO — the "tick", implemented as TWO markers:

  1. ``v2_sessions.source = 'training_import'`` (not 'audit_upload'). This one
     line is the whole isolation, because every user-facing and baseline query
     in the codebase filters ``source='audit_upload'``:
       * the user's history / project list        → import never appears
       * v2_list_user_lab_sessions                → THE baseline reader behind
         voice_confidence, delivery_stars and acoustic_read
       * the coach's live review queue            → untouched (LIVE LOOP)
     That baseline exclusion is not a nicety. Those baselines are
     SPEAKER-RELATIVE: importing fifty other people's talks under one user id
     would blend fifty voices into that user's "own norm" and quietly corrupt
     every read they get afterwards. Imports still z-score against THEMSELVES
     (the within-take path, ≥6 pieces), which is the honest reference for a
     one-off talk.

  2. ``recordings.recording_origin = 'admin_import'`` + ``source_metadata``
     (speaker label, source note, filename, importer) — the provenance the
     migration comment always anticipated but nothing ever wrote.

WHY IT STILL GETS AN ARC. The founder asked for "no project", but every coach
surface — the star review, the ideal text, breakthroughs, review-state — is
ARC-scoped, and ``get_arc_sessions`` does NOT filter source. So an import with
no arc would be analysed and then invisible to the coach, which defeats the
purpose. Each import therefore gets its own single-take arc: the coach sees a
normal review surface with zero new endpoints, and the speaker still never
sees a project, because the project LIST is source-filtered. "Not a project"
turns out to mean "an arc that isn't yours to see", not "no arc".

FENCES. AC-9 — nothing here surfaces a score; imports are not user-facing at
all. BLIND COACH — imports flow to the SAME blind labeling surface as real
takes and carry no machine verdict. LIVE LOOP — a separate source value and
its own endpoints; the live record path is untouched. NOT SYNTHETIC — this is
real human speech, so it does NOT trip the Subsystem-S wall in
learning_export (``data_origin='synthetic'``); imports are legitimate
coach-truth training material.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The session-source marker. Anything NOT 'audit_upload' is invisible to the
# user's history and to the per-speaker baseline readers — that is the entire
# isolation mechanism, so this constant is load-bearing.
IMPORT_SOURCE = "training_import"

# The recordings-row provenance marker (the value add_admin_import_fields_to_
# recordings.sql named in its own comment and nothing ever wrote).
IMPORT_ORIGIN = "admin_import"

# ── The ticks (founder 2026-07-28) ────────────────────────────────────────
# COACH-ONLY. A normal user's upload always runs everything — they are not
# offered a choice, because a half-analysed take is a broken deliverable. The
# coach building a training corpus has the opposite need: fifty files, only
# the confidence signal wanted, and the LLM layers are the whole cost.
#
#   confidence  (always on, not really a tick) transcript → pieces → acoustics
#               → acoustic read → voice-confidence → the stratified label
#               queue. This IS the corpus. Whisper is the only spend.
#   analytics   the per-piece LLM layers — topic stickiness, say-it-stronger,
#               the suggestion stars. Feeds the ADVICE model (Model 2), not
#               the confidence model. ~16 model calls per file.
#   ideal_text  best-per-slide assembly + the continuity polish. A user
#               deliverable; irrelevant to any corpus.
STAGE_CONFIDENCE = "confidence"
STAGE_ANALYTICS = "analytics"
STAGE_IDEAL_TEXT = "ideal_text"
ALL_STAGES = (STAGE_CONFIDENCE, STAGE_ANALYTICS, STAGE_IDEAL_TEXT)
DEFAULT_STAGES = (STAGE_CONFIDENCE,)


def normalize_stages(raw: Any) -> set:
    """Parse the requested stages → a set that always contains 'confidence'.

    Accepts a list, a comma-separated string, or None (→ the default).
    Unknown names are dropped rather than erroring: a newer FE sending a
    stage this build doesn't have should degrade to the stages it does,
    not fail the upload. 'confidence' is forced on because without the
    transcript and acoustics there is no take at all — un-ticking it would
    mean "store the file and do nothing", which is what a bucket is for."""
    if raw is None:
        return set(DEFAULT_STAGES)
    if isinstance(raw, str):
        parts = [p.strip() for p in raw.split(",")]
    elif isinstance(raw, (list, tuple, set)):
        parts = [str(p).strip() for p in raw]
    else:
        return set(DEFAULT_STAGES)
    picked = {p for p in parts if p in ALL_STAGES}
    picked.add(STAGE_CONFIDENCE)
    return picked


_AUDIO_EXTS = (".webm", ".mp3", ".m4a", ".wav", ".ogg", ".flac", ".mp4",
               ".aac", ".oga", ".opus")

_CONTENT_TYPES = {
    ".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".mp4": "audio/mp4",
    ".wav": "audio/wav", ".ogg": "audio/ogg", ".oga": "audio/ogg",
    ".opus": "audio/ogg", ".flac": "audio/flac", ".aac": "audio/aac",
    ".webm": "audio/webm",
}


def is_audio_filename(name: Any) -> bool:
    """Extension-based audio check for the CLI's folder walk. Pure."""
    if not isinstance(name, str) or not name.strip():
        return False
    return os.path.splitext(name)[1].lower() in _AUDIO_EXTS


def content_type_for(name: Any) -> str:
    """Best-guess content type from the filename; ffmpeg sniffs the real
    container anyway, so this only labels the stored object. Pure."""
    ext = os.path.splitext(name)[1].lower() if isinstance(name, str) else ""
    return _CONTENT_TYPES.get(ext, "audio/webm")


def build_source_metadata(*, filename: Any, speaker_label: Any = None,
                          source_note: Any = None, imported_by: Any = None,
                          imported_at: Any = None) -> dict:
    """The ``recordings.source_metadata`` blob — provenance for a corpus row.

    ``speaker_label`` is the one field worth insisting on for a multi-speaker
    corpus: without it, nothing downstream can tell whose voice a piece is,
    and a per-speaker model has no grouping key. Pure; drops empties."""
    out: dict = {"source_kind": "training_import"}
    for key, value in (("source_title", filename),
                       ("speaker_label", speaker_label),
                       ("import_notes", source_note),
                       ("imported_by", imported_by),
                       ("imported_at", imported_at)):
        if isinstance(value, str) and value.strip():
            out[key] = value.strip()
    return out


def import_training_audio(
    *,
    audio_bytes: bytes,
    filename: str,
    user_id: Optional[str],
    topic: str,
    speaker_label: Optional[str] = None,
    source_note: Optional[str] = None,
    content_type: Optional[str] = None,
    database=None,
    run_gate: bool = True,
    stages: Any = None,
    queue_per_band: int = 5,
    idempotency_key: Optional[str] = None,
) -> dict:
    """Import ONE audio file as a coach-reviewable training take.

    Returns ``{ok, session_id, arc_id, recording_id, snippet_count}`` on
    success, or ``{ok: False, reason, detail}`` when the min-content gate
    rejects the audio (silence / corrupt / too short) or a step fails. Never
    raises — a bad file in a batch must not abort the batch.

    ``run_gate`` keeps the same min-content gate the live upload runs, so junk
    never enters the corpus; a caller who has already gated can skip it.
    """
    if database is None:
        from services.db import db as database

    from services.coach_video_storage import (
        coach_media_public_url, put_coach_object_bytes,
    )

    prepared = prepare_training_import(
        audio_bytes=audio_bytes, filename=filename, user_id=user_id,
        topic=topic, speaker_label=speaker_label, source_note=source_note,
        content_type=content_type, database=database, run_gate=run_gate,
        stages=stages, idempotency_key=idempotency_key,
    )
    if not prepared.get("ok") or prepared.get("duplicate"):
        return prepared
    return run_training_import_analysis(
        prepared=prepared, audio_bytes=audio_bytes, filename=filename,
        database=database, queue_per_band=queue_per_band,
    )


def prepare_training_import(
    *,
    audio_bytes: bytes,
    filename: str,
    user_id: Optional[str],
    topic: str,
    speaker_label: Optional[str] = None,
    source_note: Optional[str] = None,
    content_type: Optional[str] = None,
    database=None,
    run_gate: bool = True,
    stages: Any = None,
    idempotency_key: Optional[str] = None,
    language: Optional[str] = None,
) -> dict:
    """Everything BEFORE the expensive analysis: gate, store the audio, write
    the session + recording rows, mark the session 'processing'.

    ``language`` — ISO-639-1 ('pl', 'de', …). None = auto-detect. It rides
    session_context to the transcriber; see the LANGUAGE note in
    services/openai_service.transcribe_audio for why a non-English import
    needs it (our Whisper prompt is English and biases detection).

    Split out so the HTTP route can return 202 in a second or two and run the
    analysis in a background thread (founder/FE 2026-07-28): the import is
    minutes of Whisper on a long talk, and the FE's proxy caps well below
    that. A gateway timeout on a request whose BE work then SUCCEEDS is the
    dangerous shape — the coach sees "failed", re-imports, and the corpus
    silently holds the same talk twice, labelled twice, trained on twice.

    ``idempotency_key`` closes the same hole from the other side: a retry
    carrying the key it already used returns the ORIGINAL import instead of
    creating a second one (``{"ok": True, "duplicate": True, ...}``).

    Returns the prepared context for run_training_import_analysis, or an
    ``{"ok": False, "reason": ...}`` the caller can surface. Never raises."""
    if database is None:
        from services.db import db as database

    from services.coach_video_storage import (
        coach_media_public_url, put_coach_object_bytes,
    )

    picked_stages = normalize_stages(stages)
    topic = (topic or "").strip()
    if not topic:
        return {"ok": False, "reason": "no_topic",
                "detail": "topic is required (it labels the take for review)"}
    if not audio_bytes:
        return {"ok": False, "reason": "no_audio", "detail": "empty file"}

    # Idempotency FIRST — before the gate, the upload, and any row. A retry
    # after a proxy timeout must cost nothing and create nothing.
    idem = (str(idempotency_key).strip() if idempotency_key else "")
    if idem:
        try:
            existing = database.find_training_import_by_key(idem)
            if existing:
                ctx = existing.get("intake_context") or {}
                return {
                    "ok": True, "duplicate": True,
                    "session_id": existing.get("id"),
                    "arc_id": existing.get("arc_id"),
                    "stages": sorted(picked_stages),
                    "queue_count": len(ctx.get("label_queue") or []),
                    "filename": filename,
                }
        except Exception as e:
            # A failed lookup must not block the import; the worst case is
            # the duplicate this key existed to prevent, which is strictly
            # better than refusing a legitimate first import.
            logger.warning("training_import: idempotency lookup failed: %s", e)

    # 1. The same gate the live path runs — silence and corrupt containers are
    #    rejected identically, so the corpus can't fill with unusable rows.
    duration_sec = 0.0
    if run_gate:
        try:
            from services.min_content_gate import evaluate_min_content_bytes
            gate = evaluate_min_content_bytes(audio_bytes)
            if not gate.get("ok"):
                return {"ok": False, "reason": gate.get("reason") or "gate",
                        "detail": "min-content gate rejected the audio"}
            duration_sec = float(gate.get("duration_sec") or 0)
        except Exception as e:
            logger.warning("training_import: gate failed for %s: %s",
                           filename, e)
            return {"ok": False, "reason": "gate_error", "detail": str(e)}

    session_id = str(uuid.uuid4())
    recording_id = str(uuid.uuid4())
    # Its own single-take arc — see the module docstring on why imports get an
    # arc at all (every coach surface is arc-scoped).
    arc_id = str(uuid.uuid4())

    # 2. Store the parent audio (same bucket + key shape as a live take, so
    #    playback/offsets behave identically on the coach surfaces).
    ext = os.path.splitext(filename or "")[1].lower() or ".webm"
    parent_key = f"willab_lab/{session_id}/import_{uuid.uuid4().hex}{ext}"
    try:
        from config import Config
        bucket = getattr(Config, "COACH_FEEDBACK_VIDEO_BUCKET",
                         "coach_feedback_videos")
        put_coach_object_bytes(
            bucket, parent_key, audio_bytes,
            content_type or content_type_for(filename),
        )
        parent_url = (coach_media_public_url(parent_key)
                      or f"s3://{bucket}/{parent_key}")
    except Exception as e:
        logger.error("training_import: upload failed for %s: %s", filename, e)
        return {"ok": False, "reason": "upload_failed", "detail": str(e)}

    # 3. Session — marked training_import so it never reaches the speaker's
    #    project list OR their acoustic baseline (the load-bearing line).
    session_context = {"topic": topic}
    if speaker_label:
        session_context["speaker_label"] = str(speaker_label).strip()
    if idem:
        session_context["import_key"] = idem
    if language and str(language).strip():
        session_context["language"] = str(language).strip().lower()
    try:
        database.v2_create_guest_session(session_id)
        database.set_session_intake_context(session_id, session_context)
        database.set_session_source(session_id, IMPORT_SOURCE)
        if user_id:
            database.set_session_user_id(session_id, str(user_id))
        database.set_session_arc(session_id, arc_id, 1)
        # The job state the FE polls (reuses the async-analysis lane the live
        # path already has: processing → ready | failed).
        try:
            database.set_session_analysis_state(session_id, "processing")
        except Exception:
            pass
        try:
            database.set_session_presentation_duration(session_id, duration_sec)
        except Exception:
            pass   # duration is metadata, never a reason to lose the import
    except Exception as e:
        logger.error("training_import: session setup failed for %s: %s",
                     filename, e)
        return {"ok": False, "reason": "session_failed", "detail": str(e)}

    # 4. Recording row with the provenance the schema always anticipated.
    from datetime import datetime, timezone
    rec_payload = {
        "id": recording_id,
        "user_id": str(user_id) if user_id else None,
        "session_v2_id": session_id,
        "storage_path": parent_key,
        "audio_url": parent_url,
        "duration": int(round(duration_sec)),
        "recording_origin": IMPORT_ORIGIN,
        "source_metadata": build_source_metadata(
            filename=filename, speaker_label=speaker_label,
            source_note=source_note, imported_by=str(user_id or ""),
            imported_at=datetime.now(timezone.utc).isoformat(),
        ),
    }
    try:
        database.create_recording(rec_payload)
    except Exception as ce:
        # Pre-migration envs lack recording_origin / source_metadata — the
        # import is still worth having, just without provenance columns.
        err_low = str(ce).lower()
        if ("recording_origin" in err_low or "source_metadata" in err_low
                or "pgrst204" in err_low):
            logger.warning(
                "training_import: provenance columns missing (run "
                "migrations/add_admin_import_fields_to_recordings.sql) — "
                "importing without them",
            )
            try:
                database.create_recording({
                    k: v for k, v in rec_payload.items()
                    if k not in ("recording_origin", "source_metadata")
                })
            except Exception as e2:
                return {"ok": False, "reason": "recording_failed",
                        "detail": str(e2)}
        else:
            logger.error("training_import: create_recording failed: %s", ce)
            return {"ok": False, "reason": "recording_failed", "detail": str(ce)}
    try:
        database.v2_set_guest_session_recording(session_id, recording_id)
    except Exception as le:
        logger.warning("training_import: link recording failed: %s", le)

    return {
        "ok": True,
        "session_id": session_id,
        "arc_id": arc_id,
        "recording_id": recording_id,
        "parent_audio_url": parent_url,
        "session_context": session_context,
        "stages": sorted(picked_stages),
        "user_id": str(user_id) if user_id else None,
        "duration_sec": round(duration_sec, 1),
        "speaker_label": speaker_label or None,
        "filename": filename,
    }


def run_training_import_analysis(
    *, prepared: dict, audio_bytes: bytes, filename: str,
    database=None, queue_per_band: int = 5,
) -> dict:
    """The expensive half: analysis + the label queue. Safe to run in a
    background thread (it touches no request state) and stamps the session's
    analysis_state so the FE's poll has an answer either way."""
    if database is None:
        from services.db import db as database

    session_id = prepared["session_id"]
    arc_id = prepared["arc_id"]
    picked_stages = set(prepared.get("stages") or DEFAULT_STAGES)
    session_context = prepared.get("session_context") or {}
    user_id = prepared.get("user_id")

    # 5. The analysis — the SAME call a live take makes, with the unticked
    #    stages skipped (stages=None on the live path = everything, unchanged).
    try:
        from services.lab_recording import process_lab_recording
        readout = process_lab_recording(
            session_id=session_id,
            user_id=user_id,
            recording_id=prepared.get("recording_id"),
            audio_bytes=audio_bytes,
            filename=filename or "import.webm",
            session_context=session_context,
            parent_audio_url=prepared.get("parent_audio_url"),
            stages=picked_stages,
        ) or {}
    except Exception as e:
        logger.error("training_import: analysis failed for %s: %s",
                     filename, e, exc_info=True)
        try:
            database.set_session_analysis_state(
                session_id, "failed", error=str(e)[:400])
        except Exception:
            pass
        return {"ok": False, "reason": "analysis_failed", "detail": str(e),
                "session_id": session_id, "arc_id": arc_id}

    # 6. The label queue — spectrum-stratified, bands discarded. Persisted on
    #    the session so re-opening shows the same queue and the coach can
    #    resume a batch; the FE reads it back through the queue endpoint.
    queue_ids: list = []
    try:
        from services.confidence_labels import stratified_label_queue
        picked = stratified_label_queue(
            database.get_snippets_by_session(session_id) or [],
            per_band=queue_per_band, seed=session_id,
        )
        queue_ids = [str(p.get("id")) for p in picked if p.get("id")]
        if queue_ids:
            database.set_session_intake_context(
                session_id, {**session_context, "label_queue": queue_ids})
    except Exception as e:
        logger.warning("training_import: queue build failed for %s: %s "
                       "(non-fatal — every piece is still labellable)",
                       filename, e)

    if STAGE_IDEAL_TEXT in picked_stages:
        try:
            from services.ideal_text_block import maybe_assemble_ideal_text
            maybe_assemble_ideal_text(arc_id, database=database,
                                      require_target=False)
        except Exception as e:
            logger.warning("training_import: ideal text failed for %s: %s",
                           filename, e)

    # A zero-piece import is a FAILURE of the thing the coach asked for, and
    # must not read as success (FE 2026-07-29: "worked perfectly" and
    # "silently did nothing" were identical on the wire). The audio decoded —
    # the gate measured its duration — so the loss is downstream, and the
    # reason narrows it to one line of code:
    #   NO_SPEECH_DETECTED  a transcript came back empty. On a talk that
    #                       plainly contains speech this is almost always
    #                       LANGUAGE: our Whisper prompt is English and biases
    #                       detection, so a non-English file needs `language`.
    #   NO_CANDIDATES       there WAS a transcript but the cutter kept
    #                       nothing — real, and a tuning question, not a bug.
    snippet_count = len(readout.get("snippets") or [])
    if snippet_count == 0:
        _had_text = bool((readout.get("transcript") or "").strip()) or bool(
            readout.get("segments"))
        _reason = "NO_CANDIDATES" if _had_text else "NO_SPEECH_DETECTED"
        _detail = (
            "the transcript was empty — if this audio is not in English, "
            "re-import it with a `language` code (e.g. pl)"
            if _reason == "NO_SPEECH_DETECTED" else
            "the audio transcribed but no piece cleared the cutter"
        )
        logger.warning(
            "training_import: ZERO pieces for %s reason=%s duration=%ss",
            filename, _reason, prepared.get("duration_sec"),
        )
        try:
            database.set_session_analysis_state(
                session_id, "failed", error=f"{_reason}: {_detail}")
        except Exception:
            pass
        return {
            "ok": False, "reason": _reason, "detail": _detail,
            "session_id": session_id, "arc_id": arc_id,
            "snippet_count": 0, "queue_count": 0,
            "duration_sec": prepared.get("duration_sec"),
            "language": (session_context or {}).get("language"),
            "filename": filename,
        }

    try:
        database.set_session_analysis_state(session_id, "ready")
    except Exception:
        pass

    return {
        "ok": True,
        "session_id": session_id,
        "arc_id": arc_id,
        "recording_id": prepared.get("recording_id"),
        "snippet_count": snippet_count,
        "queue_count": len(queue_ids),
        "stages": sorted(picked_stages),
        "duration_sec": prepared.get("duration_sec"),
        "speaker_label": prepared.get("speaker_label"),
        "filename": filename,
    }
