"""build_baseline() and analyze_take(): the Step 2 arousal-direction model packaged for POST /analyze-take."""
import json, time, uuid, warnings
from datetime import datetime, timezone
from importlib import resources
import numpy as np
import joblib
import librosa
import soundfile as sf

from . import models, clarity as clarity_mod
from .features import extract_features, LIB, WL, FEATURE_SR

__version__ = "0.2.0"
SCHEMA = "analyze-take/v0.1"
ORDER = ["engagement", "arousal", "valence", "clarity"]
CHUNK_S = 2.5      # summary judges run on ~2.5 s chunks (nEMO training clips are 0.9-5.7 s, median 2.4 s)
MIN_LAST_S = 1.0   # a shorter tail is merged into the previous chunk
WIN_S = 1.0        # grid: one moment per second
MIN_WIN_S = 0.4
ENG_COLS = ["rms_mean", "onset_rate", "voiced_ratio"]
PROVISIONAL = {
    "engagement": "heuristic proxy (loudness, speech-activity rate, voiced share vs your baseline); no engagement labels yet",
    "valence": "trained on acted speech (nEMO); expect lower accuracy on real founders",
    "clarity": "simple reference score (embedding similarity to the business case + filler words); uncalibrated",
    "word_sentiment": "whole-take HerBERT sentiment, not time-aligned; carried ~0 weight in training (nEMO sentences are emotion-neutral)",
}

# Grid layout: (step, cue, feature, scored against)
GRID = [("engagement", "voiced_ratio", "voiced_ratio", "baseline"),
        ("engagement", "loudness", "rms_mean", "baseline"),
        ("engagement", "speech_activity_rate", "onset_rate", "baseline"),
        ("arousal", "pitch_level", "f0_mean", "baseline"),
        ("arousal", "pitch_range", "f0_range", "baseline"),
        ("arousal", "voice_brightness", "spectral_centroid_mean", "baseline"),
        ("arousal", "wavlm_arousal", "wl_aro", "baseline"),
        ("valence", "wavlm_valence", "wl_val", "baseline"),
        ("valence", "wavlm_dominance", "wl_dom", "baseline"),
        ("valence", "pitch_variability", "f0_std", "baseline"),
        ("valence", "word_sentiment", "tx_val", "reference"),
        ("clarity", "business_case_coverage", None, "reference"),
        ("clarity", "semantic_similarity", None, "reference"),
        ("clarity", "filler_word_rate", None, "reference")]
WIN_COLS = sorted({c for _, _, c, v in GRID if c and v == "baseline"})
CHUNK_COLS = sorted(set(LIB + WL + ENG_COLS))

_art = {}


def _artifacts():
    if not _art:
        base = resources.files("wpl_arousal") / "artifacts"
        with resources.as_file(base / "models.joblib") as p:
            _art["models"] = joblib.load(p)
        _art["thresholds"] = json.loads((base / "thresholds.json").read_text())["thresholds"]
    return _art


def thresholds():
    return dict(_artifacts()["thresholds"])


# ---------------- audio + features ----------------
def _load(path):
    try:
        y, sr = sf.read(path, dtype="float32", always_2d=False)
    except Exception:  # mp3/webm etc. need ffmpeg/audioread; converting to wav upstream is safer
        y, sr = librosa.load(path, sr=None, mono=True)
    if y.ndim > 1:
        y = y.mean(axis=1)
    if len(y) == 0:
        raise ValueError(f"empty audio: {path}")
    y24 = librosa.resample(y, orig_sr=sr, target_sr=FEATURE_SR) if sr != FEATURE_SR else y
    return y24.astype(np.float32)


def _spans(n_samples, sr, size_s, min_last_s):
    size, n = int(size_s * sr), n_samples
    starts = list(range(0, n, size)) or [0]
    spans = [[s, min(s + size, n)] for s in starts]
    if len(spans) > 1 and (spans[-1][1] - spans[-1][0]) < min_last_s * sr:
        spans[-2][1] = spans[-1][1]; spans.pop()
    return spans


def _feats(seg24):
    f = extract_features(seg24, FEATURE_SR)
    y16 = librosa.resample(seg24, orig_sr=FEATURE_SR, target_sr=16000)
    f.update(models.wavlm_scores(y16))
    return f


def _chunk_feats(y24):
    rows = [_feats(y24[a:b]) for a, b in _spans(len(y24), FEATURE_SR, CHUNK_S, MIN_LAST_S)]
    voiced = [r for r in rows if r["n_voiced_frames"] > 0]
    return voiced or rows


def _stats(rows, cols):
    out = {}
    for c in cols:
        v = np.array([r.get(c, np.nan) for r in rows], dtype=float); v = v[np.isfinite(v)]
        mu = float(v.mean()) if len(v) else float("nan")
        sd = float(v.std(ddof=1)) if len(v) > 1 else float("nan")
        if not np.isfinite(sd) or sd == 0:
            sd = 1.0  # same rule as training
        out[c] = {"mean": mu if np.isfinite(mu) else None, "sd": sd}
    return out


def _z(val, st):
    if val is None or st is None or st["mean"] is None or not np.isfinite(val):
        return np.nan
    return (val - st["mean"]) / st["sd"]


def _cell(z):
    return None if z is None or not np.isfinite(z) else round(float(np.clip(z / 2.0, -1, 1)), 4)


# ---------------- public API ----------------
def build_baseline(calm_audio_paths, volunteer_id=None) -> dict:
    """Personal 'normal voice' from the calm baseline recordings (prompts tagged baseline_calm).
    Returns a small JSON-serialisable dict of per-cue mean/SD (no audio, no transcript). Store it per anonymous
    volunteer ID and delete it with the volunteer's data."""
    if isinstance(calm_audio_paths, (str, bytes)):
        calm_audio_paths = [calm_audio_paths]
    chunks, windows, secs = [], [], 0.0
    for p in calm_audio_paths:
        y = _load(p); secs += len(y) / FEATURE_SR
        chunks += _chunk_feats(y)
        for a, b in _spans(len(y), FEATURE_SR, WIN_S, MIN_WIN_S):
            if (b - a) >= MIN_WIN_S * FEATURE_SR:
                windows.append(_feats(y[a:b]))
    warn = []
    if secs < 30:
        warn.append(f"only {secs:.0f} s of calm speech; 60-120 s (2-3 baseline prompts) is recommended")
    if len(chunks) < 10:
        warn.append(f"only {len(chunks)} voiced 2.5 s chunks; baseline SDs are unreliable below ~10")
    return {"baseline_version": SCHEMA, "package_version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "volunteer_id": volunteer_id, "n_recordings": len(calm_audio_paths),
            "seconds": round(secs, 2), "n_chunks": len(chunks), "n_windows": len(windows),
            "chunk_stats": _stats(chunks, CHUNK_COLS), "window_stats": _stats(windows, WIN_COLS), "warnings": warn}


def _judges(task, zrows, tx_val):
    art = _artifacts()["models"][task]
    X = {"librosa": np.array([[r[c] for c in LIB] for r in zrows], dtype=float),
         "wavlm": np.array([[r[c] for c in WL] for r in zrows], dtype=float),
         "text": np.full((len(zrows), 1), np.nan if tx_val is None else tx_val, dtype=float)}
    import pandas as pd
    p = {j: art["judges"][j].predict_proba(pd.DataFrame(X[j], columns=LIB if j == "librosa" else WL if j == "wavlm" else ["tx_val"]))[:, 1]
         for j in art["judge_order"]}
    lg = lambda q: np.log(np.clip(q, 1e-4, 1 - 1e-4) / (1 - np.clip(q, 1e-4, 1 - 1e-4)))
    Z = np.column_stack([lg(p[j]) for j in art["judge_order"]])
    Zv = np.column_stack([lg(p[j]) for j in art["voice_order"]])
    # fuse per chunk in logit space, then average the stacker logits over the take
    fused = float(1 / (1 + np.exp(-np.mean(art["stacker"].decision_function(Z)))))
    voice = float(1 / (1 + np.exp(-np.mean(art["stacker_voice"].decision_function(Zv)))))
    return fused, voice, {j: round(float(np.mean(v)), 3) for j, v in p.items()}


def analyze_take(audio_path, transcript=None, baseline=None, business_case=None, take_id=None, prompt_tag=None) -> dict:
    """Analyse one take. Returns the analyze-take document (same shape as example_analyze_take.json):
    {schema, value_range, value_scaling, thresholds, ..., takes: [ {take_id, order, transcript, moments, summary, gate} ]}"""
    if not baseline or "chunk_stats" not in baseline:
        raise ValueError("baseline is required: call build_baseline() on the volunteer's calm recordings first")
    t0 = time.perf_counter()
    T = thresholds()
    y = _load(audio_path); dur = len(y) / FEATURE_SR
    transcript = (transcript or "").strip() or None

    # text judge (reference scale)
    tx_val = None
    if transcript:
        tx_val = models.text_sentiment(clarity_mod.split_sentences(transcript) or [transcript])
    # clarity (reference: business case)
    cla = clarity_mod.score(transcript, business_case) if (transcript and business_case and business_case.strip()) else None

    # ---- moments: 1 s grid ----
    WS = baseline["window_stats"]; moments = []
    for a, b in _spans(len(y), FEATURE_SR, WIN_S, MIN_WIN_S):
        f = _feats(y[a:b]); cells = []
        for step, cue, col, vs in GRID:
            note = None
            if step == "clarity":
                if cla is None:
                    val, note = None, ("no business case uploaded" if transcript else "no transcript")
                else:
                    val, note = round(cla["cues"][cue], 4), "whole-take value (transcript is not time-aligned)"
            elif col == "tx_val":
                val = None if tx_val is None else round(float(np.clip(tx_val, -1, 1)), 4)
                note = "whole-take transcript sentiment (not time-aligned)" if tx_val is not None else "no transcript"
            else:
                val = _cell(_z(f.get(col), WS.get(col)))
            c = dict(step=step, cue=cue, value=val, vs=vs)
            if note:
                c["note"] = note
            cells.append(c)
        moments.append(dict(t_start=round(a / FEATURE_SR, 2), t_end=round(b / FEATURE_SR, 2), grid=cells))

    # ---- summary row: chunk-level judges vs baseline ----
    CS = baseline["chunk_stats"]
    rows = _chunk_feats(y)
    zrows = [{c: _z(r.get(c), CS.get(c)) for c in CHUNK_COLS} for r in rows]
    eng_cues = [float(np.clip(np.nanmean([zr[c] for zr in zrows]) / 2, -1, 1)) for c in ENG_COLS]
    eng_cues = [v for v in eng_cues if np.isfinite(v)] or [0.0]
    eng = float(np.mean(eng_cues)); eng_conf = float(np.mean(np.sign(eng_cues) == np.sign(eng)))
    pa, pa_voice, ja = _judges("arousal", zrows, tx_val)
    pv, pv_voice, jv = _judges("valence", zrows, tx_val)
    summary = {
        "engagement": dict(score=round(eng, 3), confidence=round(eng_conf, 3), vs="baseline", provisional=True,
                           note="heuristic: mean of loudness, activity rate, voiced ratio vs baseline; no engagement labels yet",
                           cues=dict(zip(["loudness", "speech_activity_rate", "voiced_ratio"], [round(v, 3) for v in eng_cues]))),
        "arousal": dict(score=round(2 * pa - 1, 3), confidence=round(abs(2 * pa - 1), 3), vs="baseline",
                        p_high=round(pa, 3), judges=ja),
        "valence": dict(score=round(2 * pv - 1, 3), confidence=round(abs(2 * pv - 1), 3), vs="baseline+reference",
                        p_positive=round(pv, 3), voice_part=round(2 * pv_voice - 1, 3),
                        words_part=None if tx_val is None else round(tx_val, 3), judges=jv),
        "clarity": (dict(score=None, confidence=0.0, vs="reference",
                         note="no business case uploaded" if transcript else "no transcript", provisional=True)
                    if cla is None else
                    dict(score=round(cla["score"], 3), confidence=round(cla["confidence"], 3), vs="reference", provisional=True,
                         cues={k: round(v, 3) for k, v in cla["cues"].items()}, raw=cla["raw"],
                         note="embedding similarity to the business case + filler words; uncalibrated")),
    }
    # ---- gate: first step in ORDER that isn't clear enough; later steps are locked (score withheld) ----
    checks = [("engagement", eng >= T["engagement_score_min"], f"engagement too low vs your baseline (score < {T['engagement_score_min']})"),
              ("arousal", summary["arousal"]["confidence"] >= T["arousal_conf_min"], f"arousal not clear enough (confidence < {T['arousal_conf_min']})"),
              ("valence", summary["valence"]["confidence"] >= T["valence_conf_min"], f"valence not clear enough (confidence < {T['valence_conf_min']})"),
              ("clarity", summary["clarity"]["score"] is not None and summary["clarity"]["confidence"] >= T["clarity_conf_min"],
               "no business case / reference to score clarity against" if summary["clarity"]["score"] is None
               else f"answer too short to judge clarity (confidence < {T['clarity_conf_min']})")]
    gate = None
    for step, ok, why in checks:
        if not ok:
            gate = dict(step=step, reason=why); break
    for k, step in enumerate(ORDER):
        locked = gate is not None and k > ORDER.index(gate["step"])
        summary[step]["unlocked"] = not locked
        if locked:
            summary[step]["score_if_unlocked"] = summary[step]["score"]; summary[step]["score"] = None
    take = dict(take_id=take_id or str(uuid.uuid4()), prompt_tag=prompt_tag, duration_s=round(dur, 2),
                transcript=transcript, order=ORDER, moments=moments, summary=summary, gate=gate,
                processing_s=round(time.perf_counter() - t0, 2))
    return dict(schema=SCHEMA, package_version=__version__, value_range=[-1, 1],
                value_scaling="cell value = clip(z / 2, -1, 1), z vs the speaker's calm baseline windows (vs=baseline) "
                              "or a fixed scale (vs=reference); +1 = 2 SD above own calm voice",
                thresholds=T, provisional=PROVISIONAL, takes=[take])
