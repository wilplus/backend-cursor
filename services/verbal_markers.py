"""Verbal markers — three lexicons split by EPISTEMIC DIRECTION (SPEC D21).

Companion: SPEC.md v3 D20 (Beta-Binomial estimation), D21 (the three-way
split), Appendix F.4 (D8, hedge/booster window).

WHY THREE LEXICONS AND NOT ONE. `utils/filler_words.py` mixes disfluencies,
hedges and boosters into a single "filler" list. Hedges LOWER stated certainty
and boosters RAISE it, so summing them cancels the signal — a speaker who
hedges ten times and boosts ten times reads identical to one who does neither.
Split by what the marker does to certainty:

    HEDGE    lowers    "sort of", "I think", "maybe"      -> CUT or REPLACE
    BOOSTER  raises    "clearly", "definitely"            -> no intervention
    TIC      neither   "um", "basically", "literally"     -> CUT

THE ASSIGNMENT THAT DEVIATES FROM THE LITERATURE, DELIBERATELY. Hyland's
booster list includes `actually` and `in fact`. That holds for academic
WRITING, where they carry real emphatic force. In speech they are usually
BLEACHED — semantically empty tics. Counting a nervous speaker's verbal tics
as *raised* certainty is backwards, so per D21 `actually`, `basically` and
`literally` are TIC here. This is a deliberate departure and it is the sort of
thing that must be visible, not silent.

THE AMBIGUITY PROBLEM, WHICH IS THE REAL LIMIT ON THIS FILE. Several markers
have legitimate non-marker uses that a regex cannot distinguish:

    "I *like* it"          vs  "it was *like* really good"
    "*so* that we can"     vs  "*so*, the next point"
    "you were *right*"     vs  "*right*, moving on"
    "it *could* be"        vs  "*could* you pass"

Counting every occurrence inflates the rate, in some cases by multiples.
Disambiguating needs POS tagging or context, which this module does NOT do.
So every ambiguous term is FLAGGED, and `count()` reports the two totals
separately. A caller that ignores the flag gets an upper bound, not a rate —
and the gap between the two numbers is itself the finding.

Pure: no DB, no I/O, unit-tested.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

HEDGE = "hedge"
BOOSTER = "booster"
TIC = "tic"
CLASSES = (HEDGE, BOOSTER, TIC)

# Direction on stated certainty. TIC is 0.0 by definition — a bleached marker
# says nothing about how sure the speaker is, which is exactly why folding it
# in with boosters (as the flat filler list did) corrupts the signal.
DIRECTION = {HEDGE: -1.0, BOOSTER: 1.0, TIC: 0.0}


# ── the lexicons ────────────────────────────────────────────────────────────
#
# Each entry: term -> ambiguous?   True means the surface form has a common
# NON-marker use that no regex can rule out. See the module docstring.

_HEDGE_EN: dict[str, bool] = {
    # unambiguous hedging phrases
    "sort of": False, "kind of": False, "i think": False, "i guess": False,
    "i suppose": False, "i believe": False, "or something": False,
    "or whatever": False, "more or less": False, "a little bit": False,
    "not really sure": False, "if i remember": False, "to be honest": False,
    "in a way": False, "sort of like": False,
    "maybe": False, "perhaps": False, "possibly": False, "probably": False,
    "apparently": False, "presumably": False, "arguably": False,
    "roughly": False, "approximately": False, "somewhat": False,
    "seemingly": False, "supposedly": False,
    # epistemic verbs / adjectives (Hyland)
    "seems": False, "appears": False, "suggests": False, "tends to": False,
    "unlikely": False, "unclear": False, "uncertain": False,
    "plausible": False, "likely": False,
    # AMBIGUOUS — modals and adverbs with heavy non-hedge use
    "might": True, "may": True, "could": True, "would": True,
    "should": True, "quite": True, "rather": True, "fairly": True,
    "generally": True, "usually": True, "often": True, "sometimes": True,
    "about": True, "almost": True, "pretty": True,
}

_BOOSTER_EN: dict[str, bool] = {
    "definitely": False, "certainly": False, "clearly": False,
    "obviously": False, "undoubtedly": False, "absolutely": False,
    "of course": False, "without doubt": False, "no doubt": False,
    "in fact": False, "indeed": False, "surely": False, "truly": False,
    "evidently": False, "unquestionably": False, "decidedly": False,
    "i'm certain": False, "i'm sure": False, "there is no question": False,
    # AMBIGUOUS
    "must": True, "always": True, "never": True, "clear": True,
    "obvious": True, "sure": True, "prove": True, "show": True,
}

_TIC_EN: dict[str, bool] = {
    # unambiguous disfluencies — safe to regex
    "um": False, "uh": False, "erm": False, "uhm": False, "mmm": False,
    "hmm": False, "er": False, "ah": False,
    # bleached intensifiers. D21: these are TIC, not BOOSTER (see docstring).
    "basically": False, "literally": False,
    # AMBIGUOUS — every one of these has a common legitimate use
    "actually": True, "like": True, "you know": True, "i mean": True,
    "right": True, "so": True, "well": True, "just": True,
    "obviously": True,
}

LEXICONS: dict[str, dict[str, dict[str, bool]]] = {
    "en": {HEDGE: _HEDGE_EN, BOOSTER: _BOOSTER_EN, TIC: _TIC_EN},
}

DEFAULT_LANGUAGE = "en"


def lexicon(marker_class: str, language: Optional[str] = None) -> dict[str, bool]:
    """The term -> ambiguous map for one class. Empty dict for an unknown
    class or an unsupported language — refusing to count beats counting the
    wrong list."""
    lang = (language or DEFAULT_LANGUAGE).strip().lower()[:2]
    return LEXICONS.get(lang, LEXICONS[DEFAULT_LANGUAGE]).get(marker_class, {})


def supported_languages() -> tuple[str, ...]:
    return tuple(sorted(LEXICONS))


# ── counting ────────────────────────────────────────────────────────────────

_WORD_RE = re.compile(r"[a-z']+")
_PUNCT_RE = re.compile(r"[^\w\s']+")


def word_count(text: Any) -> int:
    """Tokens, for the denominator. Appendix F.3: the denominator is the field
    most easily got wrong and the error is silent, so it is computed here once
    rather than by each caller."""
    if not isinstance(text, str):
        return 0
    return len(_WORD_RE.findall(text.lower()))


def count(text: Any, *, language: Optional[str] = None) -> dict:
    """Count markers by class in one text.

    Returns::

        {
          "n_words": int,
          "hedge":   {"strict": int, "ambiguous": int, "total": int,
                      "terms": {term: n}},
          "booster": {...},
          "tic":     {...},
        }

    `strict` counts only terms with NO common non-marker use. `ambiguous` adds
    the rest. **`total` is an upper bound, not a rate** — "like", "so",
    "right" and the modals cannot be disambiguated without POS tagging, which
    this module does not do. Use `strict` for anything that feeds a threshold
    and treat the gap between the two as a measure of how much the ambiguity
    is costing you.
    """
    out: dict[str, Any] = {"n_words": word_count(text)}
    for cls in CLASSES:
        out[cls] = {"strict": 0, "ambiguous": 0, "total": 0, "terms": {}}
    if not isinstance(text, str) or not text.strip():
        return out

    normalised = _PUNCT_RE.sub(" ", text.lower())
    normalised = re.sub(r"\s+", " ", normalised)

    for cls in CLASSES:
        bucket = out[cls]
        for term, is_ambiguous in lexicon(cls, language).items():
            pattern = r"\b" + re.escape(term) + r"\b"
            n = len(re.findall(pattern, normalised))
            if not n:
                continue
            bucket["terms"][term] = n
            if is_ambiguous:
                bucket["ambiguous"] += n
            else:
                bucket["strict"] += n
        bucket["total"] = bucket["strict"] + bucket["ambiguous"]
    return out


# ── D20: Beta-Binomial estimation ───────────────────────────────────────────
#
# Replaces the fixed-window ratio behind an N_min gate. A short window yields a
# WIDE posterior that simply never crosses the firing threshold, so there is no
# INSUFFICIENT_DATA cliff — and the bias is toward the corpus mean, i.e. toward
# UNDER-firing, which is the correct error direction when the span IS the
# intervention.


def fit_prior(rates: Iterable[float], *,
              min_n: int = 5) -> Optional[tuple[float, float]]:
    """Method-of-moments Beta prior from per-document rates.

    Returns ``(alpha, beta)`` or None when there is too little to fit. The
    prior strength ``alpha + beta`` encodes overdispersion: bursty markers
    (a nervous speaker clusters them) give a WEAKER prior, so a single passage
    moves the posterior less.
    """
    values = [float(r) for r in rates
              if isinstance(r, (int, float)) and 0.0 <= float(r) <= 1.0]
    n = len(values)
    if n < min_n:
        return None
    mean = sum(values) / n
    if mean <= 0.0 or mean >= 1.0:
        return None
    var = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    max_var = mean * (1.0 - mean)
    if var <= 0.0 or var >= max_var:
        # Degenerate: no spread, or spread at/above the binomial maximum.
        # Fall back to a weak prior centred on the mean rather than inventing
        # a precision the data does not support.
        strength = 2.0
        return mean * strength, (1.0 - mean) * strength
    strength = max_var / var - 1.0
    return mean * strength, (1.0 - mean) * strength


def posterior(count_marks: int, n_words: int,
              prior: Optional[tuple[float, float]]) -> Optional[dict]:
    """Beta-Binomial posterior for one passage.

    ``{"mean": float, "alpha": float, "beta": float, "sd": float}`` or None.
    With no prior this degenerates to the raw ratio and says so by returning a
    wide sd — it does not pretend to precision it has not got.
    """
    if n_words <= 0 or count_marks < 0 or count_marks > n_words:
        return None
    a0, b0 = prior if prior else (0.5, 0.5)      # Jeffreys when unfitted
    a = a0 + count_marks
    b = b0 + (n_words - count_marks)
    total = a + b
    mean = a / total
    var = (a * b) / (total * total * (total + 1.0))
    return {"mean": mean, "alpha": a, "beta": b, "sd": var ** 0.5}


def dispersion(counts: Iterable[tuple[int, int]]) -> Optional[float]:
    """Overdispersion factor phi from (marks, words) pairs.

    phi = observed variance / binomial variance. phi = 1 means independent
    occurrence; phi > 1 means BURSTY, which markers are — a speaker who wobbles
    clusters them in one passage rather than sprinkling them evenly.

    Why it matters: plain binomial assumes independence and therefore
    UNDERSTATES the standard error. phi is the multiplier that corrects it,
    and at phi = 2 the window needed for a given precision doubles.
    """
    pairs = [(int(m), int(w)) for m, w in counts
             if isinstance(m, int) and isinstance(w, int) and w > 0 and 0 <= m <= w]
    if len(pairs) < 2:
        return None
    total_marks = sum(m for m, _ in pairs)
    total_words = sum(w for _, w in pairs)
    if total_words <= 0 or total_marks <= 0:
        return None
    p = total_marks / total_words
    if p <= 0.0 or p >= 1.0:
        return None
    # Pearson chi-square dispersion, the standard estimator.
    chi2 = sum(((m - w * p) ** 2) / (w * p * (1.0 - p)) for m, w in pairs)
    dof = len(pairs) - 1
    return chi2 / dof if dof > 0 else None


def window_for_precision(rate: float, *, relative_precision: float = 0.30,
                         phi: float = 1.0) -> Optional[int]:
    """Words needed to estimate `rate` to `relative_precision`.

        N = phi * (1 - r) / (rho^2 * r)

    This is a SIZING heuristic, not the estimator — D20 uses the posterior
    above, which has no cliff. It exists to answer "is this dimension even
    measurable on a passage, or only on a whole talk?"
    """
    if not (0.0 < rate < 1.0) or relative_precision <= 0 or phi <= 0:
        return None
    return int(round(phi * (1.0 - rate) / (relative_precision ** 2 * rate)))
