"""Inferred learner profile — Phase 3 of the snippet-CTA learning loop.

Problem
-------
After Phases 2 + 8 the system collects an LLM score, three component
sub-scores (specificity / emotional_movement / engagement), and an
optional 1..10 user self-rating on every coaching attempt. Nothing yet
synthesises those rows back into a "who is this learner today"
signal. The coaching turn endpoint still ships the same generic
system prompt to everyone, only augmented by admin-set custom
instructions and the classifier's behavioral_profile.

This module aggregates the user's most recent N attempts into a
deterministic JSONB blob and writes it onto user_settings. The
augment_coaching_system_prompt path then folds the blob's traits
into the [USER LONG-TERM PROFILE] block, so the AI can say things
like "this user's weakest dimension is specificity — push for a
concrete moment" without an extra LLM call to summarise the history.

Why deterministic (not LLM)
---------------------------
Two reasons:
  1. Cost — recomputing a profile on every attempt write would
     burn LLM tokens for no real upside; the underlying signals are
     all numeric.
  2. Auditability — admins need to read why the coach is treating a
     student a certain way. A JSON blob with a fixed schema is
     greppable; a free-text LLM summary is not.

If we ever want a narrative summary on top, that can be a Phase 9-ish
follow-up: cache the narrative separately and key it off the
deterministic blob's content hash.

Recompute trigger
-----------------
Today: invoked synchronously from services.coaching_outcomes.
_persist_outcome immediately after a successful coaching_attempts
insert. The blob query is cheap (LIMIT N ORDER BY created_at DESC on
an indexed table) and the user is one HTTP request away from the next
coaching turn — staleness would be user-visible.

If recompute latency becomes a problem, push it onto the same daemon
thread that runs the LLM evaluation: the eligibility for few-shot is
already async, the profile can ride that same path.

Sample size
-----------
We don't inject the profile until the user has ``MIN_ATTEMPTS_TO_INJECT``
attempts on file. Below that threshold the trait estimates are too
noisy to justify changing the AI's behaviour. Compute the blob
anyway so admins can see it forming in the diagnostic endpoint, but
the injection layer skips it.
"""
from __future__ import annotations

import logging
import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Sequence


logger = logging.getLogger(__name__)


# Phase 4 — how many top-frequency entities to surface per category
# in the inferred profile. We keep the cap small so the prompt
# augmenter can include all of them without dominating the system
# prompt; admins can still see the raw per-attempt entities via
# /coaching/progress.
RECURRING_ENTITIES_TOP_N = 5
# An entity needs to show up across at least this many attempts in
# the window before it counts as "recurring" — a one-time mention
# isn't a pattern worth telling the coach about.
RECURRING_ENTITY_MIN_COUNT = 2


# Rolling window of attempts we look at when computing the profile.
# 10 strikes a balance between picking up recent change ("this user
# improved over the last 3 attempts") and keeping the average
# resistant to one-off lucky / bad attempts.
ATTEMPTS_WINDOW = 10

# Below this sample size we treat trait estimates as too noisy to
# inject into the coaching prompt. We still STORE the blob — admins
# can read it — but the augmenter skips it.
MIN_ATTEMPTS_TO_INJECT = 3

# Score-trend thresholds (per attempt slope). Anything within ±0.02
# per attempt is "flat" — a 10-attempt swing that small (< 0.20 total)
# is within the LLM evaluator's own noise floor.
_TREND_DELTA = 0.02

_COMPONENTS = ("specificity", "emotional_movement", "engagement")


def compute_learner_profile(attempts: Sequence[dict]) -> dict[str, Any] | None:
    """Aggregate a user's recent coaching_attempts into a profile blob.

    ``attempts`` is expected to be ordered newest-first (the same
    shape db.list_recent_coaching_attempts_for_user returns). We
    re-sort by attempt_number ASC internally for trend computation,
    so the caller's ordering doesn't matter for correctness.

    Returns the profile dict, or None when ``attempts`` is empty —
    callers should leave the column NULL in that case rather than
    write a zero-valued blob.
    """
    if not attempts:
        return None

    window = list(attempts)[:ATTEMPTS_WINDOW]
    scored = [a for a in window if _is_number(a.get("score"))]
    n = len(scored)
    if n == 0:
        # Attempts exist but none have an LLM score yet. Possible on
        # legacy backfilled rows where the JSONB was malformed. Skip.
        return None

    scores = [float(a["score"]) for a in scored]
    score_average = statistics.fmean(scores)

    components_avg: dict[str, float] = {}
    for key in _COMPONENTS:
        vals = [
            float((a.get("components") or {}).get(key))
            for a in scored
            if _is_number((a.get("components") or {}).get(key))
        ]
        if vals:
            components_avg[key] = statistics.fmean(vals)

    weakest = (
        min(components_avg, key=components_avg.get)
        if components_avg else None
    )
    strongest = (
        max(components_avg, key=components_avg.get)
        if components_avg else None
    )

    # Score trend. Sort by attempt_number ASC then fit a tiny linear
    # slope (Δscore / Δattempt). With only 3–10 points a least-
    # squares slope is plenty precise and dependency-free.
    trend = _score_trend(scored)

    # Self-rating aggregates — only over attempts that actually
    # carry one. We don't penalise users who skipped the rating ask.
    self_ratings = [
        int(a["self_rating"]) for a in window
        if _is_number(a.get("self_rating"))
        and 1 <= int(a["self_rating"]) <= 10
    ]
    self_rating_average: float | None = (
        statistics.fmean(self_ratings) if self_ratings else None
    )

    # Self-vs-LLM gap. Convert self_rating to 0..1 to compare against
    # the LLM composite. Positive = user thinks they did better than
    # the LLM scored them; negative = user is harsher than the LLM.
    gap: float | None = None
    paired: list[tuple[float, float]] = []
    for a in scored:
        if not _is_number(a.get("self_rating")):
            continue
        sr = int(a["self_rating"])
        if not (1 <= sr <= 10):
            continue
        paired.append((float(a["score"]), sr / 10.0))
    if paired:
        gap = statistics.fmean(p[1] - p[0] for p in paired)

    # Phase 4 — recurring entities. Aggregate ALL attempts in the
    # window (not just the scored ones) because entities are
    # independent of whether the LLM produced a usable score.
    recurring_entities = _aggregate_entities(window)

    return {
        "version": "v2",
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "attempts_analyzed": n,
        "traits": {
            "score_average": round(score_average, 4),
            "score_per_component": {
                k: round(v, 4) for k, v in components_avg.items()
            },
            "weakest_component": weakest,
            "strongest_component": strongest,
            "score_trend": trend,
            "self_rating_average": (
                round(self_rating_average, 2)
                if self_rating_average is not None else None
            ),
            "self_rating_gap": round(gap, 4) if gap is not None else None,
            "recurring_entities": recurring_entities,
        },
    }


def format_profile_for_prompt(profile: dict[str, Any] | None) -> str | None:
    """Render a profile blob as a few short lines for the system prompt.

    Returns None when the profile is too sparse to inject (missing,
    too few analysed attempts) — the augmenter uses this to decide
    whether to add a [LEARNER INSIGHTS] block at all.

    The output is intentionally terse: each line is one trait. Long
    paragraphs would dilute the existing custom_llm_instructions
    block and confuse the model about priority.
    """
    if not isinstance(profile, dict):
        return None
    if int(profile.get("attempts_analyzed") or 0) < MIN_ATTEMPTS_TO_INJECT:
        return None
    traits = profile.get("traits") or {}
    if not traits:
        return None

    lines: list[str] = []
    sa = traits.get("score_average")
    if _is_number(sa):
        lines.append(f"- Recent answer quality (LLM 0..1): {float(sa):.2f}")
    weakest = traits.get("weakest_component")
    strongest = traits.get("strongest_component")
    if weakest:
        lines.append(
            f"- Weakest dimension: {weakest} — emphasise this when "
            "choosing what to ask next."
        )
    if strongest and strongest != weakest:
        lines.append(f"- Strongest dimension: {strongest}.")
    trend = traits.get("score_trend")
    if trend:
        lines.append(f"- Recent trend: {trend}.")

    sr_avg = traits.get("self_rating_average")
    gap = traits.get("self_rating_gap")
    if _is_number(sr_avg):
        lines.append(f"- Average self-rating (1..10): {float(sr_avg):.1f}")
    if _is_number(gap):
        gap_f = float(gap)
        if gap_f > 0.10:
            lines.append(
                f"- Self-rating runs {gap_f:+.2f} above LLM score — user "
                "may be over-confident; press for concrete evidence."
            )
        elif gap_f < -0.10:
            lines.append(
                f"- Self-rating runs {gap_f:+.2f} below LLM score — user "
                "may be self-critical; validate before challenging."
            )

    # Phase 4 — recurring entities. The coach should reference these
    # by name when they fit naturally; we explicitly tell the model
    # NOT to force-mention them, otherwise it tends to shoehorn the
    # entity into every reply.
    recurring = traits.get("recurring_entities") or {}
    if isinstance(recurring, dict):
        entity_lines = _format_recurring_entities(recurring)
        if entity_lines:
            lines.append(
                "- Recurring entities (reference by name only when "
                "naturally relevant, don't force them):"
            )
            lines.extend(entity_lines)

    if not lines:
        return None
    return "\n".join(lines)


def _format_recurring_entities(recurring: dict[str, list[dict]]) -> list[str]:
    """Render the aggregated entities block for the system prompt.

    Returns one bullet per non-empty category. Each bullet lists up
    to 3 labels with counts ("Sarah ×4, Mom ×3"). 3 < the storage
    top-N because the prompt cares about salience rather than
    completeness — admins can read the full list via the diagnostic
    endpoint.
    """
    out: list[str] = []
    for category, label_singular in (
        ("people", "People"),
        ("situations", "Situations"),
        ("themes", "Themes"),
    ):
        items = recurring.get(category) or []
        rendered = []
        for it in items[:3]:
            if not isinstance(it, dict):
                continue
            label = (it.get("label") or "").strip()
            count = it.get("count")
            if not label or not isinstance(count, int):
                continue
            rendered.append(f"{label} ×{count}")
        if rendered:
            out.append(f"    {label_singular}: " + ", ".join(rendered))
    return out


# ── Internals ───────────────────────────────────────────────────────────────


def _aggregate_entities(window: Sequence[dict]) -> dict[str, list[dict]]:
    """Count entity occurrences across ``window`` and return the top-N per category.

    Case-normalised for counting so "Sarah" and "sarah" merge, but
    the surface form returned is the most common original spelling
    in the window (so the prompt-formatter shows the user's
    phrasing). Categories without any qualifying recurrent entries
    return empty lists — callers persist the empty shape so the
    blob is grep-able for diagnostic purposes.

    Returned shape::

        {
          "people":     [{"label": "Sarah", "count": 4}, ...],
          "situations": [{"label": "Q4 review", "count": 2}, ...],
          "themes":     [{"label": "imposter syndrome", "count": 3}, ...],
        }
    """
    counters: dict[str, Counter] = {
        "people": Counter(),
        "situations": Counter(),
        "themes": Counter(),
    }
    # surface_by_key tracks the most common original spelling per
    # lowercase key so we can render "Sarah" rather than "sarah" when
    # counts are tied — Counter.most_common breaks ties by insertion
    # order, which favours the first-seen surface form anyway.
    surface_by_key: dict[str, Counter] = {
        "people": Counter(),
        "situations": Counter(),
        "themes": Counter(),
    }
    for attempt in window:
        ents = attempt.get("entities")
        if not isinstance(ents, dict):
            continue
        for category in counters:
            seq = ents.get(category)
            if not isinstance(seq, list):
                continue
            for item in seq:
                if not isinstance(item, str):
                    continue
                v = item.strip()
                if not v:
                    continue
                key = v.lower()
                counters[category][key] += 1
                surface_by_key[category][(key, v)] += 1

    result: dict[str, list[dict]] = {}
    for category, counter in counters.items():
        top = []
        for key, count in counter.most_common(RECURRING_ENTITIES_TOP_N):
            if count < RECURRING_ENTITY_MIN_COUNT:
                continue
            # Pick the surface form most often used for this key.
            surface_counts = {
                surf: c for (k, surf), c in surface_by_key[category].items()
                if k == key
            }
            label = max(surface_counts, key=surface_counts.get) if surface_counts else key
            top.append({"label": label, "count": count})
        result[category] = top
    return result


def _is_number(v: Any) -> bool:
    """True when ``v`` can be coerced to float and isn't bool/None."""
    if v is None or isinstance(v, bool):
        return False
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


def _score_trend(scored: Sequence[dict]) -> str:
    """Classify the score trajectory across ``scored`` attempts.

    Uses a small least-squares slope on (attempt_number, score). With
    < 3 paired points we can't say anything meaningful — return "flat".
    """
    points: list[tuple[float, float]] = []
    for a in scored:
        n = a.get("attempt_number")
        s = a.get("score")
        if not _is_number(n) or not _is_number(s):
            continue
        points.append((float(n), float(s)))
    if len(points) < 3:
        return "flat"

    n = len(points)
    sum_x = sum(p[0] for p in points)
    sum_y = sum(p[1] for p in points)
    sum_xy = sum(p[0] * p[1] for p in points)
    sum_xx = sum(p[0] * p[0] for p in points)
    denom = n * sum_xx - sum_x * sum_x
    if denom == 0:
        return "flat"
    slope = (n * sum_xy - sum_x * sum_y) / denom
    if slope > _TREND_DELTA:
        return "improving"
    if slope < -_TREND_DELTA:
        return "declining"
    return "flat"
