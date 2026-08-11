"""willab beta — Lab recording pipeline → Readout payload (contract §3.3).

The engine the Lab upload handler calls AFTER the min-content gate
passes + the parent audio is stored. Auth-model-independent: it takes
already-decoded inputs (bytes + session_id + session_context dict +
a stored parent_audio_url) and returns the §3.3 Readout payload. The
thin route owns multipart parsing + guest/auth + storage.

Pipeline (synchronous, ~3-5s):
  decode once
  → Whisper the WHOLE recording once (verbose_json segments, vocab-primed)
  → segment_into_snippets → per window: features + transcript sliced from
     the Whisper segment timestamps (NOT N per-window Whisper calls — that
     would blow the sync budget)
  → score_snippets_stickiness (one batch call)
  → create one charisma_snippets row per window (parent+offset model)
  → assemble the §3.3 Readout payload

Best-effort throughout: Whisper down → empty transcripts; LLM down →
no stickiness; decode fail → empty snippets. The Readout still renders
the raw acoustic features.

Pure helpers (slice_transcript_for_window / build_readout_features /
build_readout_payload) are split out + unit-tested without the audio
stack; only process_lab_recording does the I/O.
"""
from __future__ import annotations

import logging
from typing import Optional


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


def slice_transcript_for_window(
    segments: list,
    start_ms: int,
    end_ms: int,
) -> str:
    """Join Whisper segment texts overlapping the window [start_ms, end_ms].

    ``segments`` = [{start (sec), end (sec), text}] from the whole-
    recording verbose_json. A segment counts if it overlaps the window
    at all (seg.end > start AND seg.start < end). Pure — unit-tested.
    """
    if not segments:
        return ""
    start_s = start_ms / 1000.0
    end_s = end_ms / 1000.0
    parts: list = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        s = seg.get("start")
        e = seg.get("end")
        if not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            continue
        if e > start_s and s < end_s:
            text = (seg.get("text") or "").strip()
            if text:
                parts.append(text)
    return " ".join(parts).strip()


def dedupe_window_transcripts(windows: list, segments: list) -> list:
    """Claim-once transcript attribution (founder bug #2, 2026-07-06).

    ``slice_transcript_for_window`` includes ANY overlapping Whisper segment, so
    a sentence straddling two adjacent windows appears in BOTH snippets — the
    user saw the same sentence twice. This assigns each segment to EXACTLY ONE
    window — the one with the LARGEST time-overlap (ties → the earlier window) —
    so every spoken sentence appears once, where it was mostly spoken.

    ``windows``  = [(start_ms, end_ms)] CHRONOLOGICAL (the surfaced set).
    ``segments`` = whole-recording Whisper segments [{start(s), end(s), text}].
    Returns one transcript string per window (possibly ""). Pure.
    """
    texts: list = [[] for _ in windows]
    if not windows or not segments:
        return ["" for _ in windows]
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        s = seg.get("start")
        e = seg.get("end")
        text = (seg.get("text") or "").strip()
        if not text or not isinstance(s, (int, float)) or not isinstance(e, (int, float)):
            continue
        s_ms, e_ms = s * 1000.0, e * 1000.0
        best_i = None
        best_overlap = 0.0
        for i, (w_start, w_end) in enumerate(windows):
            overlap = min(e_ms, w_end) - max(s_ms, w_start)
            if overlap > best_overlap:
                best_overlap = overlap
                best_i = i
        if best_i is not None:
            texts[best_i].append(text)
    return [" ".join(t).strip() for t in texts]


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


# OpenAI Whisper rejects uploads larger than 25MB; compress above this
# threshold (a touch under 25MB for multipart/header headroom).
_WHISPER_MAX_BYTES = 24 * 1024 * 1024


def _pieces_canonical_enabled() -> bool:
    """PIECES-CANONICAL kill-switch (founder 2026-07-14). Default ON: every
    ≤200-char transcript piece becomes a first-class charisma_snippets row
    (the moment the user reads = the moment the coach labels = the learning
    unit). Set PIECES_CANONICAL_ENABLED=0 to fall back to the legacy
    salient-window cutter (live-loop safety valve)."""
    import os
    return (os.getenv("PIECES_CANONICAL_ENABLED") or "1").strip().lower() \
        not in ("0", "false", "no")


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


def _piece_llm_budget() -> int:
    """How many pieces per take get the LLM layers (stickiness comment,
    say-it-stronger card, LLM coach-note draft). Every piece always gets
    metrics + the acoustic read + a deterministic auto-comment; the budget
    only caps the model calls so a 60-minute talk (~270 pieces) can't fire
    hundreds of LLM requests. Default 16 covers a typical 3–5-min take
    fully."""
    import os
    try:
        return max(1, int(os.getenv("WILLAB_PIECE_LLM_BUDGET") or "16"))
    except (TypeError, ValueError):
        return 16


def _merge_slide_vocab(session_context):
    """Whisper prime = domain_vocabulary + slide titles (UX Wave 4 BE-S3).

    Slide titles carry the proper nouns / key terms the speaker will say, so
    priming Whisper on them sharpens transcription — the "same mechanism as
    keywords, more precise." Case-insensitive dedup, capped so the prompt
    stays small. Returns a list or None.
    """
    ctx = session_context or {}
    terms = list(ctx.get("domain_vocabulary") or [])
    for sl in (ctx.get("slides") or []):
        if isinstance(sl, dict):
            t = (sl.get("title") or "").strip()
            if t:
                terms.append(t)
    seen, merged = set(), []
    for term in terms:
        k = (term or "").strip().lower()
        if not k or k in seen:
            continue
        seen.add(k)
        merged.append(term.strip())
        if len(merged) >= 120:
            break
    return merged or None


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
    row per window. Returns {"snippets": [...]}.

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
    from services.audio_metrics import (
        decode_audio_to_pcm, segment_into_snippets, analyze_pcm_window,
        SEGMENT_MAX_SNIPPETS,
    )
    from services.snippet_salience import (
        rank_candidates_by_salience, select_extremes_by_control,
        SALIENCE_CANDIDATE_POOL, NOTABLE_POOL_SIZE,
    )
    from services.snippet_stickiness import score_snippets_stickiness
    from services.slide_word_split import slice_words_for_window
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

    # Whisper the whole recording ONCE (best-effort), vocab-primed.
    segments: list = []
    words_all: list = []  # word-level timestamps (#6 per-slide sync)
    try:
        from io import BytesIO
        from services.openai_service import OpenAIService
        ois = OpenAIService()
        if ois.client:
            vocab = _merge_slide_vocab(session_context)
            # OpenAI Whisper rejects uploads > 25MB. Long presentation
            # recordings can exceed that, so compress oversized audio to a
            # 16kHz mono mp3 just for transcription (the acoustic pipeline
            # above still uses the full-quality original). Best-effort: fall
            # back to the original bytes if the transcode fails.
            whisper_bytes = audio_bytes
            whisper_name = filename or "lab.webm"
            if len(audio_bytes) > _WHISPER_MAX_BYTES:
                from services.audio_metrics import compress_audio_for_whisper
                compressed = compress_audio_for_whisper(audio_bytes)
                if compressed and len(compressed) < len(audio_bytes):
                    whisper_bytes = compressed
                    whisper_name = "lab.mp3"
                    logger.info(
                        "process_lab_recording: compressed audio for whisper "
                        "sid=%s %d→%d bytes", session_id,
                        len(audio_bytes), len(compressed),
                    )
            # Language hint (fix 2026-07-29): the first non-English import —
            # a Polish talk — produced zero pieces. Whisper follows its
            # prompt's language, and ours is an English disfluency primer, so
            # non-English audio needs the code passed explicitly. Absent =
            # auto-detect, exactly as the live path has always behaved.
            _lang = (session_context or {}).get("language") \
                if isinstance(session_context, dict) else None
            wres = ois.transcribe_audio(
                BytesIO(whisper_bytes), whisper_name,
                vocabulary=vocab,
                language=(str(_lang).strip() or None) if _lang else None,
                # Cost attribution (token-pricing Phase 0). recording_kind
                # splits the ledger by spoken take vs re-read — they have very
                # different durations and only spoken takes count as takes.
                usage_surface=f"whisper_{recording_kind or 'spoken'}",
                usage_user_id=user_id,
                usage_session_id=session_id,
            )
            segments = (wres or {}).get("segments") or []
            words_all = (wres or {}).get("words") or []

            # Token pricing: charge the take AFTER transcription, at the band
            # the audio actually landed in. Deliberately not a pre-flight gate —
            # the audio is already accepted and analysed by this point, so a
            # zero balance costs the user tokens, never the take (fence §6.1).
            # The record-start band endpoint is the ADVISORY half of this; this
            # is the settle. Idempotent per recording: a retried pipeline run
            # re-uses recording_id and the ledger's unique index absorbs it.
            try:
                from services.token_account import charge
                from services.token_prices import band_for_seconds
                _act = ("reread" if (recording_kind or "spoken") == "read"
                        else band_for_seconds((wres or {}).get("duration")))
                charge(str(user_id), _act, ref_id=str(recording_id))
            except Exception as _tok_err:
                logger.warning("lab: token charge failed sid=%s err=%s",
                               session_id, _tok_err)
    except Exception as e:
        logger.warning(
            "process_lab_recording.voice_metrics_diag sid=%s "
            "status=transcription_failed err=%s (acoustics still computed)",
            session_id, e,
        )
        segments = []
        words_all = []

    # Punctuation restoration (founder BE-1a, 2026-07-15): Whisper's word
    # timestamps arrive punctuation-less; the segments carry the punctuated
    # text. Restore it ONCE here — every consumer downstream (piece cutting,
    # per-slide transcripts, persisted snippet words, feedback full text,
    # ideal-text assembly) inherits punctuated tokens. Deterministic
    # two-pointer alignment (no LLM); spans untouched; best-effort — any
    # hiccup keeps the raw words (degraded, never garbled).
    if words_all and segments:
        try:
            from services.slide_word_split import restore_punctuation
            words_all = restore_punctuation(words_all, segments)
        except Exception as _punct_err:
            logger.warning(
                "process_lab_recording: punctuation restore failed sid=%s: "
                "%s (raw words kept)", session_id, _punct_err,
            )

    # Run-on sentence boundaries (founder BE-1c, 2026-07-16): Whisper
    # under-punctuates spoken run-ons; the speaker's own pauses carry the
    # missing boundary, and the word timestamps already hold them. Promote
    # qualifying pauses to full stops — punctuation + casing only, words +
    # spans strictly untouched, so every downstream consumer stays verbatim-
    # faithful. Deterministic; SENTENCE_BOUNDARY_SPLIT_ENABLED=0 kills it.
    if words_all:
        try:
            from services.slide_word_split import (
                runon_split_enabled, split_runon_sentences,
            )
            if runon_split_enabled():
                words_all = split_runon_sentences(words_all)
        except Exception as _runon_err:
            logger.warning(
                "process_lab_recording: run-on sentence split failed "
                "sid=%s: %s (words kept as-is)", session_id, _runon_err,
            )

    # ── PIECES-CANONICAL (founder 2026-07-14 — "the piece IS the moment") ──
    # With word timestamps, the take is cut into ≤200-char TEXT pieces —
    # slide tap-boundaries FIRST (a piece never crosses a slide), then the
    # char cap within each slide; deckless is the flat ≤200-char cut. EVERY
    # piece becomes a charisma_snippets row with its exact word-derived audio
    # span + its own acoustic metrics: what the user reads = what the coach
    # hears and labels = what the model learns from. The legacy acoustic
    # salient-window cutter below survives ONLY as (a) the no-word-timestamps
    # fallback (segments-only Whisper) and (b) the PIECES_CANONICAL_ENABLED=0
    # kill-switch.
    _pieces_mode = False
    _piece_list: list = []
    _slides_ctx0 = (session_context or {}).get("slides")
    if words_all and _pieces_canonical_enabled():
        from services.slide_word_split import (
            chunk_slide_words_by_chars, chunk_words_by_chars,
        )
        if _slides_ctx0:
            _piece_list = chunk_slide_words_by_chars(
                words_all, (session_context or {}).get("slide_advances"),
                _slides_ctx0,
            )
        else:
            _piece_list = chunk_words_by_chars(words_all)
        _piece_list = [pc for pc in (_piece_list or [])
                       if (pc.get("transcript") or "").strip()]
        _pieces_mode = bool(_piece_list)

    _llm_budget_idx: set = set()
    if _pieces_mode:
        # The LLM budget FIRST (needs only text length) — the most
        # acoustically-activated pieces get the model layers; but we don't have
        # metrics yet, so budget after a cheap first metrics pass below.
        # Budget 0 when analytics are off: the salience ranking still runs
        # (it is free and picks which pieces get the richer feature vector),
        # but no piece reaches an LLM layer.
        _budget_n = _piece_llm_budget() if _run_analytics else 0
        # Pass 1: FULL metrics (incl. librosa) only for pieces we MIGHT budget;
        # a piece under the 1s floor gets {}. We don't yet know the budget set,
        # so pass 1 computes the cheap acoustic core for ALL pieces (librosa
        # OFF — not needed for acoustic_read/salience/shadow), then pass 2 adds
        # librosa to the budget winners. Halves the per-piece CPU on long takes.
        prelim = []
        for pc in _piece_list:
            _p_start = int(pc.get("start_offset_ms") or 0)
            _p_dur = int(pc.get("duration_ms") or 0)
            _mtx = analyze_pcm_window(
                sig, start_offset_ms=_p_start, duration_ms=_p_dur,
                transcript=pc.get("transcript") or "", include_librosa=False,
            ) or {}
            _prov = {"index": pc.get("index")}
            if pc.get("slide_index") is not None:
                _prov["slide_index"] = pc.get("slide_index")
            _mtx["piece"] = _prov
            _mtx["recording_kind"] = _rec_kind
            prelim.append({
                "start_ms": _p_start, "dur_ms": _p_dur,
                "metrics": _mtx, "transcript": pc.get("transcript") or "",
            })
        for idx, p in enumerate(prelim, start=1):
            p["idx"] = idx

        # Budget selection (salience over the cheap core metrics).
        if len(prelim) > _budget_n:
            _budget_objs = {id(p) for p in rank_candidates_by_salience(
                prelim, top_n=_budget_n)}
            _llm_budget_idx = {
                i for i, p in enumerate(prelim) if id(p) in _budget_objs
            }
        else:
            _llm_budget_idx = set(range(len(prelim)))

        # Pass 2: librosa (MFCC/chroma) ONLY for the budget winners — they're
        # the ones whose full vector feeds the richer downstream corpus.
        for i in sorted(_llm_budget_idx):
            p = prelim[i]
            _lib = analyze_pcm_window(
                sig, start_offset_ms=p["start_ms"], duration_ms=p["dur_ms"],
                transcript=p["transcript"], include_librosa=True,
            ) or {}
            _piece_prov = p["metrics"].get("piece")
            p["metrics"] = _lib
            if _piece_prov is not None:
                p["metrics"]["piece"] = _piece_prov

        # ── Capture BEFORE the derived reads are stamped ──────────────────
        # The candidate corpus must stay RAW (validation-sample independence):
        # snapshot the raw metrics NOW, before acoustic_read/user_tone_word go
        # on, so build_candidate_rows can never persist a derived composite.
        _cap_snapshot = [dict(p["metrics"]) for p in prelim]

        # Coach potentiometer + outside-normal-range triage flag per piece —
        # deterministic acoustic-only, COACH-ONLY (metrics["acoustic_read"],
        # never on the user readout — fence-tested). The LEARNED shadow model
        # stays out of this needle by design (labels blind).
        try:
            from services.acoustic_read import (
                attach_acoustic_read, resolve_read_baseline,
            )
            # Reference priority: the speaker's own baseline → (for a re-read)
            # its PARENT take's pieces → within-take/cold-start. Without the
            # parent fallback a 1–2-piece re-read pegged the needle neutral.
            _ar_base, _ar_kind = resolve_read_baseline(
                user_id, recording_kind=_rec_kind,
                paired_session_id=paired_session_id,
            )
            attach_acoustic_read(
                prelim, baseline=_ar_base, baseline_kind=_ar_kind,
            )
        except Exception as _ar_err:
            logger.warning(
                "process_lab_recording: acoustic read failed sid=%s: %s "
                "(non-fatal)", session_id, _ar_err,
            )

        # Voice-confidence composite per piece (founder spec 2026-07-27, Jiang &
        # Pell 2017) — metrics["voice_confidence"], the DELIVERY term of the L2
        # ranking blend. Stamped AFTER _cap_snapshot on purpose: it is a derived
        # composite and the candidate corpus stays RAW.
        #
        # Capture-first: computed + persisted here regardless of the ranking
        # flag, so a validation sample can be drawn and anchored against blinded
        # human ratings BEFORE it is allowed to move a pick. The flag
        # (VOICE_CONFIDENCE_RANKING_ENABLED, default OFF) is read only at rank
        # time, in voice_confidence.rank_term.
        #
        # NOT the coach needle: acoustic_read above is untouched and remains the
        # coach's stress↔charisma potentiometer + triage flag. This one is
        # ranking-internal and never reaches the coach packet or a user payload.
        try:
            from services.voice_confidence import (
                attach_voice_confidence, enabled as _vc_enabled,
                resolve_confidence_baseline, resolve_take_sex,
            )
            if _vc_enabled():
                _vc_base, _vc_kind = resolve_confidence_baseline(
                    user_id, [p.get("metrics") for p in prelim],
                )
                # Sex routes the cue WEIGHTS (one cue reverses direction) —
                # resolved once per take, after the baseline because the
                # acoustic fallback reads the speaker's baseline mean f0.
                # Never surfaced; see services/voice_confidence.py.
                #
                # The account holder is NOT always the speaker (an import is
                # someone else's voice under the coach's user_id) — that whole
                # precedence lives in resolve_take_sex, which the backfill
                # calls too so the two can never drift.
                _vc_sex, _vc_sex_src = resolve_take_sex(
                    user_id, session_context, _vc_base,
                )
                attach_voice_confidence(
                    prelim, baseline=_vc_base, baseline_kind=_vc_kind,
                    sex=_vc_sex, sex_source=_vc_sex_src,
                )
        except Exception as _vc_err:
            logger.warning(
                "process_lab_recording: voice confidence failed sid=%s: %s "
                "(non-fatal)", session_id, _vc_err,
            )

        # The USER tone word (founder carve-out) — the LEARNED read colors the
        # user's serve-time comment. Computed ONCE here (model cached), stored
        # user-only; NEVER on the coach draft (blind coach). Best-effort.
        try:
            from services.auto_comment import learned_tone_word
            for p in prelim:
                _tw = learned_tone_word(p["metrics"])
                if _tw:
                    p["metrics"]["user_tone_word"] = _tw
        except Exception as _tw_err:
            logger.warning(
                "process_lab_recording: user tone word failed sid=%s: %s "
                "(non-fatal)", session_id, _tw_err,
            )

        # NOTE: the delivery–content "congruence" signal is NOT computed here.
        # It is a delivery STAR generated in services.moment_suggestions
        # (arousal_z low + a positive-content gate) and surfaced on the SD
        # ideal-text key_moments — see services.delivery_alignment. The earlier
        # per-piece readout note (metrics["delivery_alignment_note"]) was
        # retired in favour of that star so it inherits the re-record mic.

        # Capture corpus semantics: offered = every piece, notable = budget set.
        candidates = prelim
        notable = [prelim[i] for i in sorted(_llm_budget_idx)]
    else:
        # ── LEGACY acoustic salient-window path (fallback) ─────────────
        # Candidate windows: ask the segmenter for a GENEROUS pool, not
        # the final cap. Level 1 salience selection picks the top-N most
        # acoustically-activated of these, so it must score across the whole
        # recording's moments rather than re-order a pre-capped few.
        candidate_windows = segment_into_snippets(
            sig, max_snippets=SALIENCE_CANDIDATE_POOL,
        )

        # 1) Features + transcript per CANDIDATE window (in-memory; no insert
        #    yet; index assigned AFTER selection so persisted snippets are
        #    1..N chronological).
        candidates = []
        for (start_ms, end_ms) in candidate_windows:
            dur_ms = end_ms - start_ms
            # Slice the transcript FIRST and pass it in — analyze_pcm_window
            # needs the words to compute wpm (→ the speech_rate metric).
            transcript = slice_transcript_for_window(segments, start_ms, end_ms)
            metrics = analyze_pcm_window(
                sig, start_offset_ms=start_ms, duration_ms=dur_ms,
                transcript=transcript,
            ) or {}
            candidates.append({
                "start_ms": start_ms, "dur_ms": dur_ms,
                "metrics": metrics, "transcript": transcript,
            })

        # ── SELECTION = two axes (Phase 1 directional re-ranker) ──────────
        #  (a) ACTIVATION GATE — top NOTABLE_POOL_SIZE by acoustic activation.
        #  (b) CONTROL SPLIT — top-N/2 by control composite (likely-strong) +
        #      bottom-N/2 (likely-shaky), N = SEGMENT_MAX_SNIPPETS.
        # Both composites are TRANSIENT — computed, used to select, discarded
        # (split-sink / AC-9 / §6 label hygiene: coach labels blind).
        # baseline=None → cold-start within-recording z-score.
        notable = rank_candidates_by_salience(
            candidates, top_n=NOTABLE_POOL_SIZE,
        )
        prelim = select_extremes_by_control(
            notable, top_n=SEGMENT_MAX_SNIPPETS, baseline=None,
        )
        for idx, p in enumerate(prelim, start=1):
            p["idx"] = idx

        # Claim-once transcript attribution (founder bug #2): a sentence
        # straddling two surfaced windows showed up TWICE. Re-slice the
        # SURFACED set so each segment lands in exactly one snippet (largest
        # overlap wins). Pieces mode never needs this — piece text comes from
        # the word list directly, non-overlapping by construction.
        if segments and prelim:
            _deduped = dedupe_window_transcripts(
                [(p["start_ms"], p["start_ms"] + p["dur_ms"]) for p in prelim],
                segments,
            )
            for i, p in enumerate(prelim):
                # keep the raw window-local slice for the candidate-pool
                # capture (training wants window-local text).
                p.setdefault("transcript_raw", p["transcript"])
                # A short window can lose ALL its text to a bigger neighbour —
                # fall back to the raw slice rather than a textless card.
                p["transcript"] = _deduped[i] or p["transcript"]

    # 2) Stickiness over transcripts BEFORE insert (one batch). Scored by
    #    transcript/position, so no snippet ids are needed yet. Pieces mode:
    #    only the LLM-budget pieces are scored (cost cap) — the rest carry
    #    stickiness {composite: None} honestly.
    if not _run_analytics:
        # Analytics off (import lane): no LLM topic read. Honest absence —
        # every piece carries stickiness {} exactly like an unbudgeted piece.
        sticky = [{} for _ in prelim]
    elif _pieces_mode:
        _b_order = sorted(_llm_budget_idx)
        _sticky_b = score_snippets_stickiness([
            {"id": None, "transcript": prelim[i]["transcript"]}
            for i in _b_order
        ])
        sticky = [{} for _ in prelim]
        for j, i in enumerate(_b_order):
            sticky[i] = _sticky_b[j] if j < len(_sticky_b) else {}
    else:
        sticky = score_snippets_stickiness([
            {"id": None, "transcript": p["transcript"]} for p in prelim
        ])

    # 2b) Stickiness #2 — slide-delivery claim-ledger (UX Wave 4). BEST-EFFORT:
    #     any failure here must NOT break the recording or #1. Per-snippet
    #     on-slide-ness (ii) drives overall/rank; per-slide coverage ledger (i)
    #     is the coach audit. Computed against the slides as recorded (lock).
    _slide_per_snip: list = []
    _slide_coverage: list = []
    try:
        _slides_ctx = (session_context or {}).get("slides")
        # Pieces mode (founder fix-pack BE-5, 2026-07-16 — REVIVED): each
        # piece already carries an EXACT slide_index from the cutter, so no
        # window→slide inference is needed; what the original skip dropped
        # was the text↔slide SCORE itself (cost: ~270 pieces can't all run
        # entailment). Restored two-tier: EVERY piece gets a deterministic
        # lexical relatedness vs its OWN slide (degraded=true, zero model
        # cost); the LLM-budget subset (_llm_budget_idx, default 16) is
        # upgraded via the legacy claim-decomposition (sha1-cached per
        # slide → one call per deck) + entailment pipeline. Coach-only
        # (include_slide_scores) + an L2 ranking input (power_score w_s);
        # runs AFTER the _cap_snapshot above, so the raw candidate-window
        # capture never sees it. Best-effort — LLM failure keeps the
        # lexical tier; never blocks the 201 (live loop).
        if _slides_ctx and _pieces_mode:
            from services.slide_alignment import compute_piece_slide_scores
            _slide_per_snip = compute_piece_slide_scores(
                [{"transcript": p["transcript"], "duration_ms": p["dur_ms"],
                  "slide_index": (
                      (p["metrics"].get("piece") or {}).get("slide_index")
                      if isinstance(p["metrics"].get("piece"), dict) else None
                  )}
                 for p in prelim],
                _slides_ctx,
                llm_budget_idx=_llm_budget_idx,
            ) or []
        elif _slides_ctx:
            from services.slide_alignment import compute_slide_scores
            _res = compute_slide_scores(
                [{"start_offset_ms": p["start_ms"], "duration_ms": p["dur_ms"],
                  "transcript": p["transcript"]} for p in prelim],
                _slides_ctx,
                (session_context or {}).get("slide_advances"),
            )
            _slide_per_snip = _res.get("per_snippet") or []
            _slide_coverage = _res.get("slide_coverage") or []
    except Exception as e:
        logger.warning(
            "process_lab_recording: slide scoring failed sid=%s err=%s",
            session_id, e,
        )

    # overall = 0.5·#1 + 0.5·#2(ii); #2 null → overall = #1. Rank by overall
    # desc (tie-break #1, then earliest offset). Ranking only — selection above
    # is unchanged, so #2 never biases the salience set.
    #
    # Pieces mode: ONLY the budget pieces were delivery-scored (#1). A
    # non-budget piece has no delivery signal, so it gets overall_score/rank =
    # None (NOT 0.0 — a stored 0.0 would make power_score treat it as
    # worst-activation and the 1/rank fallback would turn chronology into a
    # ranking signal; None keeps it neutral — it competes on coach direction +
    # slide_stickiness only, which is honest). _scored_i = the indices that get
    # a real overall/rank.
    _scored_i = (sorted(_llm_budget_idx) if _pieces_mode
                 else list(range(len(prelim))))
    _overall_by_i: dict = {}
    _rank_inputs: list = []
    for i in _scored_i:
        p = prelim[i]
        _s1 = (sticky[i] if i < len(sticky) else {}).get("composite")
        _s1 = float(_s1) if isinstance(_s1, (int, float)) else 0.0
        _ss = _slide_per_snip[i] if i < len(_slide_per_snip) else None
        _s2 = _ss.get("composite") if isinstance(_ss, dict) else None
        _ov = (0.5 * _s1 + 0.5 * float(_s2)) if isinstance(_s2, (int, float)) else _s1
        _overall_by_i[i] = _ov
        _rank_inputs.append((_ov, _s1, p["start_ms"], i))
    _rank_by_i = {
        t[3]: r + 1
        for r, t in enumerate(sorted(_rank_inputs, key=lambda t: (-t[0], -t[1], t[2])))
    }

    # 3) Insert each snippet with stickiness PERSISTED into its metrics
    #    blob (metrics["stickiness"]), so a later re-read rebuilds the
    #    identical §3.3 readout (build_readout_from_session). The
    #    feature mapper ignores the "stickiness" sub-key.
    snippets_data: list = []
    _rows_to_insert: list = []   # pieces mode: one bulk insert
    _metrics_by_i: list = []
    for i, p in enumerate(prelim):
        st = sticky[i] if i < len(sticky) else {}
        metrics_full = dict(p["metrics"])
        metrics_full["recording_kind"] = _rec_kind
        metrics_full["stickiness"] = {
            "composite": st.get("composite"),
            "comment": st.get("comment"),
        }
        # Stickiness #2 (UX Wave 4) — persisted alongside #1.
        _ss = _slide_per_snip[i] if i < len(_slide_per_snip) else None
        if isinstance(_ss, dict) and _ss.get("composite") is not None:
            metrics_full["slide_stickiness"] = _ss
        # overall_score / rank: ONLY for delivery-scored pieces (all in legacy;
        # the budget set in pieces mode). Non-budget pieces omit both → neutral
        # downstream (see the _scored_i note above).
        if i in _overall_by_i:
            metrics_full["overall_score"] = round(_overall_by_i[i], 3)
            metrics_full["rank"] = _rank_by_i.get(i)
        if i == 0 and _slide_coverage:  # per-slide ledger parked once, on snip[0]
            metrics_full["slide_coverage"] = _slide_coverage
        # #6 — park this window's word-level timestamps so the take viewer can
        # split the per-slide transcript at slide-click boundaries later.
        snip_words = slice_words_for_window(
            words_all, p["start_ms"], p["start_ms"] + p["dur_ms"],
        ) if words_all else None
        _metrics_by_i.append(metrics_full)
        if _pieces_mode:
            _rows_to_insert.append({
                "session_id": session_id, "user_id": user_id,
                "recording_id": recording_id,
                "start_offset_ms": p["start_ms"], "duration_ms": p["dur_ms"],
                "audio_segment_path": parent_audio_url,
                "metrics": metrics_full,
                "transcript": p["transcript"] or None,
                "words": snip_words or None,
            })
        else:
            row = db.create_charisma_snippet(
                session_id=session_id, user_id=user_id,
                recording_id=recording_id,
                start_offset_ms=p["start_ms"], duration_ms=p["dur_ms"],
                audio_segment_path=parent_audio_url, metrics=metrics_full,
                transcript=p["transcript"] or None, words=snip_words or None,
            )
            snippets_data.append({
                "id": row.get("id") if row else None, "index": p["idx"],
                "transcript": p["transcript"], "audio_ref": parent_audio_url,
                "start_offset_ms": p["start_ms"], "duration_ms": p["dur_ms"],
                "metrics": metrics_full,
            })

    if _pieces_mode:
        # ONE bulk insert instead of ~N sequential REST round-trips — the
        # live-loop cost fix for long takes (a 60-min take is ~270 pieces).
        # Ids come back in insert order; on a bulk hiccup, fall back to
        # per-row so a recording is never lost.
        _ids = db.create_charisma_snippets_bulk(_rows_to_insert)
        for i, p in enumerate(prelim):
            snippets_data.append({
                "id": _ids[i] if i < len(_ids) else None, "index": p["idx"],
                "transcript": p["transcript"], "audio_ref": parent_audio_url,
                "start_offset_ms": p["start_ms"], "duration_ms": p["dur_ms"],
                "metrics": _metrics_by_i[i],
            })

    stickiness_list = [
        {
            "snippet_id": snippets_data[i]["id"],
            "composite": (sticky[i] if i < len(sticky) else {}).get("composite"),
            "comment": (sticky[i] if i < len(sticky) else {}).get("comment"),
        }
        for i in range(len(snippets_data))
    ]

    # ── Candidate-pool capture (automation-audit fix #1: "offered vs chosen") ──
    # The pipeline scored the FULL `candidates` pool, kept `notable`, surfaced
    # `prelim` (<=10) — and would now discard the rest. Persist the WHOLE pool +
    # each window's raw feature vector + which cut it made, so the SELECTION
    # step can later be LEARNED instead of re-coded (the dropped windows are the
    # only signal for "which moments to surface"; lost otherwise, every session).
    #
    # Training-bound / split-sink (AC-9: storing != surfacing) and FENCE-safe
    # (snippet_salience.py): we store the raw `metrics` vector + the heuristic's
    # PROVISIONAL surfaced/notable decision, NEVER the transient salience score.
    # Best-effort: a failure here NEVER breaks the recording (live-loop fence).
    try:
        from services.candidate_capture import (
            build_candidate_rows, SELECTOR_VERSION,
        )
        _surfaced_info = {
            p["start_ms"]: {
                "rank": _rank_by_i.get(i),
                "snippet_id": (snippets_data[i]["id"]
                               if i < len(snippets_data) else None),
            }
            for i, p in enumerate(prelim)
        }
        # Surfaced candidates carry the DEDUPED display text after the claim-
        # once pass; the capture wants each window's RAW window-local slice
        # (preserved as transcript_raw) — restore it on shallow copies.
        #
        # Pieces mode: use the RAW metrics snapshot taken BEFORE acoustic_read
        # / user_tone_word were stamped, so the training corpus never carries
        # a derived composite (the documented fence: candidate_windows stays
        # RAW — validation-sample independence). The 'piece' provenance key is
        # also stripped (it isn't an acoustic feature).
        if _pieces_mode:
            _cap_candidates = []
            for i, c in enumerate(candidates):
                _raw_m = dict(_cap_snapshot[i]) if i < len(_cap_snapshot) else {}
                _raw_m.pop("piece", None)
                _cap_candidates.append({
                    "start_ms": c["start_ms"], "dur_ms": c["dur_ms"],
                    "metrics": _raw_m, "transcript": c.get("transcript"),
                })
        else:
            _cap_candidates = [
                ({**c, "transcript": c.get("transcript_raw")}
                 if c.get("transcript_raw") is not None else c)
                for c in candidates
            ]
        _cap_rows = build_candidate_rows(
            _cap_candidates,
            notable_starts={n.get("start_ms") for n in notable},
            surfaced_info=_surfaced_info,
            session_id=session_id,
            recording_id=recording_id,
            user_id=user_id,
            # Pieces mode re-versions the corpus semantics: offered = every
            # ≤200-char piece (all surfaced), notable = the LLM-budget set.
            # The legacy selector version stays on legacy-path rows so the
            # two regimes never mix in training.
            heuristic_version=("pieces-200char-v1" if _pieces_mode
                               else SELECTOR_VERSION),
        )
        _n_cap = db.insert_candidate_windows(_cap_rows)
        logger.info(
            "process_lab_recording: candidate pool captured sid=%s windows=%d "
            "surfaced=%d", session_id, _n_cap, len(prelim),
        )
    except Exception as _cap_err:
        logger.warning(
            "process_lab_recording: candidate-pool capture failed sid=%s "
            "err=%s (non-fatal)", session_id, _cap_err,
        )

    logger.info(
        "process_lab_recording: sid=%s snippets=%d transcribed=%s",
        session_id, len(snippets_data), bool(segments),
    )

    # Voice-metrics diagnostic (telemetry) — distinguish WHY acoustics are empty
    # so we can isolate device/PWA capture issues before re-engaging the native
    # mic path. (decode_failed is logged at the early return above.)
    _voiced = any(
        _has_voice_metrics(build_readout_features(sd.get("metrics")))
        for sd in snippets_data
    )
    if not snippets_data:
        _diag = "no_snippets"          # decode ok but no salient windows
    elif not _voiced:
        _diag = "no_voiced_speech"     # snippets exist but too quiet/silent
    elif not segments:
        _diag = "ok_acoustics_no_transcript"  # voice read; transcript missing
    else:
        _diag = "ok"
    logger.info(
        "process_lab_recording.voice_metrics_diag sid=%s status=%s "
        "snippets=%d voiced=%s transcribed=%s",
        session_id, _diag, len(snippets_data), _voiced, bool(segments),
    )

    # #A (2026-06-22) — the COMPLETE per-slide 1:1 transcript, bucketed from the
    # WHOLE-recording word list by the slide-click timeline (NOT just the salient
    # snippets, which dropped quiet slides → "first slide not caught / shifted").
    # Persisted at session level so the take viewer reads it directly (complete +
    # fast). Best-effort: never break the recording; only persist when there's
    # real content (else the take viewer keeps its per-snippet fallback).
    try:
        _slides_for_tx = (session_context or {}).get("slides")
        if _slides_for_tx and words_all:
            from services.slide_word_split import build_slide_transcripts
            _slide_tx = build_slide_transcripts(
                words_all, (session_context or {}).get("slide_advances"),
                _slides_for_tx,
            )
            if any((t.get("transcript") or "").strip() for t in _slide_tx):
                db.set_session_slide_transcripts(session_id, _slide_tx)
            # F1 (2026-07-26): measure the word→slide boundary on this take.
            # Pause-snap has been live for a while and nothing ever recorded
            # what it does. EXPOSURE + IMPACT only — there is no ground truth
            # here, so this is deliberately not an accuracy rate (see the
            # module docstring). Internal/coach-side, never user-facing (AC-9).
            # Best-effort: a measurement must never break a recording.
            try:
                from services.slide_boundary_metrics import boundary_metrics
                _bm = boundary_metrics(
                    words_all,
                    (session_context or {}).get("slide_advances"),
                    _slides_for_tx,
                )
                if _bm:
                    db.set_session_boundary_metrics(session_id, _bm)
            except Exception as _bm_err:
                logger.warning(
                    "boundary metrics failed sid=%s: %s", session_id, _bm_err)
        elif not _slides_for_tx and (words_all or segments):
            # DECKLESS (the deck guard matters: a DECK session whose Whisper
            # fell back to segments-only must NOT land here, or the whole talk
            # gets persisted under pseudo-slide 0 and the per-slide reader
            # would prefer it — review must-fix).
            #
            # With word timestamps (founder 2026-07-11): persist the whole
            # recording pre-chunked — ≤200-char pieces broken at word
            # boundaries, EACH with its audio span from the word times — so
            # every chunk's playback control plays exactly its own segment
            # and text/audio boundaries share one source (no drift).
            # An empty chunk list (malformed words) falls THROUGH to the
            # segments blob below rather than silently persisting nothing
            # (review fix — elif chains would have eaten the fallback).
            _chunks: list = []
            if words_all:
                from services.slide_word_split import chunk_words_by_chars
                _chunks = chunk_words_by_chars(words_all)
            if _chunks:
                db.set_session_slide_transcripts(session_id, _chunks)
            elif segments:
                # Segments-only Whisper fallback (no usable word timestamps):
                # persist the WHOLE recording's transcript as a single legacy
                # blob (index 0) — the readout re-chunks it at read time,
                # text-only (no per-chunk spans).
                _full = " ".join(
                    (seg.get("text") or "").strip()
                    for seg in segments
                    if isinstance(seg, dict) and (seg.get("text") or "").strip()
                ).strip()
                if _full:
                    _last_end = max(
                        (seg.get("end") or 0) for seg in segments
                        if isinstance(seg, dict)
                    )
                    db.set_session_slide_transcripts(session_id, [{
                        "index": 0, "transcript": _full,
                        "start_offset_ms": 0,
                        "duration_ms": int(float(_last_end) * 1000),
                    }])
    except Exception as _stx_err:
        # F1a (per-slide 1:1 transcript) degraded → the take viewer falls back to
        # coarser per-snippet bucketing. Make it observable (no payload change).
        from services.f1_observability import observe_f1_degrade
        observe_f1_degrade("slide_transcript_failed", exc=_stx_err,
                           session_id=session_id)

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
            _llm_ids = None
            if _pieces_mode:
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
        _full_tx = " ".join(
            (seg.get("text") or "").strip()
            for seg in (segments or [])
            if isinstance(seg, dict) and (seg.get("text") or "").strip()
        ).strip() or " ".join(
            (w.get("word") or "").strip()
            for w in (words_all or [])
            if isinstance(w, dict) and (w.get("word") or "").strip()
        ).strip()
        # Pieces mode: cards only for the LLM-budget pieces (cost cap) —
        # the instant view's suggestions ride the most salient moments;
        # the other pieces still carry text/audio/auto-comment.
        _sis_snips = snippets_data
        _sis_means = None
        if _pieces_mode:
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


def replay_applied_upgrades(feedback_rows: list, card_sizes: dict) -> dict:
    """Rebuild each snippet's CURRENT applied-suggestion set from the
    chronological Apply/revert tap log (founder 2026-07-15 — the FE's
    Approve toggle must survive reload):

      * action='applied',  target='upgrade' → add that upgrade_index;
      * action='reverted', target='upgrade' → remove it;
      * action='apply_all'                  → add EVERY index of the
        snippet's card (card_sizes[snippet_id] = len(upgrades) at serve).

    Returns {snippet_id: sorted [indexes]} — only sets that end non-empty.
    Indexes outside the card's current size are dropped (a regenerated card
    can shrink). Pure; unknown rows skipped."""
    applied: dict = {}
    for r in (feedback_rows or []):
        if not isinstance(r, dict):
            continue
        sid = str(r.get("snippet_id") or "")
        if not sid:
            continue
        action = r.get("action")
        target = r.get("target")
        idx = r.get("upgrade_index")
        cur = applied.setdefault(sid, set())
        if action == "apply_all":
            cur.update(range(int(card_sizes.get(sid) or 0)))
        elif target == "upgrade" and isinstance(idx, int) \
                and not isinstance(idx, bool):
            if action == "applied":
                cur.add(idx)
            elif action == "reverted":
                cur.discard(idx)
    out: dict = {}
    for sid, idxs in applied.items():
        size = int(card_sizes.get(sid) or 0)
        kept = sorted(i for i in idxs if 0 <= i < size)
        if kept:
            out[sid] = kept
    return out


def _attach_suggestions_to_chunks(chunks: list, out_snips: list) -> list:
    """Instant-view assembly (founder 2026-07-13): ONE deduped chunk list —
    each span of the full transcript appears EXACTLY once, with the salient
    snippet's say_it_stronger card attached to the chunk it was spoken in
    (matched by the snippet's audio-span midpoint). Kills the deckless double
    render (the same sentence riding both ``snippets[]`` and
    ``full_transcript_chunks[]``) and gives the FE the founder's display
    order per chunk: text → corrections (upgrades) → commentary (why).

    Each snippet attaches to AT MOST one chunk (first span match, offset
    order); snippets without a span, without a card, or outside every chunk
    span attach nowhere (still available on ``snippets[]``). Pure — returns
    new dicts, never mutates the source entries.
    """
    out: list = []
    used: set = set()
    for c in chunks:
        if not isinstance(c, dict):
            continue
        cc = dict(c)
        cc.setdefault("say_it_stronger", None)
        cc.setdefault("snippet_id", None)
        cs, cd = cc.get("start_offset_ms"), cc.get("duration_ms")
        if (isinstance(cs, (int, float)) and isinstance(cd, (int, float))
                and cd > 0):
            for sn in out_snips:
                sid = str(sn.get("id"))
                if sid in used:
                    continue
                if not isinstance(sn.get("say_it_stronger"), dict):
                    continue
                ss, sd = sn.get("start_offset_ms"), sn.get("duration_ms")
                if not isinstance(ss, (int, float)):
                    continue
                mid = ss + (
                    sd / 2.0
                    if isinstance(sd, (int, float)) and sd > 0 else 0
                )
                if cs <= mid < cs + cd:
                    cc["say_it_stronger"] = sn.get("say_it_stronger")
                    cc["snippet_id"] = sn.get("id")
                    used.add(sid)
                    break
        out.append(cc)
    return out


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

    # User transcript edits (founder 2026-07-07) — the user's OWN display
    # layer; the coach keeps reviewing the original. One read, mapped to both
    # target kinds (snippet / deckless chunk). Best-effort — {} pre-migration.
    _edits_by_snippet: dict = {}
    _edits_by_chunk: dict = {}
    try:
        for _e in db.get_user_transcript_edits(session_id) or []:
            _txt = (_e.get("text") or "").strip()
            if not _txt:
                continue
            if _e.get("snippet_id"):
                _edits_by_snippet[str(_e["snippet_id"])] = _txt
            elif isinstance(_e.get("chunk_index"), int):
                _edits_by_chunk[_e["chunk_index"]] = _txt
    except Exception:
        pass

    out_snips: list = []
    for i, s in enumerate(snippets):
        metrics = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
        sticky = metrics.get("stickiness") if isinstance(metrics, dict) else None
        if not isinstance(sticky, dict):
            sticky = {}
        snip_out = {
            "id": s.get("id"),
            "index": i + 1,
            "transcript": (
                s.get("transcript") or s.get("transcription_text") or ""
            ),
            "audio_ref": _playable(s.get("audio_segment_path")),
            "start_offset_ms": s.get("start_offset_ms"),
            "duration_ms": s.get("duration_ms"),
            "features": build_readout_features(metrics),
            "stickiness": {
                "composite": sticky.get("composite"),
                "comment": sticky.get("comment"),
            },
            # "Say It Stronger" — the coach's correction surface for the
            # wording lane. COACH VIEW ONLY (founder 2026-08-10: the
            # manager engine is the sole gatekeeper — "no other exist"):
            # on the user readout these LLM rewrite cards were an ungated
            # feedback lane riding the payload, so user routes pass
            # include_upgrade_cards=False and serve null. The lane still
            # PRODUCES; the gate decides what the student sees.
            "say_it_stronger": (
                (s.get("say_it_stronger_final")
                 if isinstance(s.get("say_it_stronger_final"), dict)
                 else (s.get("say_it_stronger")
                       if isinstance(s.get("say_it_stronger"), dict)
                       else None))
                if include_upgrade_cards else None
            ),
            # The user's corrected text for THIS moment (null = no edit);
            # display-preferred on the FE, never shown to the coach as the
            # original.
            "user_edited_text": _edits_by_snippet.get(str(s.get("id"))),
        }
        # Piece provenance (pieces-canonical 2026-07-14) — which ≤200-char
        # piece / deck slide this row IS. Rides both views (it's the user's
        # own text structure, not a verdict); absent on legacy window rows.
        _piece = metrics.get("piece") if isinstance(metrics, dict) else None
        _is_piece = isinstance(_piece, dict)
        if _is_piece:
            snip_out["piece_index"] = _piece.get("index")
            if _piece.get("slide_index") is not None:
                snip_out["slide_index"] = _piece.get("slide_index")
        # Spoken vs read (founder 2026-07-14) — the delivery this row is. The
        # coach labels each snippet by it; not a verdict, so it rides both
        # views (the user already knows which they did).
        _rk = metrics.get("recording_kind") if isinstance(metrics, dict) else None
        if _rk in ("spoken", "read"):
            snip_out["recording_kind"] = _rk
        # Stickiness #2 is COACH-ONLY until calibrated (AC-9) — surfaced only
        # when include_slide_scores (the coach packet), never on the user readout.
        if include_slide_scores:
            # Coach editor: the auto draft beside the (possibly folded) final.
            if isinstance(s.get("say_it_stronger"), dict):
                snip_out["say_it_stronger_draft"] = s.get("say_it_stronger")
            ss = metrics.get("slide_stickiness") if isinstance(metrics, dict) else None
            if isinstance(ss, dict):
                snip_out["slide_stickiness"] = ss
            if metrics.get("overall_score") is not None:
                snip_out["overall_score"] = metrics.get("overall_score")
            if metrics.get("rank") is not None:
                snip_out["rank"] = metrics.get("rank")
            # The stress↔charisma potentiometer + outside-normal-range triage
            # flag (founder 2026-07-14) — deterministic acoustic-only read,
            # COACH-ONLY by fence (never on the user branch above).
            _ar = metrics.get("acoustic_read") if isinstance(metrics, dict) else None
            if isinstance(_ar, dict):
                snip_out["acoustic_read"] = _ar
        out_snips.append(snip_out)

    # Applied-suggestion state (founder 2026-07-15) — replay the session's
    # Apply/revert tap log so the FE's Approve toggle survives reload: each
    # snippet with a card gets ``applied_upgrade_indexes`` (the indexes the
    # user has currently applied). The user's OWN actions echoed back —
    # nothing derived, no fence concern. Best-effort: [] pre-migration.
    try:
        _fb_rows = db.get_suggestion_feedback_by_session(session_id)
        if _fb_rows:
            _card_sizes = {
                str(so.get("id")): len(
                    (so.get("say_it_stronger") or {}).get("upgrades") or [])
                for so in out_snips
                if isinstance(so.get("say_it_stronger"), dict)
            }
            _applied = replay_applied_upgrades(_fb_rows, _card_sizes)
            for so in out_snips:
                _ap = _applied.get(str(so.get("id")))
                if _ap:
                    so["applied_upgrade_indexes"] = _ap
    except Exception as _ap_err:
        logger.warning("readout: applied-state fold failed sid=%s: %s",
                       session_id, _ap_err)

    # Auto-comment (founder 2026-07-14) — the qualitative sentence in the
    # comment slot, computed HERE at serve time from each piece's own metrics
    # (never from the coach's ai_draft, so legacy coach drafts never leak to
    # users). PIECES rows only. Two flavours by surface:
    #   * USER readout      → observations + the LEARNED tone word (persisted
    #                         metrics.user_tone_word) — the founder carve-out.
    #   * COACH packet      → observations + the ACOUSTIC tone word only (the
    #     (include_slide_scores)  deterministic lean) — the coach labels blind
    #                         of any model direction guess.
    # The coach's own edited note (post-publish coach.note) still wins on the
    # FE; this only fills the slot before a coach note exists.
    #
    # DEFAULT-OFF (founder 2026-07-14): "no comment from the coach at all at
    # this point [user side], just the suggestions" AND "no pre-filled comment
    # [coach side]." So the machine comment is retired from BOTH surfaces
    # unless COACH_PREFILL_ENABLED restores it. The coach potentiometer
    # (acoustic_read, above) is unaffected — it is not a comment.
    _piece_rows_present = any(so.get("piece_index") is not None for so in out_snips)
    if _piece_rows_present and _coach_prefill_enabled():
        try:
            from services.auto_comment import (
                build_auto_comment, acoustic_tone_word,
            )
            from services.say_it_stronger import aggregate_session_means
            _means = aggregate_session_means(
                [{"metrics": s.get("metrics")} for s in snippets])
            _by_id = {str(s.get("id")): s for s in snippets}
            for so in out_snips:
                if so.get("piece_index") is None:
                    continue
                _sm = _by_id.get(str(so.get("id"))) or {}
                _m = _sm.get("metrics") if isinstance(_sm.get("metrics"), dict) else {}
                if include_slide_scores:
                    _tw = acoustic_tone_word(_m)          # coach: acoustic only
                else:
                    _tw = _m.get("user_tone_word")        # user: learned
                so["auto_comment"] = build_auto_comment(_m, _means, tone_word=_tw)
        except Exception as _ac_err:
            logger.warning("readout: auto_comment fold failed sid=%s: %s",
                           session_id, _ac_err)

    # COACH-CONFIRMED breakthrough markers (F2 — the "you turned your stress
    # into charisma" badge on the user readout). A challenge snippet following a
    # threat one, BOTH coach-labelled, within this take. Part of the coach
    # insights layer, so gated on include_insights. Best-effort: false/null when
    # the coach hasn't labelled (no shadow guesses surface here — coach only).
    if include_insights:
        try:
            from services.challenge_threat import (
                detect_breakthroughs, resolve_direction,
            )
            from services.best_presentation import _moment_note
            coach_labels = {
                str(r.get("snippet_id")): r.get("value")
                for r in (db.get_training_labels(session_id) or [])
            }
            bt_ids = detect_breakthroughs([
                {"id": s.get("id"), "start_offset_ms": s.get("start_offset_ms"),
                 "direction": resolve_direction(
                     coach_labels.get(str(s.get("id"))), None)}
                for s in snippets
            ])
            notes = {str(s.get("id")): _moment_note(s) for s in snippets}
            for so in out_snips:
                is_bt = so.get("id") in bt_ids
                so["breakthrough"] = is_bt
                so["breakthrough_note"] = (
                    (notes.get(str(so.get("id"))) or None) if is_bt else None
                )
        except Exception as _bt_err:
            logger.warning(
                "readout: breakthrough markers failed sid=%s: %s",
                session_id, _bt_err,
            )
            for so in out_snips:
                so.setdefault("breakthrough", False)
                so.setdefault("breakthrough_note", None)

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

    # PIECES-CANONICAL identity join (founder 2026-07-14): when this session's
    # rows ARE the ≤200-char pieces (metrics.piece provenance present), the
    # instant view list is the rows themselves — 1:1 by construction, no
    # midpoint guessing, nothing rendered twice. Each entry: the piece text +
    # exact span + its own card/comment/edit. The legacy midpoint join below
    # keeps serving OLD sessions (salient-window rows) untouched.
    _piece_rows = [
        so for so in out_snips if so.get("piece_index") is not None
    ]
    if _piece_rows:
        # Dedup by piece_index — a retry/re-process can leave two full piece
        # sets on the session (create has no conflict guard); keep the FIRST
        # per index so the instant view never renders a chunk twice.
        _seen_pi: set = set()
        _ic_rows = []
        for so in sorted(_piece_rows, key=lambda x: (x.get("piece_index") or 0)):
            _pi = so.get("piece_index")
            if _pi in _seen_pi:
                continue
            _seen_pi.add(_pi)
            _ic_rows.append(so)
        result["instant_chunks"] = [{
            "index": so.get("piece_index"),
            **({"slide_index": so.get("slide_index")}
               if so.get("slide_index") is not None else {}),
            "transcript": so.get("transcript") or "",
            "start_offset_ms": so.get("start_offset_ms"),
            "duration_ms": so.get("duration_ms"),
            "snippet_id": so.get("id"),
            **({"recording_kind": so.get("recording_kind")}
               if so.get("recording_kind") else {}),
            # Upgrade cards / auto-comment: GONE from the instant view
            # (founder 2026-08-10 — the manager engine is the sole
            # gatekeeper, and auto_comment was retired from both surfaces
            # 2026-07-14; a persisted row must not resurrect it here).
            # The coach reads say_it_stronger from `snippets`, flag-gated.
            "say_it_stronger": (so.get("say_it_stronger")
                                if include_upgrade_cards else None),
            # The user's currently-applied suggestion indexes (Approve state
            # survives reload — founder 2026-07-15). Absent when none.
            **({"applied_upgrade_indexes": so.get("applied_upgrade_indexes")}
               if so.get("applied_upgrade_indexes") else {}),
            # Edit surfaces whether the FE keyed by snippet_id (preferred for
            # pieces) OR by chunk_index (deckless legacy pattern → the piece
            # ordinal): fold both so a saved edit never disappears.
            "user_edited_text": (
                so.get("user_edited_text")
                or _edits_by_chunk.get(so.get("piece_index"))
            ),
        } for so in _ic_rows]

    # Slide-deck context (UX Wave 4 BE-S6a) — session-level so the report can
    # render the deck (presentation_ref via PDF.js) + the per-snippet slide.
    try:
        ctx = db.get_session_intake_context(session_id) or {}
    except Exception:
        ctx = {}
    if isinstance(ctx, dict):
        # Take-N setup restore (founder bug 2026-07-13: "second recording
        # doesn't work" — the FE restored the deck from localStorage only, so
        # a fresh tab / evicted PWA storage / guest killed take 2 with
        # "Couldn't load your presentation"). Ride the training's setup on
        # the readout so "Record the next take" prefills SERVER-side, on the
        # authed AND guest re-read routes alike. Omitted when the context
        # carries nothing usable.
        if (ctx.get("topic") or ctx.get("slides")):
            result["setup"] = {
                "topic": ctx.get("topic"),
                "audience": ctx.get("audience"),
                "target_length_seconds": ctx.get("target_length_seconds"),
                "slides": ctx.get("slides") or [],
                "presentation_ref": ctx.get("presentation_ref"),
            }
        # Audience (backlog 1.4) — the training-setup field the FE suffixes
        # onto insight one-liners ("(audience: investors)"). Deck and
        # deckless alike; absent/blank → key omitted (FE hides the suffix).
        _aud = (ctx.get("audience") or "").strip() \
            if isinstance(ctx.get("audience"), str) else ""
        if _aud:
            result["audience"] = _aud
        slides = ctx.get("slides")
        if slides:
            result["slides"] = slides
            # BE-S4/S6b — map each snippet to the slide on screen when it was
            # spoken (exact from the tap timeline; text-overlap fallback only
            # when no timeline). The user readout renders this slide above the
            # snippet; it's the user's own deck, not a verdict (AC-9-safe).
            from services.slide_alignment import slide_for_snippet
            advances = ctx.get("slide_advances")
            for snip in out_snips:
                sl = slide_for_snippet(snip, advances, slides)
                if sl is not None:
                    snip["slide"] = sl
            # #A (readout) — the COMPLETE per-slide 1:1 transcript so the FE can
            # show EACH deck slide with exactly what was said while it was on
            # screen (every word bucketed by the click timeline), including the
            # quiet first slide the per-snippet view dropped ("first slide not
            # caught / shifted"). Prefer the value persisted at record time;
            # fall back to the per-snippet word union for older recordings.
            _stx = None
            try:
                _stx = db.get_session_slide_transcripts(session_id)
            except Exception:
                _stx = None
            if not _stx:
                try:
                    from services.slide_word_split import build_slide_transcripts
                    _union: list = []
                    for s in snippets:
                        ws = s.get("words") if isinstance(s, dict) else None
                        if isinstance(ws, list):
                            _union.extend(ws)
                    if _union:
                        _cand = build_slide_transcripts(_union, advances, slides)
                        if any((t.get("transcript") or "").strip()
                               for t in _cand):
                            _stx = _cand
                except Exception as _stx_err:
                    logger.warning(
                        "readout: slide_transcripts fallback failed sid=%s: %s",
                        session_id, _stx_err,
                    )
            if _stx:
                result["slide_transcripts"] = _stx
                # Instant synonym view (founder 2026-07-13) — DECKED: the deck
                # IS the chunking (one chunk per slide, the slide's own audio
                # span), each carrying the say_it_stronger card of the salient
                # snippet spoken on it. The FE renders the instant view from
                # THIS list alone — no snippet/chunk double render.
                if "instant_chunks" not in result:  # pieces identity wins
                    _ic_src = [{
                        "index": i,
                        "slide_index": t.get("index"),
                        "transcript": (t.get("transcript") or "").strip(),
                        "start_offset_ms": t.get("start_offset_ms"),
                        "duration_ms": t.get("duration_ms"),
                    } for i, t in enumerate(_stx)
                        if isinstance(t, dict)
                        and (t.get("transcript") or "").strip()]
                    result["instant_chunks"] = _attach_suggestions_to_chunks(
                        _ic_src, out_snips,
                    )
        else:
            # DECKLESS (founder bug #2, re-cut 2026-07-11): fold the persisted
            # whole-recording transcript as a plain string PLUS the canonical
            # ≤200-char chunk list — new-style persists carry per-chunk audio
            # spans (start_offset_ms/duration_ms against parent_audio_ref) so
            # each chunk's play control plays exactly its segment; legacy
            # single-blob persists re-chunk at read time, text-only (the FE
            # hides the play control when a chunk has no span). Each chunk
            # carries the user's own edit when one exists (display layer).
            try:
                _stx = db.get_session_slide_transcripts(session_id)
                if _stx:
                    _full = " ".join(
                        (t.get("transcript") or "").strip()
                        for t in _stx
                        if isinstance(t, dict) and (t.get("transcript") or "").strip()
                    ).strip()
                    if _full:
                        result["full_transcript"] = _full
                        from services.slide_word_split import (
                            deckless_chunks_from_stx,
                        )
                        _chunks = deckless_chunks_from_stx(_stx)
                        for _c in _chunks:
                            _c["user_edited_text"] = _edits_by_chunk.get(
                                _c.get("index"))
                        result["full_transcript_chunks"] = _chunks
                        # Instant synonym view (founder 2026-07-13) —
                        # DECKLESS: the canonical ≤200-char chunks, each
                        # carrying the say_it_stronger card of the snippet
                        # spoken in it. The FE renders the instant view from
                        # THIS list alone (chunk text → corrections →
                        # commentary) — never snippets[] AND chunks[], which
                        # doubled the same sentence. Pieces-canonical
                        # sessions already built the identity list above.
                        if "instant_chunks" not in result:
                            result["instant_chunks"] = (
                                _attach_suggestions_to_chunks(
                                    _chunks, out_snips)
                            )
            except Exception:
                pass
        if ctx.get("presentation_ref"):
            result["presentation_ref"] = ctx.get("presentation_ref")

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
                    # Coach breakthrough video (top-level, beside
                    # `breakthrough`): a public URL the FE drops into
                    # <video> next to the breakthrough badge. Null when the
                    # coach attached none. The explanation text is
                    # coach.note (no separate field).
                    snip["breakthrough_video_ref"] = cn.get(
                        "breakthrough_video_ref"
                    )

    return result


