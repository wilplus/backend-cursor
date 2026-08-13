"""Challenge-threat lane (willab Prompt D) — NOW A CORPUS LANE ONLY.

⚠️ THIS MODULE NO LONGER TOUCHES RANKING. Founder decision 2026-08-13 retired
the charisma construct from the north star and SPEC §7.2 re-pointed
``power_score`` onto ``confidence`` (``conf-q-v1``): the ``direction`` term
(``_W_D``) is gone, and ``_W_B`` now fires on the album quorum rather than on a
coach ``challenge`` mark. ``is_challenge`` moved to
services/moment_confidence.py as ``is_confident`` and changed construct with
the move. Nothing here feeds services/power_phrase_ranking.py any more.

WHAT SURVIVES, AND WHY IT WAS NOT DELETED WITH THE REST. ``training_labels``
holds real coach labels in the challenge/threat vocabulary, and they are the
corpus the shadow classifier is fitted on. SPEC §3.2 is explicit that the
wording IS the construct — changing it starts a NEW corpus and a new version
key, never an edit in place — and the founder's standing rule on detector
definitions says the same thing in stronger terms: never silently overwrite
labels, lexicons or historical calculations. Re-pointing this vocabulary is
therefore a DATA decision about an existing corpus, not a code cleanup, and it
is deliberately left for its own call.

Two pure pieces remain, both corpus-side:
  • resolve_direction — the COACH's blind label wins; else the SHADOW model's
    prediction (Phase 4 / Prompt 1). The shadow label is NEVER shown to the
    coach — the coach labels independently and the system learns from the diff.
  • detect_breakthroughs — the coach-confirmed marks behind the breakthrough
    BADGE surfaces (services/best_presentation.build_arc_breakthroughs, the
    lab_recording insights layer). A breakthrough = a coach ``challenge`` mark
    (founder 2026-06-26). The earlier threat→challenge-transition rule is
    RETIRED — see the function.
"""
from __future__ import annotations

from typing import Any, Optional

VALID_DIRECTIONS = ("threat", "ambiguous", "challenge")


def resolve_direction(
    coach_label: Any, shadow_label: Any = None,
    *, shadow_confidence: Any = None, min_confidence: Any = None,
) -> Optional[str]:
    """The snippet's direction: the COACH's label (training_labels, blind) when
    valid, else the SHADOW prediction, else None. Pure — the caller fetches both
    (the coach label from training_labels, the shadow label from
    learning_serve.predict_direction(features)["label"]).

    GRADUATED AUTONOMY (readiness rig #3, default-OFF): when ``min_confidence`` is
    set, the shadow fallback is used ONLY if ``shadow_confidence >=
    min_confidence`` — below the floor the snippet gets NO direction (None)
    rather than a low-confidence guess. That routes low-confidence cases to the
    human (no machine direction term) and high-confidence to the machine.
    ``min_confidence=None`` (the default) → no gating, identical to before. The
    COACH label is never gated — it always wins."""
    if coach_label in VALID_DIRECTIONS:
        return coach_label
    if shadow_label in VALID_DIRECTIONS:
        if min_confidence is not None:
            try:
                if (shadow_confidence is None
                        or float(shadow_confidence) < float(min_confidence)):
                    return None
            except (TypeError, ValueError):
                return None
        return shadow_label
    return None


def detect_breakthroughs(snippets: Any) -> set:
    """Return the set of snippet ids that are coach-confirmed BREAKTHROUGHS.

    BREAKTHROUGH = a coach ``challenge`` mark (founder 2026-06-26). The coach's
    challenge mark in the panel IS the breakthrough mark — so every snippet the
    coach labelled ``challenge`` is a breakthrough.

    The earlier threat→challenge-TRANSITION rule is RETIRED: it required a coach
    ``threat`` immediately before the ``challenge`` in the same take, so a coach
    who marked a single ``challenge`` (no preceding threat) saw NO breakthrough
    surface anywhere — the reported "I chose one and it wasn't shown" bug.

    ``snippets`` = list of dicts with ``id`` and ``direction`` (callers still
    pass ``start_offset_ms``; it's accepted and ignored — order no longer
    matters without the latch). The coach-only gate lives at the call sites
    (``coach_direction``), so no model guess ever reaches this set.
    """
    if not isinstance(snippets, list):
        return set()
    return {
        s.get("id")
        for s in snippets
        if isinstance(s, dict) and s.get("direction") == "challenge"
    }
