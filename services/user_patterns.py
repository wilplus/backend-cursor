"""Engine 4 — per-user acoustic patterns (founder 2026-07-11). Deterministic
v1, pure code, no LLM.

Mines the user's coach-labeled moments — POSITIVE (challenge-labeled /
strong-tagged) **and** NEGATIVE (threat-labeled / to_work_on-tagged, founder:
"the good ones and also the bad ones") — against their NEUTRAL moments, and
emits qualitative pattern statements through fixed templates, e.g. "a
longer-than-usual pause tends to come right before your strongest moments".

FENCES: AC-9 — statements are qualitative, never a number, and always
self-referential (this speaker vs themselves, never a population claim).
BLIND COACH — only coach labels/tags define the classes; shadow guesses are
never read here. Honest silence: thin data (< _MIN_CLASS_N moments in a
class, or no meaningful delta) → no statement at all.

Primary consumer: the game engine's "Here is why" section (Engine 5).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# metric key aliases (same normalization family as say_it_stronger).
_FEATURES = {
    "pace": ("wpm", "speech_rate"),
    "pausing": ("pause_ratio",),
    "pitch_variety": ("f0_sd",),
    "energy": ("dynamic_db", "loudness_range"),
}

_MIN_CLASS_N = 5      # a class needs at least this many moments to be judged
_MIN_REL_DELTA = 0.25 # relative delta vs neutral mean before a claim is made
_MAX_STATEMENTS = 4   # strongest 2 positive + 2 negative
_MAX_SESSIONS = 30    # bound the cross-session scan

# Fixed qualitative templates — (feature, higher_than_neutral?, kind).
_TEMPLATES = {
    ("pausing", True, "positive"): (
        "A longer-than-usual pause tends to come right before your "
        "strongest moments — silence is working for you."
    ),
    ("pausing", False, "positive"): (
        "Your strongest moments tend to ride shorter pauses than usual — "
        "you carry them on momentum."
    ),
    ("pausing", True, "negative"): (
        "The moments flagged to work on tend to come with more pausing "
        "than usual — hesitation creeps in."
    ),
    ("pausing", False, "negative"): (
        "You tend to rush through the moments flagged to work on, leaving "
        "less silence than usual."
    ),
    ("pace", True, "positive"): (
        "Your strongest moments tend to run a touch faster than your "
        "usual pace — energy carries them."
    ),
    ("pace", False, "positive"): (
        "Your strongest moments tend to be slower than your usual pace — "
        "you let them land."
    ),
    ("pace", True, "negative"): (
        "You tend to speed up around the moments flagged to work on."
    ),
    ("pace", False, "negative"): (
        "You tend to slow down and lose drive around the moments flagged "
        "to work on."
    ),
    ("pitch_variety", True, "positive"): (
        "Your voice moves more than usual in your strongest moments — the "
        "extra rise and fall is part of what makes them land."
    ),
    ("pitch_variety", False, "positive"): (
        "Your strongest moments come out steadier and flatter than usual — "
        "calm authority seems to be your mode."
    ),
    ("pitch_variety", True, "negative"): (
        "Your voice gets more restless than usual in the moments flagged "
        "to work on."
    ),
    ("pitch_variety", False, "negative"): (
        "Your voice flattens out in the moments flagged to work on."
    ),
    ("energy", True, "positive"): (
        "You bring noticeably more vocal energy to your strongest moments."
    ),
    ("energy", False, "positive"): (
        "Your strongest moments are quieter and more contained than your "
        "usual delivery."
    ),
    ("energy", True, "negative"): (
        "The moments flagged to work on tend to come out louder and more "
        "pushed than your usual delivery."
    ),
    ("energy", False, "negative"): (
        "Your energy drops in the moments flagged to work on."
    ),
}


def _feature_value(metrics: Any, aliases: tuple) -> Optional[float]:
    m = metrics if isinstance(metrics, dict) else {}
    for a in aliases:
        v = m.get(a)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return float(v)
    return None


def classify_moment(verdict: Any) -> str:
    """positive | negative | neutral — from the SETTLED confidence verdict.

    `verdict` is one value out of `key_moments.confidence_verdicts`: "yes",
    "no", "ambiguous", or None/absent when the panel has not settled. Only a
    settled panel classifies; everything else is neutral, which here means "we
    have nothing to say", not "average".

    RE-POINTED 2026-08-14 (founder). It used to take `(coach_label, coach_tag)`
    and read `challenge`/`strong` → positive, `threat`/`to_work_on` → negative.
    THREE of those four inputs were unusable. challenge/threat is the retired
    charisma construct and its coach control was deleted 2026-08-07, so it has
    been frozen ever since; `strong` was never chosen by anyone (the FE
    defaulted it whenever a note was typed), so "positive" fired on the coach
    having WRITTEN something. Patterns mined from that were reporting what the
    coach commented on, dressed as what the speaker does well. The confidence
    quorum is the one thing a coach actually judges, and it is defined (§17
    `conf-q-v1`) and multi-rater (label ledger rule 3).

    Blind-coach fence unchanged: `resolve()` counts human QUORUM_LANES only, so
    a shadow guess still cannot classify anything here. Pure."""
    v = verdict.strip().lower() if isinstance(verdict, str) else ""
    if v == "yes":
        return "positive"
    if v == "no":
        return "negative"
    # "ambiguous" lands here on purpose: a panel that settled on "we cannot
    # tell" is a real finding about the moment, and the honest thing to mine
    # from it is nothing.
    return "neutral"


def mine_patterns(moments: Any) -> list:
    """``moments`` = [{"metrics": {...}, "cls": "positive|negative|neutral"}].
    Returns [{kind, feature, statement}] — at most _MAX_STATEMENTS, strongest
    first per kind. [] when data is thin (honest silence). Pure."""
    by_cls: dict = {"positive": [], "negative": [], "neutral": []}
    for m in moments if isinstance(moments, list) else []:
        if isinstance(m, dict) and m.get("cls") in by_cls:
            by_cls[m["cls"]].append(m.get("metrics"))

    if len(by_cls["neutral"]) < _MIN_CLASS_N:
        return []  # no baseline → no claims

    def _mean(rows, aliases):
        vals = [v for v in (_feature_value(r, aliases) for r in rows)
                if v is not None]
        return (sum(vals) / len(vals), len(vals)) if vals else (None, 0)

    out: list = []
    for kind in ("positive", "negative"):
        if len(by_cls[kind]) < _MIN_CLASS_N:
            continue
        scored: list = []
        for feature, aliases in _FEATURES.items():
            n_mean, n_n = _mean(by_cls["neutral"], aliases)
            c_mean, c_n = _mean(by_cls[kind], aliases)
            if n_mean is None or c_mean is None or not n_mean:
                continue
            if n_n < _MIN_CLASS_N or c_n < _MIN_CLASS_N:
                continue
            rel = (c_mean - n_mean) / abs(n_mean)
            if abs(rel) < _MIN_REL_DELTA:
                continue
            stmt = _TEMPLATES.get((feature, rel > 0, kind))
            if stmt:
                scored.append((abs(rel), {
                    "kind": kind, "feature": feature, "statement": stmt,
                }))
        scored.sort(key=lambda t: t[0], reverse=True)
        out.extend(s for _, s in scored[:2])
    return out[:_MAX_STATEMENTS]


def build_user_patterns(user_id: Any, database=None) -> list:
    """Gather the user's coach-labeled moments across their lab sessions and
    mine the patterns. Best-effort — [] on any failure / thin data."""
    if not user_id:
        return []
    try:
        if database is None:
            from services.db import db as database
        sessions = (database.v2_list_user_lab_sessions(
            str(user_id), limit=_MAX_SESSIONS) or [])
        moments: list = []
        for sess in sessions:
            sid = sess.get("id")
            if not sid:
                continue
            snippets = (database.get_snippets_by_session(sid) or [])
            from services.key_moments import confidence_verdicts
            verdicts = confidence_verdicts(
                database, [s.get("id") for s in snippets])
            for s in snippets:
                snip_id = str(s.get("id"))
                moments.append({
                    "metrics": s.get("metrics"),
                    "cls": classify_moment(verdicts.get(snip_id)),
                })
        return mine_patterns(moments)
    except Exception as e:
        logger.warning("user_patterns: build failed user=%s: %s", user_id, e)
        return []
