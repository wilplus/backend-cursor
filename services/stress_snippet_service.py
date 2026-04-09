import logging
import math
import os
import re
import shutil
import subprocess
import json
import uuid
from dataclasses import dataclass
from typing import Optional

import numpy as np
import sentry_sdk

from config import Config
from services.db import db

logger = logging.getLogger(__name__)
config = Config()

_FILLER_WORDS = {
    "um", "uh", "erm", "hmm", "like", "you know", "i mean", "sort of", "kind of",
}
_SCENARIOS = ("after_pause", "before_pause", "high_filler_density", "low_filler_density")
_MODEL_CACHE: dict[str, dict] = {}


@dataclass
class CandidateWindow:
    scenario: str
    start_sec: float
    end_sec: float
    filler_density: float
    pause_strength: float
    energy_std: float
    transcript_excerpt: str


def _sigmoid(z: float) -> float:
    z = max(-35.0, min(35.0, float(z)))
    return 1.0 / (1.0 + math.exp(-z))


def _load_baseline_model() -> Optional[dict]:
    runtime_path = (db.get_runtime_config("stress_baseline_model_path") or "").strip()
    path = runtime_path or (getattr(config, "STRESS_BASELINE_MODEL_PATH", None) or "").strip()
    if not path:
        return None
    if path in _MODEL_CACHE:
        return _MODEL_CACHE[path]
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        # Basic shape check.
        if not isinstance(data, dict) or "weights" not in data or "norm_mean" not in data or "norm_std" not in data:
            return None
        _MODEL_CACHE[path] = data
        return data
    except Exception as e:
        logger.warning("stress_snippet_service: failed to load baseline model path=%s err=%s", path, e)
        return None


def _resolve_ffmpeg_executable() -> Optional[str]:
    env_path = (os.environ.get("FFMPEG_PATH") or "").strip()
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import imageio_ffmpeg

        bundled = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled:
            return bundled
    except Exception:
        return None
    return None


def _decode_audio_to_pcm(audio_bytes: bytes, ffmpeg_exe: str) -> Optional[np.ndarray]:
    try:
        proc = subprocess.run(
            [
                ffmpeg_exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-acodec",
                "pcm_s16le",
                "-ar",
                "16000",
                "-ac",
                "1",
                "pipe:1",
            ],
            input=audio_bytes,
            capture_output=True,
            timeout=45,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        samples = np.frombuffer(proc.stdout, dtype=np.int16)
        if samples.size == 0:
            return None
        return samples.astype(np.float32) / 32768.0
    except Exception:
        return None


def _extract_clip_mp3(audio_bytes: bytes, ffmpeg_exe: str, start_sec: float, duration_sec: float) -> Optional[bytes]:
    try:
        proc = subprocess.run(
            [
                ffmpeg_exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{max(0.0, start_sec):.3f}",
                "-t",
                f"{max(0.1, duration_sec):.3f}",
                "-i",
                "pipe:0",
                "-f",
                "mp3",
                "-ar",
                "16000",
                "-ac",
                "1",
                "pipe:1",
            ],
            input=audio_bytes,
            capture_output=True,
            timeout=45,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        return proc.stdout
    except Exception:
        return None


def _frame_db(signal: np.ndarray, frame_size: int = 320) -> np.ndarray:
    vals = []
    eps = 1e-9
    for i in range(0, len(signal) - frame_size + 1, frame_size):
        frame = signal[i : i + frame_size]
        rms = math.sqrt(float(np.mean(frame * frame)) + eps)
        vals.append(20.0 * math.log10(rms + eps))
    return np.array(vals, dtype=np.float32)


def _detect_pause_regions(dbs: np.ndarray, frame_ms: int = 20, threshold_db: float = -45.0, min_pause_ms: int = 240) -> list[tuple[float, float]]:
    silent = dbs < threshold_db
    min_frames = max(1, int(min_pause_ms / frame_ms))
    pauses = []
    run_start = None
    run_len = 0
    for i, val in enumerate(silent):
        if val:
            if run_start is None:
                run_start = i
            run_len += 1
            continue
        if run_start is not None and run_len >= min_frames:
            pauses.append((run_start * frame_ms / 1000.0, (run_start + run_len) * frame_ms / 1000.0))
        run_start = None
        run_len = 0
    if run_start is not None and run_len >= min_frames:
        pauses.append((run_start * frame_ms / 1000.0, (run_start + run_len) * frame_ms / 1000.0))
    return pauses


def _split_sentences(transcript: str) -> list[str]:
    text = (transcript or "").strip()
    if not text:
        return []
    chunks = [c.strip() for c in re.split(r"(?<=[.!?])\s+", text) if c.strip()]
    if chunks:
        return chunks
    return [text]


def _count_fillers(text: str) -> int:
    low = f" {(text or '').lower()} "
    total = 0
    for token in _FILLER_WORDS:
        if " " in token:
            total += low.count(f" {token} ")
        else:
            total += len(re.findall(rf"\b{re.escape(token)}\b", low))
    return total


def _clip_bounds(center_sec: float, clip_sec: float, total_sec: float) -> tuple[float, float]:
    half = clip_sec / 2.0
    start = max(0.0, center_sec - half)
    end = min(total_sec, start + clip_sec)
    start = max(0.0, end - clip_sec)
    return start, end


def _overlap_ratio(a: tuple[float, float], b: tuple[float, float]) -> float:
    i = max(0.0, min(a[1], b[1]) - max(a[0], b[0]))
    if i <= 0:
        return 0.0
    return i / max(1e-6, min(a[1] - a[0], b[1] - b[0]))


def _select_diverse(candidates: list[CandidateWindow], max_snippets: int) -> list[CandidateWindow]:
    out: list[CandidateWindow] = []
    by_scenario = {name: [] for name in _SCENARIOS}
    for c in candidates:
        if c.scenario in by_scenario:
            by_scenario[c.scenario].append(c)

    for scenario in _SCENARIOS:
        taken = 0
        for c in by_scenario[scenario]:
            if taken >= 2 or len(out) >= max_snippets:
                break
            if any(_overlap_ratio((c.start_sec, c.end_sec), (x.start_sec, x.end_sec)) > 0.7 for x in out):
                continue
            out.append(c)
            taken += 1

    for c in candidates:
        if len(out) >= max_snippets:
            break
        if any(_overlap_ratio((c.start_sec, c.end_sec), (x.start_sec, x.end_sec)) > 0.7 for x in out):
            continue
        out.append(c)
    return out[:max_snippets]


def _build_candidates(
    transcript: str,
    duration_sec: float,
    dbs: np.ndarray,
    clip_sec: float,
) -> list[CandidateWindow]:
    pause_regions = _detect_pause_regions(dbs)
    sentence_chunks = _split_sentences(transcript)
    candidates: list[CandidateWindow] = []

    # Before/after pause scenarios.
    for p_start, p_end in pause_regions[:12]:
        pre_center = max(0.0, p_start - clip_sec * 0.5)
        post_center = min(duration_sec, p_end + clip_sec * 0.5)
        pre = _clip_bounds(pre_center, clip_sec, duration_sec)
        post = _clip_bounds(post_center, clip_sec, duration_sec)
        candidates.append(
            CandidateWindow(
                scenario="before_pause",
                start_sec=pre[0],
                end_sec=pre[1],
                filler_density=0.0,
                pause_strength=min(1.0, (p_end - p_start) / 1.2),
                energy_std=0.0,
                transcript_excerpt="",
            )
        )
        candidates.append(
            CandidateWindow(
                scenario="after_pause",
                start_sec=post[0],
                end_sec=post[1],
                filler_density=0.0,
                pause_strength=min(1.0, (p_end - p_start) / 1.2),
                energy_std=0.0,
                transcript_excerpt="",
            )
        )

    # Filler-density scenarios by uniformly mapping sentence chunks across duration.
    if sentence_chunks:
        chunk_len = duration_sec / max(1, len(sentence_chunks))
        chunk_stats = []
        for i, sent in enumerate(sentence_chunks):
            start = i * chunk_len
            end = min(duration_sec, (i + 1) * chunk_len)
            fillers = _count_fillers(sent)
            words = max(1, len(re.findall(r"\b[\w']+\b", sent)))
            density = min(1.0, fillers / max(1.0, words * 0.3))
            center = (start + end) / 2.0
            clip_start, clip_end = _clip_bounds(center, clip_sec, duration_sec)
            chunk_stats.append((density, sent[:300], clip_start, clip_end))

        high = sorted(chunk_stats, key=lambda x: x[0], reverse=True)[:6]
        low = sorted(chunk_stats, key=lambda x: x[0])[:6]
        for density, sent, s, e in high:
            candidates.append(
                CandidateWindow(
                    scenario="high_filler_density",
                    start_sec=s,
                    end_sec=e,
                    filler_density=density,
                    pause_strength=0.0,
                    energy_std=0.0,
                    transcript_excerpt=sent,
                )
            )
        for density, sent, s, e in low:
            candidates.append(
                CandidateWindow(
                    scenario="low_filler_density",
                    start_sec=s,
                    end_sec=e,
                    filler_density=density,
                    pause_strength=0.0,
                    energy_std=0.0,
                    transcript_excerpt=sent,
                )
            )

    # Fallback candidates for recordings without pauses/transcript.
    if not candidates:
        for frac in (0.15, 0.35, 0.55, 0.75):
            start, end = _clip_bounds(duration_sec * frac, clip_sec, duration_sec)
            candidates.append(
                CandidateWindow(
                    scenario="uncertain",
                    start_sec=start,
                    end_sec=end,
                    filler_density=0.0,
                    pause_strength=0.0,
                    energy_std=0.0,
                    transcript_excerpt="",
                )
            )
    return candidates


def _energy_std_for_window(signal: np.ndarray, start_sec: float, end_sec: float, sr: int = 16000) -> float:
    s = max(0, int(start_sec * sr))
    e = min(len(signal), int(end_sec * sr))
    if e - s < 200:
        return 0.0
    win = signal[s:e]
    frame = 320
    vals = []
    for i in range(0, len(win) - frame + 1, frame):
        x = win[i : i + frame]
        vals.append(float(np.sqrt(np.mean(x * x) + 1e-9)))
    if len(vals) < 2:
        return 0.0
    return float(np.std(vals))


def _extract_window_signal(signal: np.ndarray, start_sec: float, end_sec: float, sr: int = 16000) -> np.ndarray:
    s = max(0, int(start_sec * sr))
    e = min(len(signal), int(end_sec * sr))
    if e <= s:
        return np.zeros((0,), dtype=np.float32)
    return signal[s:e]


def _feature_vector_for_model(
    window_signal: np.ndarray,
    scenario: str,
    snippet_features: dict,
    duration_ms: int,
) -> np.ndarray:
    frame = 320
    n = len(window_signal) // frame
    if n <= 0:
        return np.zeros((17,), dtype=np.float32)
    frames = window_signal[: n * frame].reshape(n, frame)
    eps = 1e-9
    rms = np.sqrt(np.mean(frames * frames, axis=1) + eps)
    db_vals = 20.0 * np.log10(rms + eps)
    silence_ratio = float(np.mean(db_vals < -45.0))
    energy_mean = float(np.mean(rms))
    energy_std = float(np.std(rms))
    energy_p95 = float(np.percentile(rms, 95))
    energy_p05 = float(np.percentile(rms, 5))
    dynamic_range = float(max(0.0, energy_p95 - energy_p05))
    signs = np.sign(frames)
    zcr = np.mean(np.abs(np.diff(signs, axis=1)) > 0, axis=1)
    zcr_mean = float(np.mean(zcr))
    zcr_std = float(np.std(zcr))
    fft_mag = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(frames.shape[1], d=1.0 / 16000.0)
    denom = np.sum(fft_mag, axis=1) + eps
    centroid = np.sum(fft_mag * freqs[None, :], axis=1) / denom
    centroid_mean = float(np.mean(centroid))
    centroid_std = float(np.std(centroid))
    scenario_one_hot = {
        "after_pause": [1, 0, 0, 0, 0],
        "before_pause": [0, 1, 0, 0, 0],
        "high_filler_density": [0, 0, 1, 0, 0],
        "low_filler_density": [0, 0, 0, 1, 0],
        "uncertain": [0, 0, 0, 0, 1],
    }.get(scenario or "", [0, 0, 0, 0, 1])
    pause_strength = float((snippet_features or {}).get("pause_strength") or 0.0)
    filler_density = float((snippet_features or {}).get("filler_density") or 0.0)
    energy_std_hint = float((snippet_features or {}).get("energy_std") or 0.0)
    clip_duration_s = max(0.1, float(duration_ms or 0) / 1000.0)
    return np.array(
        [
            energy_mean,
            energy_std,
            dynamic_range,
            silence_ratio,
            zcr_mean,
            zcr_std,
            centroid_mean / 4000.0,
            centroid_std / 4000.0,
            pause_strength,
            filler_density,
            energy_std_hint,
            clip_duration_s / 10.0,
            *scenario_one_hot,
        ],
        dtype=np.float32,
    )


def _predict_with_baseline_model(model: dict, vector: np.ndarray) -> Optional[tuple[float, float]]:
    try:
        w = np.array(model.get("weights") or [], dtype=np.float32)
        m = np.array(model.get("norm_mean") or [], dtype=np.float32)
        s = np.array(model.get("norm_std") or [], dtype=np.float32)
        if vector.shape[0] != w.shape[0] or m.shape[0] != w.shape[0] or s.shape[0] != w.shape[0]:
            return None
        s = np.where(s < 1e-6, 1.0, s)
        vn = (vector - m) / s
        bias = float(model.get("bias") or 0.0)
        prob = _sigmoid(float(np.dot(vn, w) + bias))
        confidence = max(0.5, min(1.0, 0.5 + abs(prob - 0.5)))
        return prob, confidence
    except Exception:
        return None


def generate_stress_snippets_for_recording(
    recording_id: str,
    *,
    source_type: str,
    max_snippets: int = 8,
    clip_seconds: int = 10,
    clear_existing: bool = True,
) -> list[dict]:
    """
    Generate and persist up to max_snippets candidate clips for binary stress labeling.
    Uses heuristics + uncertainty proxy (confidence < 0.95 preferred).
    """
    try:
        rec = db.get_recording(recording_id, None)
        if not rec:
            raise ValueError("recording not found")
        storage_path = (rec.get("storage_path") or "").strip()
        if not storage_path:
            raise ValueError("recording has no storage_path")

        ffmpeg_exe = _resolve_ffmpeg_executable()
        if not ffmpeg_exe:
            raise RuntimeError("ffmpeg is required for snippet extraction")

        audio_bytes = db.download_audio(config.AUDIO_BUCKET_NAME, storage_path)
        if not audio_bytes:
            raise ValueError("recording audio is empty")
        signal = _decode_audio_to_pcm(audio_bytes, ffmpeg_exe)
        if signal is None or len(signal) < 1600:
            raise ValueError("could not decode recording audio")

        duration_sec = float(len(signal) / 16000.0)
        dbs = _frame_db(signal)
        transcript = (rec.get("transcription_text") or "").strip()
        candidates = _build_candidates(transcript, duration_sec, dbs, float(clip_seconds))

        baseline_model = _load_baseline_model()
        scored = []
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
            # Prefer suspicious but uncertain windows.
            selection_score = 0.6 * suspicion + 0.4 * uncertainty
            scored.append(
                (
                    selection_score,
                    confidence,
                    prob,
                    CandidateWindow(
                        scenario=c.scenario,
                        start_sec=c.start_sec,
                        end_sec=c.end_sec,
                        filler_density=c.filler_density,
                        pause_strength=c.pause_strength,
                        energy_std=energy_std,
                        transcript_excerpt=c.transcript_excerpt,
                    ),
                )
            )

        scored.sort(key=lambda x: (x[1] < 0.95, x[0]), reverse=True)
        diverse = _select_diverse([x[3] for x in scored], max_snippets=max_snippets)
        selected: list[tuple[float, float, float, CandidateWindow]] = []
        for d in diverse:
            for row in scored:
                if row[3] is d:
                    selected.append(row)
                    break
        selected = selected[:max_snippets]

        if clear_existing:
            try:
                db.v2_delete_stress_snippets_for_recording(recording_id)
            except Exception as del_err:
                logger.warning("stress_snippet_service: cleanup existing snippets failed: %s", del_err)

        rows = []
        for selection_score, confidence, prob, c in selected:
            duration = max(0.5, c.end_sec - c.start_sec)
            clip_bytes = _extract_clip_mp3(audio_bytes, ffmpeg_exe, c.start_sec, duration)
            if not clip_bytes:
                continue
            snippet_id = str(uuid.uuid4())
            clip_path = f"stress_snippets/{recording_id}/{snippet_id}.mp3"
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
                    "classifier_stress_probability": round(float(prob), 5),
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

        inserted = db.v2_insert_stress_snippets(rows)
        return inserted
    except Exception as e:
        logger.warning("stress_snippet_service: generation failed recording_id=%s err=%s", recording_id, e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return []
