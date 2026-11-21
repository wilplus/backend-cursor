"""Clarity vs the uploaded business case: a simple, explainable CPU reference score. PROVISIONAL, uncalibrated."""
import re
import numpy as np
from . import models

# Polish (and a few English) filler words / hesitations
FILLERS = {"yyy", "yy", "eee", "ee", "eh", "ehm", "hmm", "mmm", "yyyy", "eeee", "um", "uh", "jakby", "generalnie",
           "znaczy", "właściwie", "wlasciwie", "no", "tak jakby", "w sumie", "po prostu", "że tak powiem", "kurczę"}
SIM_THRESHOLD = 0.5  # a business-case sentence counts as "covered" if some transcript sentence is this similar


def split_sentences(text: str) -> list:
    parts = re.split(r"(?<=[.!?…;])\s+|\n+", text or "")
    return [p.strip() for p in parts if len(p.strip().split()) >= 2] or ([text.strip()] if text and text.strip() else [])


def filler_rate(text: str) -> float:
    """Fillers per 100 words."""
    t = (text or "").lower()
    words = re.findall(r"\w+", t)
    if not words:
        return 0.0
    n = sum(1 for w in words if w in FILLERS)
    for ph in (f for f in FILLERS if " " in f):
        n += len(re.findall(r"\b" + re.escape(ph) + r"\b", t))
    return 100.0 * n / len(words)


def score(transcript: str, business_case: str) -> dict:
    ts, bs = split_sentences(transcript), split_sentences(business_case)
    n_words = len(re.findall(r"\w+", transcript or ""))
    if not ts or not bs:
        return dict(score=None, confidence=0.0, cues={}, n_words=n_words)
    et, eb = models.embed(ts), models.embed(bs)
    sim_whole = float(np.dot(et.mean(0) / np.linalg.norm(et.mean(0)), eb.mean(0) / np.linalg.norm(eb.mean(0))))
    coverage = float(((et @ eb.T).max(0) >= SIM_THRESHOLD).mean())
    fr = filler_rate(transcript)
    cues = {
        "business_case_coverage": float(np.clip(2 * coverage - 1, -1, 1)),       # 0% -> -1, 50% -> 0, 100% -> +1
        "semantic_similarity": float(np.clip((sim_whole - 0.35) / 0.3, -1, 1)),  # cosine 0.35 -> 0, 0.65 -> +1
        "filler_word_rate": float(np.clip(1 - fr / 5.0, -1, 1)),                 # 0/100 words -> +1, 5 -> 0, 10+ -> -1
    }
    return dict(score=float(np.mean(list(cues.values()))), confidence=float(min(1.0, n_words / 60.0)), cues=cues,
                raw=dict(coverage=round(coverage, 3), cosine=round(sim_whole, 3), fillers_per_100_words=round(fr, 2),
                         business_case_sentences=len(bs)), n_words=n_words)
