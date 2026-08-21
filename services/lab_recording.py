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
from services.recording_transcription import (
    WHISPER_MAX_BYTES as _WHISPER_MAX_BYTES,
    merge_slide_vocabulary as _merge_slide_vocab,
    transcribe_recording,
)

__all__ = [
    "_WHISPER_MAX_BYTES",
    "_merge_slide_vocab",
    "_build_canonical_pieces",
    "_compute_overall_ranking",
    "PiecesCanonicalUnavailable",
    "process_lab_recording",
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
    _piece_list = list(state.canonical_pieces)
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
        elif not _slides_for_tx:
            # DECKLESS: persist the canonical pieces directly so the transcript
            # workspace and feedback rows share the exact same boundaries.
            # With word timestamps (founder 2026-07-11): persist the whole
            # recording pre-chunked — ≤200-char pieces broken at word
            # boundaries, EACH with its audio span from the word times — so
            # every chunk's playback control plays exactly its own segment
            # and text/audio boundaries share one source (no drift).
            db.set_session_slide_transcripts(session_id, _piece_list)
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
            # ⛔ THE CONFIDENCE COMPOSITE DOES NOT GO HERE — not on this branch
            # either. It was put on the coach packet during the 2026-08-13
            # re-point so services/moment_suggestions.py could route the star
            # lane off it, and test_voice_confidence's source-level fence
            # caught it: showing the coach the machine's confidence read is
            # exactly the anchoring BLIND COACH exists to stop, and this
            # serializer is an allowlist precisely so a convenience field
            # cannot slip onto a surface. That module reads the metrics blob
            # from the DB itself instead.
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
