"""The one list of learning surfaces, and which of them carry packets.

EIGHT SURFACES, SEVEN PACKETS (founder 2026-09-29, decision 2; audit G-5,
the 29 Sep report's item Q7). The registry ``ml_learning_surfaces`` has held
eight rows since 0313 inserted ``exercise_adequacy_classification``, while
three Python sets, the dataset-release CHECKs (0300), the readiness report
(0301) and three tests went on saying seven. Nothing was wrong on purpose and
nothing said so, so the eighth read as forgotten.

Module 8 is different by design, and this is the one place that says how:

* it never gets a seven-surface presentation packet or exposure receipt
  (0299 stays at seven). An exercise is shown as a card, and its exposure is
  recorded once per frozen 80/20 assignment when the speaker's client
  confirms the card rendered (``confident_voice_exercise_exposures``, 0387);
* its label is the practice outcome (``exercise-adequacy-label-v1``,
  ``practice_more_confident_outcomes``), never a speaker's or a coach's
  answer about the exercise;
* its readiness is its own bar, 300 first-exposure attempts with a valid
  endpoint and 30 per exercise (``services/exercise_learning_readiness.py``),
  and the eight-surface readiness report reads its row from the exercise
  tables, not from packets and receipts (0395).

Every module that enumerates learning surfaces imports from here, so the
next surface cannot be added in one place and forgotten in three.
"""
from __future__ import annotations

#: The eighth surface, and the only one without a presentation packet.
EXERCISE_ADEQUACY_SURFACE = "exercise_adequacy_classification"

#: The registry, in registry order (0302 seeded the first seven, 0313 the
#: eighth). Ordered so the readiness report's positions and this list agree.
LEARNING_SURFACE_ORDER: tuple[str, ...] = (
    "confidence_classification",
    "correction_generation",
    "coach_comment_generation",
    "praise_generation",
    "praise_selection",
    "correction_selection",
    "ideal_text_generation",
    EXERCISE_ADEQUACY_SURFACE,
)

#: All eight canonical learning surfaces.
LEARNING_SURFACES: frozenset[str] = frozenset(LEARNING_SURFACE_ORDER)

#: The seven that carry a frozen presentation packet and a visible-render
#: receipt (0299). Module 8 is exposed through its own table instead.
PACKET_SURFACES: frozenset[str] = LEARNING_SURFACES - {
    EXERCISE_ADEQUACY_SURFACE,
}

#: Why ``prepare_presentation`` refuses module 8, in the words it raises.
NO_PACKET_REASON = (
    "exercise_adequacy_classification has no presentation packet: an "
    "exercise card's exposure is recorded per assignment in "
    "confident_voice_exercise_exposures (0387) and its label is the practice "
    "outcome"
)
