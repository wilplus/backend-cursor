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
from typing import Any, Optional


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
            "audio_ref": sd.get("audio_ref"),
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


def process_lab_recording(
    *,
    session_id: str,
    user_id: Optional[str],
    recording_id: str,
    audio_bytes: bytes,
    filename: str,
    session_context: Optional[dict],
    parent_audio_url: str,
) -> dict:
    """Run the full pipeline → §3.3 Readout payload.

    Assumes the min-content gate already passed and the parent audio is
    already stored at ``parent_audio_url`` (the shared audio_ref for
    every snippet, parent+offset model). Persists one charisma_snippets
    row per window. Returns {"snippets": [...]}.
    """
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
            wres = ois.transcribe_audio(
                BytesIO(whisper_bytes), whisper_name,
                vocabulary=vocab,
            )
            segments = (wres or {}).get("segments") or []
            words_all = (wres or {}).get("words") or []
    except Exception as e:
        logger.warning(
            "process_lab_recording.voice_metrics_diag sid=%s "
            "status=transcription_failed err=%s (acoustics still computed)",
            session_id, e,
        )
        segments = []
        words_all = []

    # ── Candidate windows: ask the segmenter for a GENEROUS pool, not
    # the final cap. Level 1 salience selection picks the top-N most
    # acoustically-activated of these, so it must score across the whole
    # recording's moments rather than re-order a pre-capped few. (For
    # typical Lab recordings the real window count is well under the
    # pool, so salience scores over ALL of the recording's windows.)
    candidate_windows = segment_into_snippets(
        sig, max_snippets=SALIENCE_CANDIDATE_POOL,
    )

    # 1) Features + transcript per CANDIDATE window (in-memory; no insert
    #    yet; index assigned AFTER selection so persisted snippets are
    #    1..N chronological).
    candidates: list = []
    for (start_ms, end_ms) in candidate_windows:
        dur_ms = end_ms - start_ms
        # Slice the transcript FIRST and pass it in — analyze_pcm_window needs
        # the words to compute wpm (→ the "speed" / speech_rate metric).
        # Without it, speech_rate was always null and the card showed "—".
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
    # Goal: the coach's ≤10 should contain the clearest GOODS and the
    # clearest SHAKIES, not just the 10 most activated.
    #
    #  (a) ACTIVATION GATE — keep the notable pool (top NOTABLE_POOL_SIZE
    #      by acoustic activation). Flat/boring/low-arousal windows drop;
    #      they're neither coachably-good nor coachably-shaky.
    #  (b) CONTROL SPLIT — within that pool, surface the top-N/2 by the
    #      control/polish composite (likely-strong) + bottom-N/2
    #      (likely-shaky), N = SEGMENT_MAX_SNIPPETS.
    #
    # Both the activation salience and the control composite are
    # TRANSIENT — computed, used to select, discarded. Neither score nor
    # any likely-strong/shaky DIRECTION is persisted, serialized, shown
    # to the coach, or made the training label (split-sink / AC-9 / the
    # §6 label-hygiene decision: coach labels blind). The persisted
    # snippet still carries the full 11-feature vector unchanged — that
    # vector is the future bridge to the Phase-2 model, so it stays.
    #
    # baseline=None → cold-start within-recording z-score (no per-speaker
    # acoustic ISB exists yet; the hook upgrades to baseline-relative
    # when it does — §5). Output ≤ cap, chronological → §3.3 / FE ~10
    # count unchanged.
    notable = rank_candidates_by_salience(
        candidates, top_n=NOTABLE_POOL_SIZE,
    )
    prelim: list = select_extremes_by_control(
        notable, top_n=SEGMENT_MAX_SNIPPETS, baseline=None,
    )
    for idx, p in enumerate(prelim, start=1):
        p["idx"] = idx

    # Claim-once transcript attribution (founder bug #2): the candidate-stage
    # slices include ANY overlapping Whisper segment, so a sentence straddling
    # two surfaced windows showed up TWICE. Re-slice the SURFACED set so each
    # segment lands in exactly one snippet (largest overlap wins). The acoustic
    # metrics keep their full padded window (playback + analysis unchanged);
    # only the display/persisted text is deduped. Candidate-pool capture keeps
    # the raw per-window slices (training wants the window-local text).
    if segments and prelim:
        _deduped = dedupe_window_transcripts(
            [(p["start_ms"], p["start_ms"] + p["dur_ms"]) for p in prelim],
            segments,
        )
        for i, p in enumerate(prelim):
            # keep the raw window-local slice for the candidate-pool capture
            # (training wants window-local text, not the deduped display text).
            p.setdefault("transcript_raw", p["transcript"])
            # A short window can lose ALL its text to a bigger neighbour —
            # fall back to the raw slice rather than a textless snippet card
            # (a rare local dup beats missing text).
            p["transcript"] = _deduped[i] or p["transcript"]

    # 2) Stickiness over transcripts BEFORE insert (one batch). Scored
    #    by transcript/position, so no snippet ids are needed yet.
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
        if _slides_ctx:
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
    _overall: list = []
    for i, p in enumerate(prelim):
        _s1 = (sticky[i] if i < len(sticky) else {}).get("composite")
        _s1 = float(_s1) if isinstance(_s1, (int, float)) else 0.0
        _ss = _slide_per_snip[i] if i < len(_slide_per_snip) else None
        _s2 = _ss.get("composite") if isinstance(_ss, dict) else None
        _ov = (0.5 * _s1 + 0.5 * float(_s2)) if isinstance(_s2, (int, float)) else _s1
        _overall.append((_ov, _s1, p["start_ms"], i))
    _rank_by_i = {
        t[3]: r + 1
        for r, t in enumerate(sorted(_overall, key=lambda t: (-t[0], -t[1], t[2])))
    }

    # 3) Insert each snippet with stickiness PERSISTED into its metrics
    #    blob (metrics["stickiness"]), so a later re-read rebuilds the
    #    identical §3.3 readout (build_readout_from_session). The
    #    feature mapper ignores the "stickiness" sub-key.
    snippets_data: list = []
    for i, p in enumerate(prelim):
        st = sticky[i] if i < len(sticky) else {}
        metrics_full = dict(p["metrics"])
        metrics_full["stickiness"] = {
            "composite": st.get("composite"),
            "comment": st.get("comment"),
        }
        # Stickiness #2 (UX Wave 4) — persisted alongside #1.
        _ss = _slide_per_snip[i] if i < len(_slide_per_snip) else None
        if isinstance(_ss, dict) and _ss.get("composite") is not None:
            metrics_full["slide_stickiness"] = _ss
        metrics_full["overall_score"] = round(_overall[i][0], 3)
        metrics_full["rank"] = _rank_by_i.get(i)
        if i == 0 and _slide_coverage:  # per-slide ledger parked once, on snip[0]
            metrics_full["slide_coverage"] = _slide_coverage
        # #6 — park this window's word-level timestamps so the take viewer can
        # split the per-slide transcript at slide-click boundaries later. Sliced
        # from the whole-recording word list (absolute seconds). Empty when
        # Whisper returned no words (older path / failure) → take viewer falls
        # back to whole-snippet bucketing.
        snip_words = slice_words_for_window(
            words_all, p["start_ms"], p["start_ms"] + p["dur_ms"],
        ) if words_all else None
        row = db.create_charisma_snippet(
            session_id=session_id,
            user_id=user_id,
            recording_id=recording_id,
            start_offset_ms=p["start_ms"],
            duration_ms=p["dur_ms"],
            audio_segment_path=parent_audio_url,
            metrics=metrics_full,
            transcript=p["transcript"] or None,
            words=snip_words or None,
        )
        snippets_data.append({
            "id": row.get("id") if row else None,
            "index": p["idx"],
            "transcript": p["transcript"],
            "audio_ref": parent_audio_url,
            "start_offset_ms": p["start_ms"],
            "duration_ms": p["dur_ms"],
            "metrics": metrics_full,
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
            heuristic_version=SELECTOR_VERSION,
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

    # AI-Commentator (Phase 4 / Prompt 2) — fire-and-forget coach-note drafts
    # for every recording (slides are optional grounding; a deck-less spoken
    # pitch still drafts). process_lab_recording is synchronous on the upload
    # response, so drafting (N LLM calls) runs in a daemon, never blocking it.
    # Best-effort: a failure here never breaks the readout.
    try:
        from services.coach_comment_drafter import dispatch_coach_note_drafts
        dispatch_coach_note_drafts(
            session_id,
            snippets_data,
            (session_context or {}).get("slides"),
            (session_context or {}).get("slide_advances"),
            goal=(session_context or {}).get("topic"),
        )
    except Exception as _draft_err:
        logger.warning(
            "process_lab_recording: coach-note draft dispatch failed sid=%s: %s",
            session_id, _draft_err,
        )

    # "Say It Stronger" (founder 2026-07-07) — per-snippet rewrite suggestions
    # for the user readout, replacing the raw acoustic numbers there. Same
    # fire-and-forget daemon pattern as the drafter above; the suggestions
    # appear on the readout RE-READ once generated (the 201 below carries
    # null). Best-effort: never blocks or breaks the recording.
    try:
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
        dispatch_say_it_stronger(session_id, snippets_data, context={
            "topic": _ctx.get("topic"),
            "audience": _ctx.get("audience"),
            "target_length_seconds": _ctx.get("target_length_seconds"),
            "duration_sec": (len(sig) / float(SAMPLE_RATE)) if sig is not None else None,
            "full_transcript": _full_tx,
        })
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
            "audio_ref": s.get("audio_segment_path"),
            "start_offset_ms": s.get("start_offset_ms"),
            "duration_ms": s.get("duration_ms"),
            "features": build_readout_features(metrics),
            "stickiness": {
                "composite": sticky.get("composite"),
                "comment": sticky.get("comment"),
            },
            # "Say It Stronger" — the qualitative rewrite-suggestion card
            # that REPLACES the raw acoustic numbers on the user view (the
            # numbers above stay in the payload for the coach surface).
            # null until the post-upload daemon lands it (FE renders the
            # shimmer / nothing). L1: display overlay only.
            "say_it_stronger": (
                s.get("say_it_stronger_final")
                if isinstance(s.get("say_it_stronger_final"), dict)
                else (s.get("say_it_stronger")
                      if isinstance(s.get("say_it_stronger"), dict) else None)
            ),
            # The user's corrected text for THIS moment (null = no edit);
            # display-preferred on the FE, never shown to the coach as the
            # original.
            "user_edited_text": _edits_by_snippet.get(str(s.get("id"))),
        }
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
        out_snips.append(snip_out)

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
        "parent_audio_ref": (
            snippets[0].get("audio_segment_path") if snippets else None
        ),
    }

    # Slide-deck context (UX Wave 4 BE-S6a) — session-level so the report can
    # render the deck (presentation_ref via PDF.js) + the per-snippet slide.
    try:
        ctx = db.get_session_intake_context(session_id) or {}
    except Exception:
        ctx = {}
    if isinstance(ctx, dict):
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


