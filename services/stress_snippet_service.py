import itertools
import logging
import math
import os
import re
import shutil
import subprocess
import json
import uuid
from dataclasses import dataclass
from typing import Optional, Tuple

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
# Each exported clip is trimmed to at most this many seconds (product cap).
STRESS_SNIPPET_CLIP_SEC_DEFAULT = 5.0
STRESS_SNIPPET_CLIP_SEC_MIN = 0.5
STRESS_SNIPPET_CLIP_SEC_MAX = 5.0
_MODEL_CACHE: dict[str, dict] = {}

# MMR / diversity (time IoU + acoustic embedding). Global assignment = exhaustive on top-K per scenario.
_MMR_LAMBDA = 0.62
_IOU_DIV_WEIGHT = 0.58
_EMB_DIV_WEIGHT = 0.42
_SCENARIO_COVER_BONUS = 0.2
_GLOBAL_ASSIGN_DIV_WEIGHT = 0.92
_GLOBAL_TOP_K_PER_SCENARIO = 6
_UTTERANCE_MIN_SEC = 0.15

# Student snippets: drop near-duplicates after selection (same speaker → similar embeddings).
# High pairwise penalty = more similar (IoU + acoustic proxy). Prefer none; allow at most
# `replica_budget` keeps that exceed `strict` but stay under `relaxed`.
_STUDENT_PAIR_STRICT = 0.34
_STUDENT_PAIR_RELAXED = 0.66
_STUDENT_REPLICA_BUDGET = 2


@dataclass
class CandidateWindow:
    scenario: str
    start_sec: float
    end_sec: float
    filler_density: float
    pause_strength: float
    energy_std: float
    transcript_excerpt: str


@dataclass
class ScoredClip:
    selection_score: float
    confidence: float
    prob: float
    cand: CandidateWindow
    emb: np.ndarray


def _sigmoid(z: float) -> float:
    z = max(-35.0, min(35.0, float(z)))
    return 1.0 / (1.0 + math.exp(-z))


def _parse_storage_uri(uri: str) -> Optional[Tuple[str, str]]:
    raw = (uri or "").strip()
    prefix = "storage://"
    if not raw.startswith(prefix):
        return None
    rest = raw[len(prefix) :].lstrip("/")
    if "/" not in rest:
        return None
    bucket, _, obj_key = rest.partition("/")
    bucket, obj_key = bucket.strip(), obj_key.strip()
    if not bucket or not obj_key:
        return None
    return bucket, obj_key


def _load_baseline_model() -> Optional[dict]:
    runtime_path = (db.get_runtime_config("stress_baseline_model_path") or "").strip()
    path = runtime_path or (getattr(config, "STRESS_BASELINE_MODEL_PATH", None) or "").strip()
    if not path:
        return None
    if path in _MODEL_CACHE:
        return _MODEL_CACHE[path]
    try:
        storage = _parse_storage_uri(path)
        if storage:
            bucket, obj_key = storage
            raw = db.download_audio(bucket, obj_key)
            data = json.loads(raw.decode("utf-8"))
        else:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
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
    """Cut a segment from in-memory audio.

    Input is a pipe, so **-ss must come after -i**. Seeking before -i does not work on
    non-seekable stdin and often yields empty or unplayable MP3s for later segments.
    """
    try:
        dur = max(0.25, float(duration_sec))
        proc = subprocess.run(
            [
                ffmpeg_exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                "pipe:0",
                "-ss",
                f"{max(0.0, start_sec):.3f}",
                "-t",
                f"{dur:.3f}",
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
            timeout=120,
        )
        if proc.returncode != 0 or not proc.stdout:
            if proc.stderr:
                logger.warning(
                    "stress_snippet_service: ffmpeg clip failed rc=%s stderr=%s",
                    proc.returncode,
                    proc.stderr.decode("utf-8", errors="replace")[:500],
                )
            return None
        if len(proc.stdout) < 256:
            logger.warning("stress_snippet_service: ffmpeg produced very small mp3 (%s bytes)", len(proc.stdout))
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


def _floor_clip_window(
    start_sec: float,
    end_sec: float,
    duration_sec: float,
    *,
    min_span_sec: float = 0.5,
) -> tuple[float, float]:
    """Widen windows shorter than min_span_sec (stable cut); does not exceed recording bounds."""
    if duration_sec <= 0:
        return start_sec, end_sec
    span = max(0.0, float(end_sec) - float(start_sec))
    cap = min(float(min_span_sec), float(duration_sec))
    if span >= cap - 1e-3:
        return start_sec, end_sec
    center = (float(start_sec) + float(end_sec)) / 2.0
    half = cap / 2.0
    ns = max(0.0, center - half)
    ne = min(float(duration_sec), ns + cap)
    ns = max(0.0, ne - cap)
    return ns, ne


def _time_iou(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Intersection-over-union on time intervals (object-detection style overlap)."""
    s1, e1 = float(a[0]), float(a[1])
    s2, e2 = float(b[0]), float(b[1])
    inter = max(0.0, min(e1, e2) - max(s1, s2))
    if inter <= 0:
        return 0.0
    union = (e1 - s1) + (e2 - s2) - inter
    return inter / max(union, 1e-9)


def _utterance_regions_from_pauses(
    pauses: list[tuple[float, float]], duration_sec: float
) -> list[tuple[float, float]]:
    """Speech segments between VAD-style pauses (natural acoustic boundaries)."""
    if duration_sec <= 0:
        return []
    if not pauses:
        return [(0.0, duration_sec)]
    pauses = sorted(pauses, key=lambda x: x[0])
    regions: list[tuple[float, float]] = []
    t = 0.0
    for ps, pe in pauses:
        if ps > t + 1e-4:
            regions.append((t, min(ps, duration_sec)))
        t = max(t, pe)
    if t < duration_sec - 1e-4:
        regions.append((t, duration_sec))
    out = [(a, b) for a, b in regions if (b - a) >= _UTTERANCE_MIN_SEC]
    return out if out else [(0.0, duration_sec)]


def _clip_bounds_utterance(
    center: float, clip_sec: float, u0: float, u1: float, total_sec: float
) -> tuple[float, float]:
    """Place a clip preferentially inside a speech utterance (reduces sliding-window bleed)."""
    u0, u1 = float(u0), float(u1)
    if (u1 - u0) >= clip_sec:
        c = min(max(center, u0 + clip_sec * 0.5), u1 - clip_sec * 0.5)
        return _clip_bounds(c, clip_sec, total_sec)
    c = (u0 + u1) * 0.5
    return _clip_bounds(c, clip_sec, total_sec)


def _build_candidates(
    transcript: str,
    duration_sec: float,
    dbs: np.ndarray,
    clip_sec: float,
) -> list[CandidateWindow]:
    pause_regions = _detect_pause_regions(dbs)
    utterances = _utterance_regions_from_pauses(pause_regions, duration_sec)
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

    # Filler-density scenarios: map each sentence to a VAD-derived utterance (not uniform time slicing).
    if sentence_chunks and utterances:
        nu = len(utterances)
        chunk_stats = []
        for i, sent in enumerate(sentence_chunks):
            u_idx = min(nu - 1, int((i + 0.5) / max(1, len(sentence_chunks)) * nu))
            u0, u1 = utterances[u_idx]
            fillers = _count_fillers(sent)
            words = max(1, len(re.findall(r"\b[\w']+\b", sent)))
            density = min(1.0, fillers / max(1.0, words * 0.3))
            center = (u0 + u1) * 0.5
            clip_start, clip_end = _clip_bounds_utterance(center, clip_sec, u0, u1, duration_sec)
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


def _acoustic_diversity_embedding(
    signal: np.ndarray, start_sec: float, end_sec: float, sr: int = 16000
) -> np.ndarray:
    """Lightweight normalized embedding for acoustic diversity (proxy for submodular / clustering ideas)."""
    w = _extract_window_signal(signal, start_sec, end_sec, sr)
    if w.size < 320:
        return np.zeros((13,), dtype=np.float32)
    frame = 320
    n = max(1, len(w) // frame)
    chunk = w[: n * frame].reshape(n, frame)
    eps = 1e-9
    rms = np.sqrt(np.mean(chunk * chunk, axis=1) + eps)
    log_rms = np.log1p(rms.astype(np.float64)).astype(np.float32)
    lo, hi = float(log_rms.min()), float(log_rms.max())
    if hi <= lo + 1e-9:
        hist = np.zeros((8,), dtype=np.float32)
    else:
        hist, _ = np.histogram(log_rms, bins=8, range=(lo, hi + 1e-6))
        hist = hist.astype(np.float32)
    d = np.diff(rms)
    if d.size == 0:
        dmean, dstd = 0.0, 0.0
    else:
        dmean, dstd = float(np.mean(d)), float(np.std(d))
    stats = np.array(
        [
            float(np.mean(rms)),
            float(np.std(rms)),
            dmean,
            dstd,
            float(np.mean(rms < 0.02)),
        ],
        dtype=np.float32,
    )
    out = np.concatenate([hist, stats]).astype(np.float32)
    nrm = float(np.linalg.norm(out))
    if nrm < 1e-6:
        return out
    return (out / nrm).astype(np.float32)


def _pair_diversity_penalty(
    a: CandidateWindow, ea: np.ndarray, b: CandidateWindow, eb: np.ndarray
) -> float:
    iou = _time_iou((a.start_sec, a.end_sec), (b.start_sec, b.end_sec))
    cos = float(np.clip(np.dot(ea, eb), -1.0, 1.0))
    emb01 = (cos + 1.0) * 0.5
    return _IOU_DIV_WEIGHT * iou + _EMB_DIV_WEIGHT * emb01


def _rel_scores_normalized(items: list[ScoredClip]) -> np.ndarray:
    raw = np.array([it.selection_score for it in items], dtype=np.float64)
    if raw.size == 0:
        return raw
    lo, hi = float(np.min(raw)), float(np.max(raw))
    if hi <= lo + 1e-12:
        return np.ones_like(raw)
    return ((raw - lo) / (hi - lo)).astype(np.float64)


def _global_scenario_assignment(items: list[ScoredClip], rel: np.ndarray) -> list[int]:
    """Exhaustive search over top-K per scenario: maximizes relevance minus diversity penalty."""
    by_s: dict[str, list[int]] = {name: [] for name in _SCENARIOS}
    for i, it in enumerate(items):
        if it.cand.scenario in by_s:
            by_s[it.cand.scenario].append(i)
    for name in _SCENARIOS:
        by_s[name].sort(key=lambda idx: rel[idx], reverse=True)
        by_s[name] = by_s[name][: _GLOBAL_TOP_K_PER_SCENARIO]
    lists = [by_s[name] if by_s[name] else [None] for name in _SCENARIOS]
    best_picked: list[int] = []
    best_total = -1e18
    for combo in itertools.product(*lists):
        picked = [x for x in combo if x is not None]
        if len(picked) != len(set(picked)):
            continue
        rel_sum = sum(float(rel[i]) for i in picked)
        pen = 0.0
        for xa in range(len(picked)):
            for xb in range(xa + 1, len(picked)):
                ia, ib = picked[xa], picked[xb]
                pen += _pair_diversity_penalty(items[ia].cand, items[ia].emb, items[ib].cand, items[ib].emb)
        total = rel_sum - _GLOBAL_ASSIGN_DIV_WEIGHT * pen
        if total > best_total:
            best_total = total
            best_picked = list(picked)
    return best_picked


def _mmr_greedy_extend(
    items: list[ScoredClip],
    rel: np.ndarray,
    selected: list[int],
    max_snippets: int,
    seen: set[int],
) -> None:
    covered = {
        items[i].cand.scenario for i in selected if items[i].cand.scenario in _SCENARIOS
    }
    n = len(items)
    while len(selected) < max_snippets:
        best_i: Optional[int] = None
        best_mmr = -1e18
        for i in range(n):
            if i in seen:
                continue
            r = float(rel[i])
            if items[i].cand.scenario in _SCENARIOS and items[i].cand.scenario not in covered:
                r += _SCENARIO_COVER_BONUS
            if not selected:
                div = 0.0
            else:
                div = max(
                    _pair_diversity_penalty(
                        items[i].cand, items[i].emb, items[j].cand, items[j].emb
                    )
                    for j in selected
                )
            mmr = _MMR_LAMBDA * r - (1.0 - _MMR_LAMBDA) * div
            if mmr > best_mmr:
                best_mmr = mmr
                best_i = i
        if best_i is None:
            break
        selected.append(best_i)
        seen.add(best_i)
        sc = items[best_i].cand.scenario
        if sc in _SCENARIOS:
            covered.add(sc)


def _worst_penalty_to_indices(items: list[ScoredClip], i: int, kept: list[int]) -> float:
    if not kept:
        return 0.0
    return max(
        _pair_diversity_penalty(items[i].cand, items[i].emb, items[j].cand, items[j].emb) for j in kept
    )


def _dedupe_ordered_clip_indices(
    ordered: list[int],
    items: list[ScoredClip],
    *,
    strict: float,
    relaxed: float,
    replica_budget: int,
) -> list[int]:
    """Keep selection order; skip clips that are too similar to already kept (student pipeline)."""
    out: list[int] = []
    replicas_used = 0
    for i in ordered:
        if i < 0 or i >= len(items):
            continue
        if not out:
            out.append(i)
            continue
        w = _worst_penalty_to_indices(items, i, out)
        if w <= strict:
            out.append(i)
        elif w <= relaxed and replicas_used < replica_budget:
            out.append(i)
            replicas_used += 1
    return out


def _select_clip_indices(
    items: list[ScoredClip],
    max_snippets: int,
    *,
    source_type: str = "",
) -> list[int]:
    """Global scenario assignment (small search) + Maximum Marginal Relevance for remaining slots."""
    n = len(items)
    if n == 0 or max_snippets <= 0:
        return []
    rel = _rel_scores_normalized(items)
    seed = _global_scenario_assignment(items, rel)
    selected: list[int] = []
    seen: set[int] = set()
    for i in seed:
        if 0 <= i < n and i not in seen:
            selected.append(i)
            seen.add(i)
    _mmr_greedy_extend(items, rel, selected, max_snippets, seen)
    out = selected[:max_snippets]
    if (source_type or "").strip().lower() == "student":
        before = len(out)
        out = _dedupe_ordered_clip_indices(
            out,
            items,
            strict=_STUDENT_PAIR_STRICT,
            relaxed=_STUDENT_PAIR_RELAXED,
            replica_budget=_STUDENT_REPLICA_BUDGET,
        )
        if len(out) < before:
            logger.info(
                "stress_snippet_service: student dedupe removed %s near-duplicate clip(s) (kept %s)",
                before - len(out),
                len(out),
            )
    return out


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
            clip_duration_s / max(0.1, float(STRESS_SNIPPET_CLIP_SEC_MAX)),
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
    clip_seconds: float = STRESS_SNIPPET_CLIP_SEC_DEFAULT,
    clear_existing: bool = True,
) -> list[dict]:
    """
    Generate and persist up to max_snippets candidate clips for binary stress labeling.
    Selection uses VAD-aligned utterance windows, time IoU + acoustic embedding diversity,
    a small exhaustive assignment across the four scenario buckets, then MMR for extras.
    """
    try:
        try:
            clip_sec = float(clip_seconds)
        except (TypeError, ValueError):
            clip_sec = float(STRESS_SNIPPET_CLIP_SEC_DEFAULT)
        clip_sec = max(
            float(STRESS_SNIPPET_CLIP_SEC_MIN),
            min(clip_sec, float(STRESS_SNIPPET_CLIP_SEC_MAX)),
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
        # (see services.audio_storage). The audio_storage helper hides
        # the R2/Supabase choice — same module used by every other
        # consumer so this can't drift again.
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
                db.v2_delete_stress_snippets_for_recording(recording_id)
            except Exception as del_err:
                logger.warning("stress_snippet_service: cleanup existing snippets failed: %s", del_err)

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
                    "stress_snippet_service: skip degenerate window recording_id=%s scenario=%s",
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
