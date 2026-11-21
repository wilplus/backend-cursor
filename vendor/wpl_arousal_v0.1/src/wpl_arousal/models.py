"""Lazy, cached loaders for the pretrained models (downloaded once into the Hugging Face cache).
Set HF_HOME (or WPL_AROUSAL_CACHE) to choose the cache folder; set HF_HUB_OFFLINE=1 after the first download."""
import os, threading
import numpy as np

# Pinned revisions (the exact snapshots used in Step 2)
WAVLM_ID, WAVLM_REV = "3loi/SER-Odyssey-Baseline-WavLM-Multi-Attributes", "00d0e12ba9bf957f5aeea36e8663c8c61cb50ac9"
HERBERT_ID, HERBERT_REV = "Voicelab/herbert-base-cased-sentiment", "ca028e48c7bae75f348e1d2a04d7a7beafb800cd"
EMB_ID, EMB_REV = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2", "e8f8c211226b894fcb81acc59f3b34ba3efd5f42"

_lock = threading.Lock()
_cache = {}


def _cache_dir():
    return os.environ.get("WPL_AROUSAL_CACHE")  # None -> default HF cache (HF_HOME)


def _torch():
    import torch
    n = int(os.environ.get("WPL_AROUSAL_THREADS", "0") or 0)
    if n > 0:
        torch.set_num_threads(n)
    return torch


def wavlm():
    """3loi WavLM (MSP-Podcast) -> arousal, dominance, valence. Uses trust_remote_code at a pinned revision."""
    with _lock:
        if "wavlm" not in _cache:
            from transformers import AutoModelForAudioClassification
            _cache["wavlm"] = AutoModelForAudioClassification.from_pretrained(
                WAVLM_ID, revision=WAVLM_REV, trust_remote_code=True, cache_dir=_cache_dir()).eval()
        return _cache["wavlm"]


def wavlm_scores(y16: np.ndarray) -> dict:
    """y16: mono float32 at 16 kHz."""
    torch = _torch(); m = wavlm()
    x = torch.tensor((y16 - m.config.mean) / (m.config.std + 1e-6), dtype=torch.float32).unsqueeze(0)
    with torch.no_grad():
        p = m(x, torch.ones(1, x.shape[1]))[0].numpy()
    p = np.asarray(p).reshape(-1)
    return dict(wl_aro=float(p[0]), wl_dom=float(p[1]), wl_val=float(p[2]))


def herbert():
    with _lock:
        if "herbert" not in _cache:
            from transformers import AutoTokenizer, AutoModelForSequenceClassification
            tok = AutoTokenizer.from_pretrained(HERBERT_ID, revision=HERBERT_REV, cache_dir=_cache_dir())
            m = AutoModelForSequenceClassification.from_pretrained(HERBERT_ID, revision=HERBERT_REV, cache_dir=_cache_dir()).eval()
            _cache["herbert"] = (tok, m)
        return _cache["herbert"]


def text_sentiment(sentences: list) -> float:
    """Polish sentiment on a fixed scale: P(positive) - P(negative), length-weighted over sentences. -1..+1."""
    torch = _torch(); tok, m = herbert()
    with torch.no_grad():
        pr = torch.softmax(m(**tok(sentences, padding=True, truncation=True, max_length=256, return_tensors="pt")).logits, -1).numpy()
    w = np.array([max(len(s.split()), 1) for s in sentences], dtype=float)
    return float(np.average(pr[:, 2] - pr[:, 0], weights=w))


def embedder():
    with _lock:
        if "emb" not in _cache:
            from transformers import AutoTokenizer, AutoModel
            tok = AutoTokenizer.from_pretrained(EMB_ID, revision=EMB_REV, cache_dir=_cache_dir())
            m = AutoModel.from_pretrained(EMB_ID, revision=EMB_REV, cache_dir=_cache_dir()).eval()
            _cache["emb"] = (tok, m)
        return _cache["emb"]


def embed(texts: list) -> np.ndarray:
    """Mean-pooled, L2-normalised multilingual sentence embeddings."""
    torch = _torch(); tok, m = embedder()
    with torch.no_grad():
        b = tok(texts, padding=True, truncation=True, max_length=256, return_tensors="pt")
        h = m(**b).last_hidden_state
        mask = b["attention_mask"].unsqueeze(-1).float()
        e = (h * mask).sum(1) / mask.sum(1).clamp(min=1e-9)
        e = torch.nn.functional.normalize(e, dim=-1)
    return e.numpy()


def warmup(text=True, clarity=True):
    """Optional: load (and download) everything up front, e.g. at server start."""
    wavlm()
    if text:
        herbert()
    if clarity:
        embedder()
