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
# loudness_range=dynamic_db.) NB: mean_pause is converted ms→seconds in
# build_readout_features (the value, not the key).
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


def build_readout_features(metrics: Optional[dict]) -> dict:
    """Map an audio_metrics dict to the §3.3 feature block.

    Always returns the full 11-key feature dict (every contract key
    present, value or None) so the FE renders one stable shape. Pure.

    ``mean_pause`` is persisted as ``pause_ms`` (milliseconds) but emitted
    here in SECONDS: the §5 Readout renders it as seconds and every other
    feature is already a natural display unit, so this is the single
    chokepoint (upload-time + re-read + admin readouts all flow through
    here) that keeps the readout uniformly display-ready. None-safe;
    storage stays in ms (no migration).
    """
    m = metrics or {}
    out = {
        out_key: m.get(src_key)
        for out_key, src_key in _FEATURE_MAP.items()
    }
    mp = out.get("mean_pause")
    if isinstance(mp, (int, float)):
        out["mean_pause"] = round(mp / 1000.0, 2)
    return out


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
    return {"snippets": out_snippets}


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
        rank_candidates_by_salience, SALIENCE_CANDIDATE_POOL,
    )
    from services.snippet_stickiness import score_snippets_stickiness
    from services.db import db

    sig = decode_audio_to_pcm(audio_bytes)
    if sig is None:
        logger.warning(
            "process_lab_recording: decode failed sid=%s", session_id,
        )
        return {"snippets": []}

    # Whisper the whole recording ONCE (best-effort), vocab-primed.
    segments: list = []
    try:
        from io import BytesIO
        from services.openai_service import OpenAIService
        ois = OpenAIService()
        if ois.client:
            vocab = (session_context or {}).get("domain_vocabulary")
            wres = ois.transcribe_audio(
                BytesIO(audio_bytes), filename or "lab.webm",
                vocabulary=vocab,
            )
            segments = (wres or {}).get("segments") or []
    except Exception as e:
        logger.warning(
            "process_lab_recording: whisper failed sid=%s err=%s",
            session_id, e,
        )
        segments = []

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
        metrics = analyze_pcm_window(
            sig, start_offset_ms=start_ms, duration_ms=dur_ms,
        ) or {}
        transcript = slice_transcript_for_window(segments, start_ms, end_ms)
        candidates.append({
            "start_ms": start_ms, "dur_ms": dur_ms,
            "metrics": metrics, "transcript": transcript,
        })

    # ── Level 1 SALIENCE SELECTION (replaces naive duration ranking).
    # Pick the top-N (= existing per-session cap SEGMENT_MAX_SNIPPETS)
    # most acoustically-salient candidates over the SAME 11-feature
    # vector. The salience score is transient — never persisted, never
    # user-facing (split-sink / AC-9); see services/snippet_salience.py
    # for the methodological fence. Output is ≤ cap, chronological, so
    # the snippet-count contract (§3.3 / FE ~10) is preserved.
    prelim: list = rank_candidates_by_salience(
        candidates, top_n=SEGMENT_MAX_SNIPPETS,
    )
    for idx, p in enumerate(prelim, start=1):
        p["idx"] = idx

    # 2) Stickiness over transcripts BEFORE insert (one batch). Scored
    #    by transcript/position, so no snippet ids are needed yet.
    sticky = score_snippets_stickiness([
        {"id": None, "transcript": p["transcript"]} for p in prelim
    ])

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
        row = db.create_charisma_snippet(
            session_id=session_id,
            user_id=user_id,
            recording_id=recording_id,
            start_offset_ms=p["start_ms"],
            duration_ms=p["dur_ms"],
            audio_segment_path=parent_audio_url,
            metrics=metrics_full,
            transcript=p["transcript"] or None,
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

    logger.info(
        "process_lab_recording: sid=%s snippets=%d transcribed=%s",
        session_id, len(snippets_data), bool(segments),
    )
    return build_readout_payload(snippets_data, stickiness_list)


def build_readout_from_session(
    session_id: str,
    *,
    include_insights: bool = True,
) -> dict:
    """Re-derive the §3.3 Readout from PERSISTED snippets — the canonical
    reader for parked-restore + history (contract: a report loads
    identically an hour later / on scroll-back).

    Reads charisma_snippets for the session, rebuilds each snippet's
    §3.3 shape from its metrics blob (features via build_readout_features
    + the persisted stickiness sub-key), in chronological order
    (start_offset_ms ASC — the honest "what happened" order).

    Post-publish (include_insights), folds the coach layer:
      - top-level ``insights_payload`` (overall_message + snippet_notes)
      - per-snippet ``coach`` {note, tag, when, examples} matched by
        snippet_id (when=None / examples=[] when the note omits them)

    Owner-scoping is the caller's job (the route). Returns
    {"snippets": [...], "insights_payload"?: {...}}.
    """
    from services.db import db

    snippets = db.get_snippets_by_session(session_id) or []
    out_snips: list = []
    for i, s in enumerate(snippets):
        metrics = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
        sticky = metrics.get("stickiness") if isinstance(metrics, dict) else None
        if not isinstance(sticky, dict):
            sticky = {}
        out_snips.append({
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
        })

    result: dict = {"snippets": out_snips}

    if include_insights:
        try:
            session = db.v2_get_session_by_id(session_id) or {}
        except Exception:
            session = {}
        ip = session.get("insights_payload")
        if isinstance(ip, dict):
            result["insights_payload"] = ip
            notes_by_id = {
                n["snippet_id"]: n
                for n in (ip.get("snippet_notes") or [])
                if isinstance(n, dict) and n.get("snippet_id")
            }
            for snip in out_snips:
                cn = notes_by_id.get(snip["id"])
                if cn:
                    snip["coach"] = {
                        "note": cn.get("note"),
                        "tag": cn.get("tag"),
                        # PR-2 — optional coach fields; None/[] when the
                        # note omits them (FE hides when absent). Older
                        # published payloads predate these keys → absent.
                        "when": cn.get("when"),
                        "examples": cn.get("examples") or [],
                    }

    return result
