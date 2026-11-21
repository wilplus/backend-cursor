"""Explainable librosa features (identical to Step 1/2 `extract_features`, so the trained models see the same inputs)."""
import numpy as np
import librosa

N_MFCC = 13
FEATURE_SR = 24000  # nEMO sample rate; librosa features were trained at this rate
LIB = ["rms_mean", "rms_std", "f0_mean", "f0_std", "f0_range", "onset_rate", "spectral_centroid_mean",
       "spectral_centroid_std"] + [f"mfcc_{i}_mean" for i in range(1, 14)]
WL = ["wl_aro", "wl_dom", "wl_val"]


def extract_features(y: np.ndarray, sr: int) -> dict:
    y = np.asarray(y, dtype=np.float32)
    if y.ndim > 1:
        y = np.mean(y, axis=1)
    duration = float(len(y) / sr) if sr else np.nan
    rms = librosa.feature.rms(y=y)[0]
    f0, _, _ = librosa.pyin(y, fmin=float(librosa.note_to_hz("C2")), fmax=float(librosa.note_to_hz("C7")), sr=sr)
    voiced = f0[~np.isnan(f0)]
    n_voiced = int(len(voiced))
    if n_voiced == 0:
        f0_mean = f0_std = f0_range = np.nan
    else:
        f0_mean, f0_std, f0_range = float(np.mean(voiced)), float(np.std(voiced)), float(np.ptp(voiced))
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    onsets = librosa.onset.onset_detect(onset_envelope=onset_env, sr=sr, units="time")
    onset_rate = float(len(onsets) / duration) if duration and duration > 0 else np.nan
    sc = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=N_MFCC).mean(axis=1)
    feats = {"duration_s": duration, "rms_mean": float(np.mean(rms)), "rms_std": float(np.std(rms)),
             "f0_mean": f0_mean, "f0_std": f0_std, "f0_range": f0_range, "n_voiced_frames": n_voiced,
             "onset_rate": onset_rate, "spectral_centroid_mean": float(np.mean(sc)),
             "spectral_centroid_std": float(np.std(sc))}
    for i, v in enumerate(mfcc, start=1):
        feats[f"mfcc_{i}_mean"] = float(v)
    # share of pyin frames (hop 512) that are voiced; used by the provisional engagement proxy
    feats["voiced_ratio"] = n_voiced / (1 + len(y) // 512)
    return feats
