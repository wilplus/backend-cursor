"""willab beta — Lab recording pipeline → Readout payload (contract §3.3).

The engine the Lab upload handler calls AFTER the min-content gate
passes + the parent audio is stored. Auth-model-independent: it takes
already-decoded inputs (bytes + session_id + session_context dict +
a stored parent_audio_url) and returns the §3.3 Readout payload. The
thin route owns multipart parsing + guest/auth + storage.

Pipeline:
  decode once
  → Whisper the WHOLE recording once (verbose_json segments, vocab-primed)
  → cut the word-timestamp stream into canonical ≤200-character pieces
     (slide boundaries first for deck takes)
  → analyze every exact text/audio piece
  → score_snippets_stickiness (one batch call)
  → create one charisma_snippets row per piece (parent+offset model)
  → assemble the §3.3 Readout payload

LLM layers remain best-effort, but canonical piece construction is required:
missing word timestamps fail processing visibly instead of activating a
different definition of a feedback moment.

Pure contract helpers are split out + unit-tested without the audio stack;
only process_lab_recording does the I/O.
"""
from __future__ import annotations

import logging
from typing import Optional

from services.recording_state import RecordingState
from services.recording_piece_analysis import (
    PiecesCanonicalUnavailable,
    analyze_canonical_pieces,
    build_canonical_pieces as _build_canonical_pieces,
)
from services.recording_feedback_scoring import (
    compute_overall_ranking as _compute_overall_ranking,
    score_recording_feedback,
)
from services.recording_persistence import persist_recording_snippets
from services.recording_transcript_persistence import persist_recording_transcript
from services.recording_transcription import (
    WHISPER_MAX_BYTES as _WHISPER_MAX_BYTES,
    merge_slide_vocabulary as _merge_slide_vocab,
    transcribe_recording,
)
from services.readout_snippets import (
    prepare_readout_snippets,
    replay_applied_upgrades,
)
from services.readout_context import (
    attach_readout_context,
    attach_suggestions_to_chunks as _attach_suggestions_to_chunks,
)

__all__ = [
    "_WHISPER_MAX_BYTES",
    "_merge_slide_vocab",
    "_build_canonical_pieces",
    "_compute_overall_ranking",
    "PiecesCanonicalUnavailable",
    "process_lab_recording",
    "replay_applied_upgrades",
    "_attach_suggestions_to_chunks",
]


logger = logging.getLogger(__name__)


# Map services.audio_metrics output keys → the §3.3 Readout feature
# names. (Some differ: speech_rate=wpm, mean_pause=pause_ms,
# loudness_range=dynamic_db.) mean_pause stays in MILLISECONDS here; the
# FE converts to seconds at its mapper (see build_readout_features).
_FEATURE_MAP = {
    "f0_mean": "f0_mean",
    "f0_sd": "f0_sd",
    "speech_rate": "wpm",
    "mean_pause": "pause_ms",
    "pause_ratio": "pause_ratio",
    "loudness_range": "dynamic_db",
    "voiced_ratio": "voiced_ratio",
    "f0_slope": "f0_slope",
    "pause_regularity": "pause_regularity",
    "intensity_envelope": "intensity_envelope",
    "f0_mid_end_delta": "f0_mid_end_delta",
}


def build_readout_features(metrics: Optional[dict]) -> dict:
    """Map an audio_metrics dict to the §3.3 feature block.

    Returns the stable feature dict (every contract key present, value or
    None) so the FE renders one shape. Pure.

    UNITS (B2 — the pause unit is now locked in the field NAME to end the
    ms↔s ping-pong that produced "mean pause 253.3s"):
      • mean_pause          — raw pause_ms, MILLISECONDS (legacy; the FE
        currently /1000s it). Kept for back-compat during FE migration.
      • mean_pause_seconds  — display-ready SECONDS (this BE converts it
        once). Self-describing: the FE should read THIS and render it raw,
        then drop its own /1000 on BOTH surfaces (ReadoutCard +
        CoachSnippetReviewCard). After that, `mean_pause` can be removed.
    Do NOT make `mean_pause` itself seconds — that double-converts against
    the FE's current /1000 (tried in BE PR #32, reverted). The fix is the
    NEW, explicitly-named field, not changing the old one's value.
    """
    m = metrics or {}
    out = {
        out_key: m.get(src_key)
        for out_key, src_key in _FEATURE_MAP.items()
    }
    mp_ms = out.get("mean_pause")
    out["mean_pause_seconds"] = (
        round(mp_ms / 1000.0, 1) if isinstance(mp_ms, (int, float)) else None
    )
    # Display-ready "speed" percentage so the FE renders e.g. 100 -> "100%"
    # without owning the unit decision. Anchor: 125 wpm = 100% (calm/clear
    # public-speaking pace); proportional for any other wpm — so 90 wpm shows
    # 72%, 150 shows 120%, etc. speech_rate keeps the raw wpm for training /
    # any caller that still needs the absolute number.
    sr_wpm = out.get("speech_rate")
    out["speech_rate_pct"] = (
        round((sr_wpm / 125.0) * 100) if isinstance(sr_wpm, (int, float)) else None
    )
    return out


def _has_voice_metrics(features: Optional[dict]) -> bool:
    """True when a snippet's §3.3 features carry at least one real ACOUSTIC
    value (pitch / volume / voicedness) — i.e. the analyzer found voiced speech.
    speech_rate is EXCLUDED (it needs the Whisper transcript, not the acoustics),
    so a transcription hiccup alone never reads as 'no voice'."""
    f = features or {}
    return any(
        isinstance(f.get(k), (int, float))
        for k in ("f0_mean", "loudness_range", "voiced_ratio")
    )


def build_readout_payload(
    snippets_data: list,
    stickiness_list: list,
) -> dict:
    """Assemble the §3.3 Readout payload from per-snippet data + the
    parallel stickiness list. Pure — unit-tested.

    ``snippets_data`` items: {id, index, transcript, audio_ref,
    start_offset_ms, duration_ms, metrics}.
    ``stickiness_list`` items (parallel by snippet_id): {snippet_id,
    composite, comment}.
    """
    sticky_by_id = {}
    for s in (stickiness_list or []):
        if isinstance(s, dict) and s.get("snippet_id") is not None:
            sticky_by_id[s["snippet_id"]] = s

    out_snippets: list = []
    for i, sd in enumerate(snippets_data or []):
        sid = sd.get("id")
        sticky = sticky_by_id.get(sid) or {}
        out_snippets.append({
            "id": sid,
            "index": sd.get("index", i + 1),
            "transcript": sd.get("transcript") or "",
            # Resolved: a writer missing its public-URL env leaves an
            # s3:// fallback here, and an <audio src> can't play that
            # (founder 2026-08-10 — the dead master player).
            "audio_ref": _playable(sd.get("audio_ref")),
            "start_offset_ms": sd.get("start_offset_ms"),
            "duration_ms": sd.get("duration_ms"),
            "features": build_readout_features(sd.get("metrics")),
            "stickiness": {
                "composite": sticky.get("composite"),
                "comment": sticky.get("comment"),
            },
        })
    return {
        "snippets": out_snippets,
        # The FULL-take audio (parent+offset model — every snippet's audio_ref
        # is the parent recording URL); mirrors the re-read payload's field so
        # the FE section playback works on the immediate 201 too.
        "parent_audio_ref": (
            out_snippets[0].get("audio_ref") if out_snippets else None
        ),
        # False → the FE shows the soft "voice metrics unavailable" notice
        # instead of an empty/broken metrics block. True when >=1 snippet has
        # real acoustic data.
        "voice_metrics_available": any(
            _has_voice_metrics(s.get("features")) for s in out_snippets
        ),
    }


def _voice_metrics_diagnostic(
    snippets_data: list,
    segments: list,
) -> tuple[bool, str]:
    """Classify canonical-piece acoustic availability for telemetry only."""
    voiced = any(
        _has_voice_metrics(build_readout_features(snippet.get("metrics")))
        for snippet in snippets_data
    )
    if not snippets_data:
        return voiced, "no_snippets"
    if not voiced:
        return voiced, "no_voiced_speech"
    if not segments:
        return voiced, "ok_acoustics_no_transcript"
    return voiced, "ok"


def _full_transcript_text(segments: list, words_all: list) -> str:
    """Prefer Whisper segment text, falling back to its word stream."""
    segment_text = " ".join(
        (segment.get("text") or "").strip()
        for segment in (segments or [])
        if isinstance(segment, dict) and (segment.get("text") or "").strip()
    ).strip()
    if segment_text:
        return segment_text
    return " ".join(
        (word.get("word") or "").strip()
        for word in (words_all or [])
        if isinstance(word, dict) and (word.get("word") or "").strip()
    ).strip()


def _playable(ref):
    """One storage ref → a playable URL. Healthy public URLs pass through;
    the s3:// fallbacks a mis-configured writer leaves behind get signed
    against their own bucket (services/audio_ref_resolver — the #378
    branch, hoisted). Founder 2026-08-10: the master player was dead on
    every user surface because only the coach queue resolved."""
    from services.audio_ref_resolver import resolve_playable_ref
    return resolve_playable_ref(ref)


def _coach_prefill_enabled() -> bool:
    """Coach-comment pre-fill (the AI-Commentator draft). Default OFF (founder
    2026-07-14): the coach writes the key-moment comment from scratch and the
    system learns from that. Set COACH_PREFILL_ENABLED=1 to restore the
    machine pre-fill without a redeploy."""
    import os
    return (os.getenv("COACH_PREFILL_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


class _SkipAnalytics(Exception):
    """Internal: skip an optional LLM block when its stage is unticked. Rides
    the block's existing best-effort try/except, so no new control flow is
    introduced on the live path (where stages is None and this never fires)."""


def process_lab_recording(
    *,
    session_id: str,
    user_id: Optional[str],
    recording_id: str,
    audio_bytes: bytes,
    filename: str,
    session_context: Optional[dict],
    parent_audio_url: str,
    recording_kind: str = "spoken",
    paired_session_id: Optional[str] = None,
    stages: Optional[set] = None,
) -> dict:
    """Run the full pipeline → §3.3 Readout payload.

    Assumes the min-content gate already passed and the parent audio is
    already stored at ``parent_audio_url`` (the shared audio_ref for
    every snippet, parent+offset model). Persists one charisma_snippets
    row per canonical piece. Returns {"snippets": [...]}.

    ``recording_kind`` (founder 2026-07-14) — 'spoken' (the original take)
    or 'read' (the re-read of the suggestion-corrected text). Stamped on
    every snippet's metrics so the coach sees, per snippet, which delivery
    it was; the acoustic pipeline is identical for both.

    ``paired_session_id`` (founder 2026-07-17) — for a 'read', its parent
    SPOKEN take. A re-read is 1–2 pieces, far too few to z-score against
    itself, so the parent take's pieces become the acoustic reference: the
    coach's needle reads honestly on re-reads instead of pegging neutral.

    ``stages`` (founder 2026-07-28, training-import ticks) — which OPTIONAL
    layers to run. None (the default, and every live caller) = ALL of them,
    byte-identical to before. A set omitting 'analytics' skips the per-piece
    LLM layers (topic stickiness, say-it-stronger); the transcript, pieces,
    acoustics, acoustic read and confidence composite always run because they
    ARE the recording. The coach-only import lane uses this to build a
    confidence corpus for the price of Whisper alone — on a 50-file batch the
    LLM layers are the difference between minutes and hours. See
    services/training_import.py.
    """
    # None = every stage (the live path). A provided set opts in explicitly.
    _run_analytics = stages is None or "analytics" in stages
    # ── F1 (2026-07-26): put slide taps on the AUDIO clock, ONCE, before
    # anything reads them. The FE measures the recorder warm-up offset and
    # sends it as slide_clock_offset_ms; subtracting it here means every
    # downstream consumer (per-slide transcripts, the piece cutter, stickiness)
    # inherits the corrected timeline without threading a parameter through
    # their signatures. No offset, or an out-of-bounds one → unchanged, so
    # takes from older clients behave exactly as before.
    try:
        from services.slide_word_split import context_with_clock_offset
        session_context = context_with_clock_offset(session_context)
    except Exception as _off_err:      # LIVE LOOP: never break a recording
        logger.warning("clock-offset correction skipped: %s", _off_err)

    _rec_kind = recording_kind if recording_kind in ("spoken", "read") \
        else "spoken"
    from services.audio_metrics import decode_audio_to_pcm
    from services.db import db

    sig = decode_audio_to_pcm(audio_bytes)
    if sig is None:
        # Diagnostic (telemetry to isolate device/PWA capture issues): the audio
        # blob couldn't be decoded — empty / truncated / unsupported codec.
        logger.warning(
            "process_lab_recording.voice_metrics_diag sid=%s status=decode_failed "
            "bytes=%d", session_id, len(audio_bytes or b""),
        )
        return {"snippets": [], "voice_metrics_available": False}

    # Stage 1 — transcription.  The frozen state makes the stage boundary
    # explicit: transcription returns a new state and cannot silently change
    # the recording context that later stages depend on.
    state = RecordingState(
        session_id=session_id,
        user_id=user_id,
        recording_id=recording_id,
        audio_bytes=audio_bytes,
        filename=filename,
        session_context=session_context,
        parent_audio_url=parent_audio_url,
        recording_kind=recording_kind,
        paired_session_id=paired_session_id,
        run_analytics=_run_analytics,
        signal=sig,
    )
    state = transcribe_recording(state, log=logger)
    # Downstream code still operates on local lists during this incremental
    # extraction.  Copy the immutable stage outputs so later normalization can
    # never mutate the state object retained for subsequent domain stages.
    segments = [
        dict(segment) if isinstance(segment, dict) else segment
        for segment in state.segments
    ]
    words_all = [
        dict(word) if isinstance(word, dict) else word
        for word in state.words_all
    ]

    # Stage 2 — canonical piece construction and acoustic enrichment. The
    # returned state keeps the raw candidate snapshot separate from derived
    # coach/user reads, preserving validation-sample independence.
    state = analyze_canonical_pieces(state, log=logger)
    _llm_budget_idx = set(state.llm_budget_indices)

    # Stage 3 — independent text and slide analysis, joined deterministically.
    state = score_recording_feedback(state, log=logger)

    # Stage 4 — persist exact canonical rows and the raw candidate corpus.
    state = persist_recording_snippets(state, database=db, log=logger)
    snippets_data = list(state.persisted_snippets)
    stickiness_list = list(state.stickiness_payload)

    # Voice-metrics diagnostic (telemetry) — distinguish WHY acoustics are empty
    # so we can isolate device/PWA capture issues before re-engaging the native
    # mic path. (decode_failed is logged at the early return above.)
    _voiced, _diag = _voice_metrics_diagnostic(snippets_data, segments)
    logger.info(
        "process_lab_recording.voice_metrics_diag sid=%s status=%s "
        "snippets=%d voiced=%s transcribed=%s",
        session_id, _diag, len(snippets_data), _voiced, bool(segments),
    )

    # Stage 5 — persist the complete slide/deckless transcript and diagnostics.
    persist_recording_transcript(state, database=db, log=logger)

    # AI-Commentator coach-note pre-fill — RETIRED by default (founder
    # 2026-07-14): "no pre-filled comment; the system should learn from what
    # the coach writes." The coach now writes the key-moment comment from
    # scratch, and the (coach_snippet_drafts.note × the snippet's acoustic
    # metrics) pair IS the training signal for the future comment-from-acoustic
    # model — no machine draft needed. Kept behind a default-OFF flag so the
    # pre-fill can be re-enabled without a redeploy if the direction changes.
    if _coach_prefill_enabled():
        try:
            from services.coach_comment_drafter import dispatch_coach_note_drafts
            _llm_ids = {
                str(snippets_data[i]["id"]) for i in _llm_budget_idx
                if i < len(snippets_data) and snippets_data[i].get("id")
            }
            dispatch_coach_note_drafts(
                session_id,
                snippets_data,
                (session_context or {}).get("slides"),
                (session_context or {}).get("slide_advances"),
                goal=(session_context or {}).get("topic"),
                llm_ids=_llm_ids,
            )
        except Exception as _draft_err:
            logger.warning(
                "process_lab_recording: coach-note draft dispatch failed "
                "sid=%s: %s", session_id, _draft_err,
            )

    # "Say It Stronger" (founder 2026-07-07) — per-snippet rewrite suggestions
    # for the user readout, replacing the raw acoustic numbers there. Same
    # fire-and-forget daemon pattern as the drafter above; the suggestions
    # appear on the readout RE-READ once generated (the 201 below carries
    # null). Best-effort: never blocks or breaks the recording.
    try:
        if not _run_analytics:
            raise _SkipAnalytics()   # import lane: no advice layers
        from services.say_it_stronger import dispatch_say_it_stronger
        from services.audio_metrics import SAMPLE_RATE
        _ctx = session_context or {}
        _full_tx = _full_transcript_text(segments, words_all)
        # Cards only for the LLM-budget pieces (cost cap) —
        # the instant view's suggestions ride the most salient moments;
        # the other pieces still carry text/audio/auto-comment.
        _sis_snips = [
            snippets_data[i] for i in sorted(_llm_budget_idx)
            if i < len(snippets_data)
        ]
        # "your average" must be the WHOLE take's, not the budget subset's
        # (the budget set is the most-activated extremes → biased mean).
        from services.say_it_stronger import aggregate_session_means
        _sis_means = aggregate_session_means(snippets_data)
        dispatch_say_it_stronger(session_id, _sis_snips, context={
            "topic": _ctx.get("topic"),
            "audience": _ctx.get("audience"),
            "strategic_context": _ctx.get("strategic_context"),
            "target_length_seconds": _ctx.get("target_length_seconds"),
            "duration_sec": (len(sig) / float(SAMPLE_RATE)) if sig is not None else None,
            "full_transcript": _full_tx,
        }, means=_sis_means)
    except Exception as _sis_err:
        logger.warning(
            "process_lab_recording: say-it-stronger dispatch failed sid=%s: %s",
            session_id, _sis_err,
        )

    return build_readout_payload(snippets_data, stickiness_list)


def build_readout_from_session(
    session_id: str,
    *,
    include_insights: bool = True,
    include_slide_scores: bool = False,
    audit_paid: bool = True,
    include_upgrade_cards: bool = True,
) -> dict:
    """Re-derive the §3.3 Readout from PERSISTED snippets — the canonical
    reader for parked-restore + history (contract: a report loads
    identically an hour later / on scroll-back).

    Reads charisma_snippets for the session, rebuilds each snippet's
    §3.3 shape from its metrics blob (features via build_readout_features
    + the persisted stickiness sub-key), in chronological order
    (start_offset_ms ASC — the honest "what happened" order).

    Post-publish (include_insights), folds the coach layer UNCONDITIONALLY —
    founder re-price 2026-07-06 RETIRES the per-take/free-intro teaser scoping
    (there is no more take-level or first-arc-ever branching here):
      - top-level ``insights_payload`` (overall_message + snippet_notes)
      - per-snippet ``coach`` {note, tag, transcript_corrected, when, examples}
        matched by snippet_id (null/[] when the note omits them)
    This is FREE for every take of every arc the instant the coach saves +
    surfaces it — no payment check. Only FOUR surfaces stay paid: the coach-
    corrected ideal text (services/best_presentation.py coach_finalized),
    the cross-take breakthroughs LIST, the game, and the snippet library —
    none of which this function serves.

    ``audit_paid`` = the ARC-level paid flag, kept ONLY as a top-level echo so
    the FE can contextualize its OWN paid-deliverable CTAs (ideal text /
    breakthroughs list / game / library) from the readout screen — it no
    longer withholds anything IN this readout. AC-9: still score-free.

    With a deck, also attaches ``slides`` (the deck), per-snippet ``slide``,
    ``presentation_ref``, and ``slide_transcripts`` — the COMPLETE per-slide 1:1
    transcript [{index, transcript, start_offset_ms, duration_ms}] so the FE can
    render each slide with exactly what was said on it (#A); omitted when there's
    nothing to surface.

    Owner-scoping is the caller's job (the route). Returns
    {"snippets": [...], "insights_payload"?: {...}, "slide_transcripts"?: [...]}.
    """
    from services.db import db

    snippets = db.get_snippets_by_session(session_id) or []

    out_snips, _edits_by_chunk = prepare_readout_snippets(
        db,
        session_id,
        snippets,
        include_insights=include_insights,
        include_slide_scores=include_slide_scores,
        include_upgrade_cards=include_upgrade_cards,
        playable=_playable,
        feature_builder=build_readout_features,
        coach_prefill_enabled=_coach_prefill_enabled,
        log=logger,
    )

    result: dict = {
        "snippets": out_snips,
        # False → FE shows the soft "voice metrics unavailable" notice (matches
        # the immediate readout; consistent on re-read / history).
        "voice_metrics_available": any(
            _has_voice_metrics(s.get("features")) for s in out_snips
        ),
        # The FULL-take audio (parent+offset model: every snippet's
        # audio_segment_path IS the parent recording URL). The FE seeks one
        # <audio> on this per section span (slide_transcripts /
        # full_transcript_chunks start_offset_ms + duration_ms). Null when
        # the session has no snippets (nothing recorded → nothing to play).
        "parent_audio_ref": _playable(
            snippets[0].get("audio_segment_path") if snippets else None
        ),
    }

    attach_readout_context(
        db,
        session_id,
        snippets,
        out_snips,
        result,
        edits_by_chunk=_edits_by_chunk,
        include_upgrade_cards=include_upgrade_cards,
        log=logger,
    )

    # Per-slide coverage ledger (Stickiness #2 (i)) — COACH-ONLY audit; parked
    # once on the first snippet's metrics at process time.
    if include_slide_scores and snippets:
        m0 = snippets[0].get("metrics")
        cov = m0.get("slide_coverage") if isinstance(m0, dict) else None
        if cov:
            result["slide_coverage"] = cov

    # audit_paid = the ARC-level paid flag — an ECHO only (kept so the FE can
    # contextualize its paid-deliverable CTAs from this screen); it no longer
    # withholds anything below (founder re-price 2026-07-06).
    result["audit_paid"] = bool(audit_paid)

    if include_insights:
        try:
            session = db.v2_get_session_by_id(session_id) or {}
        except Exception:
            session = {}
        ip = session.get("insights_payload")
        if isinstance(ip, dict):
            notes_by_id = {
                n["snippet_id"]: n
                for n in (ip.get("snippet_notes") or [])
                if isinstance(n, dict) and n.get("snippet_id")
            }
            # UNCONDITIONAL fold — free for every take of every arc the instant
            # the coach saves + surfaces it (no payment check at all).
            result["insights_payload"] = ip
            for snip in out_snips:
                cn = notes_by_id.get(snip["id"])
                if cn:
                    snip["coach"] = {
                        "note": cn.get("note"),
                        "tag": cn.get("tag"),
                        # A real coach-authored artifact (founder 2026-07-06),
                        # distinct from the immutable raw transcript above.
                        # None until the coach saves one.
                        "transcript_corrected": cn.get("transcript_corrected"),
                        # PR-2 — optional coach fields; None/[] when the
                        # note omits them (FE hides when absent). Older
                        # published payloads predate these keys → absent.
                        "when": cn.get("when"),
                        "examples": cn.get("examples") or [],
                    }
    return result
