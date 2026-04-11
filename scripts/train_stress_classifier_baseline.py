#!/usr/bin/env python3
"""
Train a baseline binary stress classifier from labeled stress snippets.

Model:
  - Feature extraction from clip audio (numpy + ffmpeg)
  - Logistic regression (implemented in numpy, no extra deps)
  - Group-aware split by user_id (default) to reduce leakage

Output:
  - JSON model artifact with normalization stats + weights
  - Optional metrics JSON

Usage:
  python3 scripts/train_stress_classifier_baseline.py --model-out exports/stress-model-v1.json
  python3 scripts/train_stress_classifier_baseline.py --model-out exports/stress-model-v1.json --source-type student --min-samples 80
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.db import db  # noqa: E402

SR = 16000


@dataclass
class Example:
    snippet_id: str
    recording_id: str
    session_id: str
    user_id: str
    source_type: str
    y: int
    x: np.ndarray


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -35.0, 35.0)))


def _resolve_ffmpeg_executable() -> Optional[str]:
    env_path = (os.environ.get("FFMPEG_PATH") or "").strip()
    if env_path and os.path.isfile(env_path) and os.access(env_path, os.X_OK):
        return env_path
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path:
        return ffmpeg_path
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
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
                str(SR),
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
        if samples.size < 100:
            return None
        return samples.astype(np.float32) / 32768.0
    except Exception:
        return None


def _frame_view(x: np.ndarray, frame: int = 320) -> np.ndarray:
    n = len(x) // frame
    if n <= 0:
        return np.zeros((0, frame), dtype=np.float32)
    trimmed = x[: n * frame]
    return trimmed.reshape(n, frame)


def _extract_features(signal: np.ndarray, scenario: str, snippet_features: dict, clip_duration_ms: int) -> np.ndarray:
    frames = _frame_view(signal, frame=320)
    if frames.shape[0] == 0:
        return np.zeros((16,), dtype=np.float32)

    eps = 1e-9
    rms = np.sqrt(np.mean(frames * frames, axis=1) + eps)
    db_vals = 20.0 * np.log10(rms + eps)
    silence_ratio = float(np.mean(db_vals < -45.0))
    energy_mean = float(np.mean(rms))
    energy_std = float(np.std(rms))
    energy_p95 = float(np.percentile(rms, 95))
    energy_p05 = float(np.percentile(rms, 5))
    dynamic_range = float(max(0.0, energy_p95 - energy_p05))

    # Zero crossing rate
    signs = np.sign(frames)
    zcr = np.mean(np.abs(np.diff(signs, axis=1)) > 0, axis=1)
    zcr_mean = float(np.mean(zcr))
    zcr_std = float(np.std(zcr))

    # Simple spectral centroid proxy
    fft_mag = np.abs(np.fft.rfft(frames, axis=1))
    freqs = np.fft.rfftfreq(frames.shape[1], d=1.0 / SR)
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
    clip_duration_s = max(0.1, float(clip_duration_ms or 0) / 1000.0)

    feats = np.array(
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
            clip_duration_s / 3.5,
            *scenario_one_hot,
        ],
        dtype=np.float32,
    )
    return feats


def _fetch_labeled_rows(limit: int, source_type: Optional[str]) -> list[dict]:
    rows: list[dict] = []
    page = 1000
    offset = 0
    while len(rows) < limit:
        query = (
            db.client.table("stress_snippets")
            .select("*")
            .order("created_at", desc=False)
            .range(offset, offset + page - 1)
        )
        if source_type:
            query = query.eq("source_type", source_type)
        result = query.execute()
        batch = result.data or []
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < page:
            break
        offset += page
    return [r for r in rows[:limit] if (r.get("coach_label") in ("stress", "no_stress"))]


def _build_examples(rows: list[dict], ffmpeg_exe: str, max_rows: int) -> list[Example]:
    out: list[Example] = []
    for row in rows[:max_rows]:
        path = (row.get("storage_path") or "").strip()
        if not path:
            continue
        try:
            audio_bytes = db.download_audio("audio_recordings", path)
        except Exception:
            continue
        if not audio_bytes:
            continue
        signal = _decode_audio_to_pcm(audio_bytes, ffmpeg_exe)
        if signal is None:
            continue
        y = 1 if row.get("coach_label") == "stress" else 0
        feats = _extract_features(
            signal=signal,
            scenario=(row.get("scenario") or "uncertain"),
            snippet_features=(row.get("features") or {}),
            clip_duration_ms=int(row.get("duration_ms") or 0),
        )
        out.append(
            Example(
                snippet_id=str(row.get("id")),
                recording_id=str(row.get("recording_id") or ""),
                session_id=str(row.get("session_id") or ""),
                user_id=str(row.get("user_id") or ""),
                source_type=str(row.get("source_type") or ""),
                y=y,
                x=feats,
            )
        )
    return out


def _group_key(ex: Example, split_group: str) -> str:
    mode = (split_group or "user_id").strip().lower()
    if mode == "session_id":
        return ex.session_id or ex.recording_id or ex.user_id or ex.snippet_id
    if mode == "recording_id":
        return ex.recording_id or ex.session_id or ex.user_id or ex.snippet_id
    if mode == "user_id":
        return ex.user_id or ex.session_id or ex.recording_id or ex.snippet_id
    raise ValueError("split_group must be one of: user_id, session_id, recording_id")


def _split_grouped(
    examples: list[Example],
    train_ratio: float,
    seed: int,
    split_group: str,
) -> tuple[list[Example], list[Example]]:
    random.seed(seed)
    groups: dict[str, list[Example]] = {}
    for ex in examples:
        groups.setdefault(_group_key(ex, split_group), []).append(ex)
    keys = list(groups.keys())
    random.shuffle(keys)
    pivot = max(1, int(round(len(keys) * train_ratio)))
    train_keys = set(keys[:pivot])
    train = []
    val = []
    for k, vals in groups.items():
        (train if k in train_keys else val).extend(vals)
    if not val:
        val = train[-max(1, len(train) // 5) :]
        train = train[: len(train) - len(val)]
    return train, val


def _as_matrix(examples: list[Example]) -> tuple[np.ndarray, np.ndarray]:
    x = np.stack([e.x for e in examples], axis=0)
    y = np.array([e.y for e in examples], dtype=np.float32)
    return x, y


def _normalize_fit(x_train: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    mean = np.mean(x_train, axis=0)
    std = np.std(x_train, axis=0)
    std = np.where(std < 1e-6, 1.0, std)
    return mean, std


def _metrics(y_true: np.ndarray, p: np.ndarray, threshold: float = 0.5) -> dict:
    pred = (p >= threshold).astype(np.float32)
    tp = float(np.sum((pred == 1) & (y_true == 1)))
    tn = float(np.sum((pred == 0) & (y_true == 0)))
    fp = float(np.sum((pred == 1) & (y_true == 0)))
    fn = float(np.sum((pred == 0) & (y_true == 1)))
    acc = (tp + tn) / max(1.0, len(y_true))
    precision = tp / max(1.0, tp + fp)
    recall = tp / max(1.0, tp + fn)
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    return {
        "accuracy": round(acc, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "tp": int(tp),
        "tn": int(tn),
        "fp": int(fp),
        "fn": int(fn),
    }


def _train_logreg(x_train: np.ndarray, y_train: np.ndarray, x_val: np.ndarray, y_val: np.ndarray, *, lr: float, epochs: int, l2: float) -> tuple[np.ndarray, float, dict]:
    n, d = x_train.shape
    w = np.zeros((d,), dtype=np.float32)
    b = 0.0
    history = {"train_loss": [], "val_loss": []}
    for _ in range(epochs):
        z = x_train @ w + b
        p = _sigmoid(z)
        grad_w = (x_train.T @ (p - y_train)) / max(1, n) + l2 * w
        grad_b = float(np.mean(p - y_train))
        w -= lr * grad_w
        b -= lr * grad_b

        train_loss = float(
            -np.mean(y_train * np.log(p + 1e-9) + (1.0 - y_train) * np.log(1.0 - p + 1e-9))
            + 0.5 * l2 * float(np.sum(w * w))
        )
        pv = _sigmoid(x_val @ w + b)
        val_loss = float(-np.mean(y_val * np.log(pv + 1e-9) + (1.0 - y_val) * np.log(1.0 - pv + 1e-9)))
        history["train_loss"].append(train_loss)
        history["val_loss"].append(val_loss)
    return w, float(b), history


def main() -> None:
    parser = argparse.ArgumentParser(description="Train baseline stress classifier from labeled snippets.")
    parser.add_argument("--model-out", required=True, help="Output JSON model artifact path")
    parser.add_argument("--metrics-out", default=None, help="Optional output metrics JSON path")
    parser.add_argument("--limit", type=int, default=20000, help="Max labeled snippets scanned")
    parser.add_argument("--max-train-rows", type=int, default=5000, help="Cap snippets used for training")
    parser.add_argument("--source-type", choices=["all", "student", "internet"], default="all")
    parser.add_argument("--min-samples", type=int, default=80, help="Minimum labeled snippets to train")
    parser.add_argument("--train-ratio", type=float, default=0.8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--split-group",
        choices=["user_id", "session_id", "recording_id"],
        default="user_id",
        help="Leakage guard: keep each group key entirely in train or val (default user_id)",
    )
    parser.add_argument("--epochs", type=int, default=350)
    parser.add_argument("--lr", type=float, default=0.08)
    parser.add_argument("--l2", type=float, default=0.002)
    parser.add_argument("--target-recall-stress", type=float, default=0.85)
    parser.add_argument("--target-precision-stress", type=float, default=0.75)
    parser.add_argument("--target-fpr-no-stress", type=float, default=0.30)
    args = parser.parse_args()

    ffmpeg_exe = _resolve_ffmpeg_executable()
    if not ffmpeg_exe:
        raise SystemExit("ffmpeg binary not found. Install ffmpeg or set FFMPEG_PATH.")

    source_filter = None if args.source_type == "all" else args.source_type
    rows = _fetch_labeled_rows(limit=max(1, int(args.limit)), source_type=source_filter)
    if len(rows) < args.min_samples:
        raise SystemExit(
            f"Not enough labeled snippets to train. Need >= {args.min_samples}, got {len(rows)}."
        )
    examples = _build_examples(rows, ffmpeg_exe=ffmpeg_exe, max_rows=max(1, int(args.max_train_rows)))
    if len(examples) < args.min_samples:
        raise SystemExit(
            f"Not enough decodable labeled snippets. Need >= {args.min_samples}, got {len(examples)}."
        )
    positives = sum(e.y for e in examples)
    negatives = len(examples) - positives
    if positives < 10 or negatives < 10:
        raise SystemExit(
            f"Label imbalance too extreme for baseline training (stress={positives}, no_stress={negatives})."
        )

    train_ex, val_ex = _split_grouped(
        examples,
        train_ratio=max(0.5, min(0.95, float(args.train_ratio))),
        seed=int(args.seed),
        split_group=args.split_group,
    )
    x_train, y_train = _as_matrix(train_ex)
    x_val, y_val = _as_matrix(val_ex)

    mean, std = _normalize_fit(x_train)
    x_train_n = (x_train - mean) / std
    x_val_n = (x_val - mean) / std

    w, b, history = _train_logreg(
        x_train_n,
        y_train,
        x_val_n,
        y_val,
        lr=float(args.lr),
        epochs=max(10, int(args.epochs)),
        l2=max(0.0, float(args.l2)),
    )

    p_train = _sigmoid(x_train_n @ w + b)
    p_val = _sigmoid(x_val_n @ w + b)
    train_metrics = _metrics(y_train, p_train)
    val_metrics = _metrics(y_val, p_val)
    val_fpr = float(val_metrics["fp"]) / max(
        1.0, float(val_metrics["fp"]) + float(val_metrics["tn"])
    )
    quality_gate = {
        "targets": {
            "recall_stress_min": round(float(args.target_recall_stress), 4),
            "precision_stress_min": round(float(args.target_precision_stress), 4),
            "fpr_no_stress_max": round(float(args.target_fpr_no_stress), 4),
        },
        "actual": {
            "recall_stress": round(float(val_metrics["recall"]), 4),
            "precision_stress": round(float(val_metrics["precision"]), 4),
            "fpr_no_stress": round(val_fpr, 4),
        },
        "passes": {
            "recall_stress": float(val_metrics["recall"]) >= float(args.target_recall_stress),
            "precision_stress": float(val_metrics["precision"]) >= float(args.target_precision_stress),
            "fpr_no_stress": val_fpr <= float(args.target_fpr_no_stress),
        },
    }
    quality_gate["ok"] = bool(all(quality_gate["passes"].values()))

    feature_names = [
        "energy_mean",
        "energy_std",
        "dynamic_range",
        "silence_ratio",
        "zcr_mean",
        "zcr_std",
        "centroid_mean_norm",
        "centroid_std_norm",
        "pause_strength_hint",
        "filler_density_hint",
        "energy_std_hint",
        "clip_duration_norm",
        "scenario_after_pause",
        "scenario_before_pause",
        "scenario_high_filler_density",
        "scenario_low_filler_density",
        "scenario_uncertain",
    ]

    artifact = {
        "model_type": "logreg_baseline_v1",
        "target": "stress_binary",
        "label_map": {"no_stress": 0, "stress": 1},
        "feature_names": feature_names,
        "norm_mean": mean.tolist(),
        "norm_std": std.tolist(),
        "weights": w.tolist(),
        "bias": b,
        "training": {
            "source_type": args.source_type,
            "split_group": args.split_group,
            "epochs": int(args.epochs),
            "learning_rate": float(args.lr),
            "l2": float(args.l2),
            "seed": int(args.seed),
            "train_size": len(train_ex),
            "val_size": len(val_ex),
            "positives_total": int(positives),
            "negatives_total": int(negatives),
        },
        "metrics": {
            "train": train_metrics,
            "val": val_metrics,
            "quality_gate": quality_gate,
            "final_train_loss": float(history["train_loss"][-1]),
            "final_val_loss": float(history["val_loss"][-1]),
        },
    }

    model_out = Path(args.model_out)
    model_out.parent.mkdir(parents=True, exist_ok=True)
    model_out.write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding="utf-8")

    metrics_obj = {
        "train": train_metrics,
        "val": val_metrics,
        "quality_gate": quality_gate,
        "train_size": len(train_ex),
        "val_size": len(val_ex),
        "total_examples": len(examples),
    }
    if args.metrics_out:
        metrics_out = Path(args.metrics_out)
        metrics_out.parent.mkdir(parents=True, exist_ok=True)
        metrics_out.write_text(json.dumps(metrics_obj, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"Training complete. model_out={model_out}")
    print(
        "Validation metrics: "
        f"accuracy={val_metrics['accuracy']} "
        f"precision={val_metrics['precision']} "
        f"recall={val_metrics['recall']} "
        f"f1={val_metrics['f1']}"
    )
    print(
        "Quality gate: "
        f"ok={quality_gate['ok']} "
        f"recall_min={quality_gate['targets']['recall_stress_min']} "
        f"precision_min={quality_gate['targets']['precision_stress_min']} "
        f"fpr_max={quality_gate['targets']['fpr_no_stress_max']} "
        f"fpr_actual={quality_gate['actual']['fpr_no_stress']}"
    )


if __name__ == "__main__":
    main()
