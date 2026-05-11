"""
Charisma snippet generation — reuses the core audio analysis pipeline from
stress_snippet_service (VAD, filler density, acoustic diversity) but writes
to the charisma_snippets table under the charisma_snippets/ storage prefix.

Coaches label each clip with "charisma" or "no_charisma".
"""
import logging
import uuid

import sentry_sdk

from config import Config
from services.db import db

# Reuse the entire clip-extraction and selection machinery from the stress
# pipeline — same underlying audio analysis, different label question.
from services.stress_snippet_service import (
    STRESS_SNIPPET_CLIP_SEC_DEFAULT,
    STRESS_SNIPPET_CLIP_SEC_MIN,
    STRESS_SNIPPET_CLIP_SEC_MAX,
    CandidateWindow,
    ScoredClip,
    _resolve_ffmpeg_executable,
    _decode_audio_to_pcm,
    _frame_db,
    _build_candidates,
    _energy_std_for_window,
    _extract_window_signal,
    _feature_vector_for_model,
    _predict_with_baseline_model,
    _load_baseline_model,
    _acoustic_diversity_embedding,
    _select_clip_indices,
    _floor_clip_window,
    _extract_clip_mp3,
)

logger = logging.getLogger(__name__)
config = Config()

# Public aliases so callers don't need to import from stress_snippet_service.
CHARISMA_SNIPPET_CLIP_SEC_DEFAULT = STRESS_SNIPPET_CLIP_SEC_DEFAULT
CHARISMA_SNIPPET_CLIP_SEC_MIN = STRESS_SNIPPET_CLIP_SEC_MIN
CHARISMA_SNIPPET_CLIP_SEC_MAX = STRESS_SNIPPET_CLIP_SEC_MAX


def generate_charisma_snippets_for_recording(
    recording_id: str,
    *,
    source_type: str,
    max_snippets: int = 8,
    clip_seconds: float = CHARISMA_SNIPPET_CLIP_SEC_DEFAULT,
    clear_existing: bool = True,
) -> list[dict]:
    """
    Generate and persist up to max_snippets candidate clips for charisma labeling.

    Uses the same VAD / filler-density / acoustic-diversity selection pipeline
    as the stress pipeline; only the storage path and target table differ.
    """
    try:
        try:
            clip_sec = float(clip_seconds)
        except (TypeError, ValueError):
            clip_sec = float(CHARISMA_SNIPPET_CLIP_SEC_DEFAULT)
        clip_sec = max(
            float(CHARISMA_SNIPPET_CLIP_SEC_MIN),
            min(clip_sec, float(CHARISMA_SNIPPET_CLIP_SEC_MAX)),
        )

        rec = db.get_recording(recording_id, None)
        if not rec:
            raise ValueError("recording not found")
        storage_path = (rec.get("storage_path") or "").strip()
        if not storage_path:
            raise ValueError("recording has no storage_path")

        ffmpeg_exe = _resolve_ffmpeg_executable()
        if not ffmpeg_exe:
            raise RuntimeError("ffmpeg is required for snippet extraction")

        # Interview audio bytes live in the dedicated R2 audio bucket
        # (see services.audio_storage). One helper, one bucket, no
        # bucket-drift bugs.
        from services.audio_storage import get_audio_bytes
        audio_bytes = get_audio_bytes(storage_path)
        if not audio_bytes:
            raise ValueError("recording audio is empty")
        signal = _decode_audio_to_pcm(audio_bytes, ffmpeg_exe)
        if signal is None or len(signal) < 1600:
            raise ValueError("could not decode recording audio")

        duration_sec = float(len(signal) / 16000.0)
        dbs = _frame_db(signal)
        transcript = (rec.get("transcription_text") or "").strip()
        candidates = _build_candidates(transcript, duration_sec, dbs, clip_sec)

        baseline_model = _load_baseline_model()
        scored_items: list[ScoredClip] = []
        for c in candidates:
            energy_std = _energy_std_for_window(signal, c.start_sec, c.end_sec)
            energy_norm = min(1.0, energy_std / 0.08) if energy_std > 0 else 0.0
            suspicion = 0.45 * c.filler_density + 0.35 * c.pause_strength + 0.20 * energy_norm
            duration_ms = int(round((c.end_sec - c.start_sec) * 1000))
            snippet_features = {
                "pause_strength": c.pause_strength,
                "filler_density": c.filler_density,
                "energy_std": energy_std,
            }
            prob = max(0.01, min(0.99, suspicion))
            confidence = max(0.5, min(1.0, 0.5 + abs(prob - 0.5)))
            if baseline_model is not None:
                window_signal = _extract_window_signal(signal, c.start_sec, c.end_sec)
                vector = _feature_vector_for_model(
                    window_signal=window_signal,
                    scenario=c.scenario,
                    snippet_features=snippet_features,
                    duration_ms=duration_ms,
                )
                pred = _predict_with_baseline_model(baseline_model, vector)
                if pred is not None:
                    prob, confidence = pred
            uncertainty = 1.0 - confidence
            selection_score = 0.6 * suspicion + 0.4 * uncertainty
            emb = _acoustic_diversity_embedding(signal, c.start_sec, c.end_sec)
            cand = CandidateWindow(
                scenario=c.scenario,
                start_sec=c.start_sec,
                end_sec=c.end_sec,
                filler_density=c.filler_density,
                pause_strength=c.pause_strength,
                energy_std=energy_std,
                transcript_excerpt=c.transcript_excerpt,
            )
            scored_items.append(
                ScoredClip(
                    selection_score=selection_score,
                    confidence=confidence,
                    prob=prob,
                    cand=cand,
                    emb=emb,
                )
            )

        pick_idx = _select_clip_indices(scored_items, max_snippets=max_snippets, source_type=source_type)
        selected = [scored_items[i] for i in pick_idx]

        if clear_existing:
            try:
                db.v2_delete_charisma_snippets_for_recording(recording_id)
            except Exception as del_err:
                logger.warning("charisma_snippet_service: cleanup existing snippets failed: %s", del_err)

        rows = []
        for sc in selected:
            selection_score = sc.selection_score
            confidence = sc.confidence
            prob = sc.prob
            c = sc.cand
            ns, ne = _floor_clip_window(
                c.start_sec, c.end_sec, duration_sec, min_span_sec=min(0.5, clip_sec * 0.99)
            )
            c.start_sec, c.end_sec = ns, ne
            if ne <= ns + 1e-4:
                logger.warning(
                    "charisma_snippet_service: skip degenerate window recording_id=%s scenario=%s",
                    recording_id,
                    c.scenario,
                )
                continue
            span = max(0.0, c.end_sec - c.start_sec)
            if span > clip_sec + 1e-4:
                center = (c.start_sec + c.end_sec) / 2.0
                half = clip_sec / 2.0
                ns2 = max(0.0, center - half)
                ne2 = min(duration_sec, ns2 + clip_sec)
                ns2 = max(0.0, ne2 - clip_sec)
                c.start_sec, c.end_sec = ns2, ne2
            duration = min(clip_sec, max(0.25, c.end_sec - c.start_sec))
            clip_bytes = _extract_clip_mp3(audio_bytes, ffmpeg_exe, c.start_sec, duration)
            if not clip_bytes:
                continue
            snippet_id = str(uuid.uuid4())
            clip_path = f"charisma_snippets/{recording_id}/{snippet_id}.mp3"
            db.upload_audio(config.AUDIO_BUCKET_NAME, clip_path, clip_bytes, content_type="audio/mpeg")
            rows.append(
                {
                    "id": snippet_id,
                    "recording_id": recording_id,
                    "session_id": rec.get("session_v2_id"),
                    "user_id": rec.get("user_id"),
                    "source_type": source_type,
                    "scenario": c.scenario,
                    "start_ms": int(round(c.start_sec * 1000)),
                    "end_ms": int(round(c.end_sec * 1000)),
                    "duration_ms": int(round((c.end_sec - c.start_sec) * 1000)),
                    "selection_score": round(float(selection_score), 5),
                    "classifier_charisma_probability": round(float(prob), 5),
                    "classifier_confidence": round(float(confidence), 5),
                    "transcript_excerpt": c.transcript_excerpt or None,
                    "storage_path": clip_path,
                    "features": {
                        "pause_strength": round(float(c.pause_strength), 5),
                        "filler_density": round(float(c.filler_density), 5),
                        "energy_std": round(float(c.energy_std), 6),
                    },
                }
            )

        inserted = db.v2_insert_charisma_snippets(rows)
        return inserted
    except Exception as e:
        logger.warning(
            "charisma_snippet_service: generation failed recording_id=%s err=%s",
            recording_id,
            e,
            exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return []
