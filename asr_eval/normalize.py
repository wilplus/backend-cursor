"""Token normalization for ASR comparison.

The comparison space, never anything shown to anyone. Mirrors
``services.take_alignment._tokens`` (lowercase, punctuation stripped,
apostrophes kept) so the eval measures words the same way the production
aligner does — a harness that tokenizes differently from the code it is
gating measures the wrong thing.

TWO NORMALIZATIONS, ON PURPOSE
------------------------------
``strip_fillers=False`` (verbatim) is willab's real target: the disfluent
prompt in ``openai_service.transcribe_audio`` exists to make Whisper KEEP
"um"/"uh"/"i mean", because filler density feeds candidate generation and
L1 says the selected slide text is the actual take verbatim. A model that
tidies disfluencies away is a REGRESSION for this product even though it
scores better on conventional WER.

``strip_fillers=True`` is DISFLUENCY-INSENSITIVE WER, not "accuracy". Read
the caveat: ``utils.filler_words`` lists tokens that are also ordinary
content words ("like", "so", "right", "actually", Polish "no"/"nie",
German "ja"). Stripping them removes real content along with the
disfluencies, so this number is only meaningful as a COMPANION to the
verbatim one. The gap between the two is the signal worth reading — a wide
gap means the provider is editorializing the speaker's disfluencies.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

# Same class as services.take_alignment._WORD_RE — word chars + apostrophe.
_WORD_RE = re.compile(r"[\w']+", re.UNICODE)

# Curly apostrophes/primes are a real cross-provider difference ("don't" vs
# "don’t"): whisper-1 and the gpt-4o-* transcribe family punctuate
# differently, and left unnormalized that alone registers as substitutions.
_APOSTROPHES = dict.fromkeys(map(ord, "‘’ʼ′"), "'")

_DEFAULT_LANG = "en"

# Cache: the filler lists are static, and _filler_phrases is called once per
# transcript per metric.
_PHRASE_CACHE: dict[str, tuple] = {}


def _filler_phrases(language: Any) -> tuple:
    """``(single_tokens, multi_word_phrases)`` for a language.

    Reuses ``utils.filler_words.get_filler_list`` so the eval's idea of a
    filler is the production one. Multi-word entries ("you know", "i mean")
    are kept as PHRASES — stripping their words individually would delete
    every standalone "know"/"mean"/"i", which is a content edit, not a
    disfluency strip. Returns empty sets if the module is unavailable, which
    makes filler-stripping a no-op rather than a wrong answer.
    """
    code = (str(language or _DEFAULT_LANG).strip().lower() or _DEFAULT_LANG)[:2]
    hit = _PHRASE_CACHE.get(code)
    if hit is not None:
        return hit
    try:
        from utils.filler_words import get_filler_list  # type: ignore

        raw = get_filler_list(code) or []
    except Exception:
        raw = []
    singles, phrases = set(), []
    for f in raw:
        parts = _WORD_RE.findall(str(f).lower())
        if len(parts) == 1:
            singles.add(parts[0])
        elif len(parts) > 1:
            phrases.append(tuple(parts))
    # Longest phrases first so "you know" wins over any prefix of it.
    phrases.sort(key=len, reverse=True)
    out = (frozenset(singles), tuple(phrases))
    _PHRASE_CACHE[code] = out
    return out


def _strip_filler_indices(toks: list, language: Any) -> list:
    """Indices of ``toks`` that survive filler-stripping, in order. Pure.

    Phrase pass first (longest-first, non-overlapping), then singles. Works
    on indices rather than values so callers holding parallel timing data
    can drop the same positions.
    """
    singles, phrases = _filler_phrases(language)
    if not singles and not phrases:
        return list(range(len(toks)))
    n = len(toks)
    dead = [False] * n
    for phrase in phrases:
        k = len(phrase)
        for i in range(n - k + 1):
            if dead[i]:
                continue
            if tuple(toks[i:i + k]) == phrase and not any(dead[i:i + k]):
                for j in range(i, i + k):
                    dead[j] = True
    return [i for i in range(n) if not dead[i] and toks[i] not in singles]


def normalize_text(text: Any) -> str:
    """NFKC + unified apostrophes + lowercase. Pure."""
    if not isinstance(text, str):
        return ""
    return unicodedata.normalize("NFKC", text).translate(_APOSTROPHES).lower()


def tokens(text: Any, *, strip_fillers: bool = False,
           language: Any = None) -> list:
    """Normalized comparison tokens for a transcript string. Pure.

    Never raises on malformed input — a provider that returns None or a dict
    where a string was expected yields [], which the metrics then score as
    total loss rather than as a silent perfect match.
    """
    norm = normalize_text(text)
    if not norm:
        return []
    toks = _WORD_RE.findall(norm)
    if not strip_fillers:
        return toks
    return [toks[i] for i in _strip_filler_indices(toks, language)]


def word_tokens(words: Any, *, strip_fillers: bool = False,
                language: Any = None) -> list:
    """Normalize a word-timestamp list into ``[{token, start, end}]``.

    Input is the ``[{word, start, end}]`` shape
    ``openai_service.transcribe_audio`` returns (SECONDS, absolute to the
    recording — the same frame as slide tap times). One input word can
    normalize to zero tokens (bare punctuation) or to several ("well—okay");
    the timing is carried onto each resulting token, because sub-word timing
    is not available and splitting the interval would invent precision the
    provider never gave us.

    Sorted by start time. Words with a missing or non-finite start are
    dropped: they cannot be bucketed to a slide, so they cannot be scored.
    """
    flat: list = []
    for w in (words or []):
        if not isinstance(w, dict):
            continue
        st = w.get("start")
        if not isinstance(st, (int, float)) or isinstance(st, bool):
            continue
        st = float(st)
        if st != st or st in (float("inf"), float("-inf")):  # NaN / ±inf
            continue
        en = w.get("end")
        en = (float(en) if isinstance(en, (int, float))
              and not isinstance(en, bool) else st)
        if en != en or en in (float("inf"), float("-inf")):
            en = st
        for tok in _WORD_RE.findall(normalize_text(w.get("word"))):
            flat.append({"token": tok, "start": st, "end": en})
    flat.sort(key=lambda t: t["start"])
    if not strip_fillers or not flat:
        return flat
    keep = _strip_filler_indices([t["token"] for t in flat], language)
    return [flat[i] for i in keep]
